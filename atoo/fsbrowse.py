"""The Setup UI's file browser, server side.

A browser page cannot look at the local disk -- that is the whole of the
browser's security model -- so `atoo ui`'s modal file browser asks
the server, which is running on the same laptop as the operator, to list
a folder for it. This module is that listing, plus the one thing the
browser may create through it (a folder), plus the two checks that keep
either from being reachable by anyone but the person at this laptop's
own browser. The HTTP endpoints are in `atoo/webui.py`
(`GET /api/fs/list`, `POST /api/fs/mkdir`); nothing here imports FastAPI,
so every rule below is testable as a plain function.

**Read-only, and names only.** A listing is names, types, sizes and
modification times. It never opens a file -- not to sniff it, not to
count its rows -- because a directory listing is the most an endpoint
that answers any path on the disk should hand out. (The Build tiles do
read a file's contents, but only one the operator chose, through
`POST /api/build/sources/load`.)

**Filtered by what the dialog is for.** `kind` names which files the
dialog offers: `md` for a conventions or instructions file, `csv` for an
input list, `json` for a plan or a watchlist, `folders` for choosing a
show bundle (no files at all), and `any`. Folders are always listed,
because they are how you get anywhere. Files the filter hides are
counted, not silently dropped, so an empty-looking folder can say "3
other files".

**Hidden entries are hidden by default** -- dot-files, the way every file
manager on the machines this runs on shows a home folder -- and counted,
with a toggle. **Folders sort first**, then names case-insensitively.

**Symlinks are shown, and resolved without being trusted.** A link's
type is its TARGET's (a link to a folder is a folder you can open), and
the entry says it is a link and where it points. A broken link, or one
in a loop, is listed as `broken` and cannot be opened -- one bad entry
must not turn a whole folder into an error.

**Every failure is a sentence, never a 500.** A folder that is not there,
cannot be read, or is a file is a `ListingError` whose message the modal
shows in place of the listing, with a way back up.

**Only this laptop's own browser may use it** (`client_is_local`,
`host_is_local`). `atoo ui --host` can bind a LAN interface, which is
a legitimate thing to do with the read-mostly Watch page; letting a
second machine on the venue network page through this laptop's home
folder is not. So the listing and folder creation refuse a request from a
non-loopback address rather than the server refusing to start -- the
Watch page stays reachable, the disk does not. The `Host` header must be
a loopback name as well, which is what stops a web page elsewhere from
reaching this server through DNS rebinding (a hostile name re-pointed at
127.0.0.1 is a same-origin page as far as the browser knows; its `Host`
header still carries the hostile name).
"""

from __future__ import annotations

import ipaddress
import os
import stat
from pathlib import Path

from atoo import bundle, config

#: What each `kind` offers. `None` is "every file"; an empty tuple is "no
#: files, only folders".
KINDS: dict[str, "tuple[str, ...] | None"] = {
    "folders": (),
    "md": (".md",),
    "csv": (".csv",),
    "json": (".json",),
    "any": None,
}

#: A folder with this many entries is listed up to here and says it was
#: cut short. A modal is not the tool for a 40,000-file folder, and
#: stat-ing all of it would stall the page.
MAX_ENTRIES = 2000

_LOCAL_HOST_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}


class ListingError(Exception):
    """A folder that cannot be listed, said in words the modal shows."""


def _is_loopback_address(host: str) -> bool:
    host = (host or "").strip().strip("[]")
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def client_is_local(client_host: "str | None") -> bool:
    """True when the request came from this machine's own loopback
    interface. An IPv4-mapped IPv6 loopback (`::ffff:127.0.0.1`) counts."""
    if not client_host:
        return False
    if _is_loopback_address(client_host):
        return True
    try:
        address = ipaddress.ip_address(client_host.strip("[]"))
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def host_is_local(host_header: "str | None") -> bool:
    """True when the request's `Host` header names this machine by a
    loopback name or address -- `127.0.0.1:8420`, `localhost:8420`,
    `[::1]:8420`. Anything else is a page that reached a loopback server
    under another name (DNS rebinding), or a proxy we know nothing about."""
    if not host_header:
        return False
    host = host_header.strip()
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else host[1:]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    host = host.lower().rstrip(".")
    return host in _LOCAL_HOST_NAMES or _is_loopback_address(host)


def resolve_path(raw: "str | None", base: "Path | None" = None) -> Path:
    """What the operator typed, as an absolute path: `~` expanded (the way
    `config.expand_home` does it, so a test's home is honoured), a
    relative path taken against `base` -- the folder the dialog is showing
    -- or the server's working directory. Not `resolve()`d: a symlinked
    folder keeps the name it was opened by, which is the name the
    operator will recognise."""
    text = (raw or "").strip()
    if not text:
        return Path.home()
    if any(ord(ch) < 32 for ch in text):
        raise ListingError("that path has a control character in it")
    path = config.expand_home(text)
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return Path(os.path.normpath(str(path)))


def display_path(path: Path) -> str:
    """`~/shows/festival` for anything under the home folder, the plain
    path otherwise -- the same shortening the Build tiles use."""
    try:
        rel = path.relative_to(Path.home())
    except ValueError:
        return str(path)
    return "~" if str(rel) == "." else f"~/{rel}"


