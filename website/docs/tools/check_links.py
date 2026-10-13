#!/usr/bin/env python3
"""Check every internal link in a built site: the page exists, and so does
the anchor it names.

    python3 tools/check_links.py dist        (npm run check-links)

Starlight builds a page whatever its links say, so a link to a page or a
heading that is not there would otherwise ship. Exits 1 and lists each one.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])


def parse(path: Path) -> Page:
    p = Page()
    p.feed(path.read_text(encoding="utf-8"))
    return p


def target_file(dist: Path, url_path: str) -> Path | None:
    rel = unquote(url_path).lstrip("/")
    for cand in (dist / rel, dist / rel / "index.html", dist / f"{rel}.html"):
        if cand.is_file():
            return cand
    return None


def main(argv: list[str]) -> int:
    dist = Path(argv[1] if len(argv) > 1 else "dist").resolve()
    pages = {p: parse(p) for p in dist.rglob("*.html")}
    bad = []
    checked = 0
    for path, page in pages.items():
        if path.name == "404.html":
            continue
        for href in page.hrefs:
            parts = urlsplit(href)
            if parts.scheme or parts.netloc or href.startswith(("mailto:", "javascript:")):
                continue
            checked += 1
            if parts.path:
                if not parts.path.startswith("/"):
                    bad.append((path, href, "relative link"))
                    continue
                target = target_file(dist, parts.path)
                if target is None:
                    bad.append((path, href, "no such page"))
                    continue
            else:
                target = path
            if parts.fragment and target.suffix == ".html":
                ids = pages[target].ids if target in pages else parse(target).ids
                if unquote(parts.fragment) not in ids:
                    bad.append((path, href, "no such anchor"))
    for path, href, why in bad:
        print(f"{path.relative_to(dist)}: {href} ({why})")
    print(f"{checked} internal link(s) in {len(pages)} page(s); {len(bad)} broken")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
