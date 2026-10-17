"""The Build page's blocks and sections, and what a rebuild
changed, on step 04 (the browser half).

Two halves, as in `test_webui_plan_table.py`:

* **What the server adds.** Each change a rebuild made that nobody asked
  for is one WARNING in the Findings panel (it
  counts under "to check", and never blocks Apply), and the plan payload
  says when the plan it replaced was built.
* **The served assets.** The Python suite cannot see the browser, so the ids, classes and contract names the page
  relies on are pinned here. The page itself was driven in Chromium.

The two plans are the frozen pair under `tests/fixtures/rebuild_diff/`
(the Demo built, then rebuilt after one edit with a reply that also,
unasked, raised the Bass DI's gain); nothing under `examples/` is read.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import plan_diff, webui  # noqa: E402
from atoo.webui import create_app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "rebuild_diff"


def _plan(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---- the findings: an unasked change is one WARNING to check -------------


def test_each_unasked_change_is_one_warning_about_its_strip():
    plan = _plan("current.plan.json")
    got = webui._rebuild_findings(plan)
    assert len(got) == plan["meta"][plan_diff.CHANGES_KEY]["counts"]["unasked"] == 1
    finding = got[0]
    assert finding["severity"] == "warning"
    assert finding["code"] == webui.REBUILD_UNASKED == "rebuild.unasked-change"
    assert finding["source"] == "rebuild"
    # Where it is, as verify spells it, so the dock's row jump finds it.
    assert finding["where"] == "channels[Bass DI]"
    assert finding["title"] == "Not asked for: gain 20 → 26 dB"
    assert finding["message"].startswith("CH 6 Bass DI: gain 20 -> 26 dB, against plan.previous.json.")
    assert "The plan may still be right" in finding["message"]


def test_an_asked_for_change_and_a_first_build_add_nothing_to_the_dock():
    # The asked-for changes (Guest Vox added, Playback moved) stay on step
    # 04's list; a first build has no comparison at all.
    plan = _plan("current.plan.json")
    asked = [s for s in plan["meta"][plan_diff.CHANGES_KEY]["strips"] if s["severity"] == "INFO"]
    assert asked, "the fixture carries asked-for changes"
    assert all(f["where"] != "channels[Guest Vox]" for f in webui._rebuild_findings(plan))
    assert webui._rebuild_findings(_plan("previous.plan.json")) == []
    assert webui._rebuild_findings({"meta": {plan_diff.CHANGES_KEY: "garbage"}}) == []
    assert webui._rebuild_findings(None) == []


def test_a_change_to_a_bus_names_the_bus_and_a_removed_strip_has_no_row():
    plan = _plan("current.plan.json")
    plan = copy.deepcopy(plan)
    plan["meta"][plan_diff.CHANGES_KEY]["strips"] = [
        {"collection": "busses", "kind": "changed", "label": "BUS 3 Keys Wedge",
         "severity": "WARNING", "reason": "", "moved_from": None, "slot": ["bus", 3],
         "summary": "fader -12 -> -6 dB", "values": []},
        {"collection": "channels", "kind": "removed", "label": "CH 20 Gone",
         "severity": "WARNING", "reason": "", "moved_from": None, "slot": None,
         "summary": "removed", "values": []},
    ]
    bus, gone = webui._rebuild_findings(plan)
    assert bus["where"] == "busses[Keys Wedge]"
    assert "where" not in gone


def test_the_plan_findings_carry_it_and_the_payload_says_when_the_old_plan_was_built(tmp_path):
    (tmp_path / "plan.json").write_text((FIXTURES / "current.plan.json").read_text())
    (tmp_path / "plan.previous.json").write_text((FIXTURES / "previous.plan.json").read_text())
    plan = _plan("current.plan.json")
    app = create_app(initial_plan=plan, initial_plan_path=str(tmp_path / "plan.json"))
    with fastapi_testclient.TestClient(app) as c:
        body = c.get("/api/plan").json()
    codes = [f.get("code") for f in body["findings"]]
    assert codes.count("rebuild.unasked-change") == 1
    assert body["previous_generated_at"] == _plan("previous.plan.json")["meta"]["generated_at"]


def test_no_previous_time_without_a_comparison(tmp_path):
    (tmp_path / "plan.json").write_text((FIXTURES / "previous.plan.json").read_text())
    app = create_app(initial_plan=_plan("previous.plan.json"),
                     initial_plan_path=str(tmp_path / "plan.json"))
    with fastapi_testclient.TestClient(app) as c:
        body = c.get("/api/plan").json()
    assert body["previous_generated_at"] is None


# ---- the served assets -------------------------------------------------


@pytest.fixture
def client():
    app = create_app()
    with fastapi_testclient.TestClient(app) as c:
        yield c


def _panel(html: str, panel_id: str) -> str:
    start = html.index(f'<section id="{panel_id}"')
    return html[start:html.index("</section>\n\n", start)]


def test_every_build_step_puts_its_block_headers_outside_the_box(client):
    """A block's header sits outside and above its
    box; nothing is titled inside a border. The step heads went: the
    first block's header names the step."""
    html = client.get("/static/shell.html").text
    heads = {
        "panel-conventions": ["House conventions"],
        "panel-input-list": ["Input list"],
        "panel-instructions": ["Conventions, in order", "Instructions"],
        "panel-plan": ["Plan"],
    }
    for panel_id, titles in heads.items():
        panel = _panel(html, panel_id)
        assert 'class="stage-head"' not in panel, panel_id
        assert 'class="panel-toolbar-label"' not in panel, panel_id
        found = re.findall(r'<div class="block-head">\s*<h2>([^<]+)</h2>', panel)
        assert found == titles, (panel_id, found)
        # Every header is followed, after its notation and help, by its box.
        assert panel.count('class="block-head"') == len(titles)
        assert panel.count('class="panel box') >= len(titles)
        # A section inside a box is a grey caps h3, never a white title.
        assert 'class="panel-toolbar-label"' not in panel


