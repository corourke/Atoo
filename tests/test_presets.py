import json
from pathlib import Path

import pytest

from atoo.presets import ChannelPreset, PresetError, PresetLibrary, load_preset

FIXTURES = Path(__file__).parent / "fixtures" / "presets"
RAW_KICK = json.loads((FIXTURES / "Kick.chn").read_text())

# Frozen copies of five of the maintainer's own presets (`starter/presets/`,
# 2026-10-12), all chpreset.11 exports from WING-EDIT 3.3.1.
ALL_FIXTURE_NAMES = (
    "Kick.chn",
    "Snare.chn",
    "H Tom.chn",
    "Fl Tom.chn",
    "Piano.chn",
)


def test_loads_all_five_reference_fixtures_with_no_warnings():
    # The allow/exclude classification was built by diffing real WING
    # exports, so this is the module's core claim: nothing in them is left
    # unclassified.
    for fixture_name in ALL_FIXTURE_NAMES:
        preset = load_preset(FIXTURES / fixture_name)
        assert preset.warnings == ()


def test_kick_preset_values_and_metadata():
    preset = load_preset(FIXTURES / "Kick.chn")
    # The file is Kick.chn; the name saved inside it is "Kick In".
    assert preset.name == "Kick In"
    assert preset.creator_fw == "VERSION_FULL"
    assert preset.creator_model == "WING-EDIT"
    assert preset.created == "2026-09-11 16:13:37"
    assert preset.source_channel == 1

    # A few real processing values, spot-checked against the raw file.
    assert preset.parameters["flt.lcf"] == pytest.approx(40.19342422)
    assert preset.parameters["gate.thr"] == -40.5
    assert preset.parameters["eq.2g"] == pytest.approx(-10.10000038)
    assert preset.parameters["dyn.ratio"] == 5


@pytest.mark.parametrize(
    "excluded_path",
    [
        "in.conn.in",  # physical patch
        "in.conn.grp",
        "main.1.on",  # bus routing
        "send.3.lvl",
        "mute",  # live mix state
        "fdr",
        "pan",
        "wid",
        "name",  # identity
        "col",
        "icon",
        "tags",  # DCA/mute-group membership
        "proc",  # chain order -- WING's CONFIG scope, not a sound field
        "ptap",
        "preins.ins",  # FX-slot allocation
        "postins.ins",
        "in.set.trim",  # gain staging tied to this show's patched source
        "in.set.inv",
    ],
)
def test_excluded_fields_never_reach_parameters(excluded_path):
    for fixture_name in ALL_FIXTURE_NAMES:
        preset = load_preset(FIXTURES / fixture_name)
        assert excluded_path not in preset.parameters


@pytest.mark.parametrize(
    "included_prefix",
    ["flt.", "gate.", "gatesc.", "dyn.", "dynxo.", "dynsc.", "eq.", "peq."],
)
def test_processing_sections_are_present_in_every_fixture(included_prefix):
    for fixture_name in ALL_FIXTURE_NAMES:
        preset = load_preset(FIXTURES / fixture_name)
        assert any(k.startswith(included_prefix) for k in preset.parameters)


def test_input_delay_fields_are_included_but_gain_stage_fields_are_not():
    # WING's own Library Scopes appendix puts input DELAY in its own
    # CONTENTS icon, separate from IN (trim/balance/phase).
    preset = load_preset(FIXTURES / "Kick.chn")
    assert preset.parameters["in.set.dly"] == pytest.approx(0.5)
    assert preset.parameters["in.set.dlymode"] == "FT"
    assert preset.parameters["in.set.dlyon"] is False
    assert "in.set.trim" not in preset.parameters
    assert "in.set.bal" not in preset.parameters


def test_unknown_field_produces_a_named_warning_not_a_silent_drop(tmp_path):
    source = json.loads((FIXTURES / "Kick.chn").read_text())
    source["ch_data"]["totally_new_field"] = {"mystery": 42}
    mutated = tmp_path / "mutant.chn"
    mutated.write_text(json.dumps(source))

    preset = load_preset(mutated)
    assert "totally_new_field.mystery" not in preset.parameters
    assert any("totally_new_field.mystery" in w for w in preset.warnings)


def test_sidechain_channel_reference_is_dropped_with_a_warning(tmp_path):
    # gatesc.src / dynsc.src can name another channel ("CH.12"). Replaying
    # that onto a different channel or show would silently key the gate
    # off whatever occupies channel 12 there -- must never be applied
    # blind.
    source = json.loads((FIXTURES / "Kick.chn").read_text())
    source["ch_data"]["gatesc"]["src"] = "CH.12"
    mutated = tmp_path / "keyed.chn"
    mutated.write_text(json.dumps(source))

    preset = load_preset(mutated)
    assert "gatesc.src" not in preset.parameters
    assert any("gatesc.src" in w and "CH.12" in w for w in preset.warnings)
    # The rest of the gate sidechain section is unaffected.
    assert preset.parameters["gatesc.type"] == "BP"


