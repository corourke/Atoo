"""The screenshot manifest stays runnable.

`tools/doc_screenshots.py` needs a browser, so the suite does not run it.
This checks what can go wrong without one: a manifest that names a show,
a step or a duplicate the script does not know, or a shot whose image is
missing from `docs/user/img/` while SHOTS.md says it was taken.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "doc_screenshots.py"

KNOWN_SHOWS = {"demo", "touringband"}
KNOWN_STEPS = {"click", "check", "fill", "select", "wait", "wait_for", "css", "console"}


def _tool():
    spec = importlib.util.spec_from_file_location("doc_screenshots", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_manifest_names_only_what_the_script_knows():
    tool = _tool()
    shots = tool.load_manifest()  # raises on a duplicate name
    assert shots
    for shot in shots:
        assert shot["show"] in KNOWN_SHOWS, shot["name"]
        assert shot.get("mode", "build") in {"build", "apply", "watch"}, shot["name"]
        assert shot.get("about"), f"{shot['name']} says nothing about what it shows"
        for step in shot.get("steps", []):
            assert len(step) == 1 and set(step) <= KNOWN_STEPS, (shot["name"], step)
        if shot.get("watch"):
            assert {"console": "demo"} in shot.get("steps", []), (
                f"{shot['name']} watches, and only the Demo rig may be watched")


def test_every_shot_recorded_as_taken_is_on_disk():
    tool = _tool()
    record = tool.read_record()
    for shot in tool.load_manifest():
        when = record.get(shot["name"], "")
        if when and not when.startswith(("skipped", "not taken")):
            assert (tool.IMG / f"{shot['name']}.png").exists(), shot["name"]


def test_nothing_that_reaches_a_console_is_let_through():
    tool = _tool()
    for path in ("/api/ping", "/api/apply/run", "/api/patch/run",
                 "/api/amend/run", "/api/undo/run", "/api/build/run"):
        assert path in tool.BLOCKED