def test_step_04_is_one_plan_block_with_three_sections_in_the_maintainers_order(client):
    html = client.get("/static/shell.html").text
    panel = _panel(html, "panel-plan")
    block = panel[panel.index('id="build-plan-block"'):]
    order = [block.index(x) for x in ('id="sec-options"', 'id="plan-empty"',
                                       'id="sec-output"', 'id="sec-changes"')]
    assert order == sorted(order)
    # Options folds, and its summary names what is chosen.
    assert '<details class="section fold" id="sec-options" open>' in block
    assert '<summary class="section-head"><h3>Options</h3>' in block
    assert 'id="options-aside"' in block and 'id="options-building"' in block
    # A running build's progress is inside Options.
    options = block[:block.index('id="plan-empty"')]
    for element_id in ("run-console-model", "run-critic", "run-build-btn", "run-panel",
                       "run-progress", "run-stop-btn", "run-log-fold"):
        assert f'id="{element_id}"' in options, element_id
    # Build output: the file line, verify, the stale reason and Rebuild.
    output = block[block.index('id="sec-output"'):block.index('id="sec-changes"')]
    for element_id in ("plan-state-tag", "plan-source", "plan-verify-line", "plan-stale-reason",
                       "plan-rebuild-btn", "plan-output"):
        assert f'id="{element_id}"' in output, element_id
    # The changes fold is a jump target that opens step 04.
    assert '<details class="section fold chg-block" id="sec-changes" data-step="plan" hidden>' in block
    assert '<div class="section-head"><h3>Build output</h3>' in block
    # One primary button in the block: Build plan. Rebuild is secondary,
    # and a locked Build plan says why in words.
    assert block.count("btn btn-primary") == 1
    assert 'id="run-build-lock"' in block


def test_setup_js_draws_the_build_output_and_the_details_fold(client):
    js = client.get("/static/setup.js").text
    for name in ("function renderBuildOutput(", "function sourceLine(", "function verifyLine(",
                 "function factsLine(", "function detailsFold(", "function renderChanges(",
                 "function changeChip(", "function changeRowClass(", "function blockHead("):
        assert name in js, name
    # The verdict, the findings line and the counts, by the ids the
    # shell gives them.
    for element_id in ("plan-source", "plan-verify-line", "plan-output", "plan-state-tag",
                       "sec-changes", "options-aside", "options-building"):
        assert f'"{element_id}"' in js, element_id
    # Notes and build details under one folded Details line (the maintainer).
    assert '<details class="fold-details" id="plan-notes-details">' in js
    assert "<summary>Details" in js
    assert "Notes from the model" in js
    # Options folds, remembered per viewer, and opens for a build.
    assert 'const OPTIONS_OPEN_KEY = "atoo.build.optionsOpen";' in js
    assert "openOptions();" in js
    # The fields it reads from the plan and the payload.
    for field in ("changes_since_previous", "previous_generated_at", "display_path",
                  "verify_now", "verify_at_generation", "generated_at", "console_model"):
        assert field in js, field


