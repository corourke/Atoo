"""An earlier change, the last slice of #81: a build into a show bundle also drafts
that bundle's `watch.json`.

Two halves, tested separately because they fail for different reasons:

  * `watch_conditions.merge_drafted_conditions` -- pure, no model, no disk.
    This is where the interesting behaviour lives, and the maintainer's answer
    ("can we do a merge?") is what it implements.
  * the `build` wiring -- that a draft reaches disk validated, that a bad
    draft reaches nothing, and above all that none of it can change the
    exit code of a build that otherwise succeeded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient

from atoo import generate
from atoo.cli import main
from atoo.watch_conditions import (
    SOURCE_DRAFTED,
    WatchConditionsError,
    load_watch_conditions,
    merge_drafted_conditions,
    parse_watch_conditions,
)

FIXTURES = Path(__file__).parent / "fixtures"


def cond(cond_id: str, channel: str = "Kick", field: str = "muted", value=True, **extra) -> dict:
    base = {"id": cond_id, "description": f"{cond_id} description", "channel": channel,
            "field": field, "operator": "==", "value": value, "severity": "warning"}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# the merge itself
# ---------------------------------------------------------------------------


def test_a_draft_with_no_existing_file_is_written_whole():
    document, report = merge_drafted_conditions(None, [cond("Kick"), cond("Crowd", "Crowd L")])
    assert [c["id"] for c in document["watch_conditions"]] == ["Kick", "Crowd"]
    assert report.added == ("Kick", "Crowd")
    assert report.changed


def test_every_drafted_condition_is_marked_as_drafted():
    """The `source` key is the only thing separating a machine's suggestion
    from an operator's decision once both are sitting in the same file."""
    document, _ = merge_drafted_conditions(None, [cond("Kick")])
    assert document["watch_conditions"][0]["source"] == SOURCE_DRAFTED


def test_a_hand_tuned_condition_is_never_overwritten():
    """The property the whole merge exists for. A rebuild must not undo a
    severity someone raised at 18:00 because the draft still says
    'warning'."""
    existing = {"watch_conditions": [cond("Kick", severity="error")]}
    document, report = merge_drafted_conditions(existing, [cond("Kick", severity="warning")])
    assert len(document["watch_conditions"]) == 1
    assert document["watch_conditions"][0]["severity"] == "error"
    assert "source" not in document["watch_conditions"][0]   # still theirs, untouched
    assert report.kept == ("Kick",)
    assert not report.added


def test_a_condition_the_draft_no_longer_proposes_is_kept():
    """A rule written about something the model didn't think to watch is
    exactly the rule worth keeping."""
    existing = {"watch_conditions": [cond("mine", "Talkback")]}
    document, report = merge_drafted_conditions(existing, [cond("Kick")])
    assert [c["id"] for c in document["watch_conditions"]] == ["mine", "Kick"]
    assert report.added == ("Kick",)


def test_a_drafted_condition_you_deleted_does_not_come_back():
    """The one case pure addition gets wrong, and the reason `drafted` is
    recorded at all. Build 1 drafts it, you delete it, build 2 must not
    cheerfully restore it."""
    first, _ = merge_drafted_conditions(None, [cond("Kick")])
    assert first["drafted"] == ["Kick"]

    # the operator deletes the condition but leaves the bookkeeping alone
    after_delete = {"watch_conditions": [], "drafted": first["drafted"]}

    second, report = merge_drafted_conditions(after_delete, [cond("Kick")])
    assert second["watch_conditions"] == []
    assert report.dismissed == ("Kick",)
    assert not report.changed


def test_the_drafted_record_is_a_union_not_a_replacement():
    """An id drafted by an older build and since deleted has to stay
    recorded, or its deletion silently stops sticking two builds later."""
    existing = {"watch_conditions": [], "drafted": ["Old"]}
    document, _ = merge_drafted_conditions(existing, [cond("New")])
    assert document["drafted"] == ["New", "Old"]


def test_two_conditions_on_the_same_target_are_both_kept_but_reported():
    """Ids are the identity, so both run. They can contradict each other,
    which is worth a word rather than a silent resolution."""
    existing = {"watch_conditions": [cond("mine", "Kick", value=True)]}
    document, report = merge_drafted_conditions(existing, [cond("theirs", "Kick", value=False)])
    assert [c["id"] for c in document["watch_conditions"]] == ["mine", "theirs"]
    assert report.overlaps == (("theirs", "mine"),)


