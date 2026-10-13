"""The Watch page's layout, look B of `mockups/watch-layout/`.

The maintainer, 2026-10-11, choosing it: *"B, with no thin colored border (keep
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
Python suite can see (CLAUDE.md); every state here is built in the test.
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
        'id="panel"', 'id="start-btn"', 'id="watch-flash-on"', 'class="summary"',
        'id="conn-pill"', 'id="alert-table"', 'id="watch-about"', 'id="wc-panel"')]
    assert order == sorted(order)
    # Nothing between the header and the table but the header's own lines.
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
    assert 'body[data-watch-worst="stale"] .watch-table-wrap' in assets["css"]
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
    assert "<button" in toggle and 'aria-pressed="false"' in toggle and "Off" in toggle
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
    """At 390px the five columns measured ~474px in a 364px frame, and
    .table-wrap's overflow: hidden clipped Rule out of reach. Narrow
    screens let the fixed widths go and scroll rather than clip; phone
    width drops Rule (Since already goes in the generic table rule)."""
    css = assets["css"]
    assert re.search(r"\.table-wrap \{[^}]*overflow: hidden", css)
    narrow = _media_block(css, "max-width: 760px", "/* The folds: one line each until opened. */")
    assert ".watch-table-wrap { overflow-x: auto; }" in narrow
    assert "#alert-table :is(.col-sev, .col-rule, .col-since) { width: auto; }" in narrow
    phone = _media_block(css, "max-width: 640px", "/* The folds: one line each until opened. */")
    assert "#alert-table .col-rule { display: none; }" in phone
    assert re.search(r"@media \(max-width: 640px\) \{[^}]*\.col-since \{ display: none; \}", css)


# ---- suppression ----------------------------------------------
#
# The maintainer, 2026-10-12: suppress all Warnings or all Infos by clicking their
# counts, and one finding by a checkbox, as in the Build findings dock. The
# rules live in watch.js; the Python suite cannot run it, so these hold the
# served text to them (CLAUDE.md, "a rename that crosses into
# atoo/web/static/ is invisible to the test suite").


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
    assert "font-variant-numeric: tabular-nums" in rule
    assert "white-space: nowrap" in rule and "box-sizing: border-box" in rule
    # Wide enough for "Updated just now" and "No reading for 45s" at 12px
    # (measured 112px and 117px in Chromium, padding included).
    width = re.search(r"min-width: ([\d.]+)em", rule)
    assert width and float(width.group(1)) >= 10
    # The stale state's padding is the base rule's, so going stale adds a
    # colour and not width; and its colour is not lost to the base rule.
    assert "padding: 3px 6px" in rule
    assert "padding" not in _rule(assets["css"], ".watch-head #last-updated.is-stale")
    assert "var(--warning-fg)" in _rule(assets["css"], ".watch-head #last-updated.is-stale")


def test_the_header_is_compact_enough_for_one_line_at_laptop_width(assets):
    css = assets["css"]
    row = _rule(css, ".watch-head .watch-head-row")
    assert "gap: 8px" in row
    assert "padding: 7px 12px" in _rule(css, ".watch-head .btn")
    assert "padding: 6px 8px" in _rule(css, ".watch-head .count-pill")
    assert "padding: 6px 8px" in _rule(css, ".watch-head #conn-pill")
    assert "width: 52px" in _rule(css, ".watch-interval input")
    flash = _rule(css, ".watch-flash-toggle")
    assert "padding: 6px 8px" in flash and "margin-left" not in flash


def test_an_info_rows_tag_in_the_table_is_the_same_blue_as_in_suppressed(assets):
    """The maintainer, 2026-10-13: "Info badge in regular section is grey
    but is the correct blue color in the suppressed section." Both draw
    `sev-badge sev-<severity>`; the table's info rows may quieten their
    text, never recolour the tag."""
    css, js = assets["css"], assets["js"]
    assert "background: var(--info-bg); color: var(--info-fg)" in _rule(css, ".sev-info")
    assert '<span class="sev-badge sev-\' + f.severity + \'">' in js
    assert re.search(r"tr\.sev-row-info[^{]*\.sev-(badge|info)\b[^{]*\{", css) is None
    assert re.search(r"#alert-table \.sev-info\b[^{]*\{", css) is None
    # The row itself stays calm, and error/warning tags keep their solids.
    assert "color: var(--text-dim)" in _rule(css, "#alert-table tr.sev-row-info :is(.row-where, .row-claim)")
    assert "var(--alarm-solid)" in _rule(css, "#alert-table .sev-error")
    assert "var(--caution-solid)" in _rule(css, "#alert-table .sev-warning")
