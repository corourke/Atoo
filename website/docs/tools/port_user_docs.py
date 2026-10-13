#!/usr/bin/env python3
"""Port the user guide into this Starlight site, one way.

    python3 tools/port_user_docs.py <path to docs/user in the development repo>

The source of truth is `docs/user/` in the development repository, beside
the code, where its worked examples are re-run by the test suite; each
release converts it into this site (Cameron, 2026-10-13). This script is
that conversion. It copies the pages here, every run from scratch, so a
page is never edited in this site:

* each page lands in its section's directory (SECTIONS below), with
  Starlight frontmatter: its H1 becomes `title`, its first paragraph
  `description`, and its place in SECTIONS `sidebar.order`;
* a link to another page becomes the site's own URL, keeping its anchor;
  an image is served from src/assets/img/; a link that leaves the user
  guide (developer docs, the repository's own files) keeps its text and
  loses the link, and is listed when the port ends;
* docs/user/README.md becomes the site's front page, and STYLE.md (the
  rules the pages are written to) is not a page.

Every link to a page that does not exist stops the port, so a page added
to docs/user/ without a place in SECTIONS cannot be silently dropped.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # website/docs
CONTENT = HERE / "src" / "content" / "docs"
ASSETS = HERE / "src" / "assets" / "img"

# Section directory -> its pages, in sidebar order. The sections follow the
# app's own areas.
SECTIONS: dict[str, list[str]] = {
    "getting-started": [
        "why", "install", "configuration", "demo", "quickstart",
        "testing-on-your-desk", "install-from-checkout",
    ],
    "build": [
        "build-a-show", "input-lists", "conventions", "conventions-reference",
        "extra-strips", "presets", "bus-presets", "show-bundles",
        "reading-findings", "pipeline", "lessons",
    ],
    "apply": [
        "apply-to-desk", "applying", "what-apply-changes", "journals", "undo",
        "two-desks",
    ],
    "watch": ["watch-a-show", "watch-conditions", "watch", "audit"],
    "patch": ["patch-a-show", "patch", "amend"],
    "troubleshooting": [
        "troubleshooting", "troubleshooting-build", "troubleshooting-verify",
        "troubleshooting-desk", "troubleshooting-audit", "troubleshooting-ui",
    ],
    "reference": ["cli-reference", "glossary", "limitations", "faq"],
}

# Pages kept out of production builds (`draft: true`): shown by `npm run dev`.
# None today: install-from-checkout is linked from published pages, and a
# link into a draft is a broken link in production.
DRAFTS: set[str] = set()

NOT_PAGES = {"STYLE"}

PAGE_OF = {page: section for section, pages in SECTIONS.items() for page in pages}

LINK = re.compile(r"(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)\)")


def slug(heading: str) -> str:
    """GitHub's (and Starlight's) heading id."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def url_of(page: str) -> str:
    if page == "README":
        return "/"
    return f"/{PAGE_OF[page]}/{page}/"


def split_title(text: str, name: str) -> tuple[str, str]:
    """The page's H1, as plain text, and the body without it."""
    # The generated reference opens with a comment that itself quotes
    # "<!-- ... -->"; everything before the H1 is header, not page.
    m = re.search(r"^# (.+)$", text, flags=re.M)
    if not m:
        raise SystemExit(f"{name}.md has no '# ' title")
    title = m.group(1).replace("`", "").strip()
    head = text[: m.start()]
    if head.strip() and not head.lstrip().startswith("<!--"):
        raise SystemExit(f"{name}.md has text before its title")
    body = text[m.end():]
    return title, body.lstrip("\n")


def plain(md: str) -> str:
    md = LINK.sub(lambda m: m.group(2), md)
    md = re.sub(r"[*_`]", "", md)
    return " ".join(md.split())


def description(body: str) -> str:
    in_fence = False
    para: list[str] = []
    for line in body.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        s = line.strip()
        if not s:
            if para:
                break
            continue
        if s.startswith(("#", "|", "!", "<", ">", "-", "*", "1.")) and not para:
            continue
        para.append(s)
    text = plain(" ".join(para))
    if len(text) > 200:
        cut = text[:200].rsplit(" ", 1)[0]
        text = cut.rstrip(",;:") + "…"
    return text


def yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Port:
    def __init__(self, src: Path):
        self.src = src
        self.unlinked: list[tuple[str, str]] = []
        # A page's H1 becomes its title, so a link to the H1's anchor is a
        # link to the top of the page.
        self.title_slug = {}
        for p in src.glob("*.md"):
            m = re.search(r"^# (.+)$", p.read_text(encoding="utf-8"), flags=re.M)
            if m:
                self.title_slug[p.stem] = slug(m.group(1))

    def rewrite_links(self, body: str, name: str, depth: int) -> str:
        up = "../" * depth

        def fix(m: re.Match) -> str:
            bang, label, target = m.groups()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                return m.group(0)
            if bang:
                if not target.startswith("img/"):
                    raise SystemExit(f"{name}.md: image outside img/: {target}")
                return f"![{label}]({up}assets/{target})"
            path, _, anchor = target.partition("#")
            if "/" not in path and path.endswith(".md"):
                page = path[:-3]
                if page in NOT_PAGES:
                    self.unlinked.append((name, target))
                    return label
                if page not in PAGE_OF and page != "README":
                    raise SystemExit(f"{name}.md links to {target}, which has no "
                                     "place in SECTIONS")
                if anchor and anchor == self.title_slug.get(page):
                    anchor = ""
                if page == "README" and "README.md" in label:
                    label = "the front page"
                return f"[{label}]({url_of(page)}{'#' + anchor if anchor else ''})"
            self.unlinked.append((name, target))
            return label

        return LINK.sub(fix, body)

    def page(self, name: str, out: Path, depth: int, front: dict) -> None:
        raw = (self.src / f"{name}.md").read_text(encoding="utf-8")
        title, body = split_title(raw, name)
        if name == "README":
            # The front page is for readers; the section for the pages'
            # writers points into the development repository.
            body = re.sub(r"^## For whoever writes these pages\n.*?(?=^## |\Z)", "",
                          body, flags=re.S | re.M)
        body = self.rewrite_links(body, name, depth)
        lines = ["---", f"title: {yaml_str(title)}"]
        desc = description(body)
        if desc:
            lines.append(f"description: {yaml_str(desc)}")
        for key, value in front.items():
            lines.append(f"{key}: {value}")
        lines += ["---", "",
                  f"<!-- Generated from docs/user/{name}.md by tools/port_user_docs.py."
                  " Edit it there, then re-run the port. -->", ""]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + body.rstrip() + "\n", encoding="utf-8")

    def run(self) -> None:
        found = {p.stem for p in self.src.glob("*.md")} - NOT_PAGES - {"README"}
        missing = found - set(PAGE_OF)
        if missing:
            raise SystemExit(f"pages with no place in SECTIONS: {sorted(missing)}")
        gone = set(PAGE_OF) - found
        if gone:
            raise SystemExit(f"SECTIONS names pages that do not exist: {sorted(gone)}")

        if CONTENT.exists():
            shutil.rmtree(CONTENT)
        if ASSETS.exists():
            shutil.rmtree(ASSETS)
        shutil.copytree(self.src / "img", ASSETS,
                        ignore=shutil.ignore_patterns("*.md", "*.json", "*.txt"))

        self.page("README", CONTENT / "index.md", 2, {})
        for section, pages in SECTIONS.items():
            for order, name in enumerate(pages, start=1):
                front = {"sidebar": f"\n  order: {order}"}
                if name in DRAFTS:
                    front["draft"] = "true"
                self.page(name, CONTENT / section / f"{name}.md", 3, front)

        print(f"ported {len(found) + 1} pages and {len(list(ASSETS.iterdir()))} "
              f"images from {self.src}")
        if self.unlinked:
            print(f"{len(self.unlinked)} link(s) leave the user guide and were "
                  "kept as text:")
            for name, target in self.unlinked:
                print(f"  {name}.md -> {target}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    src = Path(argv[1]).resolve()
    if not (src / "README.md").is_file():
        print(f"{src} does not look like docs/user/ (no README.md)", file=sys.stderr)
        return 2
    Port(src).run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
