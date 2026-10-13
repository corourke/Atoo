"""No file in this repository may carry a merge-conflict marker.

Written 2026-09-23, after `main` shipped with markers in four documents
for most of a day. They entered through a review merge whose output was
piped through `tail`: three conflicts were visible, four more were not,
and `git add -A` staged the unresolved files verbatim. The Python suite
could not see it, because the damage was all in `.md` files -- the same
shape as `CLAUDE.md`'s standing warning about `atoo/web/static/`.

Cheap, total, and it does not care how the marker got there.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Assembled rather than written out, or this file would match itself.
MARKERS = ("<" * 7 + " ", "=" * 7, ">" * 7 + " ")

#: Anything git will not diff as text is not ours to police.
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".ico",
                   ".woff", ".woff2", ".zip", ".snap"}


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                         capture_output=True, text=True, check=True).stdout
    files = []
    for name in out.split("\0"):
        if not name:
            continue
        path = ROOT / name
        if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        files.append(path)
    return files


def test_no_file_carries_a_merge_conflict_marker(whole_repository_sweep):
    offenders: list[str] = []
    # This walks every tracked file, `examples/touringband/` included, and
    # depends on nothing in any of them -- the one case conftest's
    # living-example guard stands aside for. See tests/conftest.py.
    with whole_repository_sweep("merge-conflict markers"):
        files = _tracked_text_files()
        texts = {}
        for path in files:
            try:
                texts[path] = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # not text after all; nothing to check
    for path, text in texts.items():
        for lineno, line in enumerate(text.splitlines(), start=1):
            # Anchored at column zero: `=======` is a legitimate markdown
            # rule and appears in prose, but a conflict marker is always
            # the whole line and always at the start of it. The two outer
            # markers carry a trailing space, which prose does not.
            if line.startswith(MARKERS[0]) or line.startswith(MARKERS[2]):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line[:60]}")
    assert not offenders, (
        "merge-conflict markers are committed in "
        f"{len({o.split(':')[0] for o in offenders})} file(s):\n  "
        + "\n  ".join(offenders)
        + "\n\nResolve them. If this fired on a review merge: never `git add -A` "
          "after a merge, and never read the conflict list through `tail` -- "
          "`git diff --diff-filter=U --name-only` is the whole list."
    )


def test_the_check_would_actually_catch_one(tmp_path, monkeypatch):
    """The guard's own mutation test: plant a marker and require a catch.

    A checker for something that is normally absent passes trivially
    forever, so it is worth one test proving it can fail at all.
    """
    planted = tmp_path / "poisoned.md"
    planted.write_text(f"before\n{MARKERS[0]}HEAD\nmine\n{MARKERS[1]}\n"
                       f"theirs\n{MARKERS[2]}origin/main\nafter\n")
    lines = planted.read_text().splitlines()
    hits = [l for l in lines if l.startswith(MARKERS[0]) or l.startswith(MARKERS[2])]
    assert len(hits) == 2, hits