def test_overlap_detection_matches_channel_names_case_insensitively():
    """Channel names resolve case-insensitively at evaluation time
    (_resolve_channel_base), so "kick" and "Kick" are one target."""
    existing = {"watch_conditions": [cond("mine", "kick")]}
    _, report = merge_drafted_conditions(existing, [cond("theirs", "KICK")])
    assert report.overlaps == (("theirs", "mine"),)


def test_the_merge_does_not_mutate_its_input():
    existing = {"watch_conditions": [cond("mine", "Talkback")]}
    before = json.dumps(existing, sort_keys=True)
    merge_drafted_conditions(existing, [cond("Kick")])
    assert json.dumps(existing, sort_keys=True) == before


def test_a_merged_document_still_validates():
    """Whatever comes out of here has to be loadable by the same function
    that guards a hand-written file -- including its extra `drafted` key."""
    document, _ = merge_drafted_conditions(
        {"watch_conditions": [cond("mine", "Talkback")]},
        [cond("Kick"), cond("Crowd", "Crowd L", field="fader_db", value=-90.0)],
    )
    assert len(parse_watch_conditions(json.dumps(document))) == 3


def test_source_is_optional_and_validated():
    """Absent means hand-written; a value outside the vocabulary is an
    error, the same stance every other key in this schema takes."""
    assert parse_watch_conditions(json.dumps({"watch_conditions": [cond("a")]}))
    assert parse_watch_conditions(json.dumps({"watch_conditions": [cond("a", source="drafted")]}))
    with pytest.raises(WatchConditionsError, match="unknown source"):
        parse_watch_conditions(json.dumps({"watch_conditions": [cond("a", source="robot")]}))


# ---------------------------------------------------------------------------
# draft_watch_conditions: nothing unvalidated reaches the caller
# ---------------------------------------------------------------------------


class FakeProvider:
    def __init__(self, reply: str | Exception):
        self.reply = reply
        self.labels: list[str] = []

    def complete(self, *, system: str, user: str, label: str = "", **kwargs) -> str:
        self.labels.append(label)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_a_valid_draft_comes_back_parsed():
    provider = FakeProvider(json.dumps({"watch_conditions": [cond("Kick")]}))
    out = generate.draft_watch_conditions({"channels": []}, "conventions", provider=provider)
    assert [c["id"] for c in out] == ["Kick"]
    assert provider.labels == ["watchlist"]


@pytest.mark.parametrize("reply, why", [
    ("not json at all", "unparseable reply"),
    (json.dumps({"watch_conditions": [{"id": "x"}]}), "missing required keys"),
    (json.dumps({"watch_conditions": [cond("x", field="gain")]}), "field outside the vocabulary"),
    (json.dumps({"watch_conditions": [cond("x", severity="urgent")]}), "invented severity"),
    (json.dumps({"nope": []}), "wrong top-level shape"),
])
def test_an_unusable_draft_returns_none_rather_than_raising(reply, why, capsys):
    """`None` is "did not produce a watchlist", which the caller treats as
    "write nothing". A model that invents a field must not be able to put
    a file on disk that `atoo watch` will then refuse."""
    out = generate.draft_watch_conditions(
        {"channels": []}, "conventions", provider=FakeProvider(reply))
    assert out is None, why
    assert "watch-conditions draft" in capsys.readouterr().err


def test_an_unknown_key_is_dropped_and_a_bad_condition_refused_alone(capsys):
    """The Demo's real draft carried `"index"` on its first
    condition, and the whole watchlist was thrown away over it. The key
    is dropped (INFO), a condition still unusable is left out on its
    own, and the rest is kept. Frozen: `watchlist_draft_extra_key.json`."""
    reply = (FIXTURES / "watchlist_draft_extra_key.json").read_text()
    out = generate.draft_watch_conditions(
        {"channels": []}, "conventions", provider=FakeProvider(reply))
    assert [c["id"] for c in out] == ["main-pa-muted", "lead-vox-muted"]
    assert "index" not in out[0]
    err = capsys.readouterr().err
    assert ("INFO watch-conditions draft: watch_conditions[0] ('main-pa-muted'): dropped unknown "
            "key(s) index") in err
    assert "INFO watch-conditions draft: refused watch_conditions[2]" in err
    assert "unknown field 'gain'" in err


