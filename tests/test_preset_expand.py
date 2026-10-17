"""A named preset expanded INTO the plan at build time,
and written by `apply` from the plan.

The design is the maintainer's, 2026-09-21: `build` resolves the
preset into the plan as values carrying their provenance, so the plan says
exactly what will be written; the plan always wins over the preset, and
says so; and the merge is BY ADDRESS, so a preset value and a plan value
for the same parameter are one resolved value -- the plan's -- rather than
two writes whose order decides the outcome.

Everything here runs against `tests/fixtures/` -- a checked-in copy of a
real plan and five real `.chn` exports -- never a bundle under
`examples/` (a bundle there is a living example).
"""

from __future__ import annotations

import collections
import copy
import json
import os
import sys
from pathlib import Path

import pytest

from atoo import plan_compat
from atoo import apply as apply_module
from atoo import console_facts as facts
from atoo import preset_expand
from atoo.apply import STAGE_PROCESSING, _build_write_targets, apply_plan
from atoo.cli import main
from atoo.plan_schema import GENERATION_SCHEMA, PLAN_SCHEMA
from atoo.presets import PresetLibrary, _classify, load_preset
from atoo.schema_check import validate
from atoo.verify_plan import verify_plan

sys.path.insert(0, str(Path(__file__).parent))
from test_apply import FakeConsole  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
LIBRARY_DIR = FIXTURES / "presets"
KICK_CHN = LIBRARY_DIR / "Kick.chn"
REAL_PLANS = json.loads((FIXTURES / "real_plans.json").read_text())
PARAMETER_MAP = Path(__file__).parents[1] / "docs" / "reference" / "wing-compact-parameter-map.json"

# What a preset must never write, as addresses under a strip. FR-X.4a.
FORBIDDEN_PREFIXES = ("send/", "main/", "in/conn/", "preins/", "postins/")
FORBIDDEN_EXACT = {"fdr", "mute", "tags", "name", "col", "icon", "pan", "wid", "clink",
                   "in/set/trim", "in/set/bal", "in/set/inv", "in/set/$g", "in/set/$vph"}


@pytest.fixture
def library() -> PresetLibrary:
    return PresetLibrary(LIBRARY_DIR)


def plan_naming(*presets, **processing) -> dict:
    """The fixture touringband plan, its first channels naming these
    presets; `processing` is merged into channel 1's processing."""
    plan = copy.deepcopy(plan_compat.normalise_plan(REAL_PLANS["touringband"]))
    for channel, name in zip(plan["channels"], presets):
        channel["processing"]["preset"] = name
    plan["channels"][0]["processing"].update(processing)
    return plan


def kick(plan: dict) -> dict:
    return plan["channels"][0]


def codes(findings) -> list[str]:
    return [f.code for f in findings]


# ---------------------------------------------------------------------------
# expansion: by address, into the plan
# ---------------------------------------------------------------------------


def test_expansion_puts_the_preset_into_the_plan_keyed_by_address(library):
    plan = plan_naming("Kick In", hpf_hz=None)
    preset_expand.expand_plan(plan, library)
    values = kick(plan)["processing"]["preset_values"]

    assert values["preset"] == "Kick In"
    assert values["file"] == "Kick.chn"
    assert values["sha256"] == preset_expand.file_sha256(KICK_CHN)
    # Every in-scope leaf of the file, at the address it is written to --
    # nothing overridden here because the channel states no processing.
    source = load_preset(KICK_CHN).parameters
    assert set(values["leaves"]) == {leaf.replace(".", "/") for leaf in source}
    assert values["leaves"]["eq/2g"] == pytest.approx(-10.10000038)
    assert values["leaves"]["in/set/dly"] == pytest.approx(0.5)
    # ...already in the type the desk takes: an on/off is an int, a knob a
    # float even when the file wrote a whole number, a list choice a string.
    assert values["leaves"]["gate/on"] == 1 and type(values["leaves"]["gate/on"]) is int
    assert values["leaves"]["eq/3g"] == 0.0 and type(values["leaves"]["eq/3g"]) is float
    assert values["leaves"]["dyn/ratio"] == "5.0"      # the desk's own token for 5
    assert values["overridden"] == {}
    assert validate(plan, PLAN_SCHEMA) == []


