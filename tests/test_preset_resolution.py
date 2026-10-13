"""Resolving a plan's named presets against Atoo's
own preset library.

**These are not the console's presets.** The maintainer, 2026-09-20: *"I want to
be sure that we understand that these presets are managed in Atoo,
they are not the presets that live on the console."* WING has no remote
preset-recall command at all (D7), so a "preset" here is a `.chn` export
this project reads and whose parameter values it writes like any other.
A finding in this module always means "I could not find that file", never
"the console refused it".

**Warnings, never errors** -- also the maintainer, reversing the recommendation
he was given: *"Presets are strip settings so add detail to the patch, but
it's not a blocker if the user chooses to ignore the warning."*
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo.cli import main
from atoo.presets import PresetLibrary
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).parent / "fixtures"
LIBRARY = FIXTURES / "presets"
REAL_PLANS = json.loads((FIXTURES / "real_plans.json").read_text())


def plan_naming(*presets: str | None) -> dict:
    """A real plan whose first N channels name these presets."""
    plan = json.loads(json.dumps(REAL_PLANS["touringband"]))
    for channel, name in zip(plan["channels"], presets):
        channel["processing"]["preset"] = name
    return plan


def codes(result) -> list[str]:
    return [f.code for f in result.findings]


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def preset_warnings(result) -> list[str]:
    return [f.code for f in result.findings
            if f.code.startswith("preset.") and f.severity != "info"]


def expanded(plan: dict, library) -> dict:
    """The plan as `build` leaves it: named presets resolved into it
    (slice B, `preset_expand.expand_plan`)."""
    from atoo.preset_expand import expand_plan
    expand_plan(plan, library)
    return plan


def test_a_resolvable_preset_produces_no_warning_once_expanded():
    library = PresetLibrary(LIBRARY)
    result = verify_plan(expanded(plan_naming("Kick In"), library), presets=library)
    assert not preset_warnings(result)
    assert "preset.expanded" in codes(result)   # and it says what it carries


def test_a_resolvable_preset_the_plan_never_expanded_says_nothing_is_written():
    """Slice B: a plan that NAMES a preset the library has, but carries
    none of its values (built before expansion), writes nothing from it --
    said once for that strip, and not mistaken for an unknown preset."""
    result = verify_plan(plan_naming("Kick In"), presets=PresetLibrary(LIBRARY))
    assert preset_warnings(result) == ["preset.not-expanded"]


def test_matching_is_forgiving_about_case_and_separators():
    """A conventions file says "uses the Kick In preset" in prose; the
    library file is `Kick.chn` holding the name "Kick In"."""
    library = PresetLibrary(LIBRARY)
    for spelling in ("kick in", "KICK-IN", "Kick_In", "  Kick   In  "):
        plan = expanded(plan_naming(spelling), library)
        result = verify_plan(plan, presets=library)
        assert not preset_warnings(result), spelling
        assert plan["channels"][0]["processing"]["preset_values"]["preset"] == "Kick In"


def test_an_unknown_preset_warns_and_lists_what_the_library_has():
    result = verify_plan(plan_naming("Snare Bottom"), presets=PresetLibrary(LIBRARY))
    unknown = [f for f in result.findings if f.code == "preset.unknown"]
    assert len(unknown) == 1
    assert "Snare Bottom" in unknown[0].message
    # The near names, not the whole library (2026-10-02: a hundred names
    # in one warning filled the findings panel).
    assert "Closest in the library: Snare" in unknown[0].message
    assert "Kick In" not in unknown[0].message
    assert "(5 presets)" in unknown[0].message


def test_no_library_configured_warns_once_not_once_per_channel():
    """The cause is single -- no library -- so repeating it per strip
    buries it among the findings that differ."""
    result = verify_plan(plan_naming("Kick In", "Snare", "Piano"), presets=None)
    no_library = [f for f in result.findings if f.code == "preset.no-library"]
    assert len(no_library) == 1
    assert "3 channel(s)" in no_library[0].message


def test_a_plan_naming_no_presets_says_nothing_either_way():
    """Silence is correct for the common case: most plans name none, and a
    'no presets to resolve' line on every run is noise."""
    for library in (None, PresetLibrary(LIBRARY)):
        result = verify_plan(plan_naming(), presets=library)
        assert not [c for c in codes(result) if c.startswith("preset.")]


def test_duplicate_names_warn_and_use_the_newest(tmp_path):
    """The maintainer: "Two files naming the same name is a Warning, pick the
    newest one." Picking silently is how the wrong one gets applied for a
    month, so it is said out loud."""
    import os

    source = json.loads((LIBRARY / "Kick.chn").read_text())
    older, newer = tmp_path / "old.chn", tmp_path / "new.chn"
    older.write_text(json.dumps(source))
    newer.write_text(json.dumps(source))
    os.utime(older, (1_000_000, 1_000_000))

    result = verify_plan(plan_naming("Kick In"), presets=PresetLibrary(tmp_path))
    ambiguous = [f for f in result.findings if f.code == "preset.ambiguous"]
    assert len(ambiguous) == 1
    assert str(newer) in ambiguous[0].message      # the one that won
    assert str(older) in ambiguous[0].message      # and the one ignored


def test_an_unreadable_library_warns_rather_than_raising(tmp_path):
    missing = tmp_path / "not-there"
    result = verify_plan(plan_naming("Kick In"), presets=PresetLibrary(missing))
    assert "preset.unreadable-library" in codes(result)


# ---------------------------------------------------------------------------
# severity: the whole point of the maintainer's answer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plan, library", [
    (plan_naming("Snare Bottom"), PresetLibrary(LIBRARY)),   # unknown
    (plan_naming("Kick In"), None),                        # no library
])
def test_no_preset_finding_is_ever_an_error(plan, library):
    """An unresolvable preset must never block an apply. Every preset
    finding is a warning, so `apply`'s verification gate lets it through."""
    result = verify_plan(plan, presets=library)
    preset_errors = [f for f in result.errors if f.code.startswith("preset.")]
    assert not preset_errors
    assert [f for f in result.warnings if f.code.startswith("preset.")]


