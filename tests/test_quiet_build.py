"""A clean build of a good conventions file is quiet.

The maintainer rebuilt the Demo with a real model on 2026-10-13 and the
Findings dock read 9 "to check" and 16 notes for a plan that verified
with no errors and no warnings. Each cause is tested here:

* the resolve step's line-coverage check did not recognise a quoted
  list item with a one-word preset name (`- Snare: "Snare"`), nor a
  lead-in line whose items carry it;
* notes that restate the conventions (the Category table obeyed, which
  preset values a plan carries) were counted as choices;
* `build` printed verify's notes after its own account of the same
  presets;
* `build --pretty` called the plan's notes WARNINGS and numbered an aux
  strip as a second channel 1;
* Watch listed L002 for every fader the plan itself puts at the floor.

The end-to-end check replays that build with no model: the generator's
reply recovered from his plan (by a script in the development repository) and his
resolved conventions, both frozen in `tests/fixtures/demo_2026-10-13/`
with the conventions, input list and instructions he built from.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from atoo import audit, conventions_resolve, finding_groups, webui
from atoo.ai_provider import FakeProvider
from atoo.cli import main
from atoo.diagnostics import Severity
from atoo.render import render_plan

FIXTURES = Path(__file__).parent / "fixtures"
DEMO = FIXTURES / "demo_2026-10-13"


# ---------------------------------------------------------------------------
# the resolve step's line coverage
# ---------------------------------------------------------------------------

CONVENTIONS = """\
## Processing
- Default channel presets by source: <!-- a note to me -->
  - Kick: "Kick In"
  - Snare: "Snare"