def test_setup_js_reads_the_comparison_the_build_keeps(client):
    """`meta.changes_since_previous` is `PlanChanges.to_dict()`: every key
    the page reads must still be one it writes."""
    js = client.get("/static/setup.js").text
    keys = set(_plan("current.plan.json")["meta"][plan_diff.CHANGES_KEY])
    strip = set(_plan("current.plan.json")["meta"][plan_diff.CHANGES_KEY]["strips"][0])
    for key in ("against", "counts", "notes", "strips"):
        assert key in keys and f"changes.{key}" in js, key
    for key in ("collection", "kind", "label", "severity", "reason", "slot", "summary"):
        assert key in strip and f"strip.{key}" in js, key
    assert "counts.unasked" in js
    # Each strip links to its row through the shell's own jump.
    assert "SP_.jumpTo({ mode: \"build\", target: \"#\" + a.dataset.row })" in js
    assert "jumpTo: jumpTo," in client.get("/static/shell.js").text


def test_the_tables_mark_changed_rows_and_are_blocks(client):
    js = client.get("/static/setup.js").text
    assert "${changeRowClass(id)}" in js
    for kind in ("channel", "bus", "output"):
        assert f'changeChip(cardId("{kind}", ' in js, kind
    for title in ('blockHead("Channels"', 'blockHead("Busses"', 'blockHead("Outputs"'):
        assert title in js, title
    assert '<section class="panel box plan-table-section" id="plan-channels-block">' in js
    assert '<summary class="section-head"><h3>Changed since the last build</h3>' in js


def test_an_unasked_change_jumps_to_the_list_and_counts_in_the_verdict(client):
    js = client.get("/static/setup.js").text
    assert 'finding.code === "rebuild.unasked-change"' in js
    assert 'target: "#sec-changes"' in js
    shell = client.get("/static/shell.js").text
    assert '(counts.check ? "· " + counts.check + " to check" : "no errors")' in shell


def test_styles_carry_the_block_rule_and_the_type_floor(client):
    css = client.get("/static/styles.css").text
    # docs/developer/ui-style.md §11's target classes.
    for selector in (".block-head", ".block-head h2", ".notation", ".panel.box", ".section-head",
                     ".section-head h3", ".section", "details.fold", "details.fold-details",
                     ".state", ".state.is-ok", ".state.is-warn", ".state.is-live", ".sev",
                     ".sev.sev-error", ".lock-reason", ".empty", ".chg-list", ".ct tr.row-unasked",
                     ".btn:disabled"):
        assert re.search(re.escape(selector) + r"(?![\w-])", css), selector
    block = css[css.index("/* ---- Build: blocks and sections"):]
    # Nora's §3: five sizes, nothing under 11px, in what this change added.
    sizes = {float(s) for s in re.findall(r"font(?:-size)?:[^;]*?(\d+(?:\.\d+)?)px", block)}
    assert sizes and min(sizes) >= 11, sizes
    # ...and §2's one exception: the Watch verdict word, 22/800 caps, in its own rule and nowhere else.
    assert sizes - {22} <= {11, 12, 13, 14, 16}, sizes
    assert re.findall(r"([^{}]*)\{[^}]*font-size: 22px", block) == ["\n.verdict-word "]
    assert re.search(r"\.block-head h2 \{[^}]*font-size: 16px", block)
    assert re.search(r"\.notation \{[^}]*font-size: 11px", block)
    assert re.search(r"\.section-head h3 \{[^}]*font-size: 11px", block)
    # The locked look is no hue and a dashed edge, never opacity alone --
    # app-wide since an earlier change (tests/test_webui.py covers the rule).
    assert re.search(r"\.btn:disabled, [^{]*\{[^}]*border: 1px dashed var\(--border-strong\)", block)
    for token in ("--border-strong", "--text-off"):
        assert css.count(token + ":") == 3, token  # dark, light by preference, light by choice


def test_no_badge_class_of_its_own_and_no_retired_colours(client):
    """Nora's review: a changed row's kind is a state tag (§6), not a new
    badge class; the verify tag is the severity family, whose error is
    the one red; the blue `.sev-ok` is gone."""
    css = client.get("/static/styles.css").text
    js = client.get("/static/setup.js").text
    assert ".chg-chip" not in css and "chg-chip" not in js
    assert '`<span class="state chg-state${unasked ? " is-warn" : ""}"' in js
    assert re.search(r"\.sev\.sev-error \{[^}]*var\(--danger-bg\)[^}]*var\(--danger-fg\)", css)
    assert ".sev-ok { background: var(--info-bg)" not in css
    assert ".setup-notes-details" not in css
    assert 'cls = "sev " + (errors ? "sev-error"' in js
    assert "sev-badge" not in js[js.index("function verifyLine("):js.index("function factsLine(")]
    # Focus is the brass ring; the tiles' small buttons are 11px.
    assert "details.fold > summary:focus-visible" in css and ".chg-list a:focus-visible" in css
    assert "#build-steps .btn-sm, #build-steps .help-btn, #status-rebuild-btn" in css


