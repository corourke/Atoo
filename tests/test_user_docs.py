"""`docs/user/` cannot quietly rot.

The generated `cli-reference.md` already has a guard
(`tests/test_cli_reference.py`); the hand-written pages beside it had
none, and they are exactly the kind of file WORK_PLAN.md's lesson 1
describes -- one the Python suite has no reason to look at, so nothing
notices when a flag is renamed under a worked example or a page is
linked to before it is written.

Two properties, both cheap:

1. Every relative link between these pages resolves to a file that
   exists. A skeleton page is fine to link to; a missing one is not.
2. Every `atoo ...` invocation in a fenced block is accepted by the
   CLI's own argparse tree. This does not run the commands -- most need a
   console or a model -- but it does mean a renamed or deleted flag fails
   the suite here rather than in front of an engineer at a desk.

What (2) deliberately does NOT check is the *output* under each command.
Mostly nothing in a Python test can: that is what `CLAUDE.md`'s "every
worked example is RUN before it is committed" rule is for, and it stays a
human obligation.

3. The one exception: a transcript run on the Demo show
   (`starter/demo-show/`) or on a frozen copy under `docs/user/demo/`
   needs no console and no model, so it IS run here and its output
   compared. Those copies exist so that rebuilding a show under
   `examples/` cannot make a page wrong; this makes a code change that
   alters the output fail here instead.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
USER_DOCS = REPO / "docs" / "user"

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.S)


def _pages() -> list[Path]:
    pages = sorted(USER_DOCS.glob("*.md"))
    assert pages, f"no pages in {USER_DOCS}"
    return pages


# The pages a visitor lands on before the guide: the repository's front
# page, the package's, and the two community files GitHub links from the
# repository's sidebar. Their links are checked like the guide's
# (docs/user/STYLE.md, "Before you push"), since a broken link on the
# landing page is the first thing a stranger finds.
LANDING_PAGES = [REPO / "README.md", REPO / "atoo" / "README.md",
                 REPO / "CONTRIBUTING.md", REPO / "SECURITY.md"]


def _linked_pages() -> list[Path]:
    return _pages() + LANDING_PAGES


def _page_id(page: Path) -> str:
    return str(page.relative_to(REPO))


@pytest.mark.parametrize("page", _linked_pages(), ids=_page_id)
def test_every_relative_link_resolves(page: Path):
    """A link to a page that does not exist is worse than no link: the
    reader follows it before they find out."""
    broken = []
    for target in LINK_RE.findall(page.read_text()):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        path_part, _, query = path_part.partition("?")
        resolved = (page.parent / path_part).resolve()
        if not resolved.is_relative_to(REPO.parent):
            if not _github_route_exists(resolved, query):
                broken.append(target)
        elif not resolved.exists():
            broken.append(target)
    assert not broken, f"{page.name} links to missing file(s): {broken}"


# GitHub serves a file at /<owner>/<repo>/blob/<branch>/<path>, so a
# relative link that climbs two levels above the repository root lands on
# the repository's own pages: CONTRIBUTING.md's `../../issues/new?...`.
# It survives a rename of the repository, which an absolute URL would not.
# The route is checked against the pages GitHub has, and an issue form's
# template against .github/ISSUE_TEMPLATE/.
GITHUB_ROUTES = {"issues", "issues/new", "discussions", "pulls",
                 "security/advisories/new"}


def _github_route_exists(resolved: Path, query: str) -> bool:
    if not resolved.is_relative_to(REPO.parent.parent):
        return False
    route = resolved.relative_to(REPO.parent.parent).as_posix()
    if route not in GITHUB_ROUTES:
        return False
    params = dict(p.partition("=")[::2] for p in query.split("&") if p)
    template = params.get("template")
    if template is not None:
        return (route == "issues/new" and
                (REPO / ".github" / "ISSUE_TEMPLATE" / template).exists())
    return True


def _invocations(text: str) -> list[str]:
    """Every `atoo ...` command line in a fenced block, with shell
    line continuations joined."""
    found = []
    for lang, body in FENCE_RE.findall(text):
        if lang not in ("bash", "sh", ""):
            continue
        # Join backslash continuations before splitting into lines.
        joined = body.replace("\\\n", " ")
        for line in joined.splitlines():
            line = line.strip()
            if line.startswith("$ "):
                line = line[2:].strip()
            if not line.startswith("atoo "):
                continue
            # A usage synopsis, not an invocation: the generated
            # reference prints `[--out plan.json]` for an optional flag,
            # and argparse has no way to accept its own bracket notation
            # back as arguments.
            if "[" in line or "..." in line:
                continue
            found.append(line)
    return found


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_every_documented_invocation_is_accepted_by_the_cli(page: Path):
    """Parse, do not run. Catches a flag that was renamed out from under
    a worked example -- the drift that made the CLI reference generated
    in the first place."""
    from atoo.cli import build_parser

    for line in _invocations(page.read_text()):
        argv = shlex.split(line, comments=True)[1:]
        parser, _ = build_parser()
        try:
            parser.parse_args(argv)
        except SystemExit:  # argparse prints and exits on a bad flag
            pytest.fail(f"{page.name}: the CLI rejects a documented "
                        f"invocation: {line}")


def test_the_quickstart_names_files_that_exist():
    """Its whole premise is that you can follow it against the frozen
    touring band it copies from `docs/user/demo/`. A renamed file there
    would break that silently."""
    text = (USER_DOCS / "quickstart.md").read_text()
    assert "cp -r docs/user/demo/touringband docs/user/demo/conventions.md" in text
    for named in ("touringband/input.csv", "touringband/plan.json",
                  "touringband/console-after-apply.snap"):
        assert named in text, f"quickstart no longer mentions {named}"
        assert (USER_DOCS / "demo" / named).exists(), (
            f"quickstart names docs/user/demo/{named}, which does not exist")
    assert (USER_DOCS / "demo" / "conventions.md").exists()


def _slug(heading: str) -> str:
    """GitHub's own anchor rule, near enough for these pages: lowercase,
    drop everything that is not a word character, space or hyphen, then
    spaces to hyphens. `## Expansion bays: \x60CRD\x60 and \x60MOD\x60` ->
    `expansion-bays-crd-and-mod`."""
    text = heading.strip().lstrip("#").strip()
    text = text.replace("—", "").replace("–", "")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())


def _anchors(page: Path) -> set[str]:
    return {_slug(line) for line in page.read_text().splitlines()
            if line.startswith("#")}


@pytest.mark.parametrize("page", _linked_pages(), ids=_page_id)
def test_every_anchor_link_resolves(page: Path):
    """A link into a section of another page is exactly as broken as a
    link to a missing page, and rather harder to notice: the browser
    silently lands the reader at the top instead. These pages cross-link
    into each other's sections heavily, so the fragments are checked as
    well as the paths.
    """
    broken = []
    for target in LINK_RE.findall(page.read_text()):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if "#" not in target:
            continue
        path_part, _, fragment = target.partition("#")
        if not fragment:
            continue
        other = page if not path_part else (page.parent / path_part).resolve()
        if other.suffix != ".md" or not other.exists():
            continue
        if fragment not in _anchors(other):
            broken.append(target)
    assert not broken, f"{page.name} links to missing anchor(s): {broken}"


DEMO_RE = re.compile(r"```\n(atoo [^\n]*(?:docs/user/demo/|starter/demo-show)[^\n]*)\n```\n\n```\n(.*?)```", re.S)


def _demo_transcripts() -> list[tuple[str, str, str]]:
    return [(page.name, cmd, out) for page in _pages()
            for cmd, out in DEMO_RE.findall(page.read_text())]


def test_demo_transcripts_exist():
    """Guards the guard: a reshaped fence would make the test below
    parametrize over nothing and pass."""
    names = {name for name, _, _ in _demo_transcripts()}
    assert {"pipeline.md", "applying.md", "show-bundles.md",
            "conventions-reference.md", "reading-findings.md"} <= names


@pytest.mark.parametrize("page,cmd,expected", _demo_transcripts(),
                         ids=[f"{p}:{c.split()[1]}" for p, c, _ in _demo_transcripts()])
def test_every_demo_transcript_matches_its_output(page, cmd, expected,
                                                  capsys, monkeypatch):
    """A transcript over the Demo show or `docs/user/demo/` is printed exactly as the
    command prints it. A line reading `  ...` ends what the page shows;
    everything above it must match the start of the real output."""
    from atoo.cli import main

    monkeypatch.chdir(REPO)
    try:
        main(shlex.split(cmd)[1:])
    except SystemExit:
        pass
    # A page shows what the terminal shows. `apply` prints its gate and
    # its "no reply" line on stderr; `verify` and `lessons` print nothing
    # there, so the two streams cannot interleave in the same transcript.
    captured = capsys.readouterr()
    actual = (captured.out + captured.err).rstrip("\n").splitlines()
    shown = expected.rstrip("\n").splitlines()
    if shown and shown[-1].strip() == "...":
        shown = shown[:-1]
        actual = actual[:len(shown)]
    assert shown == actual, f"{page}: `{cmd}` no longer prints what the page shows"
