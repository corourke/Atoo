"""``~/.atoo.config`` -- a user-home default conventions file,
and since then the home of every per-user default Atoo reads.

The friction this solves: a conventions file is meant to be reused across
many shows -- that reusability is the whole point of separating it from
the input list (FR-1.1's docstring makes the same point about the input
list's own columns). Someone with one settled house conventions file and a
new input list every week otherwise has to pass ``--conventions`` by hand
every time, or copy that file into every working directory just so
`cli._auto_detect`'s easy-button mode finds it.

**Format.** TOML, matching `critic_expectations.py`'s own precedent (also
stdlib `tomllib`, also the project's only other user-authored TOML
format) rather than inventing a second one:

    [conventions]
    default = "/home/you/conventions/house.md"

``default`` points at a Markdown conventions file -- whatever
`cli._auto_detect` itself would have accepted -- and may use ``~`` for the
home directory.

**This is a fallback for every route, not just one.** It used
to be consulted only when `build`'s auto-detect found exactly one input
list and no conventions file at all, so `--input x.csv` with a settled
house file named here still failed. Now any build that reaches the end
without a conventions file tries it. An explicit ``--conventions`` still
wins, and a bundle's ``instructions.md`` layers *over* whichever one is
used rather than replacing it. (It could also name a ``.rules.json`` extracted-rules file
until that format was retired along with the deterministic compile path.)

**`[watch_conditions]`, same shape, one section over:**

    [watch_conditions]
    default = "/home/you/conventions/house.watch.json"

A settled house watch-conditions file (FR-6.5) is exactly as reusable
across shows as a house conventions file, for the same reason -- `atoo
watch --watch-conditions` and `atoo ui --watch-conditions` both fall
back to this when the flag is omitted, via `load_default_watch_conditions`
below, which is `load_default_conventions` with the section name swapped
and nothing else different: same TOML file, same tilde expansion, same
"quiet-but-visible" failure posture, same single-path-not-a-list stance.
Two independent single-key sections in one file rather than folding both
under one `[defaults]` table -- `[conventions]` already shipped with
this exact shape and there's no reason to break it to accommodate a
second, unrelated default.

**`[console]`, the first section that is not a path:**

    [console]
    default = "192.0.2.16"
    port = 2223
    timeout = 1.0

`--console <ip>` otherwise has to be retyped on every `ping`, `apply`,
`audit` and `watch`, and this was asked for from a desk, where
working through the console checklist means typing the same IP a dozen
times and one wrong digit on an `apply --confirm` is a write aimed at
the wrong box on the network. `ATOO_CONSOLE` covers the same need
for a session; this covers a desk you always use. `cli` resolves the
two together, explicit flag first, and **announces any address the
command line did not name** -- see `cli._resolve_console_settings`.

Unlike the three sections above, its keys are independent and each
optional: a port with no address is a reasonable thing to set, so a
missing or wrong-typed key drops that key rather than the section. It is
also the reason this module's file handling was factored out into
`_read_config` -- an IP address has nothing to existence-check, so
`_load_default_from_section` could not serve it.

**`[workspace]`, the working folder:**

    [workspace]
    default = "~/Documents/Atoo"

A *directory*, like `[presets]`: the folder `atoo init` makes and
fills with a starter set, and the one `atoo ui` starts in when no
`--show` is given -- the file browser and the bundle bar's Open... and
New show... open on it while no bundle is open, so a new show lands
beside the starter ones. Nothing else reads it: `build` and the rest
take their paths from the command line or a bundle, never from here.
Read by `load_default_workspace`.

**One default, not a list.** The issue leaves this open; a single path is
the simplest thing that solves the stated problem (one house file), and a
search list adds ordering questions ("which one wins") nothing in the
issue asks for. Extending to a list later is a compatible change to this
module alone.

**Written by one function only: `_set_default` (2026-09-25; generalised
).** Everything above reads this file; until the Setup
UI's step 01 grew a "New file" button there was no code that wrote it at
all, and a house conventions file could only be introduced by editing it
by hand. It writes `[conventions]` (the Setup UI and `atoo init`),
`[presets]` and `[workspace]` (`atoo init` only), through
`set_default_conventions`, `set_default_presets` and
`set_default_workspace`. Each call edits **one line** -- that section's
`default` -- and leaves every other byte alone: `tomllib` is read-only, so rather than
re-serialising the whole file (which would drop every comment and
reorder every key), it finds the line, changes it, re-parses the result
and refuses to write anything unless the only difference is the value it
meant to set. It never replaces a *different* default unless asked to in
so many words.

**Failure is quiet-but-visible, never fatal.** A missing config file is
completely normal (most users never create one) and says nothing; so
does a config file that leaves a section out. A config file that exists
but is broken -- bad TOML, wrong shape, a
`default` path that doesn't exist -- prints one line to stderr and is
otherwise treated exactly like "no config file": `cli.build` falls
through to its existing "no conventions source found" error rather than
crashing or silently guessing. The alternative (raising) would turn a
stale or typo'd config entry into a crash for a feature whose entire job
is to stay out of the way until needed.
"""

