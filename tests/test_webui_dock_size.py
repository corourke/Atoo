"""The Findings panel is as tall as its content, and on a phone it follows
the page's content instead of leading it.

Beside the page (wider than 900px) the dock is a sticky column: it takes the
height of what it holds, up to the window's height, and scrolls inside past
that, rather than being a window-tall box with empty space under a short
verdict. At phone width it is a band under the tiles and tables, not about
330px of panel before them.

The Python suite cannot see a browser, so the first test asserts over the
served stylesheet and the others measure the real page in Chromium. They
skip where Playwright or a Chromium is not installed
(`ATOO_TEST_CHROMIUM`). The shows are built in the test; nothing under
`examples/` is read.
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402
from test_webui_ui_followups import (  # noqa: E402,F401
    PLAN, _Browser, _serve, client, demo_copy, home, served, show,
)

MEASURE = """() => { const d = document.querySelector('.findings-dock').getBoundingClientRect();
  const m = document.querySelector('.layout-main').getBoundingClientRect();
  const body = document.querySelector('.findings-dock .dock-body');
  return {top: d.top + window.scrollY, height: d.height, mainTop: m.top + window.scrollY,
          mainBottom: m.bottom + window.scrollY, winH: window.innerHeight,
          inner: body.scrollHeight, shown: body.clientHeight, page: document.documentElement.scrollWidth}; }"""


@pytest.fixture
def served_short(show, home, demo_copy):
    """A show with no plan: the dock has little to say."""
    (show / "plan.json").unlink()
    app = create_app(initial_bundle=str(show), initial_conventions=str(home / "conventions.md"))
    url, server, thread = _serve(app)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


def test_the_dock_is_sized_to_its_content_and_follows_the_page_on_a_phone(client):
    css = client.get("/static/styles.css").text
    dock = re.search(r"\.dock-col \{(.*?)\n\}", css, re.S).group(1)
    assert "align-self: flex-start;" in dock and "height: auto;" in dock
    # Under the pinned app header and bundle bar, whose height shell.js
    # keeps in --pin-h.
    assert re.search(r"max-height: calc\(100dvh - var\(--pin-h, 0px\) - 64px\);", dock)
    assert not re.search(r"(?<!max-)height: calc\(100", dock)
    narrow = css[css.index("@media (max-width: 900px) {\n  /* Narrow: the dock"):]
    narrow = narrow[:narrow.index("\n}\n")]
    assert "order: -1" not in narrow


def test_a_short_dock_is_short_and_a_long_one_scrolls_inside(served, served_short):
    with _Browser() as b:
        short = b.page(served_short, 1280).evaluate(MEASURE)
        assert short["height"] < short["winH"] * 0.6, short
        long_ = b.page(served, 1280).evaluate(MEASURE)
        # A stale plan with many findings fills the window, and scrolls inside.
        assert long_["height"] <= long_["winH"], long_
        assert long_["inner"] > long_["shown"], long_
        assert long_["page"] <= 1280


@pytest.mark.parametrize("show_name", ["served", "served_short"])
def test_on_a_phone_the_dock_comes_after_the_content(request, show_name):
    url = request.getfixturevalue(show_name)
    with _Browser() as b:
        m = b.page(url, 390).evaluate(MEASURE)
        assert m["top"] >= m["mainBottom"], m
        assert m["page"] <= 390, m