def test_expansion_is_idempotent_and_recomputed_rather_than_trusted(library):
    plan = plan_naming("Kick In")
    preset_expand.expand_plan(plan, library)
    once = copy.deepcopy(plan)
    preset_expand.expand_plan(plan, library)
    assert plan == once
    # A value nobody resolved (a model, a hand edit) does not survive a
    # rebuild: build recomputes the key for every channel.
    kick(plan)["processing"]["preset"] = None
    preset_expand.expand_plan(plan, library)
    assert "preset_values" not in kick(plan)["processing"]


def test_selectors_are_written_before_values_and_switches_last(tmp_path):
    """A compressor threshold means different things under different
    `dyn.mdl`; a gate switched in before its threshold gates at the old
    one. So: models and modes first, on-switches last -- whatever order
    the file happens to list them in (here: deliberately the wrong one)."""
    doc = json.loads(KICK_CHN.read_text())
    for section in ("dyn", "gate"):
        node = doc["ch_data"][section]
        doc["ch_data"][section] = {"on": node["on"], "thr": node["thr"],
                                   **{k: v for k, v in node.items() if k not in ("on", "thr")}}
    doc["ch_data"]["in"]["set"] = dict(reversed(list(doc["ch_data"]["in"]["set"].items())))
    (tmp_path / "kick.chn").write_text(json.dumps(doc))
    plan = plan_naming("Kick In", hpf_hz=None)
    preset_expand.expand_plan(plan, PresetLibrary(tmp_path))
    order = list(kick(plan)["processing"]["preset_values"]["leaves"])
    assert order.index("dyn/mdl") < order.index("dyn/thr")
    assert order.index("in/set/dlymode") < order.index("in/set/dly")
    assert order.index("gate/thr") < order.index("gate/on")
    targets, _ = _build_write_targets(plan, True)
    ch1 = [t.address for t in targets if t.address.startswith("/ch/1/") and t.stage == STAGE_PROCESSING]
    assert ch1.index("/ch/1/dyn/mdl") < ch1.index("/ch/1/dyn/thr") < ch1.index("/ch/1/dyn/on")


def test_an_aux_strip_carries_only_the_nodes_an_aux_strip_has(library):
    plan = plan_naming("Kick In", hpf_hz=None)
    kick(plan)["bank"] = "aux"
    findings = preset_expand.expand_plan(plan, library)
    leaves = kick(plan)["processing"]["preset_values"]["leaves"]
    assert not [a for a in leaves if a.split("/")[0] in ("flt", "peq", "gate", "gatesc", "dynxo")]
    assert "eq/1g" in leaves and "dyn/thr" in leaves and "in/set/dly" in leaves
    assert "preset.leaf-not-on-strip" in codes(findings)


# ---------------------------------------------------------------------------
# the plan wins, and says so
# ---------------------------------------------------------------------------


def test_the_plan_wins_over_the_preset_and_says_so_at_info(library):
    plan = plan_naming("Kick In", hpf_hz=80,
                       eq={"on": None, "bands": [{"band": "1", "gain_db": 3.0}]})
    findings = preset_expand.expand_plan(plan, library)
    values = kick(plan)["processing"]["preset_values"]

    # The addresses the plan's own processing writes are not in `leaves`
    # at all -- one value per address, the plan's...
    for address in ("flt/lc", "flt/lcf", "eq/1g", "eq/on"):
        assert address not in values["leaves"], address
        assert address in values["overridden"], address
    assert values["overridden"]["flt/lcf"] == pytest.approx(40.19342422)
    # ...and the override is said out loud, naming the address and both values.
    note = next(f for f in findings if f.code == "preset.overridden")
    assert note.severity == "info"
    assert "flt/lcf preset 40.19342422 -> plan 80.0" in note.message
    assert "eq/1g preset -5.5 -> plan 3.0" in note.message

    targets, _ = _build_write_targets(plan, True)
    by_address = {t.address: t.compute_value(None) for t in targets}
    assert by_address["/ch/1/flt/lcf"] == 80.0
    assert by_address["/ch/1/eq/1g"] == 3.0
    assert by_address["/ch/1/eq/2g"] == pytest.approx(-10.10000038)   # the preset's


