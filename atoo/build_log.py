"""Each build's own log file, in `<bundle>/builds/` (the folder was renamed to
`builds/`
on 2026-10-02).

The build log first kept a build's per-role thinking-summary notes and usage
(`ModelCallProgress.build_log_entry()`) as `plan["meta"]["build_log"]`,
folded in by `cli.py`, but plan.json is not the best place to keep
it. The plan is the console spec; the log is a build's own diary, and
it should not grow plan.json by megabytes over a show's life, or vanish
if `plan.json` is later swapped out from under it (an amend, an undo).

So this module gives a build its own file: one per build, named by its
UTC timestamp, holding the same notes/usage this project already had
plus the build's provenance (conventions stack, console model, effort)
and its OUTCOME -- because a build that failed before it ever produced a
plan is exactly the build worth keeping a record of, and it has no
`plan.json` to attach one to.

    <bundle>/builds/2026-09-28T17-33-05Z.json
    <bundle>/builds/2026-09-28T18-05-41Z.json
    ...

**The newest five are kept** (`prune.KEEP`: the builds, journals, and logs
directories are continually pruned to a max of 5 entries each). `write` prunes straight
after writing, so the
folder never holds more. The log `plan.json` (or `plan.previous.json`)
points to is protected -- a run of failed builds cannot prune away the
log of the plan the bundle still holds -- and takes one of the five
places rather than adding a sixth. `atoo lessons` therefore reads at
most five builds.

`plan.json` keeps only a pointer, `meta.build_log_file`, a path relative
to the directory this log file lives beside (the bundle, or wherever
`--out` pointed with no bundle -- see `directory_for`). A plan built
before this shipped may still carry the old, inline `meta.build_log`;
nothing here requires it to be migrated, and `resolve` reads either
shape.

**Never fed back into a prompt.** That was always the rule
(`generate._plan_for_prompt`, `patch._base_for_prompt`) and it still
holds: a build log, wherever it lives, is for a human (`atoo
lessons`, the Setup UI's "Build log" fold), never for a model.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from atoo import prune as prune_module
from atoo.bundle import BUILDS, PLAN, PLAN_PREVIOUS

DIRNAME = BUILDS

# Outcomes a build log can record. "done" covers a build that produced a
# plan, whether or not verify found errors in it -- that is `plan.json`'s
# own `meta.verify_findings`'s business, not this log's.
DONE = "done"
FAILED = "failed"
STOPPED = "stopped"


def timestamp_name(now: datetime | None = None) -> str:
    """A filesystem-safe UTC timestamp filename, e.g.
    `2026-09-28T17-33-05Z.json` -- `datetime.isoformat()`'s colons
    replaced, since a bare `:` is awkward on more than one platform and
    this name is meant to be draggable like the rest of a bundle."""
    when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return when.strftime("%Y-%m-%dT%H-%M-%SZ") + ".json"


def directory_for(*, bundle_dir: Path | None, out_path: Path | None) -> "Path | None":
    """Where this build's log goes. A bundle (`--show`) wins over
    `--out` even when `--out` points somewhere else -- into
    the bundle when there is one -- since the bundle is the one thing a
    show's builds are collected under. With no bundle, the log sits next
    to whatever `plan.json` was (or would have been) written to.

    `None` when there is NEITHER a bundle nor a real file to sit beside
    (`--out -`, the "print to stdout, write nothing" contract): falling
    back to the current directory would write into wherever the process
    happens to be running FROM, which is never right, and `--out -`
    already promises nothing lands on disk -- the build log keeps that
    promise rather than becoming the one file that quietly still does."""
    if bundle_dir is not None:
        return bundle_dir / DIRNAME
    if out_path is not None:
        return out_path.parent / DIRNAME
    return None


def pointer(directory: Path, file_path: Path) -> str:
    """`meta.build_log_file`'s value: the log's path relative to
    `directory`'s PARENT (the bundle, or the base `directory_for` used) --
    always `builds/<name>`, since `directory` is always
    `<base>/builds`."""
    return f"{DIRNAME}/{file_path.name}"


def write(directory: Path, payload: dict) -> Path:
    """Write `payload` as one build's log, atomically (a temp file,
    renamed into place -- the same pattern `cli._dump_state_file` and
    `config.py` use, so a reader never sees a half-written file), then
    prune the folder to the newest `prune.KEEP` (`prune_dir`). Returns
    the path written."""
    directory.mkdir(parents=True, exist_ok=True)
    name = timestamp_name()
    target = directory / name
    # A second build within the same second would collide; make the name
    # unique rather than silently overwrite an earlier build's log.
    n = 1
    while target.exists():
        target = directory / f"{name[:-5]}-{n}.json"
        n += 1
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    prune_dir(directory)
    return target


def _pointed_at(directory: Path) -> set[str]:
    """The log file names the plans beside `directory` point to
    (`meta.build_log_file` in `plan.json` and `plan.previous.json`), which
    pruning must not remove."""
    names: set[str] = set()
    for plan_name in (PLAN, PLAN_PREVIOUS):
        try:
            meta = json.loads((directory.parent / plan_name).read_text(encoding="utf-8")).get("meta")
        except (OSError, ValueError, AttributeError):
            continue
        value = meta.get("build_log_file") if isinstance(meta, dict) else None
        if isinstance(value, str) and value.startswith(DIRNAME + "/"):
            names.add(value[len(DIRNAME) + 1:])
    return names


def prune_dir(directory: Path) -> list[Path]:
    """Keep the newest `prune.KEEP` build logs in `directory`, protecting
    the one(s) the bundle's plans point to. Returns what was deleted."""
    return prune_module.prune(directory, prune_module.file_key(".json"),
                              protect=_pointed_at(directory))


