"""Which conventions file a plan was built from, recorded so it can be
found again.

A generated plan file includes a relative
(to the show bundle directory) file name reference to the conventions
file that was incorporated in the build, such that it can be loaded by
the UI when a show bundle is loaded.

`atoo build` has recorded `meta.conventions_stack`, but
each layer's `path` was whatever string was typed -- cwd-relative or
absolute -- so it resolved from nowhere in particular, and nothing read
it back. This module adds three keys to every layer, beside the three
that were there (never instead of them, so an old reader is unaffected):

* ``absolute_path`` -- the file as an absolute path, lexically
  (`os.path.abspath`, no symlink resolution: the path the engineer
  reaches it by, not the one the filesystem stores).
* ``bundle_relative_path`` -- the same file relative to the show bundle
  directory, e.g. ``../house-rules.md``. The house file deliberately
  lives *outside* the bundle, so a leading ``..`` is the normal case.
  ``None`` when the build ran without a bundle (``--input``/``--out``
  only): there is no directory for it to be relative to, and inventing
  one would be a path that quietly means something else.
* ``sha256`` -- the file's bytes as built. A plan naming a file that has
  been edited since would otherwise load conventions that did not
  produce it, and nothing could tell.

The same record is what `webui._build_payload` puts on its stack
entries, so the page and a built plan stay key for key.

Old plans carry none of the three. `recorded_conventions` returns None
for them, and the UI opens them exactly as it did before -- the
bare `path` of an old plan is not trusted, because it was relative to
a working directory nobody recorded.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def file_sha256(path: "str | Path") -> str | None:
    """Hex sha256 of a file's bytes, or None when it cannot be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def layer_record(path: "str | Path", bundle_dir: "str | Path | None") -> dict:
    """`{absolute_path, bundle_relative_path, sha256}` for one layer."""
    absolute = os.path.abspath(os.path.expanduser(str(path)))
    relative = None
    if bundle_dir is not None:
        try:
            relative = os.path.relpath(absolute, os.path.abspath(str(bundle_dir)))
        except ValueError:
            # Different drives on Windows: there is no relative spelling.
            relative = None
    return {
        "absolute_path": absolute,
        "bundle_relative_path": relative,
        "sha256": file_sha256(absolute),
    }


def recorded_conventions(plan: object) -> dict | None:
    """The plan's recorded house-conventions layer, or None.

    None for anything that is not a plan with a recorded layer: no `meta`,
    no `conventions_stack`, or a stack entry that predates the record (no
    `absolute_path` and no `bundle_relative_path`).
    """
    if not isinstance(plan, dict):
        return None
    meta = plan.get("meta")
    if not isinstance(meta, dict):
        return None
    stack = meta.get("conventions_stack")
    if not isinstance(stack, list):
        return None
    for layer in stack:
        if not isinstance(layer, dict) or layer.get("role") != "conventions":
            continue
        if layer.get("bundle_relative_path") or layer.get("absolute_path"):
            return layer
        return None
    return None


def resolve_recorded(layer: dict, bundle_dir: "str | Path | None") -> tuple[Path | None, str | None]:
    """Where a recorded layer's file is now: `(path, how)`.

    `how` is ``"relative"`` when it was found relative to the bundle --
    the issue's route, and the one that survives a bundle and its house
    file moving together -- ``"absolute"`` when only the recorded
    absolute path still holds a file (the bundle moved, the house file
    did not), and None with a None path when neither does.
    """
    relative = layer.get("bundle_relative_path")
    if relative and bundle_dir is not None:
        candidate = Path(os.path.normpath(os.path.join(os.path.abspath(str(bundle_dir)), relative)))
        if candidate.is_file():
            return candidate, "relative"
    absolute = layer.get("absolute_path")
    if absolute and Path(absolute).is_file():
        return Path(absolute), "absolute"
    return None, None


def same_file(a: "str | Path | None", b: "str | Path | None") -> bool:
    """Whether two paths name one file -- by inode when both exist, else
    by their normalised absolute spelling."""
    if a is None or b is None:
        return False
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.abspath(os.path.expanduser(str(a))) == os.path.abspath(os.path.expanduser(str(b)))
