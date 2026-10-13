#!/usr/bin/env python3
"""Retake the screenshots in `docs/user/img/`.

The user guide's screenshots are taken by this script rather than by
hand, so any change to the browser UI can be followed by one command
instead of an afternoon of cropping:

    python3 tools/doc_screenshots.py            # every shot
    python3 tools/doc_screenshots.py demo-bar   # just the named ones
    python3 tools/doc_screenshots.py --list     # what the manifest holds

What it holds fixed, so that two runs on the same commit give the same
pictures:

- **The browser:** headless Chromium from `/opt/pw-browsers/chromium`
  (or `--chromium PATH`), dark colour scheme (the look users prefer:
  CLAUDE.md, "Dark is the primary look"), a 1440x900 viewport, and
  a fresh browser context per show, so nothing remembered in one
  viewer's storage leaks into a shot.
- **The clock:** the page's `Date` is fixed at 2026-10-10 19:00 local
  time, so "Updated just now" and the like read the same every time.
- **The home folder:** every `atoo ui` runs on a new temporary
  `HOME`, deleted afterwards. The real `~/.atoo.config` and
  `~/Documents` are never read or written.
- **The shows:** only data that ships in the repo. `demo` is the
  packaged Demo show; `touringband` is the frozen copy under
  `docs/user/demo/touringband/`, copied into the temporary home's
  working folder after `atoo init`, so paths on screen read
  `~/Documents/Atoo/...`.

What it refuses to do: **nothing in a shot is allowed to reach a
console.** The address set for the `touringband` shots (`192.0.2.16`) is
only typed into the bar; every request that would contact it (Ping, a
preview, an apply, a patch, an undo, a live watch) and every build is
aborted in the browser before it leaves the page. A Watch shot runs on
the Demo rig, which is simulated, and so does a `preview` shot (Issue
#647): on the `demo` show only, an Apply or Patch request that carries no
`confirm` is let through, and it reads the Demo's simulated WING on
localhost. Anything with `confirm` is still aborted, and the server
refuses a Demo write regardless.

**The Demo rig is seeded.** Its faults come from a `random.Random()`
(`atoo/webui.py`, `demo_provider_factory`) that this script seeds
through `ATOO_DEMO_SEED`, so a Watch shot shows the same faults on
every run. A Watch shot presses **Stop** before it is taken, because a
row that has just cleared is still closing up for a third of a second.

Each run rewrites `docs/user/img/SHOTS.md`: one row per shot with the
commit it was taken at, so a reader of the guide can tell how old a
picture is. A dirty working tree is recorded as such.

Needs the `ui` extra and Playwright (`pip install playwright`; the
browser binary is the one already on the machine -- this script never
runs `playwright install`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
IMG = REPO / "docs" / "user" / "img"
MANIFEST = Path(__file__).with_suffix(".json")
DEFAULT_CHROMIUM = "/opt/pw-browsers/chromium"
VIEWPORT = {"width": 1440, "height": 900}
FIXED_TIME = dt.datetime(2026, 10, 10, 19, 0, 0)
PLACEHOLDER_CONSOLE = "192.0.2.16"
SEED_ENV = "ATOO_DEMO_SEED"
SEED = "1"

# Every endpoint that reaches a console or runs a model. Aborted in the
# browser for every shot; /api/watch/start is let through only for a
# shot on the Demo rig.
BLOCKED = (
    "/api/ping", "/api/apply/run", "/api/patch/run", "/api/amend/run",
    "/api/undo/run", "/api/build/run", "/api/patch/promote",
)
WATCH_START = "/api/watch/start"

# Variables that would point a build at a model. Removed from the
# server's environment: no shot needs one, and a key must never be read.
MODEL_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ATOO_AI_API_KEY",
             "ATOO_AI_PROVIDER", "ATOO_AI_BASE_URL", "OPENAI_API_KEY")


def load_manifest() -> list[dict]:
    shots = json.loads(MANIFEST.read_text())["shots"]
    names = [s["name"] for s in shots]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise SystemExit(f"{MANIFEST.name}: duplicate shot names {sorted(dupes)}")
    return shots


def git_commit() -> str:
    def git(*args):
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    sha = git("rev-parse", "--short=12", "HEAD")
    dirty = git("status", "--porcelain", "--", "atoo")
    return sha + (" (+ uncommitted changes under atoo/)" if dirty else "")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def prepare_home(show: str, home: Path) -> list[str]:
    """Set up a temporary HOME for one show. Returns the extra `ui`
    arguments that open it."""
    if show == "demo":
        return []
    if show == "touringband":
        run_cli(["init"], home)
        bundle = home / "Documents" / "Atoo" / "touringband"
        shutil.copytree(REPO / "docs" / "user" / "demo" / "touringband", bundle)
        # The conventions this plan was built from, not init's starter
        # file: otherwise the page reads the plan as older than its
        # inputs and the shots carry a warning a reader's own build
        # would not.
        shutil.copy(REPO / "docs" / "user" / "demo" / "conventions.md",
                    home / "Documents" / "Atoo" / "conventions.md")
        return ["--show", str(bundle)]
    raise SystemExit(f"unknown show {show!r} in {MANIFEST.name}")


def server_env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in MODEL_ENV}
    env.pop("ATOO_CONSOLE", None)
    env.update(HOME=str(home), PYTHONPATH=str(REPO))
    env[SEED_ENV] = SEED
    return env


def run_cli(args: list[str], home: Path) -> None:
    subprocess.run([sys.executable, "-c",
                    "import sys; from atoo.cli import main; sys.exit(main())",
                    *args], env=server_env(home), cwd=home, check=True,
                   capture_output=True)


@contextmanager
def ui_server(show: str):
    home = Path(tempfile.mkdtemp(prefix="atoo-shots-"))
    proc = None
    try:
        extra = prepare_home(show, home)
        port = free_port()
        proc = subprocess.Popen(
            [sys.executable, "-c",
             "import sys; from atoo.cli import main; sys.exit(main())",
             "ui", "--no-browser", "--port", str(port), *extra],
            env=server_env(home), cwd=home,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        url = f"http://127.0.0.1:{port}/"
        for _ in range(100):
            if proc.poll() is not None:
                raise SystemExit(f"atoo ui exited:\n{proc.stdout.read()}")
            try:
                urllib.request.urlopen(url, timeout=0.5)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise SystemExit("atoo ui did not answer within 10s")
        yield url
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(home, ignore_errors=True)


PREVIEWS = ("/api/apply/run", "/api/patch/run")


def guard(page, allow_watch: bool, allow_preview: bool = False) -> None:
    """Abort, in the browser, every request that could reach a console
    or run a model. The server is never asked. `allow_preview` lets a
    Demo show's unconfirmed preview through -- see the module docstring."""
    def handle(route):
        path = route.request.url.split("?", 1)[0]
        if allow_preview and any(path.endswith(p) for p in PREVIEWS):
            try:
                body = json.loads(route.request.post_data or "{}")
            except ValueError:
                body = {"confirm": True}
            if not body.get("confirm"):
                return route.continue_()
        if any(path.endswith(b) for b in BLOCKED):
            return route.abort()
        if path.endswith(WATCH_START) and not allow_watch:
            return route.abort()
        return route.continue_()
    page.route("**/api/**", handle)