def test_an_unasked_change_is_never_gathered_with_another(client):
    """Code review: three strips each "gain 20 -> 26 dB" were one dock row
    and the verdict counted 1. Each is its own row: the server gives each
    its own `where`, and the dock never gathers the code."""
    shell = client.get("/static/shell.js").text
    assert 'const NEVER_GATHERED = new Set(["rebuild.unasked-change"]);' in shell
    assert "!NEVER_GATHERED.has(f.code)" in shell[shell.index("const checkKey"):]
    plan = copy.deepcopy(_plan("current.plan.json"))
    template = plan["meta"][plan_diff.CHANGES_KEY]["strips"][0]
    strips = []
    for label, slot in (("CH 6 Bass DI", ["ch", 6]), ("CH 7 Gtr 1", ["ch", 7])):
        strips.append(dict(template, label=label, slot=slot))
    plan["meta"][plan_diff.CHANGES_KEY]["strips"] = strips
    got = webui._rebuild_findings(plan)
    assert [f["title"] for f in got] == ["Not asked for: gain 20 \u2192 26 dB"] * 2
    assert [f["where"] for f in got] == ["channels[Bass DI]", "channels[Gtr 1]"]


@pytest.mark.parametrize("changes", [
    {"strips": 5},
    {"strips": "abc"},
    {"strips": [{"severity": "WARNING", "collection": ["channels"], "label": "CH 1 Kick"}]},
    {"strips": [{"severity": "WARNING", "collection": {"x": 1}, "label": 7, "slot": "ch"}]},
    {"strips": [None, 3, "x"], "against": ["nope"]},
])
def test_a_malformed_comparison_never_breaks_the_plan_payload(tmp_path, changes):
    plan = copy.deepcopy(_plan("previous.plan.json"))
    plan["meta"][plan_diff.CHANGES_KEY] = changes
    webui._rebuild_findings(plan)  # does not raise
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    app = create_app(initial_plan=plan, initial_plan_path=str(tmp_path / "plan.json"))
    with fastapi_testclient.TestClient(app) as c:
        assert c.get("/api/plan").status_code == 200


def test_a_removed_strip_names_no_row_even_when_a_name_matches_its_tail():
    plan = copy.deepcopy(_plan("current.plan.json"))
    plan["channels"].append(dict(plan["channels"][0], name="DI", channel=30))
    plan["meta"][plan_diff.CHANGES_KEY]["strips"] = [
        {"collection": "channels", "kind": "removed", "label": "CH 6 Bass DI",
         "severity": "WARNING", "reason": "", "moved_from": None, "slot": None,
         "summary": "removed", "values": []}]
    (finding,) = webui._rebuild_findings(plan)
    assert "where" not in finding
    assert webui._diff_strip_name(plan, plan["meta"][plan_diff.CHANGES_KEY]["strips"][0]) is None


def test_the_demo_build_button_is_locked_not_only_labelled(client):
    js = client.get("/static/setup.js").text
    assert ('runBtn.disabled = run.state === "running" || !bundle || !!bundle.demo || SP.isStale();'
            in js)
    assert 'bundle.demo ? "the Demo show is read-only"' in js


def test_save_and_discard_are_hidden_until_there_is_something_to_save(client):
    """Nora's review (ui-style.md §4): a Save/Discard pair with nothing to
    save is hidden, not locked, on steps 02 and 04 as on 01 and 03 --
    except on a read-only show, where step 02's pair stays up, locked,
    with the reason beside it."""
    html = client.get("/static/shell.html").text
    for element_id in ("input-discard-btn", "input-save-btn", "plan-input-discard-btn",
                       "plan-input-save-btn"):
        tag = re.search(rf'<button [^>]*id="{element_id}"[^>]*>', html).group(0)
        assert " hidden" in tag, element_id
    shell = client.get("/static/shell.js").text
    assert "if (node) node.hidden = !inputListLoaded || (!dirty && !locked);" in shell
    assert "if (node) node.hidden = !dirty || !planEditable;" in shell
    js = client.get("/static/setup.js").text
    assert "if (node) node.hidden = !editable || !dirty;" in js


def test_the_channels_notation_counts_as_build_output_does(client):
    js = client.get("/static/setup.js").text
    assert "const chNote = [`${strips} channel${strips === 1 ? \"\" : \"s\"}`]" in js
    assert ".concat(aux ? [`${aux} aux`] : [])" in js
