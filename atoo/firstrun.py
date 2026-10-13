"""`atoo init` -- a working folder of your own.

Before this, a new user's only starting material was a clone of the
maintainer's working show folder, which is the project's working area (tens of
megabytes of desk captures, runs and test plans) rather than something to
hand a person. `init` makes ``~/Documents/Atoo`` (or ``--dir``),
copies a small **starter set** into it, and names three of those things
in ``~/.atoo.config`` so the rest of Atoo finds them:

    [conventions] default  ->  <folder>/conventions.md
    [presets]     default  ->  <folder>/presets
    [workspace]   default  ->  <folder>

**The starter set is the repository's top-level ``starter/``**, the one
copy of the starter conventions, the starter preset library and the Demo
show (the maintainer, 2026-10-11: *"one top level starter or
examples directory at the top of the project -- let's get rid of
duplicates"*). A wheel carries it as the package ``atoo.starter``
(``pyproject.toml`` maps that package to ``starter/``; checked by
``tests/test_packaging.py``), so a pipx install has it with no checkout.
`starter_dir()` finds it in either place: inside the installed package,
or beside the ``atoo/`` package in a checkout or an editable
install -- whichever actually holds the set, so a pre-#493 checkout's
leftover ``atoo/starter/`` is passed over. It is never read from the maintainer's own show folders -- a wheel
install has none. What
``init`` copies from it:

* ``README.md`` -- what each file is, and ``atoo ui`` next;
* ``conventions.md`` -- the starter house conventions: a
  band/club house style that states the usual choices, so a first build
  infers little. The packaged Demo show is built from the same file;
* ``presets/`` -- the starter preset library: the maintainer's own
  channel presets, one per source, that those conventions name, and three
  bus presets: "Mix Bus" for the mix busses and two for FX busses;
* no show bundle, unless asked. ``demo-show/`` (the Demo) is opened
  read-only from the package by the UI's **Try the demo show**. Which
  show a user starts with is not something ``init`` can know (the
  maintainer, 2026-10-01: *"Do not automatically choose a starter show
  -- we have no way of knowing what it should be"*), so the first show
  is made with the UI's **New show...**. Nor are there plans, build
  logs, journals, captures or resolved conventions: those are what
  Atoo makes.

**``init --demo``** also copies the Demo show into the
folder as ``demo-show/``, an ordinary writable bundle -- the copy a
tester applies to a desk of their own, which a pipx install otherwise
had no way to make. Same name and same place relative to
``conventions.md`` and ``presets/`` as in the starter set, so the plan's
bundle-relative paths find the copied conventions and the copy
opens as PLAN CURRENT. The copy is the user's from the moment it is
made: it is not in the manifest, ``--force`` never touches it, and a
``demo-show`` already in the folder -- however it got there -- is left
whole and reported. To start again from the packaged Demo, delete or
rename it and run ``init --demo`` again.

**Never overwrite.** Every file is one of:

* ``created`` -- it was not there;
* ``same`` -- it is there, byte for byte what the starter set has;
* ``older`` -- it is an *unchanged* copy of an older starter set: what
  ``init`` copied last time, untouched since, and the starter set has
  moved on. Reported; replaced only with ``--force`` (``updated``);
* ``yours`` -- it is there and differs, and nothing says ``init`` put it
  there unchanged. Left alone, with or without ``--force``.

Which copies are "unchanged" is known from ``.atoo-starter.json``, a
small manifest `init` writes in the folder: the SHA-256 of every file as
it copied it. No manifest, or a file whose hash no longer matches its
entry, means the file is the user's. That is the safe direction to be
wrong in -- a stale starter file is a nuisance, a lost edit is not.

**The config is the same.** A section that already names something else
is left alone (``kept``) and reported with what `init` would have set;
``--force`` replaces it. The edits are `config._set_default`'s one-line,
checked edits, so the file's comments and order survive.

`init` run twice is a no-op, and says so.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from atoo import config

#: Files that make a folder the starter set rather than a folder that
#: merely has its name: what `init` needs, and the Demo show's plan.
STARTER_MARKERS = ("README.md", "conventions.md", "presets/README.md",
                   "demo-show/plan.json")


def starter_candidates() -> tuple[Path, Path]:
    """Where the starter set can be, in the order looked: inside this
    package (``atoo/starter/``, where a wheel installs the package
    ``atoo.starter``), then beside it (the repository's ``starter/``,
    for a checkout or an editable install). Both are derived from this
    module's own location at run time -- nothing is recorded at build
    time or in a config."""
    package = Path(__file__).resolve().parent
    return package / "starter", package.parent / "starter"


def holds_starter_set(path: Path) -> bool:
    """Whether `path` actually holds the starter set (`STARTER_MARKERS`)."""
    return all((path / rel).is_file() for rel in STARTER_MARKERS)


def starter_dir() -> Path:
    """The starter set: the first of `starter_candidates()` that holds it.

    A folder merely being there is not enough: a checkout
    from before an earlier change had a ``atoo/starter/`` of its own, and on
    a Mac a ``.DS_Store`` or an untracked preset keeps that folder alive
    after ``git pull`` removes its files. An editable install from that
    checkout used to take the leftover folder -- ``init`` copied only the
    leftovers, and the Demo opened ``atoo/starter/demo-show``, which
    does not exist. When neither holds the set (a broken install), the
    package's own is returned, and `run_init` says the set is missing."""
    candidates = starter_candidates()
    for path in candidates:
        if holds_starter_set(path):
            return path
    return candidates[0]


