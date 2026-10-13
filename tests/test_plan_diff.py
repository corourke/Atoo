"""A rebuild says what changed against the plan it replaced (FR-1.4).

`tests/fixtures/rebuild_diff/` holds two frozen plans: the packaged Demo
show built from its recorded reply, then rebuilt after one edit -- the
`Guest Vox` row un-skipped in the input list and named in the Vox Wedge
line of instructions.md -- with a reply that also, unasked, turned the
Bass DI's gain from 20 to 26 dB. Between them: an asked-for change (the
added strip), a change nobody asked for (Bass DI), and a renumbered strip
(Playback, pushed from CH 13 to CH 14).
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from atoo import cli, plan_diff
from atoo.ai_provider import FakeProvider
from atoo.input_list import InputRow

FIXTURES = Path(__file__).parent / "fixtures" / "rebuild_diff"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def previous() -> dict:
    return _load("previous.plan.json")


@pytest.fixture
def current() -> dict:
    return _load("current.plan.json")


def _by_label(changes: plan_diff.PlanChanges) -> dict:
    return {s.label: s for s in changes.strips}


# ---- the two frozen plans --------------------------------------------------

def test_the_frozen_rebuild_has_exactly_the_three_changes(previous, current):
    changes = plan_diff.compare(previous, current)
    assert sorted((s.label, s.kind, s.severity) for s in changes.strips) == [
        ("CH 13 Guest Vox", "added", "INFO"),
        ("CH 14 Playback", "moved", "INFO"),
        ("CH 6 Bass DI", "changed", "WARNING"),
    ]
    assert changes.counts() == {"added": 1, "removed": 0, "changed": 1, "moved": 1,
                                "unasked": 1}


def test_an_asked_for_change_is_info_and_says_why(previous, current):
    guest = _by_label(plan_diff.compare(previous, current))["CH 13 Guest Vox"]
    assert guest.severity == "INFO"
    assert "a row it is made from changed" in guest.reason
    # The Vox Wedge line names it too -- through the bus it sends to.
    assert "a conventions line about it changed" in guest.reason


def test_a_change_nobody_asked_for_is_a_warning_never_an_error(previous, current):
    bass = _by_label(plan_diff.compare(previous, current))["CH 6 Bass DI"]
    assert bass.severity == "WARNING"
    assert [v.text() for v in bass.values] == ["gain 20 -> 26 dB"]
    assert bass.reason == "nothing in the input list or the conventions about it changed"


def test_a_renumbered_strip_is_moved_not_removed_and_added(previous, current):
    playback = _by_label(plan_diff.compare(previous, current))["CH 14 Playback"]
    assert playback.kind == "moved"
    assert playback.moved_from == "CH 13"
    assert playback.values == []
    assert playback.severity == "INFO"   # a row was added before it
    assert playback.slot == ("ch", 14)


def test_the_plan_keeps_the_comparison_it_was_built_with(previous, current):
    kept = current["meta"][plan_diff.CHANGES_KEY]
    again = plan_diff.compare(previous, current).to_dict(against="plan.previous.json")
    assert kept == json.loads(json.dumps(again))


def test_meta_is_ignored(previous):
    later = copy.deepcopy(previous)
    later["meta"]["generated_at"] = "2099-01-01T00:00:00+00:00"
    later["meta"]["verify_findings"] = ["anything"]
    assert plan_diff.compare(previous, later).strips == []


def test_render_is_one_line_per_strip_warnings_first(previous, current):
    lines = plan_diff.compare(previous, current).render()
    assert lines[0] == ("Changed since the last build -- 3 strips against plan.previous.json: "
                        "1 added, 1 changed, 1 moved; 1 not asked for")
    assert lines[1].split()[:4] == ["WARNING", "CH", "6", "Bass"]
    assert "CH 6 Bass DI: gain 20 -> 26 dB" in lines[1]
    assert lines[3].strip() == "INFO     CH 13 Guest Vox: added"
    assert lines[4].strip() == "INFO     CH 14 Playback: moved from CH 13"
    assert any("graded by what each strip is made from" in line for line in lines)


def test_render_all_values_lists_every_value_and_every_reason(previous, current):
    text = "\n".join(plan_diff.compare(previous, current).render(all_values=True))
    assert "CH 6 Bass DI: 1 value changed" in text
    assert "\n             gain 20 -> 26 dB" in text
    assert "input-list rows were added, removed or reordered" in text


# ---- the comparison on small plans ---------------------------------------

def _row(name, category="vocals", **kw):
    return InputRow(name=name, category=category, type="Mic", phantom=False, **kw)


def _channel(number, name, **kw):
    ch = {"channel": number, "bank": "ch", "name": name,
          "source": {"input": name, "stereo": False},
          "patch": {"group": "A", "sockets": [number], "stated": False},
          "processing": {"hpf_hz": 80, "gain_db": 20}, "fader": {"fader_db": -144},
          "dca": [], "mute_group": [], "bus_sends": [], "main_routes": []}
    ch.update(kw)
    return ch


def _plan(channels, rows, conventions="# House\n- Vocals HPF 100 Hz.\n", busses=None,
          dcas=None, console="wing-compact"):
    plan = {"channels": channels, "busses": busses or {}, "dcas": dcas or {},
            "mute_groups": {}, "outputs": {}, "notes": []}
    plan["meta"] = {"console_model": console,
                    plan_diff.BASIS_KEY: plan_diff.basis(plan, rows,
                                                         [("conventions", conventions)])}
    return plan


ROWS = [_row("Kick", "drums"), _row("Snare", "drums"), _row("Lead Vox")]


def _three():
    return [_channel(1, "Kick"), _channel(2, "Snare"), _channel(3, "Lead Vox")]


def test_identical_plans_have_no_changes_and_say_so():
    a, b = _plan(_three(), ROWS), _plan(_three(), ROWS)
    changes = plan_diff.compare(a, b)
    assert changes.strips == []
    assert changes.render() == ["Changed since the last build: nothing -- every strip "
                                "matches plan.previous.json."]


def test_a_changed_row_makes_its_strip_change_info():
    rows2 = [ROWS[0], _row("Snare", "drums", model="SM57"), ROWS[2]]
    b = _three()
    b[1]["processing"]["hpf_hz"] = 100
    changes = plan_diff.compare(_plan(_three(), ROWS), _plan(b, rows2))
    (snare,) = changes.strips
    assert (snare.label, snare.severity) == ("CH 2 Snare", "INFO")
    assert snare.reason == "a row it is made from changed"
    assert [v.text() for v in snare.values] == ["HPF 80 -> 100 Hz"]


def test_a_conventions_line_naming_the_category_makes_the_change_info():
    b = _three()
    b[2]["processing"]["hpf_hz"] = 120
    b[0]["processing"]["hpf_hz"] = 60
    changes = plan_diff.compare(
        _plan(_three(), ROWS),
        _plan(b, ROWS, conventions="# House\n- Vocals HPF 120 Hz.\n"))
    got = {s.label: s.severity for s in changes.strips}
    assert got == {"CH 3 Lead Vox": "INFO", "CH 1 Kick": "WARNING"}


def test_a_line_naming_a_bus_reaches_the_channels_that_send_to_it():
    send = [{"bus": "Vox Wedge", "mode": "pre", "level_db": -18}]
    louder = [{"bus": "Vox Wedge", "mode": "pre", "level_db": -12}]
    bus = {"Vox Wedge": {"index": 1, "mono": True}}
    a = _three()
    a[2]["bus_sends"] = send
    b = _three()
    b[2]["bus_sends"] = louder
    changes = plan_diff.compare(
        _plan(a, ROWS, busses=bus),
        _plan(b, ROWS, busses=bus, conventions="# House\n- Vocals HPF 100 Hz.\n"
                                                 "- Vox Wedge sends at -12.\n"))
    (vox,) = changes.strips
    assert vox.severity == "INFO"
    assert [v.text() for v in vox.values] == ["send to Vox Wedge level -18 -> -12 dB"]


def test_a_changed_line_that_names_no_strip_makes_every_change_asked_for():
    b = _three()
    b[0]["fader"]["fader_db"] = -10
    changes = plan_diff.compare(
        _plan(_three(), ROWS),
        _plan(b, ROWS, conventions="# House\n- Vocals HPF 100 Hz.\n- Faders start at -10.\n"))
    (kick,) = changes.strips
    assert kick.severity == "INFO"
    assert kick.reason == "the conventions changed"
    assert any("names no particular strip" in n and "Faders start at -10." in n
               for n in changes.notes)


def test_a_comment_edit_changes_nothing():
    b = _three()
    b[0]["fader"]["fader_db"] = -10
    changes = plan_diff.compare(
        _plan(_three(), ROWS),
        _plan(b, ROWS, conventions="# House\n<!-- a note -->\n- Vocals  HPF 100 Hz.\n"))
    assert [s.severity for s in changes.strips] == ["WARNING"]


def test_a_move_with_nothing_behind_it_is_a_warning():
    b = [_channel(1, "Kick"), _channel(3, "Snare"), _channel(2, "Lead Vox")]
    for ch in b:
        ch["patch"]["sockets"] = [{"Kick": 1, "Snare": 2, "Lead Vox": 3}[ch["name"]]]
    changes = plan_diff.compare(_plan(_three(), ROWS), _plan(b, ROWS))
    assert sorted((s.label, s.kind, s.moved_from, s.severity) for s in changes.strips) == [
        ("CH 2 Lead Vox", "moved", "CH 3", "WARNING"),
        ("CH 3 Snare", "moved", "CH 2", "WARNING"),
    ]


def test_removed_strip_and_a_rename_matched_by_slot():
    rows2 = [ROWS[0], ROWS[1]]
    b = _three()[:2]
    dcas_a = {"Band": {"index": 1}}
    dcas_b = {"All": {"index": 1}}
    changes = plan_diff.compare(_plan(_three(), ROWS, dcas=dcas_a),
                                _plan(b, rows2, dcas=dcas_b))
    got = {s.label: (s.kind, s.severity, s.summary()) for s in changes.strips}
    assert got["CH 3 Lead Vox"] == ("removed", "INFO", "removed")
    # Nothing in the input list or conventions names either DCA.
    assert got["DCA 1 All"] == ("changed", "WARNING", "name Band -> All")


def test_prose_and_bookkeeping_are_not_changes():
    b = _three()
    b[0]["provenance"] = {"processing": "reworded"}
    b[0]["inferred"] = [{"field": "fader", "basis": "x"}]
    b[0]["source"]["quote"] = "a different sentence"
    assert plan_diff.compare(_plan(_three(), ROWS), _plan(b, ROWS)).strips == []


def test_a_preset_file_that_changed_is_asked_for():
    a, b = _three(), _three()
    a[0]["processing"]["preset_values"] = {"file": "Kick.chn", "sha256": "a" * 64,
                                           "library": "/one", "leaves": {"x": 1}}
    b[0]["processing"]["preset_values"] = {"file": "Kick.chn", "sha256": "b" * 64,
                                           "library": "/two", "leaves": {"x": 2}}
    (kick,) = plan_diff.compare(_plan(a, ROWS), _plan(b, ROWS)).strips
    assert kick.severity == "INFO"
    assert kick.reason == "its preset file changed"
    # Compared as the file, not leaf by leaf, and not by where the library is.
    assert [v.path for v in kick.values] == ["processing.preset_values"]


def test_a_preset_library_that_only_moved_is_no_change():
    a, b = _three(), _three()
    a[0]["processing"]["preset_values"] = {"file": "K.chn", "sha256": "a" * 64,
                                           "library": "/one"}
    b[0]["processing"]["preset_values"] = {"file": "K.chn", "sha256": "a" * 64,
                                           "library": "/two"}
    assert plan_diff.compare(_plan(a, ROWS), _plan(b, ROWS)).strips == []


def test_a_send_added_is_one_change_with_its_settings():
    b = _three()
    b[0]["bus_sends"] = [{"bus": "Drum IEM", "mode": "pre", "level_db": -18}]
    (kick,) = plan_diff.compare(_plan(_three(), ROWS), _plan(b, ROWS)).strips
    assert [v.text() for v in kick.values] == ["send to Drum IEM added (pre, -18 dB)"]


def test_dca_membership_reads_as_added_and_removed_names():
    a, b = _three(), _three()
    a[0]["dca"] = ["Drums"]
    b[0]["dca"] = ["Band", "Kit"]
    (kick,) = plan_diff.compare(_plan(a, ROWS), _plan(b, ROWS)).strips
    assert [v.text() for v in kick.values] == ["DCA +Band +Kit -Drums"]


def test_a_console_model_change_makes_every_change_asked_for():
    b = _three()
    b[0]["fader"]["fader_db"] = -10
    changes = plan_diff.compare(_plan(_three(), ROWS), _plan(b, ROWS, console="wing-full"))
    assert [s.severity for s in changes.strips] == ["INFO"]
    assert any("console model changed" in n for n in changes.notes)


# ---- a replaced plan built before there was a basis ------------------------


def _without_basis(plan, input_sha="i1", conv_sha="c1"):
    plan = copy.deepcopy(plan)
    plan["meta"].pop(plan_diff.BASIS_KEY)
    plan["meta"]["input_list"] = {"sha256": input_sha}
    plan["meta"]["conventions_stack"] = [{"role": "conventions", "sha256": conv_sha}]
    return plan


def test_no_basis_and_unchanged_files_means_every_change_is_unasked():
    b = _plan(_three(), ROWS)
    b["channels"][0]["fader"]["fader_db"] = -10
    b["meta"]["input_list"] = {"sha256": "i1"}
    b["meta"]["conventions_stack"] = [{"role": "conventions", "sha256": "c1"}]
    changes = plan_diff.compare(_without_basis(_plan(_three(), ROWS)), b)
    assert [s.severity for s in changes.strips] == ["WARNING"]
    assert any("unchanged" in n for n in changes.notes)


def test_no_basis_and_a_changed_file_means_every_change_is_asked_for():
    b = _plan(_three(), ROWS)
    b["channels"][0]["fader"]["fader_db"] = -10
    b["meta"]["input_list"] = {"sha256": "i2"}
    b["meta"]["conventions_stack"] = [{"role": "conventions", "sha256": "c1"}]
    changes = plan_diff.compare(_without_basis(_plan(_three(), ROWS)), b)
    assert [s.severity for s in changes.strips] == ["INFO"]
    assert any("the input list changed" in n for n in changes.notes)


# ---- the basis -------------------------------------------------------------

def test_the_basis_records_rows_channels_and_lines():
    plan = {"channels": [_channel(1, "Kick")]}
    got = plan_diff.basis(plan, [ROWS[0]], [("conventions", "# H\n<!-- x -->\n\n-  a   b\n")])
    assert list(got["rows"]) == ["kick"]
    assert got["rows"]["kick"]["category"] == "drums"
    assert got["channels"] == {"ch:1": ["kick"]}
    assert got["conventions"] == {"conventions": ["# H", "- a b"]}
    # Any column of the row changes its fingerprint, the notes included.
    assert plan_diff.row_fingerprint(ROWS[0]) != plan_diff.row_fingerprint(
        _row("Kick", "drums", notes="inside"))


# ---- the CLI ---------------------------------------------------------------

class _Recorded(FakeProvider):
    """The generator answers with `reply`; the watchlist drafter with an
    empty draft."""
    reply = ""

    def complete(self, *, system, user, response_schema=None, label=""):
        self.response = self.reply if label == "generator" else '{"watch_conditions": []}'
        return super().complete(system=system, user=user,
                                response_schema=response_schema, label=label)


DEMO = FIXTURES / "demo"


def _demo_bundle(tmp_path, monkeypatch):
    """A scratch show bundle from the frozen Demo inputs (`fixtures/
    rebuild_diff/demo/`), the recorded reply as the generator, and the
    `build` argv. No preset library: the comparison does not need one."""
    show = tmp_path / "demo-show"
    show.mkdir()
    shutil.copy(DEMO / "input.csv", show / "input.csv")
    shutil.copy(DEMO / "instructions.md", show / "instructions.md")
    shutil.copy(DEMO / "conventions.md", tmp_path / "conventions.md")
    provider = _Recorded()
    provider.reply = (DEMO / "reply.json").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "provider_from_env", lambda *a, **k: provider)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    argv = ["build", "--show", str(show), "--conventions", str(tmp_path / "conventions.md"),
            "--console-model", "wing-compact", "--no-resolve", "--no-category-rules"]
    return show, provider, argv


def test_build_ends_with_the_changes_and_a_first_build_says_nothing(tmp_path, monkeypatch, capsys):
    """The Demo, built, rebuilt unchanged, then edited and rebuilt through
    `atoo build` -- the run the two frozen plans were taken from.
    The edit is frozen too (`*.after.*`), so nothing here depends on the
    shipped Demo's text."""
    show, provider, argv = _demo_bundle(tmp_path, monkeypatch)

    assert cli.main(argv) == 0
    first = capsys.readouterr().err
    assert "Changed since the last build" not in first
    plan = json.loads((show / "plan.json").read_text())
    assert plan_diff.BASIS_KEY in plan["meta"]
    assert plan_diff.CHANGES_KEY not in plan["meta"]

    # Rebuilt with nothing edited and the same reply: nothing changed.
    assert cli.main(argv) == 0
    assert ("Changed since the last build: nothing -- every strip matches "
            "plan.previous.json.") in capsys.readouterr().err

    provider.reply = (DEMO / "reply.after.json").read_text(encoding="utf-8")
    shutil.copy(DEMO / "input.after.csv", show / "input.csv")
    shutil.copy(DEMO / "instructions.after.md", show / "instructions.md")

    assert cli.main(argv + ["--all-changes"]) == 0
    err = capsys.readouterr().err
    section = err[err.index("Changed since the last build"):]
    assert section.splitlines()[0] == (
        "Changed since the last build -- 3 strips against plan.previous.json: "
        "1 added, 1 changed, 1 moved; 1 not asked for")
    assert "WARNING  CH 6 Bass DI: 1 value changed" in section
    assert "gain 20 -> 26 dB" in section
    kept = json.loads((show / "plan.json").read_text())["meta"][plan_diff.CHANGES_KEY]
    assert kept["counts"]["unasked"] == 1
    assert kept["against"] == "plan.previous.json"