def build_entry(*, meta: dict, build_log: dict, status: str, reason: str | None) -> dict:
    """The payload `write` saves: this build's provenance (lifted
    straight out of `plan["meta"]` as `cli._build` assembles it, so the
    two never drift apart), the per-role notes/usage an earlier change kept, and
    the outcome. `status` is one of `DONE`/`FAILED`/`STOPPED`."""
    return {
        "generated_at": meta.get("generated_at"),
        "console_model": meta.get("console_model"),
        "conventions_stack": meta.get("conventions_stack"),
        "model": meta.get("model"),
        "effort": meta.get("effort"),
        "outcome": {"status": status, "reason": reason},
        "build_log": dict(build_log) if build_log else {},
    }


def rewrite(path: Path, payload: dict) -> None:
    """Overwrite an EXISTING log file at exactly `path`, atomically. For
    the one case a build revisits its own log after writing it: the
    watchlist draft runs after the plan (and this file) are already on
    disk, and may add its own `build_log["watchlist"]` entry -- folded
    into the same file rather than a second one, since it is still the
    same build."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_all(directory: Path) -> list[dict]:
    """Every log file in `directory`, newest first, each with `file` (its
    filename, for a report to cite) and `path` added. Filenames sort
    correctly as timestamps (`read_all` still re-sorts, since a manual
    rename or a `-1` collision suffix could otherwise reorder them). A
    file that is not valid JSON is skipped -- a log mid-write, or one
    dropped in by hand -- rather than raising: reading a bundle's history
    should not fail because one build's diary is malformed."""
    if not directory.is_dir():
        return []
    out: list[dict] = []
    for path in directory.iterdir():
        if path.suffix != ".json" or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            entry = dict(data)
            entry["file"] = path.name
            entry["path"] = str(path)
            out.append(entry)
    out.sort(key=lambda e: e["file"], reverse=True)
    return out


def resolve(plan: dict, base_dir: Path) -> dict | None:
    """This plan's build log, whichever shape it carries: the inline
    `meta.build_log` a plan built before this shipped still has, or the
    file `meta.build_log_file` points to (read relative to `base_dir` --
    the bundle directory, or the directory holding `plan.json` with no
    bundle). Returns the `{role: {notes, usage}}` shape an earlier change
    established either way, or `None` when the plan has neither."""
    meta = plan.get("meta") if isinstance(plan, dict) else None
    if not isinstance(meta, dict):
        return None
    inline = meta.get("build_log")
    if isinstance(inline, dict):
        return inline
    pointer_value = meta.get("build_log_file")
    if isinstance(pointer_value, str) and pointer_value:
        try:
            data = json.loads((base_dir / pointer_value).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        build_log = data.get("build_log") if isinstance(data, dict) else None
        return build_log if isinstance(build_log, dict) else None
    return None


def resolve_full(plan: dict, base_dir: Path) -> dict | None:
    """The full log entry (provenance + outcome + build_log) for the
    plan's CURRENT build log, when it lives in its own file. For an old
    plan with only the inline `meta.build_log`, there is no separate
    file to read the rest from, so this returns `None` -- callers fall
    back to what the plan's own `meta` already carries."""
    meta = plan.get("meta") if isinstance(plan, dict) else None
    if not isinstance(meta, dict):
        return None
    pointer_value = meta.get("build_log_file")
    if not (isinstance(pointer_value, str) and pointer_value):
        return None
    try:
        data = json.loads((base_dir / pointer_value).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
