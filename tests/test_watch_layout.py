"""The Watch page's layout, look B of `mockups/watch-layout/`
(removed 2026-10-27, in git at `86ac89c5`).

Choosing it: *"B, with no thin colored border (keep
the thicker colored bars), and the flash option off by default."*

* **The table first.** A one-row header (interval, Start/Stop, the flash
  toggle, counts, "Updated", the pill) sits right above the alert table.
  "This watch" and "Watch conditions" are `<details>` below the table,
  folded while a watch runs.
* **The rows carry the state.** Each row is tinted, with a thick bar in
  its severity's colour; the header and the table frame never take a
  severity colour.
* **"Where" comes from the server.** Each row's `strip` is the strip it
  is about, as the desk names it (`webui.finding_strip`), so the page
  never parses it out of the detail text.
* **Flash on new** is off by default, remembered per device, fires only
  for a NEW warning or error (never an info), and turns into a steady
  edge glow under reduced motion.

The browser half is asserted on the served assets, which is all the
Python suite can see; every state here is built in the test.
"""

from __future__ import annotations

import re

import pytest

from conftest import require_fastapi_testclient

from atoo.audit import DEFAULT_RULES, ConsoleState, Severity
from atoo.diagnostics import Diagnostic
from atoo.watch import watch
from atoo.webui import _WatchPresenter, finding_strip


def _finding(*addresses):
    return Diagnostic.audit("X", Severity.WARNING, "routing", "A Rule", "detail", addresses)


STATE = ConsoleState({"/ch/6/name": "Bass DI", "/bus/1/name": "Drums", "/mtx/1/name": ""})


# ---- "Where": the server names the strip ----------------------------------


@pytest.mark.parametrize("addresses, expected", [
    (("/ch/6/in/conn/in",), 'CH 6 "Bass DI"'),
    (("/ch/6",), 'CH 6 "Bass DI"'),
    (("/bus/1/name",), 'BUS 1 "Drums"'),
    (("/mtx/1",), "MTX 1"),
    (("/ch/3/name", "/ch/4/name"), "CH 3, CH 4"),
    (("/io/in/LCL/9/vph",), "LCL 9"),
    (("/io/out/A/12/grp",), "A 12"),
    # A stage box's link (C008, C009): the port.
    (("/$stat/B/stat",), "AES50-B"),
    (("/cfg/something",), None),
    ((), None),
])
def test_finding_strip_names_the_strip_as_the_desk_does(addresses, expected):
    assert finding_strip(_finding(*addresses), STATE) == expected


def test_finding_strip_without_a_reading_falls_back_to_the_position():
    assert finding_strip(_finding("/ch/6/fdr"), None) == "CH 6"


def test_every_row_in_the_frame_carries_its_strip():
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/mute": 0, "/ch/1/fdr": -144.0, "/ch/1/main/1/on": 1,
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        "/main/1/name": "PA", "/main/1/mute": 0,
    })
    presenter = _WatchPresenter()
    [event] = list(watch(iter([state]).__next__, rules=list(DEFAULT_RULES),
                         sleep=lambda _: None, max_iterations=1))
    frame = presenter.payload(event, None, state)
    assert frame["all_findings"], "the state should raise at least one finding"
    for row in frame["all_findings"]:
        assert "strip" in row, row["rule_id"]
    fader = [r for r in frame["all_findings"] if "/ch/1/fdr" in r["addresses"]]
    assert fader and fader[0]["strip"] == 'CH 1 "Kick"'


# ---- the served page -------------------------------------------------------


@pytest.fixture(scope="module")
def assets():
    fastapi_testclient = require_fastapi_testclient()
    from atoo.webui import create_app
    with fastapi_testclient.TestClient(create_app()) as client:
        yield {
            "html": client.get("/").text,
            "js": client.get("/static/watch.js").text,
            "css": client.get("/static/styles.css").text,
            "shell": client.get("/static/shell.js").text,
        }


def _watch_panel(html):
    return html[html.index('id="mode-watch"'):html.index("The findings dock")]