def test_an_address_where_plan_and_preset_agree_is_not_called_an_override(library):
    """"flt/lc 1 (both agree)" was in every one of sixpiece's
    22 `preset.overridden` notes. Where the plan states the value the
    preset already has, nothing was decided, so it is not counted or said
    -- it is still recorded in `preset_values.overridden`."""
    plan = plan_naming("Kick In", hpf_hz=80)
    findings = preset_expand.expand_plan(plan, library)
    values = kick(plan)["processing"]["preset_values"]
    # The HPF switch: on in the preset, on in the plan -- recorded, not said.
    assert "flt/lc" in values["overridden"]
    note = next(f for f in findings if f.code == "preset.overridden")
    assert "both agree" not in note.message
    assert "flt/lc " not in note.message
    assert "flt/lcf preset 40.19342422 -> plan 80.0" in note.message
    assert "wins at 1 address(es)" in note.message


def test_build_write_targets_never_returns_the_same_address_twice(library):
    """The requirement recorded: with presets and explicit
    processing on the same strip, `_build_write_targets` returns each
    address once. Also true of a HAND-EDITED plan whose preset_values
    still holds an address the plan's own processing writes."""
    plan = plan_naming("Kick In", "Snare", "H Tom", hpf_hz=80, hi_cut_hz=12000,
                       eq={"on": True, "bands": [{"band": "1", "gain_db": 3.0},
                                                 {"band": "high", "shape": "SHV"}]},
                       presend_eq={"on": True, "bands": [{"band": "2", "gain_db": -2.0}]})
    preset_expand.expand_plan(plan, library)
    kick(plan)["processing"]["preset_values"]["leaves"]["flt/lcf"] = 37.9   # hand edit
    kick(plan)["processing"]["preset_values"]["leaves"]["eq/1g"] = -5.5

    targets, _ = _build_write_targets(plan, True)
    counts = collections.Counter(t.address for t in targets)
    assert [a for a, n in counts.items() if n > 1] == []
    written = {t.address: t.compute_value(None) for t in targets}
    assert written["/ch/1/flt/lcf"] == 80.0 and written["/ch/1/eq/1g"] == 3.0
    # Not vacuous: all three strips really do carry preset writes.
    for n in (1, 2, 3):
        assert f"/ch/{n}/dyn/thr" in written


# ---------------------------------------------------------------------------
# processing only -- FR-X.4a, asserted directly
# ---------------------------------------------------------------------------


def _forbidden(address: str) -> bool:
    return address.startswith(FORBIDDEN_PREFIXES) or address in FORBIDDEN_EXACT


def test_a_real_preset_file_carries_routing_and_none_of_it_reaches_the_plan(library):
    raw = json.loads(KICK_CHN.read_text())["ch_data"]
    assert raw["send"] and raw["main"] and "fdr" in raw and "tags" in raw   # the file HAS them
    plan = plan_naming("Kick In")
    preset_expand.expand_plan(plan, library)
    leaves = kick(plan)["processing"]["preset_values"]["leaves"]
    assert not [a for a in leaves if _forbidden(a)]
    assert all(_classify(preset_expand.address_leaf(a)) == "in_scope" for a in leaves)


def test_apply_never_writes_a_forbidden_leaf_even_from_a_hand_edited_plan(library):
    plan = plan_naming("Kick In")
    preset_expand.expand_plan(plan, library)
    smuggled = {"send/1/on": 1, "send/1/lvl": 0.0, "main/1/on": 1, "fdr": 0.0, "mute": 0,
                "in/conn/grp": "A", "in/conn/in": 5, "tags": "#D1", "in/set/trim": 6.0,
                "in/set/$vph": 1, "name": "Evil"}
    kick(plan)["processing"]["preset_values"]["leaves"].update(smuggled)

    targets, warnings = _build_write_targets(plan, True)
    preset_targets = [t for t in targets if ": preset " in t.description]
    assert preset_targets, "the legitimate preset leaves are still written"
    assert not [t for t in preset_targets if _forbidden(t.address[len("/ch/1/"):])]
    for address in smuggled:
        # Refused by the ALLOW-LIST, by name -- not merely by the accident
        # of having no entry in the type table.
        assert any(f"value at {address} not written -- not on the preset allow-list" in w
                   for w in warnings), address
    # And verify says so before apply ever runs.
    result = verify_plan(plan, presets=library)
    refused = next(f for f in result.findings if f.code == "preset.leaf-not-written")
    assert refused.severity == "warning"
    assert f"{len(smuggled)} of the preset" in refused.message