def do_step(page, step: dict) -> None:
    kind, arg = next(iter(step.items()))
    if kind == "click":
        page.click(arg)
    elif kind == "check":
        page.check(arg)
    elif kind == "fill":
        page.fill(arg[0], arg[1])
    elif kind == "select":
        page.select_option(arg[0], arg[1])
    elif kind == "wait":
        page.wait_for_timeout(int(arg))
    elif kind == "wait_for":
        page.wait_for_selector(arg, state="visible")
    elif kind == "css":
        # Page-level style for the shot only, e.g. to unstick a sticky
        # header that would otherwise sit over an element screenshot.
        page.add_style_tag(content=arg)
    elif kind == "console":
        # Type an address into the bar, or choose the Demo rig.
        page.click("#console-change-btn")
        if arg == "demo":
            page.check("#console-kind-demo")
            page.click("#console-set-btn")
            # The Demo's box opens once; a shot of it opens
            # it again from the bar's chip.
            page.wait_for_timeout(1500)
            close_demo_popup(page)
            return
        else:
            page.check("#console-kind-desk")
            page.fill("#console-edit-address", PLACEHOLDER_CONSOLE)
        page.click("#console-set-btn")
        page.wait_for_timeout(1500)
    else:
        raise SystemExit(f"unknown step {kind!r}")


