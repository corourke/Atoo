#!/usr/bin/env python3
"""The public repository's scrub check.

`docs/product/public-repo-manifest.md`, "The scrub check", lists what must
not reach the public tree. This script looks for it, so the check can be
run again on every tree that is about to be carried over, not done once by
eye:

- **home-path**: a macOS or Windows home directory (`/Users/<name>`,
  `C:\\Users\\<name>`), or a Linux one other than a neutral placeholder
  (`/home/user/`, which the scrubbed fixtures use, `/home/you/`,
  `/home/me/`, `/home/username/`);
- **name**: the maintainer's first name, except on a copyright or credit
  line (the allowlist below);
- **private-ip**: an RFC 1918 address (10/8, 172.16/12, 192.168/16).
  Documentation addresses (192.0.2.x, RFC 5737) are what scrubbed files
  use instead and are never reported;
- **serial**: a desk serial number (four digits, three letters or digits,
  four digits, three letters), a desk's hardware-derived name
  (`WING-PP-<digits>`), or a `creator_sn` value that is not a placeholder;
- **deny-name**: a band, venue, client or person's name from the deny
  list, `scrub_denylist.txt` next to this script (or `--deny-list`);
- **chn**: a WING channel preset (`.chn`) outside the maintainer's own
  set. The manifest carries only that set: `starter/presets/`
  and its frozen copies under `tests/fixtures/` (`OWN_PRESET_DIRS`). Any
  other `.chn` is reported, once per file, as its own category. A `.chn`
  in one of those folders is still checked for everything else, so a
  desk's own name left in `creator_name` is a **serial** hit.

Every hit is printed as `path:line: category: matched text`, then a
summary by top-level directory. The exit status is 1 if anything was
found, 0 if nothing was, and 2 on a usage error.

    python3 tools/scrub_check.py              # the whole repository
    python3 tools/scrub_check.py tests/fixtures
    python3 tools/scrub_check.py --category private-ip --category serial

The deny list itself names what was scrubbed, so it is the one file the
check never reports on; it stays in the private repository (see the
manifest). Without it the deny-name category is skipped, with a warning.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DENY_LIST = Path(__file__).resolve().parent / "scrub_denylist.txt"

# Directories that are never part of a carried tree.
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv",
             "venv", ".mypy_cache", ".ruff_cache", "build", "dist"}

# The maintainer's first name, split so this file does not report itself.
NAME = "came" + "ron"

# The maintainer's own preset set and its frozen test copies:
# the only `.chn` files the public tree carries, so the only ones the chn
# category does not report.
OWN_PRESET_DIRS = tuple(REPO_ROOT / d for d in (
    "starter/presets",
    "tests/fixtures/presets",
    "tests/fixtures/channel_presets",
))

CATEGORIES = ("home-path", "name", "private-ip", "serial", "deny-name", "chn")

HOME_PATH = re.compile(
    r"/User" r"s/[^/\s\"'`<>)\]]+"
    r"|[A-Za-z]:\\\\?Users\\\\?[^\\\s\"'`<>]+"
    r"|/home/(?!(?:user|you|me|username)(?![A-Za-z0-9._-]))[A-Za-z0-9._-]+"
)

NAME_RE = re.compile(NAME, re.IGNORECASE)

# A line naming the maintainer is fine when it is the copyright line or a
# credit: the licence header, `pyproject.toml`'s authors, and the README
# footer that credits him and links Act4Audio (the manifest).
NAME_ALLOWED_LINE = re.compile(
    r"copyright|\u00a9|\(c\)\s*\d{4}|\bauthors?\s*=|\bcredits?\b|act4audio",
    re.IGNORECASE,
)

_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
PRIVATE_IP = re.compile(
    r"(?<![\d.])(?:"
    rf"10\.{_OCTET}\.{_OCTET}\.{_OCTET}"
    rf"|192\.168\.{_OCTET}\.{_OCTET}"
    rf"|172\.(?:1[6-9]|2\d|3[01])\.{_OCTET}\.{_OCTET}"
    r")(?!\.?\d)"
)

SERIAL_PATTERNS = (
    # The serial a WING states on `/?`: four digits, three letters or
    # digits, four digits, three letters.
    re.compile(r"(?<![A-Za-z0-9])\d{4}[A-Z0-9]{3}\d{4}[A-Z]{3}(?![A-Za-z0-9])"),
    # A desk's default name is derived from its hardware: WING-PP-<digits>.
    re.compile(r"WING-[A-Z]{2,4}-\d{6,}"),
    # A preset or snapshot's creator serial.
    re.compile(r"\"creator_sn\"\s*:\s*\"(?!NO_SERIAL\"|SERIAL)[^\"]+\""),
)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    category: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.category}: {self.text}"


def load_deny_list(path: Path) -> list[str]:
    """One name per line; `#` starts a comment; blank lines are ignored."""
    names = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        name = raw.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def deny_pattern(names: list[str]) -> re.Pattern | None:
    """Each name matched without regard to case, and only as a whole word:
    a name that is part of a longer word (`Dorn` in `Dornberg`) is not it."""
    if not names:
        return None
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9])", re.IGNORECASE)


def iter_files(paths: list[Path], exempt: set[Path]):
    for root in paths:
        if root.is_file():
            if root.resolve() not in exempt:
                yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in SKIP_DIRS and not d.endswith(".egg-info"))
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if path.resolve() not in exempt:
                    yield path


def scan_text(text: str, display: str, deny: re.Pattern | None,
              categories: set[str]) -> list[Hit]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        found = []
        if "home-path" in categories:
            found += [("home-path", m) for m in HOME_PATH.finditer(line)]
        if "name" in categories and not NAME_ALLOWED_LINE.search(line):
            # A name inside a home path is reported once, as the path.
            in_paths = [m.span() for m in HOME_PATH.finditer(line)]
            found += [("name", m) for m in NAME_RE.finditer(line)
                      if not any(a <= m.start() < b for a, b in in_paths)]
        if "private-ip" in categories:
            found += [("private-ip", m) for m in PRIVATE_IP.finditer(line)]
        if "serial" in categories:
            for pattern in SERIAL_PATTERNS:
                found += [("serial", m) for m in pattern.finditer(line)]
        if deny is not None and "deny-name" in categories:
            found += [("deny-name", m) for m in deny.finditer(line)]
        found.sort(key=lambda cm: (cm[1].start(), cm[0]))
        for category, match in found:
            hits.append(Hit(display, lineno, category, match.group(0)[:120]))
    return hits


def scan_file(path: Path, display: str, deny: re.Pattern | None,
              categories: set[str], own_presets: tuple[Path, ...] = OWN_PRESET_DIRS) -> list[Hit]:
    hits = []
    if ("chn" in categories and path.suffix.lower() == ".chn"
            and path.resolve().parent not in {d.resolve() for d in own_presets}):
        hits.append(Hit(display, 0, "chn",
                        "WING channel preset outside the maintainer's own set"))
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"scrub_check: cannot read {display}: {exc}", file=sys.stderr)
        return hits
    # A binary file is read byte for byte (latin-1), so a path or an
    # address stored in it as text is still found.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    hits += scan_text(text, display, deny, categories)
    return hits


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def top_level(display: str) -> str:
    if display.startswith("/"):
        return "(outside the repository)"
    head, sep, _ = display.partition("/")
    return head + "/" if sep else "(root)"


def run(paths: list[Path], deny_list: Path | None, categories: set[str],
        base: Path = REPO_ROOT, out=None, err=None,
        own_presets: tuple[Path, ...] = OWN_PRESET_DIRS) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    exempt = set()
    deny = None
    if "deny-name" in categories:
        if deny_list is not None and deny_list.is_file():
            exempt.add(deny_list.resolve())
            deny = deny_pattern(load_deny_list(deny_list))
        else:
            print(f"scrub_check: no deny list at {deny_list}; band, venue and client "
                  "names are not checked", file=err)
    hits: list[Hit] = []
    for path in iter_files(paths, exempt):
        hits += scan_file(path, display_path(path, base), deny, categories, own_presets)
    for hit in hits:
        print(hit, file=out)
    if hits:
        print("", file=out)
        print(f"{len(hits)} hit(s). By top-level directory and category:", file=out)
        by_dir: dict[str, Counter] = {}
        for hit in hits:
            by_dir.setdefault(top_level(hit.path), Counter())[hit.category] += 1
        for directory in sorted(by_dir):
            counts = by_dir[directory]
            detail = ", ".join(f"{c} {counts[c]}" for c in CATEGORIES if counts[c])
            print(f"  {directory:<24} {sum(counts.values()):>6}  ({detail})", file=out)
        return 1
    print("scrub check: clean", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report home paths, the maintainer's name, private addresses, desk "
                    "serials, deny-listed names and .chn presets other than the maintainer's own set in a tree that is to "
                    "go public (docs/product/public-repo-manifest.md, 'The scrub check').")
    parser.add_argument("paths", nargs="*", type=Path,
                        help="files or directories to check (default: the repository)")
    parser.add_argument("--deny-list", type=Path, default=DEFAULT_DENY_LIST,
                        help="band, venue, client and people's names, one per line "
                             "(default: tools/scrub_denylist.txt)")
    parser.add_argument("--category", action="append", choices=CATEGORIES,
                        help="check only this category (repeatable; default: all)")
    args = parser.parse_args(argv)
    paths = args.paths or [REPO_ROOT]
    missing = [p for p in paths if not p.exists()]
    if missing:
        parser.error(f"no such file or directory: {missing[0]}")
    return run(paths, args.deny_list, set(args.category or CATEGORIES))


if __name__ == "__main__":
    sys.exit(main())