def test_no_allowed_leaf_is_on_the_forbidden_list():
    """The type table is the other door in: nothing on it may be routing."""
    assert not [leaf for leaf in preset_expand.LEAF_TYPES
                if _forbidden(preset_expand.leaf_address(leaf))
                or _classify(leaf) != "in_scope"]


# ---------------------------------------------------------------------------
# old plans still load, verify and apply
# ---------------------------------------------------------------------------


def test_a_plan_that_only_names_a_preset_still_validates_verifies_and_applies(library):
    plan = plan_naming("Kick In")               # no preset_values: an older plan
    assert validate(plan, PLAN_SCHEMA) == []
    result = verify_plan(plan, presets=library, console_model="wing-compact")
    assert not [f for f in result.errors if f.code.startswith("preset.")]
    assert [f.code for f in result.findings if f.code.startswith("preset.")] == ["preset.not-expanded"]

    targets, warnings = _build_write_targets(plan, True)
    assert not [t for t in targets if ": preset " in t.description]
    assert any("carries none of its values" in w and "nothing from that preset is written" in w
               for w in warnings)
    # The retired message is gone.
    assert not [w for w in warnings if "not implemented" in w]


def test_a_plan_naming_no_preset_builds_exactly_the_targets_it_did(library):
    """Expansion is a no-op for a plan that names none: same targets."""
    plan = plan_naming()
    before = [(t.address, t.value_type, t.compute_value(None)) for t in _build_write_targets(plan, True)[0]]
    preset_expand.expand_plan(plan, library)
    after = [(t.address, t.value_type, t.compute_value(None)) for t in _build_write_targets(plan, True)[0]]
    assert before == after
    assert not [c for c in plan["channels"] if "preset_values" in c["processing"]]


def test_the_model_is_never_asked_for_preset_values():
    """The values come from a file the model never sees; the generation
    schema has no such field, and a plan on disk may."""
    plan = plan_naming("Kick In")
    kick(plan)["processing"]["preset_values"] = {"preset": "Kick In", "leaves": {"eq/1g": 1.0}}
    assert validate(plan, PLAN_SCHEMA) == []
    assert any("preset_values" in e for e in validate(plan, GENERATION_SCHEMA))


# ---------------------------------------------------------------------------
# verify, on the expanded plan
# ---------------------------------------------------------------------------


def test_verify_reports_what_an_expanded_plan_will_write(library):
    plan = plan_naming("Kick In", "Snare")
    preset_expand.expand_plan(plan, library)
    result = verify_plan(plan, presets=library)
    preset = [f for f in result.findings if f.code.startswith("preset.")]
    assert [f.code for f in preset if f.severity != "info"] == []
    summary = next(f for f in preset if f.code == "preset.expanded")
    assert "2 channel(s)" in summary.message and "Kick In" in summary.message

    # Self-contained: with no library configured, nothing is missing.
    offline = verify_plan(plan, presets=None)
    assert not [f for f in offline.findings if f.code == "preset.no-library"]


def test_verify_notices_a_name_edited_without_re_expanding(library):
    plan = plan_naming("Kick In")
    preset_expand.expand_plan(plan, library)
    kick(plan)["processing"]["preset"] = "Snare"
    result = verify_plan(plan, presets=library)
    stale = next(f for f in result.findings if f.code == "preset.stale-expansion")
    assert stale.severity == "warning"
    assert "'Kick In'" in stale.message and "'Snare'" in stale.message


def test_verify_notices_the_library_copy_changed_since_the_build(library, tmp_path):
    for chn in LIBRARY_DIR.glob("*.chn"):
        (tmp_path / chn.name).write_bytes(chn.read_bytes())
    moved = PresetLibrary(tmp_path)
    plan = plan_naming("Kick In")
    preset_expand.expand_plan(plan, moved)
    doc = json.loads((tmp_path / "Kick.chn").read_text())
    doc["ch_data"]["dyn"]["thr"] = -30
    (tmp_path / "Kick.chn").write_text(json.dumps(doc))
    result = verify_plan(plan, presets=moved)
    changed = next(f for f in result.findings if f.code == "preset.library-changed")
    assert changed.severity == "info"
    # The plan is what is written, not the library.
    assert kick(plan)["processing"]["preset_values"]["leaves"]["dyn/thr"] == -20.0