# ---------------------------------------------------------------------------
# the CLI wiring: --presets and the config default
# ---------------------------------------------------------------------------


@pytest.fixture
def plan_file(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps(plan_naming("Snare Bottom")))
    return path


@pytest.mark.parametrize("command", ["verify", "apply", "build"])
def test_every_command_that_verifies_accepts_presets(command, capsys):
    """--presets is on build, verify and apply -- the three that run
    verification. A flag that exists on only some of them is the kind of
    gap #89 left for --show."""
    with pytest.raises(SystemExit):
        main([command, "--help"])
    out = capsys.readouterr().out
    assert "--presets" in out, f"{command} --help should offer --presets"


def test_verify_presets_flag_resolves_the_library(plan_file, capsys):
    main(["verify", "--plan", str(plan_file), "--presets", str(LIBRARY)])
    out = capsys.readouterr().out
    assert "preset.unknown" in out
    assert f"not in the library at {LIBRARY}" in out   # the library was actually read


def test_verify_without_a_library_reports_no_library(plan_file, capsys, monkeypatch):
    monkeypatch.setattr("atoo.cli.load_default_presets", lambda: None)
    main(["verify", "--plan", str(plan_file)])
    assert "preset.no-library" in capsys.readouterr().out


def test_an_explicit_presets_flag_beats_the_config_default(plan_file, tmp_path, capsys, monkeypatch):
    """Same precedence every other optional input in this CLI has."""
    unused = tmp_path / "unused-library"
    unused.mkdir()
    monkeypatch.setattr("atoo.cli.load_default_presets", lambda: unused)
    main(["verify", "--plan", str(plan_file), "--presets", str(LIBRARY)])
    out = capsys.readouterr().out
    assert f"not in the library at {LIBRARY}" in out, \
        "should have read the --presets library, not the default"


def test_the_config_default_is_used_when_the_flag_is_absent(plan_file, capsys, monkeypatch):
    monkeypatch.setattr("atoo.cli.load_default_presets", lambda: LIBRARY)
    main(["verify", "--plan", str(plan_file)])
    assert f"not in the library at {LIBRARY}" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["a-file", "missing"])
def test_a_library_path_that_is_not_a_directory_warns_and_carries_on(
        bad, plan_file, tmp_path, capsys, monkeypatch):
    """Not a hard failure: a missing library means strips get built without
    their preset processing, which is reported and left to the operator."""
    monkeypatch.setattr("atoo.cli.load_default_presets", lambda: None)
    if bad == "a-file":
        target = tmp_path / "f.chn"
        target.write_text("{}")
    else:
        target = tmp_path / "nope"

    code = main(["verify", "--plan", str(plan_file), "--presets", str(target)])
    captured = capsys.readouterr()
    assert "preset library" in captured.err
    assert "preset.no-library" in captured.out
    assert code != 1, "a bad library path must not be a hard failure"
