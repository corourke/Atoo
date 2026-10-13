"""`<!-- ... -->` in a conventions file or instructions.md: notes the build
ignores (the maintainer, 2026-09-25).

The file holds rules AND the engineer's notes to himself -- "(We will EQ
this so it sounds good for a recording.)" is a reminder, not a rule.
Parentheses could not be the marker (the same file puts real rules in
them), so a note goes in an HTML comment, and `conventions_text` strips
every one before any model sees the text or any quote is checked
against it. The bytes RECORDED about the file stay whole.

Every text here is built in the test: nothing reads a bundle under
examples/ (CLAUDE.md; tests/conftest.py enforces it).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from conftest import REAL_PLANS, require_fastapi_testclient
from atoo import conventions_audit as ca
from atoo import conventions_text as ct
from atoo.cli import main
from atoo.diagnostics import Severity
from atoo.webui import create_app

fastapi_testclient = require_fastapi_testclient()


# ---------------------------------------------------------------------------
# strip_comments: what a model is shown
# ---------------------------------------------------------------------------

def test_text_without_comments_is_returned_unchanged():
    text = "## Busses\n- Four wedges, MON1-4.\n\n## DCAs\n- Drums: all drums\n"
    assert ct.strip_comments(text) == text


def test_an_inline_comment_goes_and_the_rule_around_it_stays():
    text = "- Main feeds Matrix 1. <!-- We will EQ this for a recording. -->\n- Next rule\n"
    assert ct.strip_comments(text) == "- Main feeds Matrix 1.\n- Next rule\n"
    # mid-line: the spaces either side collapse to one
    assert ct.strip_comments("HPF <!-- was 100 --> 80 Hz on guitars") == "HPF 80 Hz on guitars"


def test_a_line_holding_only_a_comment_leaves_no_blank_line_and_no_empty_bullet():
    text = ("## DCAs\n"
            "- Drums: all drums\n"
            "<!-- ask about keys -->\n"
            "- <!-- Keys: all keys channels -->\n"
            "- Vocals: all vocals\n")
    assert ct.strip_comments(text) == "## DCAs\n- Drums: all drums\n- Vocals: all vocals\n"


def test_a_comment_between_two_blank_lines_leaves_one_blank_line():
    assert ct.strip_comments("rule one\n\n<!-- note -->\n\nrule two\n") == \
        "rule one\n\nrule two\n"


def test_a_multi_line_comment_goes_whole_including_a_heading_inside_it():
    text = "keep\n<!--\n## DCAs\n- Drums: all drums\n-->\nalso keep\n"
    assert ct.strip_comments(text) == "keep\nalso keep\n"


def test_a_comment_spanning_lines_never_joins_the_lines_either_side_of_it():
    text = "rule A <!-- starts here\nand ends --> rule B\n"
    assert ct.strip_comments(text) == "rule A\nrule B\n"


def test_empty_comment_forms_are_comments():
    """CommonMark: `<!-->` and `<!--->` are complete (empty) comments."""
    assert ct.strip_comments("a <!--> b <!---> c") == "a b c"


def test_a_comment_opener_inside_code_is_literal_text():
    fenced = "```\n<!-- literal -->\n```\n"
    assert ct.strip_comments(fenced) == fenced
    tilde = "~~~~\n<!-- literal -->\n~~~~\nafter <!-- gone -->\n"
    assert ct.strip_comments(tilde) == "~~~~\n<!-- literal -->\n~~~~\nafter\n"
    inline = "Write `<!--` to start a note. <!-- gone -->"
    assert ct.strip_comments(inline) == "Write `<!--` to start a note."
    # an unmatched backtick is literal, and does not hide what follows
    assert ct.strip_comments("a ` b <!-- gone --> c") == "a ` b c"


# ---------------------------------------------------------------------------
# what does NOT strip, and what it says
# ---------------------------------------------------------------------------

def test_an_unclosed_comment_swallows_nothing_and_warns_with_the_file_and_line():
    text = "## Busses\n- Four wedges.\n<!-- a note I never closed\n- Drums bus: all drums\n"
    assert ct.strip_comments(text) == text
    [finding] = ct.comment_findings(text, "house.md")
    assert finding.severity is Severity.WARNING
    assert finding.code == ct.CODE_UNCLOSED
    assert finding.where == "house.md line 3"
    assert "never closes" in finding.message
    assert finding.line == "<!-- a note I never closed"
    assert finding.source == "build"


def test_comments_before_an_unclosed_opener_still_strip():
    text = "a <!-- fine --> b\n<!-- never closed\nc\n"
    assert ct.strip_comments(text) == "a b\n<!-- never closed\nc\n"
    assert [f.code for f in ct.comment_findings(text, "x.md")] == [ct.CODE_UNCLOSED]


def test_a_stray_close_is_kept_and_noted_at_info():
    text = "Kick --> Drums bus\n"
    assert ct.strip_comments(text) == text
    [finding] = ct.comment_findings(text, "instructions.md")
    assert finding.severity is Severity.INFO
    assert finding.code == ct.CODE_STRAY_CLOSE
    assert finding.where == "instructions.md line 1"


def test_well_formed_comments_say_nothing():
    assert ct.comment_findings("a <!-- b --> c\n<!--\nd\n-->\n", "x.md") == []


# ---------------------------------------------------------------------------
# segments and sections: what the Setup page marks and the audit labels
# ---------------------------------------------------------------------------

def test_segments_concatenate_back_to_the_text_exactly():
    text = "a <!-- b --> c\n```\n<!-- d -->\n```\n<!-- e\nf -->\n<!-- open"
    parts = ct.segments(text)
    assert "".join(p.text for p in parts) == text
    assert [p.text for p in parts if p.comment] == ["<!-- b -->", "<!-- e\nf -->"]


def test_a_commented_out_heading_is_not_a_section():
    text = ("# House\n## Busses\n- Four wedges.\n"
            "<!--\n## DCAs\n- Drums: all drums\n-->\n"
            "## Outputs <!-- check with FOH -->\n- Main is the full mix.\n")
    names = [name for name, _heading, _body in ct.split_sections(text)]
    assert names == ["", "Busses", "Outputs"]


# ---------------------------------------------------------------------------
# the conventions audit: a quote found only inside a comment is not a rule
# ---------------------------------------------------------------------------

HOUSE = """# House
## Busses
- Monitor sends are pre-fader.
<!-- Monitor sends are post-fader on the jazz gigs. -->
<!--
## DCAs
- FX: all FX returns
-->
"""


def test_a_quote_that_exists_only_inside_a_comment_does_not_verify():
    layers = ca.layers_for(HOUSE, "house.md", None, None)
    assert ca.locate("Monitor sends are pre-fader.", layers) == ca.Located("conventions", "Busses")
    assert ca.locate("Monitor sends are post-fader on the jazz gigs.", layers) is None
    assert ca.locate("FX: all FX returns", layers) is None

    plan = {"conventions_audit": [{"kind": "conflict", "message": "m",
                                   "quotes": ["Monitor sends are pre-fader.",
                                              "Monitor sends are post-fader on the jazz gigs."]}]}
    [finding] = ca.findings_from_plan(plan, layers)
    assert finding.code == ca.CODE_UNVERIFIED


# ---------------------------------------------------------------------------
# atoo build: every model call, the findings, and the recorded bytes
# ---------------------------------------------------------------------------

BUILD_HOUSE = """# House
## Busses
- Four monitor busses, MON1-4. <!-- NOTE-HOUSE: we will EQ these at soundcheck -->
<!--
NOTE-HOUSE-BLOCK: a rule I have switched off
-->
"""
BUILD_INSTRUCTIONS = """# This show
## Busses
- Two wedges only.
<!-- NOTE-SHOW-UNCLOSED: never closed
- KEPT-AFTER-UNCLOSED
"""


class _Recorder:
    """Every model call's user prompt, answered with a valid plan (the
    critic and the watchlist draft read it as "no findings" and "not a
    watchlist", both of which a build survives)."""

    def __init__(self):
        plan = copy.deepcopy(REAL_PLANS["smallband"])
        plan.pop("meta", None)
        plan.setdefault("unassigned_inputs", [])
        self.reply = json.dumps(plan)
        self.users: list[tuple[str, str]] = []

    def complete(self, *, system, user, label="", **kwargs):
        self.users.append((label, user))
        return self.reply


