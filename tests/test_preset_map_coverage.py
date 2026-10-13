"""Preset-map lines are covered by the preset library, not by
whether the resolver happened to cite them.

The maintainer's real-model Demo build of a copy of `starter/` on
2026-10-13 showed ten `resolve.line-not-covered` notes, every one a line
of the preset map under "Default channel presets by source" (`- Kick:
"Kick In"` ...). The resolver cited some of the map's lines (Bass, Perc)
and not others, so the notes came and went with the model's run, and
told him to "make the line clearer" about lines that were clear and took
effect. His conventions and the resolved file that run wrote are frozen
in `tests/fixtures/preset_map_2026-10-13/`; the library is the frozen
starter set, `tests/fixtures/channel_presets/` (byte for byte the
`presets/` in his bundle).
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

from atoo import conventions_resolve
from atoo.cli import main
from atoo.presets import PresetLibrary

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BUNDLE = FIXTURES / "preset_map_2026-10-13"
LIBRARY = FIXTURES / "channel_presets"

# The ten lines his build listed, as the note quoted them.
UNCITED_MAP_LINES = [
    '- Kick: "Kick In"',
    '- Snare: "Snare"',
    '- Hi-hat: "HiHat"',
    '- Toms: "H Tom" for the high (or only) rack tom, "M Tom" for a second rack tom, '
    '"Fl Tom" for the floor tom.',
    '- Overheads: "OH"',
    '- Trumpet: "Trumpet"',
    '- Trombone: "T Bone"',
    '- Alto sax: "A Sax"',
    '- Baritone sax: "B Sax"',
    '- Tenor sax: "B Sax"',
]


def _check(conventions: str, resolved: str, library=None):
    return conventions_resolve.check(resolved, conventions, conventions_name="conventions.md",
                                     resolved_name="conventions.resolved.md",
                                     preset_library=library)


def _uncovered_notes(result):
    return [f for f in result.findings if f.code == conventions_resolve.CODE_UNCOVERED]


# ---------------------------------------------------------------------------
# the maintainer's bundle
# ---------------------------------------------------------------------------

def test_his_ten_preset_map_lines_are_covered_by_the_library():
    result = _check((BUNDLE / "conventions.md").read_text(),
                    (BUNDLE / "conventions.resolved.md").read_text(), PresetLibrary(LIBRARY))

    assert _uncovered_notes(result) == []
    assert result.uncovered == []
    assert result.preset_lines == UNCITED_MAP_LINES
    assert "58 of 58 conventions line(s) covered" in result.summary()
    assert "10 of them preset-map line(s)" in result.summary()


def test_his_uncited_map_lines_still_reach_the_generator_verbatim():
    # Covered is not dropped: the resolver may have restated the map, but
    # nothing promises it did, so an uncited map line is still appended
    # to what the generator reads, as an uncovered line always was.
    conventions = (BUNDLE / "conventions.md").read_text()
    text = (BUNDLE / "conventions.resolved.md").read_text()
    state = conventions_resolve.Freshness(BUNDLE / "conventions.resolved.md", "fresh", "frozen",
                                          {}, text, {})
    findings: list = []
    resolved = conventions_resolve.obtain(state, conventions, "conventions.md", provider=None,
                                          findings=findings, out=io.StringIO(),
                                          preset_library=PresetLibrary(LIBRARY))

    assert resolved is not None
    assert resolved.check.verbatim == UNCITED_MAP_LINES
    tail = resolved.body.split("## Conventions lines the rules above do not cover", 1)[1]
    for line in UNCITED_MAP_LINES:
        assert f"- {line}" in tail
    assert resolved.meta()["lines_not_covered"] == 0
    assert not [f for f in findings if f.code == conventions_resolve.CODE_UNCOVERED]


def test_resolve_check_lists_no_note_for_his_map(tmp_path, monkeypatch, capsys):
    for name in ("conventions.md", "conventions.resolved.md"):
        shutil.copy(BUNDLE / name, tmp_path / name)
    monkeypatch.setattr("atoo.cli.load_default_presets", lambda: LIBRARY)

    # Fresh (0) or stale (2) as the domain knowledge and the prompt have
    # moved on since the file was made; the subject here is the note.
    assert main(["resolve", "--conventions", str(tmp_path / "conventions.md"),
                 "--check"]) in (0, 2)
    out = capsys.readouterr()
    assert "58 of 58 conventions line(s) covered" in out.out
    assert "resolve.line-not-covered" not in out.out + out.err


# ---------------------------------------------------------------------------
# what is still a note
# ---------------------------------------------------------------------------

CONVENTIONS = """\
## Processing
- Default channel presets by source, from my preset library: <!-- names saved in the preset -->
  - Kick: "Kick In"
  - Snare: "Snare Top"
  - "Lead Vox": "Vocal"
  - Playback: no preset.
  - Toms: one preset for every tom.
- Start every monitor send at -18dB.
"""

# Cites only the lead-in's neighbour, so every map item and the monitor
# line are uncited.
RESOLVED = """\
# Resolved conventions

## Processing
- The high-pass filter comes from the preset. [conventions: "Default channel presets by source, from my preset library:"]
"""


def _notes_by_line(library):
    result = _check(CONVENTIONS, RESOLVED, library)
    return result, {f.line: f for f in _uncovered_notes(result)}


def test_a_map_line_naming_a_preset_not_in_the_library_says_so():
    result, notes = _notes_by_line(PresetLibrary(LIBRARY))

    note = notes['- Snare: "Snare Top"']
    assert '"Snare Top", which is not in the preset library' in note.message
    assert str(LIBRARY) in note.message
    assert "make the line clearer" not in note.fix
    assert "`atoo presets`" in note.fix
    assert '- Snare: "Snare Top"' in result.verbatim


def test_known_presets_and_no_preset_are_covered_and_a_quoted_label_is_not_a_preset():
    result, notes = _notes_by_line(PresetLibrary(LIBRARY))

    assert '- Kick: "Kick In"' in result.preset_lines
    assert "- Playback: no preset." in result.preset_lines
    # "Lead Vox" is the label, not a preset: only "Vocal" is looked up.
    assert '- "Lead Vox": "Vocal"' in result.preset_lines
    for line in result.preset_lines:
        assert line not in notes


def test_a_line_that_is_not_a_map_entry_is_still_a_note_as_before():
    _result, notes = _notes_by_line(PresetLibrary(LIBRARY))

    # Under the lead-in but quoting no preset, and an ordinary rule line.
    for line in ("- Toms: one preset for every tom.", "- Start every monitor send at -18dB."):
        note = notes[line]
        assert "is cited by no rule" in note.message
        assert "make the line clearer" in note.fix


def test_with_no_library_nothing_can_be_called_missing():
    result, notes = _notes_by_line(None)

    assert '- Snare: "Snare Top"' in result.preset_lines
    assert set(notes) == {"- Toms: one preset for every tom.",
                          "- Start every monitor send at -18dB."}


def test_preset_map_items_reads_only_items_under_a_preset_lead_in():
    text = conventions_resolve.conventions_for_model(
        CONVENTIONS + '- Colours:\n  - Kick: "Red"\n- Generic presets:\n  - Generic sax "B Sax"\n')
    items = {text.splitlines()[i].strip(): names
             for i, names in conventions_resolve.preset_map_items(text).items()}

    assert items == {
        '- Kick: "Kick In"': ["Kick In"],
        '- Snare: "Snare Top"': ["Snare Top"],
        '- "Lead Vox": "Vocal"': ["Vocal"],
        "- Playback: no preset.": [],
        '- Generic sax "B Sax"': ["B Sax"],
    }