def test_the_table_comes_right_after_a_one_row_header_and_the_folds_follow(assets):
    panel = _watch_panel(assets["html"])
    order = [panel.index(marker) for marker in (
        'id="panel"', 'id="conn-pill"', 'id="start-btn"', 'id="watch-flash-on"',
        'id="watch-verdict"', 'class="summary verdict-counts"', 'id="alert-table"',
        'id="watch-about"', 'id="wc-panel"')]
    assert order == sorted(order)
    # Nothing between the header and the table but the verdict and its lines.
    between = panel[panel.index('id="panel"'):panel.index('id="alert-table"')]
    assert 'id="wc-table"' not in between and 'id="console-origin"' not in between
    assert '<details id="watch-about"' in panel and '<details id="wc-panel"' in panel


def test_the_folds_close_on_start_and_open_on_stop_only_when_running_changes(assets):
    js = assets["js"]
    body = js[js.index("function setRunningUI(running)"):]
    body = body[:body.index("\n  }\n")]
    assert "running !== lastRunning" in body
    assert "wcPanel.open = !running" in body and "watchAbout.open = !running" in body


def test_review_on_watch_opens_a_folded_target(assets):
    """The findings dock's "Review on Watch" jumps to #wc-panel, which is
    folded while a watch runs: the jump opens a <details> target."""
    shell = assets["shell"]
    jump = shell[shell.index("function jumpTo(jump)"):]
    assert 'target.tagName === "DETAILS"' in jump[:jump.index("scrollIntoView")]
    assert "target.open = true" in jump[:jump.index("scrollIntoView")]


def test_the_rows_carry_the_state_and_nothing_else_takes_its_colour(assets):
    css, js = assets["css"], assets["js"]
    assert 'tr.className = "sev-row-" + f.severity' in js
    for sev in ("error", "warning"):
        rule = re.search(r"#alert-table tr\.sev-row-" + sev + r" \{([^}]*)\}", css)
        assert rule and "--sev-bar" in rule.group(1) and "background" in rule.group(1), sev
    assert "inset 8px 0 0 var(--sev-bar" in css
    # The maintainer: "no thin colored border" -- the header and the table frame
    # never take the worst severity's colour.
    for worst in ("error", "warning"):
        for sel in (".watch-head", ".watch-table-wrap"):
            assert not re.search(r'data-watch-worst="' + worst + r'"\][^{]*' + re.escape(sel), css)
    # Only one look: the mockup's switch is gone.
    assert "watchLook" not in js and "?look" not in js and "data-watch-look" not in css


def test_a_stale_watch_greys_the_table(assets):
    assert 'body[data-watch-worst="stale"] .watch-table-scroll' in assets["css"]
    assert 'worst = "stale"' in assets["js"]


def test_where_is_the_servers_strip_not_parsed_from_the_detail(assets):
    js = assets["js"]
    assert "f.strip" in js
    assert "WHERE_RE" not in js and "WHERE_ANY_RE" not in js


def test_flash_on_new_is_off_by_default_remembered_and_never_for_info(assets):
    html, js, css = assets["html"], assets["js"], assets["css"]
    panel = _watch_panel(html)
    toggle = panel[panel.index('id="watch-flash-on"') - 40:]
    toggle = toggle[:toggle.index("</button>")]
    assert "<button" in toggle and 'role="switch"' in toggle and 'aria-checked="false"' in toggle
    assert 'aria-pressed' not in toggle and "Off" in toggle
    assert "let flashOn = false;" in js
    assert 'localStorage.getItem("atoo.watchFlash") === "1"' in js
    assert 'localStorage.setItem("atoo.watchFlash"' in js
    # Only a new finding flashes, and only a warning or an error.
    handle = js[js.index("function handleEvent(payload)"):]
    handle = handle[:handle.index("\n  }\n")]
    assert "payload.new_findings" in handle
    assert 'flashScreen("error")' in handle and 'flashScreen("warning")' in handle
    assert 'flashScreen("info")' not in js
    assert "if (!flashOn) return;" in js
    # One short flash; a steady glow under reduced motion.
    assert re.search(r"\.watch-flash\.is-flashing \{ animation: watch-flash \.42s ease-out 1; \}", css)
    reduced = css[css.index("/* Flash on new (off by default)"):]
    reduced = reduced[reduced.index("@media (prefers-reduced-motion: reduce)"):]
    assert ".watch-flash.is-flashing { animation: none;" in reduced
    assert "box-shadow: inset 0 0 0 10px var(--alarm-solid)" in reduced


def _media_block(css, query, after):
    """The body of the first `@media (<query>)` block that follows the
    `after` marker in the stylesheet."""
    start = css.index("@media (" + query + ") {", css.index(after))
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        depth += {"{": 1, "}": -1}.get(css[j], 0)
        if depth == 0:
            return css[i + 1:j]
    raise AssertionError("unclosed @media block")


