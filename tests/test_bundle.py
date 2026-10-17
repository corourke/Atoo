"""The show-bundle path resolver.

Pure path resolution, so these tests are pure too -- nothing here reads,
parses or validates a file's contents. The CLI-level tests that `--show`
actually wires each command to the right paths live in `test_cli.py`.
"""

from pathlib import Path

import pytest

from atoo import bundle
from atoo.bundle import Bundle, BundleError


def _make(tmp_path: Path, *names: str) -> Path:
    d = tmp_path / "my-show"
    d.mkdir()
    for n in names:
        (d / n).write_text("x")
    return d


# --------------------------------------------------------------------------
# load()
# --------------------------------------------------------------------------

def test_load_resolves_every_slot_to_a_fixed_filename(tmp_path):
    d = _make(tmp_path)
    b = bundle.load(d)
    assert b.input_list == d / "input.csv"
    assert b.instructions == d / "instructions.md"
    assert b.plan == d / "plan.json"
    assert b.watch_conditions == d / "watch.json"
    assert b.journals == d / "journals"


def test_an_empty_directory_is_a_valid_bundle(tmp_path):
    """The first thing anyone does is point --show at a directory holding
    only an input list, before any plan exists. Refusing that would make
    the flag useless for its own first use."""
    b = bundle.load(_make(tmp_path))
    assert b.present() == ()
    assert set(b.missing()) == set(bundle.SLOTS)


def test_load_accepts_a_string_path(tmp_path):
    d = _make(tmp_path, "input.csv")
    assert bundle.load(str(d)).has("input.csv")


def test_a_missing_directory_is_an_error_naming_the_path(tmp_path):
    with pytest.raises(BundleError) as exc:
        bundle.load(tmp_path / "nope")
    assert "no such directory" in str(exc.value)
    assert "nope" in str(exc.value)


def test_a_file_is_not_a_bundle(tmp_path):
    f = tmp_path / "plan.json"
    f.write_text("{}")
    with pytest.raises(BundleError) as exc:
        bundle.load(f)
    assert "not a directory" in str(exc.value)


# --------------------------------------------------------------------------
# presence
# --------------------------------------------------------------------------

def test_present_and_missing_split_the_slots(tmp_path):
    d = _make(tmp_path, "input.csv", "plan.json")
    b = bundle.load(d)
    assert b.present() == ("input.csv", "plan.json")
    assert "watch.json" in b.missing()
    assert "input.csv" not in b.missing()


def test_present_is_ordered_by_the_slot_table_not_the_filesystem(tmp_path):
    d = _make(tmp_path, "watch.json", "plan.json", "input.csv")
    assert bundle.load(d).present() == ("input.csv", "plan.json", "watch.json")


def test_a_directory_named_like_a_slot_does_not_count_as_that_slot(tmp_path):
    """`has()` asks for a *file*. A stray `plan.json/` directory would
    otherwise resolve to a path every reader then fails on."""
    d = tmp_path / "my-show"
    (d / "plan.json").mkdir(parents=True)
    b = bundle.load(d)
    assert not b.has("plan.json")
    assert "plan.json" in b.missing()


# --------------------------------------------------------------------------
# optional() / require()
# --------------------------------------------------------------------------

def test_optional_returns_none_for_an_absent_slot(tmp_path):
    b = bundle.load(_make(tmp_path, "input.csv"))
    assert b.optional("watch.json") is None
    assert b.optional("input.csv") == b.input_list


def test_require_returns_the_path_when_it_exists(tmp_path):
    b = bundle.load(_make(tmp_path, "input.csv"))
    assert b.require("input.csv") == b.input_list


def test_require_names_the_directory_and_the_expected_filename(tmp_path):
    """The failure this guards against is someone laying a bundle out by
    hand and naming the input list after the show, so the message has to
    say which name it wanted -- not just 'not a bundle'."""
    d = _make(tmp_path, "touringband.csv")
    with pytest.raises(BundleError) as exc:
        bundle.load(d).require("input.csv")
    message = str(exc.value)
    assert "input.csv" in message
    assert str(d) in message


def test_an_unknown_slot_is_a_programming_error_not_a_user_error(tmp_path):
    b = bundle.load(_make(tmp_path))
    with pytest.raises(ValueError):
        b.path("conventions.md")


def test_expectations_toml_is_no_longer_a_slot(tmp_path):
    """An earlier change retired it. A bundle directory that still holds one is not an
    error and not a slot: `present()` never names it, so the web UI's
    bundle bar stops drawing a row for a file the project no longer has."""
    d = _make(tmp_path, "input.csv", "expectations.toml")
    b = bundle.load(d)
    assert "expectations.toml" not in bundle.SLOTS
    assert "expectations.toml" not in b.present()
    assert "expectations.toml" not in b.missing()
    assert not hasattr(b, "expectations")
    with pytest.raises(ValueError):
        b.path("expectations.toml")


def test_every_slot_constant_is_in_the_slots_tuple():
    for name in (bundle.INPUT_LIST, bundle.INSTRUCTIONS,
                 bundle.PLAN, bundle.WATCH_CONDITIONS):
        assert name in bundle.SLOTS
    assert len(bundle.SLOTS) == 4


# --------------------------------------------------------------------------
# the retired top-level journals (fallback retired 2026-10-02)
# --------------------------------------------------------------------------

def test_the_retired_journal_files_are_not_slots(tmp_path):
    """journals/ is the only record. A top-level journal file is not a
    slot, so a bundle holding one neither reports it nor misses it."""
    d = _make(tmp_path, "apply-journal.json")
    b = bundle.load(d)
    for name in ("apply-journal.json", "amend-journal.json", "patch-journal.json"):
        assert name not in bundle.SLOTS
        assert name not in b.present() + b.missing()


def test_the_house_conventions_file_is_not_a_bundle_slot():
    """An earlier change point 5: the house conventions file stays OUTSIDE the bundle --
    it is the reusable piece, and putting it in would defeat the point."""
    assert not any("convention" in s for s in bundle.SLOTS)


def test_bundle_is_frozen(tmp_path):
    b = bundle.load(_make(tmp_path))
    with pytest.raises(Exception):
        b.directory = Path("/elsewhere")
