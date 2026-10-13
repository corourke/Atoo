"""Which preset library a command uses -- one resolver for `build`,
`patch` and `amend`.

The order, first usable one wins:

1. **`--presets DIR`**, stated on the command line. A stated directory
   that is not there is a warning and no library -- the engineer named
   it, so quietly reaching past it for another would hide his mistake.
2. **The library the plan records** -- only when there is a plan, as there
   is for `patch` and `amend`: the `library` every expanded preset's
   `preset_values` carries (`preset_expand`, `bus_presets`). The strips
   already on the desk carry that library's values, so a strip a change
   adds takes its preset from the same one. A recorded path that no longer
   resolves (the plan was built from a relative path, or on another
   machine) is matched to the **packaged starter presets** when every
   preset file the plan records is there with the same bytes -- which is
   how the Demo show, and any copy of it, finds `starter/presets` from
   wherever it is run.
3. **`[presets] default`** in `~/.atoo.config`. One that is set but is
   not a directory, or holds no `.chn`/`.bus` file, is passed over with
   a note saying so, and the next candidate is tried.

Whichever is used is announced at INFO with the reason (CLAUDE.md's INFO
principle): the engineer can see which library his new strips' values
came from, and correct his config if it was the wrong one.

No library at all is not refused. A strip without its preset's values
still passes audio; it is a WARNING (`preset.no-library`), and `patch`
says it up front when its change names a preset (`missing_library_warning`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PRESET_VALUES_KEY = "preset_values"


@dataclass
class LibraryChoice:
    """The resolver's answer: `library` (a `PresetLibrary`, or None), the
    directory it reads, a short `source` ("--presets", "the [presets]
    default in ...", "the library the plan was built with", ...), and
    what to tell the engineer: `infos` (which library and why) and
    `warnings` (a stated library that is not there)."""

    library: object = None
    path: "Path | None" = None
    source: "str | None" = None
    infos: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _usable(path: Path) -> "str | None":
    """Why `path` cannot be a preset library, or None when it can."""
    if not path.is_dir():
        return "is a file, not a directory" if path.is_file() else "does not exist"
    if not any(path.glob("*.chn")) and not any(path.glob("*.bus")):
        return "holds no .chn or .bus preset files"
    return None


def recorded_presets(plan: "dict | None") -> list[dict]:
    """Every `preset_values` record in `plan`, channels and busses alike."""
    if not isinstance(plan, dict):
        return []
    entries = [((c or {}).get("processing") or {}).get(PRESET_VALUES_KEY)
               for c in plan.get("channels") or [] if isinstance(c, dict)]
    busses = plan.get("busses") or {}
    if isinstance(busses, dict):
        entries += [b.get(PRESET_VALUES_KEY) for b in busses.values() if isinstance(b, dict)]
    return [e for e in entries if isinstance(e, dict)]


def recorded_library(plan: "dict | None") -> "str | None":
    """The library path the plan's presets were expanded from -- the most
    common one, should a plan ever carry two."""
    paths = Counter(str(e["library"]) for e in recorded_presets(plan) if e.get("library"))
    return paths.most_common(1)[0][0] if paths else None


def _matches_starter(plan: dict, starter: Path) -> bool:
    """Whether every preset file `plan` records is in `starter`, byte for
    byte (its sha256) -- the plan was built from the packaged starter
    presets, wherever they were on the building machine."""
    import hashlib

    records = [e for e in recorded_presets(plan) if e.get("file") and e.get("sha256")]
    if not records or not starter.is_dir():
        return False
    for entry in records:
        candidate = starter / str(entry["file"])
        try:
            if hashlib.sha256(candidate.read_bytes()).hexdigest() != entry["sha256"]:
                return False
        except OSError:
            return False
    return True


def resolve(explicit: "str | None", plan: "dict | None" = None, *,
            default: "Path | None" = None, default_label: "str | None" = None,
            starter: "Path | None" = None) -> LibraryChoice:
    """The preset library to use; see the module docstring for the order.

    `default`/`default_label` are `[presets] default` and where it was
    read, and `starter` the packaged starter presets -- read from the
    config and `firstrun` when not given (tests pass them)."""
    from atoo.presets import PresetLibrary

    choice = LibraryChoice()

    def use(path: Path, source: str, why: str) -> LibraryChoice:
        choice.library, choice.path, choice.source = PresetLibrary(path), path, source
        choice.infos.append(f"preset library: {path} -- {why}")
        return choice

    if explicit:
        path = Path(explicit)
        if not path.is_dir():
            choice.warnings.append(
                f"preset library {path} (--presets) {_usable(path)} -- continuing without "
                "it; any preset this plan names will be reported unresolved")
            return choice
        return use(path, "--presets", "given with --presets")

    passed_over: list[str] = []
    recorded = recorded_library(plan)
    if recorded:
        path = Path(recorded)
        problem = _usable(path)
        if problem is None:
            return use(path, "the library the plan was built with",
                       "the library the plan on the desk was built with (its strips' "
                       "preset values record it)")
        if starter is None:
            from atoo import firstrun
            starter = firstrun.STARTER_DIR / firstrun.PRESETS_NAME
        if _matches_starter(plan, starter):
            return use(starter, "the packaged starter presets",
                       f"the plan was built with {recorded}, which is not there from here; "
                       "every preset file it records is in the packaged starter presets with "
                       "the same contents, so those are used")
        passed_over.append(f"the library the plan was built with, {recorded}, {problem}")

    if default is None and default_label is None:
        from atoo import config
        default = config.load_default_presets()
        default_label = f"the [presets] default in {config.config_path()}"
    if default is not None:
        path = Path(default)
        problem = _usable(path)
        if problem is None:
            why = default_label or "the [presets] default"
            if passed_over:
                why += f" ({'; '.join(passed_over)})"
            return use(path, default_label or "the [presets] default", why)
        passed_over.append(f"{default_label or 'the [presets] default'}, {path}, {problem}")

    if passed_over:
        choice.infos.append("no preset library: " + "; ".join(passed_over))
    return choice


def presets_named_by(change_set: "dict | None") -> list[str]:
    """The presets a change set's NEW channels and busses name -- the ones
    it would write the values of, given a library."""
    add = (change_set or {}).get("add") or {}
    names = [((c or {}).get("processing") or {}).get("preset")
             for c in add.get("channels") or [] if isinstance(c, dict)]
    busses = add.get("busses") or {}
    if isinstance(busses, dict):
        names += [b.get("preset") for b in busses.values() if isinstance(b, dict)]
    return list(dict.fromkeys(str(n) for n in names if n))


def missing_library_warning(change_set: "dict | None", choice: LibraryChoice) -> "str | None":
    """The line said up top, before the review, when a
    change names presets and no library was found -- a WARNING, not an
    ERROR: the strips are written and pass audio, without their presets'
    processing."""
    if choice.library is not None:
        return None
    named = presets_named_by(change_set)
    if not named:
        return None
    return (f"no preset library was found, and this change names {len(named)} preset(s) "
            f"({', '.join(named)}): the new strips and busses will be written WITHOUT those "
            "presets' processing (filter, gate, dynamics, EQ, a bus's compressor or effect). "
            "Pass --presets DIR, or set [presets] default in ~/.atoo.config, and "
            "preview again.")