def test_the_alert_table_fits_its_frame_at_phone_width(assets):
    """At 390px the five columns measured ~474px in a 364px frame. The
    table scrolls sideways inside its box (ui-style.md §7), narrow
    screens let the fixed widths go, and phone width drops Rule (Since
    already goes in the generic table rule)."""
    css = assets["css"]
    assert ".watch-table-scroll { overflow-x: auto; }" in css
    assert "padding: 0; overflow: clip;" in _rule(css, ".watch-table-wrap.panel.box")
    narrow = _media_block(css, "max-width: 760px", "/* The folds: each summary IS the block header")
    assert "#alert-table :is(.col-sev, .col-rule, .col-since) { width: auto; }" in narrow
    phone = _media_block(css, "max-width: 640px", "/* The folds: each summary IS the block header")
    assert "#alert-table .col-rule { display: none; }" in phone
    assert re.search(r"@media \(max-width: 640px\) \{[^}]*\.col-since \{ display: none; \}", css)


# ---- suppression ----------------------------------------------
#
# Suppress all Warnings or all Infos by clicking their
# counts, and one finding by a checkbox, as in the Build findings dock. The
# rules live in watch.js; the Python suite cannot run it, so these hold the
# served text to them.


def _fn(js, signature):
    body = js[js.index(signature):]
    return body[:body.index("\n  }\n")]


def test_warning_and_info_counts_are_buttons_and_error_is_not(assets):
    panel = _watch_panel(assets["html"])
    for sev in ("warning", "info"):
        start = panel.index(f'class="count-pill count-{sev}" data-sev="{sev}"')
        tag = panel[panel.rindex("<", 0, start):panel.index(">", start)]
        assert tag.startswith("<button") and 'aria-pressed="false"' in tag, sev
        assert 'class="count-hidden"' in panel[start:panel.index("</button>", start)]
    start = panel.index('class="count-pill count-error" data-sev="error"')
    assert panel[panel.rindex("<", 0, start):start].startswith("<div")
    js = assets["js"]
    assert 'const SUPPRESSIBLE_SEVS = ["warning", "info"];' in js


def test_a_suppressed_severity_is_struck_through_and_says_so(assets):
    js, css = assets["js"], assets["css"]
    counts = _fn(js, "function updateCounts()")
    assert '"is-suppressed"' in counts and '" hidden)"' in counts
    assert "is hidden -- click to show them again" in counts
    rule = re.search(r"\.count-pill\.is-suppressed \{([^}]*)\}", css)
    assert rule and "line-through" in rule.group(1)


def test_hidden_findings_count_toward_nothing_and_never_flash(assets):
    js = assets["js"]
    assert "!isHidden(f)" in _fn(js, "function renderStatus()")
    assert "isHidden(f)" in _fn(js, "function updateCounts()")
    assert ".filter((f) => !isHidden(f))" in _fn(js, "function renderTable()")
    handle = _fn(js, "function handleEvent(payload)")
    assert ".filter(f => !isHidden(f))" in handle[handle.index("const fresh"):]


def test_a_suppression_is_keyed_by_identity_and_ends_when_the_fault_clears(assets):
    js = assets["js"]
    assert "suppressed.has(findingKey(f))" in _fn(js, "function isHidden(f)")
    handle = _fn(js, "function handleEvent(payload)")
    cleared = handle[handle.index("payload.cleared_findings"):]
    assert "suppressed.delete(findingKey(f))" in cleared
    start = js[js.index('startBtn.addEventListener("click"'):]
    assert "suppressed.clear();" in start and "hiddenSevs.clear();" in start


def test_the_suppressed_fold_follows_the_table(assets):
    panel = _watch_panel(assets["html"])
    assert (panel.index('id="alert-table"') < panel.index('<details id="watch-suppressed"')
            < panel.index('id="watch-about"'))
    assert 'id="watch-suppressed-list"' in panel and 'id="watch-suppressed-count"' in panel


def test_finding_rows_are_separated_by_two_pixels_of_page_background(assets):
    css = assets["css"]
    assert "#alert-table tbody td { border-bottom: 2px solid var(--bg); }" in css


