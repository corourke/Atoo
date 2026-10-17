"""A rebuild replaces the findings dock's plan findings (the maintainer,
2026-09-28: *"when I do a rebuild, the list of findings in the side bar
is not cleared."*).

The dock is shared by every mode; each producer stamps its findings
(`_producer`) and replaces only its own. A build replaces plan.json, so
three producers describe something the build is replacing -- the plan's
recorded findings ("plan"), the last run's ("run") and Apply's pre-flight
verify of plan.json ("apply-preflight", read at page load and, before this
fix, never re-read until you went to Apply). All three go when a build
starts; the new plan's come back when it lands, and Apply re-reads its
pre-flight. Steps 01-03's own findings ("build") and an apply run's
("apply") stay.

The behaviour was checked in Chromium against a stand-in model (two builds,
different critic replies); these pin the served code it depends on.
"""

from __future__ import annotations

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402


@pytest.fixture
def client():
    with fastapi_testclient.TestClient(create_app()) as c:
        yield c


def test_a_build_start_empties_the_dock(client):
    # "The findings panel is still not being cleared
    # when I start a new build" -- every producer goes, not only the plan's.
    js = client.get("/static/setup.js").text
    clear = js[js.index("function clearFindingsForBuild()"):]
    clear = clear[:clear.index("\n  }\n")]
    assert "SP.setFindings([]);" in clear
    assert 'SP.showBundleMessage("");' in clear
    start = js.index("async function startBuild()")
    body = js[start:js.index("bindTableEvents(", start)]
    assert "run = data;\n      clearFindingsForBuild();" in body
    # Opening the page mid-build holds them too.
    assert 'if (run.state === "running") {\n    // The page was opened' in js
    # The old plan, redrawn meanwhile, does not put its findings back.
    assert js.count("if (!holdPlanFindings) publishPlanFindings(") == 2


def test_a_landed_build_publishes_the_new_plans_findings_only_if_it_wrote_one(client):
    js = client.get("/static/setup.js").text
    start = js.index("async function poll()")
    body = js[start:js.index("async function startBuild()", start)]
    assert "const before = planStamp(current);" in body
    assert "holdPlanFindings = false;" in body
    assert "if (planStamp(current) !== before) {" in body
    assert "publishPlanFindings((current && current.findings) || []);" in body
    assert "if (SP.planBuilt) SP.planBuilt();" in body
    # The source files' findings, emptied at the start, come back.
    assert "if (SP.publishBuildFindings) SP.publishBuildFindings();" in body


def test_apply_rereads_its_preflight_when_a_build_lands(client):
    shell = client.get("/static/shell.js").text
    assert "onPlanBuilt: (fn) =>" in shell and "planBuilt: () => planBuiltListeners.forEach(" in shell
    apply_js = client.get("/static/apply.js").text
    assert "if (SP.onPlanBuilt) SP.onPlanBuilt(fetchPreflight);" in apply_js
    # The pre-flight still stamps its findings with the producer a build clears.
    assert '_producer: "apply-preflight",' in apply_js


def test_the_bundle_message_clears_on_a_step_change_and_a_save(client):
    # "Created .../instructions.md, empty. ..."
    # "never goes away".
    shell = client.get("/static/shell.js").text
    step = shell[shell.index("function activateStep(step)"):]
    step = step[:step.index("currentStep = step;")]
    assert 'if (step !== currentStep) showBundleMessage("");' in step
    assert shell.count('showBundleMessage("");\n      absorb(data);') >= 2
    assert "publishBuildFindings: publishBuildFindings," in shell
