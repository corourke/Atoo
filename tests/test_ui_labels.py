"""One name for each thing, as the UI says it.

The docs follow the UI's labels; these pin the places the code itself
used a second word for the same thing. Most of them live in
`atoo/web/static/`, which the rest of the suite cannot see, so they
are asserted on the served assets, as `tests/test_webui.py` does.
"""

from __future__ import annotations

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.cli import UI_DESCRIPTION, build_parser  # noqa: E402
from atoo.webui import create_app  # noqa: E402


@pytest.fixture(scope="module")
def assets():
    with fastapi_testclient.TestClient(create_app()) as c:
        return {name: c.get("/static/" + name).text
                for name in ("shell.html", "shell.js", "setup.js", "watch.js")}


def test_the_findings_panel_has_one_name(assets):
    """The heading is Findings. Sentences name it "the Findings panel";
    a jump link names the heading ("in Findings →", as Apply's do).
    Nothing the page shows calls it the dock."""
    html, shell, setup = assets["shell.html"], assets["shell.js"], assets["setup.js"]
    assert 'aria-label="Collapse the Findings panel"' in html
    assert "Collapse findings dock" not in html
    assert '"Listed in the Findings panel"' in shell
    assert "the finding in the Findings panel names the " in shell
    assert '"in Findings →"' in setup
    for text in (shell, setup):
        assert "findings panel" not in text  # lower-case: the heading is capitalised
        assert "the finding in the dock" not in text
        assert "findings in the dock: " not in text  # a column title
        assert "findings in the dock; " not in text  # a help popover


def test_history_not_journal_stack_in_the_stale_page_message(assets):
    assert "The plan, pre-flight, History and runs on this page" in assets["shell.js"]
    assert "journal stack and runs" not in assets["shell.js"]


def test_start_watching_is_named_as_the_button_says(assets):
    assert ">Start watching</button>" in assets["shell.html"]
    watch = assets["watch.js"]
    assert "Press Start watching." in watch
    assert "Start Watching" not in watch
    assert "then Start watching." in watch
    assert "Stop, then Start watching, to watch" in watch


def test_the_plan_tile_says_stale_once(assets):
    """The 04 tile's badge says Stale; the badge beside Rebuild plan on
    the same tile no longer says it a second way ("Plan stale")."""
    setup = assets["setup.js"]
    assert '["Stale", "is-warn"]' in setup
    assert "Plan stale" not in setup
    assert '&& f.state !== "stale"' in setup


def test_ui_help_uses_the_page_labels():
    text = UI_DESCRIPTION
    assert "Ping, Apply, Patch, Undo and Watch" in text
    assert "Amend" not in text
    assert "rules editor" not in text
    assert "Watch conditions" in text
    assert "findings dock" not in text and "in the dock" not in text
    assert "the Findings panel: the one place findings are listed" in text
    assert "..." not in text.replace("`", "")
    assert "Change…" in text and "New show…" in text
    ui = build_parser()[1]["ui"]
    host = next(a for a in ui._actions if "--host" in a.option_strings).help
    assert "Setup write" not in host and "every write from the page" in host
    wc = next(a for a in ui._actions if "--watch-conditions" in a.option_strings).help
    assert "rules editor" not in wc and "Watch conditions" in wc


def test_build_output_says_watch_conditions_not_watchlist():
    """`build`'s own lines are asserted on their real output in
    tests/test_watchlist_draft.py. What stays "watchlist" on purpose: the
    ATOO_AI_WATCHLIST_* variables and the call's role name beside
    them, until the product rename renames every ATOO_* variable at
    once; and the finding code `build.watchlist-drafted`, an identifier."""
    from atoo.ai_provider import ROLE_MODEL_ENV
    assert ROLE_MODEL_ENV["watchlist"] == "ATOO_AI_WATCHLIST_MODEL"