# ---------------------------------------------------------------------------
# apply: written at the processing stage, and read back
# ---------------------------------------------------------------------------


class TypedDesk(FakeConsole):
    """A FakeConsole that stores every leaf in the type the WING describes
    it with (preset_expand.LEAF_TYPES), the way a desk would -- so a write
    that carried the wrong type tag would read back as the wrong thing."""

    def set_node(self, address, command):
        key, _, _ = command.partition("=")
        spec = preset_expand.leaf_type(f"{address}/{key}".split("/", 3)[-1])
        full = f"{address}/{key}"
        if spec is not None and full not in self.state:
            self.state[full] = (None, spec.osc)
        return super().set_node(address, command)


def _desk_for(plan: dict) -> TypedDesk:
    """Every address the plan writes, seeded with a value that differs from
    the plan's -- so each preset write is really made -- and typed, for a
    `/ch/1/...` processing leaf, the way the console's OWN parameter map
    describes it rather than the way the code under test does."""
    if not PARAMETER_MAP.exists():
        pytest.skip("needs docs/reference/wing-compact-parameter-map.json, which this tree does not have")
    schema = json.loads(PARAMETER_MAP.read_text())["schema"]
    state = {}
    for target in _build_write_targets(plan, True)[0]:
        value_type = target.value_type
        if target.address.startswith("/ch/1/"):
            section, _, key = target.address[len("/ch/1/"):].rpartition("/")
            entry = schema.get(f"/ch/{{n}}/{section}.{key}")
            if entry is not None:
                (value_type,) = _map_osc(entry)
        placeholder = {"i": -1, "f": -99.0, "s": "placeholder"}[value_type]
        state[target.address] = (placeholder, value_type)
    return TypedDesk(state=state)


def test_apply_writes_the_preset_at_the_processing_stage_and_reads_every_value_back(library, tmp_path):
    plan = plan_naming("Kick In", hpf_hz=80)
    preset_expand.expand_plan(plan, library)
    leaves = kick(plan)["processing"]["preset_values"]["leaves"]

    targets, _ = _build_write_targets(plan, True)
    preset_targets = {t.address: t for t in targets if ": preset " in t.description}
    assert set(preset_targets) == {f"/ch/1/{a}" for a in leaves}
    assert {t.stage for t in preset_targets.values()} == {STAGE_PROCESSING}
    for address, target in preset_targets.items():
        assert target.value_type == preset_expand.leaf_type(address[len("/ch/1/"):]).osc

    journal = tmp_path / "j.json"
    result = apply_plan(plan, _desk_for(plan), dry_run=False, journal_path=str(journal))
    records = {w.address: w for w in result.writes if w.address in preset_targets}
    assert set(records) == set(preset_targets)
    assert {w.status for w in records.values()} == {"match"}
    assert all(w.readback_value is not None for w in records.values())
    # Journalled with its type, so undo can put every one of them back.
    logged = {w["address"]: w for w in json.loads(journal.read_text())["writes"]}
    assert logged["/ch/1/dyn/ratio"]["value_type"] == "s"
    assert logged["/ch/1/dyn/ratio"]["intended_value"] == "5.0"


def test_a_desk_that_spells_a_numeric_list_choice_differently_still_matches():
    """`dyn.ratio` 5 and the desk's "5.0" are one choice; a name is still
    compared exactly."""
    assert apply_module._values_equal("s", "5", "5.0")
    assert not apply_module._values_equal("s", "5", "6.0")
    assert not apply_module._values_equal("s", "Kick", "kick")
    assert not apply_module._values_equal("s", "1:4", "1:4.0")


# ---------------------------------------------------------------------------
# the type table and its evidence
# ---------------------------------------------------------------------------


def _map_osc(entry: dict) -> set[str]:
    variants = entry.get("variants") or [entry]
    return {{"int": "i", "lin": "f", "log": "f", "list": "s"}[v["type"]] for v in variants}


