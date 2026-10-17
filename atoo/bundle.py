"""A show bundle: one directory holding everything for one show.

The problem: the conventions file is meant to be
*reusable house style* -- the engineer's preferences and approach to setting up the
board in general, not specific to a particular input list -- but its
`## Busses`/`## Outputs` sections had become the place show-specific
decisions went, because there was nowhere else for them. Meanwhile the
input list, the watchlist and the plan were independent `--flag path`
arguments a user had to remember to pass together and keep in sync by
hand.

A bundle is the answer: a directory, fixed filenames inside it, **no
manifest**. Convention over configuration: there is no manifest file to author or keep current.

    my-show/
      input.csv            the input list                  (hand-authored)
      instructions.md      per-show instructions           (hand-authored)
      plan.json            the plan the last build made    (atoo build, and nothing else)
      watch.json           the watchlist                   (hand today; drafted)
      plan.previous.json   the plan a rebuild replaced     (kept, one generation; the next rebuild
                                                           compares against it, FR-1.4)
      plan.partial.json    a failed build's partial reply  (removed by the next good build)
      journals/            every journalled write, in time order:
                           each confirmed apply, patch, amend and undo -- the newest 5
      builds/              each build's own log (`build_log.py`) -- the newest 5
      logs/                text transcripts of a rebuild script's runs -- the newest 5
      backups/             the file a copy into a slot replaced, `<name>.bak`

Only plan files and the hand-authored inputs sit at the top level;
everything else Atoo writes goes in a folder.

`plan.json` has ONE writer, `atoo build`: it is only
modified when the input list, the conventions file or the instructions
file, the inputs to plan.json, have changed. Before that a confirmed amend
replaced it; that is reversed. What a change or an amend puts on a desk is
recorded by that desk's journal entry, which embeds the plan it left there
(`journal_stack.DESK_PLAN_BLOCK`), and undo still puts back a plan.json an
amend recorded before the reversal replaced (`journal_stack.PLAN_BLOCK`).

`journals/` is the one entry here that is a **directory**, and the only
one this module does not treat as a slot: `SLOTS` is the set of fixed
FILENAMES, each of which answers `has()` with "is there a file there",
and a folder is a different question. Its name is here because naming
paths is what this module is for; everything about what is inside it --
the time ordering, the last-N pruning, which entry `atoo undo`
pops -- lives in `atoo/journal_stack.py`.

`journals/` is the ONLY record of a write. Before that,
every confirmed apply, amend and patch was also copied over a
top-level `apply-journal.json`, `amend-journal.json` or
`patch-journal.json`; nothing writes those any more (the `journals/` folder replaces
them), and since 2026-10-02 nothing reads them either: `atoo undo --show`
on a bundle with no `journals/` has nothing to undo.
A journal file named on the command line -- `atoo undo PATH` -- is
read like any journal, wherever it is, and one that carries a
`stack_entry` block resolves to the entry it copies (`journal_stack.find`).

A sixth slot, `expectations.toml`, existed until an earlier change retired the
feature behind it. A bundle directory that still holds one is **not an
error**: it is simply not a slot any more, so nothing reads it and
nothing reports it. An old show bundle keeps working, and the leftover
file can be deleted whenever its owner gets to it.

The house conventions file stays **outside** the bundle --
it is the reusable piece, named by `~/.atoo.config`, and the whole
reason it isn't per-show.

This module is deliberately **pure path resolution**: it does not read,
parse or validate any of these files. That is what lets `audit`, `watch`
and `ui` use it without dragging in `build`'s dependencies, and it is why
a slot that doesn't exist yet is a perfectly ordinary answer rather than
an error -- `plan.json` is absent until the first build, and `journals/`
until the first confirmed write.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# The fixed names. Named constants rather
# than string literals at each use site so the set is greppable and a
# rename is one edit -- these are a user-facing contract the moment
# someone lays out a directory by hand.
INPUT_LIST = "input.csv"
INSTRUCTIONS = "instructions.md"
PLAN = "plan.json"
# The plan a rebuild replaced, moved aside when the rebuild starts
# (cli._build): a failed build leaves no out-of-date plan.json behind.
PLAN_PREVIOUS = "plan.previous.json"
WATCH_CONDITIONS = "watch.json"

# The journal stack's directory. A folder, not a slot --
# see the module docstring -- and deliberately spelled here rather than
# in `journal_stack.py` so that every fixed name inside a bundle is
# greppable from one file.
JOURNALS = "journals"

# The other history folders (the bundle shows only plan files at the
# top level). Each grows by one entry
# per run and is pruned to `prune.KEEP` entries after every write into it:
# `builds/` one JSON per build (`build_log.py`),
# `logs/` the text transcripts a rebuild script saves, one
# build + verify pair per run. `backups/` holds the one file a copy into a
# slot replaced (`<name>.bak`, the Setup page's file picker), at most one
# per slot, so it needs no pruning.
BUILDS = "builds"
LOGS = "logs"
BACKUPS = "backups"

# Everything a bundle can hold, in the order a show moves through them:
# what you write, then what Atoo produces.
# `apply-journal.json` was the fifth until an earlier change retired it in favour
# of `journals/`, which is a directory and so never a slot.
SLOTS = (INPUT_LIST, INSTRUCTIONS, PLAN, WATCH_CONDITIONS)


class BundleError(Exception):
    """A directory that cannot be used as a bundle, with a message already
    phrased for a user -- the caller prints it and exits, the same
    contract `cli._LoadError` has."""


@dataclass(frozen=True)
class Bundle:
    """The four paths, resolved. Existence is answered per slot rather than
    up front, because which slots have to exist depends on the command:
    `build` needs an input list, `apply` needs a plan, `watch` needs
    neither.
    """

    directory: Path

    @property
    def input_list(self) -> Path:
        return self.directory / INPUT_LIST

    @property
    def instructions(self) -> Path:
        return self.directory / INSTRUCTIONS

    @property
    def plan(self) -> Path:
        return self.directory / PLAN

    @property
    def watch_conditions(self) -> Path:
        return self.directory / WATCH_CONDITIONS

    @property
    def journals(self) -> Path:
        """The journal stack's directory, whether or not it exists yet
        (`atoo/journal_stack.py` owns everything inside it)."""
        return self.directory / JOURNALS

    def path(self, slot: str) -> Path:
        """The path for one fixed name, whether or not anything is there."""
        if slot not in SLOTS:
            # `expectations.toml` was a slot until an earlier change retired it, and a
            # caller still asking for one is a stale caller, not a user
            # error -- hence ValueError here and silence in `present()`.
            raise ValueError(f"{slot!r} is not a bundle slot; known: {list(SLOTS)}")
        return self.directory / slot

    def has(self, slot: str) -> bool:
        return self.path(slot).is_file()

    def present(self) -> tuple[str, ...]:
        """Which slots actually hold a file, in `SLOTS` order."""
        return tuple(s for s in SLOTS if self.has(s))

    def missing(self) -> tuple[str, ...]:
        return tuple(s for s in SLOTS if not self.has(s))

    # -- optional-slot accessors -------------------------------------
    #
    # `None` for "nothing there", so a caller can pass the result straight
    # into an existing `path or None` argument without restating the
    # existence check at every call site. The required slots
    # (`input.csv` for build, `plan.json` for apply) deliberately have no
    # such accessor: those get `require()`, which explains itself.

    def optional(self, slot: str) -> Path | None:
        return self.path(slot) if self.has(slot) else None

    def require(self, slot: str) -> Path:
        """The path for a slot this command cannot run without.

        The message names the directory and the exact filename expected,
        because the failure mode this guards against is someone laying a
        bundle out by hand and naming the input list after the show.
        """
        path = self.path(slot)
        if not path.is_file():
            raise BundleError(
                f"{self.directory} is not a usable show bundle: no {slot!r} in it. "
                f"A bundle is a directory with fixed filenames inside "
                f"({', '.join(SLOTS)}) -- see https://docs.atoo.app/build/show-bundles/"
            )
        return path


def load(directory: str | Path) -> Bundle:
    """Resolve a `--show DIR` argument to a `Bundle`.

    Raises `BundleError` for a path that is not a directory. It does not
    require any particular file to be present -- an empty directory is a
    valid (if useless) bundle, and each command asks for what it needs via
    `require()`. That split matters: `atoo build --show new-show/`
    on a directory holding only `input.csv` is exactly the first thing
    someone does, and it must not be refused for missing the plan it is
    about to write.
    """
    path = Path(directory)
    if not path.exists():
        raise BundleError(
            f"no such directory: {path} -- --show takes a show bundle directory, "
            f"not a file (see https://docs.atoo.app/build/show-bundles/)."
        )
    if not path.is_dir():
        raise BundleError(
            f"{path} is a file, not a directory -- --show takes the show bundle "
            f"directory that holds {INPUT_LIST}, {PLAN} and the rest."
        )
    return Bundle(directory=path)