- Start every monitor send at -18dB.
"""


def _covered(quotes: list[str], conventions: str = CONVENTIONS) -> set[str]:
    """The lines (stripped) of `conventions` the quotes cover."""
    text = conventions_resolve.conventions_for_model(conventions)
    lines = text.splitlines()
    return {lines[i].strip() for i in conventions_resolve._covered_lines(text, quotes)}


def test_a_quoted_list_item_with_a_one_word_name_covers_its_line():
    """`- Snare: "Snare"` is three "words" with its bullet, so it took the
    short-quote path, and that compared the quote WITH its bullet to the
    line without one. Both are compared without it now."""
    covered = _covered(['- Kick: "Kick In"', '- Snare: "Snare"'])
    assert '- Snare: "Snare"' in covered
    assert '- Kick: "Kick In"' in covered


def test_a_lead_in_is_covered_by_its_items():
    covered = _covered(['- Snare: "Snare"'])
    assert any(line.startswith("- Default channel presets by source:") for line in covered)


def test_a_lead_in_whose_items_are_all_uncovered_is_still_uncovered():
    covered = _covered(['Start every monitor send at -18dB.'])
    assert not any(line.startswith("- Default channel presets") for line in covered)


def test_the_minus_of_a_level_is_not_a_bullet():
    """Only a marker followed by a space is a bullet: "-18dB" keeps its
    sign, so a two-word quote "-18dB." is not the line "18dB."."""
    conventions = "## Levels\n- -18dB\n- 18dB\n"
    covered = _covered(["-18dB"], conventions)
    assert "- -18dB" in covered and "- 18dB" not in covered


def test_the_maintainers_resolved_demo_conventions_cover_every_line():
    """The real file: 169 citations, 58 lines, and nine of them read as
    uncovered before the fix (eight preset lines and their lead-in)."""
    result = conventions_resolve.check(
        (DEMO / "conventions.resolved.md").read_text(), (DEMO / "conventions.md").read_text(),
        conventions_name="conventions.md")
    assert result.missing == []
    assert result.uncovered == []


def test_an_uncovered_line_is_an_info_not_a_warning():
    """Decided: the generator reads an uncovered line
    verbatim, so nothing is lost and the board is not at risk."""
    resolved = (DEMO / "conventions.resolved.md").read_text()
    conventions = (DEMO / "conventions.md").read_text() + "\n- Label every wedge with tape.\n"
    result = conventions_resolve.check(resolved, conventions, conventions_name="conventions.md")
    assert result.uncovered == ["- Label every wedge with tape."]
    (finding,) = result.findings
    assert (finding.code, finding.severity) == (conventions_resolve.CODE_UNCOVERED, Severity.INFO)


# ---------------------------------------------------------------------------
# the replayed Demo build
# ---------------------------------------------------------------------------


class _Replay(FakeProvider):
    def __init__(self, watchlist: str = '{"watch_conditions": []}'):
        super().__init__()
        self.watchlist = watchlist

    def complete(self, *, system, user, response_schema=None, label=""):
        if label == "generator":
            self.response = (DEMO / "generator.reply.json").read_text()
        elif label == "resolve":
            self.response = (DEMO / "conventions.resolved.md").read_text().split("-->", 1)[1]
        else:
            self.response = self.watchlist
        return super().complete(system=system, user=user, response_schema=response_schema,
                                label=label)


@pytest.fixture
def replay(tmp_path, monkeypatch):
    """Build the Demo as the maintainer did on 2026-10-13, with no model.
    Returns (exit code, the plan, stdout, stderr) for `extra` arguments."""
    def run(capsys, *extra, watchlist='{"watch_conditions": []}'):
        work = tmp_path / "starter"
        shutil.copytree(DEMO, work, ignore=shutil.ignore_patterns("conventions.resolved.md"))
        # The suite turns the resolve step off (conftest); this build is
        # the one that ran it.
        monkeypatch.setenv("ATOO_RESOLVE", "1")
        monkeypatch.delenv("ATOO_CATEGORY_RULES", raising=False)
        provider = _Replay(watchlist)
        monkeypatch.setattr("atoo.cli.provider_from_env", lambda *a, **k: provider)
        code = main(["build", "--show", str(work / "demo-show"),
                     "--conventions", str(work / "conventions.md"),
                     "--console-model", "wing-compact",
                     "--presets", str(FIXTURES / "channel_presets"), *extra])
        out = capsys.readouterr()
        plan = json.loads((work / "demo-show" / "plan.json").read_text())
        return code, plan, out.out, out.err, work
    return run


def _dock_counts(plan: dict) -> dict:
    """What the Findings dock counts (`shell.js` `dockEntries` and
    `renderFindings`): one row per (severity, code, where) across
    origins; "to check" is every ERROR and WARNING but the critic's;
    "choices" every INFO that is not a build detail."""
    seen, entries = {}, []
    for finding in webui._plan_findings(plan):
        key = (finding["severity"], finding.get("code") or "", finding.get("where") or "")
        origin = finding.get("source")
        if key in seen and origin not in seen[key]:
            seen[key].add(origin)
            continue
        seen.setdefault(key, {origin})
        entries.append(finding)
    infos = [f for f in entries if f["severity"] == "info"]
    return {
        "check": sum(1 for f in entries if f["severity"] in ("error", "warning")
                     and f.get("source") != "critic"),
        "choices": sorted(f["code"] for f in infos if not finding_groups.is_build_detail(f)),
        "details": sorted(f["code"] for f in infos if finding_groups.is_build_detail(f)),
    }


def test_the_replayed_demo_build_is_quiet(replay, capsys):
    code, plan, _out, err, _work = replay(capsys)
    assert code == 0
    counts = _dock_counts(plan)
    assert counts["check"] == 0
    assert len(counts["choices"]) <= 4, counts["choices"]
    # The two that ARE choices, and the two reminders the issue keeps.
    assert counts["choices"] == sorted(["fx.engine-allocated", "fx.insert-switched-on",
                                        "input-list.skipped", "reconcile.from-instructions"])
    # Kept, every one -- under Build details.
    for code_ in ("reply.category-rule", "preset.expanded", "preset.bus-expanded",
                  "fx.inserts", "fx.parameter-typed-from-value"):
        assert code_ in counts["details"]
    assert "resolve: checked conventions.resolved.md: 169 of 169 citation(s) found; " \
           "58 of 58 conventions line(s) covered" in err


def test_build_does_not_print_verifys_build_details_again(replay, capsys):
    _code, _plan, _out, err, _work = replay(capsys)
    verification = err.split("\nVerification: ", 1)[1]
    assert "build details the build reported above, not repeated" in verification
    for code_ in ("(preset.expanded)", "(preset.bus-expanded)", "(fx.inserts)"):
        assert code_ not in verification
    assert "(reconcile.from-instructions)" in verification
    # ...and the build's own preset notes put the choices first.
    assert "Presets -- 2 note(s)" in err and "Presets -- 3 build detail(s)" in err


def test_pretty_lists_notes_not_warnings_and_labels_the_aux(replay, capsys):
    _code, plan, out, _err, _work = replay(capsys, "--pretty")
    assert "WARNINGS (" not in out
    assert "NOTES (1)" in out and "[model] Bus presets" in out.split("NOTES (1)", 1)[1]
    details = out.split("BUILD DETAILS (1)", 1)[1]
    assert "[repair]" in details
    assert "  Aux 1  Music" in out


def test_render_labels_an_aux_strip_and_files_a_repair_note_as_a_detail():
    plan = {"channels": [
        {"channel": 1, "bank": "ch", "name": "Kick", "source": {}, "processing": {},
         "patch": None, "dca": [], "mute_group": [], "bus_sends": []},
        {"channel": 1, "bank": "aux", "name": "Music", "source": {}, "processing": {},
         "patch": None, "dca": [], "mute_group": [], "bus_sends": []},
    ], "busses": {}}
    text = render_plan(plan, [{"text": "a remark", "source": "model"},
                              {"text": "a slip read", "source": "repair"}])
    assert "      1  Kick" in text and "  Aux 1  Music" in text
    assert "NOTES (1)\n  - [model] a remark" in text
    assert "BUILD DETAILS (1)" in text and "[repair] a slip read" in text.split("BUILD DETAILS")[1]


# ---------------------------------------------------------------------------
# L002 on Watch
# ---------------------------------------------------------------------------


def _state(values: dict) -> audit.ConsoleState:
    return audit.ConsoleState(values=values)


def _floor_rig() -> dict:
    """Two named, patched, unmuted channels routed to Main, both faders at
    the floor; a bus at the floor too."""
    values = {}
    for n in (1, 2):
        values.update({f"/ch/{n}/name": f"Ch{n}", f"/ch/{n}/mute": 0,
                       f"/ch/{n}/fdr": -144.0, f"/ch/{n}/in/conn/grp": "A",
                       f"/ch/{n}/in/conn/in": n, f"/ch/{n}/main/1/on": 1})
    values.update({"/bus/1/name": "Drums", "/bus/1/mute": 0, "/bus/1/fdr": -144.0,
                   "/bus/1/main/1/on": 1, "/ch/1/send/1/on": 1, "/ch/1/send/1/lvl": 0.0})
    return values


def _l002(rules, values) -> set[str]:
    return {f.addresses[0] for f in audit.run_audit(_state(values), rules)
            if f.rule_id == "L002"}


def test_sp_l002_is_quiet_on_a_fader_the_plan_puts_at_the_floor(tmp_path):
    values = _floor_rig()
    unbound = _l002(audit.DEFAULT_RULES, values)
    assert {"/ch/1/fdr", "/ch/2/fdr"} <= unbound
    plan = {"channels": [{"channel": 1, "bank": "ch", "fader": {"fader_db": -144}},
                         {"channel": 2, "bank": "ch", "fader": {"fader_db": 0}}],
            "busses": {"Drums": {"index": 1, "fader": {"fader_db": 0}}}}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    bound = _l002(audit.with_plan_rules(audit.DEFAULT_RULES, path), values)
    # ch 1 is at the floor because the plan says so; ch 2 and the bus are
    # not where the plan put them, and are still said.
    assert "/ch/1/fdr" not in bound
    assert {"/ch/2/fdr", "/bus/1/fdr"} <= bound


def test_an_unreadable_plan_leaves_sp_l002_as_it_was(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text("{ not json")
    assert audit.with_plan_rules(audit.DEFAULT_RULES, path) == list(audit.DEFAULT_RULES)


def test_a_repair_note_is_an_info_in_builds_plain_stream():
    """A `repair` note says how a slip in the reply was read --
    a build detail, never a warning. The model's own remark stays one."""
    from atoo.cli import _note_diagnostic

    assert _note_diagnostic({"text": "x", "source": "repair"}).severity == Severity.INFO
    assert _note_diagnostic({"text": "x", "source": "model"}).severity == Severity.WARNING