def test_the_type_table_agrees_with_the_consoles_own_parameter_map():
    """Every entry the map describes is typed as the map types it, and
    every entry the map does NOT describe is recorded as unconfirmed."""
    if not PARAMETER_MAP.exists():
        pytest.skip("needs docs/reference/wing-compact-parameter-map.json, which this tree does not have")
    schema = json.loads(PARAMETER_MAP.read_text())["schema"]
    for leaf, spec in preset_expand.LEAF_TYPES.items():
        section, _, key = leaf.rpartition(".")
        ch = schema.get(f"/ch/{{n}}/{section.replace('.', '/')}.{key}")
        aux = schema.get(f"/aux/{{n}}/{section.replace('.', '/')}.{key}")
        if ch is None:
            assert not spec.confirmed, leaf
            continue
        assert _map_osc(ch) == {spec.osc}, leaf
        assert ("aux" in spec.banks) == (aux is not None) or leaf in ("dyn.in", "dyn.out"), leaf


def test_every_leaf_any_fixture_preset_carries_has_a_type():
    for chn in list(LIBRARY_DIR.glob("*.chn")) + list((FIXTURES / "channel_presets").glob("*.chn")):
        for leaf in load_preset(chn).parameters:
            assert leaf in preset_expand.LEAF_TYPES, (chn.name, leaf)


def test_the_unconfirmed_entries_are_exactly_the_ones_the_evidence_leaves_open():
    unconfirmed = sorted(leaf for leaf, spec in preset_expand.LEAF_TYPES.items() if not spec.confirmed)
    assert unconfirmed == ["dyn.ratio", "gate.col", "gate.drv", "gate.hrm", "gate.trim", "gate.wmix"]


@pytest.mark.parametrize("address, raw, expected", [
    ("eq/on", True, 1), ("flt/lc", False, 0), ("dyn/knee", 3, 3),
    ("eq/3g", 0, 0.0), ("in/set/dly", 0.5, 0.5),
    ("dyn/ratio", 5, "5.0"), ("dyn/ratio", 2.5, "2.5"), ("dyn/ratio", "4:1", "4:1"),
    ("flt/lcs", 24, "24"), ("gate/ratio", "1:4", "1:4"),
])
def test_values_are_put_in_the_type_the_desk_takes(address, raw, expected):
    value, why = preset_expand.coerce_value(address, raw)
    assert why is None and value == expected and type(value) is type(expected)


def test_a_value_that_cannot_be_typed_honestly_is_refused_not_guessed():
    assert preset_expand.coerce_value("eq/1g", "loud")[0] is None
    assert preset_expand.coerce_value("eq/on", 0.5)[0] is None
    assert preset_expand.coerce_value("nosuch/leaf", 1)[0] is None


# ---------------------------------------------------------------------------
# patch, release, the CLI and the page
# ---------------------------------------------------------------------------


def test_a_channel_a_patch_adds_gets_the_same_expansion(library):
    from atoo import patch
    base = copy.deepcopy(REAL_PLANS["touringband"])
    newcomer = copy.deepcopy(base["channels"][0])
    newcomer.update(channel=30, name="Kick 2", dca=[], mute_group=[], bus_sends=[], main_routes=[])
    newcomer["source"]["input"] = "Kick 2"
    newcomer["patch"] = {"group": "A", "sockets": [30], "stated": True}
    newcomer["processing"].update(preset="Kick In", hpf_hz=None)
    change_set = patch.empty_change_set("second kick")
    change_set["add"]["channels"].append(newcomer)
    change_set = patch.validate_change_set(change_set)
    merge = patch.merge_change(base, change_set, console_model="wing-compact", presets=library)
    added = next(c for c in merge.plan["channels"] if c["name"] == "Kick 2")
    assert added["processing"]["preset_values"]["leaves"]["dyn/thr"] == -20.0
    assert any("puts 83 processing values into the change" in i for i in merge.infos), merge.infos
    # The channels already on the desk are the base's, untouched.
    assert [c for c in merge.plan["channels"] if c["name"] != "Kick 2"] == base["channels"]


def test_returning_a_preset_strip_to_free_clears_its_compressor_and_gate(library):
    plan = plan_naming("Kick In")
    preset_expand.expand_plan(plan, library)
    warnings: list[str] = []
    targets = apply_module.release_write_targets([kick(plan)], console_model="wing-compact",
                                                 warnings=warnings)
    cleared = {t.address: t.compute_value(None) for t in targets}
    assert cleared["/ch/1/dyn/mdl"] == "COMP"
    assert cleared["/ch/1/dyn/thr"] == -10.0
    assert cleared["/ch/1/gate/on"] == 0
    assert not [w for w in warnings if "cannot return" in w and "/ch/1/" in w]
    order = list(cleared)
    assert order.index("/ch/1/dyn/mdl") < order.index("/ch/1/dyn/thr")
    assert facts.factory_strip_processing("dyn/mdl", "aux") == "GATE"
    assert facts.factory_strip_processing("dyn/knee", "aux") is facts.NO_FACTORY_READING


