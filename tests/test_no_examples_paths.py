"""Nothing a user reads points into `examples/`.

The public repository does not carry `examples/`: those are the
maintainer's live show files (`docs/product/public-repo-manifest.md`). A
worked example, a `--help` line or an error message that names
`examples/...` sends a visitor to a file that is not there. So this fails
on any `examples/` path in:

- the CLI's `--help`, for the root parser and every subcommand (and so in
  the generated `docs/user/cli-reference.md`);
- `docs/user/*.md`, apart from the pages in `PENDING_PAGES`;
- the repository's `README.md`;
- the package itself: every `.py` file under `atoo/` (code,
  docstrings, defaults and comments alike) and the text it ships
  (`prompts/`, `domain/`, `web/`), plus `starter/`.

A path into the private archive (`archive/examples/...`) is not matched:
code comments cite desk evidence there, and the manifest allows that.
Nor is a name that merely ends in `examples/` (`docs/user/demo/...` is
fine; `my-examples/` is not this directory).

`PENDING_PAGES` is the Docs Lead's half: pages still to be
moved onto the Demo show or `docs/user/demo/`. Take a page off it in the
PR that cleans it. A listed page that is already clean fails too, so the
list cannot outlive its reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
USER_DOCS = REPO / "docs" / "user"

# Pages Dana (Docs Lead) is still moving off `examples/`.
# Shrinks to empty as her PRs land.
PENDING_PAGES: set[str] = set()

_CANDIDATE = re.compile(r"examples/")


def examples_paths(text: str) -> list[str]:
    """Each line of `text` that names a path into `examples/`.

    A match counts when `examples/` starts a path (start of text, after a
    space, quote, backtick or bracket) or follows `../`. It does not count
    after a letter, digit, `-`, `.` or `_` (another name that ends in
    "examples"), nor after any other `/` (`archive/examples/`, which is
    private evidence and stays where code comments cite it)."""
    hits = []
    for line in text.splitlines():
        for m in _CANDIDATE.finditer(line):
            before = line[:m.start()]
            if before and (before[-1].isalnum() or before[-1] in "-._"):
                continue
            if before.endswith("/") and not before.endswith("../"):
                continue
            hits.append(line.strip())
            break
    return hits


def test_the_matcher():
    """Guards the guard."""
    assert examples_paths("see examples/README.md")
    assert examples_paths("`examples/conventions.md`")
    assert examples_paths("(../examples/smallband)")
    assert examples_paths("examples/festival")
    assert not examples_paths("archive/examples/console-runs/A1-raw.log")
    assert not examples_paths("tests/fixtures/examples-conventions.md")
    assert not examples_paths("docs/user/demo/audit-demo/audit_demo_state.json")
    assert not examples_paths("my-examples/x")


def test_help_names_no_examples_path():
    """Every `--help` page, root and subcommands. `cli-reference.md` is
    generated from exactly this, so it is covered too."""
    from atoo.cli import build_parser

    root, subparsers = build_parser()
    found = {}
    for name, parser in {"atoo": root, **subparsers}.items():
        hits = examples_paths(parser.format_help())
        if hits:
            found[name] = hits
    assert not found, f"--help points into examples/: {found}"


def test_argparse_defaults_name_no_examples_path():
    from atoo.cli import build_parser

    _root, subparsers = build_parser()
    found = []
    for name, parser in subparsers.items():
        for action in parser._actions:
            if isinstance(action.default, str) and examples_paths(action.default):
                found.append(f"{name} {action.dest}={action.default!r}")
    assert not found, f"a default path points into examples/: {found}"


def _user_pages() -> list[Path]:
    pages = sorted(USER_DOCS.glob("*.md"))
    assert pages
    return pages


@pytest.mark.parametrize("page", _user_pages(), ids=lambda p: p.name)
def test_user_page_names_no_examples_path(page: Path):
    hits = examples_paths(page.read_text(encoding="utf-8"))
    if page.name in PENDING_PAGES:
        assert hits, (f"{page.name} no longer mentions examples/ -- take it "
                      f"off PENDING_PAGES in {Path(__file__).name}")
        return
    assert not hits, f"{page.name} points into examples/: {hits}"


def test_pending_pages_exist():
    missing = [p for p in PENDING_PAGES if not (USER_DOCS / p).exists()]
    assert not missing, f"PENDING_PAGES names pages that do not exist: {missing}"


def test_readme_names_no_examples_path():
    hits = examples_paths((REPO / "README.md").read_text(encoding="utf-8"))
    assert not hits, f"README.md points into examples/: {hits}"


def _package_files() -> list[Path]:
    pkg = REPO / "atoo"
    files = list(pkg.rglob("*.py"))
    for sub in ("prompts", "domain", "web"):
        files += [p for p in (pkg / sub).rglob("*")
                  if p.is_file() and p.suffix in (".md", ".txt", ".js", ".html", ".css")]
    files += [p for p in (REPO / "starter").rglob("*")
              if p.is_file() and p.suffix in (".md", ".txt", ".csv", ".json")]
    return sorted(files)


def test_package_names_no_examples_path():
    """The package and the starter set are what a pipx install carries.
    A user-facing message, a default or a docstring that names
    `examples/` names a folder the installed tool has never had."""
    found = {}
    for path in _package_files():
        hits = examples_paths(path.read_text(encoding="utf-8"))
        if hits:
            found[str(path.relative_to(REPO))] = hits
    assert not found, f"the package points into examples/: {found}"