STARTER_DIR = starter_dir()
#: The Demo show inside the starter set: opened read-only by the UI,
#: never copied by `init`.
DEMO_SHOW_NAME = "demo-show"
#: The starter preset library, as `init` copies it into the folder.
PRESETS_NAME = "presets"
MANIFEST_NAME = ".atoo-starter.json"
DEFAULT_DIR_PARTS = ("Documents", "Atoo")

# What each config section is pointed at, relative to the working folder.
# "" is the folder itself.
CONFIG_TARGETS = (
    ("conventions", "conventions.md", config.set_default_conventions),
    ("presets", PRESETS_NAME, config.set_default_presets),
    ("workspace", "", config.set_default_workspace),
)


def default_directory() -> Path:
    """``~/Documents/Atoo``, against `Path.home()` so a test's home
    is honoured."""
    return Path.home().joinpath(*DEFAULT_DIR_PARTS)


def starter_files() -> list[str]:
    """Every file `init` copies from the starter set, as a POSIX path
    relative to it, sorted -- README.md first, then the loose files, then
    each folder. The Demo show is not one of them, and nor is a hidden
    file (a Mac checkout's ``.DS_Store``)."""
    names = [p.relative_to(STARTER_DIR).as_posix()
             for p in STARTER_DIR.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts
             and not any(part.startswith(".") for part in p.relative_to(STARTER_DIR).parts)
             and p.relative_to(STARTER_DIR).parts[0] != DEMO_SHOW_NAME]

    def order(name: str):
        return (name != "README.md", "/" in name, name.split("/")[0] == PRESETS_NAME,
                name.casefold())
    return sorted(names, key=order)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class InitResult:
    directory: Path
    directory_created: bool = False
    files: dict[str, str] = field(default_factory=dict)        # rel -> status
    config: list[dict] = field(default_factory=list)            # per section
    errors: list[str] = field(default_factory=list)
    #: `init --demo`: "created" (with `demo_files`), "yours" (a
    #: demo-show/ was already there, left whole), or None (not asked).
    demo: str | None = None
    demo_files: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (self.directory_created
                or self.demo == "created"
                or any(s in ("created", "updated") for s in self.files.values())
                or any(c.get("status") in ("created", "added", "replaced")
                       for c in self.config))


def _read_manifest(directory: Path) -> dict[str, str]:
    try:
        data = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return {}
    return {k: v for k, v in files.items() if isinstance(k, str) and isinstance(v, str)}


def _write_manifest(directory: Path, files: dict[str, str]) -> None:
    body = {
        "note": "Written by `atoo init`: the SHA-256 of each starter file as it was "
                "copied, so a later `init --force` can tell an untouched copy (safe to "
                "update) from one you edited (never touched). Deleting this file only "
                "means init treats every file here as yours.",
        "files": dict(sorted(files.items())),
    }
    (directory / MANIFEST_NAME).write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def demo_files() -> list[str]:
    """Every file of the packaged Demo show, as a POSIX path relative to
    it, sorted -- what `init --demo` copies. No hidden file and no
    ``__pycache__``, as for `starter_files`."""
    demo = STARTER_DIR / DEMO_SHOW_NAME
    return sorted(p.relative_to(demo).as_posix() for p in demo.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts
                  and not any(part.startswith(".") for part in p.relative_to(demo).parts))