from __future__ import annotations

import copy
import os
import re
import sys
import tempfile
from pathlib import Path

import tomllib as _toml

CONFIG_FILENAME = ".atoo.config"


def expand_home(path_str: str) -> Path:
    """Expand a leading ``~`` against `Path.home()` -- not
    `Path.expanduser()`, which reads the real `$HOME` environment
    variable and so ignores a test's `monkeypatch.setattr(Path, "home",
    ...)`. `~user/...` (someone else's home) is not supported; nothing
    here needs it."""
    parts = Path(path_str).parts
    if parts and parts[0] == "~":
        return Path.home().joinpath(*parts[1:])
    return Path(path_str)


def config_path() -> Path:
    """``~/.atoo.config``. A function rather than a module-level
    constant so tests can point it elsewhere by monkeypatching
    ``Path.home`` (the standard way to isolate a test from the real
    user's home directory) without this module caching the wrong value
    at import time."""
    return Path.home() / CONFIG_FILENAME


def _read_config() -> tuple[Path, dict] | None:
    """``(path, parsed TOML)`` for ``~/.atoo.config``, or None.

    Factored out of `_load_default_from_section` when `[console]` became the first section that does **not** name a path -- an IP
    address has nothing to existence-check -- and so could not reuse that
    function while still needing every line of its file handling.

    None covers "there is no usable config file", in all four of its
    flavours, with this module's stated posture on each: absence is
    silent, because most users have no config file and that is not a
    problem; a file this Python cannot parse, cannot read, or that is not
    valid TOML each print one line naming the file and what was wrong
    with it, and are then treated exactly like absence.
    """
    path = config_path()
    if not path.is_file():
        return None

    try:
        data = _toml.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"{path}: couldn't read it ({exc.strerror}) -- ignoring it", file=sys.stderr)
        return None
    except _toml.TOMLDecodeError as exc:
        print(f"{path}: not valid TOML -- {exc} -- ignoring it", file=sys.stderr)
        return None

    return path, data


# Every top-level section this file is read for. A section outside this
# set is reported (as a probable misspelling) when one of these is missing.
KNOWN_SECTIONS = ("conventions", "watch_conditions", "presets", "console", "workspace")


