"""The browser UI's words and paths.

The Python suite cannot run the page, so most of these assert on the
served assets -- crude, but it is what stands between a reworded line and
its quiet return (CLAUDE.md, "A rename that crosses into
`atoo/web/static/` is invisible to the test suite"). Where the server
shapes what the page prints (a path, a run's label), the payload itself is
asserted.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import (  # noqa: E402
    DEMO_CONVENTIONS, DEMO_SHOW_DIR, _display_path, create_app,
)

FIXTURES = Path(__file__).parent / "fixtures"
PLAN = json.loads((FIXTURES / "applied-show.plan.json").read_text())


@pytest.fixture
def assets():
    with fastapi_testclient.TestClient(create_app()) as c:
        yield c


def _static(client, name):
    r = client.get(f"/static/{name}")
    assert r.status_code == 200
    return r.text


# ---- Step 01's footer is not a claim about the file ----------


def test_step_01_footer_does_not_say_the_house_style_is_set(assets):
    assert "House style set" not in _static(assets, "shell.html")


# ---- No requirement ids in on-screen headings ----------------


def test_stage_headings_carry_no_requirement_ids(assets):
    html = _static(assets, "shell.html")
    kinds = [line for line in html.splitlines() if 'class="stage-kind"' in line]
    assert kinds
    for line in kinds:
        assert "FR-" not in line and "O2 &middot;" not in line, line
    # The four steps' headings, the same in both modes; the old
    # titles and the "1 What changed / 2 Read the desk / 3 Review the delta"
    # numbering went.
    for title in ("What will be written", "Preview", "Arm and write", "History"):
        assert f'class="apply-step-title" id="apply-step-' in html and f">{title}</h2>" in html, title
    for gone in ("Apply to console</h2>", "Patch a show that is already on the desk",
                 "What changed</h3>", "Read the desk</h3>", "Review the delta</h3>"):
        assert gone not in html, gone


# ---- A change may edit named fields of a running strip --------


def test_patch_note_says_a_change_can_edit_a_running_strip(assets):
    html = _static(assets, "shell.html")
    start = html.index('id="help-patch"')
    note = html[start:html.index("</span>", start)]
    assert "only the fields it names" in note and "already running" in note
    assert "only adds and removes" not in html


# ---- The empty screen points at the Demo show ----------------


def test_the_empty_screen_offers_the_demo_show(assets):
    html = _static(assets, "shell.html")
    assert 'id="no-show-notice"' in html and 'id="try-demo-btn"' in html
    shell = _static(assets, "shell.js")
    # Shown only with no bundle; the button is Console -> Demo.
    assert "noShowNotice.hidden = !!bundle" in shell
    start = shell.index('el("try-demo-btn")')
    wiring = shell[start:start + 400]
    assert "consoleKindDemo.checked = true" in wiring and "submitConsoleEdit()" in wiring


# ---- The demo's words, and short paths --------------


def test_demo_files_display_as_the_demo_show_not_a_package_path():
    assert _display_path(DEMO_SHOW_DIR / "input.csv", None) == "Demo show/input.csv"
    assert _display_path(DEMO_SHOW_DIR / "plan.json", None) == "Demo show/plan.json"
    assert _display_path(DEMO_CONVENTIONS, None) == "Demo show/conventions.md"


def test_step_04_says_the_demo_show_is_read_only(assets):
    setup = _static(assets, "setup.js")
    assert "Read-only: the demo show cannot be edited" in setup
    # Build output's first line: the short path, as the tiles
    # write it, with the absolute one as its title.
    assert "where.display_path || where.path" in setup
    assert "renderBuildOutput(plan, current)" in setup


def test_the_plan_payload_carries_a_short_display_path(tmp_path):
    directory = tmp_path / "touringband"
    directory.mkdir()
    (directory / "plan.json").write_text(json.dumps(PLAN))
    app = create_app(initial_bundle=str(directory), initial_plan=copy.deepcopy(PLAN),
                     initial_plan_path=str(directory / "plan.json"))
    with fastapi_testclient.TestClient(app) as c:
        body = c.get("/api/plan").json()
    assert body["path"] == str(directory / "plan.json")
    assert body["display_path"] == "touringband/plan.json"


def test_patch_rebuild_hint_names_the_bundle_not_its_folder(assets):
    amend = _static(assets, "amend.js")
    assert '"atoo build --show " + bundle.name' in amend
    assert '"atoo build --show " + bundle.directory' not in amend


# ---- A preview says so; a run stays in its mode ----


def test_run_panel_labels_a_preview_and_keeps_to_its_mode(assets):
    apply = _static(assets, "apply.js")
    assert 'apply: "Preview"' in apply
    assert "runLabelFor(run.kind, run.preview)" in apply
    # The run panel and the journal view hide when the run is the other
    # mode's: a full build's log is not drawn under Patch.
    assert "!ownMode" in apply and "renderResult(ownMode)" in apply


# ---- One line per control on Apply; the rest behind '?' ------


def test_apply_screen_explanations_sit_behind_help_buttons(assets):
    html = _static(assets, "shell.html")
    for hid in ("help-apply", "help-apply-write", "help-journal-stack", "help-patch"):
        assert f'aria-controls="{hid}"' in html and f'id="{hid}"' in html, hid
    # The paragraphs that used to stand between the switch and the buttons.
    for gone in ("This checkbox is <code>--confirm</code>", "Show already on the desk?",
                 'id="apply-preflight-note"', "A setup-window operation"):
        assert gone not in html, gone
    apply = _static(assets, "apply.js")
    assert "no separate file picker" not in apply
    assert "One console for the whole page" not in apply
    assert '"A preview: nothing was written."' in apply
    amend = _static(assets, "amend.js")
    assert "-- the console in the bundle bar." not in amend