def test_presets_expand_writes_the_plan_and_then_says_it_is_up_to_date(tmp_path, capsys):
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan_naming("Kick In", "Nope")))
    assert main(["presets", "--presets", str(LIBRARY_DIR), "--expand", str(source)]) == 0
    out = capsys.readouterr()
    assert "1 channel(s) carry preset values" in out.out
    assert "preset.overridden" in out.err            # touringband's Kick states an 80Hz HPF
    written = json.loads(source.read_text())
    assert written["channels"][0]["processing"]["preset_values"]["preset"] == "Kick In"
    assert "preset_values" not in written["channels"][1]["processing"]

    assert main(["presets", "--presets", str(LIBRARY_DIR), "--expand", str(source)]) == 0
    assert "already up to date" in capsys.readouterr().out


def test_build_expands_presets_before_verifying(stub_build, tmp_path, capsys):
    plan = stub_build("touringband")
    plan["channels"][0]["processing"]["preset"] = "Kick In"
    for name in ("touringband.csv", "touringband.md"):
        (tmp_path / name).write_text((FIXTURES / name).read_text())
    out = tmp_path / "p.json"
    main(["build", "--console-model", "wing-compact", "--input", str(tmp_path / "touringband.csv"),
          "--conventions", str(tmp_path / "touringband.md"), "--presets", str(LIBRARY_DIR),
          "--out", str(out)])
    built = json.loads(out.read_text())
    values = built["channels"][0]["processing"]["preset_values"]
    assert values["preset"] == "Kick In" and "flt/lcf" in values["overridden"]
    assert "preset.overridden" in {f["code"] for f in built["meta"]["build_findings"]}
    assert "preset.not-expanded" not in capsys.readouterr().err


def test_the_setup_page_shows_the_preset_and_how_many_values_it_carries():
    """The Python suite cannot see the browser code, so assert
    over the served asset (step 04's Preset row)."""
    js = (Path(__file__).parents[1] / "atoo" / "web" / "static" / "setup.js").read_text()
    assert "function presetCount(" in js
    assert "preset_values" in js
    assert '["Preset", p.preset ? esc(p.preset + presetCount(p)) : DASH]' in js


# ---------------------------------------------------------------------------
# a list choice the strip's bank does not offer -- an earlier change
# ---------------------------------------------------------------------------

STARTER_LIBRARY_DIR = FIXTURES / "channel_presets"
APPLY_EXCERPT = FIXTURES / "console-runs" / "2026-10-02-sixpiece-apply-excerpt.json"
PARAMETER_MAP = Path(__file__).parents[1] / "docs" / "reference" / "wing-compact-parameter-map.json"


def _on_aux(name: str, library_dir: Path = STARTER_LIBRARY_DIR) -> tuple[dict, list]:
    plan = plan_naming(name, hpf_hz=None)
    kick(plan)["bank"] = "aux"
    findings = preset_expand.expand_plan(plan, PresetLibrary(library_dir))
    return plan, findings


def test_the_desk_read_back_bus_for_an_aux_tap_written_in():
    """The evidence, frozen: the Compact took aux 2 HOST's preset tap `IN`
    and read back `BUS` -- and the parameter map says why: `IN` is a
    channel's tap, not on an aux's list."""
    rows = json.loads(APPLY_EXCERPT.read_text())["writes"]
    [tap] = [r for r in rows if r["address"] == "/aux/2/dynsc/tap"]
    assert (tap["intended_value"], tap["readback_value"], tap["status"]) == ("IN", "BUS", "mismatch")
    assert "IN" not in preset_expand.bank_choices("dynsc/tap", "aux")
    assert "BUS" in preset_expand.bank_choices("dynsc/tap", "aux")
    assert "IN" in preset_expand.bank_choices("dynsc/tap", "ch")


