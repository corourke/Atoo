"""`atoo lessons` (docs/developer/build-lessons-2026-09-27.md, part C):
a read-only report over one bundle's build log and findings, optionally
alongside its git history of `plan.json`.

Every fixture plan here is built IN the test or frozen into
`tests/fixtures/`: nothing here reads the contents of a bundle under
`examples/`, which is a living example, not a test fixture.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from atoo import lessons


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _minimal_plan(**overrides: dict) -> dict:
    plan = {
        "channels": [{"channel": 1, "bank": "A", "name": "Tom3", "source": {},
                      "patch": {}, "processing": {}, "fader": {}, "dca": None,
                      "mute_group": None, "bus_sends": [], "main_routes": []}],
        "dcas": {}, "mute_groups": {}, "busses": {}, "outputs": {},
        "unassigned_inputs": [], "notes": [],
    }
    plan.update(overrides)
    return plan


def test_a_plan_with_no_build_log_at_all_still_gathers_cleanly(tmp_path):
    """Old plans without `meta.build_log` load everywhere -- including
    here, where the report is simply empty of build-log items."""
    (tmp_path / "plan.json").write_text(json.dumps(_minimal_plan()))
    report = lessons.gather(tmp_path)
    assert report.sources == ["current"]
    assert report.git_note is None
    assert all(i.kind != "build_log" for i in report.items)


def test_a_directory_with_no_plan_json_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        lessons.gather(tmp_path)


def test_a_non_git_directory_says_so_and_reads_only_the_current_plan(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps(_minimal_plan()))
    report = lessons.gather(tmp_path, git_n=3)
    assert report.sources == ["current"]
    assert report.git_note is not None and "not a git repository" in report.git_note


def test_items_from_plan_covers_every_named_source():
    """One of each source the design lists, all in one plan, each
    produces at least one item -- build-log notes, critic findings,
    build findings, conventions_audit, inferred markers, the plan's own
    notes, and verify findings."""
    plan = _minimal_plan(
        meta={
            "build_log": {"generator": {"notes": [{"t": 1.0, "text": "Considering Tom3."}],
                                        "usage": {}}},
            "critic_findings": [{"severity": "warning", "code": "critic.intent",
                                 "message": "Tom3 send looks off", "category": "intent"}],
            "build_findings": [{"severity": "info", "code": "conventions.conflict",
                                "message": "Tom3 rule conflict noted"}],
            "verify_findings": {"errors": [], "warnings": [
                {"severity": "warning", "code": "value.unknown",
                 "message": "Tom3 gain is unusual"}], "info": []},
        },
        conventions_audit=[{"kind": "conflict", "message": "Tom3 vs Tom4 ordering unclear"}],
        notes=[{"text": "Tom3 assumed to be a rack tom", "source": "model"}],
    )
    plan["channels"][0]["inferred"] = [{"field": "stereo", "basis": "single source"}]
    items = lessons.items_from_plan(plan, "current")
    kinds = {i.kind for i in items}
    assert kinds == {"build_log", "critic", "build_finding", "conventions_audit",
                     "inferred", "note", "verify"}
    # Every item mentions Tom3, so every item is filed under it.
    assert all(i.topic == "Tom3" for i in items)


@pytest.mark.parametrize("names", [["Strings", "Guitars"], ["Guitars", "Strings"]])
def test_topic_for_does_not_depend_on_the_order_names_arrive_in(names):
    """Two names of one length in one note: the earlier in the text wins,
    whichever order the set hands them over. Before this, the festival
    bundle printed "## Strings" first on one run and "## Guitars" on the
    next, depending on the interpreter's hash seed."""
    text = "Guitars get an 80Hz high-pass, and Strings the same"
    assert lessons._topic_for(text, names) == "Guitars"
    assert lessons._topic_for("Kick In is not Kick", ["Kick", "Kick In"]) == "Kick In"


def test_lessons_ranks_a_topic_that_recurs_across_two_committed_plans(tmp_path):
    """A topic raised in both the current plan and an older committed
    version outranks one raised only once."""
    _run(["git", "init", "-q"], tmp_path)
    _run(["git", "config", "user.email", "t@example.com"], tmp_path)
    _run(["git", "config", "user.name", "Test"], tmp_path)

    older = _minimal_plan(notes=[{"text": "Tom3 assumed rack, per input order", "source": "model"}])
    (tmp_path / "plan.json").write_text(json.dumps(older))
    _run(["git", "add", "plan.json"], tmp_path)
    _run(["git", "commit", "-q", "-m", "older build"], tmp_path)

    current = _minimal_plan(notes=[
        {"text": "Tom3 assumed rack, per input order", "source": "model"},
        {"text": "Overheads: no ambiguity here", "source": "model"},
    ])
    (tmp_path / "plan.json").write_text(json.dumps(current))
    _run(["git", "add", "plan.json"], tmp_path)
    _run(["git", "commit", "-q", "-m", "current build"], tmp_path)

    report = lessons.gather(tmp_path, git_n=5)
    # "current" (the working copy) plus both commits git already has for
    # plan.json -- the newest of those two happens to match "current"'s
    # content byte for byte, and is read anyway: git_n counts committed
    # VERSIONS, not "versions distinct from the working copy".
    assert len(report.sources) == 3
    assert report.git_note is None
    # The recurring topic (raised in both builds) ranks first, ahead of
    # the one-off "Overheads" item from the latest build alone.
    assert report.topics[0].name == "Tom3"
    # Raised in the current plan AND both committed versions (the older
    # build, and the newer commit whose content "current" also is).
    assert len(report.topics[0].sources) == 3
    assert len(report.topics[0].items) > len(report.topics[1].items)


