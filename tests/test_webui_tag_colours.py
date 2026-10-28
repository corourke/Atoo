"""The colour rule on Build's tables (the UI style guide: one colour, one meaning).

Blue means information, amber a warning, brass only "press me". So on the
plan table (Build 04) the stereo tag and the 48V tag are the neutral
property tag (`.prop`) that Build 02 already draws, the strip's desk name
is plain dim text, and a row's Notes button, when it has a note, is told by
its filled glyph in the text colour, not by brass.

The Python suite cannot see a browser, so the first half asserts over the
served `styles.css` and `setup.js`, and the second reads the computed colours
on the real page in Chromium, dark and light. The Chromium tests skip where
Playwright or a Chromium is not installed (`ATOO_TEST_CHROMIUM`).

The shows are built in the test, from the frozen plan under
`tests/fixtures/rebuild_diff/`; nothing under `examples/` is read.
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402
from test_webui_ui_followups import (  # noqa: E402,F401
    PLAN, _Browser, _open_step, _serve, client, demo_copy, home, show,
)

# The plan names one stereo pair "OH" over inputs "OH L" and "OH R": the
# input's own name differs from the strip's, so the row says "on desk: OH".
INPUT_CSV = (
    "order,patch,name,category,type,model,phantom,notes\n"
    "1,LCL 1,Kick,drums,Mic,Beta 91A,TRUE,inside the kick\n"
    "2,LCL 2,Snare,drums,Mic,SM57,FALSE,\n"
    "5,LCL 5,OH L,drums,Mic,KSM137,TRUE,\n"
    "6,LCL 6,OH R,drums,Mic,KSM137,TRUE,\n"
)


@pytest.fixture
def served(show, home, demo_copy):
    (show / "input.csv").write_text(INPUT_CSV)
    app = create_app(initial_bundle=str(show),
                     initial_conventions=str(home / "conventions.md"),
                     initial_plan=json.loads(PLAN.read_text()),
                     initial_plan_path=str(show / "plan.json"))
    url, server, thread = _serve(app)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


# ---- the served assets ------------------------------------------------------


def test_the_plan_tables_tags_are_the_neutral_property_tag(client):
    js = client.get("/static/setup.js").text
    css = client.get("/static/styles.css").text
    assert '<span class="prop ct-st"' in js
    assert '<span class="prop" title="Phantom power (48V) on' in js
    assert '<span class="meta ct-desk-name"' in js
    for retired in (".st-badge", ".phantom-badge"):
        assert retired not in css and retired[1:] not in js, retired
    # Nothing in the table's stylesheet gives them a hue of their own.
    for selector in (".ct-st", ".ct-desk-name"):
        body = re.search(re.escape(selector) + r" \{([^}]*)\}", css).group(1)
        assert "color" not in body and "background" not in body, selector


def test_a_note_is_not_told_by_brass(client):
    css = client.get("/static/styles.css").text
    body = re.search(r"\.note-btn\.has-note \{([^}]*)\}", css).group(1)
    assert "var(--text)" in body
    assert "accent" not in body


# ---- the real page, in Chromium --------------------------------------------

# The colours of the first element matching `sel`, resolved to rgb strings.
PAINT = """([sel, scope]) => {
  const root = scope ? document.querySelector(scope) : document;
  const e = root && root.querySelector(sel); if (!e) return null;
  const c = getComputedStyle(e);
  return {color: c.color, background: c.backgroundColor, border: c.borderTopColor, text: e.textContent.trim()}; }"""

# What a CSS variable resolves to, through a probe element.
VAR = """(name) => { const p = document.createElement('span'); p.style.color = 'var(' + name + ')';
  document.body.appendChild(p); const v = getComputedStyle(p).color; p.remove(); return v; }"""


def _page(browser, url, theme, width=1280, *, demo=False):
    page = browser.page(url, width, demo=demo)
    if theme != "dark":
        page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
    return page


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_stereo_48v_and_the_desk_name_have_no_colour_of_their_own(served, theme):
    with _Browser() as b:
        page = _page(b, served, theme)
        _open_step(page, "plan")
        info, warn = page.evaluate(VAR, "--info-fg"), page.evaluate(VAR, "--warning-fg")
        accent, dim = page.evaluate(VAR, "--accent"), page.evaluate(VAR, "--text-dim")
        st = page.evaluate(PAINT, ["#panel-plan .ct .ct-st", None])
        desk = page.evaluate(PAINT, ["#panel-plan .ct .ct-desk-name", None])
        assert st["text"] == "ST"
        assert desk["text"] == "on desk: OH"
        # The same neutral tag Build 02 draws: dim text on nothing.
        assert st["color"] == dim, st
        assert st["background"] == "rgba(0, 0, 0, 0)", st
        assert st["color"] not in (info, warn, accent), st
        assert desk["color"] == dim and desk["color"] != accent
        # 48V is a tag only where the table is read-only (an editable one is
        # step 02's own tick): the Demo draws it in Build 02 and
        # Build 04 as one tag, with the same paint as ST.
        demo = _page(b, served, theme, demo=True)
        _open_step(demo, "input-list")
        two = demo.evaluate(PAINT, ["#panel-input-list .prop", None])
        _open_step(demo, "plan")
        four = demo.evaluate(PAINT, ["#panel-plan .ct .col-sheet-phantom .prop", None])
        assert two is not None and four is not None and four["text"] == "48V"
        for phantom in (two, four):
            assert (phantom["color"], phantom["background"]) == (st["color"], st["background"])
        assert (two["color"], two["background"], two["border"]) == \
               (four["color"], four["background"], four["border"])


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_a_note_button_is_not_brass_in_build_02_or_04(served, theme):
    with _Browser() as b:
        page = _page(b, served, theme)
        accent = page.evaluate(VAR, "--accent")
        text = page.evaluate(VAR, "--text")
        _open_step(page, "input-list")
        two = page.evaluate(PAINT, [".note-btn.has-note", "#panel-input-list"])
        _open_step(page, "plan")
        page.evaluate("document.querySelector('#panel-plan .row-expand-btn').click()")
        four = page.evaluate(PAINT, [".note-btn.has-note", "#panel-plan"])
        for paint in (two, four):
            assert paint is not None
            assert paint["color"] == text, paint
            assert accent not in (paint["color"], paint["border"]), paint
        # A note-less row's button is the dim hollow icon, so the two differ
        # by the glyph and the ink, never by hue.
        empty = page.evaluate(PAINT, [".note-btn:not(.has-note)", "#panel-plan"])
        assert empty["color"] == page.evaluate(VAR, "--text-dim")


def test_the_plan_table_does_not_scroll_the_page_sideways_at_390(served):
    with _Browser() as b:
        page = _page(b, served, "dark", 390)
        _open_step(page, "plan")
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