def test_a_repeated_id_in_a_draft_keeps_the_first():
    reply = json.dumps({"watch_conditions": [cond("Kick"), cond("Kick", "Snare")]})
    out = generate.draft_watch_conditions(
        {"channels": []}, "conventions", provider=FakeProvider(reply))
    assert [c["channel"] for c in out] == ["Kick"]


def test_a_draft_with_an_extra_key_still_reaches_watch_json(
        stub_build, bundle_dir, monkeypatch, capsys):
    """End to end through `build`: the draft is not stubbed, the model is."""
    stub_build("touringband")
    reply = json.dumps({"watch_conditions": [cond("Kick", index=1)]})
    real = generate.draft_watch_conditions
    monkeypatch.setattr("atoo.generate.draft_watch_conditions",
                        lambda plan, conventions, **kw: real(
                            plan, conventions, **{**kw, "provider": FakeProvider(reply)}))
    _build(bundle_dir)
    assert [c["id"] for c in load_watch_conditions(bundle_dir / "watch.json")] == ["Kick"]
    captured = capsys.readouterr()
    assert "dropped unknown key(s) index" in captured.err
    assert "Watch conditions: 1 drafted condition(s) added" in captured.out


def test_a_provider_that_raises_is_reported_not_propagated(capsys):
    out = generate.draft_watch_conditions(
        {"channels": []}, "conventions", provider=FakeProvider(RuntimeError("boom")))
    assert out is None
    assert "watch-conditions draft did not run: boom" in capsys.readouterr().err


def test_none_and_empty_list_are_different_answers():
    """"Ran, and this show warrants nothing" is a real result and must not
    read as "never ran" -- the same distinction critique_plan makes."""
    empty = generate.draft_watch_conditions(
        {"channels": []}, "conventions",
        provider=FakeProvider(json.dumps({"watch_conditions": []})))
    assert empty == []
    assert empty is not None


# ---------------------------------------------------------------------------
# the build wiring
# ---------------------------------------------------------------------------


@pytest.fixture
def bundle_dir(tmp_path):
    show = tmp_path / "show"
    show.mkdir()
    (show / "input.csv").write_text((FIXTURES / "touringband.csv").read_text())
    (tmp_path / "conventions.md").write_text((FIXTURES / "touringband.md").read_text())
    return show


def _stub_watchlist(monkeypatch, conditions):
    monkeypatch.setattr(
        "atoo.generate.draft_watch_conditions",
        lambda *args, **kwargs: conditions,
    )


def _build(bundle_dir):
    return main(["build", "--console-model", "wing-compact", "--show", str(bundle_dir),
                 "--conventions", str(bundle_dir.parent / "conventions.md"),
                 "--skip-verify"])


def test_build_writes_the_drafted_watchlist_into_the_bundle(
        stub_build, bundle_dir, monkeypatch, capsys):
    stub_build("touringband")
    _stub_watchlist(monkeypatch, [cond("Kick")])
    _build(bundle_dir)

    written = bundle_dir / "watch.json"
    assert written.is_file()
    # round-trips through the loader a real `watch` run would use
    assert [c["id"] for c in load_watch_conditions(written)] == ["Kick"]
    assert "Watch conditions: 1 drafted condition(s) added" in capsys.readouterr().out


def test_build_merges_rather_than_replacing_a_hand_tuned_watchlist(
        stub_build, bundle_dir, monkeypatch, capsys):
    (bundle_dir / "watch.json").write_text(json.dumps(
        {"watch_conditions": [cond("Kick", severity="error"), cond("mine", "Talkback")]}))
    stub_build("touringband")
    _stub_watchlist(monkeypatch, [cond("Kick"), cond("Crowd", "Crowd L")])
    _build(bundle_dir)

    written = json.loads((bundle_dir / "watch.json").read_text())
    by_id = {c["id"]: c for c in written["watch_conditions"]}
    assert set(by_id) == {"Kick", "mine", "Crowd"}
    assert by_id["Kick"]["severity"] == "error"      # theirs survived
    assert by_id["Crowd"]["source"] == SOURCE_DRAFTED   # the new one is marked
    assert "kept your own version of: Kick" in capsys.readouterr().err


def test_an_unusable_draft_leaves_an_existing_watchlist_untouched(
        stub_build, bundle_dir, monkeypatch):
    original = json.dumps({"watch_conditions": [cond("mine", "Talkback")]})
    (bundle_dir / "watch.json").write_text(original)
    stub_build("touringband")
    _stub_watchlist(monkeypatch, None)          # draft_watch_conditions failed
    _build(bundle_dir)
    assert (bundle_dir / "watch.json").read_text() == original


