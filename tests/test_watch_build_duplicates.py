"""A build never adds a watch condition the file already has.

`merge_drafted_conditions` used to compare ids alone, and a model names the
same rule differently each time it is asked, so a rebuild put `pa-main-muted`
(`MAIN 1` muted) beside the `pa-unmuted` (`MAIN PA` muted) already in
`watch.json`. Two conditions are now the same when they cover the same
strips -- a name is looked up in the plan -- and ask the same field,
operator and value; ids, descriptions, severities and the spelling of the
target do not matter.

`fixtures/watch-build-duplicates.watch.json` is the file a full-size WING
run of the Demo ended with, duplicates and all, and
`fixtures/watch-build.plan.json` the plan it was drafted for, cut down to
two channels. Bundles are built in `tmp_path`; nothing here reads a bundle
under `examples/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import bundle, cli, generate
from atoo.watch_conditions import (
    covered_strips,
    merge_drafted_conditions,
    parse_watch_conditions,
)

FIXTURES = Path(__file__).parent / "fixtures"


def plan() -> dict:
    return json.loads((FIXTURES / "watch-build.plan.json").read_text(encoding="utf-8"))


def existing() -> dict:
    return json.loads((FIXTURES / "watch-build-duplicates.watch.json").read_text(encoding="utf-8"))


def cond(cond_id: str, channel: str, field: str = "muted", op: str = "==", value=False,
         severity: str = "error") -> dict:
    return {"id": cond_id, "description": f"{channel} {field}", "channel": channel,
            "field": field, "operator": op, "value": value, "severity": severity}


def merge(drafted: list[dict], file: dict | None = None):
    return merge_drafted_conditions(file if file is not None else existing(), drafted, plan())


# ---- what a strip is ---------------------------------------------------------


@pytest.mark.parametrize("a, b", [
    ("MAIN PA", "MAIN 1"),          # the plan names Main 1 "PA"
    ("main pa", "Main 1"),
    ("BUS Drum IEM", "BUS 4"),
    ("DCA Vocals", "DCA 3"),
    ("Lead Vox", "CH 10"),
    ("lead vox", "CH Lead Vox"),
])
def test_a_name_and_the_position_it_has_in_the_plan_are_one_strip(a, b):
    assert covered_strips(a, plan()) == covered_strips(b, plan())


def test_a_range_covers_the_strips_it_names_and_a_name_the_plan_cannot_settle_stays_a_name():
    assert covered_strips("DCA 1-5", plan()) >= covered_strips("DCA Vocals", plan())
    assert covered_strips("DCA 1-2", plan()) != covered_strips("DCA Vocals", plan())
    assert covered_strips("BUS Ghost", plan()) == covered_strips("bus ghost", plan())
    assert covered_strips("BUS Ghost", plan()) != covered_strips("BUS Drums", plan())
    # With no plan a name is only itself, as it was.
    assert covered_strips("MAIN PA", None) != covered_strips("MAIN 1", None)


# ---- the duplicates a rebuild made -------------------------------------------------


def test_the_draft_for_the_same_pa_under_other_ids_adds_nothing():
    drafted = [cond("main-muted", "MAIN 1"),                     # = pa-unmuted ("MAIN PA")
               cond("main-low", "Main 1", "fader_db", ">=", -40.0)]   # = pa-main-fader-low
    document, report = merge(drafted)
    assert report.added == ()
    assert report.duplicates == (("main-muted", "pa-unmuted"), ("main-low", "pa-main-fader-low"))
    assert not report.changed
    assert document["watch_conditions"] == existing()["watch_conditions"]


def test_one_condition_on_a_range_covers_a_draft_for_one_strip_in_it():
    document, report = merge([cond("vocals-dca", "DCA Vocals"), cond("fx-dca", "dca fx")])
    assert report.duplicates == (("vocals-dca", "vocals-dca-muted"), ("fx-dca", "dca-muted"))
    assert report.added == ()


def test_a_draft_wider_than_the_range_it_overlaps_is_added():
    _, report = merge([cond("dcas", "DCA 1-8")])
    assert report.added == ("dcas",) and report.duplicates == ()
    assert report.overlaps == (("dcas", "vocals-dca-muted"),)


def test_a_different_threshold_operator_field_or_value_is_not_a_duplicate():
    drafted = [cond("lower", "MAIN 1", "fader_db", ">=", -50),
               cond("strict", "MAIN 1", "fader_db", ">", -40),
               cond("muted-wanted", "MAIN 1", value=True),
               cond("patch", "Lead Vox", "patch", "==", "AES50-A 13")]
    _, report = merge(drafted)
    assert report.added == ("lower", "strict", "muted-wanted", "patch")
    assert report.duplicates == ()


def test_severity_and_wording_are_not_part_of_the_meaning():
    document, report = merge([cond("pa", "MAIN PA", severity="warning")])
    assert report.duplicates == (("pa", "pa-unmuted"),)
    assert not report.added


def test_a_condition_repeated_inside_the_draft_is_added_once():
    document, report = merge([cond("a", "Lead Vox", "fader_db", ">=", -40),
                              cond("b", "CH 10", "fader_db", ">=", -40.0)])
    assert report.added == ("a",) and report.duplicates == (("b", "a"),)


def test_a_duplicate_is_not_recorded_as_drafted():
    """Never put in the file, so deleting the rule it duplicated later must
    let the draft propose it again."""
    document, _ = merge([cond("main-muted", "MAIN 1"), cond("new", "BUS Drums", "fader_db", "<=", 6)])
    assert "main-muted" not in document["drafted"]
    assert "new" in document["drafted"]


def test_the_merged_file_still_loads():
    document, _ = merge([cond("new", "Kick", "fader_db", "<=", 6)])
    assert parse_watch_conditions(json.dumps(document))


# ---- through the build ---------------------------------------------------------


class _Show:
    def __init__(self, directory: Path):
        self.directory = directory

    def path(self, slot: str) -> Path:
        return self.directory / slot


def _draft(show, monkeypatch, drafted):
    monkeypatch.setattr(generate, "draft_watch_conditions", lambda *a, **k: drafted)
    cli._draft_watchlist_into_bundle(show, plan(), "conventions", provider=None,
                                     conventions_name="conventions.md", instructions=None,
                                     instructions_name=None, written=[])


def test_a_rebuild_that_drafts_the_same_rules_again_leaves_watch_json_as_it_is(
        tmp_path, monkeypatch, capsys):
    path = tmp_path / bundle.WATCH_CONDITIONS
    path.write_text(json.dumps(existing(), indent=2) + "\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    _draft(_Show(tmp_path), monkeypatch,
           [cond("main-muted", "MAIN 1"), cond("vocals-bus", "BUS Vocals"),
            cond("dca-vox", "DCA Vocals")])

    assert path.read_text(encoding="utf-8") == before
    err = capsys.readouterr().err
    assert "'main-muted' says what your 'pa-unmuted' already says" in err
    assert "'vocals-bus' says what your 'vocals-bus-muted' already says" in err
    assert "the same strips, field, operator and value" in err
    assert "added nothing new" in err


def test_a_first_build_still_writes_the_whole_draft(tmp_path, monkeypatch, capsys):
    _draft(_Show(tmp_path), monkeypatch,
           [cond("main-muted", "MAIN 1"), cond("also-main", "MAIN PA")])
    written = json.loads((tmp_path / bundle.WATCH_CONDITIONS).read_text(encoding="utf-8"))
    assert [c["id"] for c in written["watch_conditions"]] == ["main-muted"]