def test_self_sidechain_source_is_included_normally():
    preset = load_preset(FIXTURES / "Kick.chn")
    assert preset.parameters["gatesc.src"] == "SELF"
    assert preset.parameters["dynsc.src"] == "SELF"


def test_rejects_non_chpreset_type(tmp_path):
    bad = tmp_path / "bad.chn"
    bad.write_text(json.dumps({"type": "snap.1", "ch_data": {}}))
    with pytest.raises(PresetError, match="channel preset"):
        load_preset(bad)


def test_rejects_missing_ch_data(tmp_path):
    bad = tmp_path / "bad.chn"
    bad.write_text(json.dumps({"type": "chpreset.8"}))
    with pytest.raises(PresetError, match="ch_data"):
        load_preset(bad)


def test_rejects_malformed_json(tmp_path):
    bad = tmp_path / "bad.chn"
    bad.write_text("{not json")
    with pytest.raises(PresetError, match="not valid JSON"):
        load_preset(bad)


def test_rejects_missing_file(tmp_path):
    with pytest.raises(PresetError):
        load_preset(tmp_path / "does_not_exist.chn")


def test_falls_back_to_filename_when_info_text_missing(tmp_path):
    source = json.loads((FIXTURES / "Kick.chn").read_text())
    source["info_text"] = ""
    mutated = tmp_path / "unnamed_preset.chn"
    mutated.write_text(json.dumps(source))
    preset = load_preset(mutated)
    assert preset.name == "unnamed_preset"


def test_leaves_is_an_alias_for_parameters():
    preset = load_preset(FIXTURES / "Kick.chn")
    assert preset.leaves() == preset.parameters


class TestPresetLibrary:
    def test_names_lists_every_preset_by_info_text(self):
        library = PresetLibrary(FIXTURES)
        names = library.names()
        assert set(names) == {"Kick In", "Snare", "H Tom", "Fl Tom", "Piano"}

    def test_get_looks_up_by_name_case_insensitively(self):
        library = PresetLibrary(FIXTURES)
        preset = library.get("kick in")
        assert isinstance(preset, ChannelPreset)
        assert preset.name == "Kick In"

    def test_get_raises_for_unknown_name(self):
        library = PresetLibrary(FIXTURES)
        with pytest.raises(PresetError, match="no preset named"):
            library.get("nonexistent preset")

    def test_iteration_yields_every_preset(self):
        library = PresetLibrary(FIXTURES)
        loaded = list(library)
        assert len(loaded) == 5
        assert all(isinstance(p, ChannelPreset) for p in loaded)

    def test_rejects_non_directory(self, tmp_path):
        not_a_dir = tmp_path / "nope.chn"
        not_a_dir.write_text("{}")
        library = PresetLibrary(not_a_dir)
        with pytest.raises(PresetError, match="not a directory"):
            library.names()

    def test_duplicate_names_resolve_to_the_newest_rather_than_raising(self, tmp_path):
        """Reversed by the maintainer on 2026-09-20: "Two files naming
        the same name is a Warning, pick the newest one." A duplicate is a
        library-hygiene problem and must not stop a show being built --
        `verify_plan` raises the warning, this just picks."""
        import os

        source = json.loads((FIXTURES / "Kick.chn").read_text())
        older, newer = tmp_path / "a.chn", tmp_path / "b.chn"
        older.write_text(json.dumps(source))
        newer.write_text(json.dumps(source))
        os.utime(older, (1_000_000, 1_000_000))     # unambiguously older

        library = PresetLibrary(tmp_path)
        assert library.get("Kick In").source_path == newer
        # ...and the full list is still available, newest first, so a
        # caller can report the ambiguity instead of swallowing it
        assert [p.source_path for p in library.matches("Kick In")] == [newer, older]

    def test_name_matching_is_forgiving_about_case_and_separators(self, tmp_path):
        """An engineer writing "uses the Kick In preset" in a conventions
        file is writing prose, not a filename."""
        source = json.loads((FIXTURES / "Kick.chn").read_text())
        (tmp_path / "k.chn").write_text(json.dumps(source))
        library = PresetLibrary(tmp_path)
        for spelling in ("Kick In", "kick in", "KICK-IN", "kick_in", "  Kick   In "):
            assert library.get(spelling).source_path == tmp_path / "k.chn", spelling

    def test_matching_does_not_go_further_than_separators(self, tmp_path):
        """"Kick (In)" stays a different preset from "Kick In" --
        normalizing punctuation away starts merging presets someone meant
        to keep apart."""
        source = json.loads((FIXTURES / "Kick.chn").read_text())
        (tmp_path / "k.chn").write_text(json.dumps(source))
        library = PresetLibrary(tmp_path)
        with pytest.raises(PresetError, match="no preset named"):
            library.get("Kick (In)")