@pytest.mark.parametrize("broken", ["basis", "to_dict", "render", "compare"])
def test_a_failure_in_the_comparison_is_a_warning_and_the_build_goes_on(
        tmp_path, monkeypatch, capsys, broken):
    show, _provider, argv = _demo_bundle(tmp_path, monkeypatch)
    assert cli.main(argv) == 0
    capsys.readouterr()

    def boom(*a, **k):
        raise RuntimeError("boom")

    target = {"basis": (plan_diff, "basis"), "compare": (plan_diff, "compare"),
              "to_dict": (plan_diff.PlanChanges, "to_dict"),
              "render": (plan_diff.PlanChanges, "render")}[broken]
    monkeypatch.setattr(*target, boom)
    assert cli.main(argv) == 0
    err = capsys.readouterr().err
    assert "WARNING could not" in err and "boom" in err
    assert (show / "plan.json").is_file()


def test_nothing_changed_still_prints_how_it_was_graded():
    """The replaced plan has no basis (the shipped Demo's, built before
    one existed): the fallback note prints even when no strip changed."""
    b = _plan(_three(), ROWS)
    b["meta"]["input_list"] = {"sha256": "i1"}
    b["meta"]["conventions_stack"] = [{"role": "conventions", "sha256": "c1"}]
    lines = plan_diff.compare(_without_basis(_plan(_three(), ROWS)), b).render()
    assert lines[0].startswith("Changed since the last build: nothing")
    assert any("has no record of what each strip was made from" in line for line in lines)


def test_a_rewrapped_line_or_a_heading_does_not_make_everything_asked_for():
    b = _three()
    b[0]["fader"]["fader_db"] = -10
    old = "# House\n- Vocals HPF 100 Hz.\n- Monitor sends are pre-fader and start at -18 dB.\n"
    new = ("# House rules\n- Vocals HPF 100 Hz.\n- Monitor sends are pre-fader\n"
           "  and start at -18 dB.\n")
    changes = plan_diff.compare(_plan(_three(), ROWS, conventions=old),
                                _plan(b, ROWS, conventions=new))
    assert [s.severity for s in changes.strips] == ["WARNING"]
    assert any("only re-wrap text or are headings" in n for n in changes.notes)


def test_a_build_outside_a_bundle_compares_nothing(tmp_path):
    assert cli._changes_since_previous(None, tmp_path / "x.plan.json", {}) is None

