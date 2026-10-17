"""Keep a bundle's history folders to the newest few entries.

A bundle shows only plan files at the top level (so text files go in a
directory called `logs`), and the builds, journals, and logs directories
are continually pruned to a max of 5 entries each.

So a bundle has three folders that grow by one entry per run, and each is
pruned to `KEEP` entries straight after every write into it:

    my-show/
      builds/     one JSON per build (build_log.py)         pruned by build_log.write
      journals/   one JSON per confirmed write + index.json pruned by journal_stack.record
      logs/       a build + verify transcript pair per run  pruned by the rebuild script,
                  of a rebuild script                       via `python3 -m atoo.prune logs DIR`

**What an entry is.** For `builds/` and `journals/` it is one file. For
`logs/` it is one RUN: the script writes `<stamp>-build.txt` and
`<stamp>-verify.txt` with the same stamp, and the pair is one entry
(`run_key`), so keeping five keeps five runs, each with both halves -- a
build transcript whose verify was pruned away is half a record.

**Which entries are kept.** The newest, by name: every name here starts
with a UTC timestamp, so a lexicographic sort is a chronological one and
no file is opened to order them. A caller may PROTECT entries it cannot
lose (`builds/` protects the log `plan.json` points to); a protected entry
takes one of the `KEEP` places rather than adding one, so the folder still
holds at most `KEEP` -- unless more than `KEEP` are protected, which keeps
them all. `journals/` decides what it can lose itself
(`journal_stack._prune`), because which journal a stack still needs is a
question about the stack, not about file names; it shares `KEEP`.

The limit is a named constant, not a setting: five.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Iterable

#: How many entries each of `builds/`, `journals/` and `logs/` keeps.
KEEP = 5


def run_key(name: str) -> str | None:
    """The entry a `logs/` file belongs to: its name without the trailing
    `-<what>.txt` -- `2026-10-02T17-33-05Z-build.txt` and
    `2026-10-02T17-33-05Z-verify.txt` are one run, `2026-10-02T17-33-05Z`.
    None for anything that is not a `.txt` (it is not ours to delete)."""
    if not name.endswith(".txt"):
        return None
    stem = name[:-len(".txt")]
    head, sep, _what = stem.rpartition("-")
    return head if sep and head else stem


def file_key(suffix: str) -> Callable[[str], "str | None"]:
    """An `entry_of` for a folder where each file is one entry: the file's
    own name, for names ending in `suffix`; None (never touched) for the
    rest."""
    def key(name: str) -> str | None:
        return name if name.endswith(suffix) else None
    return key


def select(keys: Iterable[str], keep: int, protect: Iterable[str] = ()) -> tuple[list[str], list[str]]:
    """`(kept, dropped)`, each oldest first, for entry `keys` that sort
    chronologically. The newest `keep` are kept, with every key in
    `protect` taking one of those places (the oldest unprotected ones give
    theirs up). `keep <= 0` keeps everything."""
    ordered = sorted(set(keys))
    if keep <= 0 or len(ordered) <= keep:
        return ordered, []
    protected = [k for k in ordered if k in set(protect)]
    room = max(keep - len(protected), 0)
    rest = [k for k in ordered if k not in set(protected)]
    newest = rest[len(rest) - room:] if room else []
    kept = sorted(set(protected) | set(newest))
    dropped = [k for k in ordered if k not in set(kept)]
    return kept, dropped


def prune(directory: Path, entry_of: Callable[[str], "str | None"], *,
          keep: int | None = None, protect: Iterable[str] = ()) -> list[Path]:
    """Delete every file in `directory` whose entry (`entry_of(name)`) is
    not among the newest `keep` (default `KEEP`). Files `entry_of` maps to
    None are left alone. Returns the paths deleted. A file that cannot be
    deleted is skipped, not raised: pruning is housekeeping, and must never
    turn a run that worked into one that failed."""
    keep = KEEP if keep is None else keep
    try:
        files = [p for p in directory.iterdir() if p.is_file()]
    except OSError:
        return []
    by_entry: dict[str, list[Path]] = {}
    for path in files:
        key = entry_of(path.name)
        if key is not None:
            by_entry.setdefault(key, []).append(path)
    _kept, dropped = select(by_entry, keep, protect)
    removed: list[Path] = []
    for key in dropped:
        for path in sorted(by_entry[key]):
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                pass
    return removed


def prune_logs(directory: Path, keep: int | None = None) -> list[Path]:
    """`logs/`: keep the newest `keep` runs (`run_key`)."""
    return prune(directory, run_key, keep=keep)


def main(argv: list[str] | None = None) -> int:
    """`python3 -m atoo.prune logs DIR` -- what
    a rebuild script calls after writing a run's transcripts
    into `DIR` (a bundle's `logs/`). Prints one line per run removed."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] != "logs":
        print("usage: python3 -m atoo.prune logs DIR", file=sys.stderr)
        return 2
    directory = Path(argv[1])
    removed = prune_logs(directory)
    runs = sorted({run_key(p.name) for p in removed})
    if runs:
        print(f"INFO {directory} keeps the newest {KEEP} runs; removed "
              f"{len(runs)} older: {', '.join(r for r in runs if r)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