def test_atoo_watch_on_a_show_binds_sp_l002_to_its_plan(tmp_path, capsys):
    """The CLI's `watch --show` runs the same plan-bound rules as the page."""
    show = tmp_path / "show"
    show.mkdir()
    (show / "input.csv").write_text("name,patch\nCh1,A 1\nCh2,A 2\n")
    (show / "plan.json").write_text(json.dumps({
        "channels": [{"channel": 1, "bank": "ch", "fader": {"fader_db": -144}},
                     {"channel": 2, "bank": "ch", "fader": {"fader_db": 0}}],
        "busses": {"Drums": {"index": 1, "fader": {"fader_db": -144}}}}))
    state = tmp_path / "state.json"
    state.write_text(json.dumps(_floor_rig()))
    main(["watch", "--show", str(show), "--state-sequence", str(state), "--count", "1",
          "--interval", "0"])
    out = capsys.readouterr().out
    # Unbound, it reads `L002 ... (3)  CH 1 "Ch1", CH 2 "Ch2", BUS 1 "Drums"`.
    block = out.split("L002 Active Strip Fader At Floor", 1)[1].split("\n\n", 1)[0]
    assert 'CH 2 "Ch2"' in block
    assert 'CH 1 "Ch1"' not in block and 'BUS 1 "Drums"' not in block