def test_build_strips_comments_from_every_model_call_and_warns_on_an_unclosed_one(
        tmp_path, monkeypatch, capsys):
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures"
    show = tmp_path / "show"
    show.mkdir()
    (show / "input.csv").write_text((fixtures / "smallband.csv").read_text())
    (show / "instructions.md").write_text(BUILD_INSTRUCTIONS)
    house = tmp_path / "house.md"
    house.write_text(BUILD_HOUSE)

    recorder = _Recorder()
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: recorder)
    assert main(["build", "--console-model", "wing-compact", "--skip-verify", "--critic",
                 "--show", str(show), "--conventions", str(house)]) == 0

    assert [label for label, _ in recorder.users] == ["generator", "critic", "watchlist"]
    for label, user in recorder.users:
        assert "NOTE-HOUSE" not in user, label
        assert "- Four monitor busses, MON1-4.\n" in user, label
        assert "- Two wedges only." in user, label
        # the unclosed opener is read as written, not dropped with what follows
        assert "NOTE-SHOW-UNCLOSED" in user and "KEPT-AFTER-UNCLOSED" in user, label

    plan = json.loads((show / "plan.json").read_text())
    [unclosed] = [f for f in plan["meta"]["build_findings"] if f["code"] == ct.CODE_UNCLOSED]
    assert unclosed["severity"] == "warning"
    assert unclosed["where"] == "instructions.md line 4"

    # What is recorded is the file as it is, comments and all.
    house_layer = plan["meta"]["conventions_stack"][0]
    assert house_layer["sha256"] == hashlib.sha256(house.read_bytes()).hexdigest()

    err = capsys.readouterr().err
    assert "Comments in the conventions" in err
    assert ct.CODE_UNCLOSED in err and "instructions.md line 4" in err