def _copy_demo(directory: Path, result: InitResult) -> None:
    """`init --demo`: the packaged Demo show, copied whole to
    ``<directory>/demo-show``, or left alone if anything is there by that
    name. Copied into a hidden sibling first and renamed into place, so a
    failure leaves no half-copied bundle to be mistaken for the Demo."""
    target = directory / DEMO_SHOW_NAME
    if target.exists() or target.is_symlink():
        result.demo = "yours"
        return
    names = demo_files()
    if "plan.json" not in names:
        result.errors.append("this Atoo install's Demo show has no plan.json -- the "
                             "Demo show was not copied. Reinstall Atoo.")
        return
    staging = directory / f".{DEMO_SHOW_NAME}.atoo-init"
    try:
        if staging.exists():
            shutil.rmtree(staging)
        for rel in names:
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(STARTER_DIR / DEMO_SHOW_NAME / rel, dest)
        # A rename never replaces a folder that has something in it, and
        # one that appeared since the check above is left alone too.
        os.rename(staging, target)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if target.exists():
            result.demo = "yours"
            return
        result.errors.append(f"couldn't copy the Demo show to {DEMO_SHOW_NAME}/: "
                             f"{exc.strerror or exc}")
        return
    result.demo = "created"
    result.demo_files = names


def run_init(directory: Path | None = None, *, force: bool = False,
             demo: bool = False) -> InitResult:
    """Make the working folder, copy the starter set into it, and set the
    three config defaults; with `demo`, copy the Demo show in too
    (`_copy_demo`). Never overwrites anything the user made or changed;
    see the module docstring."""
    directory = Path(directory) if directory is not None else default_directory()
    directory = config.expand_home(str(directory))
    if not directory.is_absolute():
        directory = Path.cwd() / directory
    directory = Path(os.path.normpath(str(directory)))
    result = InitResult(directory=directory)

    if not all((STARTER_DIR / rel).is_file() for rel in ("README.md", "conventions.md")):
        looked = " or ".join(str(p) for p in starter_candidates())
        result.errors.append(
            f"this Atoo install has no starter set (looked in {looked}) -- nothing was "
            "written. Reinstall Atoo (`pipx reinstall atoo`, or from a checkout "
            "`pipx install --force --editable .`).")
        return result
    if directory.exists() and not directory.is_dir():
        result.errors.append(f"{config.config_value_for(directory)} is a file, not a folder "
                             "-- nothing was written. Choose another place with --dir.")
        return result
    if not directory.exists():
        try:
            directory.mkdir(parents=True)
        except OSError as exc:
            result.errors.append(f"couldn't create {config.config_value_for(directory)}: "
                                 f"{exc.strerror or exc} -- nothing was written.")
            return result
        result.directory_created = True

    manifest = _read_manifest(directory)
    new_manifest = dict(manifest)
    for rel in starter_files():
        source = STARTER_DIR / rel
        target = directory / rel
        want = _sha256(source)
        if target.is_symlink() or (target.exists() and not target.is_file()):
            result.files[rel] = "yours"
            continue
        if not target.exists():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive create: never over a file that appeared since
                # the check above.
                with open(target, "xb") as handle:
                    handle.write(source.read_bytes())
            except FileExistsError:
                result.files[rel] = "yours"
                continue
            except OSError as exc:
                result.errors.append(f"couldn't write {rel}: {exc.strerror or exc}")
                continue
            result.files[rel] = "created"
            new_manifest[rel] = want
            continue
        have = _sha256(target)
        if have == want:
            result.files[rel] = "same"
            new_manifest[rel] = want
        elif manifest.get(rel) == have:
            # An untouched copy of what an older `init` put here.
            if force:
                try:
                    tmp = target.with_name(f".{target.name}.atoo-init")
                    shutil.copyfile(source, tmp)
                    os.replace(tmp, target)
                except OSError as exc:
                    result.errors.append(f"couldn't update {rel}: {exc.strerror or exc}")
                    continue
                result.files[rel] = "updated"
                new_manifest[rel] = want
            else:
                result.files[rel] = "older"
        else:
            result.files[rel] = "yours"
    if new_manifest != manifest:
        try:
            _write_manifest(directory, new_manifest)
        except OSError as exc:
            result.errors.append(f"couldn't write {MANIFEST_NAME}: {exc.strerror or exc} -- "
                                 "a later `init --force` will treat these files as yours")
    if demo:
        _copy_demo(directory, result)

    for section, rel, writer in CONFIG_TARGETS:
        target = directory / rel if rel else directory
        entry = {"section": section, "value": config.config_value_for(target)}
        if rel and not target.exists():
            # Only reachable when the copy itself failed (reported above).
            entry.update(status="skipped", message=f"{rel} is not in the folder")
            result.config.append(entry)
            continue
        try:
            outcome = writer(target, replace=force)
        except config.ConfigWriteError as exc:
            entry.update(status="error", message=str(exc))
            result.errors.append(str(exc))
        else:
            entry.update(status=outcome["status"], previous=outcome.get("previous"),
                         message=outcome["message"])
        result.config.append(entry)
    return result