def _load_default_from_section(section: str, *, expect: str = "file") -> Path | None:
    """Shared implementation behind `load_default_conventions` and
    `load_default_watch_conditions` -- both read the exact same shape
    (``[<section>]`` with a string `default` key) out of the exact same
    file, differing only in which section name they read. None covers
    every reason not to use a default: no config file, a config file this
    Python can't parse (no TOML reader), invalid TOML, a missing/
    wrong-shaped `[<section>]`/`default` key, or a `default` path that
    does not exist. The first is silent, and so is a config file with no
    `[<section>]` at all -- most users have no config file, most who do
    set only some of its sections, and neither is a problem. Every other case prints one stderr
    line naming the config file and what was wrong with it, since those
    are configuration the user actually wrote and got wrong, not absence
    -- see the module docstring's "Failure is quiet-but-visible" note.

    `expect` is "file" for the two sections that name one, and "dir" for
    `[presets]`, which names a *library* directory. The only
    difference is the existence check and the wording of the one line it
    prints -- pointing `[presets] default` at a `.chn` file rather than at
    the directory holding it is the obvious mistake to make, and it should
    say so rather than silently finding no presets.
    """
    if expect not in ("file", "dir"):
        raise ValueError(f"expect must be 'file' or 'dir', not {expect!r}")
    read = _read_config()
    if read is None:
        return None
    path, data = read

    # A config file that simply has no `[<section>]` is not a mistake: most
    # people set one or two of these defaults, not all of them, and a line
    # on stderr for every section they left out was printed on every
    # command (seen 2026-09-25 on one engineer's own config, whose missing
    # [presets] section was announced by every step of a desk session).
    # Only a section that IS there and is the wrong shape is reported --
    # or one that is missing while the file carries a section Atoo
    # does not read, which is how a misspelling (`[convention]`) looks.
    if section not in data:
        unknown = sorted(k for k in data if k not in KNOWN_SECTIONS)
        if unknown:
            print(
                f"{path}: no [{section}] section, and "
                + ", ".join(f"[{k}]" for k in unknown)
                + " is not one Atoo reads (it reads "
                + ", ".join(f"[{k}]" for k in KNOWN_SECTIONS)
                + ") -- a misspelling? Ignoring it",
                file=sys.stderr,
            )
        return None
    table = data.get(section)
    if not isinstance(table, dict) or not isinstance(table.get("default"), str):
        print(
            f"{path}: expected a [{section}] section with a `default = \"...\"` "
            "path -- ignoring it",
            file=sys.stderr,
        )
        return None

    default = expand_home(table["default"])
    if expect == "dir":
        if not default.is_dir():
            what = ("is a file, not a directory" if default.is_file() else "does not exist")
            print(f"{path}: default {section} directory {default} {what} -- ignoring it",
                  file=sys.stderr)
            return None
    elif not default.is_file():
        print(f"{path}: default {section} file {default} does not exist -- ignoring it",
              file=sys.stderr)
        return None
    return default


def load_default_conventions() -> Path | None:
    """The `default` path from ``~/.atoo.config``'s `[conventions]`
    section, or None -- see `_load_default_from_section` for the full
    failure-mode accounting."""
    return _load_default_from_section("conventions")


def load_default_watch_conditions() -> Path | None:
    """The `default` path from ``~/.atoo.config``'s
    `[watch_conditions]` section, or None -- same failure
    posture as `load_default_conventions`, see `_load_default_from_section`
    and this module's docstring."""
    return _load_default_from_section("watch_conditions")


def load_default_presets() -> Path | None:
    """The `default` path from ``~/.atoo.config``'s `[presets]`
    section, or None.

    A preset library is a *directory* of `.chn` files, which is the one
    way this differs from `[conventions]` and `[watch_conditions]`. Same
    quiet-but-visible failure posture otherwise.

    House-level rather than per-show, by decision (2026-09-20): a preset library is the
    reusable piece, shared across
    shows, exactly like the conventions file -- so it has no show-bundle
    slot.
    """
    return _load_default_from_section("presets", expect="dir")


def load_default_workspace() -> Path | None:
    """The `default` path from ``~/.atoo.config``'s `[workspace]`
    section, or None -- the working folder `atoo init`
    makes, where `atoo ui`'s file browser and its New show... start
    when no bundle is open. A directory, like `[presets]`; same
    quiet-but-visible failure posture as the rest of this module."""
    return _load_default_from_section("workspace", expect="dir")