def test_git_n_limits_how_many_older_versions_are_read(tmp_path):
    _run(["git", "init", "-q"], tmp_path)
    _run(["git", "config", "user.email", "t@example.com"], tmp_path)
    _run(["git", "config", "user.name", "Test"], tmp_path)
    for i in range(4):
        (tmp_path / "plan.json").write_text(json.dumps(_minimal_plan(notes=[
            {"text": f"build number {i}", "source": "model"}])))
        _run(["git", "add", "plan.json"], tmp_path)
        _run(["git", "commit", "-q", "-m", f"build {i}"], tmp_path)

    report = lessons.gather(tmp_path, git_n=2)
    # "current" plus at most 2 older committed versions.
    assert len(report.sources) == 3


def _write_build_log_file(directory: Path, name: str, *, notes: list[dict]) -> None:
    (directory / "builds").mkdir(exist_ok=True)
    (directory / "builds" / name).write_text(json.dumps({
        "generated_at": "2026-09-28T00:00:00+00:00", "console_model": "wing-compact",
        "conventions_stack": [], "model": None, "effort": None,
        "outcome": {"status": "done", "reason": None},
        "build_log": {"generator": {"notes": notes, "usage": {}}},
    }))


def test_gather_reads_every_file_in_build_logs(tmp_path):
    """Each build's log lives in its own file under
    `builds/`, not inline in `meta.build_log`. `gather()` reads
    every one of them, newest first, as its own source."""
    (tmp_path / "plan.json").write_text(json.dumps(_minimal_plan()))
    _write_build_log_file(tmp_path, "2026-09-28T10-00-00Z.json",
                          notes=[{"t": 1.0, "text": "Tom3 send looks unusual."}])
    _write_build_log_file(tmp_path, "2026-09-28T11-00-00Z.json",
                          notes=[{"t": 2.0, "text": "Tom3 send still looks unusual."}])

    report = lessons.gather(tmp_path)
    assert report.sources == ["current", "2026-09-28T11-00-00Z", "2026-09-28T10-00-00Z"]
    build_log_items = [i for i in report.items if i.kind == "build_log"]
    assert len(build_log_items) == 2
    assert all(i.role == "generator" for i in build_log_items)
    assert report.topics[0].name == "Tom3"
    assert len(report.topics[0].sources) == 2


def test_last_n_limits_how_many_build_log_files_are_read(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps(_minimal_plan()))
    for i in range(4):
        _write_build_log_file(tmp_path, f"2026-09-28T{10 + i:02d}-00-00Z.json",
                              notes=[{"t": 1.0, "text": f"note {i}"}])

    report = lessons.gather(tmp_path, last_n=2)
    build_log_items = [i for i in report.items if i.kind == "build_log"]
    assert len(build_log_items) == 2
    # Newest first.
    assert report.sources[1:] == ["2026-09-28T13-00-00Z", "2026-09-28T12-00-00Z"]


def test_a_plan_with_only_the_old_inline_build_log_still_gathers(tmp_path):
    """A plan built before an earlier change still carries `meta.build_log`
    inline, with no `builds/` folder at all -- `gather()` still
    mines it, via `items_from_plan`'s own reading of that shape."""
    plan = _minimal_plan(meta={"build_log": {
        "generator": {"notes": [{"t": 1.0, "text": "Tom3 inline note."}], "usage": {}}}})
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    report = lessons.gather(tmp_path)
    build_log_items = [i for i in report.items if i.kind == "build_log"]
    assert len(build_log_items) == 1
    assert build_log_items[0].source == "current"


def test_render_text_and_json_both_cover_every_topic(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps(_minimal_plan(
        notes=[{"text": "Tom3 assumed rack", "source": "model"}])))
    report = lessons.gather(tmp_path)
    text = lessons.render_text(report)
    assert "Tom3" in text
    data = json.loads(lessons.render_json(report))
    assert data["topics"][0]["topic"] == "Tom3"
    assert data["sources"] == ["current"]


