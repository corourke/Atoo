"""Which preset library a command uses, resolved once for
`build`, `patch` and `amend` (`atoo/preset_library.py`).

At the desk, `patch --show /tmp/demo-show "...horns..." --confirm`, with no
`--presets`, wrote Trumpet, Trombone and a new Horns bus without their
presets' values: the show's own library was there all along, recorded in
every expanded strip of its plan. These pin the order -- `--presets`, then
the library the plan records (or the packaged starter it matches), then
`[presets] default` -- that it is said at INFO, and that a change naming
presets with no library at all is a WARNING up top, not a trailing note.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from atoo import preset_library
from atoo.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
LIBRARY = FIXTURES / "presets"
REAL_PLANS = json.loads((FIXTURES / "real_plans.json").read_text())


def _library(tmp_path: Path, name: str) -> Path:
    """A copy of the fixture library, so two candidates are distinguishable."""
    target = tmp_path / name
    shutil.copytree(LIBRARY, target)
    return target


def _plan_built_with(library: str, sha256: str | None = None, file: str = "Kick.chn") -> dict:
    """A plan whose first channel carries a preset expanded from `library`."""
    plan = copy.deepcopy(REAL_PLANS["touringband"])
    plan["channels"][0]["processing"]["preset"] = "Kick In"
    plan["channels"][0]["processing"]["preset_values"] = {
        "preset": "Kick In", "file": file, "library": library,
        "sha256": sha256 or "0" * 64, "leaves": {}, "overridden": {}}
    return plan


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# the order
# ---------------------------------------------------------------------------

def test_an_explicit_library_beats_the_plans_and_the_default(tmp_path):
    stated, recorded, default = (_library(tmp_path, n) for n in ("stated", "recorded", "default"))
    choice = preset_library.resolve(str(stated), _plan_built_with(str(recorded)),
                                    default=default, default_label="the default")
    assert choice.path == stated and choice.source == "--presets"
    assert any("given with --presets" in i for i in choice.infos)


def test_the_library_the_plan_records_beats_the_config_default(tmp_path):
    """The strips already on the desk carry that library's values; a strip a
    change adds takes its preset from the same one."""
    recorded, default = _library(tmp_path, "recorded"), _library(tmp_path, "default")
    choice = preset_library.resolve(None, _plan_built_with(str(recorded)),
                                    default=default, default_label="the default")
    assert choice.path == recorded
    assert any("the plan on the desk was built with" in i for i in choice.infos)


def test_a_recorded_library_not_there_is_matched_to_the_starter_by_contents(tmp_path,
                                                                           monkeypatch):
    """The Demo show and any copy of it: `starter/presets` was recorded
    relative to where it was built, and is found again by its files."""
    monkeypatch.chdir(tmp_path)    # where starter/presets is not
    starter = _library(tmp_path, "starter-presets")
    plan = _plan_built_with("starter/presets", _sha(starter / "Kick.chn"))
    choice = preset_library.resolve(None, plan, default=None, default_label="the default",
                                    starter=starter)
    assert choice.path == starter
    assert any("packaged starter presets with the same contents" in i for i in choice.infos)


def test_a_starter_whose_files_differ_is_not_taken_for_the_plans_library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    starter, default = _library(tmp_path, "starter-presets"), _library(tmp_path, "default")
    plan = _plan_built_with("starter/presets", "f" * 64)
    choice = preset_library.resolve(None, plan, default=default, default_label="the default",
                                    starter=starter)
    assert choice.path == default
    assert any("starter/presets, does not exist" in i for i in choice.infos), choice.infos


def test_an_empty_or_missing_default_is_passed_over_and_said(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    for default in (empty, tmp_path / "missing"):
        choice = preset_library.resolve(None, None, default=default, default_label="the default")
        assert choice.library is None
        assert choice.infos and choice.infos[0].startswith("no preset library: the default")


def test_a_stated_library_that_is_not_there_is_a_warning_and_no_library(tmp_path):
    recorded = _library(tmp_path, "recorded")
    choice = preset_library.resolve(str(tmp_path / "nope"), _plan_built_with(str(recorded)))
    assert choice.library is None
    assert choice.warnings and "(--presets) does not exist" in choice.warnings[0]


# ---------------------------------------------------------------------------
# build and patch share it
# ---------------------------------------------------------------------------

def test_build_resolves_its_library_with_the_shared_resolver(stub_build, tmp_path, monkeypatch,
                                                            capsys):
    seen = []
    real = preset_library.resolve
    monkeypatch.setattr(preset_library, "resolve",
                        lambda *a, **k: seen.append(a) or real(*a, **k))
    plan = stub_build("touringband")
    plan["channels"][0]["processing"]["preset"] = "Kick In"
    for name in ("touringband.csv", "touringband.md"):
        (tmp_path / name).write_text((FIXTURES / name).read_text())
    out = tmp_path / "p.json"
    main(["build", "--console-model", "wing-compact", "--input", str(tmp_path / "touringband.csv"),
          "--conventions", str(tmp_path / "touringband.md"), "--presets", str(LIBRARY),
          "--out", str(out)])
    assert seen and seen[0][0] == str(LIBRARY)
    assert f"INFO preset library: {LIBRARY} -- given with --presets" in capsys.readouterr().err
    assert json.loads(out.read_text())["channels"][0]["processing"]["preset_values"]


def test_missing_library_warning_names_the_presets_a_change_adds():
    change_set = {"add": {"channels": [{"processing": {"preset": "Trumpet"}},
                                       {"processing": {"preset": None}}],
                          "busses": {"Horns": {"preset": "Mix Bus"}}}}
    none = preset_library.LibraryChoice()
    warning = preset_library.missing_library_warning(change_set, none)
    assert "names 2 preset(s) (Trumpet, Mix Bus)" in warning
    assert preset_library.missing_library_warning({"add": {}}, none) is None
    found = preset_library.LibraryChoice(library=object())
    assert preset_library.missing_library_warning(change_set, found) is None


def test_the_patch_page_draws_the_missing_library_warning_first():
    """CLAUDE.md: the suite cannot see the browser -- assert over the asset."""
    js = (Path(__file__).parents[1] / "atoo" / "web" / "static" / "amend.js").read_text()
    assert 'if (review.preset_warning) {' in js
    assert 'text("li", "is-warning", "WARNING " + review.preset_warning)' in js
    assert js.index("review.preset_warning") < js.index("(review.infos || [])")
