"""

The maintainer, 2026-10-02: *"have all the findings go to the sidebar like they're
supposed to with no duplication, the other thing is we are going to need to
reduce or hide a lot of those info messages. They're simply too many of
them."*

The realistic load is a frozen copy of sixpiece's plan as the maintainer's
rebuild of 2026-10-01 wrote it (`tests/fixtures/sixpiece_2026-10-01.plan.json`,
see `tests/fixtures/README.md`): 36 build INFOs, 10 verify findings and 10
critic findings. Nothing here reads `examples/`.

What the browser does with these -- the INFO toggle, the per-code rows, the
one row for a finding two producers published -- is pinned on the served
assets (CLAUDE.md: the Python suite cannot see `web/static/`), and was
checked in Chromium.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import finding_groups  # noqa: E402
from atoo.webui import _plan_findings, create_app  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "sixpiece_2026-10-01.plan.json"


@pytest.fixture(scope="module")
def plan() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def client():
    with fastapi_testclient.TestClient(create_app()) as c:
        yield c


def _items(entries):
    """The findings a list of dock entries stands for (a grouped entry's
    `members`, else itself)."""
    return [m for f in entries for m in (f.get("members") or [f])]


def _recorded(plan):
    meta = plan["meta"]
    verify = meta["verify_findings"]
    return (list(verify["errors"]) + list(verify["warnings"]) + list(verify["info"])
            + list(meta["critic_findings"]) + list(meta["build_findings"]))


def test_every_finding_the_plan_recorded_reaches_the_dock_exactly_once(plan):
    recorded = _recorded(plan)
    shown = _items(_plan_findings(plan))
    assert len(shown) == len(recorded) == 56
    key = lambda f: (f.get("severity"), f.get("where"), f.get("message"))  # noqa: E731
    assert Counter(map(key, shown)) == Counter(map(key, recorded))


def test_the_dock_groups_info_by_code_with_a_count_and_words(plan):
    """What the dock's INFO rows say for sixpiece: one row per code, the
    count being the items it stands for, and the words from
    `finding_groups.CODE_SUMMARIES`."""
    infos = [f for f in _plan_findings(plan) if f["severity"] == "info"]
    by_code: Counter = Counter()
    for f in infos:
        by_code[f["code"]] += len(f.get("members") or [f])
    assert by_code["preset.overridden"] == 22
    assert by_code["reply.category-rule"] == 7
    assert by_code["reply.instructed-strip"] == 3
    assert finding_groups.code_summary("preset.overridden", 22) == (
        "22 channels: the plan's own processing replaced a value its preset sets")
    assert finding_groups.code_summary("reply.category-rule", 7).startswith("7 categories: ")
    assert finding_groups.code_summary("reply.channels-numbered", 1).startswith("1 note: ")
    # A code nobody wrote words for still gets a row.
    assert finding_groups.code_summary("some.new-code", 2) == "2 notes: some.new-code"
    # Every code sixpiece's INFOs carry has its own words.
    assert not set(by_code) - set(finding_groups.CODE_SUMMARIES)


def test_the_page_gets_the_code_words_from_python(client):
    """One table, in finding_groups.py; the page reads it from the startup
    blob rather than keeping its own copy."""
    page = client.get("/").text
    blob = page.split('id="initial-shell"', 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    codes = json.loads(blob)["finding_codes"]
    assert codes["preset.overridden"] == list(finding_groups.CODE_SUMMARIES["preset.overridden"])
    js = client.get("/static/shell.js").text
    assert "const CODE_WORDS = startup.finding_codes || {};" in js


def test_the_dock_collapses_info_under_one_remembered_fold(client):
    """Every INFO goes under a closed fold -- "Choices",
    with the build details in a second one -- its state kept
    per viewer in localStorage (wrapped in try/catch: a private window
    throws). Several INFOs with one code are one row, in the words
    `finding_groups.CODE_SUMMARIES` gives that code."""
    js = client.get("/static/shell.js").text
    html = client.get("/static/shell.html").text
    for element_id in ("dock-info", "dock-info-count", "dock-info-list",
                       "dock-details", "dock-details-count", "dock-details-list"):
        assert f'id="{element_id}"' in html
    assert '<details class="dock-fold dock-info" id="dock-info" hidden>' in html
    assert 'const INFO_OPEN_KEY = "atoo.dock.infoOpen";' in js
    assert ('try { details.open = localStorage.getItem(key) === "1"; } '
            "catch (e) { details.open = false; }") in js
    assert "try { localStorage.setItem(key, details.open" in js
    assert "const isInfo = (entry) => severityRank(entry.finding.severity) >= SEVERITY_ORDER.info;" in js
    assert "const choiceRows = gather(choices, infoKey);" in js
    assert "fill(dockInfoList, choiceRows, false);" in js
    assert 'row.where = count + " " + (words ? words[1] : "strips");' in js
    # A finding a badge points at is shown even when its fold is closed.
    assert 'for (let fold = li.parentElement.closest("details"); fold;' in js


def test_a_finding_two_passes_publish_is_one_row(client):
    """Step 04's plan carries the verify its build ran; Apply's pre-flight
    runs that verify again on the same plan.json; the build and its verify
    each announce `preset.expanded`. Same severity, code and `where` from
    a DIFFERENT origin (producer or source) is the same finding: one row,
    the newest words, every origin's jump links. One origin's repeats are
    never merged (the critic says two things about Ambient/EKIT)."""
    js = client.get("/static/shell.js").text
    assert ('const key = [finding.severity, finding.code || "", finding.where || ""]'
            '.join("\\u0000");') in js
    assert 'const origin = (finding._producer || "") + "/" + (finding.source || "");' in js
    assert "if (prior && prior.origins.indexOf(origin) === -1) {" in js
    assert "entry.twins.forEach((twin) => { twin._resolved = check.checked; });" in js
    # The row badges and step 04's count read what the dock shows.
    setup = client.get("/static/setup.js").text
    assert "(SP_.shownFindings ? SP_.shownFindings() : SP_.findings()).forEach((f) => {" in setup


def _dock_rows(found):
    """The dock's fold (shell.js `dockEntries`), restated for a test: one
    row per (severity, code, where), except that one origin's repeats each
    keep their own row."""
    rows: list = []
    by_key: dict = {}
    for f in found:
        key = (f["severity"], f["code"], f.get("where"))
        origin = (f.get("_producer"), f.get("source"))
        prior = by_key.get(key)
        if prior is not None and origin not in prior["origins"]:
            prior["origins"].append(origin)
            continue
        row = {"finding": f, "origins": [origin]}
        if prior is None:
            by_key[key] = row
        rows.append(row)
    return rows


def test_sixpiece_in_the_dock_has_no_repeats(plan):
    """On the real load: the plan's own findings plus a pre-flight that
    repeats every verify finding (as `/api/apply/preflight` does for a
    plan verified against the same files) fold to one row each. The only
    fold inside the plan itself is `preset.expanded`, said by the build
    and again by its verify; the critic's two Ambient/EKIT findings stay
    two."""
    found = [dict(f, _producer="plan") for f in _plan_findings(plan)]
    preflight = [dict(f, _producer="apply-preflight") for f in found if f["source"] == "verify"]
    rows = _dock_rows(found + preflight)
    assert len(rows) == len(found) - 1
    folded = [r for r in rows if len({o[1] for o in r["origins"]}) > 1]
    assert [r["finding"]["code"] for r in folded] == ["preset.expanded"]
    ekit = [r for r in rows if r["finding"]["code"] == "critic.intent"
            and r["finding"]["where"] == "Ambient/EKIT"]
    assert len(ekit) == 2


def test_a_refused_build_puts_its_error_in_the_dock(client):
    """The ERROR for a missing input list or house file arrives
    only when Build is pressed -- in the refusal's `findings` -- and goes
    once the file is there."""
    js = client.get("/static/setup.js").text
    assert "publishRefusal(data.findings || []);" in js
    assert 'replaceFindings("build-refusal", list.map((finding) => {' in js
    assert "dropAnsweredRefusals(sources);" in js
