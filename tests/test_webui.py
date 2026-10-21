"""O6 prototype: the web UI's HTTP/WebSocket surface over atoo.watch.

Exercises `atoo.webui` the way a browser tab actually would --
start/stop the demo session, read the alert feed off the WebSocket, and
confirm a bad console IP surfaces as a status error rather than a silent,
permanently-empty watch loop. Uses fastapi's TestClient (`with client:`
so the whole test runs against one event loop, matching a real uvicorn
process -- see this module's own debugging notes in webui.py's PR: a
TestClient call made outside `with client:` tears its event loop down
between requests, which the session's background thread then can't
broadcast to).
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import _DEMO_ISSUES, create_app, demo_provider_factory  # noqa: E402
from atoo.watch import watch  # noqa: E402

FIXTURE_PLAN_PATH = Path(__file__).parent / "fixtures" / "setup_viewer.plan.json"
FIXTURE_WATCH_CONDITIONS_PATH = Path(__file__).parent / "fixtures" / "sample.watch.json"


@pytest.fixture
def client():
    app = create_app()
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Atoo" in r.text


def test_the_served_page_says_atoo_and_never_the_old_name(client):
    """The product is Atoo. The page title and the header say
    so, and no served asset still carries the old name -- the Python
    suite cannot see a browser string any other way."""
    page = client.get("/").text
    assert "<title>Atoo</title>" in page
    assert "<h1>Atoo</h1>" in page
    # The brass chip holds A2 (docs/marketing/naming-and-brand.md, "Colour
    # and mark"); it held SP.
    assert '<span class="brand-mark">A2</span>' in page
    # Spelled in two halves, so a release's old-name gate does not find it
    # in this test.
    old_name = "show" + "proof"
    assert old_name not in page.lower()
    static = Path(__file__).parents[1] / "atoo" / "web" / "static"
    for asset in sorted(static.iterdir()):
        r = client.get("/static/" + asset.name)
        assert r.status_code == 200, asset.name
        assert old_name not in r.text.lower(), asset.name


def test_static_assets_served(client):
    r = client.get("/static/watch.js")
    assert r.status_code == 200
    r = client.get("/static/styles.css")
    assert r.status_code == 200


def test_static_assets_and_index_are_not_cached(client):
    # This page and its assets change as this prototype does -- a browser
    # that caches them without revalidating (no Cache-Control header at
    # all, StaticFiles' default) can keep showing an old bug, or an old
    # fix, after a `git pull`, until someone thinks to hard-refresh. Every
    # request must revalidate (a 304 is fine and expected; a cached hit
    # with no request at all is the failure mode this guards against).
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/static/watch.js").headers["cache-control"] == "no-cache"
    assert client.get("/static/styles.css").headers["cache-control"] == "no-cache"


def test_status_starts_idle(client):
    r = client.get("/api/status")
    body = r.json()
    assert {k: body[k] for k in ("running", "label", "error")} == {
        "running": False, "label": "", "error": None}


def test_demo_watch_end_to_end(client):
    client.post("/api/console", json={"demo": True})
    r = client.post("/api/watch/start", json={"source": "console", "interval": 0.1})
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is True
    assert body["label"] == "Demo"

    with client.websocket_connect("/ws/watch") as ws:
        status = ws.receive_json()
        assert status["type"] == "status"
        assert status["running"] is True

        baseline = ws.receive_json()
        assert baseline["type"] == "event"
        assert baseline["baseline"] is True
        # `demo_provider_factory` always starts from the clean base rig --
        # the very first read is never alerted on regardless. Clean means
        # nothing above info: the Demo's conventions start every channel
        # fader at the floor, which L002 notes at INFO, strip by strip.
        clean = baseline["all_findings"]
        assert {f["rule_id"] for f in clean if f["severity"] != "info"} == set()

        # From here the demo is randomized (see test_demo_provider_never_
        # duplicates_or_grows_unbounded for the deterministic version of
        # these guarantees) -- just check a few more events arrive with
        # the shape the frontend depends on.
        for _ in range(5):
            event = ws.receive_json()
            assert event["type"] == "event"
            assert event["baseline"] is False
            all_keys = [(f["rule_id"], tuple(f["addresses"])) for f in event["all_findings"]]
            assert len(all_keys) == len(set(all_keys)), "a single event must never repeat a finding"
            assert len(all_keys) <= len(clean) + len(_DEMO_ISSUES) * 2  # generous ceiling, see the issue bank

    r = client.post("/api/watch/stop")
    assert r.json()["running"] is False


def test_demo_provider_never_duplicates_or_grows_unbounded():
    """Unit-level, deterministic version of the same guarantee the
    end-to-end test above only spot-checks: seeded so the randomness is
    reproducible, run long enough to actually exercise `_DEMO_ISSUES`
    (including its Severity.ERROR entry -- the demo used to show
    warning/info only), and asserted against `atoo.watch.watch`'s own
    new/cleared accounting rather than raw event shape.

    This replaces the old fixed before/after alternation, which dumped
    every seeded finding at once and then repeated the identical dump/
    clear every single interval forever -- what looked like duplicates
    piling up down the page. The fix: `active` in `demo_provider_factory`
    is a set (no key can appear twice) that gains or loses at most one
    issue per read, bounded at `len(_DEMO_ISSUES)`, chosen randomly rather
    than as a mass toggle.
    """
    provider, closer = demo_provider_factory(rng=random.Random(42))
    assert closer is None

    # The rules as the Watch page runs them on the Demo show: R012 told which
    # splits the plan states (the Demo's vocals are parallel on purpose).
    from atoo import webui
    from atoo.audit import DEFAULT_RULES, split_path_rules
    plan = json.loads((Path(webui.DEMO_SHOW_DIR) / "plan.json").read_text(encoding="utf-8"))
    events = list(watch(provider, rules=split_path_rules(DEFAULT_RULES, plan), interval=0,
                        max_iterations=300, sleep=lambda s: None))

    # Baseline: the clean rig, nothing armed yet -- nothing above info (the
    # Demo's conventions start every channel fader at the floor, L002 INFO).
    clean = events[0].all_findings
    assert [f.rule_id for f in clean if f.severity.value != "info"] == []

    severities_seen = set()
    quiet_ticks = 0
    for event in events:
        keys = [(f.rule_id, f.addresses) for f in event.all_findings]
        assert len(keys) == len(set(keys)), "no event may show the same finding twice"
        assert len(event.all_findings) <= len(clean) + len(_DEMO_ISSUES) * 2  # bounded, not "and it keeps growing"
        # A finding can't be new and cleared in the same tick -- that
        # would mean two different issues share a (rule_id, addresses)
        # key, which the independence check in atoo/webui.py's
        # `_DEMO_ISSUES` comment promises can't happen.
        assert not (set(keys) & {(f.rule_id, f.addresses) for f in event.cleared_findings})
        for f in event.all_findings:
            severities_seen.add(f.severity.value)
        if event.iteration > 0 and not event.new_findings and not event.cleared_findings:
            quiet_ticks += 1

    # Real showtime doesn't spike every parameter at once -- some ticks
    # should pass with nothing changing at all (this is what "randomly
    # issue and revoke, not dump-and-repeat" actually means operationally).
    assert quiet_ticks > 0
    # And the severity range promised above ("include a few errors") has
    # to actually show up, not just exist in the issue bank unreachable.
    assert "error" in severities_seen
    assert "warning" in severities_seen
    assert "info" in severities_seen


def test_unreachable_console_reports_error_not_silence(client):
    r = client.post(
        "/api/watch/start",
        json={"source": "console", "console": "192.0.2.1", "port": 2223, "timeout": 0.2, "interval": 0.5},
    )
    assert r.status_code == 200  # accepted -- the failure surfaces once the background thread tries it

    with client.websocket_connect("/ws/watch") as ws:
        msg = ws.receive_json()
        while msg.get("type") != "error":
            msg = ws.receive_json()
        assert "no reply from 192.0.2.1:2223" in msg["error"]

    status = client.get("/api/status").json()
    assert status["running"] is False
    assert "192.0.2.1" in status["error"]


def test_starting_a_new_session_stops_the_previous_one(client):
    client.post("/api/console", json={"demo": True})
    client.post("/api/watch/start", json={"source": "console", "interval": 5.0})
    assert client.get("/api/status").json()["running"] is True

    client.post("/api/console", json={"demo": True})
    r = client.post("/api/watch/start", json={"source": "console", "interval": 5.0})
    assert r.json()["running"] is True  # replaced, not rejected -- FR-6.7 is one session at a time

    client.post("/api/watch/stop")
    assert client.get("/api/status").json()["running"] is False


def test_missing_console_ip_is_a_client_error(client):
    r = client.post("/api/watch/start", json={"source": "console", "interval": 1.0})
    assert r.status_code == 400


def test_unknown_source_is_a_client_error(client):
    r = client.post("/api/watch/start", json={"source": "bogus", "interval": 1.0})
    assert r.status_code == 400


# ---- The plan (FR-6.3) -- `/api/plan*`, read-only. What was
# The viewer at `/setup` is Build step 04 now, drawn by the
# same `setup.js`; these tests pin the API and the renderer it kept.


def test_api_plan_with_nothing_loaded_is_a_documented_404():
    # No `--plan` given at startup, and no `/api/plan/load` call yet --
    # a clear, documented "nothing loaded" shape (a 404 with an `error`
    # body), not a bare crash or an ambiguous empty 200.
    app = create_app()
    with fastapi_testclient.TestClient(app) as c:
        r = c.get("/api/plan")
        assert r.status_code == 404
        assert r.json() == {"error": "no plan loaded"}


def test_api_plan_returns_plan_loaded_at_startup():
    plan = json.loads(FIXTURE_PLAN_PATH.read_text())
    app = create_app(initial_plan=plan, initial_plan_path=str(FIXTURE_PLAN_PATH))
    with fastapi_testclient.TestClient(app) as c:
        r = c.get("/api/plan")
        assert r.status_code == 200
        body = r.json()
        assert body["path"] == str(FIXTURE_PLAN_PATH)
        assert body["plan"] == plan
        assert body["plan"]["channels"][0]["name"] == "Kick"


def test_plan_load_with_valid_path_replaces_loaded_plan(client):
    r = client.post("/api/plan/load", json={"path": str(FIXTURE_PLAN_PATH)})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == str(FIXTURE_PLAN_PATH)
    assert body["plan"]["channels"][0]["name"] == "Kick"

    # A subsequent GET reflects the newly loaded plan, not whatever (if
    # anything) was loaded before.
    r2 = client.get("/api/plan")
    assert r2.status_code == 200
    assert r2.json()["plan"]["channels"][0]["name"] == "Kick"


def test_plan_load_with_missing_file_is_a_clean_error(client):
    r = client.post("/api/plan/load", json={"path": "/no/such/plan.json"})
    assert r.status_code == 400
    assert "error" in r.json()

    # Nothing was loaded -- GET /api/plan still reports "nothing loaded".
    r2 = client.get("/api/plan")
    assert r2.status_code == 404


def test_plan_load_with_invalid_json_is_a_clean_error(client, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    r = client.post("/api/plan/load", json={"path": str(bad)})
    assert r.status_code == 400
    assert "error" in r.json()


def test_the_served_pages_read_as_explanations_and_not_as_a_project_diary(client):
    """View-source is the first thing a curious engineer opens,
    so no served page (script, style or markup) attributes a decision to a
    person on a date, cites the project's rulebook or plan, or points at a
    document, mockup or run the public tree does not have. Asserted over
    the served assets because the Python suite cannot see the browser code."""
    diary = re.compile(
        r"maintainer\W+\d{4}-\d{2}-\d{2}"
        r"|CLAUDE\.md|WORK_PLAN|OPTIONS-H"
        r"|docs/(?!user/)[a-z]+/|\bmockups/|\barchive/|\bexperiments/|ui-style\.md"
    )
    static = Path(__file__).resolve().parent.parent / "atoo" / "web" / "static"
    names = sorted(p.name for p in static.iterdir() if p.is_file())
    assert {"setup.js", "shell.js", "watch.js", "styles.css", "shell.html"} <= set(names)
    for name in names:
        served = client.get(f"/static/{name}")
        assert served.status_code == 200, name
        found = diary.search(served.text)
        assert not found, f"/static/{name} still carries {found.group(0)!r}"
    assert not diary.search(client.get("/").text)


def test_setup_is_retired_and_its_renderer_is_not(client):
    """Step 04 covers everything `/setup` did, so the route
    and its page are gone. `setup.js` is not -- it is still the one thing
    that draws a plan, now inside the shell -- and a stale link to the
    dead route would be a 404 an operator clicks."""
    assert client.get("/setup").status_code == 404
    assert client.get("/static/setup.html").status_code == 404
    assert client.get("/static/setup.js").status_code == 200
    assert 'href="/setup"' not in client.get("/").text, "/ still links to /setup"


def test_api_plan_carries_the_plans_own_findings():
    """Step 04 draws the plan and puts its findings in the dock from ONE
    body -- the findings the build recorded in `meta`, read back, never
    recomputed."""
    plan = json.loads(FIXTURE_PLAN_PATH.read_text())
    plan["meta"]["verify_findings"] = {
        "errors": [{"severity": "error", "code": "output.socket-out-of-range",
                    "message": "LCL output 99 does not exist", "where": "outputs[Matrix]",
                    "source": "verify"}],
        "warnings": [],
    }
    app = create_app(initial_plan=plan, initial_plan_path=str(FIXTURE_PLAN_PATH))
    with fastapi_testclient.TestClient(app) as c:
        body = c.get("/api/plan").json()
    assert [(f["source"], f["code"]) for f in body["findings"]][0] == ("verify", "output.socket-out-of-range")


def test_a_plan_built_before_18_still_opens_with_its_critic_findings_named():
    """**A plan whose critic findings carry the older `kind`** -- no
    `category` and no `code`, which is what every plan.json written before
    that issue has on disk. They must still reach the dock as critic
    findings with a code, not as blanks.

    Stated as a two-line plan rather than read out of
    `examples/touringband/plan.json`, which is where this test used to get
    its legacy findings. That bundle is rebuilt between shows, and the
    rebuild of 2026-09-23 wrote newer findings into it -- so the test
    went green-then-red on a property of the maintainer's working file, while the
    old shape it exists to defend went untested either way. A legacy plan
    cannot stop being legacy, so this one is written out here."""
    from atoo.webui import _plan_findings

    plan = {"meta": {"critic_findings": [
        {"severity": "error", "kind": "intent", "where": "Drums Comp",
         "message": "the conventions ask for heavy compression and nothing encodes it"},
    ]}}
    critic = [f for f in _plan_findings(plan) if f["source"] == "critic"]
    assert critic, "sanity: this plan carries critic findings"
    assert critic[0]["category"] == "intent"
    assert critic[0]["code"] == "critic.intent"
    assert "kind" not in critic[0]
    assert critic[0]["where"] == "Drums Comp"


def test_step_04_lists_no_findings_of_its_own(client):
    """An earlier change ("after a plan is rebuilt there's
    typically a very long list of warnings and info findings down the page
    under the build status. That is what the sidebar is for"). Step 04's
    "Critic pass", "Verify" and "The conventions themselves" lists are
    gone; the plan's findings are in the dock (`publishPlanFindings`) and
    step 04 draws one line counting them. The Python suite cannot see the
    page, so this pins the served asset.

    The critic's older `kind` is still read -- in Python now
    (`_plan_finding`, tested above), which is what feeds the dock."""
    js = client.get("/static/setup.js").text
    for gone in ("renderCriticFindings", "renderVerifyFindings", "renderBuildFindings",
                 "setup-findings-list", "The conventions themselves", "meta_grouped"):
        assert gone not in js, f"setup.js still draws a findings list ({gone})"
    assert 'id="plan-findings-summary"' in js
    assert "function paintFindingsSummary()" in js
    assert "SP.onFindingsChange(paintFindingsSummary)" in js
    # It counts what the dock SHOWS, and says when a pass never ran.
    assert "SP_.shownFindings" in js
    assert "meta.verify_findings == null" in js and "meta.critic_findings == null" in js
    assert "publishPlanFindings(current.findings || [])" in js


def test_setup_page_names_each_calls_effort(client):
    """The critic and the watchlist run at their own effort (2026-09-27),
    and the build readout's snapshot carries it as `effort` -- on the call
    in flight and on each finished call's chip. The Python suite cannot
    see the page read it, so this asserts the served JS does."""
    js = client.get("/static/setup.js").text
    assert 'p.effort ? "effort " + p.effort' in js
    assert 'call.effort ? "effort " + call.effort' in js


def test_setup_page_names_the_fixup_call(client):
    """The one fix-up round (2026-09-29) is a call of its own, labelled
    `fixup`; step 04's chip and live phase read its words from
    PHASE_WORDS rather than showing the bare label."""
    js = client.get("/static/setup.js").text
    assert 'fixup: "Fix-up round"' in js


def test_setup_page_names_the_resolve_call(client):
    """The resolve step (2026-09-30, `conventions_resolve.py`) is a call of
    its own, labelled `resolve`; step 04's chip and live phase name it."""
    js = client.get("/static/setup.js").text
    assert 'resolve: "Resolving the conventions"' in js


def test_step_01_says_whether_the_resolved_conventions_are_fresh(tmp_path, monkeypatch):
    """Nothing is said while there is no resolved file (the next build
    makes one, and says so); a file beside the conventions is reported
    fresh or stale, at INFO, on the conventions tile."""
    from atoo import conventions_resolve
    from atoo.ai_provider import FakeProvider

    monkeypatch.delenv("ATOO_RESOLVE", raising=False)
    directory = _build_bundle(tmp_path)
    house = _house(tmp_path)

    def sources():
        app = create_app(initial_bundle=str(directory), initial_conventions=str(house))
        with fastapi_testclient.TestClient(app) as c:
            return c.get("/api/build/sources").json()

    data = sources()
    assert "build.resolved-conventions" not in _codes(data)
    assert "resolved" not in data["conventions"]

    resolved = conventions_resolve.resolved_path(house)
    resolved.write_text(conventions_resolve.run(
        HOUSE_CONVENTIONS, house.name,
        provider=FakeProvider(response='- a rule [conventions: "x"]\n')))
    data = sources()
    assert data["conventions"]["resolved"]["state"] == "fresh"
    [finding] = [f for f in data["findings"] if f["code"] == "build.resolved-conventions"]
    assert finding["severity"] == "info" and "is fresh" in finding["message"]

    house.write_text(HOUSE_CONVENTIONS + "\n- Kick is red.\n")
    data = sources()
    assert data["conventions"]["resolved"]["state"] == "stale"
    assert "the conventions changed" in data["conventions"]["resolved"]["reason"]


def test_setup_page_names_each_calls_model(client):
    """The critic and the watchlist run on their own model too (2026-09-28,
    docs/developer/build-cost-reduction.md slice A: Haiku by default), and
    the snapshot carries it as `model` on every call. Step 04's chips and
    the plan's Build log headings must name it, or a Haiku critic looks
    like a Sonnet one -- and the Python suite cannot see the page."""
    js = client.get("/static/setup.js").text
    assert 'call.model ? call.model' in js, "each finished call's chip names its model"
    assert 'p.model ? p.model' in js, "the call in flight's chip names its model"
    assert "usage.model" in js, "the Build log's per-role heading names the model it ran on"


def test_setup_page_renders_meta_build_log(client):
    """docs/developer/build-lessons-2026-09-27.md, part C: a plan's
    `meta.build_log` (each role's kept thinking-summary notes and usage)
    gets its own disclosure on step 04. The Python suite cannot see the
    browser render it, so this pins that the served JS still reads the field."""
    js = client.get("/static/setup.js").text
    assert "meta.build_log" in js, "setup.js must read plan.meta.build_log"
    assert "Build log" in js
    # Each role's heading carries its thinking count.
    assert "usage.thinking_source" in js and "usage.thinking" in js


def test_setup_page_no_longer_renders_expectations_findings(client):
    """An earlier change retired expectations. The Python suite cannot see the browser,
    so the only thing standing between "the key is gone from
    `build`" and "the page still draws a section for it" is an assertion
    over the served asset.

    The fixture plan this suite loads deliberately still carries
    `meta.expectations_findings` -- it is the old-plan-on-disk case -- so
    the page must open it and simply not draw that section.
    """
    js = client.get("/static/setup.js").text
    assert 'renderVerifyFindings("Expectations"' not in js, (
        "setup.js still renders an Expectations findings section for a "
        "feature that no longer exists"
    )
    assert "meta.expectations_findings" not in js
    assert "renderBuildOutput(plan, current)" in js, (
        "sanity check: the build-status block, which stays, is still rendered"
    )
    # And the fixture really is the old-plan case, or the assertion above
    # proves nothing about backwards compatibility.
    meta = json.loads(FIXTURE_PLAN_PATH.read_text())["meta"]
    assert "expectations_findings" in meta
    loaded = client.post("/api/plan/load", json={"path": str(FIXTURE_PLAN_PATH)})
    assert loaded.status_code == 200, "an old plan carrying the key must still load"


def test_the_bundle_payload_has_no_expectations_slot(client):
    """The bundle bar's "Also in this bundle" strip is built straight from
    `bundle.SLOTS` (shell.js `renderBundle`), so a retired slot disappears
    from the page only if it disappears from this payload."""
    from atoo import bundle as bundle_mod
    assert "expectations.toml" not in bundle_mod.SLOTS
    js = client.get("/static/shell.js").text
    assert "expectations" not in js.lower()
    r = client.get("/api/bundle")
    if r.status_code == 200:
        assert all(s["slot"] != "expectations.toml" for s in r.json()["slots"])


def test_setup_page_reads_verify_findings_by_their_stable_code(client):
    """The other half of the same wire shape. `code`/`where`/`message`
    survived an earlier change unchanged -- this pins that, since a rename there would
    break the page just as quietly."""
    # The dock is the only thing that renders a finding.
    js = client.get("/static/shell.js").text
    for field in ("finding.code", "finding.where", "finding.message", "finding.severity"):
        assert field in js


def test_watch_page_unaffected_by_plan_state():
    # Loading a plan must not change anything about Watch mode or its
    # routes.
    plan = json.loads(FIXTURE_PLAN_PATH.read_text())
    app = create_app(initial_plan=plan, initial_plan_path=str(FIXTURE_PLAN_PATH))
    with fastapi_testclient.TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "Atoo" in r.text
        status = c.get("/api/status").json()
        assert {k: status[k] for k in ("running", "label", "error")} == {
            "running": False, "label": "", "error": None}


# ---- Watch-conditions panel (FR-6.5) -- the Watch page's own
# `/api/watch-conditions*` surface, plus `ConnectRequest.watch_conditions_path`
# threading a watch session's rules. None of this touches `/api/plan*` or
# Build; see webui.py's own comments on that boundary.


def test_api_watch_conditions_with_nothing_loaded_is_a_documented_404():
    app = create_app()
    with fastapi_testclient.TestClient(app) as c:
        r = c.get("/api/watch-conditions")
        assert r.status_code == 404
        assert r.json() == {"error": "no watch-conditions file loaded", "bundle_file": None}


def test_api_watch_conditions_returns_conditions_loaded_at_startup():
    app = create_app(initial_watch_conditions_path=str(FIXTURE_WATCH_CONDITIONS_PATH))
    with fastapi_testclient.TestClient(app) as c:
        r = c.get("/api/watch-conditions")
        assert r.status_code == 200
        body = r.json()
        assert body["path"] == str(FIXTURE_WATCH_CONDITIONS_PATH)
        assert body["watch_conditions"][0]["id"] == "crowd-mic-never-muted"


def test_create_app_degrades_gracefully_on_a_bad_initial_watch_conditions_path(tmp_path):
    # Mirrors ui_cmd's own fail-fast check having already run in the real
    # CLI path -- create_app() itself must not crash even if handed a bad
    # path directly (as this test does), it just ends up with nothing
    # loaded, same as if the flag were never passed.
    app = create_app(initial_watch_conditions_path=str(tmp_path / "does-not-exist.json"))
    with fastapi_testclient.TestClient(app) as c:
        r = c.get("/api/watch-conditions")
        assert r.status_code == 404


def test_watch_conditions_load_with_valid_path_replaces_loaded_conditions(client):
    r = client.post("/api/watch-conditions/load", json={"path": str(FIXTURE_WATCH_CONDITIONS_PATH)})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == str(FIXTURE_WATCH_CONDITIONS_PATH)
    assert len(body["watch_conditions"]) == 2

    r2 = client.get("/api/watch-conditions")
    assert r2.status_code == 200
    assert r2.json()["watch_conditions"][0]["id"] == "crowd-mic-never-muted"


def test_watch_conditions_load_with_missing_file_is_a_clean_error(client):
    r = client.post("/api/watch-conditions/load", json={"path": "/no/such/watch.json"})
    assert r.status_code == 400
    assert "error" in r.json()
    assert client.get("/api/watch-conditions").status_code == 404


def test_watch_conditions_load_with_invalid_json_is_a_clean_error(client, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    r = client.post("/api/watch-conditions/load", json={"path": str(bad)})
    assert r.status_code == 400
    assert "error" in r.json()


def test_watch_conditions_load_with_malformed_conditions_is_a_400_not_a_500(client, tmp_path):
    # A structurally-invalid file (unknown field) -- WatchConditionsError,
    # not a crash.
    bad = tmp_path / "bad_field.watch.json"
    bad.write_text(json.dumps({"watch_conditions": [{
        "id": "x", "description": "x", "channel": "x",
        # `dca` stood in for "unknown field" here until an earlier change made it
        # a real one; `gain` is still genuinely unknown.
        "field": "gain", "operator": "==", "value": True, "severity": "info",
    }]}))
    r = client.post("/api/watch-conditions/load", json={"path": str(bad)})
    assert r.status_code == 400
    assert "unknown field" in r.json()["error"]


def test_watch_conditions_save_round_trips_through_the_loader(client, tmp_path):
    out = tmp_path / "written.watch.json"
    conditions = [{
        "id": "kick-never-muted",
        "description": "Kick must never be muted",
        "channel": "Kick",
        "field": "muted",
        "operator": "==",
        "value": False,
        "severity": "error",
    }]
    r = client.post("/api/watch-conditions/save", json={"path": str(out), "watch_conditions": conditions})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == str(out)
    assert body["watch_conditions"] == conditions
    assert out.is_file()

    # What was written actually round-trips through the real loader --
    # not just accepted by the endpoint's own validation call.
    from atoo.watch_conditions import load_watch_conditions
    assert load_watch_conditions(out) == conditions

    # And GET now reflects it, same as a load.
    r2 = client.get("/api/watch-conditions")
    assert r2.status_code == 200
    assert r2.json()["watch_conditions"] == conditions


def test_watch_conditions_save_rejects_invalid_conditions_without_writing(client, tmp_path):
    out = tmp_path / "never_written.watch.json"
    bad_conditions = [{
        "id": "dup", "description": "x", "channel": "x",
        "field": "muted", "operator": ">", "value": True, "severity": "info",
    }]
    r = client.post("/api/watch-conditions/save", json={"path": str(out), "watch_conditions": bad_conditions})
    assert r.status_code == 400
    assert "error" in r.json()
    assert not out.exists()  # never written -- validated before disk touched


def test_watch_conditions_save_rejects_duplicate_ids(client, tmp_path):
    out = tmp_path / "dup.watch.json"
    conditions = [
        {"id": "same", "description": "a", "channel": "a", "field": "muted",
         "operator": "==", "value": True, "severity": "info"},
        {"id": "same", "description": "b", "channel": "b", "field": "muted",
         "operator": "==", "value": True, "severity": "info"},
    ]
    r = client.post("/api/watch-conditions/save", json={"path": str(out), "watch_conditions": conditions})
    assert r.status_code == 400
    assert "duplicate" in r.json()["error"]
    assert not out.exists()


def test_watch_start_with_watch_conditions_path_threads_custom_rules_into_the_session(client, tmp_path):
    # Kick's mute is always 0 (false) in the demo base rig
    # (atoo/web/demo_states/before.json) and no `_DEMO_ISSUES` entry
    # ever touches /ch/1/mute -- so a watch condition demanding Kick be
    # muted fires a WATCH: finding on every single read, deterministically,
    # proving `req.watch_conditions_path` actually reached `watch()`'s
    # `rules=` rather than being silently ignored.
    watch_conditions_file = tmp_path / "kick_always_muted.watch.json"
    watch_conditions_file.write_text(json.dumps({"watch_conditions": [{
        "id": "kick-must-be-muted",
        "description": "Kick must be muted (test-only condition, never true in the demo rig)",
        "channel": "Kick",
        "field": "muted",
        "operator": "==",
        "value": True,
        "severity": "error",
    }]}))

    client.post("/api/console", json={"demo": True})
    r = client.post("/api/watch/start", json={
        "source": "console", "interval": 0.1, "watch_conditions_path": str(watch_conditions_file),
    })
    assert r.status_code == 200
    assert r.json()["running"] is True

    with client.websocket_connect("/ws/watch") as ws:
        ws.receive_json()  # status
        baseline = ws.receive_json()
        assert baseline["type"] == "event"
        assert baseline["baseline"] is True
        rule_ids = [f["rule_id"] for f in baseline["all_findings"]]
        assert "WATCH:kick-must-be-muted" in rule_ids

    client.post("/api/watch/stop")


def test_watch_start_with_bad_watch_conditions_path_is_a_clean_error(client):
    client.post("/api/console", json={"demo": True})
    r = client.post("/api/watch/start", json={
        "source": "console", "interval": 1.0, "watch_conditions_path": "/no/such/watch.json",
    })
    assert r.status_code == 400
    assert "error" in r.json()
    # And no session was started over it.
    assert client.get("/api/status").json()["running"] is False


def test_watch_start_with_no_watch_conditions_path_behaves_exactly_as_before(client):
    # Omitting the field entirely (today's existing request shape) must
    # not change behavior at all -- built-in rules only.
    client.post("/api/console", json={"demo": True})
    r = client.post("/api/watch/start", json={"source": "console", "interval": 0.1})
    assert r.status_code == 200
    assert r.json()["running"] is True
    client.post("/api/watch/stop")


def test_served_watch_js_offers_every_watch_condition_field(client):
    # An earlier change added `dca`/`mute_group`/`patch` to the Python vocabulary.
    # `watch.js` keeps its OWN copy of that list (WC_FIELDS) to build the
    # editor's <select>, and the Python suite cannot see this file --
    # a rename or extension that crosses into
    # atoo/web/static/ is invisible to pytest and fails SILENTLY in
    # the browser. Crude, but it is the only thing standing between a
    # Python-side vocabulary change and an editor that cannot author the
    # new conditions.
    body = client.get("/static/watch.js").text
    for field in ("muted", "fader_db", "dca", "mute_group", "patch",
                  "send_on", "send_db", "send_mode", "phantom"):
        assert f'"{field}"' in body, f"watch.js does not offer the {field!r} watch-condition field"
    # The relational fields take a string value, so the editor needs a
    # text input for them -- not the checkbox/number the scalar fields use.
    assert "WC_TEXT_FIELDS" in body
    assert "wc-value-text" in body


def test_step_04_opens_a_plan_from_its_tile_not_a_path_box(client):
    """The "open a plan.json that is somewhere else"
    row belongs on the Plan tile like every other file. Its path box is a
    hidden input the tile's Change file fills (filebrowser.js `browseInto`),
    so no example path is shown to go stale."""
    import re
    html = client.get("/").text
    assert "Or open a plan.json that is somewhere else" not in html
    tile = html[html.index('id="tab-plan"'):html.index('class="help-pop pipeline-help"')]
    assert 'id="plan-browse-btn"' in tile and "Change file" in tile
    assert re.search(r'<input type="hidden" id="plan-path">', html)


def test_setup_page_shows_which_console_the_plan_was_built_for(client):
    """`meta.console_model` decides which panel a plan's socket
    numbers were checked against -- a plan for a Compact patches local
    inputs 9..24 that a full-size WING does not have. The Setup page
    renders the meta block, so a field it never reads is a field the
    operator never sees.

    Asserted over the served asset because the Python suite has no way to
    see the browser code: a frontend that simply never read
    this key would show nothing and break no test.
    """
    js = client.get("/static/setup.js").text
    assert "meta.console_model" in js, (
        "setup.js must render meta.console_model -- without it the page "
        "silently omits which console the plan is for"
    )
    # An older plan has no such key, and `esc(undefined)` renders as an
    # empty string -- the exact silently-blank failure an earlier change hit.
    assert "Console model not stated -- built by an older version." in js, (
        "setup.js must say the field is absent rather than rendering blank "
        "for a plan that predates it"
    )


def test_setup_page_renders_every_processing_field_the_plan_can_carry(client):
    """The rule that a renamed field breaks the page silently, applied forward rather than after the
    fact: the Python suite cannot see the browser code, so a field Python
    can write and render is a field the page can silently omit.

    An earlier change adds `processing.eq`; the phase 1 six had
    already been sitting in render.py and in apply.py's write targets
    while this page showed only `hpf_hz` and `preset` -- an engineer
    reviewing a plan in the Setup UI would have seen no sign that a trim
    or an EQ curve was about to be written to their desk.
    """
    js = client.get("/static/setup.js").text
    for field in ("hi_cut_hz", "tilt_db", "trim_db", "balance_db",
                  "invert", "gain_db", "processing.eq"):
        assert field in js, f"setup.js never reads processing.{field}"
    assert "eq.mix_pct" in js, "setup.js never reads the EQ's wet/dry mix"
    for band_field in ("band.freq_hz", "band.gain_db", "band.q", "band.shape"):
        assert band_field in js, f"setup.js never reads an EQ band's {band_field}"


def test_setup_page_distinguishes_the_two_eqs(client):
    """A channel has two EQs at different tap points. A page that showed
    both as "EQ" would read as a duplicate or a typo rather than as the
    two separate controls they are."""
    js = client.get("/static/setup.js").text
    assert "processing.presend_eq" in js
    assert "PreSend EQ" in js


# ---------------------------------------------------------------- 
# the Watch page's console IP field seeds from ATOO_CONSOLE / [console]
#
# Two halves, tested two different ways, because the standing
# warning about the browser applies squarely here: the Python suite cannot see
# `atoo/web/static/`, and `esc()`-style rendering turns an
# `undefined` payload key into an empty string rather than an error. So
# the server half is tested over the response, and the browser half is
# tested by asserting over the text of the served `watch.js` -- crude, but
# it is the only thing standing between a Python rename and a page that
# quietly stops seeding (or, far worse, quietly stops SAYING it seeded).

SEEDED_CONSOLE = {
    "address": "192.0.2.16", "address_source": "ATOO_CONSOLE",
    "port": 2223, "port_source": None,
    "timeout": 1.0, "timeout_source": None,
}


def _shell_blob(html: str) -> dict:
    start = html.index('id="initial-shell"')
    return json.loads(html[html.index(">", start) + 1:html.index("</script>", start)])


def test_watch_mode_embeds_the_resolved_console_defaults():
    """Watch is a mode of the shell, and the console it
    seeds from is the shell's ONE resolved console -- `initial-shell`'s
    `console` key, the same dict the bundle bar's readout shows. The old
    Watch page carried an identical second copy as `initial-console`;
    that blob is gone, and nothing may still be looking for it."""
    app = create_app(initial_console=SEEDED_CONSOLE)
    with fastapi_testclient.TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert _shell_blob(r.text)["console"] == SEEDED_CONSOLE
        assert 'id="initial-console"' not in r.text


def test_watch_mode_with_no_console_defaults_is_todays_page():
    """No environment variable, no config file: an empty IP box and no
    provenance line, exactly as. `create_app()` resolves
    nothing itself -- `ui_cmd` does -- so the default really is 'nothing
    seeded'."""
    app = create_app()
    with fastapi_testclient.TestClient(app) as c:
        assert _shell_blob(c.get("/").text)["console"] == {}


def test_watch_mode_console_defaults_are_read_fresh_per_request():
    app = create_app(initial_console=dict(SEEDED_CONSOLE))
    with fastapi_testclient.TestClient(app) as c:
        assert "192.0.2.16" in c.get("/").text
        app.state.console_defaults = dict(SEEDED_CONSOLE, address="192.0.2.19")
        assert "192.0.2.19" in c.get("/").text


def test_the_page_escapes_a_closing_tag_in_a_console_origin():
    """A config path is operator-supplied text, and `</` inside a
    `<script>` block closes it early -- the rest of the JSON would land
    in the document as markup."""
    app = create_app(initial_console=dict(
        SEEDED_CONSOLE, address_source="</script><b>x</b> [console]"))
    with fastapi_testclient.TestClient(app) as c:
        r = c.get("/")
        assert "</script><b>" not in r.text
        assert "<\\/script>" in r.text


def test_watch_js_follows_the_bundle_bars_console(client):
    """The console address is *"Editable in the bundle
    bar only"*. Watch used to carry its own IP and port boxes, seeded from
    the same resolved console -- two places to type an address on
    one page, so Watch could be reading one desk while Apply wrote another.
    Now watch.js reads the shell's ONE console, redraws when the bar
    changes it, and Start sends no address at all (the server watches the
    bar's). Asserted over the served asset because nothing else can see
    it, and loaded after shell.js or `window.Atoo` does not exist."""
    js = client.get("/static/watch.js").text
    assert "const SP = window.Atoo || null;" in js
    assert "return SP.console() || {};" in js, (
        "watch.js never reads the shell's console -- the readout would stay blank")
    assert "SP.onConsoleChange(" in js, (
        "watch.js never hears the bar change -- it would name the old desk")
    for key in ("desk.address", "desk.port", "desk.timeout", "desk.timeout_source"):
        assert key in js, f"watch.js never reads the {key!r} key"
    # Nothing on this form chooses a desk any more.
    assert "body.console" not in js and "body.port" not in js, (
        "watch.js still sends an address -- the console is the bar's, not this form's")
    for gone in ("consoleIp", "consolePort", "seedConsoleFields", "is-seeded"):
        assert gone not in js, f"watch.js still carries the retired {gone!r}"
    html = client.get("/static/shell.html").text
    assert (html.index('<script src="/static/shell.js">')
            < html.index('<script src="/static/watch.js">')), (
        "watch.js must load after shell.js, which defines window.Atoo"
    )


def test_the_browser_severity_ladder_matches_pythons(client):
    """`critical` was dropped from `Severity` on 2026-09-23, and the
    browser keeps its own copy of the ladder in three places -- the sort
    order, the finding labels, and the watch-condition severity
    `<select>`. The Python suite cannot see any of them, and a stale
    `critical` there is not a crash: a pill nothing ever increments, and a
    `<select>` offering a value the loader now refuses to read back.

    Asserted over the served assets for exactly that reason."""
    from atoo.diagnostics import Severity

    js = client.get("/static/watch.js").text
    page = client.get("/").text
    css = client.get("/static/styles.css").text

    for severity in (s.value for s in Severity):
        assert severity in js, f"watch.js never mentions the {severity!r} severity"

    assert "critical" not in js, (
        "watch.js still carries the dropped `critical` severity -- Python can never "
        "send one, so its pill would sit at 0 forever and its <select> option would "
        "write a watch.json the loader refuses"
    )
    assert "critical" not in page, "the page still renders a `critical` count pill"
    assert "critical" not in css, "styles.css still styles a `critical` severity"
    # Every served script, not just the one this test was written for:
    # Watch now shares a page with Build and Apply.
    for asset in ("shell.js", "setup.js", "apply.js"):
        assert "critical" not in client.get(f"/static/{asset}").text, asset


def test_watch_js_says_which_console_it_watches_without_repeating_the_address(client):
    """The bar is where the desk is named, with its provenance.
    Watch's line says
    in words which console Start watches -- the bar's, or Demo -- and no
    longer prints the address or its provenance a second time. A running
    watch whose desk the bar has since moved away from still says so
    rather than quietly carrying on under the new name."""
    js = client.get("/static/watch.js").text
    assert "SP.consoleProvenance(desk)" not in js
    render = js[js.index("function renderWatchConsole()"):]
    render = render[:render.index("\n  }\n")]
    assert "barLabel(desk)" in render and 'makeCode(label)' not in render, (
        "Watch's console line prints the bar's address again")
    assert "Watches Demo" in render
    assert "console-origin" in js, "watch.js never fills the console line"
    assert "Change it there." in js
    assert "Stop, then Start watching, to watch" in js, (
        "watch.js never says a running watch is still on the old desk")


def test_the_page_has_one_console_address_field_and_it_is_in_the_bar(client):
    """The decision, as markup. The only input on the page that takes a
    console address is the bundle bar's editor; Watch's boxes are gone, and
    so is the read-only readout that replaced them. An id renamed
    on one side and not the other is the silently-blank failure again."""
    page = client.get("/").text
    # Watch no longer repeats the address even read-only, and
    # its Source picker is gone -- Demo is chosen in the bar's editor.
    for gone in ('id="console-ip"', 'id="console-port"', 'id="console-ip-tag"',
                 'id="console-port-tag"', 'id="watch-console"', 'id="source-select"',
                 'id="console-fields"', "Demo fixtures"):
        assert gone not in page, f"the page still carries {gone}"
    for present in ('id="console-origin"',
                    'id="console-edit-address"', 'id="console-edit-port"',
                    'id="console-kind-desk"', 'id="console-kind-demo"',
                    'id="console-change-btn"', 'id="console-set-btn"'):
        assert present in page, f"the page has no {present}"
    address_inputs = re.findall(r'<input[^>]*id="([^"]*)"[^>]*placeholder="203\.0\.113', page)
    assert address_inputs == ["console-edit-address"], address_inputs


def test_styles_css_marks_an_address_set_here_and_draws_the_watch_readout(client):
    """A rule nobody serves is a signal nobody sees."""
    css = client.get("/static/styles.css").text
    assert ".console-source.is-set-here" in css
    assert ".watch-console" not in css and ".console-fields" not in css.replace(
        "old `.console-fields[hidden]`", ""), "styles.css still styles Watch's retired readout"
    assert ".seg-opt" in css and ".wc-file" in css
    assert ".console-origin" in css
    assert ".journal-stack-table tr.is-other-desk" in css
    assert "input.is-seeded" not in css and ".seed-tag" not in css, (
        "styles.css still styles the retired seeded-input markers")


# ======================================================================
# The shell (`/`; `/app`) -- mockup version H phase 1, an earlier change.
#
# One page, three modes, shared chrome: the bundle bar, the console
# readout with its Ping, and the findings dock. Two halves to test, and
# only one of them is Python:
#
#   * the endpoints the page calls, below;
#   * the SERVED ASSETS, further down. the rule about the static assets is
#     the reason those exist at all -- a key renamed on the Python side
#     and not in shell.js renders a silently blank element and breaks no
#     other test in this file.
# ======================================================================


IDENTITY = "WING,192.0.2.16,FOH,wing-compact,SN12345,3.1-0"


class _RecordingConsole:
    """A desk that answers `/?` and records every request it is given, so
    a test can assert on what was actually asked rather than on what the
    code claims it asks. Same shape as `tests/test_ping.py`'s, and for
    the same reason: the property worth defending is that a ping reads
    NOTHING else."""

    instances: list = []

    def __init__(self, ip, port=2223, timeout=1.0, raw_log=None):
        from atoo.console import OscReply  # noqa: F401  (documents the contract)

        self.ip, self.port, self.timeout = ip, port, timeout
        self.requests: list = []
        self.closed = False
        _RecordingConsole.instances.append(self)

    def identity(self):
        from atoo.console import OscReply

        self.requests.append("/?")
        return OscReply(address="/?", typetag="s", args=[IDENTITY])

    def close(self):
        self.closed = True


@pytest.fixture
def recording_console(monkeypatch):
    _RecordingConsole.instances = []
    import atoo.console as console_module

    monkeypatch.setattr(console_module, "WingConsole", _RecordingConsole)
    return _RecordingConsole


def _bundle_dir(tmp_path, *files):
    directory = tmp_path / "touringband"
    directory.mkdir()
    for name in files:
        (directory / name).write_text("{}")
    return directory


# ---- GET /api/bundle --------------------------------------------------


def test_api_bundle_with_nothing_open_is_a_documented_404(client):
    """Same shape as `GET /api/plan` and `GET /api/watch-conditions`, not
    an empty-object 200: "no bundle open" and "a bundle with nothing in
    it" are different states, and the bundle bar draws them differently."""
    r = client.get("/api/bundle")
    assert r.status_code == 404
    assert r.json() == {"error": "no show bundle open"}


def test_api_bundle_derives_every_slot_path_from_the_one_directory(tmp_path):
    """The whole reason version H replaced four path inputs with one
    folder: every filename inside a bundle is fixed, so the page is sent
    the derived paths rather than left to join strings itself."""
    from atoo import bundle as bundle_module

    directory = _bundle_dir(tmp_path, "input.csv", "plan.json")
    app = create_app(initial_bundle=str(directory))
    with fastapi_testclient.TestClient(app) as c:
        payload = c.get("/api/bundle").json()

    assert payload["name"] == "touringband"
    assert payload["directory"] == str(directory)
    # Every slot, in bundle.SLOTS order, whether or not anything is there.
    assert [s["slot"] for s in payload["slots"]] == list(bundle_module.SLOTS)
    by_slot = {s["slot"]: s for s in payload["slots"]}
    assert by_slot["input.csv"]["path"] == str(directory / "input.csv")
    assert by_slot["input.csv"]["present"] is True
    # watch.json is absent until a build drafts it -- not an error. And
    # apply-journal.json is no slot at all.
    assert by_slot["watch.json"]["present"] is False
    assert payload["present"] == ["input.csv", "plan.json"]
    assert "watch.json" in payload["missing"]
    assert "apply-journal.json" not in by_slot


def test_create_app_degrades_gracefully_on_a_bad_initial_bundle(tmp_path):
    """`cli.ui_cmd` has already validated `--show` and reported it, so
    anything left here is the file system changing underneath us. Same
    None-is-fine posture as `initial_watch_conditions_path`: the server
    still starts, and the browser can open a corrected folder."""
    app = create_app(initial_bundle=str(tmp_path / "gone"))
    with fastapi_testclient.TestClient(app) as c:
        assert c.get("/api/bundle").status_code == 404
        assert c.get("/").status_code == 200


# ---- POST /api/bundle/open --------------------------------------------


def test_bundle_open_replaces_the_open_bundle(client, tmp_path):
    directory = _bundle_dir(tmp_path, "input.csv")
    r = client.post("/api/bundle/open", json={"directory": str(directory)})
    assert r.status_code == 200
    assert r.json()["name"] == "touringband"
    assert r.json()["created"] is False
    assert client.get("/api/bundle").json()["directory"] == str(directory)


def test_bundle_open_with_a_missing_directory_is_a_clean_error(client, tmp_path):
    """A 400 with `bundle.BundleError`'s own already-user-facing message,
    not a raised exception and not a bare 500."""
    r = client.post("/api/bundle/open", json={"directory": str(tmp_path / "nope")})
    assert r.status_code == 400
    assert "no such directory" in r.json()["error"]


def test_bundle_open_with_a_file_is_a_clean_error(client, tmp_path):
    a_file = tmp_path / "plan.json"
    a_file.write_text("{}")
    r = client.post("/api/bundle/open", json={"directory": str(a_file)})
    assert r.status_code == 400
    assert "not a directory" in r.json()["error"]


def test_bundle_open_with_create_makes_the_directory(client, tmp_path):
    """H's `New show...` button. It makes a DIRECTORY and never a file --
    `atoo build --show new-show/` on a folder holding only input.csv
    is the first thing anyone does, which is why `bundle.load` accepts an
    empty directory in the first place."""
    target = tmp_path / "new-show"
    r = client.post("/api/bundle/open", json={"directory": str(target), "create": True})
    assert r.status_code == 200
    assert r.json()["created"] is True
    assert target.is_dir()
    assert r.json()["present"] == []


def test_bundle_open_with_create_on_an_existing_folder_says_it_adopted_one(client, tmp_path):
    """`created: false` is the difference between starting a new show and
    quietly reopening somebody else's. Silently reporting the second as
    the first is the outcome that boolean exists to prevent."""
    directory = _bundle_dir(tmp_path, "input.csv", "plan.json")
    r = client.post("/api/bundle/open", json={"directory": str(directory), "create": True})
    assert r.status_code == 200
    assert r.json()["created"] is False
    assert "plan.json" in r.json()["present"]


# ---- POST /api/ping ----------------------------------------------------


def test_ping_reports_what_the_desk_said(recording_console):
    """The model the desk states for itself is the evidence
    `apply` cross-checks a plan against, so the pill shows it -- seeing it
    before an apply beats discovering it during one."""
    app = create_app(initial_console={"address": "192.0.2.16",
                                      "address_source": "ATOO_CONSOLE",
                                      "port": 2223, "timeout": 1.0})
    with fastapi_testclient.TestClient(app) as c:
        r = c.post("/api/ping", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["address"] == "192.0.2.16"
    assert body["port"] == 2223
    assert body["model"] == "wing-compact"
    assert body["model_label"] == "WING Compact"
    assert body["identity"] == [IDENTITY]
    assert body["elapsed_ms"] is not None
    assert body["error"] is None
    # A value nobody typed has to say where it came from.
    assert body["address_source"] == "ATOO_CONSOLE"


def test_ping_reads_nothing_beyond_the_identity_reply(recording_console):
    """FR-X.16, and the whole reason this button is safe to press
    mid-show. Asserted by counting what the desk was asked, not by
    trusting a docstring -- exactly as `tests/test_ping.py` does for the
    CLI, because the browser button is the one someone presses mid-set."""
    app = create_app(initial_console={"address": "192.0.2.16", "port": 2223, "timeout": 1.0})
    with fastapi_testclient.TestClient(app) as c:
        c.post("/api/ping", json={})
    assert len(recording_console.instances) == 1
    console = recording_console.instances[0]
    assert console.requests == ["/?"]
    assert console.closed is True


def test_ping_lets_a_typed_console_win_and_claims_no_provenance_for_it(recording_console):
    """Typing over the seeded address wins for this one round trip. It
    also stops reporting the seed's origin: an address the operator typed
    did not come from ATOO_CONSOLE, and saying it did is the
    stale-export mistake an earlier change exists to prevent, inverted."""
    app = create_app(initial_console={"address": "192.0.2.16",
                                      "address_source": "ATOO_CONSOLE",
                                      "port": 2223, "timeout": 1.0})
    with fastapi_testclient.TestClient(app) as c:
        body = c.post("/api/ping", json={"console": "203.0.113.50"}).json()
    assert body["address"] == "203.0.113.50"
    assert body["address_source"] is None
    assert recording_console.instances[0].ip == "203.0.113.50"


def test_ping_with_no_console_anywhere_is_a_client_error(client):
    """Nothing typed, nothing resolved -- the page asked a question it had
    no address for, which is a 400. Distinct from a desk that does not
    answer, below."""
    r = client.post("/api/ping", json={})
    assert r.status_code == 400
    assert "no console address" in r.json()["error"]


def test_an_unreachable_desk_is_a_200_with_ok_false(client):
    """**Not** a 4xx or a 5xx. The endpoint did its job and the answer was
    no; rendering that the same way as a broken request would make an
    unreachable console look like a broken page."""
    # Port 1 on loopback: nothing listens, and the request times out fast.
    r = client.post("/api/ping",
                    json={"console": "127.0.0.1", "port": 1, "timeout": 0.2})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]
    assert body["model"] is None


# ---- The page and its assets ------------------------------------------
#
# From here down, every assertion is over what is actually SERVED.
# A rename that crosses into atoo/web/static/ is
# invisible to the test suite -- `esc()`-style rendering turns a missing
# field into an empty string, so the failure mode is a blank element that
# passes every Python test.


def test_shell_page_and_its_asset_are_served(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/shell.js").status_code == 200
    assert client.get("/static/shell.html").status_code == 200


def test_shell_page_is_not_cached(client):
    """Assembled per request (it splices its own startup JSON into the
    file on disk), so a cached copy would serve a stale bundle name or a
    stale console address -- the two values on it someone acts on."""
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/static/shell.js").headers["cache-control"] == "no-cache"


def test_shell_page_embeds_startup_state_before_its_own_script_tag(tmp_path):
    """Document order, not `</body>` proximity: a plain `<script src>`
    runs the moment the parser reaches it, so a blob spliced in after it
    is a blob `shell.js` never finds. That failure is silent and total --
    it cost the plan viewer every plan, 100% of the time, when
    `_embed_startup_json` was first written."""
    directory = _bundle_dir(tmp_path, "input.csv")
    app = create_app(initial_bundle=str(directory),
                     initial_console={"address": "192.0.2.16",
                                      "address_source": "ATOO_CONSOLE"})
    with fastapi_testclient.TestClient(app) as c:
        html = c.get("/").text

    blob = html.index('id="initial-shell"')
    script = html.index('<script src="/static/shell.js">')
    assert blob < script, "shell.js will run before its startup JSON exists"
    # Step 04 (setup.js) reads the same blob and codes against the
    # `window.Atoo` shell.js defines, so it must come after both.
    assert script < html.index('<script src="/static/setup.js">'), (
        "setup.js must load after shell.js -- it needs window.Atoo"
    )

    payload = json.loads(
        html[html.index(">", blob) + 1:html.index("</script>", blob)]
    )
    assert payload["bundle"]["name"] == "touringband"
    assert payload["console"]["address"] == "192.0.2.16"
    assert payload["findings"] == []


def test_shell_page_renders_with_nothing_open_at_all(client):
    """No `--show`, no console anywhere: still a page, with the bundle
    and console blanks reported as null rather than omitted."""
    html = client.get("/").text
    blob = html.index('id="initial-shell"')
    payload = json.loads(html[html.index(">", blob) + 1:html.index("</script>", blob)])
    assert payload["bundle"] is None
    assert payload["console"] == {}
    assert 'id="bundle-name"' in html


def test_shell_page_seeds_its_findings_dock(tmp_path):
    """Phase 1 never fills the dock -- nothing on the page runs a build,
    an apply or a verify yet. The seam is tested now because it is the
    contract phases 3 and 4 fill, and a dock nothing can put anything
    into cannot be checked at all."""
    from atoo.diagnostics import Diagnostic, Severity

    findings = [Diagnostic(severity=Severity.WARNING, code="strip.colour-not-writable",
                           message="no such colour", where="channel 7").to_dict()]
    app = create_app(initial_findings=findings)
    with fastapi_testclient.TestClient(app) as c:
        html = c.get("/").text
    assert "strip.colour-not-writable" in html


def test_shell_html_carries_every_element_shell_js_fills(client):
    """An id renamed on one side and not the other is the silently-blank
    failure again -- `getElementById` returns null and the feature just
    does not happen."""
    html = client.get("/static/shell.html").text
    for element_id in (
        "mode-build", "mode-apply", "mode-watch",
        "nav-build", "nav-apply", "nav-watch",
        "bundle-name",
        "bundle-change-btn", "bundle-new-btn",
        "bundle-message",
        "console-address", "console-source", "ping-btn", "ping-pill",
        "dock-col", "dock-tab", "dock-tab-count", "dock-title-count",
        "dock-active-list", "dock-active-empty",
        "dock-resolved", "dock-resolved-list", "dock-resolved-count",
    ):
        assert f'id="{element_id}"' in html, f"shell.html has no #{element_id}"


def test_bundle_bar_words(client):
    """The bundle's button reads Open..., an
    empty bundle reads "none", the bar shows no "set here" beside a
    console typed into it, and separators divide bundle, console and Ping."""
    html = client.get("/static/shell.html").text
    js = client.get("/static/shell.js").text
    assert 'id="bundle-change-btn">Open&hellip;</button>' in html
    assert 'id="bundle-name">none</code>' in html
    assert 'bundleName.textContent = "none";' in js
    assert "none open" not in html + js
    assert "address_source === CONSOLE_SET_HERE) {" in js
    assert html.count('class="bundle-bar-sep"') == 2



# ---- The shared pieces of docs/developer/ui-style.md ----------
# The Python suite cannot see the page, so these read the served assets.


def _css_rules(css):
    """(selector, body) for every plain rule in a stylesheet."""
    import re

    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def test_no_disabled_rule_dims_with_opacity(client):
    """ui-style.md §4: opacity is never the signal. A red button at 40%
    still reads as red, and in a dim room it reads as armed."""
    css = client.get("/static/styles.css").text
    dimming = [sel.strip() for sel, body in _css_rules(css)
               if ":disabled" in sel and "opacity" in body
               and "opacity: 1;" not in body]
    assert not dimming, dimming


def test_one_locked_look_for_every_button(client):
    import re

    css = client.get("/static/styles.css").text
    rule = re.search(r"\.btn:disabled, \.btn\.is-locked \{([^}]*)\}", css)
    assert rule, "no shared locked look"
    body = rule.group(1)
    for decl in ("background: transparent", "color: var(--text-off)",
                 "border: 1px dashed var(--border-strong)", "cursor: not-allowed"):
        assert decl in body, decl
    # Last in the file, so no screen's own button colour wins over it.
    assert css.rindex(".btn:disabled, .btn.is-locked") > css.rindex(".tile-stale .btn-secondary")
    # A locked segmented control wears the same look: dashed, no fill, no hue.
    seg = re.search(r"\.seg\.is-locked \{([^}]*)\}", css)
    assert seg and "border-style: dashed" in seg.group(1) and "background: transparent" in seg.group(1)
    assert "var(--text-off)" in re.search(r"\.seg\.is-locked \.seg-opt \{([^}]*)\}", css).group(1)


def test_the_shared_buttons_tags_and_focus_ring(client):
    import re

    css = client.get("/static/styles.css").text
    for selector in (".btn-quiet", ".btn-sm", ".btn[hidden]", ".state", ".state.is-ok",
                     ".state.is-err", ".prop", ".sev", ".sev.solid.sev-error", ".sev.big",
                     ".lock-reason"):
        assert re.search(re.escape(selector) + r"(?![\w-])", css), selector
    # Danger is the solid red with white ink, not the pink tint.
    assert re.search(r"\.btn-danger \{[^}]*background: var\(--alarm-solid\); color: var\(--alarm-ink\)", css)
    # Quiet: brass words, no box, 13/600 sentence case.
    quiet = re.search(r"\.btn-quiet \{([^}]*)\}", css).group(1)
    for decl in ("color: var(--accent)", "background: transparent", "font-size: 13px",
                 "font-weight: 600", "text-transform: none"):
        assert decl in quiet, decl
    # Every button has the brass focus ring.
    assert re.search(r"\.btn:focus-visible[^{]*\{\s*outline: 2px solid var\(--accent\); outline-offset: 2px;\s*\}", css)


def test_the_guide_tokens_and_no_orange(client):
    css = client.get("/static/styles.css").text
    for token in ("--accent-tint", "--ok-solid", "--ok-ink", "--border-strong", "--text-off"):
        assert css.count(token + ":") == 3, token  # dark, light by preference, light by choice
    for token in ("--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--radius", "--mono"):
        assert css.count(token + ":") == 1, token  # theme-free
    # Error has one red (§1): the orange --error-* is gone.
    assert "--error-fg" not in css.replace("`--error-*`", "")
    assert "var(--error" not in css


def test_the_bundle_bar_and_header_follow_the_guide(client):
    html = client.get("/static/shell.html").text
    bar = html[html.index('<div class="bundle-bar" id="bundle-bar">'):html.index('id="console-bar-edit"')]
    for element_id in ("bundle-change-btn", "bundle-new-btn", "console-change-btn", "demo-chip"):
        assert f'class="btn btn-quiet" id="{element_id}"' in bar, element_id
    assert 'id="theme-seg" role="radiogroup" aria-label="Theme"' in html
    assert "pipe-change-btn" not in bar and "state-readonly" not in bar
    # Label type, no colon.
    assert '<span class="bundle-bar-label">Show bundle</span>' in bar
    assert '<span class="bundle-bar-label">Console</span>' in bar
    # The Ping answer is a state tag, and a locked Ping says why.
    assert '<span class="state" id="ping-pill">Not pinged</span>' in bar
    assert 'class="lock-reason" id="ping-lock"' in bar and 'id="ping-detail"' in bar
    # The empty state: one sentence and one way out.
    notice = html[html.index('id="no-show-notice"'):html.index("</p>", html.index('id="no-show-notice"'))]
    assert "No show open." in notice and 'class="btn btn-secondary btn-sm" id="try-demo-btn"' in notice
    # Danger is never paired with primary.
    assert "btn-primary btn-danger" not in html and "btn-danger btn-primary" not in html


def test_the_ping_answer_is_a_state_and_ping_locks_with_a_reason(client):
    js = client.get("/static/shell.js").text
    assert 'pingPill.className = "state" + (state ? " " + state : "");' in js
    assert 'setPingPill("Answered", "is-ok", parts.join(" · "));' in js
    assert 'setPingPill("No reply", "is-err", data.error || "no reply");' in js
    assert 'className = "ping-pill' not in js and '"is-bad"' not in js
    assert "pingBtn.disabled = !!pingReason;" in js and "pingLock.hidden = !pingReason;" in js
    assert 'return "the Demo has no desk to ping";' in js
    assert 'setPingPill("nothing to ping"' not in js


def test_the_demo_lock_does_not_dim_a_locked_button(client):
    """Nora's review: the Demo rule's id selectors beat
    `.btn:disabled`, so a locked Write showed at 0.45 on top of the dashed
    look. Every listed control is inert; only the non-buttons are dimmed."""
    import re

    css = client.get("/static/styles.css").text
    dims = [sel for sel, body in _css_rules(css)
            if "body.is-demo-show" in sel and "opacity" in body and "opacity: 1;" not in body]
    assert dims and all(sel.strip().endswith(":not(.btn)") for sel in dims), dims
    assert re.search(r"#apply-run-btn[^{]*\) \{\s*pointer-events: none;\s*\}", css)


def test_a_long_ping_answer_wraps_inside_the_console_group(client):
    import re

    css = client.get("/static/styles.css").text
    wide = re.search(r"@media \(min-width: 720px\) \{(.*?)\n\}", css, re.S)
    assert wide and ".console-readout { flex: 100 1 0; min-width: 0; flex-wrap: nowrap; }" in wide.group(1)
    assert ".ping-detail { flex: 1 1 0; min-width: 12em;" in wide.group(1)

def test_shell_js_reads_every_key_webui_sends(client):
    """One assertion per key that crosses the wire. Python renaming a key
    shell.js still reads leaves an empty pill and breaks nothing else."""
    js = client.get("/static/shell.js").text

    # The startup blob's three sections.
    assert "initial-shell" in js
    for key in ("startup.bundle", "startup.console", "startup.findings"):
        assert key in js, f"shell.js never reads {key}"

    # `_bundle_payload`'s shape.
    # (Its `slots` were read only by the "Also in this bundle" strip,
    # removed 2026-09-25; the payload still carries them for scripts.)
    for key in ("bundle.name", "bundle.directory"):
        assert key in js, f"shell.js never reads {key}"

    # `cli.resolve_console_defaults`'s shape.
    for key in ("consoleDefaults.address", "consoleDefaults.address_source"):
        assert key in js, f"shell.js never reads {key}"

    # `console.PingResult.to_dict`'s shape, plus the endpoint's own
    # `address_source`. `data.ok` is the one that matters most: a desk
    # that did not answer comes back as a 200, so a page that only
    # checked `response.ok` would paint a failure green.
    for key in ("data.ok", "data.model_label", "data.address", "data.port",
                "data.elapsed_ms", "data.identity"):
        assert key in js, f"shell.js never reads {key}"

    # `Diagnostic.to_dict`'s shape, plus the UI-only `jumps` key.
    for key in ("finding.severity", "finding.code", "finding.message",
                "finding.where", "finding.source", "finding.fix",
                "finding.issue", "finding.jumps"):
        assert key in js, f"shell.js never reads {key}"
    # And the two halves an earlier change exists to keep apart are each rendered
    # ON the key, not merely mentioned near it -- `fix` is what the
    # engineer can change, `issue` means they cannot and it is ours. A
    # substring can only check the guard; the guard is the behaviour.
    assert "if (finding.fix)" in js, "shell.js reads `fix` but renders it unconditionally"
    assert "if (finding.issue != null)" in js, (
        "shell.js must render the limitation line only when `issue` is set -- "
        "issue 0 is a real issue number, so a truthiness test would drop it"
    )
    assert "dock-item-fix" in js and "dock-item-limitation" in js


def test_shell_js_severity_ladder_matches_pythons(client):
    """The dock orders by severity, so a ladder that drifted from
    Python's would sort findings into the wrong order -- or, for a value
    it does not know, to the bottom of a list it should head."""
    from atoo.diagnostics import Severity

    js = client.get("/static/shell.js").text
    html = client.get("/static/shell.html").text
    css = client.get("/static/styles.css").text
    for severity in (s.value for s in Severity):
        assert severity in js, f"shell.js never mentions the {severity!r} severity"
        assert f"sev-{severity}" in css, f"styles.css never styles sev-{severity}"
    for text in (js, html):
        assert "critical" not in text, (
            "the shell still carries the severity rung dropped on 2026-09-23 -- "
            "Python can never send one, so its section would never fill"
        )


def test_shell_js_offers_the_contract_later_phases_code_against(client):
    """`window.Atoo` is the seam phases 2-6 attach to. It is asserted
    here so a refactor cannot quietly rename half of it out from under a
    page this repository cannot otherwise see."""
    js = client.get("/static/shell.js").text
    assert "window.Atoo" in js
    # `member + ":"` and not just `member`: every one of these is also the
    # name of a local function in this file, so a bare substring would go
    # on passing after the exported key itself was renamed.
    for member in ("activateMode", "setFindings", "addFindings", "clearFindings",
                   "onBundleChange", "onModeChange", "currentMode", "bundle", "console",
                   "ping"):
        assert f"{member}:" in js, f"window.Atoo has no {member}"


def test_styles_css_carries_the_shell_chrome(client):
    """H's tile/badge/dock vocabulary, ported. A later phase lifting H's
    markup for a Build step lands on these class names; a rule nobody
    serves is a layout nobody gets."""
    import re

    css = client.get("/static/styles.css").text
    for selector in (".bundle-bar", ".bundle-bar-name",
                     ".console-readout", ".ping-detail",
                     ".mode-panel",
                     ".state-badge", ".state-loaded", ".state-missing",
                     ".dock-col", ".findings-dock", ".dock-item", ".dock-jump",
                     ".pipe-file-hint", ".prop"):
        # The class has to END there. A plain substring check would be
        # satisfied by `.findings-dockk`, which is a typo that serves no
        # rule at all -- and that is precisely the mistake worth catching.
        assert re.search(re.escape(selector) + r"(?![\w-])", css), (
            f"styles.css has no {selector} rule"
        )




# ======================================================================
# Build steps 01-03 (version H, phase 2): the three file tiles.
#
# `GET /api/build/sources` and `POST /api/build/sources/load`, the
# overrides/adds-to-house tags, and -- from `test_shell_html_carries_...`
# onward -- assertions over the SERVED assets, because the Python suite
# cannot otherwise see the browser.
# ======================================================================

HOUSE_CONVENTIONS = """# house-rules.md

## Inputs
Patch input sockets according to the supplied input list.

## Channels
Patch drums first, then bass, then vocals.

## Output
Main is the full mix.
"""

SHOW_INSTRUCTIONS = """## Channels
Keys L and Keys R are the one stereo pair on this run.

## Watch
MLD VOX is the lead vocal -- alert if it is muted.
"""

INPUT_CSV = """socket,name,category,type,model,phantom,notes
AES50-A 1,Kick,drums,Mic,,FALSE,
AES50-A 2,MLD VOX,vocals,Mic,,TRUE,lead
"""


def _build_bundle(tmp_path, *, input_csv=INPUT_CSV, instructions=SHOW_INSTRUCTIONS):
    directory = tmp_path / "touringband"
    directory.mkdir(parents=True)
    if input_csv is not None:
        (directory / "input.csv").write_text(input_csv)
    if instructions is not None:
        (directory / "instructions.md").write_text(instructions)
    return directory


def _house(tmp_path, text=HOUSE_CONVENTIONS):
    path = tmp_path / "house-rules.md"
    path.write_text(text)
    return path


@pytest.fixture
def build_client(tmp_path):
    """A shell with all three Build sources present and readable."""
    directory = _build_bundle(tmp_path)
    app = create_app(initial_bundle=str(directory), initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        yield c


# ---- GET /api/build/sources -------------------------------------------


def test_build_sources_reads_the_three_files_a_build_reads(build_client, tmp_path):
    """One payload, three tiles. Not three endpoints: the
    overrides/adds-to-house tags are a fact about two of the files at
    once, so a page that fetched them separately could draw a tag against
    a conventions file it had not read."""
    r = build_client.get("/api/build/sources")
    assert r.status_code == 200
    data = r.json()
    assert data["slots"] == ["conventions", "input_list", "instructions"]
    for slot in data["slots"]:
        assert data[slot]["state"] == "loaded", slot
        assert data[slot]["present"] is True
    assert data["conventions"]["path"] == str(tmp_path / "house-rules.md")
    assert data["input_list"]["path"] == str(tmp_path / "touringband" / "input.csv")
    assert data["instructions"]["path"] == str(tmp_path / "touringband" / "instructions.md")


def test_build_sources_is_never_a_404_because_the_tiles_are_always_drawn(client):
    """Deliberately unlike `GET /api/plan` and `GET /api/bundle`, and
    documented as such: "Missing" is one of version H's three tile states,
    not an absence of an answer. A 404 here would make an empty bundle
    look like a broken endpoint."""
    r = client.get("/api/build/sources")
    assert r.status_code == 200
    data = r.json()
    assert data["conventions"]["state"] == "notset"
    assert data["input_list"]["state"] == "notset"
    assert data["instructions"]["state"] == "notset"
    assert data["stack"] == []


def test_every_tile_path_is_derived_from_the_one_bundle_folder(build_client):
    """H draws `touringband/input.csv` on the tile -- folder plus fixed
    filename -- because that is the whole of what was chosen. The browser
    never joins those two strings itself."""
    data = build_client.get("/api/build/sources").json()
    assert data["input_list"]["display_path"] == "touringband/input.csv"
    assert data["instructions"]["display_path"] == "touringband/instructions.md"
    # The house file is NOT in the bundle (an earlier change point 5), so it is not
    # shown as though it were.
    assert not data["conventions"]["display_path"].startswith("touringband/")


def test_a_tile_carries_the_stamp_the_page_calls_stale_from(build_client):
    """`stale` is the one badge the server cannot answer -- it is a
    comparison between two reads. These two fields are what makes that
    comparison possible, so they are part of the wire shape, not a
    convenience."""
    data = build_client.get("/api/build/sources").json()
    for slot in ("conventions", "input_list", "instructions"):
        assert isinstance(data[slot]["mtime"], float), slot
        assert isinstance(data[slot]["size"], int), slot


# ---- the findings reading those files produces -------------------------


def _codes(data):
    return [f["code"] for f in data["findings"]]


def test_an_unparseable_input_list_is_a_finding_not_an_exception(tmp_path):
    """The split, and the reason this screen exists: the file is
    there, its content is wrong, and the operator has to be able to look
    at it. A 500 -- or a refusal -- would leave them with neither."""
    directory = _build_bundle(tmp_path, input_csv="name,category,type,phantom\nKick,drums,Mic,maybe\n")
    app = create_app(initial_bundle=str(directory), initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        r = c.get("/api/build/sources")
    assert r.status_code == 200
    data = r.json()
    assert data["input_list"]["state"] == "loaded"
    assert data["input_list"]["rows"] is None
    finding = [f for f in data["findings"] if f["code"] == "input-list.invalid"]
    assert len(finding) == 1
    # The loader's own message, passed through rather than reworded -- it
    # names the row and the column, which is the whole value of it.
    assert finding[0]["message"] == "row 2: column 'phantom' must be TRUE or FALSE, got 'maybe'"
    assert finding[0]["severity"] == "error"


def test_the_input_list_is_read_by_the_engines_own_loader(build_client, tmp_path):
    """Not a second CSV reader with its own opinion about what a valid
    input list is. The rows the page gets are `parse_input_list`'s rows."""
    from atoo.input_list import CANONICAL_COLUMNS, parse_input_list

    data = build_client.get("/api/build/sources").json()
    expected = parse_input_list((tmp_path / "touringband" / "input.csv").read_text())
    assert data["input_list"]["columns"] == list(CANONICAL_COLUMNS)
    assert data["input_list"]["rows"] == [
        {column: getattr(row, column) for column in CANONICAL_COLUMNS} for row in expected
    ]


def test_a_missing_instructions_file_is_a_quiet_line_on_its_tile_not_a_finding(tmp_path):
    """A bundle with no per-show text is normal. Until 2026-10-02 it was
    an INFO, `build.no-instructions`, in the dock of every new show; an earlier change made it a line on tile 03 ("the house conventions apply in full")
    and nothing in the dock."""
    directory = _build_bundle(tmp_path, instructions=None)
    app = create_app(initial_bundle=str(directory), initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        data = c.get("/api/build/sources").json()
    assert data["instructions"]["state"] == "missing"
    assert "build.no-instructions" not in _codes(data)
    assert data["instructions"]["findings"] == []
    assert "apply in full" in data["instructions"]["todo"]
    assert data["instructions"]["missing"] is None


def test_a_missing_input_list_is_a_to_do_until_build_is_pressed(tmp_path):
    """"A new show missing its input list is a to-do, not an
    error. The user hasn't had a chance to add one yet." The tile says so;
    the dock gets nothing; Build is refused with the ERROR, which the
    refusal carries for the dock."""
    directory = _build_bundle(tmp_path, input_csv=None)
    app = create_app(initial_bundle=str(directory), initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        data = c.get("/api/build/sources").json()
        assert data["input_list"]["state"] == "missing"
        assert "build.input-list-missing" not in _codes(data)
        assert "input list" in data["input_list"]["todo"]
        assert data["input_list"]["missing"]["code"] == "build.input-list-missing"

        refused = c.post("/api/build/run", json={"console_model": "wing-compact"})
    assert refused.status_code == 400
    body = refused.json()
    assert "no input list" in body["error"]
    assert [(f["severity"], f["code"]) for f in body["findings"]] == [
        ("error", "build.input-list-missing")]


def test_no_house_conventions_file_anywhere_is_refused_at_build_naming_the_config(tmp_path):
    """`build` refuses without one and says where to put it. On open the
    tile says what is missing; pressing Build gets the ERROR
    naming the config file."""
    from atoo.config import config_path

    directory = _build_bundle(tmp_path)
    app = create_app(initial_bundle=str(directory))
    with fastapi_testclient.TestClient(app) as c:
        data = c.get("/api/build/sources").json()
        assert "build.no-conventions" not in _codes(data)
        assert data["conventions"]["todo"]
        refused = c.post("/api/build/run", json={"console_model": "wing-compact"}).json()
    finding = [f for f in refused["findings"] if f["code"] == "build.no-conventions"][0]
    assert finding["severity"] == "error"
    assert str(config_path()) in finding["fix"]
    assert "[conventions]" in finding["fix"]


def test_a_conventions_path_that_is_not_there_is_a_to_do_not_a_crash(tmp_path):
    """The config file names a file that has since moved. `create_app`
    takes it anyway and the tile reports it (as a to-do, the
    ERROR waiting for Build), matching every other artifact's
    None-is-fine posture."""
    directory = _build_bundle(tmp_path)
    app = create_app(initial_bundle=str(directory),
                     initial_conventions=str(tmp_path / "gone.md"))
    with fastapi_testclient.TestClient(app) as c:
        assert c.get("/").status_code == 200
        data = c.get("/api/build/sources").json()
    assert data["conventions"]["state"] == "missing"
    assert "build.conventions-missing" not in _codes(data)
    assert "gone.md" in data["conventions"]["todo"]
    assert data["conventions"]["missing"]["code"] == "build.conventions-missing"


def test_a_file_that_is_there_but_wrong_is_still_a_finding(tmp_path):
    """An earlier change moved only the ABSENT files out of the dock. An input
    list that is there and does not load is somebody's mistake, and stays
    an ERROR in the dock from the moment it is read."""
    directory = _build_bundle(tmp_path)
    (directory / "input.csv").write_text("this is not,an input list\n1,2,3,4\n")
    app = create_app(initial_bundle=str(directory), initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        data = c.get("/api/build/sources").json()
    errors = [f for f in data["findings"] if f["severity"] == "error"]
    assert errors and all(f["source"] == "build" for f in errors)
    assert data["input_list"]["todo"] is None


def test_a_new_show_has_nothing_in_the_dock(tmp_path):
    """"when I created a new show that I got error
    and warning findings immediately in the sidebar ... It seems a little
    premature." A brand-new, empty bundle with a house file: no ERROR, no
    WARNING, and no missing-file finding of any severity."""
    house = _house(tmp_path)
    app = create_app(initial_conventions=str(house))
    with fastapi_testclient.TestClient(app) as c:
        made = c.post("/api/bundle/open", json={"directory": str(tmp_path / "newshow"),
                                                "create": True})
        assert made.status_code == 200
        data = c.get("/api/build/sources").json()
        page = c.get("/").text
    sevs = {f["severity"] for f in data["findings"]}
    assert not sevs & {"error", "warning"}, data["findings"]
    assert not {"build.input-list-missing", "build.no-instructions",
                "build.no-conventions"} & set(_codes(data))
    assert data["input_list"]["todo"] and data["instructions"]["todo"]
    assert 'id="todo-input-list"' in page and 'id="todo-instructions"' in page


@pytest.mark.parametrize("house", [
    "Just some prose about how I set up a desk.\n",
    "## Sources\nPatch as listed.\n\n## Channels\nDrums first.\n",
])
def test_headings_are_never_required_or_remarked_on(tmp_path, house):
    """The section headers "aren't really used". A
    conventions file is prose the model reads whole, so a file with no
    headings, or headings that are not the canonical eight, is shown and
    edited as written, with no finding about its headings -- the INFOs
    `conventions.no-sections` and `conventions.unknown-section` served
    the section cards and step 03's tags, and went with them."""
    directory = _build_bundle(tmp_path)
    path = _house(tmp_path, house)
    app = create_app(initial_bundle=str(directory), initial_conventions=str(path))
    with fastapi_testclient.TestClient(app) as c:
        data = c.get("/api/build/sources").json()
    assert data["conventions"]["state"] == "loaded"
    assert data["conventions"]["text"] == house
    assert not [code for code in _codes(data) if code.startswith("conventions.")]


def test_the_canonical_eight_are_the_eight_artifact_formats_documents():
    """The headings the example files (`conventions_example`) are laid out
    under are a document-format fact, and the document is the source of
    it. A heading added to §2 and not here would leave the example short
    of one."""
    import re

    from atoo.webui import CANONICAL_CONVENTION_SECTIONS

    doc = Path(__file__).parent.parent / "docs" / "developer" / "artifact-formats.md"
    if not doc.exists():
        pytest.skip("needs docs/developer/artifact-formats.md, which this tree does not have")
    text = doc.read_text()
    section = text.split("## 2. Conventions file (Markdown)")[1].split("\n## 3.")[0]
    example = section.split("```markdown")[1].split("```")[0]
    documented = tuple(re.findall(r"^## (.+)$", example, flags=re.MULTILINE))
    assert documented == CANONICAL_CONVENTION_SECTIONS


# ---- the two-layer conventions stack, and its tags ---------------------


def test_the_stack_is_the_shape_the_plan_records(build_client, tmp_path):
    """`meta.conventions_stack`, key for key and in the same order --
    worst precedence first -- so what the page shows and what a built
    plan records cannot disagree (`cli.build_cmd`)."""
    data = build_client.get("/api/build/sources").json()
    assert [layer["role"] for layer in data["stack"]] == ["conventions", "instructions"]
    assert data["stack"][0]["path"] == str(tmp_path / "house-rules.md")
    assert data["stack"][1]["path"] == str(tmp_path / "touringband" / "instructions.md")
    for layer in data["stack"]:
        assert {"path", "role", "source"} <= set(layer)


def test_the_whole_file_reaches_the_editor_as_written(build_client, tmp_path):
    """Steps 01 and 03 edit the file whole: the
    title line, the prose before the first heading, comments -- nothing is
    split off or left out of what the editor is given."""
    data = build_client.get("/api/build/sources").json()
    assert data["conventions"]["text"] == (tmp_path / "house-rules.md").read_text()
    assert data["conventions"]["text"].startswith("# house-rules.md")
    assert data["instructions"]["text"] == (
        tmp_path / "touringband" / "instructions.md").read_text()


# ---- POST /api/build/sources/load --------------------------------------


def test_load_points_one_tile_somewhere_else_and_leaves_the_others(build_client, tmp_path):
    other = tmp_path / "other-rules.md"
    other.write_text("## Busses\nMonitors first.\n")
    r = build_client.post("/api/build/sources/load",
                          json={"slot": "conventions", "path": str(other)})
    assert r.status_code == 200
    data = r.json()
    assert data["conventions"]["path"] == str(other)
    assert data["conventions"]["origin"] == "loaded here"
    assert data["input_list"]["display_path"] == "touringband/input.csv"
    # And it sticks, for this session: the next plain GET says the same.
    assert build_client.get("/api/build/sources").json()["conventions"]["path"] == str(other)


def test_load_with_a_path_that_is_not_there_is_a_400_and_changes_nothing(build_client, tmp_path):
    """Not a silent switch to a "Missing" tile: replacing a working file
    with nothing, for a typo, loses what the operator had."""
    before = build_client.get("/api/build/sources").json()["input_list"]["path"]
    r = build_client.post("/api/build/sources/load",
                          json={"slot": "input_list", "path": str(tmp_path / "nope.csv")})
    assert r.status_code == 400
    assert "nope.csv" in r.json()["error"]
    assert build_client.get("/api/build/sources").json()["input_list"]["path"] == before


def test_load_with_a_directory_says_so(build_client, tmp_path):
    r = build_client.post("/api/build/sources/load",
                          json={"slot": "input_list", "path": str(tmp_path)})
    assert r.status_code == 400
    assert "that is a directory" in r.json()["error"]


def test_load_with_an_unknown_slot_is_a_clean_400_naming_the_three(build_client, tmp_path):
    r = build_client.post("/api/build/sources/load",
                          json={"slot": "watchlist", "path": str(tmp_path / "house-rules.md")})
    assert r.status_code == 400
    error = r.json()["error"]
    assert "watchlist" in error
    for slot in ("conventions", "input_list", "instructions"):
        assert slot in error


def test_a_file_that_loads_but_will_not_parse_is_a_200_with_a_finding(build_client, tmp_path):
    """The other half of the split above: the path was right, the content
    is wrong, and refusing would leave the operator unable to look at what
    they just pointed at."""
    bad = tmp_path / "broken.csv"
    bad.write_text("name,category,type,phantom\nKick,drums,Mic,maybe\n")
    r = build_client.post("/api/build/sources/load",
                          json={"slot": "input_list", "path": str(bad)})
    assert r.status_code == 200
    assert "input-list.invalid" in _codes(r.json())


def test_opening_another_show_drops_every_typed_override_the_house_one_included(
    build_client, tmp_path,
):
    """A tile still pointing at the previous show's input.csv while the
    bundle bar names a new folder is the worst of both. The house file used
    to be kept -- it lives outside the bundle -- but since an earlier change a bundle's
    plan records the house file it was built from, and the maintainer chose
    (2026-09-24) that a typed one is dropped too: the new show opens on its
    recorded file, else the config's (here, the fixture's house-rules.md)."""
    other_house = tmp_path / "other-rules.md"
    other_house.write_text("## Busses\nMonitors first.\n")
    other_input = tmp_path / "loose.csv"
    other_input.write_text(INPUT_CSV)
    build_client.post("/api/build/sources/load",
                      json={"slot": "conventions", "path": str(other_house)})
    build_client.post("/api/build/sources/load",
                      json={"slot": "input_list", "path": str(other_input)})

    second = _build_bundle(tmp_path / "second", input_csv=INPUT_CSV, instructions=None)
    build_client.post("/api/bundle/open", json={"directory": str(second)})

    data = build_client.get("/api/build/sources").json()
    assert data["conventions"]["path"] != str(other_house)
    assert data["conventions"]["display_origin"] != "loaded here"
    assert data["input_list"]["path"] == str(second / "input.csv")


# ---- New file / New instructions.md (2026-09-25) -----------------------
#
# The maintainer: "there is no way to introduce either one outside of creating a
# file outside the UI and manually adding it to either the user preferences
# or an environment variable or the show bundle." These endpoints create
# an EMPTY file -- files only, never a console -- and never overwrite. The
# template is a suggestion only: the example text
# beside each editor, which nothing writes.


def _strip_to_rules(text: str) -> str:
    """What is left of an example once its title, headings and HTML
    comments are gone -- i.e. everything the model would read as a rule.
    Comments are stripped by the build's own rule
    (`conventions_text.strip_comments`), so this is exactly what a build
    would read."""
    from atoo.conventions_text import strip_comments

    return "\n".join(line for line in strip_comments(text).splitlines()
                     if not line.startswith("#")).strip()


@pytest.mark.parametrize("which", ["conventions", "instructions"])
def test_an_example_is_the_canonical_headings_in_order_and_not_one_rule(which):
    """The build reads everything outside an HTML comment, so an example
    line -- "Drums get a high-pass at 80Hz" -- inserted whole would be
    built into the next show. Headings, and comments saying what KIND of
    thing goes under each; once those are stripped, nothing may be left."""
    from atoo.webui import (CANONICAL_CONVENTION_SECTIONS, CONVENTION_SECTION_NOTES,
                                 conventions_example, instructions_example)

    text = (conventions_example("atoo-rules-house.md") if which == "conventions"
            else instructions_example("touringband"))
    headings = tuple(re.findall(r"^## (.+)$", text, flags=re.MULTILINE))
    assert headings == CANONICAL_CONVENTION_SECTIONS
    assert _strip_to_rules(text) == ""
    # One note per canonical section, and no note for a section that is not.
    assert tuple(CONVENTION_SECTION_NOTES) == CANONICAL_CONVENTION_SECTIONS
    # No number anywhere: a frequency, a level, a count is a rule's shape.
    assert not re.search(r"\d", text.split("\n", 1)[1]), "an example states a value"


def test_the_instructions_example_says_only_differences_belong():
    from atoo.webui import instructions_example

    text = instructions_example("touringband")
    assert "Only what differs" in text
    # No more tags keyed on headings (2026-09-28): the example must not
    # promise that a matching heading does anything.
    assert "overrides house" not in text and "SAME heading" not in text


@pytest.mark.parametrize("which", ["conventions", "instructions"])
def test_an_example_says_its_comments_are_not_read_and_headings_are_optional(which):
    """Since 2026-09-25 comments are stripped before any model sees the
    file (`conventions_text`), and they are where a note to yourself goes.
    And since 2026-09-28 nothing keys on a heading, so the example must
    not say the page needs them."""
    from atoo.webui import conventions_example, instructions_example

    text = (conventions_example("atoo-rules-house.md") if which == "conventions"
            else instructions_example("touringband"))
    flat = " ".join(text.split())
    assert "NOT read by the build" in flat
    assert "notes to yourself" in flat
    assert "these comments included" not in flat
    assert "with or without them" in flat
    assert "card" not in flat


@pytest.fixture
def home(tmp_path, monkeypatch):
    """`~` -- and so ~/.atoo.config -- pointed at a tmpdir. `Path.home`
    and $HOME both, because `config.expand_home` reads the first and
    anything calling `expanduser` reads the second."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake)
    monkeypatch.setenv("HOME", str(fake))
    return fake


def test_new_conventions_writes_an_empty_file_and_points_step_01_at_it(tmp_path, home):
    """The template is a suggestion only. New file
    writes nothing into the file; the example arrives beside the editor."""
    from atoo.webui import conventions_example

    directory = _build_bundle(tmp_path)
    app = create_app(initial_bundle=str(directory))
    with fastapi_testclient.TestClient(app) as c:
        r = c.post("/api/build/conventions/new",
                   json={"path": "~/atoo-rules-house.md"})
        assert r.status_code == 200
        data = r.json()
        again = c.get("/api/build/sources").json()

    target = home / "atoo-rules-house.md"
    assert target.read_bytes() == b""
    assert data["created"] == {"slot": "conventions", "path": str(target),
                               "display_path": "~/atoo-rules-house.md"}
    for payload in (data, again):
        assert payload["conventions"]["path"] == str(target)
        assert payload["conventions"]["state"] == "loaded"
        assert payload["conventions"]["text"] == ""
        assert payload["examples"]["conventions"] == conventions_example(
            "atoo-rules-house.md")
    assert "empty" in data["message"]
    # The build's own error about having no house file is gone.
    assert "build.no-conventions" not in _codes(data)
    # Not asked to touch the config, so it did not -- and said so.
    assert data["config_write"] is None
    assert not (home / ".atoo.config").exists()
    assert "was not changed" in data["message"]


def test_the_suggested_name_is_one_new_file_would_accept(build_client, home):
    def suggestion():
        return build_client.get("/api/build/sources").json()["config"][
            "new_conventions_suggestion"]

    assert suggestion() == "~/atoo-rules-house.md"
    (home / "atoo-rules-house.md").write_text("taken")
    assert suggestion() == "~/atoo-rules-house-2.md"


def test_new_conventions_never_overwrites(build_client, tmp_path, home):
    existing = home / "atoo-rules-house.md"
    existing.write_text("## Channels\nmine, not yours\n")
    r = build_client.post("/api/build/conventions/new", json={"path": str(existing)})
    assert r.status_code == 409
    assert "nothing was written" in r.json()["error"]
    assert existing.read_text() == "## Channels\nmine, not yours\n"
    # And step 01 still shows what it showed.
    assert build_client.get("/api/build/sources").json()["conventions"]["path"] \
        == str(tmp_path / "house-rules.md")


@pytest.mark.parametrize("path, status, words", [
    ("", 400, "give a path"),
    ("~/rules.txt", 400, "does not end in .md"),
    ("~/no-such-folder/rules.md", 400, "there is no folder"),
    ("~", 400, "does not end in .md"),
])
def test_new_conventions_refuses_a_bad_path_cleanly(build_client, home, path, status, words):
    r = build_client.post("/api/build/conventions/new", json={"path": path})
    assert r.status_code == status
    assert words in r.json()["error"]
    assert not (home / "no-such-folder").exists()


def test_new_conventions_can_make_itself_the_default_and_says_what_it_wrote(
        tmp_path, home):
    config = home / ".atoo.config"
    before = ('# mine\n[watch_conditions]\ndefault = "~/w.json"\n\n'
              '[console]\ndefault = "192.0.2.16"\n')
    config.write_text(before)
    app = create_app(initial_bundle=str(_build_bundle(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        r = c.post("/api/build/conventions/new",
                   json={"path": "~/atoo-rules-house.md", "make_default": True})
        data = r.json()
        # A second bundle with no plan falls back to the config default --
        # which, for this session, is now the new file.
        second = _build_bundle(tmp_path / "second")
        c.post("/api/bundle/open", json={"directory": str(second)})
        reopened = c.get("/api/build/sources").json()

    assert r.status_code == 200
    assert data["config_write"]["status"] == "added"
    assert config.read_text() == before + (
        '\n[conventions]\ndefault = "~/atoo-rules-house.md"\n')
    assert 'default = "~/atoo-rules-house.md"' in data["message"]
    assert data["config"]["conventions_default"] == "~/atoo-rules-house.md"
    assert reopened["conventions"]["path"] == str(home / "atoo-rules-house.md")


def test_new_conventions_never_replaces_a_different_default_silently(build_client, home):
    config = home / ".atoo.config"
    (home / "house.md").write_text("## Channels\nx\n")
    before = '[conventions]\ndefault = "~/house.md"\n'
    config.write_text(before)

    # The page is told what the config says BEFORE anyone ticks the box.
    assert build_client.get("/api/build/sources").json()["config"]["conventions_default"] \
        == "~/house.md"

    r = build_client.post("/api/build/conventions/new",
                          json={"path": "~/new-rules.md", "make_default": True})
    assert r.status_code == 200  # the file was made; the config was not changed
    written = r.json()["config_write"]
    assert written["status"] == "kept"
    assert written["previous"] == "~/house.md"
    assert "~/house.md" in r.json()["message"]
    assert config.read_text() == before
    assert (home / "new-rules.md").is_file()

    # Replacing it is its own request, and it has to say so.
    refused = build_client.post("/api/config/conventions-default",
                                json={"path": "~/new-rules.md"})
    assert refused.status_code == 409
    assert "~/house.md" in refused.json()["error"]
    assert config.read_text() == before

    replaced = build_client.post("/api/config/conventions-default",
                                 json={"path": "~/new-rules.md", "replace": True})
    assert replaced.status_code == 200
    assert replaced.json()["config_write"]["status"] == "replaced"
    assert config.read_text() == '[conventions]\ndefault = "~/new-rules.md"\n'


def test_a_config_it_cannot_edit_safely_is_reported_and_left_alone(build_client, home):
    config = home / ".atoo.config"
    config.write_text("[not valid toml\n")
    r = build_client.post("/api/build/conventions/new",
                          json={"path": "~/atoo-rules-house.md", "make_default": True})
    assert r.status_code == 200
    assert r.json()["config_write"]["status"] == "refused"
    assert "not valid TOML" in r.json()["message"]
    assert config.read_text() == "[not valid toml\n"


def test_setting_a_default_needs_a_file_that_is_there(build_client, home):
    r = build_client.post("/api/config/conventions-default", json={"path": "~/nope.md"})
    assert r.status_code == 400
    assert not (home / ".atoo.config").exists()


def test_new_instructions_needs_a_bundle(client):
    r = client.post("/api/build/instructions/new")
    assert r.status_code == 400
    assert "no show bundle open" in r.json()["error"]


def test_new_instructions_never_overwrites(build_client, tmp_path):
    existing = tmp_path / "touringband" / "instructions.md"
    r = build_client.post("/api/build/instructions/new",
                          json={"expected_bundle": str(tmp_path / "touringband")})
    assert r.status_code == 409
    assert "nothing was written" in r.json()["error"]
    assert existing.read_text() == SHOW_INSTRUCTIONS


def test_new_instructions_writes_an_empty_file_into_the_bundle(tmp_path):
    from atoo.webui import instructions_example

    directory = _build_bundle(tmp_path, instructions=None)
    elsewhere = tmp_path / "loose-instructions.md"
    elsewhere.write_text("## Busses\nfrom somewhere else\n")
    app = create_app(initial_bundle=str(directory), initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        before = c.get("/api/build/sources").json()
        assert before["instructions"]["todo"]
        # Step 03 pointed elsewhere by Change file: creating the bundle's
        # own file points it back, since that is the only one build reads.
        c.post("/api/build/sources/load", json={"slot": "instructions", "path": str(elsewhere)})
        r = c.post("/api/build/instructions/new", json={"expected_bundle": str(directory)})
    assert r.status_code == 200
    data = r.json()
    target = directory / "instructions.md"
    # Empty: the template is a suggestion beside the editor, never
    # written by New file.
    assert target.read_bytes() == b""
    assert data["instructions"]["path"] == str(target)
    assert data["instructions"]["state"] == "loaded"
    assert data["instructions"]["text"] == ""
    assert data["examples"]["instructions"] == instructions_example("touringband")
    assert data["instructions"]["todo"] is None
    assert data["stack"][-1]["role"] == "instructions"
    assert "empty" in data["message"]


def test_the_new_file_controls_are_in_the_served_page(client):
    """The Python suite cannot see the browser. An id renamed on one side
    and not the other is a button that silently does nothing."""
    html = client.get("/static/shell.html").text
    js = client.get("/static/shell.js").text
    # Step 01's New file opens the file browser rather than a
    # row of its own; the dialog's ids are asserted with the dialog's tests.
    for element_id in (
        "new-conventions",
        "conv-created", "conv-created-text", "conv-replace-default",
        "new-instructions", "instr-create-row", "instr-create-btn",
    ):
        assert f'id="{element_id}"' in html, f"shell.html has no #{element_id}"
        assert f'"{element_id}"' in js, f"shell.js never reaches #{element_id}"
    for endpoint in ("/api/build/conventions/new", "/api/config/conventions-default",
                     "/api/build/instructions/new"):
        assert endpoint in js, f"shell.js never calls {endpoint}"
    # The keys those endpoints answer with, each read by name.
    for key in ("data.message", "data.config_write", "data.created",
                "written.status", "written.previous",
                "info.conventions_default", "info.new_conventions_suggestion",
                "info.display_path", "info.exists", "make_default", "replace: true"):
        assert key in js, f"shell.js never reads {key}"
    # The checkbox starts unticked every time the dialog opens.
    assert "checked: false" in js
    # Step 03's New file writes into the bundle, so it names the bundle the
    # page shows (FR-6.11).
    assert "expected_bundle: bundle ? bundle.directory : null" in js


def test_shell_page_embeds_the_build_sources_at_first_paint(tmp_path):
    """Three files read on the server and spliced into the document, not
    three fetches the page makes after load -- the same reason the bundle
    name and console address ride in (see `_embed_startup_json`)."""
    directory = _build_bundle(tmp_path)
    app = create_app(initial_bundle=str(directory), initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        html = c.get("/").text
    blob = html.index('id="initial-shell"')
    assert blob < html.index('<script src="/static/shell.js">')
    payload = json.loads(html[html.index(">", blob) + 1:html.index("</script>", blob)])
    assert payload["build"]["input_list"]["display_path"] == "touringband/input.csv"
    assert [layer["role"] for layer in payload["build"]["stack"]] == [
        "conventions", "instructions",
    ]


def test_shell_html_carries_every_build_element_shell_js_fills(client):
    """The silently-blank failure again: an id renamed on one side and not
    the other means `getElementById` returns null and the tile just never
    fills in."""
    html = client.get("/static/shell.html").text
    for element_id in (
        "build-steps", "status-rows", "status-layers",
        "findings-conventions", "findings-input-list", "findings-instructions",
        "tab-conventions", "tab-input-list", "tab-instructions", "tab-plan",
        "panel-conventions", "panel-input-list", "panel-instructions", "panel-plan",
        "badge-conventions", "badge-input-list", "badge-instructions", "badge-plan",
        "hint-conventions", "hint-input-list", "hint-instructions", "hint-plan",
        "change-conventions", "change-input-list", "change-instructions",
        "stale-conventions", "stale-input-list", "stale-instructions",
        "reload-conventions", "reload-input-list", "reload-instructions",
        "conv-house-file", "conv-text", "conv-empty", "conv-example", "conv-example-text",
        "conv-example-insert",
        "input-table-wrap", "input-rows", "input-empty", "input-source",
        "conv-stack", "instr-text", "instr-empty", "instr-example", "instr-example-text",
        "instr-example-insert",
        "house-conv-source", "house-conv-toggle-btn", "input-source-toggle-btn",
        "next-to-input-list", "next-to-instructions", "next-to-plan",
    ):
        assert f'id="{element_id}"' in html, f"shell.html has no #{element_id}"


def test_shell_js_reads_every_build_key_webui_sends(client):
    """One assertion per key that crosses the wire for the Build tiles.
    Python renaming one shell.js still reads leaves a blank tile and
    breaks nothing else."""
    js = client.get("/static/shell.js").text

    assert "startup.build" in js, "shell.js never reads the embedded build state"
    assert '"/api/build/sources"' in js
    assert '"/api/build/sources/load"' in js

    # `_build_source_payload`'s shape.
    for key in ("source.state", "source.display_path", "source.path",
                "source.mtime", "source.size", "source.text",
                "source.rows", "source.columns", "source.findings"):
        assert key in js, f"shell.js never reads {key}"
    # Steps 01 and 03 are one editor each (2026-09-28); the server sends
    # no sections, and the page reads none.
    for gone in ("source.sections", "section.layer_tag", "section.segments"):
        assert gone not in js, f"shell.js still reads {gone}"
    # The example beside each editor, by the key the server sends it under.
    assert "build.examples" in js
    # The house file, cut into read and comment runs, for "View house file".
    assert "conventions.text_segments" in js

    # `_build_payload`'s own keys, and the stack's.
    assert "build.stack" in js
    for key in ("layer.path", "layer.source", "layer.display_path", "layer.display_source"):
        assert key in js, f"shell.js never reads {key}"


def test_the_setup_page_says_comments_are_not_read_by_the_build(client):
    """`<!-- ... -->` is shown as written: steps 01 and 03 are the file
    itself in a text editor, comments and all, and each says under it what
    a comment means. Step 03's "View house file" still marks each comment
    as a dimmed `.md-comment` span with the tooltip."""
    js = client.get("/static/shell.js").text
    assert 'const COMMENT_TITLE = "comment -- not read by the build";' in js
    assert 'span.className = "md-comment";' in js
    assert "span.title = COMMENT_TITLE;" in js
    assert "renderMarked(house, conventions && conventions.text_segments" in js

    css = client.get("/static/styles.css").text
    assert ".md-comment {" in css

    html = client.get("/").text
    assert html.count("text is a comment &mdash; not read by the build") == 2


def test_step_03_no_longer_tags_sections(client):
    """No sections view, so no overrides/adds-to-house tag per section
. The precedence is still said, in words, under
    the editor and in the stack above it."""
    js = client.get("/static/shell.js").text
    html = client.get("/").text
    css = client.get("/static/styles.css").text
    assert "layer_tag" not in js and "override-tag" not in js
    assert ".override-tag" not in css
    assert "where the two disagree, this file wins" in html


def test_shell_js_gives_every_build_finding_a_way_back_to_its_tile(client):
    """`jumps` is UI-only and added here rather than in Python, because a
    Diagnostic has no idea where on a screen its cause is shown. A jump
    onto a tile has to OPEN the step, not just flash the tab."""
    js = client.get("/static/shell.js").text
    assert "jumps: [{ label: STEP_LABEL[slot], mode: \"build\", target: \"#tab-\" + slotId(slot) }]" in js
    assert "if (target.dataset && target.dataset.step) activateStep(target.dataset.step);" in js


def test_shell_js_only_replaces_its_own_findings_in_the_shared_dock(client):
    """The dock is shared by all three modes. A Build re-read that called
    `setFindings` with its own list alone would wipe whatever Apply or
    Watch had put there."""
    js = client.get("/static/shell.js").text
    assert 'findings.filter((finding) => finding._producer !== "build")' in js


def test_the_bundle_bar_lists_no_files(client):
    """The "Also in this bundle" strip is gone ("We
    don't need this in the UI"). Each file is shown by the step that reads
    it; the bar names only the folder."""
    html = client.get("/").text
    js = client.get("/static/shell.js").text
    assert "Also in this bundle" not in html
    assert 'id="bundle-files' not in html
    assert "bundleFilesList" not in js


def test_the_theme_toggle_is_served_and_the_light_tokens_answer_it(client):
    """A toggle to see both the light and dark variants."""
    html = client.get("/").text
    js = client.get("/static/shell.js").text
    css = client.get("/static/styles.css").text
    assert 'id="theme-seg"' in html and 'localStorage.getItem("atoo.theme")' in html
    assert "THEME_NEXT" not in js and "wireSeg(el(\"theme-seg\")" in js
    assert ':root[data-theme="light"]' in css and ':root:not([data-theme="dark"])' in css


def test_styles_css_carries_the_build_tiles_and_the_editor(client):
    """H's Build vocabulary, ported. A rule nobody serves is a layout
    nobody gets."""
    import re

    css = client.get("/static/styles.css").text
    for selector in (".pipeline-wrap", ".pipeline-nav", ".pipe-stop", ".pipe-num",
                     ".pipe-label", ".pipe-stop-actions", ".pipe-arrow",
                     ".pipe-stop.has-error", ".pipeline-row", ".build-body",
                     ".step-panel", ".step-scroll", ".stage-head", ".stage-title",
                     ".stage-kind", ".conv-card", ".conv-heading",
                     ".conv-summary-text", ".conv-source-pre", ".source-editor",
                     ".source-example",
                     ".stack-list", ".stack-num", ".house-conv-strip", ".tile-stale",
                     ".step-footer", ".socket-chip", ".it"):
        assert re.search(re.escape(selector) + r"(?![\w-])", css), (
            f"styles.css has no {selector} rule"
        )


def _tile(html: str, tab_id: str) -> str:
    """The markup of one Build tile: from its `id` to the next tile's."""
    start = html.index(f'id="{tab_id}"')
    ends = [i for i in (html.find('class="pipe-arrow"', start),
                        html.find('class="help-pop pipeline-help"', start)) if i != -1]
    return html[start:min(ends)]


def test_build_tiles_put_the_path_above_the_buttons_and_carry_their_status(client):
    """An earlier change: the buttons moved below the path
    so they no longer shorten it, and each of the status line's readouts
    moved onto the tile it describes. The status line itself is gone."""
    html = client.get("/static/shell.html").text
    assert 'class="status-bar"' not in html
    for tab_id, slot in (("tab-conventions", "conventions"), ("tab-input-list", "input-list"),
                         ("tab-instructions", "instructions"), ("tab-plan", "plan")):
        tile = _tile(html, tab_id)
        # The path is the tile's own row, not inside the buttons' row, and
        # comes first.
        assert f'id="hint-{slot}"' in tile
        assert tile.index(f'id="hint-{slot}"') < tile.index('class="pipe-stop-actions"'), tab_id
        actions = tile[tile.index('class="pipe-stop-actions"'):]
        assert f'id="hint-{slot}"' not in actions, tab_id
    assert 'id="status-rows"' in _tile(html, "tab-input-list")
    assert 'id="status-layers"' in _tile(html, "tab-instructions")
    for slot in ("conventions", "input-list", "instructions"):
        assert f'id="findings-{slot}"' in _tile(html, f"tab-{slot}")
    plan = _tile(html, "tab-plan")
    for element_id in ("status-plan-badge", "status-plan-sep", "status-rebuild-btn",
                       "status-build-progress"):
        assert f'id="{element_id}"' in plan, element_id
    js = client.get("/static/shell.js").text
    assert 'el("findings-" + slotId(slot))' in js
    # A key on a button inside a tile is the button's, not the tab's.
    assert "if (ev.target !== tab) return;" in js


# Every block of instructions on Build that an earlier change moved out of the
# layout into pop-up help, by the popover's id and a phrase of its text.
BUILD_HELP = {
    "help-build-steps": "Steps 01&ndash;03 write a file only on Save",
    "help-conv-house": "Named once in <code>~/.atoo.config</code>",
    "help-conv-file": "The whole file reaches the model as one layer",
    "help-input-list": "One row per <strong>physical input</strong>",
    "help-conv-stack": "Both layers reach the model, labelled",
    "help-instr-file": "Only what is true of <em>this</em> show.",
    "help-run-build": 'Runs <code id="run-command">atoo build</code>',
}


def test_build_instructions_are_pop_up_help_and_keep_their_text(client):
    """"Remove instructions in red -- OK to make it pop up
    help" and "Move instructions in yellow box to pop up help". The text
    is kept, word for word, inside a popover a "?" opens -- never deleted,
    and no longer a paragraph in the layout."""
    import re

    html = client.get("/static/shell.html").text
    build = html[html.index('id="mode-build"'):html.index('id="mode-apply"')]
    for pop_id, phrase in BUILD_HELP.items():
        # The button: focusable (a real <button>), labelled, and pointing
        # at its popover; the popover starts closed and holds the text.
        button = re.search(
            r'<button type="button" class="help-btn" aria-label="Help: [^"]+"\s+'
            r'aria-expanded="false" aria-controls="' + pop_id + '">', build)
        assert button, f"no labelled help button for #{pop_id}"
        popover = re.search(r'class="help-popover[^"]*" id="' + pop_id +
                            r'" role="note" hidden>(.*?)</(?:span|div)>\s*</(?:span|div)>',
                            build, re.S)
        assert popover, f"#{pop_id} is not a closed .help-popover"
        assert phrase in popover.group(1), f"#{pop_id} lost its text: {phrase}"
    # None of them is still a paragraph in the layout.
    for phrase in BUILD_HELP.values():
        assert build.count(phrase) == 1, phrase
    # The plan table's how-to-read-it note, drawn by setup.js.
    setup = client.get("/static/setup.js").text
    assert 'aria-controls="help-plan-table"' in setup
    assert 'class="help-popover" id="help-plan-table"' in setup
    assert "Ch is the channel number, in the colour the plan sets." in setup
    assert '<p class="panel-note">Ch is the channel number' not in setup


def test_shell_js_opens_and_closes_the_pop_up_help(client):
    """The popover is the page's own: Escape closes it and gives focus
    back to its button, a click elsewhere closes it, and aria-expanded
    says which state it is in."""
    js = client.get("/static/shell.js").text
    for text in ('closest(".help-btn")', 'ev.key === "Escape" && openHelp', "closeHelp(true)",
                 'button.setAttribute("aria-expanded", "true")',
                 'button.setAttribute("aria-expanded", "false")',
                 'el(button.getAttribute("aria-controls"))', "button.focus()"):
        assert text in js, f"shell.js never has {text}"
    css = client.get("/static/styles.css").text
    for selector in (".help-pop", ".help-btn", ".help-popover", ".help-btn:focus-visible"):
        assert selector + " " in css or selector + "," in css or selector + "{" in css, selector


def test_findings_dock_top_meets_the_build_tiles(client):
    """"Move findings panel up to align with top of tiles".
    The tiles sit 8px into the shell body (2px + 6px of padding); the dock
    starts 8px down too, and its sticky offset no longer holds it lower."""
    import re

    css = client.get("/static/styles.css").text
    dock = re.search(r"\.dock-col \{(.*?)\}", css, re.S).group(1)
    assert "margin-top: 8px;" in dock
    assert "top: 8px;" in dock
    assert "top: calc(var(--sticky-h) + 12px)" not in dock
    assert re.search(r"\.pipeline-wrap \{[^}]*padding: 2px 0 0;", css)
    assert re.search(r"\.pipeline-nav \{[^}]*padding: 6px 0 8px;", css)


def test_hidden_means_hidden_on_the_shell(client):
    """`.tile-stale { display: flex }` beats the browser's own
    `[hidden] { display: none }`, which put a "this file changed on disk"
    banner on screen at first paint for a file that had not changed.
    Scoped to `body.shell` because this stylesheet is shared."""
    css = client.get("/static/styles.css").text
    assert "body.shell [hidden] { display: none !important; }" in css


def test_the_build_state_badges_are_all_four_states_h_draws(client):
    """Loaded / Missing / Stale, plus the not-set a tile with no path at
    all is in. A state with no badge is a tile that lies about a file."""
    js = client.get("/static/shell.js").text
    css = client.get("/static/styles.css").text
    for state, label in (("loaded", "Loaded"), ("missing", "Missing"),
                         ("notset", "Not set"), ("stale", "Stale")):
        assert f'{state}: {{ text: "{label}"' in js, f"shell.js has no {state} badge"
        assert f".state-{state}" in css, f"styles.css never styles state-{state}"


# ======================================================================
# Build step 04 (version H, phase 3): run the build.
#
# `POST /api/build/run` + `GET /api/build/status`, driven against the real
# `atoo build` with the model stubbed (conftest's `stub_build` -- no
# test here may reach a provider), and then the served assets, because
# the Python suite cannot see the browser.
# ======================================================================

INPUT_LIST = Path(__file__).parent / "fixtures" / "touringband.csv"

DRAFTED = [{"id": "mld-vox-muted", "description": "MLD VOX muted mid-set",
            "channel": "MLD VOX", "field": "muted", "operator": "==",
            "value": True, "severity": "error"}]

# **The one condition the operator wrote for himself**, and the whole
# subject of `test_a_drafted_watchlist_is_a_finding_that_opens_watch`: the
# build merges its drafts alongside it and never over the top of it.
OPERATORS_OWN_CONDITION = {
    "id": "Kick", "description": "Kick", "channel": "Kick",
    "field": "muted", "operator": "==", "value": True, "severity": "warning",
}


def _touringband_bundle(tmp_path):
    """A show bundle named `touringband`, carrying an input list and a
    watch.json with **exactly one hand-written condition in it**, and no
    plan.json yet -- so a plan that appears is the build's.

    Built here rather than copied out of `examples/touringband/`. It was
    copied, until the maintainer's rebuild of 2026-09-23 drafted nineteen
    conditions into that bundle's watch.json and the merge test below --
    which names the ids it expects -- failed on a change to his working
    file rather than to `atoo`. What these tests need is one
    condition that must survive a merge; that is now said here instead of
    being a property of a file in `examples/`.
    """
    directory = tmp_path / "touringband"
    directory.mkdir()
    (directory / "input.csv").write_text(INPUT_LIST.read_text())
    (directory / "watch.json").write_text(json.dumps(
        {"watch_conditions": [dict(OPERATORS_OWN_CONDITION)]}, indent=2) + "\n")
    return directory


def _wait_for_build(c, timeout=10.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        status = c.get("/api/build/status").json()
        if status["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("the build never finished")


@pytest.fixture
def run_client(tmp_path, stub_build, monkeypatch):
    stub_build("touringband")
    monkeypatch.setattr("atoo.generate.draft_watch_conditions",
                        lambda *a, **k: [dict(c) for c in DRAFTED])
    directory = _touringband_bundle(tmp_path)
    app = create_app(initial_bundle=str(directory), initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_build_status_is_idle_before_any_build(client):
    """Always a state, never a 404: the page draws "no build yet" from it."""
    status = client.get("/api/build/status").json()
    assert status["state"] == "idle"
    assert status["log"] == [] and status["findings"] == []


def test_a_build_runs_in_the_background_and_lands_the_plan_on_screen(run_client, tmp_path):
    """The whole of step 04's server half: the run answers at once, the
    status says running and then done, the plan the build wrote is the
    plan `GET /api/plan` now serves, and the findings it recorded come
    with it."""
    r = run_client.post("/api/build/run", json={"console_model": "wing-compact"})
    assert r.status_code == 200
    assert r.json()["state"] in ("running", "done")
    assert r.json()["command"][:3] == ["atoo", "build", "--show"]

    status = _wait_for_build(run_client)
    assert status["state"] == "done"
    # touringband's stubbed plan leaves its Matrix unpatched: a WARNING
    # (`output.no-patch`, 2026-10-09), so the build is applicable -- exit 0.
    assert status["exit_code"] == 0
    assert status["elapsed_s"] is not None
    assert any("plan written to" in line for line in status["log"]), status["log"]

    plan_path = tmp_path / "touringband" / "plan.json"
    assert plan_path.is_file()
    body = run_client.get("/api/plan").json()
    assert body["path"] == str(plan_path)
    assert body["plan"]["meta"]["console_model"] == "wing-compact"
    assert body["findings"], "the verify findings the build recorded must reach the page"
    assert {f["source"] for f in body["findings"]} == {"verify"}
    assert ("output.no-patch", "warning") in {(f["code"], f["severity"]) for f in body["findings"]}


def test_the_build_is_the_cli_command_not_a_copy_of_it(run_client, tmp_path):
    """What the browser builds and what a terminal builds cannot drift:
    the argv is `atoo build`'s own, with the conventions step 01
    shows and the model and critic the page chose."""
    run_client.post("/api/build/run", json={"console_model": "wing-rack", "critic": True})
    status = _wait_for_build(run_client)
    assert status["command"] == [
        "atoo", "build", "--show", str(tmp_path / "touringband"),
        "--conventions", str(tmp_path / "house-rules.md"),
        "--console-model", "wing-rack", "--critic",
    ]


def test_a_drafted_watchlist_is_a_finding_that_opens_watch(run_client, tmp_path):
    """OPTIONS-H point 3: Build has no watch step, so the build says it
    drafted conditions -- counted from the file, merged, never over the
    top of what was there."""
    run_client.post("/api/build/run", json={"console_model": "wing-compact"})
    status = _wait_for_build(run_client)
    drafted = [f for f in status["findings"] if f["code"] == "build.watchlist-drafted"]
    assert len(drafted) == 1, status["findings"]
    assert drafted[0]["severity"] == "info"
    assert drafted[0]["message"].startswith("1 condition(s) drafted into touringband/watch.json")
    assert '"source": "drafted"' in drafted[0]["message"]
    assert "never written over the top" in drafted[0]["message"]

    written = json.loads((tmp_path / "touringband" / "watch.json").read_text())
    ids = [c["id"] for c in written["watch_conditions"]]
    assert ids == ["Kick", "mld-vox-muted"], "the operator's own condition must survive"


def test_a_second_build_while_one_runs_is_refused(tmp_path, stub_build, monkeypatch):
    import threading

    import atoo.generate as generate_module

    stub_build("touringband")
    release = threading.Event()
    stubbed = generate_module.generate_plan

    def slow(*a, **k):
        release.wait(5)
        return stubbed(*a, **k)

    monkeypatch.setattr("atoo.generate.generate_plan", slow)
    monkeypatch.setattr("atoo.generate.draft_watch_conditions", lambda *a, **k: [])
    app = create_app(initial_bundle=str(_touringband_bundle(tmp_path)),
                     initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        assert c.post("/api/build/run", json={"console_model": "wing-compact"}).status_code == 200
        assert c.get("/api/build/status").json()["state"] == "running"
        second = c.post("/api/build/run", json={"console_model": "wing-compact"})
        assert second.status_code == 409
        assert second.json() == {"error": "a build is already running"}
        release.set()
        assert _wait_for_build(c)["state"] == "done"


def test_a_build_with_no_model_to_talk_to_fails_as_a_finding_not_a_crash(tmp_path, monkeypatch):
    """No provider stub: the real `provider_from_env`, pointed at a
    backend that refuses at once. The run ends `failed`, the page is
    told why in the build's own words, and nothing is a 500."""
    monkeypatch.setenv("ATOO_AI_PROVIDER", "claude")
    monkeypatch.delenv("ATOO_AI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(initial_bundle=str(_touringband_bundle(tmp_path)),
                     initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        assert c.post("/api/build/run", json={"console_model": "wing-compact"}).status_code == 200
        status = _wait_for_build(c)
        assert status["state"] == "failed"
        assert status["exit_code"] == 1
        finding = status["findings"][0]
        assert finding["code"] == "build.failed"
        assert finding["severity"] == "error"
        assert "generation failed" in finding["message"]
        assert "ATOO_AI_PROVIDER" in finding["fix"]
        assert c.get("/api/plan").status_code == 404, "a failed build lands no plan"
    assert not (tmp_path / "touringband" / "plan.json").exists()


def test_a_build_refuses_a_console_model_it_was_not_given(build_client):
    """An unstated model is a hard stop, and not a judgement
    call -- a Full's 8 local inputs and a Compact's 24 are a patch that
    lands or one that cannot."""
    r = build_client.post("/api/build/run", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "no console model chosen -- one of: wing-compact, wing-full, wing-rack"
    r = build_client.post("/api/build/run", json={"console_model": "x32"})
    assert r.status_code == 400
    assert "unknown console model 'x32'" in r.json()["error"]
    assert build_client.get("/api/build/status").json()["state"] == "idle"


def test_a_build_needs_a_bundle_and_a_house_file(client, tmp_path):
    r = client.post("/api/build/run", json={"console_model": "wing-compact"})
    assert r.status_code == 400
    assert "no show bundle open" in r.json()["error"]

    app = create_app(initial_bundle=str(_build_bundle(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        r = c.post("/api/build/run", json={"console_model": "wing-compact"})
    assert r.status_code == 400
    assert "no house conventions file" in r.json()["error"]


def test_a_build_refuses_instructions_the_build_would_not_read(build_client, tmp_path):
    """`build` reads instructions.md from the bundle and nowhere else. A
    step 03 pointed elsewhere would build from one text while showing
    another, and `meta.conventions_stack` would record the unseen one."""
    other = tmp_path / "elsewhere.md"
    other.write_text("## Channels\nsomething else\n")
    build_client.post("/api/build/sources/load",
                      json={"slot": "instructions", "path": str(other)})
    r = build_client.post("/api/build/run", json={"console_model": "wing-compact"})
    assert r.status_code == 400
    assert "reads instructions only from the bundle's own instructions.md" in r.json()["error"]


def test_opening_another_bundle_swaps_the_plan_for_its_own(tmp_path):
    """Step 04 showing the last show's plan under this show's name is
    worse than showing none."""
    first = tmp_path / "a"
    first.mkdir()
    second = tmp_path / "b"
    second.mkdir()
    (second / "plan.json").write_text(FIXTURE_PLAN_PATH.read_text())
    plan = json.loads(FIXTURE_PLAN_PATH.read_text())
    app = create_app(initial_plan=plan, initial_plan_path="somewhere.json", initial_bundle=str(first))
    with fastapi_testclient.TestClient(app) as c:
        assert c.get("/api/plan").status_code == 200
        c.post("/api/bundle/open", json={"directory": str(tmp_path / "c"), "create": True})
        assert c.get("/api/plan").status_code == 404
        c.post("/api/bundle/open", json={"directory": str(second)})
        assert c.get("/api/plan").json()["path"] == str(second / "plan.json")


def test_build_output_from_other_threads_stays_out_of_the_build_log():
    """The build's stdout is routed by thread, not swapped process-wide:
    a watch loop printing while a build runs must not land in its log."""
    import io
    import threading

    from atoo.webui import _ThreadRoutedStream

    captured, elsewhere = [], io.StringIO()
    stream = _ThreadRoutedStream(elsewhere, threading.get_ident(), captured.append)
    stream.write("mine\n")
    other = threading.Thread(target=lambda: stream.write("theirs\n"))
    other.start()
    other.join()
    assert captured == ["mine\n"]
    assert elsewhere.getvalue() == "theirs\n"
    assert stream.isatty() is False


def test_a_routed_stream_resolves_to_the_owners_log_from_any_thread():
    """A model call's progress ticker writes from a thread of its own; it
    resolves the stream in the build's thread first (`for_current_thread`)
    so its lines still land in the build's log."""
    import io
    import threading

    from atoo.webui import _ThreadRoutedStream

    captured, elsewhere = [], io.StringIO()
    stream = _ThreadRoutedStream(elsewhere, threading.get_ident(), captured.append)
    resolved = stream.for_current_thread()
    other = threading.Thread(target=lambda: resolved.write("from the ticker\n"))
    other.start()
    other.join()
    assert captured == ["from the ticker\n"]
    assert resolved.isatty() is False

    seen = []
    t = threading.Thread(target=lambda: seen.append(stream.for_current_thread()))
    t.start()
    t.join()
    assert seen == [elsewhere], "another thread resolves to its own stream, not the build's"


# ---- step 04's live progress ------------------------


def _streaming_plan_provider(refused=False, **kw):
    """A FakeProvider that plays a valid plan back as a stream, through the
    same ModelCallProgress a real provider uses. The plan is frozen in
    tests/fixtures, never read from examples/.

    `refused=True` patches its Matrix into a local output the Compact
    does not have, so verify refuses the plan (its unpatched Matrix is
    only a WARNING since 2026-10-09) and the build runs a fix-up round."""
    import copy

    from conftest import REAL_PLANS
    from atoo.ai_provider import FakeProvider

    plan = copy.deepcopy(REAL_PLANS["touringband"])
    if refused:
        no_such = {"group": "LCL", "sockets": [99]}
        plan["outputs"]["Matrix"]["socket"] = dict(no_such)
        plan["outputs"]["Matrix"]["sockets"] = [dict(no_such)]
    plan.pop("meta", None)
    plan.setdefault("unassigned_inputs", [])
    plan.setdefault("notes", [])
    return FakeProvider(response=json.dumps(plan), model="slow-fake", **kw)


@pytest.fixture
def progress_client(tmp_path, monkeypatch):
    import atoo.progress as progress_module

    monkeypatch.setattr(progress_module, "MODEL_TICK", 0.02)
    holder = {}

    def provider():
        return holder["provider"]

    monkeypatch.setattr("atoo.cli.provider_from_env", provider)
    app = create_app(initial_bundle=str(_touringband_bundle(tmp_path)),
                     initial_conventions=str(_house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        c.holder = holder
        yield c


def test_build_status_carries_no_progress_before_any_model_call(client):
    assert client.get("/api/build/status").json()["progress"] is None


def test_a_running_build_reports_its_model_call_live(progress_client):
    """The structured channel: which call (generator, then watchlist), its
    stage, its clock and its tokens, while it runs -- not scraped from the
    log."""
    import time

    progress_client.holder["provider"] = _streaming_plan_provider(
        refused=True, stream_chunks=20, thinking_chars=2000, chunk_delay=0.03)
    assert progress_client.post("/api/build/run",
                                json={"console_model": "wing-compact"}).status_code == 200
    stages, phases, snapshots = set(), set(), []
    deadline = time.time() + 20
    while time.time() < deadline:
        status = progress_client.get("/api/build/status").json()
        p = status["progress"]
        if p is not None and status["state"] == "running":
            stages.add(p["stage"])
            phases.add(p["phase"])
            snapshots.append(p)
        if status["state"] != "running":
            break
        time.sleep(0.01)
    assert status["state"] == "done", status["log"]
    assert {"thinking", "writing"} <= stages, stages
    assert "generator" in phases
    live = [s for s in snapshots if s["stage"] in ("thinking", "writing")]
    assert live and all(s["estimated"] for s in live)
    assert any(s["thinking_tokens"] for s in live)
    assert any(s["output_tokens"] for s in live)
    assert all(s["model"] == "slow-fake" and s["started_at"] for s in live)
    assert all(s["elapsed_s"] is not None for s in live)

    final = status["progress"]
    # This plan is refused by verify (its Matrix is patched to a socket
    # the desk does not have), so the build spends its one fix-up round
    # -- a call, and a chip, of its own -- before the watchlist.
    assert [c["label"] for c in final["calls"]] == ["generator", "fixup", "watchlist"]
    assert all(c["stage"] == "done" for c in final["calls"])
    assert final["stage"] == "done"


def test_the_builds_progress_lines_reach_its_log_sparsely(progress_client):
    """On a pipe -- and the page's log is one -- a stage change is a line
    and the clock is a line every 10s at first; never one per token."""
    progress_client.holder["provider"] = _streaming_plan_provider(
        stream_chunks=200, thinking_chars=4000, chunk_delay=0.002)
    progress_client.post("/api/build/run", json={"console_model": "wing-compact"})
    status = _wait_for_build(progress_client, timeout=30)
    log = status["log"]
    generator = [line for line in log if "slow-fake (generator)" in line]
    assert generator[0].startswith("slow-fake (generator): sending, waiting for the first reply")
    assert "stderr is not a terminal" in generator[0]
    assert any("(generator): thinking --" in line for line in generator), log
    # Four hundred deltas; a handful of lines.
    assert len(generator) <= 6, generator


def test_a_new_build_starts_with_no_progress_from_the_last(progress_client):
    import threading
    import time

    import atoo.generate as generate_module

    progress_client.holder["provider"] = _streaming_plan_provider(stream_chunks=2)
    progress_client.post("/api/build/run", json={"console_model": "wing-compact"})
    assert _wait_for_build(progress_client)["progress"]["calls"]

    release = threading.Event()
    real = generate_module.generate_plan

    def slow(*a, **k):
        release.wait(5)
        return real(*a, **k)

    generate_module.generate_plan = slow
    try:
        progress_client.post("/api/build/run", json={"console_model": "wing-compact"})
        time.sleep(0.05)
        running = progress_client.get("/api/build/status").json()
        assert running["state"] == "running"
        assert running["progress"] is None, "the last build's calls must not show on this one"
    finally:
        release.set()
        generate_module.generate_plan = real
    _wait_for_build(progress_client)


def test_the_shell_embeds_step_04s_first_paint(tmp_path):
    """The plan, the last run and the model choices ride in the startup
    blob, so a reload mid-build lands on "running", not a blank step."""
    directory = tmp_path / "touringband"
    directory.mkdir()
    plan = json.loads(FIXTURE_PLAN_PATH.read_text())
    app = create_app(initial_bundle=str(directory), initial_plan=plan,
                     initial_plan_path=str(FIXTURE_PLAN_PATH))
    with fastapi_testclient.TestClient(app) as c:
        html = c.get("/").text
    blob = html.index('id="initial-shell"')
    payload = json.loads(html[html.index(">", blob) + 1:html.index("</script>", blob)])
    assert payload["plan"]["path"] == str(FIXTURE_PLAN_PATH)
    assert payload["plan"]["plan"]["channels"][0]["name"] == "Kick"
    assert "findings" in payload["plan"]
    assert payload["run"]["state"] == "idle"
    assert [m["id"] for m in payload["console_models"]] == ["wing-compact", "wing-full", "wing-rack"]


# ---- step 04 in the served assets --------------------------------------


def test_shell_html_carries_step_04(client):
    html = client.get("/").text
    for element_id in ("run-console-model", "run-critic", "run-build-btn", "run-command",
                       "run-model-note", "run-message", "run-panel", "run-state",
                       "run-elapsed", "run-exit", "run-last-command", "run-log",
                       "plan-empty", "plan-view", "plan-source", "plan-render",
                       "plan-path", "plan-load-btn", "back-to-instructions"):
        assert f'id="{element_id}"' in html, f"shell.html has no #{element_id}"
    assert "Next phase" not in html, "step 04 is built -- its tile must stop saying otherwise"
    assert "the plan viewer" not in html


def test_setup_js_reads_every_step_04_key_webui_sends(client):
    """One assertion per key that crosses the wire for step 04. A Python
    rename setup.js still reads is a silently blank element."""
    js = client.get("/static/setup.js").text
    assert '"/api/build/run"' in js and '"/api/build/status"' in js
    assert '"/api/plan"' in js and '"/api/plan/load"' in js
    for key in ("startup.plan", "startup.run", "startup.console_models",
                "model.id", "model.label",
                "run.state", "run.log", "run.elapsed_s", "run.started_at",
                "run.exit_code", "run.command", "run.findings",
                "current.plan", "current.path", "current.findings",
                "meta.console_model"):
        assert key in js, f"setup.js never reads {key}"
    for state in ('running: ["Running"', 'done: ["Done"', 'failed: ["Failed"'):
        assert state in js, f"setup.js does not draw the {state.split(':')[0]} state"
    assert "console_model: modelSelect.value, critic: critic.checked" in js


def test_the_page_draws_the_live_build_readout_from_status_progress(client):
    """Step 04's readout, and the status line's, read `progress` from
    `GET /api/build/status` -- one assertion per key setup.js reads. A
    Python rename is otherwise a silently blank element."""
    html = client.get("/").text
    for element_id in ("run-progress", "run-progress-bar", "run-progress-phase",
                       "run-progress-stage", "run-progress-elapsed", "run-progress-tokens",
                       "run-progress-note", "run-progress-calls", "status-build-progress"):
        assert f'id="{element_id}"' in html, f"shell.html has no #{element_id}"
    js = client.get("/static/setup.js").text
    assert "const p = run.progress || null;" in js
    for key in ("p.phase", "p.model", "p.stage", "p.started_at", "p.elapsed_s",
                "p.thinking_tokens", "p.output_tokens", "p.input_tokens",
                "p.total_output_tokens", "p.streams", "p.calls",
                "call.label", "call.stage", "call.elapsed_s", "call.total_output_tokens"):
        assert key in js, f"setup.js never reads {key}"
    for label in ('generator: "Generating the plan"', 'critic: "Critic review"',
                  'watchlist: "Drafting watch conditions"'):
        assert label in js
    # The clock ticks from `started_at` between polls, not from the last tick.
    assert "Date.now() / 1000 - p.started_at" in js
    assert "renderProgress();" in js
    css = client.get("/static/styles.css").text
    assert "@keyframes run-progress-sweep" in css
    assert ".run-progress-bar.is-stopped" in css


def test_setup_js_flows_findings_into_the_shared_dock_with_jumps(client):
    """Through `window.Atoo`, replacing only its own producers'
    findings; every one with a way back to what caused it; the drafted
    watchlist's opening Watch."""
    js = client.get("/static/setup.js").text
    assert "SP.addFindings(list)" in js
    assert 'SP.findings().filter((f) => f._producer !== producer)' in js
    assert 'replaceFindings("plan", list.map(withJumps))' in js
    assert 'finding.code === "build.watchlist-drafted"' in js
    assert '{ label: "Review on Watch", mode: "watch", target: "#wc-panel" }' in js
    # Verify's structured `where`, and the critic's free text.
    assert "/^(channels|busses|outputs)\\[([^\\]]+)\\]/" in js
    assert 'target: instructions ? "#instr-text" : "#conv-text"' in js
    # The cards the jumps land on open step 04 on the way.
    assert 'data-step="plan"' in js


def test_setup_js_jumps_a_conventions_finding_to_the_line_it_quotes(client):
    """FR-6.2, since 2026-09-28's single editor: a conventions-audit finding
    jumps to the step whose file it quotes -- `where` names the layer
    ("instructions § Busses" is step 03's) -- and carries the quote
    conventions_audit.py verified (`line`) for the editor to select. No
    heading is guessed from a finding's code any more; there are no
    section cards to land on. `meta.verify_findings.info` and
    `meta.build_findings` are the keys the meta block reads."""
    js = client.get("/static/setup.js").text
    assert 'if (!(/^conventions\\./.test(code) || code === "critic.conventions")) return null;' in js
    assert "if (!finding.line) return null;" in js
    assert '/^instructions/.test(finding.where || "")' in js
    assert "find: finding.line," in js
    for gone in ("sectionFor", "sectionSlug", "conv-sec-", "instr-sec-", "heading = \"Inputs\""):
        assert gone not in js, f"setup.js still has {gone}"
    # They reach the page only through the dock: the
    # plan payload's `findings` (webui._plan_findings reads
    # `meta.verify_findings.info` and `meta.build_findings`).
    assert "publishPlanFindings(current.findings || [])" in js


def test_shell_js_selects_the_quoted_line_when_a_finding_jumps_to_an_editor(client):
    """The dock's jump rides along as the event's `detail`, and each
    step's editor reads `detail.find` and selects that text."""
    js = client.get("/static/shell.js").text
    assert 'new CustomEvent("atoo:jump", { bubbles: true, detail: jump })' in js
    assert 'box.addEventListener("atoo:jump", (ev) => {' in js
    assert "if (ev.detail && ev.detail.find) selectQuote(slot, ev.detail.find);" in js
    assert "box.setSelectionRange(range[0], range[1]);" in js


def test_shell_js_edits_steps_01_and_03_as_one_text_and_saves_it_whole(client):
    """No sections view. Each step's one textarea is
    the file; its Save sends it whole as `text` -- the key the server
    reads -- and Save/Discard appear only once it differs from the file."""
    js = client.get("/static/shell.js").text
    assert 'text: "conv-text", empty: "conv-empty"' in js
    assert 'text: "instr-text", empty: "instr-empty"' in js
    assert "text: box.value," in js
    assert "const dirty = !!box && box.value !== box.dataset.original;" in js
    assert 'box.addEventListener("input", () => noteTextChange(slot));' in js
    for gone in ("startSourceEditing", "sectionEdits", "renderSections", "conv-source-toggle-btn",
                 "instr-source-toggle-btn", "conv-add-section", "instr-add-section"):
        assert gone not in js, f"shell.js still has {gone}"


def test_the_example_is_a_suggestion_the_page_inserts_only_when_asked(client):
    """"provide the templated new conventions and
    instructions files as suggestions only". The example is shown beside
    the editor, read-only; Insert puts it (or the part selected) at the
    cursor as an unsaved change, and only Save writes it."""
    js = client.get("/static/shell.js").text
    html = client.get("/").text
    assert "exampleText.textContent = text;" in js
    assert "const text = exampleSelection(slot) || pre.textContent || \"\";" in js
    assert 'box.setRangeText(text, start, end, "end");' in js
    assert 'insert.addEventListener("click", () => insertExample(slot));' in js
    # Nothing in the page sends the example to the server: no request
    # body the page builds names it.
    assert "build.examples && build.examples[slot]" in js
    bodies = re.findall(r"JSON\.stringify\(\{.*?\}\)", js, flags=re.DOTALL)
    assert bodies and not [b for b in bodies if "example" in b.lower()]
    # The empty editor's hint is a placeholder -- never part of the file.
    assert "box.placeholder = ids.placeholder;" in js
    assert "never written unless you insert it and Save" in html


# --------------------------------------------------------------------------
# the Watch page says what the read could not check
# --------------------------------------------------------------------------


def test_the_watch_event_payload_carries_the_coverage_caveat():
    """R002 and R005 now stand down on a read with no output patch
    in it, so a shorter list of findings is no longer necessarily a
    healthier desk. The one thing that can tell the two apart has to
    reach the browser."""
    from atoo.audit import ConsoleState, coverage_caveat, run_audit
    from atoo.watch import WatchEvent
    from atoo.webui import _WatchPresenter

    blind = ConsoleState({"/bus/1/name": "Drums", "/ch/1/send/1/on": 1})
    caveat = coverage_caveat(blind)
    assert caveat and "R002" in caveat

    payload = _WatchPresenter().payload(
        WatchEvent(0, "now", run_audit(blind), [], []), caveat)
    assert payload["coverage_caveat"] == caveat

    seeing = ConsoleState({"/io/in/LCL/1/vph": 0, "/io/out/LCL/1/grp": "OFF",
                           "/io/out/LCL/1/in": 0})
    assert coverage_caveat(seeing) is None
    assert _WatchPresenter().payload(WatchEvent(0, "now", [], [], []))["coverage_caveat"] is None


def test_the_watch_page_renders_the_coverage_caveat(client):
    """A rename or a reshape on the Python side is invisible to this
    suite: `esc()`-style rendering
    turns a missing field into a silently blank element rather than an
    error. So the served asset is asserted on directly -- crude, and the
    only thing standing between a payload change and a Watch page that
    quietly stops saying "I could not check this"."""
    js = client.get("/static/watch.js").text
    assert "coverage_caveat" in js, (
        "watch.js must read the coverage caveat off the watch event payload "
        "-- without it the page shows a shorter finding list "
        "with no note that rules went unanswered."
    )
    assert "coverage-note" in js
    html = client.get("/static/shell.html").text
    assert 'id="coverage-note"' in html


# ---- The stale-page guard -----------
# A tab A19 opened kept showing A19's state against the server A20 started
# on the same port over a different bundle copy. The server refuses a stale
# write (tests/test_webui_stale_page.py); these assert the page's half,
# which the Python suite otherwise cannot see.


def test_shell_js_watches_the_server_instance_and_bundle(client):
    js = client.get("/static/shell.js").text
    # It knows which process drew it, and asks the one it is talking to.
    assert "startup.instance" in js
    assert 'fetch("/api/status"' in js
    assert "status.instance !== pageInstance" in js
    # And the bundle, with this tab's own "Open bundle" not mistaken for
    # another tab's.
    assert "status.bundle" in js and "bundleOpening" in js and "bundleEpoch" in js
    # When: on a timer, on coming back into view, and on demand.
    assert "visibilitychange" in js and "setInterval" in js
    for name in ("isStale:", "checkServer:", "markStale:", "onStale:"):
        assert name in js, name


def test_the_stale_page_banner_is_on_the_page_and_starts_hidden(client):
    html = client.get("/static/shell.html").text
    for element in ('id="stale-banner"', 'id="stale-banner-detail"', 'id="stale-reload-btn"'):
        assert element in html, element
    banner = html[html.index('id="stale-banner"') - 40:html.index('id="stale-banner"') + 80]
    assert "hidden" in banner and 'role="alert"' in banner
    css = client.get("/static/styles.css").text
    assert ".stale-banner" in css and "body.is-stale-page" in css


def test_every_write_the_page_sends_says_what_the_page_reviewed(client):
    """apply.js is the only file that sends a console write. Each of the
    three carries the bundle it shows, and the thing it reviewed -- the
    fields `webui` refuses a confirmed write without."""
    js = client.get("/static/apply.js").text
    assert js.count("expected_bundle: bundleShown()") == 3
    assert "expected_plan_sha256: (preflight && preflight.plan_sha256)" in js
    assert "run.review.review_id" in js and "expected_review_id" in js
    assert "expected_undo_id: AV.topId()" in js
    # It asks whether the page is current before sending, and redraws what
    # a 409 says it was wrong about.
    assert "await SP.checkServer()" in js
    for what in ('"bundle"', '"plan"', '"review"', '"undo"'):
        assert f"data.stale === {what}" in js, what
    assert "topId: topId" in client.get("/static/amend.js").text


def test_a_build_and_a_reconnecting_watch_socket_ask_too(client):
    assert "await SP.checkServer()" in client.get("/static/setup.js").text
    assert "SP.checkServer()" in client.get("/static/watch.js").text


def test_setup_page_reads_both_shapes_of_an_unassigned_input(client):
    """`plan.unassigned_inputs` holds bare names in a plan built before
    2026-09-29 and `{input, quote, from}` objects since (every row is
    built unless a quote says to leave it out). A page reading only one
    shape shows the other as "[object Object]" or blank, and the Python
    suite cannot see that -- so the served JS is asserted on."""
    js = client.get("/static/setup.js").text
    assert "function unassignedName(entry)" in js
    assert 'typeof entry === "object" ? (entry.input || "") : (entry || "")' in js
    assert "plan.unassigned_inputs.map(unassignedLine)" in js


def test_setup_page_joins_a_stereo_pairs_second_row_by_name(client):
    """A pair whose rows state no socket is joined to its second input-list
    row by `source.pair_input` (2026-09-29) -- there is no stated socket to
    join it by. The Python suite cannot see the page read the field."""
    js = client.get("/static/setup.js").text
    assert "ch.source.pair_input" in js


# ---- FR-X.15c: grouped findings on the page -----------------------------

def _grouping_plan() -> dict:
    """Three channels whose preset lost the same high-pass, and one critic
    note -- stated here, never read out of `examples/`."""
    overridden = [
        {"severity": "info", "code": "preset.overridden", "where": f"channels[{n}]",
         "source": "build",
         "message": f"ch {n} ('C{n}'): the plan's own processing wins at 1 address(es) "
                    f"the preset 'P' also sets -- flt/lcf preset 20.0 -> plan {40 + n}.0"}
        for n in (1, 2, 3)]
    return {"channels": [{"channel": n, "name": f"C{n}"} for n in (1, 2, 3)],
            "meta": {"build_findings": overridden,
                     "verify_findings": {"errors": [], "warnings": [], "info": []},
                     "critic_findings": [{"severity": "warning", "code": "critic.intent",
                                          "where": "C1", "message": "check it"}]}}


def test_the_dock_gets_one_item_per_distinct_message():
    """The plan's `meta` keeps one finding per channel; the dock reads one
    item for the three, with each member kept for its row's jump link."""
    from atoo.webui import _plan_findings

    plan = _grouping_plan()
    found = _plan_findings(plan)
    grouped = [f for f in found if f["code"] == "preset.overridden"]
    assert len(grouped) == 1
    assert grouped[0]["where"] == "ch 1-3 (3 channels)"
    assert "plan 41.0..43.0" in grouped[0]["message"]
    assert [m["where"] for m in grouped[0]["members"]] == ["channels[1]", "channels[2]",
                                                           "channels[3]"]
    assert len(plan["meta"]["build_findings"]) == 3, "the data is not touched"


def test_the_plan_payload_lists_findings_only_for_the_dock():
    """Step 04 no longer draws its own lists, so the payload
    no longer carries a second, grouped copy of `meta`'s findings
    (`meta_grouped`) for it. The dock's `findings` hold every one of the
    plan's findings -- verify, critic and build -- once."""
    from atoo.webui import _plan_payload

    payload = _plan_payload(_grouping_plan(), None)
    assert "meta_grouped" not in payload
    items = [m for f in payload["findings"] for m in (f.get("members") or [f])]
    assert sorted(f["code"] for f in items) == ["critic.intent"] + ["preset.overridden"] * 3
    assert len(payload["plan"]["meta"]["build_findings"]) == 3


def test_the_apply_view_groups_its_warnings_and_the_journal_keeps_each():
    from atoo.webui import _apply_payload

    warnings = [f"ch {n} ('C{n}'): patch socket was not stated in the input list and was "
                "assigned during generation -- verify before trusting this write"
                for n in range(1, 5)]
    journal = {"dry_run": False, "writes": [], "warnings": list(warnings)}
    payload = _apply_payload(journal, None, None)
    assert payload["warnings"] == [
        "ch 1-4 (4 channels): patch socket was not stated in the input list and was "
        "assigned during generation -- verify before trusting this write"]
    assert journal["warnings"] == warnings


def test_setup_js_jumps_a_grouped_finding_to_each_members_row(client):
    """The Python suite cannot see the page,
    so the served asset is asserted on. A grouped dock item (`members`)
    takes a jump link per member, which is also what counts it on each
    row's Findings badge. The Plan panel draws no list of its own."""
    js = client.get("/static/setup.js").text
    assert "if (Array.isArray(finding.members) && finding.members.length) {" in js
    assert "withJumps(m).jumps.forEach((j) => {" in js
    # A grouped item belongs to every row one of its members is about.
    assert "Object.assign(ids, findingRowIds(m));" in js
    # `channels[10]` is channel number 10 first, list index second.
    assert "String(c.channel) === name" in js


def test_starting_a_build_blanks_the_plan_it_replaces():
    """The build moves plan.json aside as it starts;
    step 04 stops showing it at the same moment."""
    from fastapi.testclient import TestClient
    from atoo.webui import create_app
    js = TestClient(create_app()).get("/static/setup.js").text
    start = js[js.index("async function startBuild()"):]
    start = start[:start.index("\n  }\n")]
    assert start.index("clearFindingsForBuild();") < start.index("current = null;") \
        < start.index("renderCurrentPlan();")


def test_atoo_demo_seed_makes_the_demo_repeatable(monkeypatch):
    """`ATOO_DEMO_SEED` fixes the Demo's faults run after run, so the
    doc screenshot harness can retake Watch running and get the same
    picture (Docs Lead, 2026-10-10)."""
    def run():
        provider, _ = demo_provider_factory()
        events = list(watch(provider, interval=0, max_iterations=40, sleep=lambda s: None))
        return [sorted(f.code + str(f.where) for f in e.all_findings) for e in events]

    monkeypatch.setenv("ATOO_DEMO_SEED", "7")
    first, second = run(), run()
    assert first == second and any(first)


def test_step_04_reads_the_bus_preset_fields_the_plan_carries(client):
    """The bus row's detail draws `preset` and
    `preset_values.inserts` (model, engine, point, saved_on). A rename on
    the Python side would leave it silently blank, so the
    served asset is checked for the field names it reads."""
    js = client.get("/static/setup.js").text
    for field in ("b.preset_values", "b.preset", "ins.engine", "ins.model",
                  "ins.point", "ins.saved_on", "v.file"):
        assert field in js, field


def test_watch_verdict_and_table_headings_stay_at_the_top(client):
    """The verdict bar and the alert table's column headings are sticky, and
    the box that holds them clips rather than scrolls (a scroll container
    would stop them sticking to the window); watch.js feeds the headings'
    offset from the verdict bar's own height."""
    import re

    css = client.get("/static/styles.css").text
    box = re.search(r"\.watch-table-wrap\.panel\.box \{([^}]*)\}", css).group(1)
    assert "overflow: clip" in box and "overflow: hidden" not in box
    bar = re.search(r"\.watch-table-wrap \.verdict-bar \{([^}]*)\}", css).group(1)
    assert "position: sticky" in bar and "top: 0" in bar
    heads = re.search(r"#alert-table thead th \{([^}]*)\}", css).group(1)
    assert "position: sticky" in heads and "var(--verdict-h" in heads
    js = client.get("/static/watch.js").text
    assert '"--verdict-h"' in js and "ResizeObserver" in js


def test_the_drafted_tag_is_blue_not_yellow(client):
    """Drafted is a call to look, not a fault: the info blue, so it cannot
    be read as the yellow WARNING severity beside it in the conditions table."""
    import re

    css = client.get("/static/styles.css").text
    rule = re.search(r"\.state\.is-info \{([^}]*)\}", css).group(1)
    assert "var(--info-bg)" in rule and "var(--info-fg)" in rule
    js = client.get("/static/watch.js").text
    assert 'tag.className = "state is-info wc-source-drafted"' in js
    assert "state is-warn wc-source-drafted" not in js
    assert 'class="state is-info" id="wc-drafted-badge"' in client.get("/").text