def test_an_unreadable_watchlist_is_refused_rather_than_overwritten(
        stub_build, bundle_dir, monkeypatch, capsys):
    """Far more likely to be a file someone is mid-edit on than one they
    want replaced by a machine."""
    (bundle_dir / "watch.json").write_text("{ this is not json")
    stub_build("touringband")
    _stub_watchlist(monkeypatch, [cond("Kick")])
    _build(bundle_dir)
    assert (bundle_dir / "watch.json").read_text() == "{ this is not json"
    assert "left untouched" in capsys.readouterr().err


@pytest.mark.parametrize("drafted", [None, [], [cond("Kick")]])
def test_drafting_never_changes_the_exit_code_of_a_good_build(
        drafted, stub_build, bundle_dir, monkeypatch):
    """#91's first review criterion. The plan is the deliverable; the
    watchlist is a convenience and must never cost a build."""
    stub_build("touringband")
    _stub_watchlist(monkeypatch, drafted)
    assert _build(bundle_dir) == 0


def test_a_build_with_no_bundle_drafts_nothing(stub_build, tmp_path, monkeypatch):
    """There is nowhere to put a watchlist without a bundle, and inventing
    a path beside --out is not this feature's job."""
    called = []
    monkeypatch.setattr("atoo.generate.draft_watch_conditions",
                        lambda *a, **k: called.append(1) or [cond("Kick")])
    (tmp_path / "in.csv").write_text((FIXTURES / "touringband.csv").read_text())
    (tmp_path / "c.md").write_text((FIXTURES / "touringband.md").read_text())
    stub_build("touringband")
    main(["build", "--console-model", "wing-compact", "--input", str(tmp_path / "in.csv"), "--conventions", str(tmp_path / "c.md"),
          "--out", str(tmp_path / "p.json"), "--skip-verify"])
    assert not called
    assert not list(tmp_path.glob("watch*.json"))


# ---------------------------------------------------------------------------
# the Setup/Watch UI, which cannot see a top-level key
# ---------------------------------------------------------------------------


def test_saving_from_the_ui_preserves_the_drafted_bookkeeping(tmp_path):
    """`CLAUDE.md`'s browser blind spot, in its exact shape. The editor
    table renders one row per condition and posts those rows back, so a
    TOP-LEVEL key is invisible to it. Dropping `drafted` on save would
    silently undo every deletion: the operator removes a drafted condition
    in this editor, saves, and the next `build --show` puts it straight
    back."""
    fastapi_testclient = require_fastapi_testclient()
    from atoo.webui import create_app

    path = tmp_path / "watch.json"
    path.write_text(json.dumps({
        "watch_conditions": [cond("mine", "Talkback")],
        "drafted": ["Kick", "Crowd"],
    }))

    with fastapi_testclient.TestClient(create_app()) as client:
        r = client.post("/api/watch-conditions/save",
                        json={"path": str(path), "watch_conditions": [cond("mine", "Talkback")]})
        assert r.status_code == 200, r.text

    assert json.loads(path.read_text())["drafted"] == ["Kick", "Crowd"]


def test_a_deleted_draft_stays_deleted_across_a_ui_save_and_a_rebuild(tmp_path):
    """The end-to-end version of the test above, which is the behaviour
    anyone actually cares about."""
    fastapi_testclient = require_fastapi_testclient()
    from atoo.webui import create_app

    path = tmp_path / "watch.json"
    first, _ = merge_drafted_conditions(None, [cond("Kick"), cond("Crowd", "Crowd L")])
    path.write_text(json.dumps(first))

    # the operator deletes "Kick" in the editor and saves
    kept = [c for c in first["watch_conditions"] if c["id"] != "Kick"]
    with fastapi_testclient.TestClient(create_app()) as client:
        assert client.post("/api/watch-conditions/save",
                           json={"path": str(path), "watch_conditions": kept}).status_code == 200

    # the next build drafts the same two conditions again
    after, report = merge_drafted_conditions(
        json.loads(path.read_text()), [cond("Kick"), cond("Crowd", "Crowd L")])
    assert report.dismissed == ("Kick",)
    assert [c["id"] for c in after["watch_conditions"]] == ["Crowd"]