# -- "Where the thinking went" (docs/developer/build-cost-reduction.md, slice D)

FIXTURE_LOG = Path(__file__).parent / "fixtures" / "lessons_thinking.build-log.json"


@pytest.mark.parametrize("text, bucket", [
    ("Counting the channels on LCL", "mechanical"),
    ("Numbering the busses in order", "mechanical"),
    ("37 channels × 4 monitor busses = 148 sends", "mechanical"),
    ("Sockets 1-24 are LCL", "mechanical"),
    ("Vocals overflow to AES50-A", "mechanical"),
    ("All 38 channels seem accounted for", "judgement"),     # not "count"
    ("Does that rule apply to the busses too?", "conventions"),
    ("What 'Band' means as a mute group", "conventions"),
    ("These two conventions conflict", "conventions"),
    ("The schema has no index field for a bus", "prompt"),
    ("Is null allowed here?", "prompt"),
    ("OH L - drums, Mic, SM81, phantom required", "judgement"),  # an input row
    ("A required field in the plan", "prompt"),
    ("Assembling the final JSON", "writing"),
    ("Kick gets a 40Hz high-pass", "judgement"),
])
def test_bucket_for_files_a_note_by_its_seed_keywords(text, bucket):
    assert lessons._bucket_for(text) == bucket


def test_thinking_time_charges_each_note_the_gap_before_it():
    """Each note is charged the seconds since the note before it (the
    call's start for the first): a summary describes the thinking that
    led up to it. The fixture's generator notes are at t=10, 30, 35, 45,
    50, 50, 60, so judgement gets 10 + 0 + 10, mechanical 20, conventions
    5, prompt 10 and writing 5, of 60 seconds."""
    entry = json.loads(FIXTURE_LOG.read_text())
    roles = lessons.thinking_time(entry["build_log"])
    assert list(roles) == ["generator", "critic"]      # watchlist has no notes
    gen = roles["generator"]
    assert gen.notes == 7
    assert gen.total == pytest.approx(60.0)
    assert gen.seconds == pytest.approx({"mechanical": 20.0, "conventions": 5.0,
                                         "prompt": 10.0, "writing": 5.0,
                                         "judgement": 20.0})
    assert gen.share("mechanical") == pytest.approx(1 / 3)
    critic = roles["critic"]
    assert critic.seconds["mechanical"] == pytest.approx(4.0)
    assert critic.seconds["judgement"] == pytest.approx(4.0)


def test_thinking_time_never_charges_a_negative_or_unreadable_gap():
    roles = lessons.thinking_time({"generator": {"notes": [
        {"t": 10.0, "text": "judgement a"},
        {"t": 5.0, "text": "counting b"},       # t went backwards: 0 s
        {"text": "no t at all"},                 # skipped
        {"t": 12.0, "text": "judgement c"},
    ]}})
    gen = roles["generator"]
    assert gen.notes == 3
    assert gen.seconds["mechanical"] == 0.0
    assert gen.total == pytest.approx(12.0)


def test_gather_reports_thinking_time_per_build_in_text_and_json(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps(_minimal_plan()))
    logs = tmp_path / "builds"
    logs.mkdir()
    (logs / "2026-09-28T12-00-00Z.json").write_text(FIXTURE_LOG.read_text())

    report = lessons.gather(tmp_path)
    assert [b.source for b in report.thinking_time] == ["2026-09-28T12-00-00Z"]

    text = lessons.render_text(report)
    assert "## Where the thinking went" in text
    assert "generator    60.0s over   7 note(s): mechanical 33%, conventions 8%, " \
           "prompt 17%, writing 8%, judgement 33%" in text

    data = json.loads(lessons.render_json(report))
    [build] = data["thinking_time"]
    assert build["source"] == "2026-09-28T12-00-00Z"
    assert build["roles"]["generator"]["seconds"] == 60.0
    assert build["roles"]["generator"]["buckets"]["mechanical"] == {"seconds": 20.0, "share": 0.333}
    assert set(build["roles"]) == {"generator", "critic"}


def test_an_inline_build_log_on_the_current_plan_is_timed_too(tmp_path):
    entry = json.loads(FIXTURE_LOG.read_text())
    (tmp_path / "plan.json").write_text(json.dumps(_minimal_plan(
        meta={"build_log": entry["build_log"]})))
    report = lessons.gather(tmp_path)
    assert [b.source for b in report.thinking_time] == ["current"]


def test_no_notes_means_no_thinking_time_section(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps(_minimal_plan(
        notes=[{"text": "Tom3 assumed rack", "source": "model"}])))
    report = lessons.gather(tmp_path)
    assert report.thinking_time == []
    assert "Where the thinking went" not in lessons.render_text(report)
    assert json.loads(lessons.render_json(report))["thinking_time"] == []