_FILE_WORDS = {
    "created": "created",
    "same": "already there",
    "updated": "updated (an untouched older starter copy)",
    "older": "left alone: an untouched copy of an older starter set -- --force updates it",
    "yours": "left alone: it is yours (it differs from the starter set)",
}


def format_report(result: InitResult) -> list[str]:
    """What `atoo init` prints: the folder, every starter file that
    is not merely "already there" (the preset library summarised), every
    config value written or left alone, and what to do next."""
    shown = config.config_value_for(result.directory)
    lines = []
    if result.errors and not result.files:
        return lines
    lines.append(f"Working folder: {shown}"
                 + (" (created)" if result.directory_created else " (already there)"))

    # Loose files one per line; the preset library's presets (channel
    # `.chn` and bus `.bus`) as one line of counts, plus a line for each
    # preset not merely created/same.
    prefix = f"{PRESETS_NAME}/"
    presets = [r for r in result.files
               if r.startswith(prefix) and r.endswith((".chn", ".bus"))]
    loose = [r for r in result.files if r not in presets]
    for rel in loose:
        lines.append(f"  {rel:<28} {_FILE_WORDS[result.files[rel]]}")
    if presets:
        counts: dict[str, int] = {}
        for rel in presets:
            counts[result.files[rel]] = counts.get(result.files[rel], 0) + 1
        summary = ", ".join(f"{n} {_FILE_WORDS[s].split(':')[0]}"
                            for s, n in sorted(counts.items(),
                                               key=lambda kv: list(_FILE_WORDS).index(kv[0])))
        lines.append(f"  {prefix:<28} {len(presets)} presets: {summary}")
        for rel in presets:
            if result.files[rel] in ("older", "yours", "updated"):
                lines.append(f"    {rel[len(prefix):]}: {_FILE_WORDS[result.files[rel]]}")
    if result.demo == "created":
        for rel in result.demo_files:
            lines.append(f"  {DEMO_SHOW_NAME + '/' + rel:<28} created")
    elif result.demo == "yours":
        lines.append(f"  {DEMO_SHOW_NAME + '/':<28} left alone: a {DEMO_SHOW_NAME} folder is "
                     "already here -- rename it, and run init --demo again, for a fresh copy")

    lines.append("")
    lines.append(f"{config.config_value_for(config.config_path())}:")
    for entry in result.config:
        section, value, status = entry["section"], entry["value"], entry.get("status")
        key = f"[{section}] default"
        if status in ("created", "added"):
            lines.append(f"  {key:<24} set to {value}")
        elif status == "replaced":
            lines.append(f"  {key:<24} set to {value} (replaced {entry.get('previous')})")
        elif status == "unchanged":
            lines.append(f"  {key:<24} already {value}")
        elif status == "kept":
            lines.append(f"  {key:<24} left as {entry.get('previous')} -- init would have set "
                         f"{value}; --force replaces it")
        else:
            lines.append(f"  {key:<24} not set: {entry.get('message')}")

    lines.append("")
    if not result.changed and not result.errors:
        lines.append("Nothing to do: everything init sets up is already here, and it changes "
                     "nothing that is.")
    start = shown
    for entry in result.config:
        if entry["section"] == "workspace" and entry.get("status") == "kept":
            start = f"{entry.get('previous')} (your [workspace] default)"
    lines.append("Next: `atoo ui` opens Atoo in your browser, starting in "
                 f"{start}. {shown}/README.md says what each file is.")
    if result.demo == "created":
        lines.append(f"The Demo show's copy is {shown}/{DEMO_SHOW_NAME}: yours to edit, "
                     "build and apply.")
    return lines