def load_console_defaults() -> dict:
    """``[console]`` from ``~/.atoo.config`` --
    ``{"address": str|None, "port": int|None, "timeout": float|None}``.

    The fourth section in this file and the first that names something
    other than a path::

        [console]
        default = "192.0.2.16"
        port = 2223
        timeout = 1.0

    This was asked for from a console session, alongside
    ``ATOO_CONSOLE``: ``--console <ip>`` has to be retyped on every
    ``apply``, ``audit``, ``watch`` and ``ping``, and getting one digit
    wrong on an ``apply --confirm`` is a write aimed at the wrong box on
    the network. An environment variable suits a session; a config file
    suits a desk you always use.

    **Every key is independent and optional**, which is the one way this
    differs from the three path sections. Those have a single `default`
    key and no file at all if it is missing; here, someone may perfectly
    reasonably set a port and no address (a house desk on a non-standard
    port, addressed by ``$ATOO_CONSOLE`` per-show), so a missing or
    malformed key drops *that key* rather than the section.

    Same quiet-but-visible posture as the rest of this module: a wrong
    type prints one line and is ignored, never raises. `port` and
    `timeout` are deliberately not range-checked here -- argparse does
    not range-check the matching flags either, and a config file
    inventing a second set of rules for the same values is how two
    sources of one fact start to drift.
    """
    empty = {"address": None, "port": None, "timeout": None}
    read = _read_config()
    if read is None:
        return empty
    path, data = read

    table = data.get("console")
    if table is None:
        return empty
    if not isinstance(table, dict):
        print(f"{path}: expected a [console] section, not a bare `console` value "
              "-- ignoring it", file=sys.stderr)
        return empty

    out = dict(empty)
    # `default`, not `address`, for one reason: [conventions], [watch_conditions]
    # and [presets] all spell their one setting `default`, and a fourth
    # section that spelled it differently would be a thing to look up.
    if "default" in table:
        if isinstance(table["default"], str) and table["default"].strip():
            out["address"] = table["default"].strip()
        else:
            print(f"{path}: [console] default should be a console address in quotes, "
                  f"e.g. default = \"192.0.2.16\" -- ignoring it", file=sys.stderr)

    if "port" in table:
        # bool before int on purpose: `port = true` is an `int` to
        # isinstance, and would sail through as port 1.
        if isinstance(table["port"], int) and not isinstance(table["port"], bool):
            out["port"] = table["port"]
        else:
            print(f"{path}: [console] port should be a number, e.g. port = 2223 "
                  "-- ignoring it", file=sys.stderr)

    if "timeout" in table:
        if isinstance(table["timeout"], (int, float)) and not isinstance(table["timeout"], bool):
            out["timeout"] = float(table["timeout"])
        else:
            print(f"{path}: [console] timeout should be a number of seconds, e.g. "
                  "timeout = 1.0 -- ignoring it", file=sys.stderr)

    return out


# ----------------------------------------------------------------------
# Writing a section's `default` -- `[conventions]` from the Setup UI's
# step 01 (2026-09-25); `[conventions]`, `[presets]` and `[workspace]`
# from `atoo init`. One line each, and checked.
# ----------------------------------------------------------------------


class ConfigWriteError(Exception):
    """``~/.atoo.config`` could not be changed safely. The message is
    user-facing and says what to do instead; nothing was written."""


# The sections `_set_default` may write. `[watch_conditions]` and
# `[console]` are read-only to Atoo: nothing has asked to write them.
WRITABLE_SECTIONS = ("conventions", "presets", "workspace")


def _table_header(section: str) -> "re.Pattern[str]":
    return re.compile(r"^[ \t]*\[[ \t]*" + re.escape(section) + r"[ \t]*\][ \t]*(#.*)?$")


_ANY_HEADER = re.compile(r"^[ \t]*\[")
_DEFAULT_KEY = re.compile(r"^([ \t]*)default[ \t]*=")


def conventions_default_setting() -> str | None:
    """The raw ``[conventions] default`` string, as written, or None --
    **silently**, and whether or not the file it names exists.

    For a page that has to tell someone what their config says *before*
    offering to change it ("it already names ~/house.md"), where
    `load_default_conventions`'s job -- a usable path or None, with one
    stderr line per problem -- is the wrong answer twice over: a named
    file that has gone missing is still what the config says, and a page
    re-reading this on every request must not print on every request.
    """
    path = config_path()
    if not path.is_file():
        return None
    try:
        data = _toml.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, _toml.TOMLDecodeError):
        return None
    table = data.get("conventions")
    if isinstance(table, dict) and isinstance(table.get("default"), str):
        return table["default"]
    return None