# ---------------------------------------------------------------------------
# the Setup page: the file as written, and the house view's comments marked
# ---------------------------------------------------------------------------

UI_HOUSE = """# house-rules.md

## Channels
Patch drums first. <!-- then bass, when there is one -->

## Output
<!-- Main feeds the recorder; nothing to say yet -->

<!--
## DCAs
- Drums: all drums
-->
"""
UI_INSTRUCTIONS = """## Channels
<!-- nothing different tonight -->

## Outputs
Main is the full mix.

## Busses
<!-- never closed
"""


@pytest.fixture
def ui_sources(tmp_path):
    show = tmp_path / "show"
    show.mkdir()
    (show / "input.csv").write_text(
        "socket,name,category,type,model,phantom,notes\nAES50-A 1,Kick,drums,Mic,,FALSE,\n")
    (show / "instructions.md").write_text(UI_INSTRUCTIONS)
    house = tmp_path / "house-rules.md"
    house.write_text(UI_HOUSE)
    app = create_app(initial_bundle=str(show), initial_conventions=str(house))
    with fastapi_testclient.TestClient(app) as c:
        yield c.get("/api/build/sources").json()


def test_each_editor_gets_the_file_whole_and_the_house_view_its_comments(ui_sources):
    # Steps 01 and 03 are one editor each (2026-09-28): the text exactly
    # as written, commented-out heading and all.
    assert ui_sources["conventions"]["text"] == UI_HOUSE
    assert ui_sources["instructions"]["text"] == UI_INSTRUCTIONS
    # Step 03's "View house file" gets the whole file cut into read and
    # comment runs.
    whole = ui_sources["conventions"]["text_segments"]
    assert "".join(seg["text"] for seg in whole) == UI_HOUSE
    assert [seg["text"] for seg in whole if seg["comment"]][0] == (
        "<!-- then bass, when there is one -->")


def test_an_unclosed_comment_reaches_the_step_findings(ui_sources):
    codes = [(f["code"], f["where"]) for f in ui_sources["instructions"]["findings"]]
    assert (ct.CODE_UNCLOSED, "instructions.md line 8") in codes
    assert not any(f["code"] == ct.CODE_UNCLOSED for f in ui_sources["conventions"]["findings"])


# -- headings of any level, and the description comment (2026-09-25) ---------


@pytest.mark.parametrize("line,expected", [
    ("# Busses", (1, "Busses")), ("## Busses", (2, "Busses")),
    ("### Busses ###", (3, "Busses")), ("   ## Busses", (2, "Busses")),
    ("## Busses <!-- note -->", (2, "Busses")),
    ("####### seven", None), ("##Busses", None), ("## ", None), ("text # not", None),
])
def test_heading_name_ignores_the_level(line, expected):
    assert ct.heading_name(line) == expected


def test_every_level_starts_a_section_and_the_title_does_not():
    text = "# my-rules.md\n\n<!-- preamble -->\n\n## Inputs\na\n### Busses\nb\n#### DCAs\nc\n"
    assert [name for name, _, _ in ct.split_sections(text)] == ["", "Inputs", "Busses", "DCAs"]


def test_two_level_one_headings_are_both_sections_not_a_title():
    text = "# Inputs\na\n# Busses\nb\n"
    assert [name for name, _, _ in ct.split_sections(text)] == ["", "Inputs", "Busses"]


def test_a_heading_inside_a_comment_is_still_not_a_section_at_any_level():
    text = "## Inputs\na\n<!--\n### Busses\n-->\n"
    assert [name for name, _, _ in ct.split_sections(text)] == ["", "Inputs"]


# -- no headings needed anywhere (the maintainer, 2026-09-28) ------------------------


def test_files_with_no_headings_build_and_reach_the_model_whole(stub_build, tmp_path):
    """The Setup page no longer keys on headings, and neither may the
    build: a house file and an instructions.md with none build a plan, are
    recorded as the two layers, and reach the prompt as written."""
    from atoo.generate import _conventions_section

    stub_build("touringband")
    show = tmp_path / "show"
    show.mkdir()
    fixtures = Path(__file__).parent / "fixtures"
    (show / "input.csv").write_text((fixtures / "touringband.csv").read_text())
    (show / "instructions.md").write_text("No talkback tonight. <!-- ask FOH -->\n")
    house = tmp_path / "house.md"
    house.write_text("Drums first, then bass. Monitors are mono.\n")
    main(["build", "--show", str(show), "--conventions", str(house),
          "--console-model", "wing-compact", "--skip-verify"])
    meta = json.loads((show / "plan.json").read_text())["meta"]
    assert [layer["role"] for layer in meta["conventions_stack"]] == ["conventions", "instructions"]
    prompt = _conventions_section(house.read_text(), "house.md",
                                  (show / "instructions.md").read_text(), "instructions.md")
    assert "Drums first, then bass. Monitors are mono." in prompt
    assert "No talkback tonight." in prompt and "ask FOH" not in prompt
    # And the audit finds a quote in a file with no headings, labelled by
    # the file alone.
    layers = ca.layers_for(house.read_text(), "house.md", None, None)
    assert ca.locate("Monitors are mono", layers) == ca.Located("conventions", "")