def _entry(directory: Path, name: str, kind_suffixes, want_bundle_marks: bool) -> "dict | None":
    full = directory / name
    try:
        lst = os.lstat(full)
    except OSError:
        return None
    is_link = stat.S_ISLNK(lst.st_mode)
    entry = {
        "name": name,
        "path": str(full),
        "hidden": name.startswith("."),
        "symlink": is_link,
    }
    st = lst
    if is_link:
        try:
            target = full.resolve(strict=True)
            st = os.stat(full)
            entry["target"] = str(target)
        except (OSError, RuntimeError):
            entry.update(type="broken", size=None, mtime=None, matches=False)
            return entry
    if stat.S_ISDIR(st.st_mode):
        entry.update(type="dir", size=None, mtime=st.st_mtime, matches=True)
        if want_bundle_marks:
            # A folder that already holds a bundle's own files is worth
            # marking when the dialog is choosing a show: it is the
            # difference between opening a show and adopting a folder.
            try:
                entry["bundle"] = any((full / slot).is_file() for slot in
                                      (bundle.INPUT_LIST, bundle.INSTRUCTIONS, bundle.PLAN))
            except OSError:
                entry["bundle"] = False
    else:
        suffix = Path(name).suffix.lower()
        matches = kind_suffixes is None or suffix in kind_suffixes
        entry.update(type="file", size=st.st_size, mtime=st.st_mtime, matches=matches)
    return entry


def list_directory(raw_path: "str | None", kind: str = "any", show_hidden: bool = False,
                   base: "str | None" = None) -> dict:
    """One folder, listed for the modal. `raw_path` may name a FILE, in
    which case its folder is listed and the file comes back as `selected`
    -- which is how the dialog opens on "the folder of the file this tile
    shows" with that file already highlighted, and how a path pasted into
    the dialog's path field lands on the file it names.

    Raises `ListingError` for a kind it does not know, a path that is not
    there, and a folder it may not read."""
    if kind not in KINDS:
        raise ListingError(f"unknown kind {kind!r} -- one of: {', '.join(KINDS)}")
    suffixes = KINDS[kind]
    path = resolve_path(raw_path, Path(base) if base else None)
    selected = None
    if not path.exists():
        if path.is_symlink():
            raise ListingError(f"{display_path(path)} is a link to something that is not there")
        raise ListingError(f"there is nothing at {display_path(path)}")
    if not path.is_dir():
        selected = path.name
        path = path.parent
    try:
        names = os.listdir(path)
    except PermissionError:
        raise ListingError(f"you do not have permission to read {display_path(path)}")
    except OSError as exc:
        raise ListingError(f"couldn't read {display_path(path)}: {exc.strerror or exc}")

    entries = []
    hidden_count = 0
    other_files = 0
    truncated = False
    for name in names:
        if name.startswith(".") and not show_hidden:
            hidden_count += 1
            continue
        entry = _entry(path, name, suffixes, kind == "folders")
        if entry is None:
            continue
        if entry["type"] == "file" and (suffixes == () or not entry["matches"]):
            other_files += 1
            continue
        if len(entries) >= MAX_ENTRIES:
            truncated = True
            break
        entries.append(entry)
    order = {"dir": 0, "broken": 1, "file": 2}
    entries.sort(key=lambda e: (order.get(e["type"], 3), e["name"].casefold(), e["name"]))

    parent = path.parent if path.parent != path else None
    return {
        "path": str(path),
        "display_path": display_path(path),
        "parent": str(parent) if parent is not None else None,
        "home": str(Path.home()),
        "sep": os.sep,
        "kind": kind,
        "show_hidden": bool(show_hidden),
        "hidden_count": hidden_count,
        "other_files": other_files,
        "truncated": truncated,
        "writable": os.access(path, os.W_OK),
        "selected": selected,
        "entries": entries,
    }


def make_folder(raw_path: "str | None", base: "str | None" = None) -> Path:
    """Create ONE new folder. The dialog's New folder button, and the
    only thing the file browser writes.

    Refused, with a sentence, when: the path is empty; something is
    already there (a folder or a file -- never "opened instead", which is
    `POST /api/bundle/open`'s job and says so); the folder it would go in
    does not exist (one level at a time, so a typo two levels up is not
    silently built out); or the OS says no."""
    text = (raw_path or "").strip()
    if not text:
        raise ListingError("give a name for the new folder")
    if text.replace("\\", "/").rstrip("/").split("/")[-1] in ("", ".", ".."):
        raise ListingError(f"{text!r} is not a folder name")
    path = resolve_path(text, Path(base) if base else None)
    if path.exists() or path.is_symlink():
        what = "a folder" if path.is_dir() else "a file"
        raise FileExistsError(f"there is already {what} called {path.name} in "
                              f"{display_path(path.parent)} -- nothing was created")
    if not path.parent.is_dir():
        raise ListingError(f"there is no folder {display_path(path.parent)} -- nothing was "
                           "created")
    try:
        path.mkdir()
    except FileExistsError:
        raise FileExistsError(f"there is already something called {path.name} in "
                              f"{display_path(path.parent)} -- nothing was created")
    except PermissionError:
        raise ListingError(f"you do not have permission to create a folder in "
                           f"{display_path(path.parent)}")
    except OSError as exc:
        raise ListingError(f"couldn't create {display_path(path)}: {exc.strerror or exc}")
    return path