def test_a_channel_tap_on_an_aux_is_carried_as_the_aux_s_equivalent_and_said_at_info():
    plan, findings = _on_aux("Speech")
    leaves = kick(plan)["processing"]["preset_values"]["leaves"]
    assert leaves["dynsc/tap"] == "BUS"
    [note] = [f for f in findings if f.code == "preset.value-not-on-strip"]
    assert note.severity == "info"
    assert "dynsc/tap 'IN' -> 'BUS'" in note.message


def test_the_same_preset_on_a_channel_keeps_its_own_tap():
    plan = plan_naming("Speech", hpf_hz=None)
    findings = preset_expand.expand_plan(plan, PresetLibrary(STARTER_LIBRARY_DIR))
    assert kick(plan)["processing"]["preset_values"]["leaves"]["dynsc/tap"] == "IN"
    assert "preset.value-not-on-strip" not in codes(findings)


@pytest.mark.parametrize("library_dir", [STARTER_LIBRARY_DIR, LIBRARY_DIR],
                         ids=["channel_presets", "presets"])
def test_every_fixture_preset_on_an_aux_carries_only_what_an_aux_offers(library_dir):
    for path in sorted(library_dir.glob("*.chn")):
        name = load_preset(path).name
        plan, _ = _on_aux(name, library_dir)
        values = preset_expand.preset_values(kick(plan))
        if values is None:
            continue    # a name the library resolves to another file
        for address, value in values["leaves"].items():
            assert preset_expand.value_refusal(address, "aux", value) is None, (path.name, address)


def test_a_choice_with_no_equivalent_is_left_out_with_the_values_it_governs(tmp_path):
    """No preset in the library does this today; the rule is the same.
    `DS902` is a channel's dynamics model an aux does not have, so the
    preset's compressor values -- set for it -- go with it."""
    doc = json.loads((STARTER_LIBRARY_DIR / "Speech.chn").read_text())
    doc["ch_data"]["dyn"]["mdl"] = "DS902"
    (tmp_path / "speech.chn").write_text(json.dumps(doc))
    plan, findings = _on_aux("Speech", tmp_path)
    leaves = kick(plan)["processing"]["preset_values"]["leaves"]
    assert "dyn/mdl" not in leaves and "dyn/thr" not in leaves
    assert "dyn/on" in leaves and "eq/1g" in leaves
    [note] = [f for f in findings if f.code == "preset.value-not-on-strip"]
    assert "dyn/mdl 'DS902'" in note.message
    assert "dyn/thr (set for dyn/mdl, which is left out)" in note.message


def test_apply_and_verify_refuse_a_choice_the_aux_does_not_offer_in_a_hand_edited_plan():
    """A plan built before an earlier change still carries `IN`: apply does not
    write it to read back a mismatch, and verify says so first."""
    plan, _ = _on_aux("Speech")
    kick(plan)["processing"]["preset_values"]["leaves"]["dynsc/tap"] = "IN"
    n = kick(plan)["channel"]
    targets, warnings = _build_write_targets(plan, True)
    assert f"/aux/{n}/dynsc/tap" not in {t.address for t in targets}
    assert any("value at dynsc/tap not written -- an aux strip's dynsc/tap has no 'IN'" in w
               and "'BUS'" in w for w in warnings)
    result = verify_plan(plan, presets=PresetLibrary(STARTER_LIBRARY_DIR))
    refused = next(f for f in result.findings if f.code == "preset.leaf-not-written")
    assert "dynsc/tap" in refused.message


def test_only_the_model_variant_lists_go_unchecked():
    """`bank_choices` trusts the type table's tokens except for a list whose
    choices change with the strip's model: those are exactly the list-typed
    preset leaves among the parameter map's `variant_templates`."""
    if not PARAMETER_MAP.exists():
        pytest.skip("needs docs/reference/wing-compact-parameter-map.json, which this tree does not have")
    data = json.loads(PARAMETER_MAP.read_text())
    variant = set()
    for template in data["variant_templates"]:
        bank_node, _, leaf = template.rpartition(".")
        for bank in ("ch", "aux"):
            prefix = f"/{bank}/{{n}}/"
            if bank_node.startswith(prefix):
                address = bank_node[len(prefix):] + "/" + leaf
                spec = preset_expand.leaf_type(address)
                if spec is not None and spec.osc == "s":
                    variant.add(address)
    assert variant == set(preset_expand._MODEL_VARIANT_LISTS)