def config_value_for(path: Path) -> str:
    """How ``path`` is written into the config: ``~/...`` under the home
    directory -- the form this file's own docs use, and one that survives
    a home directory being renamed -- and absolute everywhere else."""
    path = Path(path)
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


def _toml_basic_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _without_default(data: dict, section: str, *, drop_empty_table: bool) -> dict:
    """``data`` with `[<section>] default` removed -- the one key the
    edit may change. What is left must be identical before and after."""
    out = copy.deepcopy(data)
    table = out.get(section)
    if isinstance(table, dict):
        table.pop("default", None)
        if drop_empty_table and not table:
            del out[section]
    return out


def set_default_conventions(target: Path, *, replace: bool = False) -> dict:
    """Make ``target`` the ``[conventions] default`` -- see `_set_default`,
    which this is with the section filled in."""
    return _set_default("conventions", target, replace=replace)


def set_default_presets(target: Path, *, replace: bool = False) -> dict:
    """Make the directory ``target`` the ``[presets] default`` (the `atoo init`) -- see `_set_default`."""
    return _set_default("presets", target, replace=replace)


def set_default_workspace(target: Path, *, replace: bool = False) -> dict:
    """Make the directory ``target`` the ``[workspace] default`` -- see `_set_default`."""
    return _set_default("workspace", target, replace=replace)


