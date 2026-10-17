"""The findings dock the maintainer approved on
2026-10-11 (`mockups/findings-dock/`, "approved, as shown").

The verdict first; one line per finding naming its strip the way the desk
does; one row for one finding on several strips; the critic's warnings
apart as Advice; INFO folded as Choices, with the build plumbing in a
second fold; and a badge counting only what needs a look.

The server's part is tested here directly (`finding_groups.label_strips`,
the `stale` mark that replaced a sentence on every note, the critic's
claim reaching the dock). The page's part is pinned on the served assets
-- the Python suite cannot see `web/static/` -- and was
driven in Chromium on copies of two show bundles and the frozen
`docs/user/demo` bundles. Nothing here reads `examples/`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import bus_presets, finding_groups, generate  # noqa: E402
from atoo.webui import _plan_findings, create_app  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "sixpiece_2026-10-01.plan.json"


@pytest.fixture
def client():
    with fastapi_testclient.TestClient(create_app()) as c:
        yield c


def _plan() -> dict:
    """A small plan, built here, with one of each kind of strip."""
    return {
        "channels": [
            {"channel": 23, "bank": "ch", "name": "Crowd"},
            {"channel": 2, "bank": "aux", "name": "HOST"},
            {"channel": 5, "bank": "ch", "name": "Twin"},
            {"channel": 6, "bank": "ch", "name": "Twin"},
        ],
        "busses": {"Drums": {"index": 3}},
        "outputs": {"Matrix 1": {"kind": "matrix", "index": 1},
                    "Stage feed": {"kind": "main", "index": 2}},
        "dcas": {"Vocals": {"index": 4}},
        "mute_groups": {"Band": {"index": 1}},
    }


# ---- the strip, as the desk names it -----------------------------------

@pytest.mark.parametrize("finding, label", [
    ({"where": "channels[Crowd]", "message": "ch 23 'Crowd' reaches no Main: x"}, "CH 23 Crowd"),
    ({"where": "channels[HOST]", "message": "1 of the preset values will not be written"},
     "AUX 2 HOST"),
    ({"where": "channels[2]", "message": "aux 2 ('HOST'): 31 values are not carried"}, "AUX 2 HOST"),
    ({"where": "busses[Drums]", "message": "m"}, "BUS 3 Drums"),
    ({"where": "outputs[Matrix 1]", "message": "Matrix index set to 1"}, "MTX 1"),
    ({"where": "outputs[Stage feed].patch", "message": "m"}, "MAIN 2 Stage feed"),
    ({"where": "plan.dcas[Vocals]", "message": "m"}, "DCA 4 Vocals"),
    ({"where": "mute_groups[Band]", "message": "m"}, "MGRP 1 Band"),
    # The critic's free text, when it names a strip the plan has.
    ({"where": "HOST (aux 2)", "message": "m", "source": "critic"}, "AUX 2 HOST"),
    ({"where": "Crowd", "message": "m", "source": "critic"}, "CH 23 Crowd"),
    ({"where": "Drums", "message": "m", "source": "critic"}, "BUS 3 Drums"),
    # A strip the plan does not have still reads as the desk would.
    ({"where": "", "message": "ch 40 ('Spare'): left alone"}, "CH 40 Spare"),
])
def test_a_finding_names_its_strip_the_way_the_desk_does(finding, label):
    assert finding_groups.strip_label(finding, finding_groups.desk_names(_plan())) == label


@pytest.mark.parametrize("finding", [
    {"where": "conventions", "message": "built from a file that is no longer there"},
    {"where": "sixpiece/plan.json", "message": "older than its inputs"},
    # "ch 24-40, aux 3-7" is a range, not channel 24.
    {"where": "Apply", "message": "ch 24-40, aux 3-7: not in this plan"},
    # Two strips called Twin: which one would be a guess.
    {"where": "channels[Twin]", "message": "m"},
    # A critic's text that names no one strip.
    {"where": "Sample Pad / patching", "message": "m", "source": "critic"},
])
def test_a_finding_about_no_one_strip_gets_no_label(finding):
    assert finding_groups.strip_label(finding, finding_groups.desk_names(_plan())) is None


def test_the_plans_findings_carry_their_strip_and_keep_every_other_key():
    plan = json.loads(FIXTURE.read_text())
    shown = _plan_findings(plan)
    names = {c["name"]: c for c in plan["channels"]}
    labelled = 0
    for f in shown:
        for item in f.get("members") or [f]:
            where = item.get("where") or ""
            if where.startswith("channels[") and where[9:-1] in names:
                c = names[where[9:-1]]
                assert item["strip"] == f"{'AUX' if c.get('bank') == 'aux' else 'CH'} " \
                                       f"{c['channel']} {c['name']}"
                labelled += 1
            assert item["message"] and item["code"]
    assert labelled >= 5
    # A grouped entry's own line stays its group's; its members are named.
    grouped = [f for f in shown if f.get("members")]
    assert grouped and all("strip" not in f for f in grouped)


# ---- the critic's claim reaches the dock -------------------------

def test_a_critics_claim_reaches_the_dock_as_its_title():
    """A frozen critic reply, as a build would store it in
    `meta.critic_findings` and the dock would read it. A real model's
    claims are unverified until the next real build."""
    reply = json.dumps({"findings": [
        {"severity": "warning", "kind": "intent", "where": "Crowd",
         "claim": "Every monitor send is down",
         "message": "Crowd sends to MON1-6 at -144 dB, so it is silent in every monitor."},
        {"severity": "warning", "kind": "intent", "where": "HOST (aux 2)",
         "message": "No claim in this one; the page cuts the message to make the line."},
    ]})
    plan = _plan()
    plan["meta"] = {"critic_findings": [f.to_dict() for f in generate.parse_critic_findings(reply)]}
    first, second = _plan_findings(plan)
    assert (first["title"], first["strip"], first["source"]) == (
        "Every monitor send is down", "CH 23 Crowd", "critic")
    assert first["message"].startswith("Crowd sends to MON1-6")
    assert "title" not in second and second["strip"] == "AUX 2 HOST"


# ---- the page ------------------------------------------------------------

def test_the_dock_has_a_verdict_and_its_sections(client):
    html = client.get("/static/shell.html").text
    for element_id in ("dock-verdict", "dock-check", "dock-check-count", "dock-active-list",
                       "dock-advice", "dock-advice-count", "dock-advice-list",
                       "dock-info", "dock-details", "dock-active-empty", "dock-resolved"):
        assert f'id="{element_id}"' in html, element_id
    assert "a second model's opinion; never blocks Apply" in html
    assert "What needs a look, first" in html
    # The verdict comes before the lists, To check before Advice, Advice
    # before the folds.
    order = [html.index(f'id="{i}"') for i in
             ("dock-verdict", "dock-check", "dock-advice", "dock-info", "dock-details")]
    assert order == sorted(order)


def test_the_page_draws_one_line_per_finding(client):
    js = client.get("/static/shell.js").text
    # Where: the server's strip first; the message's own prefix after.
    assert "if (finding.strip) return finding.strip;" in js
    # Claim: a producer's title (the critic's claim), else the message up
    # to its first colon, semicolon or " -- ".
    assert "if (finding.title) return [finding.title, String(finding.message || \"\")];" in js
    assert "const CLAIM_CUT = /:\\s|;\\s?|\\s--\\s/g;" in js
    assert 'details.className = "dock-row";' in js
    assert 'line.className = "dock-line";' in js
    css = client.get("/static/styles.css").text
    assert "-webkit-line-clamp: 2;" in css
    assert ".dock-item.is-advice { border-left-style: dashed; }" in css


def _dock_lines(js: str, findings: list[dict]) -> list[list[str]]:
    """[where, claim] for each finding, as the served `shell.js` draws its
    line: its own `whereOf`/`splitClaim`, run in Node. The Python suite
    cannot otherwise see what the page makes of a message."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    start = js.index("  const BANK_WORDS")
    end = js.index("  // Rows whose details are open")
    script = ("const startup = {};\n" + js[start:end]
              + "\nconst found = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "\nconsole.log(JSON.stringify(found.map((f) => [whereOf(f), splitClaim(f)[0]])));")
    out = subprocess.run([node, "-e", script], input=json.dumps(findings),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_a_possessive_on_the_strip_is_not_cut_off_as_the_claim(client):
    """An FX note reads "bus 7 ('Vox Verb')'s pre-insert:
    V-REV goes into FX5 -- ...". The line was cut at that first colon and
    read "BUS 7 Vox Verb 's pre-insert"; the "'s" belongs to the strip the
    line names, and "pre-insert" is no claim on its own."""
    entry = {"index": 7}
    owner = bus_presets.insert_owner("Vox Verb", entry, "preins")
    findings = [
        {"severity": "info", "code": "fx.engine-allocated", "where": "busses[Vox Verb]",
         "message": f"{owner}: V-REV goes into FX5 -- the engine the preset was saved from"},
        {"severity": "info", "code": "fx.insert-switched-on", "where": "busses[Vox Verb]",
         "message": f"{owner}: the preset 'Vox Verb' was saved with its insert bypassed; "
                    "it is switched on"},
        # A possessive further in is the claim's own.
        {"severity": "info", "code": "fx.parameter-typed-from-value", "where": "busses[Vox Verb]",
         "message": f"{owner}: 3 of V-REV's parameters (mod, out, trans) are written with the "
                    "type their saved value has -- each is read back"},
        # Owned by the strip, but no colon after: the "'s" alone goes.
        {"severity": "warning", "code": "x", "where": "",
         "message": "bus 7 ('Vox Verb')'s insert names FX5, but the insert is off"},
        # Unchanged: a strip prefix with no possessive, and a short claim.
        {"severity": "warning", "code": "x", "where": "channels[Crowd]",
         "message": "ch 23 'Crowd' reaches no Main: it is heard nowhere"},
        {"severity": "info", "code": "x", "where": "",
         "message": "A: the reply chose the group, code the next free socket"},
        {"severity": "info", "code": "x", "where": "",
         "message": "12 channel(s) carry a preset's values: ch 1 Kick In (83)"},
    ]
    js = client.get("/static/shell.js").text
    assert "const POSSESSIVE = /^'s\\s+/;" in js
    assert 'text = text.replace(POSSESSIVE, "");' in js
    assert _dock_lines(js, findings) == [
        ["BUS 7 Vox Verb", "pre-insert: V-REV goes into FX5"],
        ["BUS 7 Vox Verb", "pre-insert: the preset 'Vox Verb' was saved with its insert bypassed"],
        ["BUS 7 Vox Verb", "pre-insert: 3 of V-REV's parameters (mod, out, trans) are written "
                           "with the type their saved value has"],
        ["BUS 7 Vox Verb", "insert names FX5, but the insert is off"],
        ["CH 23 Crowd", "reaches no Main"],
        ["Plan", "A: the reply chose the group, code the next free socket"],
        ["Plan", "12 channel(s) carry a preset's values"],
    ]


def test_the_badge_counts_what_needs_a_look_and_the_critic_never_blocks(client):
    js = client.get("/static/shell.js").text
    assert "const needsLook = checkRows.length + adviceRows.length;" in js
    assert 'badge.textContent = String(needsLook);' in js
    assert 'const isAdvice = (entry) => !isInfo(entry) && entry.finding.source === "critic";' in js
    # Blocked counts errors, never the critic's.
    assert ('errors: entries.filter((entry) => entry.finding.severity === "error"\n'
            '        && entry.finding.source !== "critic").length,') in js
    # Errors first, then a stale plan, then ready.
    assert 'const verdict = blocked ? "blocked" : (stale ? "stale" : (hasPlan ? "ok" : "none"));' in js


def test_a_stale_plan_says_so_once_in_the_verdict(client):
    js = client.get("/static/shell.js").text
    assert "stale: active.some((entry) => !!entry.finding.stale)," in js
    assert 'const stale = hasPlan && (state === "stale" || !!counts.stale);' in js
    assert "if (stale) {" in js
    assert "The build's and the critic's notes are as built." in js


def test_build_details_are_their_own_fold(client):
    js = client.get("/static/shell.js").text
    assert "const BUILD_DETAILS = new Set(startup.build_detail_codes || []);" in js
    assert "const details = infos.filter((entry) => BUILD_DETAILS.has(entry.finding.code));" in js
    # Only INFOs are ever sorted into it.
    assert "const infos = active.filter(isInfo).sort(bySeverity);" in js


def test_reconcile_from_instructions_has_words_for_its_one_row():
    one, many, words = finding_groups.CODE_SUMMARIES["reconcile.from-instructions"]
    assert (one, many) == ("strip", "strips")
    assert words == "built from instructions.md, not on the input list"


def test_step_04_folds_its_repair_notes(client):
    js = client.get("/static/setup.js").text
    assert "const DETAIL_NOTE_SOURCES = new Set(startup.detail_note_sources || []);" in js
    assert "const detailNotes = allNotes.filter(isDetailNote);" in js
    assert 'id="plan-notes-details"' in js


def test_the_page_starts_dark_unless_this_browser_chose_otherwise(client):
    """"Dark look is almost always going to be
    preferred by users." With nothing saved the page is Dark; a saved
    light, dark or auto still wins."""
    html = client.get("/static/shell.html").text
    js = client.get("/static/shell.js").text
    assert 'var theme = "dark";' in html
    assert 'if (t === "light" || t === "dark" || t === "auto") theme = t;' in html
    assert 'if (theme !== "auto") document.documentElement.dataset.theme = theme;' in html
    assert 'id="theme-seg" role="radiogroup" aria-label="Theme"' in html
    assert 'aria-checked="true" tabindex="0" data-value="dark">Dark</button>' in html
    assert "localStorage.setItem(THEME_KEY, choice);" in js


def test_each_section_counts_the_rows_it_draws(client):
    """After a Demo preview the Choices head read 12 beside
    seven rows -- the run's six journal notes are drawn as one "6 notes"
    row, but the head counted findings. Every section's count, the
    verdict's lines and the badge now count the rows `gather` makes, the
    same lists `fill` draws."""
    js = client.get("/static/shell.js").text
    assert "const checkRows = gather(check, checkKey);" in js
    assert "const choiceRows = gather(choices, infoKey);" in js
    assert "const detailRows = gather(details, infoKey);" in js
    for list_id, rows in (("dockActiveList", "checkRows"), ("dockAdviceList", "adviceRows"),
                          ("dockInfoList", "choiceRows"), ("dockDetailsList", "detailRows")):
        assert f"fill({list_id}, {rows}, " in js
    for count_id, rows in (("dock-check-count", "checkRows"), ("dock-advice-count", "adviceRows"),
                           ("dock-info-count", "choiceRows"), ("dock-details-count", "detailRows")):
        assert f'setText("{count_id}", String({rows}.length));' in js
    assert "check: checkRows.length, advice: adviceRows.length, choices: choiceRows.length," in js
    # The old counts, one per finding, are gone.
    for stale in ('String(check.length)', 'String(choices.length)', 'String(details.length)',
                  'String(advice.length)', 'choices: choices.length'):
        assert stale not in js


# ---- The panel to the UI style guide ---------------------------
# docs/developer/ui-style.md §9. Checked in Chromium, dark then light, at
# 1440 and 390, on the Demo, a show with errors, a stale plan, a rebuild
# with a change nobody asked for, and a show with no plan yet.

def _tone(js: str, errors: int, needs_look: int) -> str:
    """The count badge's state class, as the served `shell.js` picks it,
    run in Node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    line = next(l.strip() for l in js.splitlines() if l.strip().startswith("const tone = "))
    script = (f"const counts = {{ errors: {errors} }}; const needsLook = {needs_look};\n"
              + line + "\nconsole.log(tone);")
    return subprocess.run([node, "-e", script], capture_output=True, text=True,
                          check=True).stdout.strip()


def test_the_count_badge_is_neutral_at_zero_red_with_an_error_yellow_with_warnings(client):
    js = client.get("/static/shell.js").text
    assert _tone(js, 0, 0) == "is-zero"
    assert _tone(js, 0, 3) == "is-warn"
    assert _tone(js, 2, 5) == "is-err"
    # Set on both badges, the title's and the collapsed tab's, every redraw.
    assert '["dock-title-count", "dock-tab-count"].forEach((id) => {' in js
    assert 'badge.classList.remove("is-zero", "is-warn", "is-err");' in js
    html = client.get("/static/shell.html").text
    assert '<span class="dock-tab-count is-zero" id="dock-tab-count">0</span>' in html
    assert '<span class="dock-title-count is-zero" id="dock-title-count"' in html
    css = client.get("/static/styles.css").text
    badge = css[css.index(".dock-tab-count, .dock-title-count {"):]
    badge = badge[:badge.index(".findings-dock {")]
    # Never brass, and a 3px tag rather than a 9px pill.
    assert "--accent" not in badge and "border-radius: 9px" not in badge
    assert "border-radius: 3px;" in badge
    assert ".dock-title-count.is-warn { background: var(--caution-solid); color: var(--caution-ink); }" in badge
    assert ".dock-title-count.is-err { background: var(--alarm-solid); color: var(--alarm-ink); }" in badge


def test_the_verdict_leads_with_a_large_severity_tag(client):
    js = client.get("/static/shell.js").text
    assert ('badge.className = "sev big " + { blocked: "sev-error", stale: "sev-warning", '
            'ok: "sev-ok", none: "sev-none" }[verdict];') in js
    assert ('badge.textContent = { blocked: "Blocked", stale: "Stale", ok: "Ready to apply", '
            'none: "No plan yet" }[verdict];') in js
    # No plan yet is neutral grey, never blue (blue is information only).
    assert '"sev-info"' not in js[js.index("function renderVerdict"):js.index("function fill(")]
    assert "No errors" not in js
    css = client.get("/static/styles.css").text
    assert ".sev.sev-none {" in css
    assert '.dock-verdict[data-state="none"] { border-left-color: var(--border-strong); }' in css
    # A count is bold white when not zero, dim when it is.
    assert 'if (!n) li.className = "is-zero";' in js
    assert ".dock-verdict-lines li.is-zero, .dock-verdict-lines li.is-zero b" in css
    # The stale line: a Stale state tag, the sentence in meta type, and
    # Rebuild as a quiet button.
    assert 'tag.className = "state is-warn";' in js and 'tag.textContent = "Stale";' in js
    assert 'btn.className = "btn btn-quiet dock-jump";' in js


def test_the_panel_uses_the_shared_tags_buttons_and_folds(client):
    js = client.get("/static/shell.js").text
    html = client.get("/static/shell.html").text
    css = client.get("/static/styles.css").text
    # Each row leads with the severity, as a word, in the shared tint tag.
    assert 'sev.className = "sev sev-" + severity;' in js
    # Jump links are quiet buttons; the source is a property tag.
    assert 'a.className = "btn btn-quiet dock-jump";' in js
    assert 'src.className = "prop";' in js
    for gone in ("dock-src", "source-tag", "dock-count-info", "dock-count-dim",
                 "dock-empty-note", "sev-ready"):
        assert gone not in js + html + css, gone
    # Folds: Choices and Addressed are section folds, Build details the
    # quiet Details fold; one chevron each, drawn by the shared rule.
    assert '<details class="dock-fold fold dock-info" id="dock-info" hidden>' in html
    assert '<details class="dock-fold fold-details dock-details" id="dock-details" hidden>' in html
    assert '<details class="dock-fold fold dock-resolved" id="dock-resolved" hidden>' in html
    dock_html = html[html.index('id="dock-col"'):html.index("</aside>")]
    assert 'class="chevron"' not in dock_html
    # The shared empty state, and a count with no brackets.
    assert '<p class="empty dock-empty" id="dock-active-empty">' in html
    assert 'el("dock-resolved-count").textContent = String(resolved);' in js


def test_the_panel_has_no_type_under_11px_no_orange_and_no_opacity(client):
    import re

    css = client.get("/static/styles.css").text
    assert ".dock-title { font-size: 16px;" in css
    for m in re.finditer(r"([^{}]*\b(?:dock|findings-dock)[^{}]*)\{([^}]*)\}", css):
        selector, body = m.group(1).strip(), m.group(2)
        for size in re.findall(r"font(?:-size)?:\s*(?:\d+\s+)?([\d.]+)px", body):
            assert float(size) >= 11, (selector, size)
        assert "--error-fg" not in body, selector
        assert "opacity" not in body, selector
        assert "outline: none" not in body, selector
    # Every control in the panel shows the brass ring.
    assert ".dock-tab:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }" in css
    assert (".dock-item-check:focus-visible, .dock-row > summary:focus-visible,\n"
            ".dock-details > summary:focus-visible { outline: 2px solid var(--accent); "
            "outline-offset: 2px; }") in css


def test_addressed_rows_go_neutral_and_focus_follows_the_fold(client):
    """Nora's review: a ticked row must not read as a live
    error, and collapsing or opening the panel keeps keyboard focus."""
    css = client.get("/static/styles.css").text
    assert ".dock-item.is-resolved { border-left-color: var(--border-strong); }" in css
    assert ".dock-item.is-resolved .sev { background: var(--bg-row-alt); color: var(--text-dim); }" in css
    js = client.get("/static/shell.js").text
    assert ('dockTab.addEventListener("click", () => { toggleDock(); '
            'el("dock-collapse-btn").focus(); });') in js
    assert ('el("dock-collapse-btn").addEventListener("click", () => { toggleDock(); '
            'dockTab.focus(); });') in js
    html = client.get("/static/shell.html").text
    assert "dock-head-advice" not in html + css


def test_apply_progress_line_is_a_sentence_not_a_readout(client):
    """A nowrap readout holding a sentence pushed Apply sideways at 390px;
    a readout holds sockets and ids (ui-style.md §6)."""
    html = client.get("/static/shell.html").text
    assert '<p class="apply-progress-line meta" id="apply-progress-line" hidden></p>' in html