def close_demo_popup(page) -> None:
    """The Demo show's box opens once per browser: close it
    if it is up, so it is not over the shot."""
    if page.is_visible("#demo-popup"):
        page.click("#demo-popup [data-popup-close]")
        page.wait_for_selector("#popup-scrim", state="hidden")


def take(browser, url: str, shot: dict) -> None:
    ctx = browser.new_context(viewport=VIEWPORT, color_scheme="dark",
                              device_scale_factor=1)
    page = ctx.new_page()
    page.clock.set_fixed_time(FIXED_TIME)
    guard(page, allow_watch=shot.get("watch", False),
          allow_preview=bool(shot.get("preview")) and shot["show"] == "demo")
    page.goto(url + "#" + shot.get("mode", "build"))
    page.wait_for_timeout(1500)
    close_demo_popup(page)
    for step in shot.get("steps", []):
        do_step(page, step)
    page.wait_for_timeout(500)
    out = IMG / f"{shot['name']}.png"
    target = shot.get("target")
    if target:
        page.locator(target).first.screenshot(path=str(out))
    else:
        page.screenshot(path=str(out), full_page=False)
    ctx.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="shots to take (default: all)")
    ap.add_argument("--list", action="store_true", help="list the manifest and stop")
    ap.add_argument("--chromium", default=DEFAULT_CHROMIUM, help="the browser binary")
    args = ap.parse_args(argv)

    shots = load_manifest()
    if args.list:
        for s in shots:
            print(f"{s['name']:<24} {s['show']:<12} {s['about']}")
        return 0
    unknown = set(args.names) - {s["name"] for s in shots}
    if unknown:
        raise SystemExit(f"not in the manifest: {sorted(unknown)}")
    chosen = [s for s in shots if not args.names or s["name"] in args.names]

    from playwright.sync_api import sync_playwright

    IMG.mkdir(parents=True, exist_ok=True)
    commit = git_commit()
    results: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chromium)
        for show in dict.fromkeys(s["show"] for s in chosen):
            with ui_server(show) as url:
                for shot in (s for s in chosen if s["show"] == show):
                    take(browser, url, shot)
                    results[shot["name"]] = "taken"
                    print(f"took  {shot['name']}.png")
        browser.close()

    # A partial run keeps the other shots' rows as they were.
    previous = read_record()
    rows = []
    for shot in shots:
        name = shot["name"]
        if results.get(name) == "taken":
            rows.append((shot, commit))
        elif name in results:
            rows.append((shot, results[name]))
        else:
            rows.append((shot, previous.get(name, "not taken yet")))
    write_record(rows)
    return 0


RECORD_HEAD = [
    "# Screenshots",
    "",
    "Taken by `tools/doc_screenshots.py` from the manifest",
    "`tools/doc_screenshots.json`. Do not edit the images by hand: change",
    "the manifest or the UI, and run the script again. This file is",
    "rewritten on every run; a shot the run did not take keeps its row.",
    "",
    "| Shot | Show | What it shows | Taken at |",
    "|---|---|---|---|",
]


def read_record() -> dict[str, str]:
    """{shot name: its "Taken at" cell} from the current SHOTS.md."""
    record = IMG / "SHOTS.md"
    found = {}
    if record.exists():
        for line in record.read_text().splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 4 and ".png`" in cells[0]:
                found[cells[0].split("`")[1][:-len(".png")]] = cells[3]
    return found


def write_record(rows: list[tuple[dict, str]]) -> None:
    lines = list(RECORD_HEAD)
    for shot, when in rows:
        name = shot["name"]
        taken = (IMG / f"{name}.png").exists() and not when.startswith(("skipped", "not taken"))
        cell = f"[`{name}.png`]({name}.png)" if taken else f"`{name}.png`"
        lines.append(f"| {cell} | {shot['show']} | {shot['about']} | {when} |")
    (IMG / "SHOTS.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
