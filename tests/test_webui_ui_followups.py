"""The UI style follow-ups of an earlier change (docs/developer/ui-style.md):

1. **Focus ring** (§4): every button shows the brass ring under keyboard
   focus. An earlier change shipped `.btn:focus-visible`; the quiet `.link-btn`s and a
   few class-less buttons still fell back to the browser's own ring, so
   `button:focus-visible` is the floor under it.
2. **Build tables** (§7): cells are 8px by 12px, a row is 36px, and a table
   wider than its box scrolls inside the box, never the page.
3. **The pipeline tiles**: four lines (name and state, file, counts,
   buttons), the buttons' line never wraps (except from 901 to 1120px,
   beside the Findings dock, where it wraps rather than overflow the tile),
   and the four tiles of a show are one height. A tile's to-do sentence is
   upright 13px (§8).

The Python suite cannot see a browser, so the asset tests pin what the served page
carries, and the Chromium tests measure the real page. The Chromium tests
skip where Playwright or a Chromium is not installed (`ATOO_TEST_CHROMIUM`).

Every bundle is built in the test, with the frozen plan under
`tests/fixtures/rebuild_diff/`; nothing under `examples/` is read.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import webui  # noqa: E402
from atoo.webui import create_app  # noqa: E402

PLAN = Path(__file__).parent / "fixtures" / "rebuild_diff" / "current.plan.json"
INPUT_CSV = (
    "order,patch,name,category,type,model,phantom,notes\n"
    "1,LCL 1,Kick,drums,Mic,Beta 91A,TRUE,inside the kick\n"
    "2,LCL 2,Snare,drums,Mic,SM57,FALSE,\n"
    "3,LCL 3,Guest Vox,vocals,Mic,SM58,FALSE,\n"
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def demo_copy(tmp_path, monkeypatch):
    """The server's Demo show is a scratch copy of the packaged one."""
    copy = tmp_path / "package" / "starter"
    shutil.copytree(webui.DEMO_ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(webui, "DEMO_ROOT", copy)
    monkeypatch.setattr(webui, "DEMO_SHOW_DIR", copy / webui.DEMO_SHOW_DIR.name)
    monkeypatch.setattr(webui, "DEMO_CONVENTIONS", copy / "conventions.md")
    monkeypatch.setattr(webui, "DEMO_PRESETS", copy / "presets")
    return copy


@pytest.fixture
def show(home):
    """A writable show with a plan, whose input list has moved on since it
    was built: the plan is Stale, so tile 04 carries its Rebuild button."""
    show = home / "shows" / "club"
    show.mkdir(parents=True)
    (show / "input.csv").write_text(INPUT_CSV)
    (show / "instructions.md").write_text("## Channels\n- Kick first.\n")
    shutil.copy(PLAN, show / "plan.json")
    (home / "conventions.md").write_text("## Inputs\n- Patch in list order.\n")
    return show


@pytest.fixture
def client(show, home):
    app = create_app(initial_bundle=str(show),
                     initial_conventions=str(home / "conventions.md"))
    with fastapi_testclient.TestClient(app) as c:
        yield c


# ---- the served assets ------------------------------------------------------


def _rules(css: str, selector: str) -> list[str]:
    """The bodies of every rule whose selector list is exactly `selector`."""
    return [m.group(1) for m in re.finditer(
        r"(?:^|\}|\*/)\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)]


def test_every_button_has_the_brass_focus_ring(client):
    css = client.get("/static/styles.css").text
    bodies = _rules(css, "button:focus-visible, .btn:focus-visible, .btn-icon:focus-visible")
    assert len(bodies) == 1
    assert "outline: 2px solid var(--accent)" in bodies[0]
    assert "outline-offset: 2px" in bodies[0]
    # Nothing below it takes the ring off a button.
    assert not re.search(r"button[^{]*:focus-visible[^{]*\{[^}]*outline:\s*none", css)


def _tile(html: str, tab_id: str) -> str:
    start = html.index(f'id="{tab_id}"')
    ends = [i for i in (html.find('class="pipe-arrow"', start),
                        html.find('class="help-pop pipeline-help"', start)) if i != -1]
    return html[start:min(ends)]


def test_a_tile_is_four_lines_and_house_is_on_the_file_line(client):
    html = client.get("/").text
    for tab_id in ("tab-conventions", "tab-input-list", "tab-instructions", "tab-plan"):
        tile = _tile(html, tab_id)
        order = [tile.index(c) for c in ('class="pipe-stop-top"', 'id="hint-',
                                        'class="pipe-meta"', 'class="pipe-stop-actions"')]
        assert order == sorted(order), tab_id
        actions = tile[tile.index('class="pipe-stop-actions"'):]
        # The buttons' line holds buttons: not House, a count or a readout.
        assert 'class="prop"' not in actions, tab_id
        assert "pipe-stat" not in actions, tab_id
    conventions = _tile(html, "tab-conventions")
    line = conventions[conventions.index('class="pipe-file-line"'):conventions.index('class="pipe-meta"')]
    assert 'id="hint-conventions"' in line and 'class="prop"' in line
    # The counts are on the meta line.
    for slot in ("conventions", "input-list", "instructions"):
        meta = _tile(html, f"tab-{slot}")
        meta = meta[meta.index('class="pipe-meta"'):meta.index('class="pipe-stop-actions"')]
        assert f'id="findings-{slot}"' in meta
    assert 'id="status-rows"' in _tile(html, "tab-input-list")
    assert 'id="status-layers"' in _tile(html, "tab-instructions")
    plan = _tile(html, "tab-plan")
    meta = plan[plan.index('class="pipe-meta"'):plan.index('class="pipe-stop-actions"')]
    for element_id in ("status-build-progress", "status-plan-badge", "status-rebuild-btn"):
        assert f'id="{element_id}"' in meta, element_id


def test_the_css_never_wraps_the_tiles_buttons_except_beside_the_dock(client):
    css = client.get("/static/styles.css").text
    (actions,) = _rules(css, ".pipe-stop-actions")
    assert "flex-wrap: nowrap" in actions and "gap: 8px" in actions
    assert "wrap;" not in actions.replace("nowrap", "")
    # No shared height: the tiles share a flex row and stretch to the tallest.
    assert "--pipe-tile-h" not in css
    # The 20px plan tag fits the counts' 18px line, so a wrapped row of tiles stays level.
    assert ".pipe-meta .state { margin-block: -1px; }" in css
    # Beside the Findings dock the tiles are too narrow for one line.
    assert re.search(r"@media \(min-width: 901px\) and \(max-width: 1120px\) \{\s*"
                     r"#build-steps \.pipe-stop-actions \{ flex-wrap: wrap; row-gap: 4px; \}", css)
    # §8: a tile's to-do is an upright 13px sentence, not italic 12px.
    (todo,) = _rules(css, ".pipe-stop > .pipe-todo")
    assert "font-size: 13px" in todo and "font-style: normal" in todo
    assert "italic" not in todo


def test_the_css_sets_the_build_tables_cells_and_rows(client):
    css = client.get("/static/styles.css").text
    assert ".build-body :is(.it, .ct) :is(th, td) { padding: 8px 12px; }" in css
    assert ".build-body :is(.it, .ct) tbody td { height: 36px; box-sizing: border-box; line-height: 19px; }" in css
    assert "td:not(.col-move):not(.col-remove):not(.col-order)" in css


# ---- the real page, in Chromium --------------------------------------------


def _chromium():
    sync_api = pytest.importorskip("playwright.sync_api")
    path = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(path).exists():
        pytest.skip(f"no Chromium at {path} (set ATOO_TEST_CHROMIUM)")
    return sync_api, path


def _serve(app):
    uvicorn = pytest.importorskip("uvicorn")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the test server did not start")
    return f"http://127.0.0.1:{port}/", server, thread


@pytest.fixture
def served(show, home, demo_copy):
    app = create_app(initial_bundle=str(show),
                     initial_conventions=str(home / "conventions.md"),
                     initial_plan=json.loads(PLAN.read_text()),
                     initial_plan_path=str(show / "plan.json"))
    url, server, thread = _serve(app)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def served_with_a_to_do(show, home, demo_copy):
    """No instructions.md: tile 03 says so in a to-do sentence."""
    (show / "instructions.md").unlink()
    app = create_app(initial_bundle=str(show),
                     initial_conventions=str(home / "conventions.md"))
    url, server, thread = _serve(app)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


class _Browser:
    """One Chromium; a dark page of a given width, on the page's own URL."""

    def __init__(self):
        self.sync_api, self.path = _chromium()

    def __enter__(self):
        self._p = self.sync_api.sync_playwright().start()
        self.browser = self._p.chromium.launch(executable_path=self.path)
        return self

    def __exit__(self, *exc):
        self.browser.close()
        self._p.stop()

    def page(self, url, width, *, demo=False):
        page = self.browser.new_page(viewport={"width": width, "height": 900})
        # Dark is the primary look; the Demo popup is the first-run notice.
        page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen','1');"
                             " localStorage.setItem('atoo.theme','dark'); } catch (e) {}")
        page.goto(url)
        if demo:
            r = page.request.post(url + "api/console", data={"demo": True})
            assert r.ok, r.text()
        page.goto("about:blank")
        page.goto(url)
        if demo:
            page.wait_for_function("document.body.classList.contains('is-demo-show')")
        page.wait_for_selector("#build-steps .pipe-stop", state="attached")
        page.wait_for_selector("#input-rows tr", state="attached")
        return page


def _open_step(page, step):
    page.evaluate("s => document.getElementById('tab-' + s).click()", step)
    page.wait_for_selector(f"#panel-{step}:not([hidden])", state="attached")


TILES = """() => Array.from(document.querySelectorAll('#build-steps .pipe-stop')).map(t => {
  const a = t.querySelector('.pipe-stop-actions'); const r = t.getBoundingClientRect();
  return {id: t.id, h: Math.round(r.height * 10) / 10, wrap: getComputedStyle(a).flexWrap,
          fits: a.scrollWidth <= a.clientWidth + 0.5, actionsH: Math.round(a.getBoundingClientRect().height)}; })"""


@pytest.mark.parametrize("width", [1440, 390])
def test_the_four_tiles_are_one_height_on_a_writable_show_and_the_demo(served, width):
    with _Browser() as b:
        writable = b.page(served, width)
        w = writable.evaluate(TILES)
        assert [t["id"] for t in w] == ["tab-conventions", "tab-input-list",
                                        "tab-instructions", "tab-plan"]
        demo = b.page(served, width, demo=True)
        d = demo.evaluate(TILES)
        # Within a show the four tiles are equal (a flex row, `stretch`); a
        # read-only show's are shorter, its buttons being hidden.
        assert len({t["h"] for t in w}) == 1, w
        assert len({t["h"] for t in d}) == 1, d
        # Tile 04 carries Rebuild plan on a Stale plan: it still fits.
        assert writable.locator("#status-rebuild-btn").is_visible()
        for t in w:
            assert t["wrap"] == "nowrap", t
            assert t["fits"], t
            assert t["actionsH"] <= 24, t
        # The Demo's buttons are hidden, not locked (section 4).
        assert not demo.locator("#change-conventions").is_visible()


BESIDE_THE_DOCK = """() => Array.from(document.querySelectorAll('#build-steps .pipe-stop')).map(t => {
  const r = t.getBoundingClientRect(); const c = getComputedStyle(t);
  const inner = r.right - parseFloat(c.borderRightWidth) - parseFloat(c.paddingRight);
  const a = t.querySelector('.pipe-stop-actions');
  const shown = Array.from(a.children).filter(e => e.offsetParent);
  const last = shown.length ? Math.max(...shown.map(e => e.getBoundingClientRect().right)) : null;
  return {id: t.id, w: Math.round(r.width), h: Math.round(r.height * 10) / 10, inner, last,
          overflow: a.scrollWidth - a.clientWidth}; })"""


@pytest.mark.parametrize("width", [901, 1000, 1120])
def test_between_901_and_1120_the_buttons_wrap_rather_than_leave_the_tile(served, width):
    """Beside the Findings dock a tile is 115 to 165px wide: New file used to
    run out of tile 01 (28px at 1000, and across its border)."""
    with _Browser() as b:
        page = b.page(served, width)
        tiles = page.evaluate(BESIDE_THE_DOCK)
        assert len(tiles) == 4
        # Tile 01's buttons end inside the tile's inner edge.
        one = tiles[0]
        assert one["last"] is not None and one["last"] <= one["inner"] + 0.5, one
        # The four tiles are equal.
        assert len({t["h"] for t in tiles}) == 1, tiles
        assert page.evaluate("() => getComputedStyle(document.querySelector("
                             "'#build-steps .pipe-stop-actions')).flexWrap") == "wrap"


def test_above_1120_the_buttons_line_is_one_row(served):
    with _Browser() as b:
        page = b.page(served, 1200)
        assert all(t["wrap"] == "nowrap" and t["fits"] for t in page.evaluate(TILES))


def test_a_to_do_on_a_tile_is_an_upright_13px_sentence(served_with_a_to_do):
    with _Browser() as b:
        page = b.page(served_with_a_to_do, 1440)
        todo = page.locator("#todo-instructions")
        todo.wait_for(state="visible")
        assert todo.inner_text().startswith("Optional.")
        style = todo.evaluate("e => [getComputedStyle(e).fontStyle, getComputedStyle(e).fontSize]")
        assert style == ["normal", "13px"]
        # The buttons are still one non-wrapping line under it.
        assert all(t["wrap"] == "nowrap" and t["fits"] for t in page.evaluate(TILES))


ROWS = """(sel) => { const t = document.querySelector(sel); if (!t) return null;
  const rows = Array.from(t.querySelectorAll('tbody > tr'))
    .filter(r => r.offsetParent && !r.classList.contains('row-detail'));
  const single = rows.filter(r => !r.querySelector('.ct-desk-name'));
  const cs = (e) => { const c = getComputedStyle(e); return [c.paddingTop, c.paddingRight, c.paddingBottom, c.paddingLeft]; };
  const text = Array.from(t.querySelectorAll('tbody td')).find(td => td.offsetParent && td.textContent.trim() && !/col-(num|findings|order|move|remove|expand)/.test(td.className) && !Array.from(td.querySelectorAll('input, button, select, textarea')).some(e => e.offsetParent));
  let wrap = t.parentElement; while (wrap && wrap !== document.body && getComputedStyle(wrap).overflowX === 'visible') wrap = wrap.parentElement;
  return {rows: rows.length, heights: single.map(r => r.getBoundingClientRect().height),
          th: cs(Array.from(t.querySelectorAll('thead th')).find(h => h.textContent.trim() && h.offsetParent && !/col-(move|remove|order|expand)/.test(h.className))), text: text ? cs(text) : null,
          wrap: [wrap.clientWidth, wrap.scrollWidth, getComputedStyle(wrap).overflowX],
          page: [document.documentElement.clientWidth, document.documentElement.scrollWidth]}; }"""


def _assert_36px_rows(m):
    assert m["rows"] > 0
    # A row is 36px (the collapsed 1px rule between rows is half in each).
    assert all(35.5 <= h <= 37.6 for h in m["heights"]), m["heights"]
    assert sum(1 for h in m["heights"] if h <= 36.6) >= 0.8 * len(m["heights"]), m["heights"]


def test_the_input_table_is_8_by_12_with_36px_rows_writable_and_read_only(served):
    with _Browser() as b:
        for demo in (False, True):
            page = b.page(served, 1440, demo=demo)
            _open_step(page, "input-list")
            m = page.evaluate(ROWS, "#input-table")
            _assert_36px_rows(m)
            assert m["th"] == ["8px", "12px", "8px", "12px"], m
            if demo:
                # A text cell is 8px by 12px (a writable row's cells hold inputs).
                assert m["text"] == ["8px", "12px", "8px", "12px"], m
            assert m["page"][0] == m["page"][1], m


def test_a_wide_table_scrolls_inside_its_box_never_the_page(served):
    with _Browser() as b:
        page = b.page(served, 390)
        _open_step(page, "input-list")
        m = page.evaluate(ROWS, "#input-table")
        assert m["wrap"][2] in ("auto", "scroll")
        assert m["wrap"][1] > m["wrap"][0], m
        assert m["page"][0] == m["page"][1], m
        _open_step(page, "plan")
        page.wait_for_selector("#panel-plan table.ct", state="attached")
        m = page.evaluate(ROWS, "#panel-plan table.ct")
        assert m["wrap"][1] > m["wrap"][0], m
        assert m["page"][0] == m["page"][1], m
        # Rows stay 36px at phone width too: nothing wraps to a second line.
        _assert_36px_rows(m)


def test_the_channel_table_with_every_sheet_column_scrolls_in_its_box(served):
    with _Browser() as b:
        page = b.page(served, 1440)
        _open_step(page, "plan")
        page.wait_for_selector("#panel-plan table.ct", state="attached")
        m = page.evaluate(ROWS, "#panel-plan table.ct")
        _assert_36px_rows(m)
        assert m["th"] == ["8px", "12px", "8px", "12px"], m
        assert m["text"] == ["8px", "12px", "8px", "12px"], m
        # One view with every column of the input list. This
        # show's rows carry CHANGED chips and plan-only strips, which make it
        # wider than its box: the box scrolls, never the page. A captured
        # show's table fits (`test_a_captured_shows_channel_table_fits_its_box`).
        assert m["wrap"][2] in ("auto", "scroll")
        assert m["page"][0] == m["page"][1], m


def test_every_button_shows_the_brass_ring_under_keyboard_focus(served):
    with _Browser() as b:
        page = b.page(served, 1440)
        accent = page.evaluate(
            "() => { const p = document.createElement('i'); p.style.color = 'var(--accent)';"
            " document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; }")
        # A button of each class: the tiles' and bar's, an icon button, and
        # the two that an earlier change left to the browser's ring.
        page.evaluate("""() => {
          for (const cls of ['link-btn', '']) {
            const b = document.createElement('button'); b.type = 'button'; b.className = cls;
            b.id = 'probe-' + (cls || 'bare'); b.textContent = 'probe'; document.body.prepend(b);
          } }""")
        checked = {"btn": 0, "other": 0}
        probes = set()
        for _ in range(60):
            page.keyboard.press("Tab")
            info = page.evaluate("""() => { const e = document.activeElement;
              if (!e || e === document.body) return null; const c = getComputedStyle(e);
              return {tag: e.tagName, id: e.id, cls: e.className, fv: e.matches(':focus-visible'),
                      style: c.outlineStyle, width: c.outlineWidth, color: c.outlineColor, offset: c.outlineOffset}; }""")
            if info and info["tag"] == "BUTTON" and info["fv"]:
                assert info["style"] == "solid" and info["width"] == "2px", info
                assert info["color"] == accent, info
                if info["id"].startswith("probe-"):
                    probes.add(info["id"])
                if "btn" in str(info["cls"]).split() or info["id"].startswith("probe-"):
                    assert info["offset"] == "2px", info
                    checked["btn"] += 1
                else:
                    checked["other"] += 1
        assert probes == {"probe-link-btn", "probe-bare"}, probes
        assert checked["btn"] >= 8, checked


@pytest.fixture
def served_church(home, tmp_path):
    """The church desk's frozen snapshot, captured into a show."""
    import copy

    from atoo import capture
    from atoo.snapshot import load_snapshot

    snap = Path(__file__).parent / "fixtures" / "church-full-2026-10-24.snap"
    state = capture.state_from_snap(load_snapshot(str(snap)), "wing-full")
    result = capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                  captured="2026-10-24", snapshot="captures/church.snap")
    directory = tmp_path / "church"
    capture.write_bundle(copy.deepcopy(result), directory, evidence_name="church.snap",
                         evidence=b"{}")
    app = create_app(initial_bundle=str(directory),
                     initial_plan=json.loads((directory / "plan.json").read_text()),
                     initial_plan_path=str(directory / "plan.json"))
    url, server, thread = _serve(app)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.parametrize("width", [1440, 1920])
def test_a_captured_shows_channel_table_fits_its_box(served_church, width):
    """The Channels table fits its box beside the Findings panel, every
    column in view; the box's scroll is a fallback for a narrow window."""
    with _Browser() as b:
        page = b.page(served_church, width)
        _open_step(page, "plan")
        page.wait_for_selector("#plan-channels-table", state="attached")
        m = page.evaluate(ROWS, "#plan-channels-table")
        assert m["wrap"][1] <= m["wrap"][0], m
        for table in ("#plan-busses-table", "#plan-outputs-table"):
            m = page.evaluate(ROWS, table)
            assert m["wrap"][1] <= m["wrap"][0], (table, m)


def test_edit_sheets_takes_the_same_page_to_build_and_back_to_the_running_watch(
        served_church, monkeypatch):
    """Watch's Edit sheets changes the page, not the tab (the maintainer,
    2026-10-25: "it should just navigate to the Build page"): step 04 says
    Watch is still running, and Back to Watch finds the same session, still
    running, with no new tab and no restart."""
    import copy

    from atoo import capture, webui
    from atoo.snapshot import load_snapshot

    snap = Path(__file__).parent / "fixtures" / "church-full-2026-10-24.snap"
    state = capture.state_from_snap(load_snapshot(str(snap)), "wing-full")
    keep = ("/ch/1/", "/bus/9/")
    small = type(state)(values={a: v for a, v in state.values.items() if a.startswith(keep)},
                        console_model="wing-full")
    monkeypatch.setattr(webui, "console_provider_factory",
                        lambda address, **kw: ((lambda names=None: copy.deepcopy(small)), None))
    with _Browser() as b:
        page = b.page(served_church + "#watch", 1440)
        started = page.request.post(served_church + "api/watch/start",
                                    data={"source": "console", "console": "192.0.2.1",
                                          "interval": 0.2})
        assert started.ok, started.text()
        page.wait_for_selector("#watch-edit-sheets:not([hidden])")
        page.click("#watch-edit-sheets")
        page.wait_for_selector("#panel-plan:not([hidden])")
        assert page.evaluate("location.hash") == "#build"
        assert len(page.context.pages) == 1
        assert page.is_visible("#plan-from-watch")
        assert "Watch is still running." in page.inner_text("#plan-from-watch")
        page.click("#plan-back-to-watch")
        assert page.evaluate("location.hash") == "#watch"
        assert not page.is_visible("#plan-from-watch")
        assert page.request.get(served_church + "api/status").json()["running"] is True
        page.wait_for_selector("#alert-body tr")
        page.request.post(served_church + "api/watch/stop")

def test_a_long_refusal_wraps_inside_the_busses_box(served_church):
    """A refused cell's reason is a sentence under its row, and it wraps: an
    output two buses claim gave a reason long enough to stretch the Busses
    table to ~3,000 px when the row's one-line rule won. The reason names
    the rows as the sheet does, not by their plan paths. A row's sources are
    in its disclosure since revision 3; a long list of names
    nothing is called gives a long reason too."""
    with _Browser() as b:
        page = b.page(served_church, 1440)
        _open_step(page, "plan")
        page.click('#plan-busses-table tr[data-bus-label="Bus 10"] .row-expand-btn')
        page.wait_for_selector('input[data-bus-row="Bus 10"][data-bus-col="sources"]')
        page.fill('input[data-bus-row="Bus 10"][data-bus-col="sources"]',
                  "; ".join(f"Nobody By That Name {n}" for n in range(12)))
        page.wait_for_selector("#plan-busses-table tr.row-refusal")
        m = page.evaluate(ROWS, "#plan-busses-table")
        assert m["wrap"][1] <= m["wrap"][0], m
        width = page.evaluate("document.querySelector('#plan-busses-table')"
                              ".getBoundingClientRect().width")
        assert width <= m["wrap"][0] + 1, (width, m)
        reason = page.inner_text("#plan-busses-table tr.row-refusal")
        assert "Nobody By That Name 0" in reason
        assert "busses[" not in reason


def test_a_page_that_joins_a_running_watch_shows_every_finding_already_there(
        served_church, monkeypatch):
    """A page that joins a running watch -- opened after Start,
    reloaded, or reconnected -- is handed the server's last frame, whose
    new_findings are only that pass's. It showed none of the findings already
    there, so a stage box not connected (C008, an ERROR) vanished from the
    table though nothing on the desk had changed. Every finding the frame
    lists is on the table."""
    import time

    from atoo import webui
    from atoo.audit import ConsoleState

    desk = ConsoleState({"/$stat/A/stat": "-", "/$stat/B/stat": "-", "/$stat/C/stat": "-",
                         "/io/out/B/25/grp": "LCL", "/io/out/B/25/in": 1,
                         "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0},
                        console_model="wing-full")
    monkeypatch.setattr(webui, "console_provider_factory",
                        lambda address, **kw: ((lambda names=None: desk), None))
    with _Browser() as b:
        first = b.page(served_church + "#watch", 1440)
        started = first.request.post(served_church + "api/watch/start",
                                     data={"source": "console", "console": "192.0.2.1",
                                           "interval": 0.2})
        assert started.ok, started.text()
        first.wait_for_selector("#alert-body tr:has-text('C008')")
        time.sleep(1.5)   # several passes, so the last frame is not the baseline
        joined = b.page(served_church + "#watch", 1440)
        joined.wait_for_selector("#alert-body tr:has-text('C008')", timeout=10000)
        assert ("Stage box AES50 port B appears to not be connected"
                in joined.inner_text("#alert-body tr:has-text('C008')"))
        first.reload()
        first.wait_for_selector("#alert-body tr:has-text('C008')", timeout=10000)
        first.request.post(served_church + "api/watch/stop")


def test_choosing_a_role_leaves_the_page_where_it_was(served_church):
    """Choosing a Role in the Busses table moved the page about
    40-100 px when the check came back and the tables were drawn again. The
    page stays put, and so does the cell."""
    with _Browser() as b:
        page = b.page(served_church, 1440)
        _open_step(page, "plan")
        cell = 'select[data-bus-row="Bus 2"][data-bus-col="role"]'
        page.wait_for_selector(cell)
        page.evaluate("s => { const e = document.querySelector(s); window.scrollTo(0, "
                      "e.getBoundingClientRect().top + window.scrollY - 450); }", cell)
        page.wait_for_timeout(300)
        where = "s => [window.scrollY, document.querySelector(s).getBoundingClientRect().top]"
        before = page.evaluate(where, cell)
        page.click(cell)
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        # The check answers after 400 ms; the tables are drawn again then.
        page.wait_for_function("document.querySelector('.bus-dirty-badge:not([hidden])')")
        page.wait_for_timeout(1200)
        after = page.evaluate(where, cell)
        assert after[0] == before[0], (before, after)
        assert abs(after[1] - before[1]) <= 3, (before, after)