# ---- the header -----------------------------------------------
#
# From the desk, 2026-10-13: the Info count was grey while the Suppressed
# list showed the same infos blue; "Updated (n)s ago" changed width as it
# counted and pushed the counts sideways; and at laptop width the
# "Watching <address>" pill wrapped onto a second line. Measured in
# Chromium at 1280 and 1440 when fixed; held here on the served text.


def _rule(css, selector):
    m = re.search(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def test_the_info_count_is_blue_when_its_infos_are_hidden_by_their_boxes(assets):
    js, css = assets["js"], assets["css"]
    counts = _fn(js, "function updateCounts()")
    assert 'pill.classList.toggle("has-hidden", hidden[sev] > 0);' in counts
    info = _rule(css, ".count-info:is(.has-count, .has-hidden)")
    assert "background: var(--info-bg)" in info and "color: var(--info-fg)" in info
    # Error and Warning keep their colour only for what is on screen.
    assert ".count-error.has-count {" in css and ".count-warning.has-count {" in css
    assert ".count-error:is(" not in css and ".count-warning:is(" not in css
    # Same specificity: the struck-through state must come later to win.
    assert css.index(".count-pill.is-suppressed {") > css.index(".count-info:is(.has-count, .has-hidden)")


def test_the_updated_label_keeps_one_width_while_it_counts(assets):
    rule = _rule(assets["css"], ".watch-head #last-updated")
    assert "font-variant-numeric: tabular-nums" in rule and "white-space: nowrap" in rule
    # Wide enough for "Updated just now" at 12px while readings arrive.
    width = re.search(r"min-width: ([\d.]+)em", _rule(assets["css"], ".watch-head #last-updated.meta"))
    assert width and float(width.group(1)) >= 10
    # Stale, it is a warning state (ui-style.md §6).
    render = _fn(assets["js"], "function renderLastUpdated()")
    assert 'lastUpdated.className = stale ? "state is-warn" : "meta";' in render


def test_the_header_is_a_block_header_outside_its_box(assets):
    """An earlier change (ui-style.md §3): the title, a notation, then on the
    right the connection state and the controls -- outside the box, which
    is the alert table. Start is the primary, Stop and Flash secondary
    small buttons; Flash says its state in words."""
    panel = _watch_panel(assets["html"])
    head = panel[panel.index('id="panel"'):panel.index('class="panel box table-box watch-table-wrap"')]
    assert 'class="block-head watch-head"' in head and "<h2>Watch</h2>" in head
    assert 'class="notation" id="watch-notation"' in head
    assert 'id="start-btn" class="btn btn-primary btn-sm"' in head
    assert 'id="stop-btn" class="btn btn-secondary btn-sm"' in head
    assert 'class="switch watch-flash-toggle" role="switch"' in head
    assert "<span>Flash on new</span>" in head and '<span class="word" aria-hidden="true">Off</span>' in head
    assert "width: 52px" in _rule(assets["css"], ".watch-interval input")
    assert 'flashToggle.setAttribute("aria-checked", flashOn ? "true" : "false");' in assets["js"]


def test_an_info_rows_tag_in_the_table_is_the_same_blue_as_in_suppressed(assets):
    """"Info badge in regular section is grey
    but is the correct blue color in the suppressed section." Both draw
    `sev sev-<severity>`; the table's info rows may quieten their text,
    never recolour the tag. Since the Watch restyle the table's error and warning
    tags are the large solids (ui-style.md §6, §10)."""
    css, js = assets["css"], assets["js"]
    assert "background: var(--info-bg); color: var(--info-fg)" in _rule(css, ".sev-info")
    row = _fn(js, "function rowHtml(f)")
    assert '<span class="sev big\' + solid + " sev-" + f.severity' in row
    assert 'f.severity === "error" || f.severity === "warning" ? " solid" : ""' in row
    assert 'badge.className = "sev sev-" + f.severity;' in js
    assert re.search(r"tr\.sev-row-info[^{]*\.sev(-badge|-info)?\b[^{]*\{", css) is None
    assert re.search(r"#alert-table \.sev-info\b[^{]*\{", css) is None
    # The row itself stays calm, and error/warning tags take the solids.
    assert "color: var(--text-dim)" in _rule(css, "#alert-table tr.sev-row-info :is(.row-where, .row-claim)")
    assert "var(--alarm-solid)" in _rule(css, ".sev.solid.sev-error")
    assert "var(--caution-solid)" in _rule(css, ".sev.solid.sev-warning")

# ---- A clean screen while watching ----------------------------


def test_the_watch_header_and_verdict_are_pinned_and_the_bars_above_are_hidden(assets):
    css, js, html = assets["css"], assets["js"], assets["html"]
    # The verdict is the box's head, but a sibling of it, so it can pin for
    # the whole page rather than only while the table is on screen.
    panel = _watch_panel(html)
    assert panel.index('id="watch-verdict"') < panel.index('aria-label="Alerts"')
    head = re.search(r"\.watch-shell > \.watch-head \{([^}]*)\}", css).group(1)
    # Under the app header and bundle bar while they show (`--pin-h`, 0
    # while a watch runs and hides them).
    assert "position: sticky" in head and "top: var(--pin-h, 0px)" in head
    verdict = re.search(r"\.watch-shell > \.verdict-bar \{([^}]*)\}", css).group(1)
    assert "position: sticky" in verdict and "var(--watch-head-h" in verdict
    heads = re.search(r"#alert-table thead th \{([^}]*)\}", css).group(1)
    assert "var(--watch-head-h" in heads and "var(--verdict-h" in heads
    assert '"--watch-head-h"' in js and '"--verdict-h"' in js
    # Hidden only on the Watch tab while a watch runs; Stop (running false) shows them.
    assert "body.is-watching:has(#mode-watch.is-active) :is(.topbar, #bundle-chrome) { display: none; }" in css
    assert 'document.body.classList.toggle("is-watching", !!running)' in js
    # Stop stays in the pinned header at phone width; Start is only dropped while watching.
    assert "body.is-watching .watch-shell > .watch-head :is(" in css
    assert "#stop-btn" not in re.search(r"body\.is-watching \.watch-shell > \.watch-head :is\(([^)]*)\)", css).group(1)


def test_the_pinned_header_and_verdict_stay_in_view_in_the_real_page(tmp_path, monkeypatch):
    import os
    import socket
    import threading
    import time
    from pathlib import Path

    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    chromium = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(chromium).exists():
        pytest.skip(f"no Chromium at {chromium} (set ATOO_TEST_CHROMIUM)")
    from atoo import webui

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    for name in ("ATOO_CONSOLE", "ATOO_CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(webui, "DEMO_CLIP_CHANCE", 1.0)
    monkeypatch.setenv("ATOO_DEMO_SEED", "703")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(webui.create_app(), host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/"
    top = "(s) => document.querySelector(s).getBoundingClientRect().top"
    shown = "(s) => getComputedStyle(document.querySelector(s)).display !== 'none'"
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            for width in (1280, 920, 390):
                page = browser.new_page(viewport={"width": width, "height": 500})
                page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1'); } catch (e) {}")
                page.goto(url + "#watch")
                assert page.request.post(url + "api/console", data={"demo": True}).ok
                page.reload()
                page.wait_for_function("document.body.classList.contains('is-demo-show')")
                assert page.evaluate(shown, ".topbar") and page.evaluate(shown, "#bundle-chrome")
                page.click("#start-btn")
                page.wait_for_selector("#alert-body tr:has-text('Clipped')", timeout=30000)
                assert not page.evaluate(shown, ".topbar") and not page.evaluate(shown, "#bundle-chrome")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                assert page.evaluate("scrollY") > 0
                assert page.evaluate(top, "#panel") == 0
                head_h = page.evaluate("document.getElementById('panel').offsetHeight")
                assert abs(page.evaluate(top, "#watch-verdict") - head_h) <= 1
                assert page.evaluate("(s) => { const r = document.querySelector(s).getBoundingClientRect();"
                                     " return r.top >= 0 && r.bottom <= innerHeight; }", "#stop-btn")
                # Stop brings the bars back.
                page.click("#stop-btn")
                page.wait_for_function("!document.body.classList.contains('is-watching')")
                assert page.evaluate(shown, ".topbar") and page.evaluate(shown, "#bundle-chrome")
                page.close()
        finally:
            browser.close()


def test_build_and_apply_keep_the_header_and_bundle_bar_pinned_in_the_real_page(tmp_path,
                                                                                monkeypatch):
    """The app header and the show bundle bar stay at the top of the window
    in Build and Apply, as Watch's header does;
    Build's tiles and the Findings panel pin under them, and a jump to a row
    lands below them. On a phone only the app header stays."""
    import os
    import socket
    import threading
    import time
    from pathlib import Path

    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    chromium = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(chromium).exists():
        pytest.skip(f"no Chromium at {chromium} (set ATOO_TEST_CHROMIUM)")
    from atoo import webui

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    for name in ("ATOO_CONSOLE", "ATOO_CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(webui.create_app(), host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/"
    box = "(s) => { const r = document.querySelector(s).getBoundingClientRect(); return [r.top, r.bottom]; }"
    pin = "parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--pin-h'))"
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            for width in (1440, 1920, 390):
                page = browser.new_page(viewport={"width": width, "height": 600})
                page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1'); } catch (e) {}")
                page.goto(url + "#build")
                assert page.request.post(url + "api/console", data={"demo": True}).ok
                page.reload()
                page.wait_for_function("document.body.classList.contains('is-demo-show')")
                page.click("#tab-plan")
                page.wait_for_selector("#plan-channels-table tbody tr")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(300)
                assert page.evaluate("scrollY") > 0
                top_bar = page.evaluate(box, "body.shell > .topbar")
                assert abs(top_bar[0]) <= 1, (width, top_bar)
                pinned = page.evaluate(pin)
                if width > 600:
                    chrome = page.evaluate(box, "#bundle-chrome")
                    assert abs(chrome[0] - top_bar[1]) <= 1 and abs(pinned - chrome[1]) <= 1, \
                        (width, chrome, pinned)
                    assert abs(page.evaluate(box, "#pipeline-wrap")[0] - pinned) <= 1
                    assert page.evaluate(box, "#dock-col")[0] >= pinned
                else:
                    # The bundle bar scrolls away; only the header is pinned.
                    assert page.evaluate(box, "#bundle-chrome")[1] <= 0
                    assert abs(pinned - top_bar[1]) <= 1
                # A jump to a row lands below the pinned bars.
                row = page.evaluate("document.querySelector('#plan-channels-table tbody tr[id]').id")
                page.evaluate("(id) => window.Atoo.jumpTo({mode: 'build', target: '#' + id})", row)
                page.wait_for_timeout(600)
                assert page.evaluate(box, "#" + row)[0] >= pinned, width
                # Apply keeps them too.
                page.goto(url + "#apply")
                page.wait_for_selector("#mode-apply:not([hidden])")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(300)
                assert abs(page.evaluate(box, "body.shell > .topbar")[0]) <= 1, width
                page.close()
        finally:
            browser.close()


# ---- a long Where wraps -----------------------
#
# "In Watch, finding column is way too small." One finding whose Where is a
# list of strips held its line (white-space: nowrap), and the table widened
# the Where column for every row, squeezing the Finding beside it.


def test_a_where_wraps_at_its_spaces(assets):
    rule = _rule(assets["css"], ".row-where")
    assert "nowrap" not in rule
    assert "overflow-wrap: anywhere" in rule


def test_a_long_where_leaves_the_finding_its_width_in_the_real_page(tmp_path, monkeypatch):
    import os
    import socket
    import threading
    import time
    from pathlib import Path

    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    chromium = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(chromium).exists():
        pytest.skip(f"no Chromium at {chromium} (set ATOO_TEST_CHROMIUM)")
    from atoo import webui

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    for name in ("ATOO_CONSOLE", "ATOO_CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(webui.create_app(), host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    # Two rows as watch.js draws them: a short Where, and a long list.
    rows = """
      const row = (where) => '<tr class="sev-row-warning"><td class="col-hide"></td>' +
        '<td class="col-sev"></td><td class="col-where"><span class="row-where">' + where +
        '</span></td><td class="col-title"><span class="row-claim">Clipped</span>' +
        '<span class="row-why">MTX 2 clipped 3 times; the last was 9.9 s ago.</span></td>' +
        '<td class="col-rule"></td><td class="col-since"></td></tr>';
      document.getElementById('alert-body').innerHTML = row('MTX 2') +
        row('CH 1, CH 2, CH 16, CH 26, CH 28, CH 37, CH 38, CH 40, AUX 3-4');
      const w = (s) => document.querySelector('#alert-body tr td' + s).getBoundingClientRect().width;
      return [w('.col-where'), w('.col-title')];
    """
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            for width in (1000, 1440):
                page = browser.new_page(viewport={"width": width, "height": 700})
                page.goto(f"http://127.0.0.1:{port}/#watch")
                where, finding = page.evaluate(f"() => {{ {rows} }}")
                assert where <= 221, (width, where)
                assert finding > where, (width, where, finding)
                page.close()
        finally:
            browser.close()