def _set_default(section: str, target: Path, *, replace: bool = False) -> dict:
    """Make ``target`` the ``[<section>] default`` in
    ``~/.atoo.config``, changing nothing else in that file.
    ``section`` is one of `WRITABLE_SECTIONS`.

    Returns ``{"status", "config_path", "value", "previous", "message"}``.
    `status` is one of:

    * ``created`` -- there was no config file; one was written holding
      only this section.
    * ``added`` -- the file had no ``[<section>] default``; the key (and
      the section header, if that was missing too) was added. Every other
      line is untouched.
    * ``replaced`` -- a different default was there and ``replace`` was
      set; that one line was rewritten.
    * ``unchanged`` -- it already names this file.
    * ``kept`` -- it names a **different** file and ``replace`` was not
      set. Nothing is written: replacing someone's house default is a
      decision, and it is theirs to make out loud (``previous`` says what
      is there, so the caller can ask).

    **The edit is one line, and it is checked.** `tomllib` cannot write,
    and re-serialising the whole file would drop every comment and
    reorder every key, so instead the ``default =`` line inside
    ``[<section>]`` is found and rewritten (or one is inserted under
    the header, or a section is appended). The result is then parsed
    again and compared with the original: if anything other than that one
    value differs -- a multi-line string, a dotted ``<section>.default``
    key, an inline table, anything this line-based edit did not foresee --
    it raises `ConfigWriteError` and the file is left exactly as it was.

    Raises `ConfigWriteError` for a config file that is not valid TOML, a
    Python with no TOML reader, a file that cannot be read or written, or
    an edit that would change more than it should.
    """
    if section not in WRITABLE_SECTIONS:
        raise ValueError(f"Atoo does not write [{section}]")
    target = Path(target)
    path = config_path()
    value = config_value_for(target)
    line = f"default = {_toml_basic_string(value)}"
    # Messages name the file the way a person does -- ~/.atoo.config.
    shown = config_value_for(path)
    result = {"config_path": str(path), "value": value, "previous": None}

    if not path.exists():
        text = f"[{section}]\n{line}\n"
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as exc:
            raise ConfigWriteError(f"couldn't create {shown}: {exc.strerror}") from exc
        return {**result, "status": "created",
                "message": f"Created {shown} with [{section}] {line}."}

    try:
        # newline="": the file's own line endings, CRLF included, so the
        # lines this does not touch are written back exactly as they were.
        with open(path, encoding="utf-8", newline="") as handle:
            original = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigWriteError(f"couldn't read {shown}: {exc} -- nothing was written") from exc
    try:
        data = _toml.loads(original)
    except _toml.TOMLDecodeError as exc:
        raise ConfigWriteError(
            f"{shown} is not valid TOML ({exc}), so it was not touched -- fix it by hand, "
            f"then add [{section}] {line}") from exc

    table = data.get(section)
    if table is not None and not isinstance(table, dict):
        raise ConfigWriteError(
            f"{shown} has a `{section}` value that is not a [{section}] section -- "
            f"not touched; change it by hand to [{section}] {line}")
    existing = table.get("default") if isinstance(table, dict) else None
    if existing is not None:
        result["previous"] = existing if isinstance(existing, str) else repr(existing)
        same = (isinstance(existing, str)
                and expand_home(existing).resolve() == target.resolve())
        if same:
            return {**result, "status": "unchanged",
                    "message": f"{shown} already names {existing} as the default "
                               "-- nothing to change."}
        if not replace:
            return {**result, "status": "kept",
                    "message": f"{shown} already names {result['previous']} as the default "
                               "-- left as it is. Replacing it is a separate, explicit step."}

    lines = original.splitlines(keepends=True)
    header_re = _table_header(section)
    header = next((i for i, text in enumerate(lines)
                   if header_re.match(text.rstrip("\r\n"))), None)
    if header is None:
        if table is not None:
            # `conventions.default = ...` as a dotted key, or an inline
            # table: legal TOML with no header line to edit under.
            raise ConfigWriteError(
                f"{shown} sets `{section}` without a [{section}] header line "
                f"(a dotted key or an inline table) -- not touched; change it by hand "
                f"to [{section}] {line}")
        nl = "\r\n" if "\r\n" in original else "\n"
        sep = "" if not original or original.endswith("\n") else nl
        blank = nl if original.strip() else ""
        updated = f"{original}{sep}{blank}[{section}]{nl}{line}{nl}"
    else:
        end = next((i for i in range(header + 1, len(lines))
                    if _ANY_HEADER.match(lines[i])), len(lines))
        key = next((i for i in range(header + 1, end)
                    if _DEFAULT_KEY.match(lines[i])), None)
        if key is not None:
            indent = _DEFAULT_KEY.match(lines[key]).group(1)
            ending = lines[key][len(lines[key].rstrip("\r\n")):] or "\n"
            lines[key] = f"{indent}{line}{ending}"
        else:
            head = lines[header]
            ending = head[len(head.rstrip("\r\n")):]
            if not ending:  # the header is the file's last line, unterminated
                lines[header] = head + "\n"
                ending = "\n"
            lines.insert(header + 1, f"{line}{ending}")
        updated = "".join(lines)

    try:
        new_data = _toml.loads(updated)
    except _toml.TOMLDecodeError:
        new_data = None
    ok = (
        isinstance(new_data, dict)
        and isinstance(new_data.get(section), dict)
        and new_data[section].get("default") == value
        and _without_default(new_data, section, drop_empty_table=table is None)
        == _without_default(data, section, drop_empty_table=False)
    )
    if not ok:
        raise ConfigWriteError(
            f"{shown} is laid out in a way a one-line edit cannot change safely -- "
            f"not touched; set [{section}] {line} by hand")

    # Written beside the original and renamed over it, so a failure part
    # way through never leaves a half-written config behind.
    try:
        fd, tmp = tempfile.mkstemp(prefix=".atoo.config.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(updated)
            os.chmod(tmp, path.stat().st_mode & 0o7777)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError as exc:
        raise ConfigWriteError(f"couldn't write {shown}: {exc.strerror} -- nothing changed") from exc

    if existing is not None:
        return {**result, "status": "replaced",
                "message": f"Replaced [{section}] default {result['previous']} with "
                           f"{value} in {shown}. Nothing else in it changed."}
    return {**result, "status": "added",
            "message": f"Added [{section}] {line} to {shown}. Nothing else in it changed."}