# ---------------------------------------------------------------------------
# chpreset.11 -- the WING-EDIT export format, and a preset that carries
# routing. Every preset in the maintainer's own set is one; the Kick is used.
# ---------------------------------------------------------------------------


def test_a_chpreset_11_export_parses():
    """`chpreset.8` comes off the desk; `chpreset.11` comes out of
    WING-EDIT, the offline editor, and carries more leaves than .8."""
    preset = PresetLibrary(FIXTURES).get("Kick In")
    assert RAW_KICK["type"] == "chpreset.11"
    assert preset.parameters, "a v11 preset must yield sound-shaping parameters like any other"
    assert preset.parameters["eq.on"] is True


def test_a_chpreset_8_shaped_export_still_parses(tmp_path):
    """The desk's own export, `chpreset.8`, has no `in.set.$g`/`$vph`.
    None is in the starter set any more, so one is built from the Kick."""
    source = json.loads(json.dumps(RAW_KICK))
    source["type"] = "chpreset.8"
    for leaf in ("$g", "$vph"):
        source["ch_data"]["in"]["set"].pop(leaf)
    (tmp_path / "kick8.chn").write_text(json.dumps(source))
    preset = load_preset(tmp_path / "kick8.chn")
    assert preset.warnings == ()
    assert preset.parameters == load_preset(FIXTURES / "Kick.chn").parameters


def test_the_one_preset_that_carries_routing_does_not_leak_it():
    """**This is the case "the plan always wins over the preset" exists
    for.** A preset saved with `scopes_main` "++++" and `scopes_send` all
    `+` carries `main.*` and 144 `send.*` leaves, including
    `send.1.lvl = -144`.

    Recalled naively onto a channel, that preset would rewrite the strip's
    routing to the main mix and pull every send to the floor. The
    allow-list is what stands between a plan and that, so it gets a test
    with the real file behind it rather than a constructed one."""
    preset = PresetLibrary(FIXTURES).get("Kick In")
    leaked = [k for k in preset.parameters if k.startswith(("send.", "main.", "in.conn."))]
    assert leaked == [], f"routing escaped the allow-list: {leaked[:5]}"

    # Straight from the file, because `leaves` is already the filtered
    # view -- asserting against it would be asserting the allow-list
    # against itself.
    raw = RAW_KICK
    assert raw["scopes_main"] == "++++" and set(raw["scopes_send"]) == {"+"}, \
        "the fixture was saved with routing out of scope -- it no longer tests anything"
    assert raw["ch_data"]["send"]["1"]["lvl"] == -144
    assert "on" in raw["ch_data"]["main"]["1"]


def test_the_channels_view_of_its_head_amp_is_excluded():
    """`in.set.$g` and `in.set.$vph` are new in chpreset.11 and are the
    channel's view of its input SOCKET's gain and phantom -- WING's `$`
    prefix, and the protocol PDF p.47 says of both "depends on source
    type".

    Excluding them is a safety property, not tidiness. Phantom power is
    the one value in this system with a safety check over it (a ribbon mic
    and 48V). A preset saved on someone else's desk must not be a side
    door around that check."""
    assert "$vph" in RAW_KICK["ch_data"]["in"]["set"]
    preset = PresetLibrary(FIXTURES).get("Kick In")
    assert "in.set.$g" not in preset.parameters
    assert "in.set.$vph" not in preset.parameters
    assert not preset.warnings, f"a known v11 leaf is still unclassified: {list(preset.warnings)}"


def test_a_bus_preset_beside_the_channel_presets_is_not_read_as_one():
    """The maintainer's set has three bus presets (`.bus`) beside its
    channel presets. A `.bus` file says `type: chpreset.11` too, but its
    `ch_data` is a bus, so channel lookups read `*.chn` only; the bus
    presets are a name space of their own (`bus_presets`)."""
    shipped = FIXTURES.parent / "channel_presets"
    buses = sorted(p.name for p in shipped.glob("*.bus"))
    assert buses == ["FX Snare Verb.bus", "FX Vox Verb.bus", "Mix Bus.bus"]
    names = PresetLibrary(shipped).names()
    assert "Vox Verb" not in names and "Snare Verb" not in names and "Mix Bus" not in names
    assert len(names) == len(list(shipped.glob("*.chn")))
    assert sorted(b.name for b in PresetLibrary(shipped).bus_presets()) == [
        "Mix Bus", "Snare Verb", "Vox Verb"]
