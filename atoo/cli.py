"""atoo -- CLI entry points.

Subcommands, with one wrinkle: `atoo --help` splices every
subcommand's own options into a single screen rather than making you
find them behind `atoo <cmd> --help`. That indirection was the
actual complaint behind "the input, conventions, out and pretty are
totally missing" (2026-09-10); subcommands themselves are fine and
needed, since apply (O2/O3) and watch (O4/O6) each carry their own
argument sets.
"""

from __future__ import annotations

import argparse
import dataclasses
import errno
import json
import os
import re
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from atoo import bundle
from atoo import build_log as build_log_module
from atoo import console_facts as facts
from atoo import conventions_audit
from atoo import install_info
from atoo import instructed_channels
from atoo import conventions_ref
from atoo import conventions_text
from atoo import conventions_resolve
from atoo import category_table as category_table_module
from atoo import lessons
from atoo import plan_freshness
from atoo import plan_diff
from atoo.config import (
    config_path, config_value_for, expand_home, load_console_defaults, load_default_conventions,
    load_default_presets, load_default_watch_conditions, load_default_workspace,
)
from atoo import input_list as input_list_module
from atoo.input_list import InputListError, load_input_list
from atoo.render import render_plan
from atoo import generate
from atoo import diagnostics
from atoo import plan_schema
from atoo import preset_expand
from atoo import finding_groups
from atoo.ai_provider import AIProviderError, provider_from_env
from atoo.progress import BuildStopped, check_stopped, stopped_message
from atoo.snapshot import SnapshotError, compare_snapshot, load_snapshot
from atoo.verify_plan import resolve_console_model, verify_plan
from atoo import report


class _LoadError(Exception):
    """A clean, already-user-facing message for a conventions source that
    couldn't be loaded -- raised by _resolve_conventions so build() has
    one error-formatting path rather than duplicating it per source kind."""


def _emit_diagnostics(diags, heading: str | None = None) -> None:
    """The one place build-time diagnostics reach a human.

    Replaces five separate `print(f"  - {x}")` loops that rendered four
    different structured types and two bare-string streams as the same
    undifferentiated bullet -- so a limitation of Atoo's own
    compiler looked exactly like a mistake in the engineer's conventions
    file. Severity-labelled and blocked now, worst first, with the `fix`
    and tracking-issue lines the types didn't previously carry.
    """
    text = diagnostics.render(diags, heading=heading)
    if text:
        print(text, file=sys.stderr)


def _readable_partial(text: str) -> str:
    """A saved `.partial`, pretty-printed when it is whole JSON (the
    generator writes its reply on one line) and as it arrived otherwise."""
    try:
        return json.dumps(json.loads(text), indent=2)
    except (TypeError, ValueError):
        return text


def _note_diagnostic(note) -> diagnostics.Diagnostic:
    """A generated plan's `notes` entry, at the render boundary.

    `plan["notes"]` entries are `{text, source}` objects.
    They are the model's own account of what it could not do, so they
    arrive as prose with a provenance tag rather than as structured
    diagnostics, and this is where they join the one renderer.

    This once had to recover a severity from the compile
    path's bare strings; that path is gone, and with it the
    prefix-sniffing that did it.
    """
    if isinstance(note, diagnostics.Diagnostic):
        return note
    source = note.get("source", "") if isinstance(note, dict) else ""
    # No `code`: this stream genuinely has no stable codes, and inventing
    # a placeholder one would put "(plan.note)" under every single line
    # while telling a reader nothing. The renderer omits an empty code.
    # A `repair` note says how a slip in the reply was read: a build
    # detail (`finding_groups.DETAIL_NOTE_SOURCES`), never a warning.
    detail = finding_groups.is_detail_note(note)
    return diagnostics.Diagnostic(
        severity=diagnostics.Severity.INFO if detail else diagnostics.Severity.WARNING,
        code="",
        # note_line() prefixes the source tag when there is one, so a
        # note keeps saying which pass produced it.
        message=plan_schema.note_line(note),
        source=source or "build",
    )


SHOW_HELP = (
    "A show bundle: one directory holding everything for this show, under fixed "
    "filenames (input.csv, instructions.md, plan.json, watch.json, "
    "and a journals/ directory of every write in time order) with "
    "no manifest to maintain. Each command takes the pieces it "
    "needs from the directory instead of being handed them one flag at a time, and "
    "everything a run produces is written back into it. An explicit flag always wins over "
    "the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/"
)


def _add_console_model_argument(ap: argparse.ArgumentParser, *, extra: str = "") -> None:
    """The socket counts that decide whether a plan is patchable
    differ between the three WING models (the Full has 8 local inputs and
    local aux jacks; the Rack and Compact have 24 local inputs and no aux
    jacks at all), and the OSC address tree is identical on all three, so
    nothing can infer this -- it has to be stated. Unknown is a hard stop.
    """
    ap.add_argument(
        "--console-model",
        choices=sorted(facts.CONSOLE_MODELS),
        default=None,
        help="Which WING this plan is for. Required unless the plan already "
             "states it in meta.console_model (a plan built by Atoo does). "
             "Socket counts differ between models, so an unstated model is an "
             "error rather than an assumption." + extra)


def _console_model_of_show(show: "bundle.Bundle") -> tuple[str, str] | None:
    """The console model a show's own plan states, and which file said so.

    The current `plan.json` first; the plan a rebuild moved aside
    (`plan.previous.json`) next, because a build that failed or was stopped
    leaves only that one and the retry should not have to be told again.
    None when neither exists or neither states a model.
    """
    for name in (bundle.PLAN, bundle.PLAN_PREVIOUS):
        path = show.directory / name
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stated = resolve_console_model(plan) if isinstance(plan, dict) else None
        if stated:
            return stated, name
    return None


def _add_show_argument(ap: argparse.ArgumentParser) -> None:
    """`--show DIR` -- identical on every command that takes it."""
    ap.add_argument("--show", default=None, metavar="DIR", help=SHOW_HELP)


def _open_bundle(args: argparse.Namespace):
    """The `--show` directory as a `bundle.Bundle`, or None when not given.

    Raises `bundle.BundleError` with an already-user-facing message, the
    same contract `_LoadError` has.
    """
    show = getattr(args, "show", None)
    return bundle.load(show) if show else None


def _plan_layers(plan: dict, show, plan_path):
    """The conventions and instructions `plan` was built from, for
    verify's check of a channel built from them
    (`instructed_channels.layers_from_plan`): the files its
    `meta.conventions_stack` records, found relative to the bundle (or
    the plan's own directory), and the bundle's instructions.md."""
    bundle_dir = show.directory if show is not None else (
        Path(plan_path).parent if plan_path else None)
    instructions = None
    if show is not None:
        instructions = show.optional(bundle.INSTRUCTIONS)
    elif bundle_dir is not None:
        instructions = Path(bundle_dir) / bundle.INSTRUCTIONS
    return instructed_channels.layers_from_plan(plan, bundle_dir, instructions)


def _fill_from_bundle(args: argparse.Namespace, b, attr: str, slot: str,
                      *, required: bool = False) -> None:
    """Point one argument at its bundle slot, unless the user stated it.

    **Explicit flags always win** -- the same precedence
    `--watch-conditions` already has over `~/.atoo.config`'s default, and
    the reason `--show DIR --plan somewhere-else.json` reads the plan you
    named rather than the bundle's.

    An absent optional slot leaves the argument alone, so the command's
    own existing fallbacks (auto-detect, the config default) still run
    behind it.
    """
    if b is None or getattr(args, attr, None):
        return
    path = b.require(slot) if required else b.optional(slot)
    if path is not None:
        setattr(args, attr, str(path))


def _discover_files(directory: Path) -> tuple[list[Path], list[Path]]:
    """*.csv and *.md (excluding README, any case) directly in `directory`
    -- the "what's here to build" scan the easy-button mode (no
    --input/--conventions given) uses.

    `*.rules.json` used to count as a conventions source too; the rules IR
    was an artifact of the extraction+compile path, retired.
    """
    csv_paths = sorted(directory.glob("*.csv"))
    md_paths = sorted(p for p in directory.glob("*.md") if p.name.lower() != "readme.md")
    return csv_paths, md_paths


def _auto_detect(directory: Path) -> tuple[Path, Path] | None:
    """The easy-button case: exactly one input list and exactly one
    conventions file sitting in `directory`. Returns (input, conventions),
    or None if the directory isn't unambiguous -- the caller is
    responsible for explaining why not."""
    csv_paths, md_paths = _discover_files(directory)
    if len(csv_paths) == 1 and len(md_paths) == 1:
        return csv_paths[0], md_paths[0]
    return None


def _print_discovery_guidance(directory: Path) -> None:
    csv_paths, md_paths = _discover_files(directory)
    where = "current directory" if directory == Path(".") else str(directory)
    if not csv_paths:
        print(f"no --input given, and no .csv input list found in the {where} -- "
              f"pass --input explicitly, or cd to a directory with one "
              f"(see https://docs.atoo.app/build/build-a-show/)", file=sys.stderr)
        return
    if not md_paths:
        print(f"no --conventions given, and no conventions file (.md) "
              f"found in the {where} -- pass one explicitly", file=sys.stderr)
        return
    print(f"ambiguous: {len(csv_paths)} input list(s) and {len(md_paths)} "
          f"conventions file(s) found in the {where} -- run with explicit files, e.g.:", file=sys.stderr)
    for p in csv_paths:
        print(f"  {p.name}", file=sys.stderr)
    for p in md_paths:
        print(f"  {p.name}", file=sys.stderr)
    print(f"\n  atoo --input {csv_paths[0]} --conventions {md_paths[0]}", file=sys.stderr)


def _default_out_path(input_path: str, conventions_path: str) -> Path:
    """<input-stem>+<conventions-stem>.plan.json in the current directory
    -- what --out defaults to when not given, so running Atoo always
    produces a file you can find afterward instead of only console
    output ("no output file" was flagged twice: 2026-09-10 against the
    old `sandbox` subcommand, and again after this file's own default
    reverted to stdout-only when `sandbox` was folded into `build`)."""
    input_stem = Path(input_path).stem
    conventions_stem = Path(conventions_path).stem
    return Path(f"{input_stem}+{conventions_stem}.plan.json")


def _findings_meta(result) -> dict | None:
    """`{"errors": [...], "warnings": [...]}` of plain dicts for a
    `verify_plan.VerifyResult`, or None when `result` is None.

    Mirrors `report.verify_at_generation_status()`'s None-means-"didn't
    run" convention, but for the raw findings rather than a summary --
    used for `meta.verify_findings`, which is None on --skip-verify.
    """
    if result is None:
        return None
    return {
        "errors": [f.to_dict() for f in result.errors],
        "warnings": [f.to_dict() for f in result.warnings],
        # 2026-09-25: the notes -- values decided where the conventions
        # were silent (`inferred.py`), and things declared that nothing
        # uses. The Setup UI's step-04 dock reads this key too.
        "info": [f.to_dict() for f in result.infos],
    }


def build(args: argparse.Namespace) -> int:
    """`atoo build`, and what a stop means for it.

    A build can be stopped two ways: Ctrl-C in a terminal, and the Setup
    UI's Stop (`progress.StopSignal`, which ends the model call by closing
    its connection and raises `BuildStopped`). Either way the answer is
    the same sentence, without a traceback, and it is only ever true: a
    stopped call returns no text, no `.partial.json` file is saved for it (that
    is for a call that FAILED, whose partial is the evidence of why), and
    plan.json and watch.json are each written only after a last
    `check_stopped()`. `written` records what did land before the stop --
    the plan is written before the watchlist draft is asked for, so a stop
    during the draft leaves a new plan.json, and the sentence says so.
    Exit 130, the shell's own code for an interrupted command."""
    import time as _time

    written: list[str] = []
    started = _time.monotonic()
    # `_build` fills this in as it learns each piece (the bundle, if
    # any; the console model; the conventions stack; the provider) so
    # that a stop or a Ctrl-C caught HERE -- before `_build` ever reaches
    # its own "done" build-log write -- can still write a "stopped" log
    # (build-log.py's `STOPPED`) with whatever provenance was known.
    # `ctx["logged"]` is set True the moment `_build` writes a log of its
    # own, so a stop that lands AFTER a plan already logged (e.g. during
    # the bonus watchlist draft) is not also reported as a second,
    # misleading "stopped" log for a build that in fact succeeded.
    ctx: dict = {}
    try:
        return _build(args, written, ctx)
    except (KeyboardInterrupt, BuildStopped) as exc:
        how = "" if isinstance(exc, BuildStopped) else " (Ctrl-C)"
        print("", file=sys.stderr)
        print(stopped_message(_time.monotonic() - started, written, how=how),
              file=sys.stderr, flush=True)
        if not ctx.get("logged"):
            reason = (str(exc) or "stopped by you") if isinstance(exc, BuildStopped) else "Ctrl-C"
            _write_build_log(ctx, status=build_log_module.STOPPED, reason=reason)
        return 130


def _write_build_log(ctx: dict, *, status: str, reason: str | None,
                     meta: "dict | None" = None) -> "Path | None":
    """Write one build's log file (`build_log.py`) from what `ctx` (or a
    fully-assembled `plan['meta']`, once there is one) knows, and mark
    `ctx["logged"]` so a later stop is not ALSO reported as a build that
    never logged anything. Shared by three callers: a generation failure
    (no `meta` yet -- this builds a minimal one from `ctx`), `_build`'s
    own success path (passes the real, already-assembled `plan['meta']`),
    and a stop caught in `build()` after `_build` raised out without
    reaching either of those.

    Never raises: a build log is a courtesy kept for a human reviewing a
    batch of builds later (`atoo lessons`) -- losing it must never
    turn a clean stop, or a generation failure already reported on
    stderr, into a second, unrelated traceback."""
    try:
        provider = ctx.get("provider")
        build_log_data = getattr(provider, "build_log", None) or {}
        directory = build_log_module.directory_for(
            bundle_dir=ctx.get("bundle_dir"), out_path=ctx.get("out_path"))
        if directory is None:
            # `--out -` with no bundle: nothing is written for the plan
            # either, and there is no sensible directory to fall back to
            # (`directory_for`'s own docstring). `ctx["logged"]` stays
            # unset on purpose, so a LATER stop -- one that DOES resolve
            # a directory (a stop can land after `--out`/`--show` become
            # known) -- still gets to try.
            return None
        if meta is None:
            meta = {
                "generated_at": _now_iso(),
                "console_model": ctx.get("console_model"),
                "conventions_stack": ctx.get("conventions_stack"),
                "model": getattr(provider, "model", None),
                "effort": None,
            }
        entry = build_log_module.build_entry(
            meta=meta, build_log=build_log_data, status=status, reason=reason)
        path = build_log_module.write(directory, entry)
        ctx["logged"] = True
        ctx["log_dir"] = directory
        ctx["log_path"] = path
        ctx["log_entry"] = entry
        return path
    except OSError:
        return None


def _fixup_model(provider) -> str:
    """The model a fix-up call runs on: the generator's (`model_for` maps
    the `fixup` label to it), named for the progress line."""
    model_for = getattr(provider, "model_for", None)
    model = model_for("fixup") if callable(model_for) else getattr(provider, "model", None)
    return str(model or "the generator's model")


def _fixup_counts(fixup: dict) -> tuple[int, int, int]:
    """(verify errors, routing warnings, critic omissions) the round
    carried. `fixup["errors"]` holds them in that order."""
    w, o = fixup.get("warnings", 0), fixup.get("omissions", 0)
    return len(fixup["errors"]) - w - o, w, o


def _say_fixup(fixup: dict) -> None:
    """The progress line for a fix-up round: "fix-up: 2 verify errors sent
    back to claude-haiku-4-5"."""
    n, w, o = _fixup_counts(fixup)
    what = "verify" if fixup["checker"] == "verify" else "format"
    sent = [f"{n} {what} error{'' if n == 1 else 's'}"] if n else []
    if w:
        sent.append(f"{w} routing warning{'' if w == 1 else 's'}")
    if o:
        sent.append(f"{o} line{'' if o == 1 else 's'} the critic found not carried out")
    print(f"fix-up: {' and '.join(sent)} sent back to {fixup['model']}",
          file=sys.stderr, flush=True)


def _fixup_found(fixup: dict) -> str:
    """"verify refused the first reply with 1 error(s)", or, when the
    round also carried routing warnings or the critic's omissions, what
    verify and the critic found."""
    n, w, o = _fixup_counts(fixup)
    if not w and not o:
        return f"{fixup['checker']} refused the first reply with {n} error(s)"
    found = []
    if n or w:
        found.append(f"{fixup['checker']} found {n} error(s)"
                     + (f" and {w} routing warning(s)" if w else ""))
    if o:
        found.append(f"the critic found {o} line(s) of the instructions or conventions not "
                     "carried out")
    return " and ".join(found) + " in the first reply"


def _fixup_finding(fixup: dict, still: list[str]) -> "diagnostics.Diagnostic":
    """The build finding for a fix-up round: INFO naming what was fixed
    when the corrected reply passes, WARNING when it did not (the plan
    written is still refused by apply, and verify's own errors say why),
    when the round produced no usable plan, or when its plan was worse on
    verify than the first and was not kept. Kept in `meta.build_findings`,
    so a plan says it was corrected."""
    first = fixup["errors"]
    listed = "; ".join(first)
    sent = f"{_fixup_found(fixup)}, sent back to {fixup['model']} in one fix-up round"
    if fixup.get("failed"):
        return diagnostics.Diagnostic(
            severity=diagnostics.Severity.WARNING, code="build.fixup-failed", where="build",
            source="build",
            message=(f"{sent}; that round did not produce a usable plan ({fixup['failed']}), "
                     f"so the first plan stands. Refused: {listed}"))
    if fixup.get("rejected"):
        return diagnostics.Diagnostic(
            severity=diagnostics.Severity.WARNING, code="build.fixup-rejected", where="build",
            source="build",
            message=(f"{sent}; the corrected reply was worse on verify ({fixup['rejected']}), so "
                     f"it was not kept and the first plan stands. Still open: {listed}"))
    if still:
        return diagnostics.Diagnostic(
            severity=diagnostics.Severity.WARNING, code="build.fixup-unresolved", where="build",
            source="build",
            message=(f"{sent}; the corrected reply still has "
                     f"{len(still)} of them (below). First round: {listed}"))
    return diagnostics.Diagnostic(
        severity=diagnostics.Severity.INFO, code="build.fixup", where="build", source="build",
        message=(f"{_fixup_found(fixup)}; one fix-up "
                 f"round sent them back to {fixup['model']}, and the corrected reply passes. "
                 f"Fixed: {listed}"))


def _omission_line(finding: "diagnostics.Diagnostic") -> str:
    """A critic omission as the fix-up sends it: what is missing, then the
    engineer's line it comes from, verbatim."""
    what = finding.title or finding.message
    return (f"{finding.where}: {what} -- not carried out: '{finding.line}' "
            "(critic.omission)")


def _on_the_first_plan(finding: "diagnostics.Diagnostic") -> "diagnostics.Diagnostic":
    """A critic finding about a first plan the fix-up round replaced, its
    headline (or, with none, its text) starting "On the first plan:"."""
    if finding.title:
        return dataclasses.replace(finding, title=f"On the first plan: {finding.title}")
    return dataclasses.replace(finding, message=f"On the first plan: {finding.message}")


def _verify_worse(before, after) -> str:
    """Why `after` is worse on verify than `before` ("3 errors where the
    first had 1"), or "" when it is not: more errors, or as many and more of
    the routing warnings the fix-up is sent."""
    if before is None or after is None:
        return ""
    b, a = len(before.errors), len(after.errors)
    if a != b:
        return f"{a} error(s) where the first had {b}" if a > b else ""
    bw, aw = len(generate.fixup_warning_lines(before)), len(generate.fixup_warning_lines(after))
    return (f"{aw} routing warning(s) where the first had {bw}" if aw > bw else "")


def _omissions_after(omissions: list, first_plan: dict, plan: dict, repaired: bool,
                     critic_findings: list) -> tuple[list, list]:
    """The critic's quoted omissions, checked again against the plan
    written, without asking the critic again. Returns `(critic_findings,
    build_findings)`: an omission carried out leaves the critic's list and
    is said at INFO (`build.critic-repair`); one still missing stays in it,
    a WARNING, saying so.

    A line naming output sockets that the first plan did not patch is
    checked: carried out when the plan written patches them all. Any other
    line code cannot read for itself, so when the round's plan was kept the
    INFO says only that the round was asked to carry it out, never that it
    did."""
    from atoo import outputs_sheet

    first_patched = set(outputs_sheet.output_sources(first_plan))
    patched = set(outputs_sheet.output_sources(plan))
    sent = {id(o) for o in omissions}
    kept, said = [], []
    for finding in critic_findings:
        if id(finding) not in sent:
            kept.append(finding)
            continue
        sockets = _sockets_named(finding.line)
        checked = bool(sockets) and not sockets <= first_patched
        done = sockets <= patched if checked else repaired
        if not done:
            kept.append(dataclasses.replace(
                finding, message=f"{finding.message} -- still not carried out after the "
                                 "fix-up round"))
            continue
        found = (f"the critic found '{finding.line}' not carried out in the first reply "
                 f"({finding.title or finding.message})")
        if checked:
            message = (f"{found}; the fix-up round carried it out: the plan written patches "
                       + _socket_runs_words(
                           sorted(sockets, key=lambda s: outputs_sheet.socket_order(*s))))
        else:
            message = (f"{found}; the fix-up round was asked to carry it out, and code can't "
                       "check this kind of line, so confirm it in the plan or at soundcheck")
        said.append(diagnostics.Diagnostic(
            severity=diagnostics.Severity.INFO, code="build.critic-repair", where=finding.where,
            line=finding.line, source="build", message=message))
    return kept, said


def _display_resolved(path: Path) -> str:
    """The resolved file's path as a person reads it: relative to the
    current directory when it is under it, else as it is."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except (ValueError, OSError):
        return str(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SheetRefused(Exception):
    """One of the show's sheets (`busses.csv`, `outputs.csv`) has a cell that
    cannot work on the desk; the build stops, naming the sheet and the cell."""

    def __init__(self, sheet: str, message: str):
        super().__init__(message)
        self.sheet = sheet


def _lay_on_bus_sheet(plan: dict, show, input_csv: str,
                      console_model: "str | None", *,
                      outputs_cells: "dict[str, str] | None" = None) -> list:
    """The show's `busses.csv` laid onto `plan`, in place, as a Save in
    Build's step 04 lays it (`sheets.overlay_busses`): a filled
    cell wins over the conventions and the reply. Every change and every
    choice made on the way is an INFO (`build.bus-sheet`); a cell that cannot
    physically work -- the overlay's own refusals, and any ERROR `verify`
    would newly find because of the sheet -- raises `SheetRefused` with
    step 04's own wording. No show, or no sheet: nothing, and no findings."""
    from atoo import sheets, source_edit

    if show is None or not (show.directory / bundle.BUSSES).is_file():
        return []
    text = (show.directory / bundle.BUSSES).read_text(encoding="utf-8-sig")
    rows = [r.values for r in source_edit.read_records(text)[1]]
    if outputs_cells is not None:
        # `outputs.csv` decides the sockets (`_lay_on_sheets`): the column is
        # kept aside, to be compared once that sheet is laid on.
        rows = [dict(row) for row in rows]
        for row in rows:
            cell = (row.get("outputs") or "").strip()
            if cell:
                outputs_cells[(row.get("bus") or "").strip()] = cell
            row["outputs"] = ""
    result = sheets.overlay_busses(plan, rows,
                                   categories=sheets.categories_by_channel(plan, input_csv))
    if not result.refusals:
        sheets.refuse_new_errors(plan, result, console_model=console_model)
    if result.refusals:
        raise SheetRefused(bundle.BUSSES, "; ".join(r.text() for r in result.refusals))

    def info(message: str) -> diagnostics.Diagnostic:
        return diagnostics.Diagnostic(severity=diagnostics.Severity.INFO, code="build.bus-sheet",
                                      where=bundle.BUSSES, message=message, source="build")

    findings = [info(f"{bundle.BUSSES} wins over the conventions: {change}.")
                for change in result.changes]
    findings += [info(note) for note in result.notes]
    plan.clear()
    plan.update(result.plan)
    return findings


def _lay_on_sheets(plan: dict, show, input_csv: str, console_model: "str | None",
                   layers: "list[tuple[str, str | None]] | None" = None) -> list:
    """The show's `busses.csv`, then its `outputs.csv`, laid onto
    `plan`, in place.

    `outputs.csv` is where each output socket's source is kept (answer A): when the show has one, it alone says which sockets a bus, a
    Main or a Matrix feeds, and `busses.csv`'s `outputs` column -- derived
    from it, and kept in step with it by a Busses-table Save -- is not laid
    on. Where that column says something else, one INFO names both files."""
    from atoo import outputs_sheet

    has_outputs = show is not None and (show.directory / bundle.OUTPUTS).is_file()
    cells: dict[str, str] = {}
    findings = _lay_on_bus_sheet(plan, show, input_csv, console_model,
                                 outputs_cells=cells if has_outputs else None)
    findings += _lay_on_outputs_sheet(plan, show, console_model, layers)
    findings += _lay_on_user_sheet(plan, show, console_model)
    if not cells:
        return findings
    from atoo import sheets

    now = outputs_sheet.output_sources(plan)
    groups = {"Bus": "BUS", "Main": "MAIN", "Matrix": "MTX"}
    for label, cell in cells.items():
        kind, _, number = label.partition(" ")
        if kind not in groups or not number.isdigit():
            continue
        obj = (groups[kind], int(number))
        sockets = {socket for socket, src in now.items()
                   if src[0] == obj[0] and (src[1] + 1) // 2 == obj[1]}
        if sheets._socket_set(cell) == sockets:
            continue
        said = sheets._socket_runs([{"group": g, "sockets": [n]} for g, n in sockets]) or "nowhere"
        findings.append(diagnostics.Diagnostic(
            severity=diagnostics.Severity.INFO, code="build.outputs-sheet", where=bundle.BUSSES,
            message=(f"{bundle.BUSSES} says {label} goes to {cell}, {bundle.OUTPUTS} says {said}: "
                     f"{bundle.OUTPUTS} is where each socket's source is kept, so it wins, and "
                     f"{bundle.BUSSES}'s Outputs column follows it. Edit {bundle.OUTPUTS}, or "
                     f"its rows in Build 04's Outputs table, to move a bus."),
            source="build"))
    return findings


def _lay_on_user_sheet(plan: dict, show, console_model: "str | None") -> list:
    """The show's `user.csv` laid onto `plan`, in place (`user_sheet.overlay`): a row with a filled source sets its USR slot over the
    conventions and the reply, `OFF` takes the slot out, and a slot the sheet
    does not name is left to them. Every change is an INFO
    (`build.user-sheet`); a row that cannot physically work raises
    `SheetRefused`. No show, or no sheet: nothing."""
    from atoo import user_sheet

    if show is None or not (show.directory / bundle.USER).is_file():
        return []
    rows = user_sheet.read_rows((show.directory / bundle.USER).read_text(encoding="utf-8-sig"))
    result = user_sheet.overlay(plan, rows, complete=False, console_model=console_model)
    if result.refusals:
        raise SheetRefused(bundle.USER, "; ".join(r.text() for r in result.refusals))
    findings = [diagnostics.Diagnostic(
        severity=diagnostics.Severity.INFO, code="build.user-sheet", where=bundle.USER,
        message=f"{bundle.USER} wins over the conventions: {change}.", source="build")
        for change in result.changes]
    plan.clear()
    plan.update(result.plan)
    return findings


def _lay_on_outputs_sheet(plan: dict, show, console_model: "str | None",
                          layers: "list[tuple[str, str | None]] | None" = None) -> list:
    """The show's `outputs.csv` laid onto `plan`, in place
    (`outputs_sheet.overlay`): each row with a filled source wins
    over the conventions and the reply, `OFF` disconnects that socket, and a
    socket the sheet does not name is left to them -- but a bus, Main or Matrix
    the sheet names feeds the sockets its rows give it and no others. Every change is an INFO (`build.outputs-sheet`); a row that cannot
    physically work raises `SheetRefused`. No show, or no sheet: nothing.

    Where the sheet takes a socket off a bus, Main or Matrix and
    a line of `layers` (`[("instructions", text), ("conventions", text)]`)
    names that socket, the engineer asked for it in words and does not get
    it: that is a WARNING quoting the line (`build.outputs-sheet-overrides`),
    never an INFO alone."""
    from atoo import outputs_sheet

    if show is None or not (show.directory / bundle.OUTPUTS).is_file():
        return []
    rows = outputs_sheet.read_rows(
        (show.directory / bundle.OUTPUTS).read_text(encoding="utf-8-sig"))
    result = outputs_sheet.overlay(plan, rows, complete=False, console_model=console_model)
    if result.refusals:
        raise SheetRefused(bundle.OUTPUTS, "; ".join(r.text() for r in result.refusals))
    findings = [diagnostics.Diagnostic(
        severity=diagnostics.Severity.INFO, code="build.outputs-sheet", where=bundle.OUTPUTS,
        message=f"{bundle.OUTPUTS} wins over the conventions: {change}.", source="build")
        for change in result.changes]
    findings += _sheet_overrides_said(plan, result.plan, layers or [])
    plan.clear()
    plan.update(result.plan)
    return findings


_SOCKET_WORDS = re.compile(r"\b(AES50-[ABC]|[A-Za-z]{2,4})\s*(\d{1,2})(?:\s*[-\u2013]\s*(\d{1,2}))?\b")


def _sockets_named(line: str) -> set:
    """The output sockets a line of text names: `USB 18-19` -> `{("USB", 18),
    ("USB", 19)}`, `AES50-A 3` -> `{("A", 3)}`."""
    from atoo import outputs_sheet

    found = set()
    for group, first, last in _SOCKET_WORDS.findall(line):
        start, end = int(first), int(last or first)
        if end < start or end - start > 64:
            continue
        for n in range(start, end + 1):
            socket = outputs_sheet.parse_output(f"{group} {n}")
            if socket is not None:
                found.add(socket)
    return found


def _sheet_overrides_said(before: dict, after: dict,
                          layers: "list[tuple[str, str | None]]") -> list:
    """A WARNING for each bus, Main or Matrix whose sockets the outputs sheet
    took off where an instructions or conventions line names them: what the
    line asked, that it is not carried out, and how to carry it out."""
    from atoo import outputs_sheet

    was, now = outputs_sheet.output_sources(before), outputs_sheet.output_sources(after)
    objects = {"BUS": "Bus", "MAIN": "Main", "MTX": "Matrix"}
    lost: dict[str, list] = {}
    for socket, source in was.items():
        if source[0] in objects and now.get(socket) != source:
            lost.setdefault(f"{objects[source[0]]} {(source[1] + 1) // 2}", []).append(socket)
    findings = []
    for label, sockets in lost.items():
        quoted = None
        for where, text in layers:
            for line in (text or "").splitlines():
                if _sockets_named(line) & set(sockets):
                    quoted = (where, line.strip().lstrip("-*").strip())
                    break
            if quoted:
                break
        if quoted is None:
            continue
        group, n = label.split()
        kept = sorted((s for s, src in now.items()
                       if src[0] == {"Bus": "BUS", "Main": "MAIN", "Matrix": "MTX"}[group]
                       and (src[1] + 1) // 2 == int(n)),
                      key=lambda s: outputs_sheet.socket_order(*s))
        gone = _socket_runs_words(sorted(sockets, key=lambda s: outputs_sheet.socket_order(*s)))
        has = _socket_runs_words(kept) or "none"
        findings.append(diagnostics.Diagnostic(
            severity=diagnostics.Severity.WARNING, code="build.outputs-sheet-overrides",
            where=bundle.OUTPUTS,
            message=(f"{bundle.OUTPUTS} decides {label}'s sockets ({has}), so the {quoted[0]}' "
                     f"'{quoted[1]}' is not carried out: {gone} "
                     f"{'is' if len(sockets) == 1 else 'are'} not patched from {label}. "
                     f"Add {gone} to {bundle.OUTPUTS}, or edit them in Build 04's Outputs table, "
                     "to carry it out."),
            source="build"))
    return findings


def _socket_runs_words(sockets: list) -> str:
    """`[("USB", 18), ("USB", 19)]` -> `USB 18-19`."""
    from atoo import sheets

    return sheets._socket_runs([{"group": g, "sockets": [n]} for g, n in sockets])


def _build(args: argparse.Namespace, written: list[str], ctx: dict | None = None) -> int:
    if ctx is None:
        ctx = {}
    # --show DIR first, so everything below sees the bundle's paths as if
    # they had been passed as flags. Resolution order end to end:
    #   explicit flag  >  --show  >  _auto_detect  >  ~/.atoo.config
    try:
        show = _open_bundle(args)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    # `input.csv` is the one slot a build cannot do without, so it reports
    # a missing file rather than silently falling through to auto-detect
    # and compiling some other directory's show.
    try:
        _fill_from_bundle(args, show, "input", bundle.INPUT_LIST, required=True)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    # A bundle's `instructions.md` is a *layer*, never the conventions
    # file itself: the show-independent
    # conventions file is always brought in, as well as a show's
    # instructions if it is present, and content in the instructions file
    # overrides the conventions file.
    #
    # `instructions.md` once filled `--conventions` directly, which
    # meant a bundle's per-show text either replaced the house file or --
    # when `--conventions` was also given -- was dropped without a word.
    instructions_path = show.optional(bundle.INSTRUCTIONS) if show is not None else None
    # Generated artifacts land in the bundle, not wherever --out happens
    # to point -- the whole reason a bundle is one draggable
    # thing after a build.
    if show is not None and not args.out:
        args.out = str(show.plan)

    input_path = args.input
    conventions_path = args.conventions
    # Where the conventions text came from, for the announcement below.
    conventions_source = "--conventions" if conventions_path else ""

    if not input_path and not conventions_path:
        detected = _auto_detect(Path("."))
        if detected is not None:
            input_path_p, conventions_path_p = detected
            input_path = str(input_path_p)
            conventions_path = str(conventions_path_p)
            conventions_source = "found in the current directory"
            print(f"No --input/--conventions given -- using the only pair found here: "
                  f"{input_path} + {conventions_path}\n")
        else:
            # Nothing unambiguous here. If there is exactly one input
            # list and no conventions file at all, the settled house file
            # is worth trying before giving up.
            csv_paths, _md_paths = _discover_files(Path("."))
            default_conventions = load_default_conventions() if len(csv_paths) == 1 else None
            if default_conventions is None:
                _print_discovery_guidance(Path("."))
                return 1
            input_path = str(csv_paths[0])
            conventions_path = str(default_conventions)
            conventions_source = str(config_path())
            print(f"(input list: {input_path})\n", file=sys.stderr)
    elif not input_path:
        print("--conventions given without --input -- --input is required", file=sys.stderr)
        return 1

    if not conventions_path:
        # The show-independent conventions file is always brought in. The
        # house default was once
        # consulted only inside the auto-detect branch above, so
        # `--input x.csv --show DIR` failed even with a settled house file
        # named in the config. It is the fallback for every route now.
        default_conventions = load_default_conventions()
        if default_conventions is not None:
            conventions_path = str(default_conventions)
            conventions_source = str(config_path())

    if not conventions_path:
        print("no conventions file -- one is required.\n"
              "It is your standing house style, reused across every show, so it lives "
              "OUTSIDE a show bundle: pass --conventions, or name one in "
              f"{config_path()}'s [conventions] default.\n"
              "A bundle's instructions.md layers on top of it; it is not a substitute "
              "for it.", file=sys.stderr)
        return 1

    try:
        instructions_text = instructions_path.read_text(encoding="utf-8") if instructions_path else None
    except OSError as exc:
        print(f"couldn't read {instructions_path}: {exc.strerror}", file=sys.stderr)
        return 1

    # The stack, worst-to-best precedence, announced rather than applied
    # silently. A
    # build that quietly composed a file the command line never named is
    # a build whose output cannot be explained afterwards.
    #
    # Each layer also carries `conventions_ref.layer_record`'s three keys:
    # the absolute path, the path relative to the bundle (None
    # with no bundle), and a sha256 of the bytes as built -- so the UI
    # can open the file this plan was built from, and say so when it has
    # been edited since. `path` stays exactly what was typed.
    bundle_dir = show.directory if show is not None else None
    ctx["bundle_dir"] = bundle_dir
    conventions_stack = [{"path": conventions_path, "role": "conventions",
                          "source": conventions_source or "explicit",
                          **conventions_ref.layer_record(conventions_path, bundle_dir)}]
    if instructions_path is not None:
        conventions_stack.append({"path": str(instructions_path), "role": "instructions",
                                  "source": f"show bundle {show.directory}",
                                  **conventions_ref.layer_record(instructions_path, bundle_dir)})
    ctx["conventions_stack"] = conventions_stack
    if len(conventions_stack) > 1 or conventions_source not in ("--conventions", ""):
        print("Conventions, in order -- each layer overrides the one above it:", file=sys.stderr)
        for i, layer in enumerate(conventions_stack, 1):
            print(f"  {i}. {layer['path']}  ({layer['source']})", file=sys.stderr)
        print(file=sys.stderr)

    # Read once, as written. `<!-- ... -->` comments are the engineer's
    # notes to himself: every model-facing and quote-checking reader
    # strips them (`generate._conventions_section`,
    # `conventions_audit.layers_for`), so these texts are passed on
    # WHOLE -- and `conventions_stack`'s sha256 above is over the file's
    # real bytes, comments included, because it answers "is this the
    # file the plan was built from". What reading the comments found --
    # an `<!--` that never closes, which would otherwise read a note as
    # a rule -- is said now, before a model call is spent, and kept in
    # `meta.build_findings`.
    try:
        conventions_raw = Path(conventions_path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"couldn't read {conventions_path}: {exc.strerror}", file=sys.stderr)
        return 1
    comment_findings = conventions_text.comment_findings(
        conventions_raw, Path(conventions_path).name)
    if instructions_text is not None:
        comment_findings += conventions_text.comment_findings(
            instructions_text, Path(instructions_path).name)
    if comment_findings:
        _emit_diagnostics(comment_findings,
                          heading="Comments in the conventions -- "
                                  f"{len(comment_findings)} note(s):")
        print(file=sys.stderr)

    try:
        rows = load_input_list(input_path)
    except OSError as exc:
        print(f"couldn't read input list {input_path!r}: {exc.strerror}", file=sys.stderr)
        return 1
    except InputListError as exc:
        # The file by its name, not its path: this line is also
        # what the Build page's dock quotes when a build it ran fails, and
        # a full path there puts the home folder into a shared screenshot.
        print(f"input list error in {Path(input_path).name}: {exc}", file=sys.stderr)
        return 1
    # `-` in the `order` column (FR-1.1, 2026-10-10): the row stays in the
    # file and is left out of this build entirely -- not sent to the model,
    # not built, not reconciled as missing. One INFO names them.
    skip_findings: list = []
    try:
        skipped = input_list_module.skipped_rows(Path(input_path).read_text(encoding="utf-8"))
    except (OSError, InputListError):
        skipped = []
    found = input_list_module.skip_finding(skipped, where=Path(input_path).name)
    if found is not None:
        skip_findings.append(found)
        print(f"INFO {found.message}", file=sys.stderr, flush=True)

    if getattr(args, "prompt_dir", None):
        os.environ["ATOO_PROMPT_DIR"] = args.prompt_dir

    critic_findings: list = []
    # Distinct from `critic_findings` being empty: this tracks whether the
    # critic pass ran at all (--critic), so
    # meta.critic_findings below can be None ("didn't run") rather than
    # [] ("ran, found nothing").
    critic_ran = False
    # The only way a plan is built since the deterministic
    # compiler was retired: the model lays the show out with the
    # conventions AND the input list in front of it, and deterministic
    # code checks the result rather than deriving it.
    if not conventions_path:
        print("a conventions file is required -- pass --conventions, or --show DIR "
              "with an instructions.md in it", file=sys.stderr)
        return 1
    # `out_path` resolved here, rather than only once a plan exists, so
    # that a build log written for a build that FAILED (below, before any
    # plan) still lands beside where `--out` (or its default) was always
    # going to put one -- not next to whatever the current directory
    # happens to be (`build_log.directory_for`).
    out_path = None if args.out == "-" else (
        Path(args.out) if args.out else _default_out_path(input_path, conventions_path))
    ctx["out_path"] = out_path

    # Resolve the console model BEFORE spending a model call on
    # a plan we would then refuse. An unknown model is a hard stop.
    # Not defaulted to the Compact: "any plan would be meaningless" applies
    # to an unstated model exactly as it does to an unrecognised one, and a
    # silent default is how a Full's 8 local inputs become a plan patching
    # LCL 24.
    console_model = getattr(args, "console_model", None)
    if not console_model and show is not None:
        # A show that has been built before already says which WING it is
        # for. Asking again is a question with a known answer; starting
        # from it, and saying so, is the judgement an engineer would make
        # (the flag still wins, and so does a change of desk).
        found = _console_model_of_show(show)
        if found is not None:
            console_model, stated_in = found
            print(f"INFO console model: {console_model}, from {stated_in} "
                  f"(meta.console_model, the desk this show was last built for) -- "
                  f"pass --console-model to build for a different WING",
                  file=sys.stderr, flush=True)
    ctx["console_model"] = console_model
    try:
        facts.panel_for(console_model)
    except facts.UnknownConsoleModel as exc:
        print(str(exc), file=sys.stderr)
        print("pass --console-model, e.g. --console-model wing-compact"
              + (f" ({bundle.PLAN} in this show states none to take it from)"
                 if show is not None else ""), file=sys.stderr)
        return 1

    # A build is a model call: with no model set up it cannot happen, and it
    # says so before anything on disk moves -- plan.json stays as it is, so
    # Apply still has the plan it had.
    try:
        provider = provider_from_env()
    except AIProviderError as exc:
        message = (f"{exc}. See 'Setting up an AI provider' in the user guide. Nothing was "
                   "changed" + (f": {bundle.PLAN} is as it was." if show is not None else "."))
        print(f"build failed: {message}", file=sys.stderr)
        return 1

    # A rebuild clears the current plan and current findings, because none of
    # that is still current.
    # A show's plan.json is moved aside the moment its rebuild starts, so a
    # build that fails or is stopped leaves no out-of-date plan for Apply
    # to offer. Kept as plan.previous.json, one generation, for reading.
    if show is not None and out_path is not None and out_path == show.plan \
            and out_path.is_file():
        previous = out_path.with_name(bundle.PLAN_PREVIOUS)
        out_path.replace(previous)
        print(f"INFO {bundle.PLAN} moved aside to {bundle.PLAN_PREVIOUS}: it was built from "
              f"what this build replaces, so it is no longer current", file=sys.stderr)

    # The resolved conventions (`conventions_resolve.py`, 2026-09-30):
    # the house conventions and the domain knowledge restated once as
    # cited rules, which the generator and the fix-up read in place of
    # both. `--no-resolve` / ATOO_RESOLVE=0 turn it off, for the A/B.
    resolve_off = ("--no-resolve" if getattr(args, "no_resolve", False)
                   else None if conventions_resolve.enabled()
                   else f"{conventions_resolve.RESOLVE_ENV}=0")
    resolve_state = None
    resolved = None
    resolve_findings: list = []
    resolve_called = False
    category_rules_off = ("--no-category-rules" if getattr(args, "no_category_rules", False)
                          else None if category_table_module.enabled()
                          else f"{category_table_module.ENV}=0")
    category_table = None
    instructed_strips = None
    try:
        ctx["provider"] = provider
        if resolve_off is None:
            resolve_state = conventions_resolve.freshness(conventions_path, conventions_raw)
            resolve_called = not resolve_state.fresh
        # The calls this build will make besides the generator, and the
        # effort each runs at where the provider has one (Claude's
        # per-role effort): said once, at INFO, when any differs from the
        # generator's -- the judgement made on the engineer's behalf, and
        # the setting that changes it.
        other_roles = ((["resolve"] if resolve_called else [])
                       + (["critic"] if args.critic else [])
                       + (["watchlist"] if show is not None else []))
        announce = getattr(provider, "effort_announcement", None)
        effort_line = announce(other_roles) if announce else None
        if effort_line:
            print(effort_line, file=sys.stderr, flush=True)
        if resolve_state is None:
            print(f"INFO resolved conventions: off ({resolve_off}) -- the generator reads the "
                  "raw conventions and the domain knowledge", file=sys.stderr, flush=True)
        else:
            shown = _display_resolved(resolve_state.path)
            if resolve_state.fresh:
                print(f"INFO resolved conventions: {shown} is fresh ({resolve_state.reason}) -- "
                      "the generator reads it in place of the conventions and the domain "
                      "knowledge", file=sys.stderr, flush=True)
            else:
                print(f"INFO resolved conventions: {shown} is {resolve_state.state} "
                      f"({resolve_state.reason}) -- resolving now: one extra model call, role "
                      "resolve", file=sys.stderr, flush=True)
            # The preset library the build will use, for the preset
            # map's coverage; announced later, with the build.
            resolved = conventions_resolve.obtain(
                resolve_state, conventions_raw, Path(conventions_path).name,
                provider=provider, findings=resolve_findings,
                preset_library=_preset_library_choice(args).library)
            if resolve_findings:
                # The check's per-citation findings are one line here, not
                # one block each (sixty of them in a long
                # run): they are kept in full in
                # meta.build_findings, and `resolve --check` lists them.
                # A refused or failed resolve still prints in full.
                per_item = (conventions_resolve.CODE_QUOTE, conventions_resolve.CODE_UNCOVERED)
                listed = [f for f in resolve_findings if f.code not in per_item]
                quotes = sum(1 for f in resolve_findings
                             if f.code == conventions_resolve.CODE_QUOTE)
                lines = sum(1 for f in resolve_findings
                            if f.code == conventions_resolve.CODE_UNCOVERED)
                # A citation not found is a WARNING (a rule the engineer
                # may never have written); a line no rule cites is an INFO
                # (the generator reads it verbatim, so nothing
                # is lost).
                lists = f"`atoo resolve --conventions {conventions_path} --check` lists them"
                if quotes:
                    print(f"WARNING resolved conventions: {quotes} citation(s) not found in "
                          f"the texts -- {lists}", file=sys.stderr)
                if lines:
                    print(f"INFO resolved conventions: {lines} conventions line(s) cited by no "
                          f"rule, given to the generator verbatim -- {lists}", file=sys.stderr)
                if listed:
                    _emit_diagnostics(
                        listed, heading=f"Resolved conventions -- {len(listed)} note(s):")
                print(file=sys.stderr)
        # The Category table (`category_table.py`, 2026-09-30): the
        # resolved file's per-category channel settings, which code writes
        # on every channel of the category the reply leaves them out of.
        # `--no-category-rules` / ATOO_CATEGORY_RULES=0 ignores it,
        # and the generator's prompt is then what it was without it.
        if resolved is not None and resolved.table is not None:
            if category_rules_off:
                print(f"INFO category table: off ({category_rules_off}) -- the generator "
                      "writes every channel's settings", file=sys.stderr, flush=True)
            else:
                resolve_findings.extend(resolved.table.findings)
                category_table = resolved.table.table
                if category_table is not None:
                    print(f"INFO category table: {len(category_table.entries)} categor"
                          f"{'y' if len(category_table.entries) == 1 else 'ies'} in "
                          f"{resolved.name} -- code writes their "
                          f"{category_table_module.fields_named(category_table)} on every "
                          "channel of the category whose reply leaves them out",
                          file=sys.stderr, flush=True)
                else:
                    _emit_diagnostics(resolved.table.findings,
                                      heading="Category table -- 1 note:")
        # The Instructed strips block (`instructed_channels.py`,
        # 2026-10-01): the strips the conventions ask for that are not
        # input-list rows, which code builds after the reply is expanded.
        # With no resolved file the generator builds them, as before.
        if resolved is not None and resolved.strips is not None:
            resolve_findings.extend(resolved.strips.findings)
            instructed_strips = resolved.strips.strips or None
            if instructed_strips:
                print(f"INFO instructed strips: {len(instructed_strips)} in {resolved.name} -- "
                      "code builds "
                      + ", ".join(f"{s.name} ({s.bank} {s.number if s.number else '?'})"
                                  for s in instructed_strips),
                      file=sys.stderr, flush=True)
            listed = [f for f in resolved.strips.findings
                      if f.severity != diagnostics.Severity.INFO]
            if listed:
                _emit_diagnostics(listed, heading=f"Instructed strips -- {len(listed)} note(s):")
        # What code derived while expanding the model's shorter reply --
        # the sockets it counted out, the colours it applied from the
        # category map -- each an INFO (`reply_expand`), reported with
        # the other build findings below and kept in `meta.build_findings`.
        expansion_findings: list = []
        # The model reads the list as the engineer wrote it -- the `order`
        # column and its numbers included, as data for an instruction to
        # use -- minus the skipped rows (`input_list.build_text`).
        input_csv = input_list_module.build_text(Path(input_path).read_text(encoding="utf-8"))
        gen_kwargs = dict(
            conventions_name=Path(conventions_path).name,
            input_name=Path(input_path).name,
            instructions=instructions_text,
            instructions_name=Path(instructions_path).name if instructions_path else None,
            constrain=not args.no_constrain,
            console_model=console_model,
            resolved=resolved.body if resolved is not None else None,
            resolved_name=resolved.name if resolved is not None else None,
            category_table=category_table,
            instructed_strips=instructed_strips,
        )
        # The fix-up round: a reply refused by the
        # format check, or a plan refused by verify with ERRORS, goes back
        # to the generator's model once with the exact messages
        # (`generate.fixup_plan`). `fixup` records the one round, if spent.
        fixup_budget = generate.fixup_rounds()
        fixup: dict | None = None
        replies: list[str] = []
        try:
            plan = generate.generate_plan(
                conventions_raw, input_csv, provider=provider,
                findings=expansion_findings, replies=replies, **gen_kwargs)
        except generate.GenerationError as first:
            if not fixup_budget or not first.reply:
                raise
            errors = [str(first)]
            fixup = {"checker": "the format check", "errors": errors,
                     "model": _fixup_model(provider)}
            _say_fixup(fixup)
            expansion_findings.clear()
            try:
                plan = generate.fixup_plan(
                    conventions_raw, input_csv, first.reply, errors,
                    checker="the format check", provider=provider,
                    findings=expansion_findings, replies=replies, **gen_kwargs)
            except generate.GenerationError as second:
                raise generate.GenerationError(
                    f"{second}\n(one fix-up round did not mend it; the first reply "
                    f"was refused too: {first})",
                    partial_text=second.partial_text, reply=second.reply) from second
    except (AIProviderError, generate.GenerationError, generate.PromptError) as exc:
        print(f"generation failed: {exc}", file=sys.stderr)
        print(f"  {install_info.describe().summary()}", file=sys.stderr)
        if isinstance(exc, AIProviderError):
            print("  no plan was written; the build log keeps this attempt.", file=sys.stderr)
        # Whatever the model wrote before it failed is the only evidence
        # of WHY, and it was paid for. Throwing it away leaves "it hit
        # max_tokens" with nothing to read -- was it thinking, or was it
        # repeating one channel forty times, as a local model once did?
        partial = getattr(exc, "partial_text", "")
        if partial:
            where = _partial_path(Path(args.out) if args.out and args.out != "-"
                                  else Path("generation.json"))
            try:
                # The model writes its reply unindented (reply_expand);
                # a partial that parses is saved pretty-printed so a
                # person can read it, and one that does not is saved as
                # it arrived.
                where.write_text(_readable_partial(partial), encoding="utf-8")
                print(f"  the {len(partial):,} characters that did arrive are in "
                      f"{where} -- read them before changing anything",
                      file=sys.stderr)
            except OSError as write_exc:
                print(f"  (could not save the partial reply: {write_exc})",
                      file=sys.stderr)
        # A failed build has no plan.json to hang a log on -- which is a
        # big part of why this log exists at all: whatever the generator
        # DID say (its build-log notes, if it streamed a summary before
        # failing) is otherwise lost the moment this process exits.
        _write_build_log(ctx, status=build_log_module.FAILED, reason=str(exc))
        return 1
    preset_library = _resolve_preset_library(args, announce=True)
    # A quote of the resolved conventions is accepted wherever a
    # conventions quote is checked, and credited to the raw line its rule
    # cites (`conventions_audit.locate`).
    resolved_layer = ({"resolved": resolved.body, "resolved_name": resolved.name}
                      if resolved is not None else {})

    def settle(plan: dict, expansion_findings: list):
        """What follows a plan out of the model, for the first reply and a
        fix-up's alike: the show's bus sheet laid on, the conventions audit,
        preset expansion and verify. Returns `(build_findings,
        audit_findings, preset_findings, verdict)`; raises `SheetRefused`
        for a sheet cell that cannot work."""
        # The bus sheet wins over the conventions where it has
        # a filled cell, before presets are expanded and verify reads the
        # plan, so both see the plan that will be written.
        expansion_findings = expansion_findings + _lay_on_sheets(
            plan, show, input_csv, getattr(args, "console_model", None),
            [("instructions", instructions_text), ("conventions", conventions_raw)])
        # FR-6.2, folded into the build: the problems the
    # generator found in the conventions TEXT -- a conflict it had to pick
    # a side in, something declared that nothing joins -- with every quote
    # checked against the house conventions and the instructions it was
    # built from. A quote that is not in either is kept, at INFO, and says
    # it is not trusted (`conventions_audit.py`).
        audit_findings = conventions_audit.findings_from_plan(
            plan, conventions_audit.layers_for(
                conventions_raw, Path(conventions_path).name,
                instructions_text, Path(instructions_path).name if instructions_path else None,
                **resolved_layer))
        # A named
        # preset is expanded INTO the plan here, so the plan says exactly what
        # will be written and `apply` never opens a .chn. Merged by address;
        # the plan's own processing wins and each override is an INFO. Before
        # verify, so verify reports on the plan that will be written.
        preset_findings = preset_expand.expand_plan(plan, preset_library)
        build_findings = (comment_findings + skip_findings + resolve_findings
                          + expansion_findings
                          + audit_findings + preset_findings)

        # Verification runs on EVERY plan, however it was built. It is the one
        # part of generation that is proven, and it is not specific to generated plans
        # -- the first thing it ever did was reject the *compiler's* own
        # touringband plan for an output with no socket, which the compiler had
        # downgraded to one warning among three.
        verdict = None
        if not args.skip_verify:
            verdict = verify_plan(plan, rows, presets=preset_library,
                                  console_model=getattr(args, "console_model", None),
                                  layers=instructed_channels.layers_from_texts(
                                      conventions_raw, Path(conventions_path).name, instructions_text,
                                      Path(instructions_path).name if instructions_path else None,
                                      **resolved_layer))
        return build_findings, audit_findings, preset_findings, verdict

    try:
        build_findings, audit_findings, preset_findings, verdict = settle(plan, expansion_findings)
    except SheetRefused as exc:
        message = (f"{exc.sheet} cannot be laid onto this plan, so nothing was written: "
                   f"{exc}. Change the cell"
                   + (" (Build's step 04 shows it)" if exc.sheet == bundle.BUSSES else "")
                   + ", or clear it to leave it to the conventions.")
        print(f"build failed: {message}", file=sys.stderr)
        _write_build_log(ctx, status=build_log_module.FAILED, reason=message)
        return 1

    # The critic reads the settled first plan, before the fix-up round
    # (the plan's author, 2026-10-27): its findings are opinion, not
    # errors, and stay report-only -- except an omission quoting, verbatim,
    # a line of the instructions or conventions the plan did not carry out
    # (`conventions_audit.check_critic_omission` sets its `line`). Those
    # join verify's errors in the one round, or spend it on their own: the
    # engineer's own words are the check, never the critic's opinion. The
    # critic is not asked again afterwards; each omission's line is checked
    # against the plan written (`_omissions_after`).
    omissions: list = []
    if args.critic:
        critic_ran = True
        critic_findings = generate.critique_plan(
            conventions_raw, input_csv, plan,
            provider=provider,
            conventions_name=Path(conventions_path).name,
            input_name=Path(input_path).name,
            instructions=instructions_text,
            instructions_name=Path(instructions_path).name if instructions_path else None,
        )
        omissions = [f for f in critic_findings if f.code == "critic.omission" and f.line]

    # The fix-up round for verify's ERRORS and the critic's quoted
    # omissions -- only when the round was not already spent on the format
    # check above: one round per build, never a loop. Warnings and notes are
    # not sent, except a strip that reaches no output
    # (`generate.FIXUP_WARNING_CODES`): a routing slip, not a judgement
    # call, and one the model mends when it is shown it. The corrected plan
    # is kept only when verify finds it no worse than the first.
    def fixup_lines(verdict) -> tuple[list[str], list[str]]:
        if verdict is None:
            return [], []
        return generate.verify_error_lines(verdict), generate.fixup_warning_lines(verdict)

    first_plan = plan
    repaired = False
    fix_errors, fix_warnings = fixup_lines(verdict)
    omission_lines = [_omission_line(f) for f in omissions]
    if ((fix_errors or fix_warnings or omission_lines) and fixup_budget and fixup is None
            and replies):
        errors = fix_errors + fix_warnings + omission_lines
        fixup = {"checker": "verify", "errors": errors, "warnings": len(fix_warnings),
                 "omissions": len(omission_lines), "model": _fixup_model(provider)}
        _say_fixup(fixup)
        fixed_findings: list = []
        try:
            fixed = generate.fixup_plan(
                conventions_raw, input_csv, replies[-1], errors,
                checker=("the critic" if not (fix_errors or fix_warnings)
                         else "verify and the critic" if omission_lines else "verify"),
                provider=provider,
                findings=fixed_findings, replies=replies, **gen_kwargs)
        except (AIProviderError, generate.GenerationError, generate.PromptError) as exc:
            # The first plan still stands -- written, and refused by apply,
            # exactly as a build without a fix-up leaves it -- and the round
            # that did not produce a better one says why.
            fixup["failed"] = str(exc)
            print(f"fix-up: the round did not produce a usable plan, so the first one "
                  f"stands: {exc}", file=sys.stderr, flush=True)
        else:
            try:
                settled = settle(fixed, fixed_findings)
            except SheetRefused as exc:
                # The first plan, which the sheet went onto, still stands.
                fixup["failed"] = f"{exc.sheet} cannot be laid onto it: {exc}"
                print(f"fix-up: {fixup['failed']}, so the first plan stands",
                      file=sys.stderr, flush=True)
            else:
                worse = _verify_worse(verdict, settled[3])
                if worse:
                    fixup["rejected"] = worse
                    print(f"fix-up: the corrected reply is worse on verify ({worse}), so the "
                          "first plan stands", file=sys.stderr, flush=True)
                else:
                    plan = fixed
                    repaired = True
                    build_findings, audit_findings, preset_findings, verdict = settled
    if fixup is not None:
        still_errors, still_warnings = fixup_lines(verdict)
        still = still_errors + (still_warnings if fixup.get("warnings") else [])
        build_findings = build_findings + [_fixup_finding(fixup, still)]
    if repaired and critic_findings:
        # The critic read the first plan, which the round replaced: what it
        # said about it may already be mended, so it says which plan it read.
        sent = {id(o) for o in omissions}
        critic_findings = [f if id(f) in sent else _on_the_first_plan(f)
                           for f in critic_findings]
    if omissions:
        critic_findings, repairs = _omissions_after(
            omissions, first_plan, plan, repaired, critic_findings)
        build_findings = build_findings + repairs

    warnings = list(plan.get("notes") or [])

    # `build`'s own record of itself, namespaced under one key
    # (PLAN_SCHEMA's "meta") rather than several new top-level fields, so
    # it reads as "this build's record of itself" and not part of the
    # console spec the rest of the plan describes. `verify_at_generation`
    # is a snapshot as of THIS MOMENT ONLY -- see apply_cmd's "The gate"
    # comment below, which re-verifies fresh at apply time and never reads
    # this field. Reusing `verdict` from above rather than re-running
    # verification a second time just to populate it.
    plan["meta"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # No `strategy` (review 2026-09-28, R14):
        # it had one value, "generate", once the compiler was retired, so
        # it said nothing. A plan built before carries it and still loads
        # -- `meta` is an open object -- with no warning.
        # Which console this plan was built for, and therefore
        # which panel its socket numbers were checked against. Assigned
        # here as well as in `generate_plan` because this statement
        # REPLACES the meta dict wholesale -- dropping it would leave every
        # built plan unverifiable without the flag being passed again.
        "console_model": console_model,
        # Which conventions texts went into this build, in precedence
        # order. `conventions_file` above names one file and cannot
        # say "and also"; now "the conventions file" is no longer
        # one file, so a plan that changed has to be explainable from the
        # plan itself rather than from whoever remembers the command.
        "conventions_stack": conventions_stack,
        # The input list's own record, the same shape as a
        # conventions layer's (path, absolute path, path relative to the
        # bundle, sha256 of the bytes as built), so the Setup page and
        # Apply's pre-flight can say "input.csv changed after this plan
        # was built" (`plan_freshness`). A plan without it is "cannot
        # tell", never "stale".
        "input_list": plan_freshness.input_list_record(input_path, bundle_dir),
        "verify_at_generation": report.verify_at_generation_status(
            verify_result=verdict,
        ),
        # The same findings sources that already went to
        # stderr, also mirrored into plan.json itself so a UI reading the
        # plan file alone doesn't need the stderr stream (the now-retired
        # .report.md file used to serve this purpose
        # and report.py's module docstring). Each is None exactly when
        # that pass didn't run at all -- distinct from an empty list,
        # which means it ran and found nothing. `apply_cmd` never reads
        # any of this; it re-verifies fresh every time (see its "The
        # gate" comment).
        "critic_findings": (
            [f.to_dict() for f in critic_findings] if critic_ran else None
        ),
        "verify_findings": _findings_meta(verdict),
        # FR-6.2: the generator's conventions-audit entries, quote-checked
        # (above), after anything reading the files' `<!-- -->` comments
        # found (an unclosed one). Always a list -- the check always
        # runs, so [] means it ran and found nothing.
        "build_findings": [f.to_dict() for f in build_findings],
        # Whether the generator read the resolved conventions in place of
        # the raw file and the domain knowledge (`conventions_resolve.py`),
        # and which: its path (as a layer record) and fingerprint. `used:
        # false` says why not -- the A/B's other arm, or a refused file.
        "resolved_conventions": (
            {**resolved.meta(bundle_dir),
             "category_table": resolved.table.meta(
                 applied=category_table is not None, off_reason=category_rules_off),
             **({"instructed_strips": resolved.strips.meta(
                 applied=bool(instructed_strips))} if resolved.strips is not None else {})}
            if resolved is not None
            else conventions_resolve.not_used_meta(
                resolve_off or ("the resolve call failed" if any(
                    f.code == conventions_resolve.CODE_FAILED for f in resolve_findings)
                    else "the resolved file was refused"))),
    }
    # Which model built this, and at what effort per role, so two builds'
    # `critic_findings` (or drafted watch conditions) can be compared
    # knowing which run was which. Additive; only for a provider that has
    # an effort (Claude), and only the roles this build ran.
    effort_for = getattr(provider, "effort_for", None)
    # The fix-up, when a round was spent, is a role of its own in `effort`
    # and `models` as it is in the build log -- on the generator's model
    # and at its effort.
    ran_roles = [*(["resolve"] if resolve_called else []), "generator",
                 *(["fixup"] if fixup is not None else []),
                 *[r for r in other_roles if r != "resolve"]]
    if callable(effort_for):
        plan["meta"]["model"] = getattr(provider, "model", None)
        plan["meta"]["effort"] = {role: effort_for(role) for role in ran_roles}
        # `meta.model` stays the generator's. When a role ran on another
        # model (the critic and the watchlist on a cheaper model, say),
        # `meta.models` says which,
        # so `meta.critic_findings` is read knowing who wrote them.
        model_for = getattr(provider, "model_for", None)
        if callable(model_for):
            models = {role: model_for(role) for role in ran_roles}
            if len(set(models.values())) > 1:
                plan["meta"]["models"] = models

    # FR-1.4: what each strip was made from -- every built
    # input-list row's fingerprint, the rows each channel is made from,
    # and the conventions texts' lines -- so the NEXT rebuild can tell a
    # change the edit asked for from one nobody did. Then this build's
    # own comparison with the plan it replaced, kept beside it.
    # None of it may fail the build: the plan is the deliverable and this
    # is a report on it, so a failure here is a WARNING and the build goes on.
    try:
        plan["meta"][plan_diff.BASIS_KEY] = plan_diff.basis(
            plan, rows, [("conventions", conventions_raw)]
            + ([("instructions", instructions_text)] if instructions_text is not None else []))
    except Exception as exc:  # noqa: BLE001 -- see above
        print(f"WARNING could not record what each strip was made from, so the next rebuild "
              f"cannot grade its changes strip by strip: {exc}", file=sys.stderr)
    # The plan was made from the show's bus sheet (`settle`
    # laid it on), so it records the sheet as it records the input list, and
    # an edit to it afterwards reads Stale.
    if show is not None and (show.directory / bundle.BUSSES).is_file():
        plan["meta"]["bus_sheet"] = plan_freshness.input_list_record(
            show.directory / bundle.BUSSES, bundle_dir)
    if show is not None and (show.directory / bundle.OUTPUTS).is_file():
        plan["meta"]["outputs_sheet"] = plan_freshness.input_list_record(
            show.directory / bundle.OUTPUTS, bundle_dir)
    if show is not None and (show.directory / bundle.USER).is_file():
        plan["meta"]["user_sheet"] = plan_freshness.input_list_record(
            show.directory / bundle.USER, bundle_dir)
    changes = _changes_since_previous(show, out_path, plan)
    if changes is not None:
        try:
            plan["meta"][plan_diff.CHANGES_KEY] = changes.to_dict(
                against=bundle.PLAN_PREVIOUS)
        except Exception as exc:  # noqa: BLE001 -- see above
            print(f"WARNING could not keep the comparison with {bundle.PLAN_PREVIOUS} in the "
                  f"plan: {exc}", file=sys.stderr)

    # A stop that landed after the last model call -- during verify --
    # still means nothing is written: not plan.json, and (moved here for
    # the same reason) not this build's log either, so a stop caught by
    # `build()` below still reports one, honestly saying nothing landed.
    check_stopped()

    # `out_path` was already resolved (and put in `ctx`) well before this
    # point -- see the comment where it is set, above -- so a build log
    # for a build that FAILED before reaching here still knew the same
    # answer.

    # Plan.json is not the best place for a build's log. Each build writes its
    # OWN log file,
    # `<bundle>/builds/<timestamp>.json` -- the per-role
    # thinking-summary notes and usage a provider records
    # (`ModelCallProgress.build_log_entry()`), plus this build's own
    # provenance and outcome -- rather than growing plan.json with them.
    # `plan.json` keeps only a pointer, `meta.build_log_file`, so a plan
    # stays small and a build that never produced one (the `except`
    # above) still gets a log. Written here, with `plan["meta"]` already
    # fully assembled; rewritten below (same file) if the watchlist
    # draft adds a "watchlist" entry.
    log_path = _write_build_log(ctx, status=build_log_module.DONE, reason=None,
                                meta=plan["meta"])
    if log_path is not None:
        plan["meta"]["build_log_file"] = build_log_module.pointer(ctx["log_dir"], log_path)

    plan_json = json.dumps(plan, indent=2)

    # --out - means "print the plan JSON to stdout, don't write a file"
    # (the original, pre-2026-09-10 default); any other value, including
    # the default, writes a file -- see _default_out_path's docstring for
    # why that's the default rather than stdout.
    if out_path is None:
        if args.pretty:
            print(render_plan(plan, warnings))
        else:
            print(plan_json)
    else:
        out_path.write_text(plan_json + "\n", encoding="utf-8")
        written.append(out_path.name)
        # A partial reply saved by an earlier, failed build is evidence of
        # that failure only; once a plan is written it is out of date
        # (clear any plan.partial.json after a
        # successful build).
        stale_partial = _partial_path(out_path)
        if stale_partial.is_file():
            stale_partial.unlink()
            print(f"INFO {stale_partial.name} removed: a plan was built, so the partial reply "
                  f"an earlier failed build left is out of date", file=sys.stderr)
        built = "Generated"
        print(
            f"{built} plan written to {out_path} ({len(plan['channels'])} channels). "
            f"This is Atoo's own intermediate plan (the parameters it would write to a "
            f"console) -- not a conventions file, and not a WING show file. Nothing has been "
            f"written to any console -- `atoo apply` does that."
        )
        # The splits and recording feeds, which the channel count
        # does not show.
        from atoo import outputs_sheet
        direct = outputs_sheet.summary_line(plan)
        if direct is not None:
            print(direct)
        if args.pretty:
            print()
            print(render_plan(plan, warnings))

    # A build into a bundle also drafts that
    # bundle's watchlist. Deliberately after the plan is written -- the
    # plan is the deliverable, and nothing below may change this command's
    # exit code.
    if show is not None:
        _draft_watchlist_into_bundle(
            show, plan, conventions_raw,
            provider=provider, written=written,
            conventions_name=Path(conventions_path).name,
            instructions=instructions_text,
            instructions_name=Path(instructions_path).name if instructions_path else None,
        )
        # The watchlist draft is the one model call that runs AFTER the
        # plan is on disk (above). Its own build-log entry ("watchlist")
        # only exists now, so the build's log FILE (not plan.json -- its
        # `meta.build_log_file` pointer does not change) is rewritten in
        # place to fold it in. Never touches the exit code: a failure
        # writing this back is the same "warning, not a non-zero exit"
        # `_draft_watchlist_into_bundle` already gives its own failures.
        build_log_data = getattr(provider, "build_log", None) or {}
        if (build_log_data and ctx.get("log_path") is not None
                and build_log_data != (ctx.get("log_entry") or {}).get("build_log")):
            updated = build_log_module.build_entry(
                meta=plan["meta"], build_log=build_log_data,
                status=build_log_module.DONE, reason=None)
            try:
                build_log_module.rewrite(ctx["log_path"], updated)
                ctx["log_entry"] = updated
            except OSError:
                pass

    # Everything the conventions-reading layers had to say: sanitize
    if warnings and not args.pretty:
        # `warnings` is plan["notes"] -- tagged {text, source} objects, the model's own account of what it could not do.
        # This list could once also be the compiler's bare strings,
        # and most of the machinery here existed to reconcile the two.
        adapted_notes = [_note_diagnostic(w) for w in warnings]
        # Counted by severity rather than as one number: an error buried
        # in "24 warning(s)" is a mistake that was fixed once already.
        _emit_diagnostics(
            adapted_notes,
            heading=f"\n{diagnostics.summary_line(adapted_notes)}:",
        )

    # Deliberately its own block rather than merged into the stream
    # above: a critic is a model, and the whole point is that a model's
    # opinion must never read as a deterministic finding. Same renderer,
    # separate heading.
    # The comment findings were printed before generation; only the
    # generator's own conventions audit is new here.
    if audit_findings:
        _emit_diagnostics(
            audit_findings,
            heading=f"\nThe conventions themselves -- {len(audit_findings)} note(s) "
                    "(conflicts the plan had to settle, things declared but unused):",
        )

    if preset_findings:
        # Which presets' values a plan carries is a build
        # detail (`finding_groups.BUILD_DETAIL_CODES`), listed after the
        # notes that are choices -- an engine picked, an insert switched on.
        preset_notes = [f for f in preset_findings if not finding_groups.is_build_detail(f)]
        preset_details = [f for f in preset_findings if finding_groups.is_build_detail(f)]
        if preset_notes:
            _emit_diagnostics(
                preset_notes,
                heading=f"\nPresets -- {len(preset_notes)} note(s) (where the plan's own "
                        "processing won, and what the build chose for an effect):",
            )
        if preset_details:
            _emit_diagnostics(
                preset_details,
                heading=f"\nPresets -- {len(preset_details)} build detail(s) (what each named "
                        "preset put into the plan):",
            )

    pair_phantom_notes = [f for f in build_findings if f.code == "reply.pair-phantom"]
    if pair_phantom_notes:
        _emit_diagnostics(
            pair_phantom_notes,
            heading=f"\nStereo channels -- {len(pair_phantom_notes)} note(s) (the desk switches a "
                    "pair's 48V together, so each pair takes one value):")

    fixup_findings = [f for f in build_findings if f.code.startswith("build.fixup")]
    if fixup_findings:
        _emit_diagnostics(fixup_findings, heading="\nFix-up round:")

    if critic_findings:
        _emit_diagnostics(
            critic_findings,
            heading=f"\nCritic pass -- {len(critic_findings)} finding(s). These are a "
                    "model's opinion, not a gate:",
        )

    if verdict is not None and verdict.findings:
        if fixup is not None and fixup["checker"] == "verify" and verdict.errors:
            # Both rounds' errors: what the first reply was refused for,
            # then (below) what the corrected one still is.
            n, w, _ = _fixup_counts(fixup)
            counted = f"{n} error(s)" + (f" and {w} routing warning(s)" if w else "")
            print(f"\nVerification of the first reply -- {counted}, "
                  "sent back in one fix-up round:", file=sys.stderr)
            for line in fixup["errors"][:n + w]:
                print(f"  {line}", file=sys.stderr)
            print("\nVerification of the plan written, after the fix-up round:",
                  file=sys.stderr)
        print(f"\nVerification: {verdict.report(omit_details=True)}", file=sys.stderr)
        if verdict.errors:
            print("\nThe plan was still written, so you can read and fix it -- but "
                  "`atoo apply` will refuse it in this state.", file=sys.stderr)

    # FR-1.4: last, so it is what a rebuild ends on. A first build (no
    # plan.previous.json) says nothing about changes.
    if changes is not None:
        try:
            lines = changes.render(all_values=getattr(args, "all_changes", False),
                                   against=bundle.PLAN_PREVIOUS)
        except Exception as exc:  # noqa: BLE001 -- a report on the plan, never a failure
            lines = [f"WARNING could not print what changed since the last build: {exc}"]
        print(file=sys.stderr)
        for line in lines:
            print(line, file=sys.stderr)

    return 2 if (verdict is not None and verdict.errors) else 0


def _changes_since_previous(show, out_path, plan: dict) -> "plan_diff.PlanChanges | None":
    """This build's plan against the bundle's `plan.previous.json` (the
    plan a rebuild replaced, FR-1.4), or None when there is none to
    compare with -- a first build, or a build outside a show bundle.
    Never fails the build: a previous plan that cannot be read, or a
    comparison that breaks, is said at WARNING and the build goes on."""
    if show is None or out_path is None or out_path != show.plan:
        return None
    previous_path = out_path.with_name(bundle.PLAN_PREVIOUS)
    if not previous_path.is_file():
        return None
    try:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"WARNING could not read {bundle.PLAN_PREVIOUS} to say what changed since the "
              f"last build: {exc}", file=sys.stderr)
        return None
    try:
        return plan_diff.compare(previous, plan)
    except Exception as exc:  # the plan is the deliverable; this is a report on it
        print(f"WARNING could not compare this plan with {bundle.PLAN_PREVIOUS}: {exc}",
              file=sys.stderr)
        return None


def verify_cmd(args: argparse.Namespace) -> int:
    """Check an existing plan, without rebuilding or applying it.

    Separate from `build` because the loop this serves is not "make a
    plan", it is "I changed the prompt / the conventions / what I think is
    correct -- does the plan I already have still hold up". A generation
    can cost 40 minutes on a local model; re-checking one must cost
    nothing.
    """
    try:
        show = _open_bundle(args)
        _fill_from_bundle(args, show, "plan", bundle.PLAN, required=True)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not args.plan:
        # The error argparse gave before --plan stopped being required.
        print("--plan is required (or --show DIR, to take plan.json from a show bundle)",
              file=sys.stderr)
        return 1
    # Optional, and a bundle slot: verifying a bundle is `atoo verify
    # --show DIR` with nothing else to remember, which is the whole reason
    # the directory has fixed names.
    _fill_from_bundle(args, show, "input", bundle.INPUT_LIST)

    try:
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
    except OSError as exc:
        print(f"couldn't read plan {args.plan!r}: {exc.strerror}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"plan {args.plan!r} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    rows = None
    if args.input:
        try:
            rows = load_input_list(args.input)
        except (OSError, InputListError) as exc:
            print(f"couldn't read input list {args.input!r}: {exc}", file=sys.stderr)
            return 1

    result = verify_plan(plan, rows, presets=_resolve_preset_library(args),
                         console_model=getattr(args, "console_model", None),
                         layers=_plan_layers(plan, show, args.plan))
    print(result.report())

    return 2 if result.errors else 0


def compare_cmd(args: argparse.Namespace) -> int:
    """Plan vs. a show file the console saved.

    `apply` proves each write landed by reading that address straight back.
    This proves the desk as a whole still matches, from a file the console
    wrote itself -- after a recall, a soundcheck edit, or anything else
    that happened between then and now.
    """
    try:
        show = _open_bundle(args)
        _fill_from_bundle(args, show, "plan", bundle.PLAN, required=True)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not args.plan:
        print("--plan is required (or --show DIR, to take plan.json from a show bundle)",
              file=sys.stderr)
        return 1
    # `--snapshot` stays explicit on purpose: a .snap is a capture taken at
    # a moment in time, not one of the show's standing artifacts, so it has
    # no fixed slot in the bundle to resolve from.

    try:
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
    except OSError as exc:
        print(f"couldn't read plan {args.plan!r}: {exc.strerror}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"plan {args.plan!r} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        ae_data = load_snapshot(args.snapshot)
    except SnapshotError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = compare_snapshot(plan, ae_data)
    if not result.findings:
        print(f"The show file matches the plan on every field the plan states.")
        return 0

    print(f"{len(result.errors)} difference(s), {len(result.warnings)} not compared\n")
    for f in result.errors:
        print(f"  {f}")
    if result.warnings:
        print()
        for f in result.warnings:
            print(f"  {f}")
    print("\nOnly fields the plan actually states are compared -- a null fader is not "
          "an assertion about where the fader should be.")
    return 2 if result.errors else 0


def _parse_socket_counts(spec: str | None) -> dict[str, int]:
    """"LCL=20,A=48" -> {"LCL": 20, "A": 48}; a value that is not that ends the
    command with the reason (exit 2), not a traceback."""
    from atoo.console_facts import parse_socket_counts
    try:
        return parse_socket_counts(spec)
    except ValueError as exc:
        print(f"atoo: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def _gain_texts(args: argparse.Namespace, show, base: dict) -> tuple[str, ...]:
    """The conventions and the show's instructions, comments stripped: where a
    gain the engineer stated for a channel ("Playback gain 15 dB") is read, so
    that a change never overwrites it."""
    from atoo.conventions_text import strip_comments

    conventions, _name, instructions, _iname, _infos = _change_conventions(args, show, base)
    return tuple(strip_comments(text) for text in (instructions, conventions) if text)


def _aes50_devices(console, state) -> dict | None:
    """What is on each AES50 port, asked of the desk (`apply.read_aes50_devices`)
    or, offline, read from the saved capture when it carries them; None when
    nothing says (an offline capture without them also warns: an empty record
    is a record, a missing one is not)."""
    from atoo.apply import read_aes50_devices

    if console is not None:
        return read_aes50_devices(console)
    values = getattr(state, "values", None) or {}
    found = {port: values.get(facts.aes50_device_address(port)) for port in facts.AES50_PORTS}
    found = {port: (device if isinstance(device, str) else None) for port, device in found.items()}
    if not any(isinstance(d, str) for d in found.values()):
        # Checking nothing quietly makes an offline run differ
        # from the live desk, which refuses a socket past the box's size.
        print("WARNING: this saved state has no stage-box device names "
              "(/$stat/A/dev, B, C); a socket past the box's size cannot be "
              "checked. Save it again with `atoo audit --dump-state`.",
              file=sys.stderr)
        return None
    return found


def _load_state_file(path: str):
    """A JSON object of address -> value, the shape both `audit --state`
    and `watch --state-sequence` accept -- returns a `ConsoleState`, or
    None after printing a ready-to-show error (caller returns 1)."""
    from atoo.audit import ConsoleState

    try:
        # `~` is expanded here as well as by the shell: the help examples name
        # ~/Documents/Atoo/audit-demo/..., and Windows shells pass `~` through.
        with open(expand_home(path), encoding="utf-8") as f:
            values = json.load(f)
    except OSError as exc:
        print(f"couldn't read state file {path!r}: {exc.strerror}", file=sys.stderr)
        return None
    except json.JSONDecodeError as exc:
        print(f"state file {path!r} is not valid JSON: {exc}", file=sys.stderr)
        return None
    return ConsoleState(values)


def _dump_state_file(path: str, state) -> bool:
    """Write a live read to `path` in the shape `_load_state_file` reads
    back -- a flat JSON object of address -> value -- so `audit --state`
    and `watch --state-sequence` can replay it offline. False after
    printing a ready-to-show error.

    Written to a temporary file and renamed into place, so an existing
    capture of the same name is never left half-overwritten.

    The format has no slot for the console model, so the capture does not
    carry it. Said out loud rather than dropped silently: the factory
    input patches `is_in_use()` discounts are per model, and a replay
    without one can find what the live audit did not. `--plan` supplies
    the model on replay (`run_audit` takes it from `meta.console_model`).
    """
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state.values, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        print(f"--dump-state: couldn't write {path!r}: {exc.strerror}", file=sys.stderr)
        return False
    note = f"Saved {len(state.values)} addresses to {path}"
    if state.console_model:
        note += (f". The file does not record the model ({state.console_model}): "
                 f"replay it with --plan so the audit knows which desk it came from")
    print(note + ".", file=sys.stderr)
    return True


def _add_presets_argument(ap: argparse.ArgumentParser) -> None:
    """`--presets DIR` -- identical on build, verify and apply."""
    ap.add_argument(
        "--presets", default=None, metavar="DIR",
        help="Atoo's own preset library: a directory of .chn channel-preset "
             "exports, looked up by the name inside the file. These are NOT the "
             "console's own presets or scenes -- those cannot be recalled remotely at "
             "all -- they are parameter values Atoo writes like any other. `build` "
             "expands each named preset INTO the plan (its processing values, the "
             "plan's own processing winning where both set one), and `apply` writes "
             "what the plan carries; verify and apply use the library only to say "
             "whether it changed since. A plan naming a preset this library hasn't "
             "got is a warning, never a block. Defaults to [presets] default in "
             "~/.atoo.config.")


def _preset_library_choice(args: argparse.Namespace, plan: "dict | None" = None):
    """Which preset library this command uses, and why -- the one resolver
    `build`, `patch` and `amend` share (`atoo/preset_library.py`): explicit `--presets`, else the library `plan` records (or
    the packaged starter presets its files match), else
    `~/.atoo.config`'s `[presets] default`. The library is house-level,
    never a show-bundle slot; a plan only
    remembers which one its strips' values came from.

    A library that is not there is a note and no library rather than a
    hard failure: strips get built without their preset processing, which
    this project reports (`preset.no-library`) and lets the operator
    decide about, rather than refusing to run."""
    from atoo import preset_library

    return preset_library.resolve(
        getattr(args, "presets", None), plan, default=load_default_presets(),
        default_label=f"the [presets] default in {config_path()}")


def _resolve_preset_library(args: argparse.Namespace, plan: "dict | None" = None, *,
                            announce: bool = False):
    """The `PresetLibrary` `_preset_library_choice` settles on, or None. A
    stated library that is not there is said on stderr; with `announce`,
    so is which library was used and why (INFO)."""
    choice = _preset_library_choice(args, plan)
    for warning in choice.warnings:
        print(warning, file=sys.stderr)
    if announce:
        for info in choice.infos:
            print(f"INFO {info}", file=sys.stderr)
    return choice.library


def _draft_watchlist_into_bundle(show, plan: dict, conventions: str, *, provider,
                                 conventions_name: str,
                                 instructions: str | None,
                                 instructions_name: str | None,
                                 written: list[str] | None = None) -> None:
    """Draft a watchlist for a just-built plan and merge it into the
    bundle's `watch.json`.

    **This function cannot fail a build.** It returns None either way and
    the caller ignores it: a plan that built fine plus a watchlist that did
    not draft is a warning, not a non-zero exit. Every path out of here
    that isn't a successful write prints why on stderr and returns.

    The merge is additive and never rewrites a condition already in the
    file -- see `watch_conditions.merge_drafted_conditions`, which also
    explains why `drafted` is recorded alongside the conditions.
    """
    import json as _json

    from atoo.watch_conditions import (
        DRAFTED_KEY, MEANING, WatchConditionsError, merge_drafted_conditions,
    )

    drafted = generate.draft_watch_conditions(
        plan, conventions, provider=provider, conventions_name=conventions_name,
        instructions=instructions, instructions_name=instructions_name,
    )
    if drafted is None:
        # Already explained itself on stderr; `None` is "did not run",
        # which is a different fact from "ran and proposed nothing".
        return
    if not drafted:
        print("Watch-conditions draft ran and proposed nothing for this show.", file=sys.stderr)
        return

    path = show.path(bundle.WATCH_CONDITIONS)
    existing: dict | None = None
    if path.is_file():
        try:
            existing = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Refuse rather than overwrite. An unreadable watch.json is
            # far more likely to be a file someone is mid-edit on than a
            # file they want replaced by a machine.
            print(f"couldn't read {path} to merge the drafted watch conditions into it ({exc}) "
                  f"-- it was left untouched and nothing was written.", file=sys.stderr)
            return

    document, report = merge_drafted_conditions(existing, drafted, plan)

    try:
        # Validate the MERGED document, not just the draft: the merge is
        # what lands on disk, and a file the next `watch` run refuses is
        # the one thing worse than no watchlist.
        _load_watch_conditions_text(document, str(path))
    except WatchConditionsError as exc:
        print(f"merging the drafted watch conditions into {path} would have made it invalid "
              f"({exc}) -- it was left untouched.", file=sys.stderr)
        return

    if not report.changed:
        print(f"Watch-conditions draft added nothing new to {path}.", file=sys.stderr)
    else:
        try:
            check_stopped()
            path.write_text(_json.dumps(document, indent=2) + "\n", encoding="utf-8")
            if written is not None:
                written.append(path.name)
        except OSError as exc:
            print(f"couldn't write the drafted watch conditions to {path}: {exc.strerror}",
                  file=sys.stderr)
            return
        print(f"Watch conditions: {len(report.added)} drafted condition(s) added to {path} "
              f"({', '.join(report.added)}). They are marked \"source\": \"drafted\" -- "
              f"read them before the show; nothing watches until you run `atoo watch`.")

    # Said separately because each is a different kind of "and note that".
    if report.kept:
        print(f"  kept your own version of: {', '.join(report.kept)}", file=sys.stderr)
    if report.dismissed:
        print(f"  not re-added, you removed {'it' if len(report.dismissed) == 1 else 'them'} "
              f"before: {', '.join(report.dismissed)}", file=sys.stderr)
    for new_id, existing_id in report.duplicates:
        print(f"  not added: the draft's {new_id!r} says what your {existing_id!r} already "
              f"says.", file=sys.stderr)
    if report.duplicates:
        print(f"  (two conditions are the same when they have {MEANING}; a name is looked "
              "up in the plan, and a range covers the strips in it.)", file=sys.stderr)
    for new_id, existing_id in report.overlaps:
        print(f"  note: {new_id!r} and your {existing_id!r} watch the same channel and "
              f"field under different ids -- both will run, and they may disagree.",
              file=sys.stderr)
    if report.dismissed or report.kept:
        print(f"  ({DRAFTED_KEY} in {path.name} is how a deleted draft stays deleted.)",
              file=sys.stderr)


def _load_watch_conditions_text(document: dict, source: str) -> list[dict]:
    """`parse_watch_conditions` over an in-memory document, so a merged
    result is held to exactly the standard a file on disk is."""
    import json as _json

    from atoo.watch_conditions import parse_watch_conditions

    return parse_watch_conditions(_json.dumps(document), source=source)


def _load_watch_conditions_file(path: str) -> list[dict] | None:
    """A watch-conditions JSON file (FR-6.5), the same shape
    `atoo.watch_conditions.load_watch_conditions` validates --
    returns the parsed+validated condition list, or None after printing a
    ready-to-show error (caller returns 1). Mirrors `_load_plan_file`'s
    own error-handling shape (below); shared by `watch_cmd` and `ui_cmd`
    so `--watch-conditions` is validated identically from
    either entry point, rather than each command growing its own copy of
    this try/except."""
    from atoo.watch_conditions import WatchConditionsError, load_watch_conditions

    try:
        return load_watch_conditions(path)
    except WatchConditionsError as exc:
        print(str(exc), file=sys.stderr)
        return None
    except OSError as exc:
        print(f"couldn't read watch-conditions file {path!r}: {exc.strerror}", file=sys.stderr)
        return None


def _load_plan_file(path: str):
    """A plan JSON file, the same shape `atoo build`
    produces -- returns the parsed dict, or None after printing a
    ready-to-show error (caller returns 1). Mirrors `_load_state_file`'s
    own error-handling shape."""
    try:
        with open(expand_home(path), encoding="utf-8") as f:
            return json.load(f)
    except OSError as exc:
        print(f"couldn't read plan file {path!r}: {exc.strerror}", file=sys.stderr)
        return None
    except json.JSONDecodeError as exc:
        print(f"plan file {path!r} is not valid JSON: {exc}", file=sys.stderr)
        return None


CONSOLE_ENV = "ATOO_CONSOLE"
CONSOLE_PORT_ENV = "ATOO_CONSOLE_PORT"
CONSOLE_TIMEOUT_ENV = "ATOO_CONSOLE_TIMEOUT"

DEFAULT_CONSOLE_PORT = 2223
DEFAULT_CONSOLE_TIMEOUT = 1.0


def _env_number(name: str, cast, what: str):
    """One `ATOO_CONSOLE_*` numeric environment variable, or None.

    A value that will not parse prints one line and is ignored rather
    than raising -- the same quiet-but-visible posture `config.py` takes
    for its own file, and for the same reason: a stale `export` in a
    shell should not turn every command into a traceback.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return cast(raw)
    except ValueError:
        print(f"{name}={raw!r} is not {what} -- ignoring it", file=sys.stderr)
        return None


def resolve_console_defaults() -> dict:
    """Where a command that names no console on its command line would
    end up pointing, and where each value came from.

    **This is the one implementation of the precedence rule**
    below the flag: `ATOO_CONSOLE*` beats `~/.atoo.config`'s
    `[console]` section, which beats the built-in default. Two callers
    share it, and deliberately so -- two copies of a precedence rule is
    how they drift:

    * `_resolve_console_settings` below, which layers "an explicit flag
      beats all three" on top for every CLI command that has a
      `--console`, and announces on stderr.
    * `ui_cmd`, which hands the result to `webui.create_app` so the Watch
      page's console field seeds from the same place `ping`, `apply`,
      `audit` and `watch` do. `ui` has no `--console` of its
      own -- see `_resolve_console_settings`'s second note -- so it needs
      the values without the arg-mutating half.

    Returns `{"address", "address_source", "port", "port_source",
    "timeout", "timeout_source"}`. `address` is None when nothing named
    one; `port`/`timeout` always carry the built-in default as a
    fallback. Each `*_source` is a human-readable origin -- the variable
    name, or `<config path> [console]` -- or **None when the value is the
    built-in default**, because a value nobody chose has no provenance to
    show. Whether a given origin is worth announcing is the caller's
    call, not this function's: the CLI stays quiet about a config file
    that merely restates port 2223, and so does the Watch page.
    """
    defaults = load_console_defaults()

    address = address_source = None
    env_address = os.environ.get(CONSOLE_ENV, "").strip()
    if env_address:
        address, address_source = env_address, CONSOLE_ENV
    elif defaults["address"]:
        address, address_source = defaults["address"], f"{config_path()} [console]"

    port, port_source = DEFAULT_CONSOLE_PORT, None
    env_port = _env_number(CONSOLE_PORT_ENV, int, "a port number")
    if env_port is not None:
        port, port_source = env_port, CONSOLE_PORT_ENV
    elif defaults["port"] is not None:
        port, port_source = defaults["port"], f"{config_path()} [console]"

    timeout, timeout_source = DEFAULT_CONSOLE_TIMEOUT, None
    env_timeout = _env_number(CONSOLE_TIMEOUT_ENV, float, "a number of seconds")
    if env_timeout is not None:
        timeout, timeout_source = env_timeout, CONSOLE_TIMEOUT_ENV
    elif defaults["timeout"] is not None:
        timeout, timeout_source = defaults["timeout"], f"{config_path()} [console]"

    return {
        "address": address, "address_source": address_source,
        "port": port, "port_source": port_source,
        "timeout": timeout, "timeout_source": timeout_source,
    }


def _resolve_console_settings(args: argparse.Namespace) -> None:
    """Fill in `--console`, `--port` and `--timeout` from the environment
    and `~/.atoo.config`, and say so when they did not come from the
    command line. 

    **Precedence, matching every other optional input in this CLI:** an
    explicit flag beats `ATOO_CONSOLE*`, which beats the config
    file's `[console]` section, which beats the built-in default. Same
    shape as `_fill_from_bundle`'s "explicit flags always win".

    Two things this deliberately does NOT do:

    1. **It does not default silently.** A run that connects somewhere
       the command line never named says so on stderr, once. The failure
       that prevents is a stale `export` in a shell, aimed at last week's
       desk, on a command carrying `--confirm`. `--port` and `--timeout`
       announce only when they actually change the outcome -- a config
       file restating the default port is not news.
    2. **It does not touch a command that has no `--console`.** `ui`
       has a `--port`, and it is the web server's, not a console's.
       `hasattr(args, "console")` is the guard, so the resolver simply
       does not run there. (`ui` still seeds its *page's* console field
       from the same defaults -- it calls `resolve_console_defaults`
       directly, which touches no args at all.)

    An explicitly-chosen offline source (`audit --state`, `watch
    --state-sequence`) suppresses address resolution entirely: those runs
    never open a socket, and announcing a console they will not contact
    would be a lie in the one place this is meant to tell the truth.
    """
    if not hasattr(args, "console"):
        return

    offline = (getattr(args, "state", None) or getattr(args, "state_sequence", None)
               or getattr(args, "snap", None))
    resolved = resolve_console_defaults()

    if args.console is None and not offline and resolved["address"]:
        args.console = resolved["address"]
        print(f"Using console {resolved['address']} from {resolved['address_source']}",
              file=sys.stderr)

    if getattr(args, "port", None) is None:
        args.port = resolved["port"]
        if resolved["port_source"] and resolved["port"] != DEFAULT_CONSOLE_PORT:
            print(f"Using console port {resolved['port']} from {resolved['port_source']}",
                  file=sys.stderr)

    if getattr(args, "timeout", None) is None:
        args.timeout = resolved["timeout"]
        if resolved["timeout_source"] and resolved["timeout"] != DEFAULT_CONSOLE_TIMEOUT:
            print(f"Using console timeout {resolved['timeout']}s from "
                  f"{resolved['timeout_source']}", file=sys.stderr)

    if not offline:
        # How many reads are kept in flight. Set by the
        # environment only, and read again by `WingConsole` itself, so the
        # Watch page gets the same window; said here when it is not the
        # default, like the timeout above.
        from atoo.console import window_notice

        notice = window_notice()
        if notice:
            print(notice, file=sys.stderr)


def _no_console_address(*, offline: str | None = None) -> int:
    """Print the "you have not said which console" error and return the
    exit code for it.

    This replaces argparse's own `required=True` message on four
    commands. It has to name all three ways of supplying an
    address, because the old message named one and would now be wrong:
    `--console` is required-or-resolvable, not required.

    Exit code 2, which is what argparse itself exits with for a missing
    required argument -- a script that tested for it keeps working.
    """
    lines = ["no console address -- say which desk to talk to, one of:",
             "  --console <ip>",
             f"  export {CONSOLE_ENV}=<ip>",
             f"  a [console] default in {config_path()}"]
    if offline:
        lines.append(f"  {offline} to work from an offline capture instead")
    print("\n".join(lines), file=sys.stderr)
    return 2


def _open_read_raw_log(args: argparse.Namespace):
    """`audit`/`watch --raw-log FILE`, opened for append and LINE-BUFFERED.

    Line-buffered on purpose. The read this flag exists to diagnose is the
    slow or stuck one, eight unanswered addresses costing 24s
    of a 47s read -- and the run an operator gives up on with Ctrl-C is the
    one whose log matters most. A block-buffered file would lose its tail
    exactly then."""
    path = getattr(args, "raw_log", None)
    return open(path, "a", buffering=1, encoding="utf-8") if path else None


def _open_console(args: argparse.Namespace, raw_log=None):
    """Connect and confirm identity -- returns the open `WingConsole`, or
    None after printing a ready-to-show error (caller returns 1). Caller
    owns closing it.

    `raw_log`, an open file, records every request and reply from the very
    first `/?` onward -- the identity exchange included, since a desk that
    will not identify itself is one of the things a raw log is for."""
    from atoo.console import WingConsole

    console = WingConsole(args.console, port=args.port, timeout=args.timeout, raw_log=raw_log)
    identity = console.identity()
    if identity is None:
        console.close()
        print(f"no reply from {args.console}:{args.port} -- is the console reachable, and is "
              f"its OSC remote enabled?", file=sys.stderr)
        return None
    if identity.is_socket_error:
        # The fix, which until now lived only in `apply_cmd`'s own
        # copy of this connect sequence -- so `audit` and `watch` still
        # printed the nonsensical `Console: OSError: [Errno 65] No route to
        # host` and carried on as if connected. A SOCKET_ERROR reply is
        # truthy, which is exactly what made the original bug possible.
        # Found while adding `atoo ping`, whose whole job
        # is to tell these two failure modes apart.
        console.close()
        print(f"couldn't reach {args.console}:{args.port} -- {identity.args[0]}", file=sys.stderr)
        return None
    print(f"Console: {', '.join(identity.args)}" if identity.args else f"Console at {args.console}")
    # The desk states its own model, which is better evidence
    # than a flag and removes the need for one on every online command.
    # Stashed on args so the command can cross-check the plan against it.
    args.detected_console_model = facts.model_from_identity(identity.args)
    # And the whole reply, so a write can record WHICH desk it wrote to
    # (`_desk_of`, per-desk journal history) without a second round trip.
    args.console_identity = list(identity.args)
    return console


def _desk_of(args: argparse.Namespace) -> dict | None:
    """The desk this invocation is talking to, as the journal stack records
    it (`journal_stack.desk_from_identity`): the `/?` reply `_open_console`
    or `apply_cmd` stashed, plus the address and port it was reached at.

    Just the address when no identity was stashed -- a desk opened some
    other way, or a test double -- which `journal_stack.same_desk` compares
    as the fallback it is. None with no console at all (`--state`)."""
    from atoo import journal_stack

    return journal_stack.desk_from_identity(
        getattr(args, "console_identity", None), getattr(args, "console", None),
        getattr(args, "port", None))


def _console_read_kwargs(args: argparse.Namespace, plan: dict | None = None) -> dict:
    """The `read_console_state` arguments for this invocation.

    `--input-sockets`/`--output-sockets` still win outright,
    but when they are absent this no longer means "read no physical
    sockets at all". `audit.socket_groups_to_read` derives them from the
    model the desk stated on `/?` (stashed by `_open_console`) and from
    the plan, if one was given -- because a run that reads no sockets is a
    silent partial audit, and that is what every hardware run so far has
    been.

    `bulk` is True unless `--per-leaf` was passed. The node-dump read
    became the CLI's default once A11 found the two paths agreeing on
    every value (2026-09-24). It is decided HERE, not by
    `read_console_state`'s own default, which stays per-leaf on purpose:
    the A11 desk script calls the library with no
    `bulk` argument as its per-leaf side of that very comparison, and a
    library default flipped under it would compare the dump with itself
    and report a meaningless zero. `--bulk-read` is accepted and changes
    nothing.
    """
    from atoo.audit import socket_groups_to_read

    stated_in = _parse_socket_counts(args.input_sockets)
    stated_out = _parse_socket_counts(args.output_sockets)
    derived_in, derived_out = socket_groups_to_read(
        getattr(args, "detected_console_model", None), plan)
    return dict(
        channels=args.channels, aux=args.aux, buses=args.buses, mains=args.mains,
        matrices=args.matrices, dcas=args.dcas, mute_groups=args.mute_groups,
        input_sockets=stated_in or derived_in,
        output_sockets=stated_out or derived_out,
        bulk=not getattr(args, "per_leaf", False),
    )


def _read_progress(args: argparse.Namespace, read_kwargs: dict, *, names_known: bool = False):
    """A `ReadProgress` for one live console read, or None if the user
    asked for silence.

    A live read is 6,197 addresses on a WING Compact -- 325
    requests by node dump, pipelined eight in flight by default (`ATOO_CONSOLE_WINDOW`) -- and it used to print nothing at all
    for the whole of them; it could not be told from
    a hang at the desk, and the last tool that looked hung got killed
    mid-run. The total comes from `audit.console_read_plan`, counted
    rather than estimated, so the percentage is real.

    It goes to **stderr**, not stdout: every desk-run script
    redirects a command's output to a file it
    then treats as the run's evidence, and a progress line is not
    evidence. `run_logged` merges the two, so it lands in the log anyway.
    """
    if getattr(args, "no_progress", False):
        return None
    from atoo.progress import ReadProgress

    # The denominator can grow a little: a leaf a node dump turns out not
    # to carry is read on its own afterwards, and that is one request more
    # than planned. Better a moving denominator than a percentage over 100
    # or a guess at how many will be missing. `names_known`: a watch pass
    # between name refreshes, which asks for no names.
    total = read_requests(read_kwargs, names_known=names_known)
    from atoo.console import window_setting

    return ReadProgress(total, label="read",
                        timeout=getattr(args, "timeout", None) or DEFAULT_CONSOLE_TIMEOUT,
                        window=window_setting()[0])


def _phases(args: argparse.Namespace):
    """A `progress.Phases` for a run that reads and writes a desk (`apply`,
    `undo`, `patch`), or None if the user asked for silence.

    At the desk on 2026-10-12, `apply --confirm` printed its
    verify block and then nothing for the whole of the reset's read (39.6s)
    and the writes after it, and was taken for a hang -- the
    failure, on the one command that fix did not reach. Each phase now says
    what it is doing on stderr, the way `audit`'s read does, for the same
    reasons (`_read_progress`): stdout stays the run's evidence."""
    if getattr(args, "no_progress", False):
        return None
    from atoo.console import window_setting
    from atoo.progress import Phases

    return Phases(timeout=getattr(args, "timeout", None) or DEFAULT_CONSOLE_TIMEOUT,
                  window=window_setting()[0])


#: `--no-progress`'s help on the commands that write.
NO_PROGRESS_WRITE_HELP = (
    "Do not print what the run is doing while it reads and writes the console. Each long "
    "phase -- reading the desk (a preview reads the reset's settings and the plan's in one pass), writing (each setting "
    "is read back as it is written), reading back again what disagreed -- normally "
    "prints its name, how far it has got and the address in flight on stderr as it "
    "goes, and a line with its count and time when it ends. Without it a slow run looks "
    "like a hung one, so pass this only when something downstream is parsing stderr.")


def ping_cmd(args: argparse.Namespace) -> int:
    """`atoo ping` -- connect, say what answered, stop.

    Every online command already opens with `_open_console`'s `/?`
    identity round trip, so "is the desk reachable, and is its OSC remote
    enabled" has always been answerable -- it just required running a
    command that does something else on the way. The standing answer was
    `atoo audit --console <ip>`, which reads the whole console first
    and only then prints the line you wanted. That is the first thing
    anyone does at a desk and it should not require knowing which other
    command happens to print the identity.

    **It reads nothing else.** One OSC round trip, no strip sweep, no
    writes, nothing touched -- which is what makes it safe to type in the
    middle of a show. `tests/test_ping.py` asserts that by counting the
    requests a fake console receives, rather than trusting this docstring
    to stay true.

    It also names the model the desk states for itself
    (`console_facts.model_from_identity`), because that is what `apply`
    cross-checks a plan against before writing anything, and
    seeing it before an apply beats discovering it during one.
    """
    if args.console is None:
        return _no_console_address()
    console = _open_console(args)
    if console is None:
        return 1
    with console:
        model = getattr(args, "detected_console_model", None)
        if model is None:
            # Not a failure: the desk answered, which is what was asked.
            # But `apply`'s model cross-check needs a model it recognises,
            # so an unfamiliar one is worth saying out loud here, with the
            # token itself -- it is the string to add to
            # `console_facts.IDENTITY_MODEL_ALIASES`.
            token = facts.identity_model_token(getattr(args, "console_identity", None))
            said = (f"{token!r} is not a model Atoo has measured" if token
                    else "the desk stated no model")
            print(f"Detected model: not recognized ({said}). `apply` will check sockets "
                  "against the plan's own model only, and warn before writing.")
        else:
            print(f"Detected model: {facts.CONSOLE_MODELS[model]['label']} ({model})")
    return 0


def capture_cmd(args: argparse.Namespace) -> int:
    """`atoo capture` (desk sheets piece 1) -- a desk you didn't
    build, as a show bundle: `input.csv`, `busses.csv`, `outputs.csv`, `user.csv`, a plan of the desk as
    it is, an empty `watch.json`, and the snapshot it was made from.

    **No model, and nothing written to the desk.** The whole job is in
    `atoo.capture`; this reads the source and writes the folder. Every value
    the desk does not state is decided there and printed here, at INFO."""
    import datetime

    from atoo import capture
    from atoo.firstrun import default_directory

    captured = datetime.date.today().isoformat()
    if args.snap and args.console:
        print("capture reads one desk: give --console or --snap, not both", file=sys.stderr)
        return 1
    if args.snap:
        model = args.console_model
        if model is None:
            print(f"a .snap does not say which WING wrote it, and the socket counts differ "
                  f"between them -- pass --console-model ({', '.join(sorted(facts.CONSOLE_MODELS))})",
                  file=sys.stderr)
            return 1
        try:
            read = capture.from_snap(expand_home(args.snap), model, captured=captured)
        except SnapshotError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        source = f"the snapshot {args.snap}"
    else:
        if args.console is None:
            return _no_console_address()
        console = _open_console(args)
        if console is None:
            return 1
        with console:
            model = getattr(args, "detected_console_model", None) or args.console_model
            if model is None:
                print("the desk stated a model Atoo does not know, so its sockets cannot be "
                      "checked -- pass --console-model", file=sys.stderr)
                return 1
            read = capture.from_console(
                console, model, captured=captured,
                progress=_read_progress(args, dict(capture.live_read_kwargs(model), bulk=True)))
        source = f"the desk at {args.console}"

    result = read.capture
    parent = Path(expand_home(args.dir)) if args.dir else (load_default_workspace()
                                                           or default_directory())
    target = capture.free_directory(parent, args.name or read.name)
    capture.write_bundle(result, target, evidence_name=read.evidence_name, evidence=read.evidence)

    print(f"Captured {source} to {target}/")
    for line in capture.summary_lines(result):
        print(f"  {line}")
    print(f"  {bundle.CAPTURES}/{read.evidence_name}")
    if result.notes:
        print(f"\nWhat the desk does not state, decided or left out "
              f"({len(result.notes)}):")
        for note in result.notes:
            print(f"  [INFO] {note}")
    print(f"\nNothing was written to the desk. Watch it with this show:\n"
          f"  atoo watch --show {target} --console <address>")
    return 0


def presets_cmd(args: argparse.Namespace) -> int:
    """`atoo presets` -- list a preset library.

    A preset's name is the `info_text` label INSIDE the `.chn` file, not
    its filename, and that is the right call: it is the name the engineer
    gave it on the desk. But it means `ls` does not tell you what your own
    library is called -- nothing about a file's name says what it answers
    to, and a conventions file naming a filename that differs from the
    saved name silently gets no preset at all.

    Bus presets (`.bus`) are listed after the channel presets,
    with the effect each inserts and the engine it was saved from.

    Before this, the only way to learn the real names was to ask for one
    that does not exist and read them off the `preset.unknown` warning.
    That works, and it needs a plan that already names a preset.

    **The warnings column is the part that is more than a convenience.** A
    preset carrying an unrecognised field, or a sidechain keyed off
    another channel, already reports itself -- but only when some plan
    happens to name it. A listing is where you would find out otherwise.

    Deliberately does NOT go through `_resolve_preset_library`, which
    warns and returns None for a directory that is not there because a
    missing library should not stop a show being built. Here the library
    IS the subject: asking to list one that does not exist is a file this
    command could not read, which is exit 1.
    """
    from atoo.presets import PresetError, PresetLibrary, normalize_preset_name

    chosen, source = args.presets, "--presets"
    if not chosen:
        default = load_default_presets()
        if default is None:
            print("no preset library given -- pass --presets DIR, or set a [presets] "
                  f"default in {config_path()}.", file=sys.stderr)
            return 1
        chosen, source = str(default), f"the [presets] default in {config_path()}"
        print(f"No --presets given -- using {source}: {chosen}\n", file=sys.stderr)

    directory = Path(chosen)
    try:
        library = PresetLibrary(directory)
        presets = list(library)
    except PresetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if getattr(args, "expand", None):
        return _expand_presets_into_plan(args, library)

    if not presets:
        # A true answer to the question asked, so 0: it ran, and there is
        # nothing to report. An empty library is a thing an engineer needs
        # to be told plainly, not an error to debug.
        print(f"No presets in {directory} -- no .chn files there.")
        return _print_bus_presets(library)

    # Name, not filename, is what a plan matches on, so it leads. Sorted
    # by it for the same reason: this list is read to find a name.
    presets.sort(key=lambda preset: (normalize_preset_name(preset.name), preset.name))

    name_width = max(len("name"), max(len(preset.name) for preset in presets))
    count_width = max(len("params"), max(len(str(len(preset.parameters))) for preset in presets))
    file_width = max(len("file"), max(len(preset.source_path.name) for preset in presets))

    print(f"{len(presets)} preset(s) in {directory}\n")
    print(f"{'name'.ljust(name_width)}  {'params'.rjust(count_width)}  file")
    print(f"{'-' * name_width}  {'-' * count_width}  {'-' * file_width}")
    for preset in presets:
        print(f"{preset.name.ljust(name_width)}  "
              f"{str(len(preset.parameters)).rjust(count_width)}  "
              f"{preset.source_path.name}")

    # Two kinds of library-hygiene problem, both otherwise invisible until
    # a plan happens to name the preset carrying them.
    flagged = [preset for preset in presets if preset.warnings]
    by_name: dict[str, list] = {}
    for preset in presets:
        by_name.setdefault(normalize_preset_name(preset.name), []).append(preset)
    duplicates = {name: found for name, found in by_name.items() if len(found) > 1}

    if flagged or duplicates:
        print()
    for name, found in sorted(duplicates.items()):
        files = ", ".join(preset.source_path.name for preset in found)
        # `PresetLibrary.get` picks the newest rather than raising,
        # so this is a hygiene report, not a
        # refusal -- but which one wins is decided by mtime, and mtime is
        # not preserved by `git clone`.
        print(f"warning: {len(found)} files share the name "
              f"{found[0].name!r}: {files}. The newest wins when a plan asks for it.")
    for preset in flagged:
        print(f"warning: {preset.name} ({preset.source_path.name}) --")
        for warning in preset.warnings:
            print(f"  {warning}")

    if _print_bus_presets(library):
        return 1
    # Warnings alone are still 0, the same as `verify` (see the canonical
    # exit-code table): the listing ran and is complete.
    return 0


def _print_bus_presets(library) -> int:
    """The library's bus presets (`.bus`): name, the effect it
    inserts and the engine it was saved from, and any warning. Returns 1
    when a `.bus` cannot be read, else 0."""
    from atoo.presets import INSERT_POINT_NAMES, PresetError

    try:
        buses = library.bus_presets()
    except PresetError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not buses:
        return 0
    buses.sort(key=lambda b: b.name.lower())
    width = max(len("bus preset"), max(len(b.name) for b in buses))

    def effect(b) -> str:
        if not b.inserts:
            return "no effect"
        return "; ".join(
            f"{i.model} ({INSERT_POINT_NAMES.get(i.point, i.point)}"
            + (f", saved on FX{i.saved_engine}" if i.saved_engine else "")
            + (", saved bypassed" if not i.saved_on else "") + ")"
            for i in b.inserts)

    rows = [(b.name, effect(b), b.source_path.name) for b in buses]
    effect_width = max(len("effect"), max(len(r[1]) for r in rows))
    print(f"\n{len(buses)} bus preset(s)\n")
    print(f"{'bus preset'.ljust(width)}  {'effect'.ljust(effect_width)}  file")
    print(f"{'-' * width}  {'-' * effect_width}  {'-' * max(len(r[2]) for r in rows)}")
    for name, eff, file in rows:
        print(f"{name.ljust(width)}  {eff.ljust(effect_width)}  {file}")
    for b in buses:
        if b.warnings:
            print(f"warning: {b.name} ({b.source_path.name}) --")
            for warning in b.warnings:
                print(f"  {warning}")
    return 0


def _expand_presets_into_plan(args: argparse.Namespace, library) -> int:
    """`atoo presets --expand PLAN`: what `build`
    does to a plan's named presets, without a model call.

    `build` resolves every named preset into the plan it writes
    (`processing.preset_values`), so a built plan needs nothing from here.
    This is for the plan that did not get that: one built before slice B,
    one built with no library, one whose preset name was edited by hand, or
    one whose library copy has changed since. Same function as `build`
    (`preset_expand.expand_plan`), same INFO for every value the plan's own
    processing overrides, and the plan is only rewritten when something in
    it actually changed. Nothing is read from or written to a console.
    """
    plan = _load_plan_file(args.expand)
    if plan is None:
        return 1
    before = json.dumps(plan, sort_keys=True)
    findings = preset_expand.expand_plan(plan, library)
    if findings:
        _emit_diagnostics(findings, heading=f"Presets -- {len(findings)} note(s):")
    out = Path(args.out) if getattr(args, "out", None) else Path(args.expand)
    carried = [c for c in plan.get("channels") or []
               if isinstance(c, dict) and preset_expand.preset_values(c)]
    from atoo import bus_presets
    bus_count = sum(1 for e in (plan.get("busses") or {}).values()
                    if bus_presets.preset_values(e))
    bus_words = f", and {bus_count} bus(ses) a bus preset's" if bus_count else ""
    if json.dumps(plan, sort_keys=True) == before and out == Path(args.expand):
        print(f"{args.expand}: already up to date -- {len(carried)} channel(s) carry preset "
              f"values{bus_words}; nothing written.")
        return 0
    try:
        out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"couldn't write {out}: {exc.strerror}", file=sys.stderr)
        return 1
    leaves = sum(len(preset_expand.preset_values(c)["leaves"]) for c in carried)
    print(f"Wrote {out}: {len(carried)} channel(s) carry preset values ({leaves} in all)"
          f"{bus_words}, resolved from {library.directory}. Nothing has been written to any console -- "
          "`atoo apply` does that.")
    return 0


def audit_cmd(args: argparse.Namespace) -> int:
    # Imported here for the same reason apply_cmd imports console lazily --
    # `atoo build`/`--help` shouldn't pay for the console layer.
    from atoo.audit import (
        build_signal_graph, diff_against_plan, plan_processing_read_addresses,
        read_console_state, render_coverage, render_findings, render_trace,
        run_audit, trace_signal_path, Severity, SEVERITY_ORDER,
    )

    try:
        show = _open_bundle(args)
        _fill_from_bundle(args, show, "plan", bundle.PLAN)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # --plan is independent of --state/--console: it works on top of
    # whichever live-state source is selected below. It does three things
    # -- it adds the conventions-diff findings (FR-4.1), it scopes the
    # structural rules to what the plan is actually about (FR-4.5), and it names the physical sockets this rig has, which is
    # why it is now loaded BEFORE the console read rather than after it
    # (the model knows the panel, only the plan knows the
    # stage boxes).
    plan = None
    if args.plan:
        plan = _load_plan_file(args.plan)
        if plan is None:
            return 1

    if args.dump_state:
        if args.state:
            print("--dump-state writes what a LIVE read saw; with --state there is no "
                  "read to save -- the capture is already the file you named.",
                  file=sys.stderr)
            return 1
        # Checked before the read, not after it: a directory that cannot
        # take the file should cost nothing, not a whole read of the desk.
        dump_dir = os.path.dirname(os.path.abspath(args.dump_state))
        if not os.path.isdir(dump_dir) or not os.access(dump_dir, os.W_OK):
            print(f"--dump-state: cannot write into {dump_dir!r}; nothing was read.",
                  file=sys.stderr)
            return 1

    if args.state:
        state = _load_state_file(args.state)
        if state is None:
            return 1
    else:
        if args.console is None:
            return _no_console_address(offline="--state FILE")
        raw_log = _open_read_raw_log(args)
        try:
            console = _open_console(args, raw_log=raw_log)
            if console is None:
                return 1
            with console:
                read_kwargs = _console_read_kwargs(args, plan)
                # The processing leaves the plan states (trim, balance, invert,
                # head-amp gain, filters, EQ), for CV008: only `audit`
                # compares them, so only it reads them.
                read_kwargs["extra"] = plan_processing_read_addresses(plan)
                if args.dump_state:
                    # What is on each AES50 port, so an offline
                    # patch of the saved reading can check a socket against
                    # the box's size as the live desk does.
                    read_kwargs["extra"] += [(facts.aes50_device_address(port), "s")
                                             for port in facts.AES50_PORTS]
                progress = _read_progress(args, read_kwargs)
                if not read_kwargs.get("bulk"):
                    print(PER_LEAF_BANNER, file=sys.stderr, flush=True)
                state = read_console_state(console, progress=progress, **read_kwargs)
                if progress is not None:
                    progress.finish()
        finally:
            if raw_log is not None:
                raw_log.close()
        if args.dump_state and not _dump_state_file(args.dump_state, state):
            return 1

    findings = run_audit(state, plan=plan)

    if plan is not None:
        findings = findings + diff_against_plan(state, plan)
        # run_audit() already sorted its own findings, but that sort
        # doesn't re-apply once more findings are appended -- redo it on
        # the combined list so severity/rule-id order still holds.
        findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))

    # rstrip so the coverage note below is separated by exactly one blank
    # line whether or not `render_findings` ended with one.
    print(render_findings(findings).rstrip("\n"))
    # Say what the reading covered. A report that silently
    # omits four rules reads exactly like a report that ran them and
    # found nothing.
    print("\n" + render_coverage(state, from_capture=bool(args.state)))

    if args.trace_from and args.trace_to:
        graph = build_signal_graph(state)
        result = trace_signal_path(graph, args.trace_from, args.trace_to)
        print(render_trace(result))

    return 1 if any(f.severity == Severity.ERROR for f in findings) else 0


# Both measured on a WING Compact by A11 on 2026-09-24
# (desk run A11, session 2026-09-24-1045),
# the run that made the node-dump read the default:
#
#   per-leaf:   5,860 requests in 118.8s -> ~20.3 ms a request
#   node dump:    352 requests in   4.8s -> ~13.6 ms a request
#
# A dump request is dearer than a GET (a ~2kB reply rather than ~40
# bytes) and there are sixteen times fewer of them. Used only to tell
# the user what they are waiting for; nothing branches on them. They
# replace a single 163-requests-a-second figure from A1's raw log
# (2026-09-21), which predated the 320-address fix and was ~3.3x optimistic for a
# whole-desk per-leaf read.
#
# How many addresses a pass asks for is not a constant beside them. It
# was 5,288, then 5,928, then 6,032, then 5,712 once 320 addresses
# the desk does not have were dropped, 5,808 once each strip's
# alternate patch was read, 6,112 once every insert
# point and FX slot was read, 6,113 once the comms half read
# `/cfg/talk/assign`, 6,114 once `/io/altsw` was read, 6,138 once
# each phantom-capable socket's width was read, 6,143 once three AES50 link
# states and two monitor sources were read, 6,167 once
# each local socket's own mute was read, 6,195 once the width of each bus,
# Main and Matrix was read, and it is 6,197 since what each expansion bay holds
# was read -- a
# hand-maintained number that went stale every time the read changed, and
# that never included the physical sockets at all. `read_addresses()` counts the
# plan instead, for the exact flags this invocation is using.
PER_LEAF_SECONDS_PER_REQUEST = 118.8 / 5860
NODE_DUMP_SECONDS_PER_REQUEST = 4.8 / 352


def read_addresses(read_kwargs: dict) -> int:
    """How many addresses one live pass with these settings asks for."""
    from atoo.audit import console_read_plan

    return len(console_read_plan(**{k: v for k, v in read_kwargs.items() if k != "bulk"}))


def read_requests(read_kwargs: dict, *, names_known: bool = False) -> int:
    """How many requests one live pass asks the desk, the way this
    invocation will read it: one per address with `--per-leaf`, otherwise
    one per node plus one per leaf no node dump covers (names, tags).

    `names_known`: a `watch` pass between name refreshes,
    which takes its names from the last refresh and asks for none of them
    -- 88 fewer requests on a Compact either way.

    The first pass only. The socket-name second pass depends on what the
    first one finds -- a few dozen on a patched desk, per-leaf either
    way -- and a leaf a dump turns out not to carry costs one more; both
    are small next to the total and neither is knowable in advance.
    """
    from atoo.audit import console_read_plan, group_plan_by_node, is_name_address

    plan = console_read_plan(**{k: v for k, v in read_kwargs.items() if k != "bulk"})
    if names_known:
        plan = [(address, value_type) for address, value_type in plan
                if not is_name_address(address)]
    if not read_kwargs.get("bulk"):
        return len(plan)
    by_node, alone = group_plan_by_node(plan)
    return len(by_node) + len(alone)


def estimated_pass_seconds(read_kwargs: dict, *, names_known: bool = False) -> float:
    """Roughly how long one live pass takes on hardware, from A11's rates."""
    rate = (NODE_DUMP_SECONDS_PER_REQUEST if read_kwargs.get("bulk")
            else PER_LEAF_SECONDS_PER_REQUEST)
    return read_requests(read_kwargs, names_known=names_known) * rate


def watch_name_refresh(args: argparse.Namespace) -> int:
    """How many passes `watch` goes between reading names:
    `--name-refresh` when given, otherwise `watch.DEFAULT_NAME_REFRESH`
    by node dump and 1 -- every pass -- with `--per-leaf`. A per-leaf
    pass is about two minutes, so a refresh every five would leave a
    rename unseen for ten of them, to save 88 of ~6,100 requests."""
    from atoo.watch import DEFAULT_NAME_REFRESH

    stated = getattr(args, "name_refresh", None)
    if stated is not None:
        return stated
    return 1 if getattr(args, "per_leaf", False) else DEFAULT_NAME_REFRESH


PER_LEAF_BANNER = (
    "--per-leaf: one GET per leaf instead of node dumps -- about 6,100 requests, "
    "roughly two minutes on a WING Compact\n"
    "  (measured: 118.8s per-leaf against 4.8s by node dump). This is the "
    "diagnostic path; the\n"
    "  default read agreed with it on all 5,860 values compared."
)


def _format_duration(seconds: float) -> str:
    seconds = max(1, round(seconds))
    if seconds < 90:
        return f"{seconds}s"
    return f"{round(seconds / 60)} minute(s)"


def _watch_estimate(read_kwargs: dict, max_iterations: int | None,
                    interval: float, name_refresh: int = 1) -> str:
    """The line `watch --console` prints before its first pass: how many
    addresses, how many requests, and how long that is on hardware.

    A pass is a node-dump read by default -- 325
    requests on a Compact, 237 between name refreshes, and
    seconds rather than minutes -- so the gap BETWEEN passes is no
    longer negligible next to the pass itself, and a total that left it
    out would be wrong by half at the default two-second interval.
    `watch` sleeps between passes, not after the last one.

    With names refreshed every `name_refresh` passes it says
    what a pass between refreshes costs too, and the total counts each
    kind of pass at its own price.
    """
    addresses = read_addresses(read_kwargs)
    requests = read_requests(read_kwargs)
    seconds = estimated_pass_seconds(read_kwargs)
    how = (f"as {requests} requests by node dump" if read_kwargs.get("bulk")
           else "one request each (--per-leaf)")
    line = (f"Reading {addresses} addresses per pass, {how} -- roughly "
            f"{_format_duration(seconds)} each on hardware")
    between = seconds
    if name_refresh > 1:
        between = estimated_pass_seconds(read_kwargs, names_known=True)
        line += (f". Names are read at Start and every {name_refresh} passes; the passes "
                 f"between ask {read_requests(read_kwargs, names_known=True)} requests, "
                 f"roughly {_format_duration(between)}")
    if not max_iterations:
        return line + ", until you stop it."
    refreshes = (-(-max_iterations // name_refresh) if name_refresh > 1
                 else max_iterations)
    total = (refreshes * seconds + (max_iterations - refreshes) * between
             + max(0, max_iterations - 1) * interval)
    return line + f", so {max_iterations} pass(es) is about {_format_duration(total)}."


def _bundle_plan_dict(show) -> dict | None:
    """The open bundle's plan, parsed; None without a bundle or a plan, or
    when it will not parse -- a broken plan.json is Build's to report."""
    if show is None or not show.plan.is_file():
        return None
    try:
        plan = json.loads(show.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return plan if isinstance(plan, dict) else None


def watch_cmd(args: argparse.Namespace) -> int:
    from atoo.audit import (DEFAULT_RULES, coverage_caveat, read_console_state,
                                 render_coverage, render_findings, Severity)
    from atoo.watch import render_event, watch

    try:
        show = _open_bundle(args)
        _fill_from_bundle(args, show, "watch_conditions", bundle.WATCH_CONDITIONS)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "record_meters", None) and not args.console:
        print("--record-meters records the console's meter stream, so it needs --console: "
              "a state file or the Demo has no meters to record.", file=sys.stderr)
        return 2

    watch_conditions_path = args.watch_conditions
    if not watch_conditions_path:
        # No --watch-conditions given, and no bundle supplied one --
        # fall back to a settled house
        # watch-conditions file named in ~/.atoo.config's
        # [watch_conditions] section, the same "only when nothing else was
        # found/stated" precedence build()'s own ~/.atoo.config
        # fallback uses (this file's build(), ~line 262) -- an explicit
        # --watch-conditions flag always wins over this.
        default_watch_conditions = load_default_watch_conditions()
        if default_watch_conditions is not None:
            watch_conditions_path = str(default_watch_conditions)
            print(f"No --watch-conditions given -- using the default from {config_path()}: "
                  f"{watch_conditions_path}\n", file=sys.stderr)

    rules = DEFAULT_RULES
    # A scoped target on a Main or a Matrix (`MAIN PA`) needs names the
    # poll never reads: read once, into the first state, and never again.
    start_names: list[str] = []
    if watch_conditions_path:
        from atoo.watch_conditions import build_watch_rules, start_name_addresses

        conditions = _load_watch_conditions_file(watch_conditions_path)
        if conditions is None:
            return 1
        rules = DEFAULT_RULES + build_watch_rules(conditions)
        start_names = start_name_addresses(conditions)
    # The bundle's plan: FX busses' effects as planned (CV015), channels cut off from every planned route (CV016),
    # mutes the plan does not have (CV017), sends and Main routes
    # against the plan (CV006, CV007), a Matrix send or Main route it does not have, an INFO (CV018)
    # 48V and a bus's width against the plan (CV019, CV020), talkback that
    # misses a monitor mix the plan builds (CV021, CV022); and L002 quiet
    # on a fader the plan itself puts at the floor.
    if show is not None:
        from atoo.audit import with_plan_rules
        rules = with_plan_rules(rules, show.plan)
    from atoo.watch import plan_notes, virtual_soundcheck_note

    # W004/W005: the plan as Watch started with it, or that it has none.
    session_notes = plan_notes(show.plan if show is not None else None)
    # --virtual-soundcheck: the alternate inputs are on purpose (C004 and
    # C005 at INFO), and a note says so for as long as the watch runs.
    if args.virtual_soundcheck:
        from atoo.audit import virtual_soundcheck_rules

        rules = virtual_soundcheck_rules(rules)
        plan_notes_fn = session_notes
        session_notes = lambda: plan_notes_fn() + [virtual_soundcheck_note()]  # noqa: E731

    console = None
    stop_listening = None
    if args.state_sequence:
        paths = [p.strip() for p in args.state_sequence.split(",") if p.strip()]
        states = []
        for p in paths:
            state = _load_state_file(p)
            if state is None:
                return 1
            states.append(state)

        cycle = 0

        def state_provider():
            nonlocal cycle
            state = states[cycle % len(states)]
            cycle += 1
            return state

        max_iterations = args.count if args.count is not None else len(states)
        label = f"{len(states)} state file(s) in sequence"
    else:
        if args.console is None:
            return _no_console_address(offline="--state-sequence FILES")
        # Held open for the life of the watch, as the console is; line
        # buffering is what makes that safe to end with Ctrl-C.
        console = _open_console(args, raw_log=_open_read_raw_log(args))
        if console is None:
            return 1
        # The bundle's plan widens the output sockets read to
        # every group it patches, as `audit --plan` does.
        read_kwargs = _console_read_kwargs(args, _bundle_plan_dict(show))
        name_refresh = watch_name_refresh(args)

        def read_once(names):
            # A fresh ReadProgress per pass: the counts it reports are
            # about ONE read, and `watch` runs the same read over and
            # over. Without this a `watch` pass is as
            # silent as the `audit` read was, for as many minutes.
            progress = _read_progress(args, read_kwargs, names_known=names is not None)
            state = read_console_state(console, progress=progress, names=names,
                                       **read_kwargs)
            if progress is not None:
                progress.finish()
            return state

        # Names at Start and every `name_refresh` passes, not
        # every pass. The first pass always reads them, so the scoped
        # names below resolve against a full reading.
        from atoo.audit import console_read_plan
        from atoo.watch import refreshing_names

        state_provider = refreshing_names(
            read_once,
            console_read_plan(**{k: v for k, v in read_kwargs.items() if k != "bulk"}),
            name_refresh)

        if start_names:
            from atoo.watch_conditions import console_name_reader, read_names_at_start

            state_provider = read_names_at_start(state_provider, console_name_reader(console),
                                                 start_names)

        # The console's meters are listened to for clips, on
        # a thread of its own (L003); if that cannot be had the watch
        # says so at INFO and carries on.
        from atoo.metering import with_clip_detection

        state_provider, stop_listening = with_clip_detection(
            state_provider, args.console, record=getattr(args, "record_meters", None))

        max_iterations = args.count
        label = f"{args.console}:{args.port}"

    # The findings log, opened once the desk has identified
    # itself and before the first read, so a header exists even if the
    # first pass never finishes.
    findings_log = None
    if args.findings_log:
        from atoo import findings_log as findings_log_module

        try:
            findings_log = findings_log_module.FindingsLog.open(
                args.findings_log, findings_log_module.header_line(
                    install=install_info.describe().payload(),
                    console=args.console,
                    identity=getattr(args, "console_identity", None),
                    plan=(str(show.directory / bundle.PLAN) if show is not None else None),
                    conditions={"file": watch_conditions_path,
                                "rules": [r.id for r in rules if r not in DEFAULT_RULES]}
                    if watch_conditions_path else None,
                    started=findings_log_module._now()))
        except OSError as exc:
            print(f"--findings-log {args.findings_log}: {exc}", file=sys.stderr)
            if stop_listening is not None:
                stop_listening()
            if console is not None:
                console.close()
            return 1

    # flush= on every print in this command, not as a style: `watch` is a
    # long-running live monitor, and Python block-buffers stdout when it
    # is redirected to a file. Running `watch --console --count 8`
    # into a log on 2026-09-22 gave a ZERO-BYTE FILE for minutes, and it was
    # killed -- reasonably, since nothing else was on screen either.
    # Nothing was wrong: one live read is thousands of addresses, so
    # eight of them is minutes of correct, silent work. A monitor whose
    # output only appears at exit is not a monitor. The
    # read itself reports progress too, so the silence is over; this line
    # still earns its place by saying up front how long to expect.
    if args.console:
        print(_watch_estimate(read_kwargs, max_iterations, args.interval, name_refresh),
              flush=True)
    print(f"Watching {label} every {args.interval:g}s (Ctrl-C to stop) -- read-only, nothing here writes "
          f"to a console.\n", flush=True)

    # The coverage note is a fact about the STATE, and a
    # `WatchEvent` carries only findings -- a shape `webui.py` and the
    # Watch page both consume, so it is not widened for a status line.
    # Keeping the first state here costs nothing and changes nothing.
    _provider = state_provider
    first_state: list = []
    latest_state: list = []

    def state_provider():
        state = _provider()
        if not first_state:
            first_state.append(state)
        latest_state[:] = [state]
        return state

    last_findings = []
    try:
        for event in watch(state_provider, rules=rules, interval=args.interval,
                           max_iterations=max_iterations, session_notes=session_notes):
            last_findings = event.all_findings
            if findings_log is not None:
                findings_log.record(event, latest_state[0] if latest_state else None)
            # The coverage paragraph has been printed at the
            # baseline, but it arrived AFTER the findings it
            # qualifies and never again -- so a bare ERROR on pass 47 of
            # a live watch carries no caveat at all, which is how
            # R002/R005 reached an engineer on 2026-09-24 looking like
            # verdicts. `coverage_caveat` is the one-line form, printed
            # ahead of the baseline findings and again with any change
            # event, because that is where an engineer at the desk is
            # actually reading. FR-4.2: a monitor that cannot say "I
            # could not check this" is not reporting, it is guessing.
            caveat = coverage_caveat(latest_state[0])
            if event.iteration == 0:
                if caveat:
                    print(caveat + "\n", flush=True)
                print(f"[{event.at}] baseline -- {len(event.all_findings)} finding(s) already present:",
                      flush=True)
                print(render_findings(event.all_findings).rstrip("\n"), flush=True)
                # The full paragraph too, once: it names the rules in
                # words and says how to widen the read, which the one
                # line deliberately does not.
                print("\n" + render_coverage(
                    first_state[0], from_capture=bool(args.state_sequence)), flush=True)
            else:
                text = render_event(event)
                if text:
                    print(text, flush=True)
                    if caveat:
                        print("  " + caveat, flush=True)
                else:
                    # Say SOMETHING every pass. "Nothing changed" is the
                    # expected result of a watch cycle, and a monitor that
                    # prints nothing on the expected result is
                    # indistinguishable from one that has died.
                    print(f"[{event.at}] pass {event.iteration}: no change.", flush=True)
        stop_reason = "finished"
    except KeyboardInterrupt:
        print("\nStopped watching.")
        stop_reason = "Ctrl-C"
    except BaseException:
        # Not a clean stop: no footer, so the log says it was cut off.
        if findings_log is not None:
            findings_log.abandon()
            findings_log = None
        raise
    finally:
        if stop_listening is not None:
            stop_listening()
        if console is not None:
            console.close()
    if findings_log is not None:
        findings_log.close(stop_reason)

    return 1 if any(f.severity == Severity.ERROR for f in last_findings) else 0


def _plan_inputs_changed(plan: dict, show) -> "diagnostics.Diagnostic | None":
    """The WARNING for a bundle plan built before an edit to one of its
    inputs (`plan_freshness`), or None: no bundle, a plan that
    is current, or one too old to record what it was built from."""
    if show is None:
        return None
    assessment = plan_freshness.assess_bundle(plan, show)
    return plan_freshness.stale_diagnostic(
        assessment, f"{show.directory.name or show.directory}/{bundle.PLAN}")


def apply_cmd(args: argparse.Namespace) -> int:
    # Before anything else: this is the one command that writes, and
    # "which desk" is the question it must not get wrong.
    if args.console is None:
        return _no_console_address()
    try:
        show = _open_bundle(args)
        _fill_from_bundle(args, show, "plan", bundle.PLAN, required=True)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not args.plan:
        # The error argparse gave before --plan stopped being required.
        print("--plan is required (or --show DIR, to take plan.json from a show bundle)",
              file=sys.stderr)
        return 1
    _fill_from_bundle(args, show, "input", bundle.INPUT_LIST)
    _parse_socket_counts(args.clean_output_sockets)   # a bad value stops here, before the desk is touched

    # Imported here rather than at module scope so `atoo build` and
    # `--help` don't pay for (or depend on) the console layer at all.
    from atoo.apply import (CROSS_MODEL, sockets_missing_on_model)
    from atoo.apply import (apply_plan, box_sockets_missing, check_desk_model,
                                 plan_expansion_bay_use, plan_uses_aes50, read_aes50_devices,
                                 read_fitted_bays, unfitted_bays_the_plan_needs, unknown_boxes)
    from atoo.console import WingConsole

    try:
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
    except OSError as exc:
        print(f"couldn't read plan {args.plan!r}: {exc.strerror}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"plan {args.plan!r} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    # The gate. `build` tells you a plan will be refused in this state;
    # this is where that promise is kept. It runs before the console is
    # even contacted, because the point is to not write an impossible plan
    # to real hardware -- and `set_param` is never acknowledged, so a bad
    # write is only discovered on readback, after the damage.
    rows = presets = verdict = None
    if not args.skip_verify:
        if args.input:
            try:
                rows = load_input_list(args.input)
            except (OSError, InputListError) as exc:
                print(f"couldn't read input list {args.input!r}: {exc}", file=sys.stderr)
                return 1
        presets = _resolve_preset_library(args)
        layers = _plan_layers(plan, show, args.plan)
        verdict = verify_plan(plan, rows, presets=presets,
                              console_model=getattr(args, "console_model", None),
                              layers=layers)
        if verdict.findings:
            print(verdict.report(), file=sys.stderr)
        if verdict.errors:
            print(f"\nRefusing to apply {args.plan!r}. Fix the plan, or pass --skip-verify "
                  "if you have a reason to write it anyway.", file=sys.stderr)
            return 2
        if rows is None:
            print("(pass --input to also check that every input became a channel and that "
                  "phantom power is safe for the mics in use)", file=sys.stderr)

    # A plan older than its inputs is announced, never refused
    # -- applying the plan as built is a choice an engineer may make on
    # purpose. Only for a bundle, whose three inputs are known.
    stale_inputs = _plan_inputs_changed(plan, show)
    if stale_inputs is not None:
        _emit_diagnostics([stale_inputs], heading="The plan is older than its inputs:")

    journal_path = args.journal
    # In a bundle the journal belongs in the bundle, and
    # only in its `journals/` stack -- named for the desk
    # it reaches, so the path is chosen once the desk has answered, below.
    stack_journal = journal_path is None and args.confirm and show is not None
    if journal_path is None and args.confirm and not stack_journal:
        # FR-X.3 -- a real apply is always journalled, whether or not the
        # caller thought to ask for one. A dry run has nothing to reverse.
        journal_path = str(Path(args.plan).with_suffix("").with_suffix(".apply-journal.json"))

    raw_log = open(args.raw_log, "a", encoding="utf-8") if args.raw_log else None
    try:
        with WingConsole(args.console, port=args.port, timeout=args.timeout, raw_log=raw_log) as console:
            identity = console.identity()
            if identity is None:
                print(f"no reply from {args.console}:{args.port} -- is the console reachable, and is "
                      f"its OSC remote enabled?", file=sys.stderr)
                return 1
            if identity.is_socket_error:
                # Distinct from a plain timeout (no reply at
                # all) -- this is the OS itself refusing the packet or
                # declining to route it, which surfaces useful detail
                # (host unreachable vs connection refused vs network
                # unreachable) that a generic "is it reachable" message
                # would throw away.
                print(f"couldn't reach {args.console}:{args.port} -- {identity.args[0]}", file=sys.stderr)
                return 1
            print(f"Console: {', '.join(identity.args)}" if identity.args else f"Console at {args.console}")
            args.console_identity = list(identity.args)

            # Verification above ran against the model the plan
            # states; this is the first moment we can hear the model from
            # the desk itself. Graded by the rule that a judgement
            # call is not an impossible patch (`apply.check_desk_model`):
            # a different model whose panel has every socket the plan
            # patches is applied, with an INFO and the verify re-run
            # against the desk; a socket the desk does not have is refused;
            # a desk whose model we cannot resolve is announced at WARNING.
            # Deliberately NOT gated on --skip-verify: that flag says "this
            # plan has findings, write it anyway", which is a judgement
            # about the plan. This is about the hardware, and
            # --console-model is still the explicit way to say which desk
            # the plan is to be checked for.
            intended = resolve_console_model(plan, getattr(args, "console_model", None))
            model_check = check_desk_model(plan, intended, identity.args, args.console,
                                           skip_verify=args.skip_verify)
            if model_check.refuses:
                print(f"\nERROR: {model_check.message}", file=sys.stderr)
                return 2
            if model_check.severity == "info":
                print(f"\nINFO: {model_check.message}", file=sys.stderr)
            elif model_check.severity == "warning":
                print(f"\nWARNING: {model_check.message}", file=sys.stderr)
            # --skip-verify skips the plan's FINDINGS, never the hardware.
            # Across models the check above already walked every socket;
            # on the same model (or an unmeasured one) nothing did once
            # verify was skipped, so a plan patching a socket this desk
            # does not have would have been written. That is the one case
            # kept as an error, and `amend` refuses it whatever
            # --skip-verify says -- apply now matches.
            if args.skip_verify and model_check.outcome != CROSS_MODEL:
                against = model_check.desk_model or intended
                missing = (sockets_missing_on_model(plan, against)
                           if against in facts.CONSOLE_MODELS else [])
                if missing:
                    label = facts.CONSOLE_MODELS[against]["label"]
                    lines = "\n".join(f"  - {m}" for m in missing)
                    print(f"\nERROR: {len(missing)} socket(s) this plan patches do not exist "
                          f"on the {label}:\n{lines}\nRefusing to apply {args.plan!r} to "
                          f"{args.console}: --skip-verify skips the plan's findings, not the "
                          "hardware. Repatch to sockets this desk has.", file=sys.stderr)
                    return 2
            if model_check.verify_against and not args.skip_verify:
                desk_label = facts.CONSOLE_MODELS[model_check.verify_against]["label"]
                desk_verdict = verify_plan(plan, rows, presets=presets,
                                           console_model=model_check.verify_against,
                                           layers=layers)
                if desk_verdict.errors:
                    print(f"\nAgainst the {desk_label}:", file=sys.stderr)
                    print(desk_verdict.report(), file=sys.stderr)
                    print(f"\nRefusing to apply {args.plan!r} to {args.console}: it does not "
                          f"verify against the {desk_label}. Fix the plan, or pass "
                          "--skip-verify if you have a reason to write it anyway.",
                          file=sys.stderr)
                    return 2
                # Only what the first pass did not already print: most of
                # a verdict does not depend on the model at all.
                seen = {(f.code, f.where, f.message) for f in verdict.findings}
                fresh = [f for f in desk_verdict.findings
                         if (f.code, f.where, f.message) not in seen]
                if fresh:
                    print(f"Against the {desk_label}, verify also says:", file=sys.stderr)
                    for f in fresh:
                        print(f"  {f}", file=sys.stderr)

            # The second check, which can only be made once
            # a desk is on the line. `CRD` and `MOD` are BAYS, not sockets:
            # the firmware answers /io/in/{CRD,MOD}/1..64 whether or not
            # there is a card or a module in the slot, and -- measured on
            # hardware 2026-09-21, console_facts.UNFITTED_BAY_PATCH_IS_ACCEPTED
            # -- the desk ACCEPTS a patch to an empty bay, reads it back
            # unchanged, and shows it on the surface. Nothing downstream
            # catches it: apply's own readback agrees, the journal says
            # `match`, `audit` sees a patched channel. The channel is
            # silent and the proof says it is fine, which is the one
            # outcome this whole tool exists to prevent.
            #
            # A stop rather than a warning, for the same reason as the model cross-check:
            # a plan whose
            # inputs arrive on hardware that is not in the console was
            # never checked against this console, and writing it produces
            # a desk that looks right. Unlike the model cross-check there is no override
            # flag, because there is nothing to override -- the
            # `--console-model` states which of two opinions about the
            # desk is correct, whereas this is the desk's own read-only
            # inventory of itself. Also unlike that, this check cannot
            # fire on an ambiguous reading: only a literal `NONE` counts,
            # so a card whose name we do not know, or a bay that did not
            # answer, carries on (see `facts.bay_is_empty`).
            # The two GETs are skipped entirely for a plan that uses no
            # bay, which is most plans: a leaf an older firmware does not
            # implement costs a full timeout-and-retry, and no plan should
            # pay that for a question it never asked.
            # plan.json is written only by a build,
            # so the changes and amends standing on this desk are NOT in it,
            # and a full apply writes over them. Announced, never refused.
            if show is not None:
                from atoo import journal_stack
                replaced = journal_stack.replaced_changes_diagnostic(
                    show.directory, _desk_of(args))
                if replaced is not None:
                    _emit_diagnostics([replaced])

            bay_use = plan_expansion_bay_use(plan)
            empty = unfitted_bays_the_plan_needs(
                bay_use, read_fitted_bays(console, bay_use)) if bay_use else {}
            if empty:
                print("", file=sys.stderr)
                for group, places in sorted(empty.items()):
                    label = facts.GROUP_ALIASES.get(group, group)
                    print(f"{args.console} reports NOTHING in the {group} bay ({label}), and this "
                          f"plan uses it {len(places)} time(s):", file=sys.stderr)
                    for place in places:
                        print(f"  - {place}", file=sys.stderr)
                print("\nThe console would accept these patches and read them back unchanged -- "
                      "it does not refuse a patch to an empty bay -- so nothing after this point "
                      "would tell you the channels are silent. Fit the card or module, or repatch "
                      "these to a group this desk has.", file=sys.stderr)
                return 2

            # A socket past the end of a stage box is patched to nothing: the
            # desk lists 48 on every AES50 port whatever is on it. Asked of
            # the desk, here, as the bays are -- only when the plan uses a port.
            devices = read_aes50_devices(console) if plan_uses_aes50(plan) else None
            beyond = box_sockets_missing(plan, devices)
            if beyond:
                print("", file=sys.stderr)
                print(f"This plan patches {len(beyond)} socket(s) that do not exist on the "
                      f"stage box {args.console} reports:", file=sys.stderr)
                for row in beyond:
                    print(f"  - {row['line']}", file=sys.stderr)
                print("\nThe console would accept these patches and read them back unchanged, "
                      "so nothing after this point would tell you those channels are silent. "
                      "Nothing was written. Repatch them to sockets the box has.",
                      file=sys.stderr)
                return 2
            for port, device in unknown_boxes(devices).items():
                print(f"WARNING: AES50-{port} reports a {device!r}, and Atoo has no size "
                      f"recorded for it -- the sockets patched on {port} were not checked "
                      "against the box.", file=sys.stderr)

            if stack_journal:
                journal_path = _stack_journal_path(show, "apply", args)
            result = apply_plan(
                plan, console, dry_run=not args.confirm, journal_path=journal_path,
                clean_output_sockets=_parse_socket_counts(args.clean_output_sockets),
                desk=_desk_of(args),
                model_check=model_check.to_journal() if model_check.message else None,
                # The whole show: every strip the plan does not build is
                # unpatched, and talkback's assign follows the plan
                # (2026-10-02). `amend` and `patch` never pass this.
                full_apply=True,
                # Reset to the DESK's model's initialized
                # capture first -- the desk being written to, not the
                # plan's model, which a cross-model apply differs from.
                initialize=not args.no_init,
                init_model=model_check.desk_model,
                init_token=model_check.desk_token,
                phases=_phases(args),
            )
    finally:
        if raw_log is not None:
            raw_log.close()

    print(result.summary())
    # One line per distinct warning, naming the strips it covers
    # (FR-X.15c); the journal keeps every one.
    _print_result_warnings(result)

    if journal_path and not result.dry_run:
        # This goes BEFORE the abort check on purpose: a run that
        # died partway is journalled for what it got through, and
        # `undo.py`'s docstring is explicit that such a journal "is the
        # most important one to be able to reverse -- it is the one
        # nobody planned for". A stack that recorded only clean runs
        # would be missing exactly those.
        if result.aborted:
            print(f"Journal: {journal_path}")
        # The plan this run left on the desk, so the next `amend --show` on
        # THIS desk compares against it rather than plan.json -- which is
        # the bundle's latest show, and may be another desk's.
        from atoo import journal_stack
        _record_on_stack(show, "apply", journal_path, desk=_desk_of(args), extra={
            journal_stack.DESK_PLAN_BLOCK: journal_stack.desk_plan_block(
                plan, "the applied plan")})

    if result.aborted:
        # A fatal connection loss, not an ordinary dry-run/
        # mismatch outcome -- exits non-zero either way, dry run included,
        # since "nothing was written, this was a preview" would be a
        # misleading thing to print when the real reason nothing happened
        # is that the console dropped mid-run, not that this was a preview.
        return 1

    if result.dry_run:
        print("\nNothing was written -- this was a preview. Re-run with --confirm to apply.")
        return 0

    if journal_path:
        print(f"Journal: {journal_path}")
    if result.mismatches:
        # Not a warning: a mismatch means the console did not end up in the
        # state the plan called for, which is precisely what O3 exists to
        # catch. A non-zero exit makes that impossible to miss in a script.
        #
        # Specifically 2, not 1. The project's convention --
        # stated in `docs/user/quickstart.md`,
        # and followed by `build`, `verify` and `compare` -- is `0` clean,
        # `1` bad usage or an unreadable file, `2` the command ran and
        # found problems. A readback mismatch is the headline "ran and
        # found problems" of this whole tool, and returning 1 for it made
        # it indistinguishable in `case $?` from "I could not read the
        # plan" or "the desk never answered". Those call for different
        # responses at a venue: one is a re-run, the other is a network
        # problem. Every other non-zero exit from this function is a 1
        # for exactly that transport/usage class, or the 2 the refusal
        # gate and the console-model mismatch already return.
        print(f"\n{len(result.mismatches)} parameter(s) did NOT land:", file=sys.stderr)
        for m in result.mismatches:
            print(f"  - {m.address}: wanted {m.intended_value!r}, console reports {m.readback_value!r}",
                  file=sys.stderr)
        return 2
    return 0


def _partial_path(path: Path) -> Path:
    """Where a failed model call's partial reply is saved, beside the file
    it was meant to become: `plan.json` -> `plan.partial.json`, so it still sorts beside
    it and opens in a JSON viewer.
    It is often NOT valid JSON -- it is a reply cut off partway."""
    return path.with_name(f"{path.stem}.partial{path.suffix}")


def _stack_journal_path(show, kind: str, args: argparse.Namespace) -> str:
    """Where a confirmed run in a bundle writes its journal: a new entry in
    the bundle's `journals/`, named for the desk on the line (no top-level `<kind>-journal.json` copy any more). Asked once the desk
    has answered, since the entry's name carries its serial."""
    from atoo import journal_stack

    return str(journal_stack.new_entry_path(show.directory, kind, _desk_of(args)))


def _record_on_stack(show, kind: str, journal_path: str,
                     undo_of: str | None = None, extra: dict | None = None,
                     desk: dict | None = None):
    """Put a confirmed run's journal on the bundle's stack.

    Called after the write, never before: the desk has already been
    written to by the time we get here, so a stack that cannot be
    updated is a warning and never an exit code. The journal itself is
    already on disk -- inside `journals/` for a bundle run,
    where this only indexes it, or at the `--journal` path the operator
    named -- and that file is what `atoo undo <path>` reads.

    Returns the entry, or None when there is no bundle to record into
    (`--plan foo.json` with no `--show`: the stack is per bundle, and
    there is no bundle).

    `desk` is the console the run wrote to (`_desk_of`), recorded so undo
    walks back that desk's history and no other when one bundle is applied
    to two desks.
    """
    if show is None or not journal_path:
        return None
    from atoo import journal_stack

    try:
        entry = journal_stack.record(show.directory, kind, journal_path, undo_of=undo_of,
                                     extra=extra, desk=desk)
    except (journal_stack.JournalStackError, OSError) as exc:
        print(f"  (could not add this run to {show.journals}: {exc})", file=sys.stderr)
        return None
    if Path(entry.path) != Path(journal_path):
        print(f"  on the bundle's journal stack as {bundle.JOURNALS}/{entry.id}")
    _say_pruned(show, entry)
    return entry


def _say_pruned(show, entry) -> None:
    """INFO when recording `entry` pruned writes that still stand on a desk
    (`journal_stack.Entry.pruned_now`): `journals/` keeps the newest five,
    so undo can no longer reach them. Said once, when it happens -- the
    refusal at the floor (`journal_stack.undo_floor`) says it again if
    anyone tries."""
    from atoo import journal_stack

    lost = list(getattr(entry, "pruned_now", ()) or ())
    if not lost:
        return
    names = "; ".join(f"{r.get('id')} ({r.get('kind')})" for r in lost)
    print(f"  INFO {show.journals} keeps the newest {journal_stack.keep_limit()} entries: "
          f"{len(lost)} older write(s) still on the desk were pruned ({names}). Undo now "
          "reaches back no further than the oldest entry kept; the pruned writes stay on "
          "the desk, and a full apply of the plan replaces them.")


def _record_change_on_stack(show, kind: str, journal_path, plan_left: dict, left_by: str,
                            desk: dict | None = None, change: dict | None = None):
    """Record a confirmed patch or amend on the bundle's journal stack, with
    the plan it left on its desk -- and never touch plan.json.

    **plan.json is written only by a build**: it is not
    modified unless the input list, the conventions file or the
    instructions file, the inputs to plan.json, have changed.
    What is on the desk is recorded by the desk's own entry
    (`journal_stack.DESK_PLAN_BLOCK`), which is what the next patch or amend
    of THIS desk compares against (`_desk_applied_plan`) -- so a second
    change from the same text, or a second amend from the same rebuild,
    still finds nothing to add, without plan.json having to change.

    `plan_left` is the effective plan for a run that completed (with or
    without mismatches: it is what the run meant to put there), and the
    plan it started from for one that aborted partway -- the reasoning,
    per desk: that at least describes everything that was there before.
    `change` is a patch's `{"number", "name", "text"}`
    (`patch.change_block`); its number is taken now, at record time, so two
    changes previewed side by side are still numbered in the order they
    were written."""
    from atoo import journal_stack

    extra = {journal_stack.DESK_PLAN_BLOCK: journal_stack.desk_plan_block(plan_left, left_by)}
    if change is not None:
        if show is not None:
            change = {**change, "number": journal_stack.next_change_number(show.directory)}
        extra[journal_stack.CHANGE_BLOCK] = change
        # The journal file itself carries the change too, whether or not
        # there is a stack to record it on (`--plan FILE` with no bundle).
        try:
            payload = json.loads(Path(journal_path).read_text(encoding="utf-8"))
            payload[journal_stack.CHANGE_BLOCK] = change
            Path(journal_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass
    entry = _record_on_stack(show, kind, journal_path, desk=desk, extra=extra)
    if change is not None and entry is not None:
        print(f"  recorded as {journal_stack.change_label(change)}")
    return entry


def _say_plan_json_untouched(show, plan_path, *, modified: list | None = None) -> None:
    """The one line every confirmed patch and amend ends its journal part
    with: plan.json is the last build's, and stays so."""
    if show is None:
        print(f"{plan_path} was not changed -- only `atoo build` writes a plan. The "
              "journal records what this run wrote.")
        return
    print(f"{bundle.PLAN} is unchanged -- only a build writes it. What is on this desk now is "
          f"recorded in its journal entry, which the next patch or amend of this desk reads; "
          f"a full `atoo apply --show {show.directory}` would replace it, and warns "
          "before it does.")
    if modified:
        print(f"  INFO not written, because each would change something already running: "
              f"{', '.join(modified)}.")


def _undo_plan_swap(stack_bundle, source_entry, block, *, only: bool):
    """What undoing `source_entry` does to the bundle's plan.json.

    `block` is the entry's `bundle_plan` (`journal_stack.saved_plan`), or
    None. Returns `(bytes to write, bundle_plan block for the undo's own
    entry)` when the plan goes back, or None -- having said why -- when it
    does not.

    The rule: put the replaced plan
    back **only while plan.json is still the file that run wrote**, judged
    by the sha256 recorded when it wrote it. An operator who has rebuilt
    plan.json since has made a decision this command cannot see; their
    build is left alone and they are told so at WARNING. The returned block
    is the mirror image, so undoing THIS undo (the redo) re-installs the
    amended plan under the same rule.

    **Only an entry recorded before plan.json became build-only carries a block.** Since
    then plan.json is written only by a build, so a patch or amend entry
    has nothing to put back, and its undo leaves plan.json alone -- the
    desk's own journal is what records what is on it. The restore stays for
    the old entries that did replace it: they still have to undo correctly.
    """
    from atoo import journal_stack

    if source_entry is None:
        return None
    plan = Path(stack_bundle) / bundle.PLAN
    if block is None:
        if source_entry.kind in journal_stack.CHANGE_KINDS:
            print(f"  {bundle.PLAN} left as it is: only a build writes it, and that "
                  f"{source_entry.kind} did not.")
        return None
    if only:
        print(f"WARNING: {plan} left as it is -- --only reverses part of that run, so the "
              "rest of it is still on the desk and the plan it wrote still describes it.",
              file=sys.stderr)
        return None
    try:
        current = plan.read_bytes()
    except OSError:
        current = None
    if current is None or journal_stack.plan_sha256(current) != block["written_sha256"]:
        print(f"WARNING: {plan} was NOT put back -- it has been "
              f"{'removed' if current is None else 'rebuilt or edited'} since that run wrote "
              f"it, and that is the operator's file now. The plan it replaced is kept in "
              f"{source_entry.path} under \"{journal_stack.PLAN_BLOCK}\".", file=sys.stderr)
        return None
    restored = journal_stack.saved_plan_bytes(block)
    return restored, journal_stack.plan_block(current, restored)


def _stack_bundle_for(journal_file: str, show):
    """Which bundle's stack a journal path belongs to, or None.

    `--show` wins when it was given. Otherwise the journal's parent is the
    bundle when the journal is an entry (`my-show/journals/<id>.json`), or
    its own directory for a file beside the stack (a `--journal PATH` the
    operator put in the bundle).
    Inferred rather than asked for because `atoo undo <path>` is a
    documented invocation and the one the staleness check most needs to
    fire on -- a guard that only works when you remember to pass `--show`
    is not a guard.

    A directory with no `journals/` in it is not a stack: a journal
    sitting anywhere else (`<plan>.apply-journal.json` beside a plan, or
    `docs/user/demo/undo-demo/`) resolves to None, and is undone on its own.
    """
    if show is not None:
        return show.directory
    path = Path(journal_file)
    candidate = path.parent.parent if path.parent.name == bundle.JOURNALS else path.parent
    return candidate if (candidate / bundle.JOURNALS).is_dir() else None


def _refuse_out_of_order(stack_dir, journal_file: str, entry, later,
                         undone_by: str | None = None) -> None:
    """Print the refusal for the hazard: a journal that is no
    longer the top of the stack.

    It makes no sense to undo an apply out from under a subsequent
    amend. Refusing is the safer reading and is what
    this does by default -- the per-address guard inside `undo` cannot
    see a later journal at all, so every address would pass it and the
    show would come off the desk under the amend.
    """
    from atoo import journal_stack

    if entry is None:
        print(f"{journal_file} is not on the journal stack in {stack_dir} -- it was "
              "written before this bundle had one, or copied in from elsewhere -- so "
              "everything on that stack is newer than it.", file=sys.stderr)
    else:
        print(f"{journal_file} is not the newest entry in {stack_dir}.", file=sys.stderr)
    if undone_by is not None:
        print(f"It has already been reversed, by {bundle.JOURNALS}/{undone_by} -- there "
              "is nothing of it left on the desk to put back. Reversing THAT file is the "
              "redo. Pass --out-of-order to run this one anyway.", file=sys.stderr)
    elif later:
        print(f"{len(later)} later write(s) are still on the desk:", file=sys.stderr)
        for above in later:
            print(f"  {journal_stack.describe(above)}", file=sys.stderr)
        print("\nReversing this one would put the console back to before them while they "
              "stay on it -- undo's own guard is per address and cannot see a later run, "
              "so every address here would pass it.", file=sys.stderr)
        print("Undo them first (`atoo undo --show DIR` reverses the newest, one step "
              "at a time), or pass --out-of-order if you have a reason to reach underneath "
              "them.", file=sys.stderr)
    else:
        print("A later write is standing on top of it. Pass --out-of-order to run it "
              "anyway.", file=sys.stderr)


class _UndoLink:
    """`undo`'s one connection -- a desk, or a `--state` file -- opened once,
    on first need.

    On first need rather than up front because two of undo's answers are
    files-only and should arrive before anything waits on a desk: "there is
    nothing to undo", and the stack refusal for a named journal that some
    later write on its own desk still stands on. But "which entry is the
    newest" is now asked of ONE desk (per-desk history),
    so `undo --show` with no journal named has to hear the desk say who it
    is before it can pick -- and a named journal has to be checked against
    the desk on the line before anything is written to it.

    `desk` is the connected console as the journal stack records one
    (`_desk_of`), or None: no console (an offline `--state` preview), which
    the stack reads as "every desk"."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.console = None
        self.state = None
        self.desk = None
        self.raw_log = None
        self.opened = False

    def open(self) -> int | None:
        """None once connected (or loaded); the exit code when not."""
        if self.opened:
            return None
        args = self.args
        if args.state:
            if args.confirm:
                print("--state is a preview against a saved capture; it cannot arm a write. "
                      "Pass --console with --confirm to actually reverse anything.",
                      file=sys.stderr)
                return 1
            loaded = _load_state_file(args.state)
            if loaded is None:
                return 1
            self.state = loaded.values
            self.opened = True
            return None
        if args.console is None:
            return _no_console_address(offline="--state FILE")
        self.console = _open_console(args)
        if self.console is None:
            return 1
        self.desk = _desk_of(args)
        if args.raw_log:
            self.raw_log = open(args.raw_log, "a", encoding="utf-8")
            self.console.raw_log = self.raw_log
        self.opened = True
        return None

    def close(self) -> None:
        if self.console is not None:
            self.console.close()
        if self.raw_log is not None:
            self.raw_log.close()


def _undo_staleness(stack_bundle, source_entry, undone_by, desk):
    """`(stale, later)` for reversing `source_entry` on `desk` -- the
    question, asked of one desk.

    `later` is what a reversal would reach underneath: the live entries
    newer than it ON THAT DESK (`journal_stack.above`/`positions` with a
    desk). An entry on another console is not underneath anything on this
    one. `desk` None asks it of the whole stack."""
    from atoo import journal_stack

    if source_entry is None:
        # Not on the stack at all (a journal from before the stack, or one
        # copied in): everything standing on this desk is newer than it.
        later = journal_stack.positions(stack_bundle, desk)
        return bool(later), later
    if source_entry.kind == "undo":
        # An UNDO entry is never a stack position, so "is anything above
        # it" is the wrong question: reversing it is the documented redo.
        # The only thing that makes it stale is having been reversed.
        return undone_by is not None, []
    if undone_by is not None:
        return True, []
    later = journal_stack.above(stack_bundle, source_entry, desk)
    return bool(later), later


def _refuse_other_desk(journal_file: str, source_desk: dict, desk: dict) -> None:
    """The refusal for a journal recorded on a different desk than the one
    on the line: undo can only apply against the
    correct desk and the correct journal. No override: there is no legitimate
    reason to reverse desk A's journal onto desk B. Per address, undo cannot
    tell the two apart (a plan applied to both holds the same value at every
    address on both), so every address would pass the guard and the wrong
    console would be reversed."""
    from atoo import journal_stack

    print(f"{journal_file} was written to {journal_stack.describe_desk(source_desk)}, but "
          f"the console on the line is {journal_stack.describe_desk(desk)}.",
          file=sys.stderr)
    print("Undo only reverses a journal on the desk it was written to (matched by the "
          "serial the desk states; by its address only when it states none). Its guard is "
          "per address, and a plan applied to both desks holds the same value at every "
          "address on both -- so every address would pass it and THIS desk would be "
          "reversed. Connect to the desk it was written to: `atoo undo --show DIR` "
          "reverses the newest write on whichever desk it reaches.", file=sys.stderr)


def _say_desk_moved(recorded: dict, desk: dict) -> None:
    """The INFO for the same desk (by serial) at a new address: the IP changing
    going from a home network to a gig network is the same desk, and
    allowed. Said, because it was inferred."""
    print(f"  INFO this journal was written to serial {recorded.get('serial')} at "
          f"{recorded.get('address')}; the desk on the line states the same serial at "
          f"{desk.get('address')}. The serial is the desk, so it is the same one -- its "
          "address has changed since.")


def _journal_desk(journal: dict) -> dict | None:
    """The desk a journal file itself says it was written to -- its own
    `stack_entry.desk` -- for a journal the stack cannot place. None when
    it names none (written before desks were recorded, or never on a stack)."""
    block = journal.get("stack_entry") if isinstance(journal, dict) else None
    desk = block.get("desk") if isinstance(block, dict) else None
    return desk if isinstance(desk, dict) and desk else None


def _print_result_warnings(result) -> None:
    """The warnings and notes under a run's summary line, which promises
    them ("N warning(s), listed below"). They go to stderr, so stdout is
    flushed first: a run piped through `tee` or `2>&1` holds stdout in a
    block buffer, and the lines would otherwise reach the reader long before
    the summary they belong under."""
    sys.stdout.flush()
    for w in finding_groups.group_lines(result.warnings):
        print(f"  - {w}", file=sys.stderr)
    sys.stderr.flush()


def undo_cmd(args: argparse.Namespace) -> int:
    """`atoo undo` -- reverse an apply from its journal.

    D6 and O2 both promise reversibility; `atoo/undo.py` holds the
    reasoning and the guard. This function is the screen around it: read
    the journal, preview, and -- only with `--confirm` -- arm.

    There is no second arming control (OPTIONS-H): `--confirm` is the
    one, exactly as on `apply`.

    It has a second form: with `--show DIR` and no journal
    named, it pops the **top of that bundle's stack** -- the newest write
    still standing on the desk, whatever kind it was. An explicit path
    still works exactly as it did, and is now checked against the stack:
    a journal that is no longer the top is refused, because undo's guard
    is per address and cannot see the later run it would be reaching
    underneath.

    **Per desk** (one plan, applied to a primary and a
    backup). Every entry records the desk it wrote to, so "the top" is the
    newest write standing **on the desk this command reaches**: `--show`
    with no journal pops that desk's newest and leaves the other desk's
    history alone; a named journal is stale only if a later write on THIS
    desk stands on it; and a journal recorded on a different desk is
    refused, naming both, with no override: undo can only apply against the
    correct desk and journal. The desk is its
    serial, so the same serial at a new address is the same desk (INFO),
    and a different serial at the same address is not. An entry recorded
    before entries named their desk counts as this desk's, said at INFO.
    """
    from atoo import journal_stack
    from atoo import undo as undo_engine

    show = None
    if getattr(args, "show", None):
        try:
            show = bundle.load(args.show)
        except bundle.BundleError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    journal_file = args.journal_file
    if journal_file is None and show is None:
        print("undo needs a journal to reverse: either `--show DIR` (reverses the "
              "newest write recorded in that bundle) or the path to a journal file.",
              file=sys.stderr)
        return 1

    link = _UndoLink(args)
    try:
        return _undo_run(args, show, journal_file, link, journal_stack, undo_engine)
    finally:
        link.close()


def _undo_run(args, show, journal_file, link, journal_stack, undo_engine) -> int:
    """`undo_cmd`'s body, with `link` owning the connection so that every
    return below closes it."""
    if journal_file is None:
        newest_anywhere = journal_stack.top(show.directory)
        recorded = journal_stack.entries(show.directory)
        if newest_anywhere is not None:
            # Which entry is "the newest" depends on which desk is on the
            # line, so the desk is asked before the pick.
            code = link.open()
            if code is not None:
                return code
            newest = journal_stack.top(show.directory, link.desk)
            standing = journal_stack.positions(show.directory)
            if newest is None:
                print(f"nothing to undo on this desk ({journal_stack.describe_desk(link.desk)}): "
                      f"every write still standing in {show.journals} was recorded on a "
                      "different desk --", file=sys.stderr)
                for entry in standing:
                    print(f"  {journal_stack.describe(entry)}", file=sys.stderr)
                print("Connect to that desk to undo it there.", file=sys.stderr)
                return 1
            floor = journal_stack.undo_floor(show.directory, link.desk)
            if floor is not None:
                print(f"nothing more to undo on this desk: {show.journals} keeps only the "
                      f"newest {journal_stack.keep_limit()} entries. This desk's last write "
                      "still journalled is", file=sys.stderr)
                print(f"  {journal_stack.describe(newest)}", file=sys.stderr)
                print(f"and the write beneath it was pruned ({floor.id}, {floor.kind}). "
                      "Undoing it would leave the desk holding a write no journal records, so "
                      "amend and patch would compare against the wrong plan. Nothing was "
                      "written. To change the desk from here, apply a plan (a full apply "
                      "replaces everything) or patch it.", file=sys.stderr)
                return 1
            journal_file = str(newest.path)
            print(f"Reversing the newest entry in {show.journals}"
                  + (" on this desk:" if link.desk is not None else ":"))
            print(f"  {journal_stack.describe(newest)}")
            skipped = [e for e in standing
                       if e.id > newest.id and not journal_stack.on_desk(e, link.desk)]
            if skipped:
                print(f"  INFO {len(skipped)} newer write(s) on this stack were recorded on "
                      "a different desk, and are left alone:")
                for entry in skipped:
                    print(f"    {journal_stack.describe(entry)}")
            if link.desk is None and any(e.desk for e in standing):
                print("  INFO no desk was contacted (--state), so this is the newest write "
                      "on the whole stack. A confirmed undo reverses the newest write on the "
                      "desk it reaches, which may be a different entry.")
        elif recorded:
            print(f"nothing to undo: every write recorded in {show.journals} has already "
                  f"been reversed ({len(recorded)} entries, all accounted for). Reversing "
                  "one of the undo journals in there is the redo.", file=sys.stderr)
            return 1
        else:
            print(f"nothing to undo: {show.directory} has recorded no writes "
                  f"(nothing in {bundle.JOURNALS}/).", file=sys.stderr)
            return 1

    try:
        journal = undo_engine.load_journal(journal_file)
        only = undo_engine.parse_only(args.only) if args.only else None
    except undo_engine.UndoError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # THE OUT-OF-ORDER GUARD, and the reason the stack exists -- now asked of the
    # desk being written (per-desk history).
    stack_bundle = _stack_bundle_for(journal_file, show)
    source_entry = None
    if stack_bundle is not None:
        # Not on this bundle's stack at all is `find` -> None: a journal
        # copied in from elsewhere, or written before the stack began.
        # Without handling that, `undo <that file>` reversed the show out
        # from under every write recorded on the stack since.
        source_entry = journal_stack.find(stack_bundle, journal_file)
        undone_by = (journal_stack.reversed_by(stack_bundle, source_entry)
                     if source_entry is not None else None)
        gone = (journal_stack.pruned_target(stack_bundle, source_entry)
                if source_entry is not None else None)
        if gone is not None and undone_by is None:
            # The redo of an undo whose target was pruned: the writes it
            # would put back belong to a journal that is no longer on the
            # stack, so nothing would record that they are on the desk.
            print(f"{journal_file} reversed {gone}, whose journal has been pruned "
                  f"({bundle.JOURNALS}/ keeps only the newest "
                  f"{journal_stack.keep_limit()} entries). Redoing it would put writes on "
                  "the desk that no journal records, so amend, patch and undo would not know "
                  "they are there. Nothing was written -- apply or patch instead.",
                  file=sys.stderr)
            return 1

        # Phase 1, from files alone and BEFORE the console is opened: a
        # refusal that arrives after the desk has been contacted is one the
        # operator has already started waiting on. Asked of the desk the
        # journal was recorded on -- if the desk on the line turns out to
        # be another, the desk check below refuses anyway. For a journal
        # that names no desk, only entries that name none either are
        # certainly on the same desk as it; `{}` is a desk no recorded
        # desk matches, which asks exactly that.
        if not link.opened:
            probe = (source_entry.desk if source_entry is not None and source_entry.desk
                     else {})
            stale, later = _undo_staleness(stack_bundle, source_entry, undone_by, probe)
            if stale and not args.out_of_order:
                _refuse_out_of_order(journal_stack.stack_dir(stack_bundle), journal_file,
                                     source_entry, later, undone_by)
                return 1

        code = link.open()
        if code is not None:
            return code

        # Phase 2: the desk on the line.
        desk = link.desk
        if desk is not None:
            recorded_on = (source_entry.desk if source_entry is not None
                           else _journal_desk(journal))
            if recorded_on is None:
                print(f"  INFO {Path(journal_file).name} does not record which desk it was "
                      f"written to (it predates per-desk journals), so it is taken to be "
                      f"this desk's -- {journal_stack.describe_desk(desk)}. The single-desk "
                      "assumption was true when it was written.")
            elif not journal_stack.same_desk(recorded_on, desk):
                # Strict, and no override (undo can
                # only apply against the correct desk and journal).
                _refuse_other_desk(journal_file, recorded_on, desk)
                return 1
            elif journal_stack.desk_moved(recorded_on, desk):
                _say_desk_moved(recorded_on, desk)
        if (args.journal_file is not None and source_entry is not None
                and source_entry.kind != "undo" and undone_by is None):
            # The same floor `undo --show` stops at, for a journal named
            # by its path: the desk's last kept write, with a pruned one
            # beneath it.
            top_now = journal_stack.top(stack_bundle, desk)
            floor = journal_stack.undo_floor(stack_bundle, desk)
            if floor is not None and top_now is not None and top_now.id == source_entry.id:
                print(f"{journal_file} is this desk's last write still in "
                      f"{bundle.JOURNALS}/, and the one beneath it was pruned ({floor.id}; "
                      f"only the newest {journal_stack.keep_limit()} entries are kept). "
                      "Undoing it would leave the desk holding a write no journal records. "
                      "Nothing was written -- apply or patch instead.", file=sys.stderr)
                return 1
        stale, later = _undo_staleness(stack_bundle, source_entry, undone_by, desk)
        if stale:
            if not args.out_of_order:
                _refuse_out_of_order(journal_stack.stack_dir(stack_bundle), journal_file,
                                     source_entry, later, undone_by)
                return 1
            print(f"WARNING: {journal_file} is not the newest entry in "
                  f"{journal_stack.stack_dir(stack_bundle)}, and --out-of-order was given.",
                  file=sys.stderr)
            for higher in later:
                print(f"  still on the desk: {journal_stack.describe(higher)}",
                      file=sys.stderr)

    code = link.open()
    if code is not None:
        return code
    if stack_bundle is None and link.desk is not None:
        # A journal outside any bundle's stack -- a copy moved somewhere,
        # or `apply --plan FILE`'s own. If it says which desk it was written
        # to, the same rule holds: only that desk.
        recorded_on = _journal_desk(journal)
        if recorded_on is not None and not journal_stack.same_desk(recorded_on, link.desk):
            _refuse_other_desk(journal_file, recorded_on, link.desk)
            return 1
        if journal_stack.desk_moved(recorded_on, link.desk):
            _say_desk_moved(recorded_on, link.desk)
    console, state = link.console, link.state

    undo_journal = args.undo_journal
    if undo_journal is None and args.confirm:
        # Never the file being undone: overwriting the evidence with
        # the record of having reversed it destroys the only thing that
        # could reverse THIS run.
        source = Path(journal_file)
        if stack_bundle is not None and source.parent.name == bundle.JOURNALS:
            # Popping the stack: the undo IS a stack entry, so it is
            # written straight into `journals/` like every bundle run's
            # journal rather than as
            # `<some entry id>.undo.json` beside the entry it
            # reverses -- which would sit in the stack directory
            # under a name the ordering scheme does not recognise.
            undo_journal = str(journal_stack.new_entry_path(stack_bundle, "undo", link.desk))
        else:
            undo_journal = str(source.with_name(source.stem + ".undo.json"))
    try:
        result = undo_engine.undo_from_journal(
            journal, console, dry_run=not args.confirm, only=only,
            journal_path=undo_journal, state=state,
            source_journal=journal_file,
            # A --state preview reads a file, not a desk: nothing to report.
            phases=_phases(args) if state is None else None,
        )
    except undo_engine.UndoError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    link.close()
    link.console = link.raw_log = None
    if getattr(args, "result_json", None):
        # A file that cannot be written is said, and is not a reason to skip
        # recording a reversal that has already reached the desk.
        _write_review_json(args.result_json, result.to_dict(), flag="--result-json")

    if result.dry_run:
        # The preview is per-address by requirement: a refusal list that
        # only turns up after the write has happened is worthless. The
        # summary under it then drops its own per-address lines rather
        # than naming the same addresses twice.
        print(result.preview())
        print()
        print(result.summary(detail=False))
    else:
        # A confirmed run prints the counts and only the addresses that
        # need looking at, exactly as `apply` does -- 394 RESTORE lines
        # scrolling past is not a report.
        print(result.summary())
    # One line per distinct warning, naming the strips it covers
    # (FR-X.15c); the journal keeps every one.
    _print_result_warnings(result)

    # The bundle's plan.json follows the stack. Asked of the
    # entry, not the run, so an apply (which never replaces plan.json)
    # and an amend recorded before plan.json became build-only both answer
    # "nothing to do".
    saved_plan = (journal_stack.saved_plan(source_entry)
                  if stack_bundle is not None and source_entry is not None else None)
    if result.aborted:
        # Recorded on the way out, as `apply_cmd` records an aborted apply:
        # the partial journal is the only file saying which addresses this
        # run reached. It is recorded as an ABORTED undo, which the stack
        # keeps as evidence and does not pop (`journal_stack._live`) -- the
        # run it was reversing stays the top, so `undo --show` again
        # finishes the job.
        if stack_bundle is not None and undo_journal:
            recorded = _record_on_stack(
                bundle.Bundle(directory=Path(stack_bundle)), "undo", undo_journal,
                undo_of=source_entry.id if source_entry is not None else None,
                desk=link.desk)
            if recorded is not None:
                print(f"This partial undo is recorded on the stack ({recorded.id}); the "
                      "run it was reversing is still the top -- run `atoo undo --show` "
                      "again to finish it.", file=sys.stderr)
        if saved_plan is not None:
            print(f"WARNING: {bundle.PLAN} left as it is -- this undo aborted partway, and "
                  "the run it was reversing is still on the stack.", file=sys.stderr)
        return 1
    if result.dry_run and saved_plan is not None:
        print(f"\nOn --confirm, {bundle.PLAN} goes back to the plan that run replaced -- "
              "if it is still the file that run wrote.")
    if result.dry_run:
        if state is not None:
            print("\nReviewed offline from --state; no console was contacted. Re-run with "
                  "--console to preview against the desk, and --confirm to reverse.")
        else:
            print("\nNothing was written -- this was a preview. Re-run with --confirm to reverse.")
        return 0
    if undo_journal:
        print(f"Journal of this undo: {undo_journal}")
        print("  (undoing THAT file is the redo)")
        if stack_bundle is not None:
            # An undo is a set of writes and is journalled like any other
            # (FR-X.3), and its journal is the only file carrying the
            # addresses this run REFUSED to touch. It is recorded, and it
            # pops the entry it reversed rather than becoming a new
            # position -- see `atoo/journal_stack.py`.
            #
            # And the plan.json that entry replaced goes back,
            # under `_undo_plan_swap`'s rule. Recorded first, written
            # second, for the reason `_record_amend_and_replace_plan`
            # gives: the entry is what lets the NEXT undo (the redo) put
            # it back again. Refused, failed and unreversible addresses do
            # not stop it -- the entry is popped either way, the plan
            # follows the stack, and `verify` reports what did not revert.
            swap = _undo_plan_swap(stack_bundle, source_entry, saved_plan,
                                   only=only is not None)
            recorded = _record_on_stack(
                bundle.Bundle(directory=Path(stack_bundle)), "undo", undo_journal,
                undo_of=source_entry.id if source_entry is not None else None,
                extra={journal_stack.PLAN_BLOCK: swap[1]} if swap else None,
                desk=link.desk)
            if swap is not None:
                plan = Path(stack_bundle) / bundle.PLAN
                if recorded is None:
                    print(f"WARNING: {plan} was NOT put back -- this undo could not be "
                          "recorded on the journal stack, which is what a redo would "
                          "restore it from.", file=sys.stderr)
                else:
                    try:
                        plan.write_bytes(swap[0])
                        print(f"  {bundle.PLAN} put back to the plan that run replaced.")
                    except OSError as exc:
                        print(f"WARNING: couldn't write {plan}: {exc.strerror}.",
                              file=sys.stderr)
            remaining = journal_stack.top(stack_bundle, link.desk)
            if remaining is not None:
                print(f"  next on the stack{' for this desk' if link.desk else ''}: "
                      f"{journal_stack.describe(remaining)}")
    if result.unreversible and not result.dry_run:
        # Said at INFO, not a failure: the desk cannot be put back to a value
        # it never held, and nothing here was refused or failed. The first
        # write of a setting the earlier state did not carry has no earlier
        # value to restore.
        from atoo.undo import GONE_WITH_MODEL
        gone = [step for step in result.unreversible
                if (step.detail or "").startswith(GONE_WITH_MODEL)]
        first_time = [step for step in result.unreversible if step not in gone]
        if first_time:
            addresses = ", ".join(step.address for step in first_time[:6])
            more = len(first_time) - 6
            print(f"  INFO {len(first_time)} address(es) had no earlier value on the "
                  f"desk (the run wrote them for the first time), so there is nothing to put "
                  f"back: {addresses}{f', and {more} more' if more > 0 else ''}. "
                  "They stay as the run left them.")
        if gone:
            addresses = ", ".join(step.address for step in gone[:6])
            more = len(gone) - 6
            print(f"  INFO {len(gone)} address(es) existed only under the model the run set "
                  f"and are gone with it now that the model is back: "
                  f"{addresses}{f', and {more} more' if more > 0 else ''}.")
    if result.failed or result.refused:
        # Exit 2, the "it ran and found problems" code apply/build/verify
        # use: a reversal that did not land, or an address somebody else has
        # moved, is "the console is not back where it was", which is
        # precisely what this command exists to report. An address with no
        # earlier value is not that (see the INFO above), so it exits 0.
        return 2
    return 0


def _valid_strip_label(label: str) -> bool:
    """`ch:20` / `aux:3` -- the form `--allow-strip` takes, which is also
    the form the journal's `scope.strips` records."""
    bank, _, number = label.partition(":")
    return bank in ("ch", "aux") and number.isdigit() and int(number) >= 1


def _write_review_json(path: str, review: dict, flag: str = "--review-json") -> bool:
    """`amend --review-json FILE` and `undo --result-json FILE`: a run's
    review as data. False, having said why, when the file cannot be
    written."""
    try:
        Path(path).write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"{flag} {path}: {exc}", file=sys.stderr)
        return False
    return True


def _desk_applied_plan(show, desk: dict | None, bundle_plan: dict | None):
    """`(plan, infos)`: the plan on the connected desk, for `patch --show`
    and `amend --show`.

    The plan the desk's newest standing write left there
    (`journal_stack.desk_plan`, found by serial, so it survives the desk
    moving networks) -- after changing the primary, the backup is still
    compared against the plan its own apply put on it, so it gets the same
    channels rather than "Nothing to add". None when there is no such plan,
    and the caller keeps `plan.json` (`bundle_plan`) -- the bundle's last
    build -- or, for a patch with no plan.json either, starts from an empty
    base (`patch.empty_base`).

    `infos` always says which it was and why: a choice the
    engineer did not state is fine, one that does not announce itself is
    not."""
    from atoo import journal_stack

    here = bundle.PLAN
    if bundle_plan is None:
        fallback = (f"and there is no {here} in this bundle either, so the change starts "
                    "from an EMPTY base -- an initialized board with nothing of this show "
                    "on it")
    else:
        fallback = f"so the applied plan is {here} -- the bundle's last build"
    if desk is None:
        return None, [f"no desk was contacted (--state), {fallback}. A run against the desk "
                      "compares against the plan that desk's own newest write left on it, "
                      "which may differ."]
    try:
        entry, plan = journal_stack.desk_plan(show.directory, desk)
    except (journal_stack.JournalStackError, OSError):
        entry, plan = None, None
    where = journal_stack.describe_desk(desk)
    if entry is None:
        return None, [f"no write to this desk ({where}) is standing in {bundle.JOURNALS}/, "
                      f"{fallback}."
                      + (" If this desk was set up from a different plan, name it with "
                         "--plan FILE." if bundle_plan is not None else "")]
    if plan is None:
        return None, [f"this desk's newest write ({bundle.JOURNALS}/{entry.id}) predates "
                      f"per-desk plans, {fallback}."]
    same = plan == bundle_plan
    infos = [f"applied plan: the one this desk's newest write left on it -- "
             f"{bundle.JOURNALS}/{entry.id} ({entry.kind})"
             + (f"; {here} says the same." if same else ".")]
    if journal_stack.desk_moved(entry.desk, desk):
        infos.append(f"that write reached serial {entry.serial} at {entry.address}; it is at "
                     f"{desk.get('address')} now. The serial is the desk, so it is the same "
                     "one.")
    if not same and bundle_plan is not None:
        infos.append(f"{here} differs from it: {here} is the bundle's last build, and the "
                     "changes, amends and applies recorded since -- to this desk or "
                     "another -- are in the journal, not in it.")
    return plan, infos


def _claimed_but_empty_warning(strips, from_bundle: bool) -> str | None:
    """The safety net for amending against the wrong desk's plan: strips
    the applied plan claims that read empty here. A warning, never a
    refusal -- they stay OURS, so nothing is placed on them either way, and
    a strip the engineer cleared by hand is a legitimate reason for one."""
    if not strips:
        return None
    labels = [s.label for s in strips]
    shown = ", ".join(labels[:8]) + (f" and {len(labels) - 8} more" if len(labels) > 8 else "")
    text = (f"the applied plan claims {len(labels)} strip(s) as this show's that read EMPTY "
            f"on this desk -- no name, nothing on the socket, factory patch: {shown}. The "
            "plan may describe a different desk. They are still treated as ours, so nothing "
            "is placed on them;")
    if from_bundle:
        text += (" check that this is the desk the plan was applied to, or that it has not "
                 "been reloaded since. A desk that never had the show is a full apply "
                 "(`atoo apply --show DIR`), not an amend.")
    else:
        text += " check that the plan named with --plan is the one on this desk."
    return text


def _print_amend_preflight(preflight, what: str = "the amended plan") -> None:
    """Say what `amend.preflight` found, in `apply_cmd`'s words. The refusal itself is printed where the command refuses. `what`
    names the plan verified: "the amended plan" (a rebuild) or "the changed
    plan" (a typed change merged onto the desk's)."""
    verify = preflight.verify
    if verify is not None:
        if verify.errors:
            print(f"\nPre-flight verify of {what} against {preflight.where}:",
                  file=sys.stderr)
            print(verify.report(), file=sys.stderr)
        else:
            # One line, not `apply`'s full report: an amend's review is
            # long already, these warnings are about the whole show and
            # `build` reported them when it made the rebuild, and none of
            # them blocks. Each one is in `--review-json` in full.
            codes = ", ".join(dict.fromkeys(f.code for f in verify.warnings))
            said = (f"no errors, {len(verify.warnings)} warning(s) ({codes}) -- warnings do "
                    "not block" if verify.warnings else "no findings")
            print(f"\nPre-flight verify of {what} against {preflight.where}: "
                  f"{said}.")
    elif preflight.skip_verify:
        print(f"\n--skip-verify: {what} was NOT verified. The sockets this run "
              f"writes were still checked against {preflight.where}.", file=sys.stderr)
    check = preflight.model_check
    if check is not None and check.message and not check.refuses:
        print(f"\n{'INFO' if check.severity == 'info' else 'WARNING'}: {check.message}",
              file=sys.stderr)


def _change_conventions(args: argparse.Namespace, show, base: dict):
    """The conventions a change is compiled with: `(conventions text,
    its name, instructions text, its name, infos)`.

    The house file: `--conventions` if given, else the one the show on the
    desk was BUILT from (the base plan's recorded layer) -- so a
    change gets the same house treatment as the channels beside it -- else
    `~/.atoo.config`'s default. The bundle's `instructions.md` layers on
    top, exactly as for a build. Each text is passed whole: the model-facing
    reader strips the comments (`generate._conventions_section`)."""
    infos: list[str] = []
    path = getattr(args, "conventions", None)
    how = "--conventions"
    if not path:
        layer = conventions_ref.recorded_conventions(base)
        if layer is not None:
            found, _ = conventions_ref.resolve_recorded(
                layer, show.directory if show is not None else None)
            if found is not None:
                path, how = str(found), "the house file the show on the desk was built from"
    if not path:
        default = load_default_conventions()
        if default is not None:
            path, how = str(default), f"the default in {config_path()}"
    conventions = name = None
    if path:
        try:
            conventions, name = Path(path).read_text(encoding="utf-8"), Path(path).name
            infos.append(f"conventions: {path} ({how})")
        except OSError as exc:
            infos.append(f"conventions: couldn't read {path} ({exc.strerror}) -- compiled "
                         "without them")
    else:
        infos.append("conventions: none -- no --conventions, no house file recorded in the "
                     f"plan on the desk, and no default in {config_path()}. The change is "
                     "compiled from its own words and the domain knowledge alone, so a new "
                     "channel gets no house treatment.")
    instructions = instructions_name = None
    if show is not None and show.instructions.is_file():
        try:
            instructions = show.instructions.read_text(encoding="utf-8")
            instructions_name = bundle.INSTRUCTIONS
            infos.append(f"instructions: {show.instructions} (layered on top, as for a build)")
        except OSError:
            pass
    return conventions, name, instructions, instructions_name, infos


def _change_text(args: argparse.Namespace) -> "tuple[str | None, str | None]":
    """`(text, error)`: the change typed on the command line or read from
    `--change-file`."""
    text = getattr(args, "change", None)
    change_file = getattr(args, "change_file", None)
    if text and change_file:
        return None, "give the change as text OR with --change-file, not both"
    if change_file:
        try:
            text = Path(change_file).read_text(encoding="utf-8")
        except OSError as exc:
            return None, f"couldn't read --change-file {change_file}: {exc.strerror}"
    if text is not None and not text.strip():
        return None, "the change is empty -- say what to add or drop"
    return (text.strip() if text is not None else None), None


def patch_cmd(args: argparse.Namespace) -> int:
    """`atoo patch` -- change a desk that already has a show on it (or
    nothing yet), and move nothing else (O2; FR-2.1-FR-2.7).

    Two modes, one operation:

    * **a change** -- plain English, compiled on its own by one model call
      into a change set and merged onto the plan on the desk
      (`atoo/patch.py`). Recorded in the journal as a patch, with its
      text and short name.
    * **`--amended-plan FILE`** -- a rebuilt plan as the change: what
      `atoo amend` has always done, and still does under that name
      (`amend_cmd` is this function).

    Everything after the change is known is amend's back half, unchanged:
    read the desk, work out the delta, show what will and will NOT be
    written, and -- only with `--confirm` -- write, prove, journal. A
    setup-and-rehearsal operation, not a mid-show one.
    `plan.json` is never written: only a build does that.
    """
    import time

    from atoo import amend as amend_engine
    from atoo import desk_view, journal_stack
    from atoo import patch as patch_engine

    if getattr(args, "promote", None):
        return _promote_change(args)
    mode = "amend" if getattr(args, "amended_plan", None) else "patch"
    verb = "patch" if mode == "patch" else "amend"
    started = time.monotonic()

    # Stated or taken from the bundle? Only a plan taken from the bundle is
    # swapped for the one the connected desk's own newest write left there
    # (`_desk_applied_plan`); a plan somebody named is theirs to vouch for.
    plan_stated = bool(args.plan)
    try:
        show = _open_bundle(args)
        _fill_from_bundle(args, show, "plan", bundle.PLAN)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    change_text = change_set = None
    amended = None
    compile_infos: list[str] = []
    if mode == "amend" and (getattr(args, "change", None) or getattr(args, "change_file", None)
                            or getattr(args, "change_set", None)):
        print("--amended-plan patches from a rebuilt plan; a typed change (or --change-file, "
              "--change-set) is the other way -- give one or the other", file=sys.stderr)
        return 1
    if mode == "amend":
        if not args.plan:
            print("--plan is required (or --show DIR, to take the applied plan.json from a "
                  "show bundle)", file=sys.stderr)
            return 1
        amended = _load_plan_file(args.amended_plan)
        if amended is None:
            return 1
    else:
        if show is None and not args.plan:
            print("patch needs --show DIR (the show bundle whose journal records what is on "
                  "the desk), or --plan FILE naming the plan on the desk", file=sys.stderr)
            return 1
        change_text, error = _change_text(args)
        if error:
            print(error, file=sys.stderr)
            return 1
        if getattr(args, "change_set", None):
            try:
                change_set, saved_text = patch_engine.load_change_set(
                    args.change_set, infos=compile_infos)
            except (OSError, ValueError) as exc:
                print(f"--change-set {args.change_set}: {exc}", file=sys.stderr)
                return 1
            except patch_engine.ChangeError as exc:
                print(f"--change-set {args.change_set}: {exc}", file=sys.stderr)
                return 1
            change_text = change_text or saved_text
        if not change_text and change_set is None:
            print("say what the change is: atoo patch --show DIR \"trumpet and sax on "
                  "A 21-22\" (or --change-file FILE; or --amended-plan FILE to "
                  "patch from a rebuilt plan)", file=sys.stderr)
            return 1

    applied = None
    if args.plan:
        applied = _load_plan_file(args.plan)
        if applied is None:
            return 1

    for label in args.allow_strip or []:
        if not _valid_strip_label(label):
            print(f"--allow-strip {label!r}: expected a strip label like 'ch:20' or 'aux:3'",
                  file=sys.stderr)
            return 1

    # Stage 1 -- read the desk. Scoped: four addresses per strip, not
    # `audit`'s full sweep, because this is the command that gets run while
    # a support act is playing.
    console = None
    desk_read_s = None
    read_count = 0
    if args.state:
        state = _load_state_file(args.state)
        if state is None:
            return 1
        faces = dict(state.values)
    else:
        if args.console is None:
            return _no_console_address(offline="--state FILE")
        console = _open_console(args)
        if console is None:
            return 1
        read_plan = amend_engine.occupancy_read_plan(channels=args.channels, aux=args.aux)
        progress = None
        if not args.no_progress:
            from atoo.progress import ReadProgress
            progress = ReadProgress(len(read_plan), label="occupancy read")
        t0 = time.monotonic()
        state = amend_engine.read_occupancy(
            console, channels=args.channels, aux=args.aux, progress=progress)
        # Each strip's colour, and each bus, main, matrix and
        # DCA's name and colour, so the review can draw the desk as the
        # WING draws it (`desk_view`). Read-only, like everything here.
        # A --confirm run writes what its preview showed and is not drawn
        # again, so it skips this read.
        face_plan = [] if args.confirm else desk_view.face_read_plan()
        if progress is not None and hasattr(progress, "add_total") and face_plan:
            progress.add_total(len(face_plan))
        faces = desk_view.read_faces(console, progress=progress) if face_plan else {}
        desk_read_s = time.monotonic() - t0
        read_count = len(read_plan) + len(amend_engine.source_name_addresses(
            state, channels=args.channels, aux=args.aux)) + len(face_plan)
        if progress is not None:
            progress.finish()

    # Which plan is ON THIS DESK (per-desk journals). plan.json is the
    # bundle's last build; the desk's own newest write says what is on it.
    source_infos: list[str] = []
    if show is not None and not plan_stated:
        desk_plan, source_infos = _desk_applied_plan(
            show, _desk_of(args) if console is not None else None, applied)
        if desk_plan is not None:
            applied = desk_plan
        for info in source_infos:
            print(f"  INFO {info}")
    console_model = (state.console_model or getattr(args, "console_model", None)
                     or (resolve_console_model(applied) if applied else None))
    if applied is None:
        # A patch on a desk this bundle never wrote, with no plan.json: an
        # initialized board, and a supported start.
        if console_model is None:
            if console is not None:
                console.close()
            print("no console model: the desk did not say which WING it is and there is no "
                  "plan to take it from -- pass --console-model", file=sys.stderr)
            return 1
        applied = patch_engine.empty_base(console_model)

    model_s = None
    compiled_by = None
    repair_with = None
    if mode == "patch" and change_set is None:
        conventions, conventions_name, instructions, instructions_name, conv_infos = \
            _change_conventions(args, show, applied)
        for info in conv_infos:
            print(f"  INFO {info}")
        source_infos += conv_infos
        try:
            facts.panel_for(console_model)
        except facts.UnknownConsoleModel as exc:
            if console is not None:
                console.close()
            print(f"{exc}\npass --console-model, e.g. --console-model wing-compact",
                  file=sys.stderr)
            return 1
        if getattr(args, "prompt_dir", None):
            os.environ["ATOO_PROMPT_DIR"] = args.prompt_dir
        print(f"\nCompiling the change: {change_text.strip()}")
        t0 = time.monotonic()
        try:
            provider = provider_from_env()
            compiled_by = getattr(provider, "model", None) or type(provider).__name__
            compile_args = dict(
                provider=provider, console_model=console_model,
                conventions=conventions, conventions_name=conventions_name,
                instructions=instructions, instructions_name=instructions_name,
                constrain=not args.no_constrain)
            change_set = patch_engine.compile_change(
                change_text, applied, infos=compile_infos, **compile_args)
            if getattr(provider, "repairs_replies", False):
                repair_with = compile_args
        except (AIProviderError, patch_engine.ChangeError, generate.PromptError) as exc:
            if console is not None:
                console.close()
            print(f"the change could not be compiled: {exc}", file=sys.stderr)
            print(f"  {install_info.describe().summary()}", file=sys.stderr)
            if isinstance(exc, AIProviderError):
                print("  nothing was changed: the desk and the show are as they were.",
                      file=sys.stderr)
            partial = getattr(exc, "partial_text", "")
            if partial:
                where = _partial_path(
                    (show.directory if show is not None else Path(".")) / "change.json")
                try:
                    where.write_text(partial, encoding="utf-8")
                    print(f"  the {len(partial):,} characters that did arrive are in {where}",
                          file=sys.stderr)
                except OSError:
                    pass
            return 1
        model_s = time.monotonic() - t0
        for info in compile_infos:
            print(f"  INFO {info}")
    elif mode == "patch":
        compiled_by = f"--change-set {args.change_set}"
        for info in compile_infos:
            print(f"  INFO {info}")
    if mode == "patch" and patch_engine.changes_nothing(change_set):
        # An instruction that compiles to nothing was not carried out: the
        # model judged it impossible and said so in its notes rather than
        # writing it for the code to refuse (a send to a bus the desk does
        # not have). Refused, with the model's own reason, never "nothing
        # to add".
        if console is not None:
            console.close()
        notes = [n for n in change_set.get("notes") or [] if isinstance(n, str) and n.strip()]
        for note in notes:
            print(f"  NOTE {note.strip()}")
        print("\nRefusing to patch: the change, as compiled, adds, drops and edits nothing, "
              "so it was not carried out" + (" -- the reason is the note above." if notes
                                             else ". Say it again, more exactly.")
              + " Nothing was written.", file=sys.stderr)
        return 2
    change = None
    saved = None
    if mode == "patch":
        saved = patch_engine.saved_change_set(change_set, change_text)
        change = patch_engine.change_block(change_text, change_set, None)
        print(f"\nChange: {change['name']}")
        if getattr(args, "save_change_set", None):
            try:
                Path(args.save_change_set).write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
                print(f"  the compiled change set is saved in {args.save_change_set} -- "
                      "`--change-set` it to write exactly this one")
            except OSError as exc:
                print(f"--save-change-set {args.save_change_set}: {exc.strerror}",
                      file=sys.stderr)

    # The preset library the change's new strips take their values from: the one the plan on the desk was built with, found
    # without a flag, and said -- with a WARNING up top, before the review,
    # when the change names presets and there is none.
    library_choice = _preset_library_choice(args, applied)
    preset_library = library_choice.library
    for warning in library_choice.warnings:
        print(warning, file=sys.stderr)
    for info in library_choice.infos:
        print(f"  INFO {info}")
    from atoo import preset_library as preset_library_module
    library_warning = preset_library_module.missing_library_warning(change_set, library_choice)
    if library_warning:
        print(f"WARNING: {library_warning}", file=sys.stderr)

    before: dict = {}
    after: dict = {}
    proof = amend_engine.WitnessPlan((), False, "the change never got as far as one")
    try:
        occupancy = amend_engine.strip_occupancy(
            state, applied, channels=args.channels, aux=args.aux)
        print(amend_engine.occupancy_summary(occupancy))
        empty_warning = _claimed_but_empty_warning(
            amend_engine.claimed_but_empty(occupancy), bool(source_infos))
        if empty_warning:
            print(f"WARNING: {empty_warning}", file=sys.stderr)

        # Stage 2/3 -- the delta, and what will NOT be written.
        # What the desk says is on each AES50 port: a socket past the end of
        # a stage box is not one it has, whatever the port's 48 addresses say.
        aes50_devices = _aes50_devices(console, state)
        gain_texts = _gain_texts(args, show, applied) if mode == "patch" else ()
        if mode == "patch":
            def plan_this():
                # A bus, DCA or mute group the change names that
                # the plan on the desk does not know is read off the desk --
                # only that object, never a sweep -- and carried out against.
                # Read again for a repaired change set, which may name others.
                nonlocal read_count
                desk_objects = None
                if patch_engine.unknown_names(applied, change_set):
                    desk_objects = {**state.values, **faces}
                    for find_reads in (patch_engine.name_reads, patch_engine.member_reads):
                        reads = find_reads(applied, change_set, desk_objects)
                        if reads and console is not None:
                            desk_objects.update(desk_view.read_addresses(console, reads))
                            read_count += len(reads)
                return patch_engine.plan_patch(
                    applied, change_set, occupancy, allow_strips=set(args.allow_strip or []),
                    console_model=state.console_model or getattr(args, "console_model", None),
                    presets=preset_library, text=change_text, aes50_devices=aes50_devices,
                    gain_texts=gain_texts, desk_objects=desk_objects)
            amendment, _merge = plan_this()
            if amendment.blocked and repair_with is not None:
                # The desk refused what the model proposed: a provider that
                # repairs replies is asked once more, with the refusal in
                # front of it (a socket that is not free, a name that is not
                # there). One more call, never a loop.
                problem = "\n".join(c.line() for c in amendment.blocked)
                try:
                    change_set = patch_engine.repair_change_set(
                        change_text, applied, change_set, problem, infos=compile_infos,
                        **repair_with)
                except (AIProviderError, patch_engine.ChangeError) as exc:
                    print(f"  INFO the desk refused the first reply and asking again did not help: {exc}")
                else:
                    for info in compile_infos[-1:]:
                        print(f"  INFO {info}")
                    saved = patch_engine.saved_change_set(change_set, change_text)
                    change = patch_engine.change_block(change_text, change_set, None)
                    print(f"\nChange: {change['name']}")
                    amendment, _merge = plan_this()
        else:
            amendment = amend_engine.plan_amendment(
                applied, amended, occupancy, allow_strips=set(args.allow_strip or []),
                console_model=state.console_model)
        print("\n" + amendment.summary())
        live = [e for e in amendment.edits if e.moves_audio]
        if live:
            # A physical patch change on something already
            # running moves audio the moment it is written -- said on its own,
            # before anything else in the review, not as one note among many.
            print(f"\n!! {len(live)} PATCH CHANGE(S) ON SOMETHING ALREADY RUNNING -- these "
                  "move audio the moment they are written:")
            for edit in live:
                print(f"!!   {edit.line()}")
        switched = [e for e in amendment.edits if e.switches_phantom]
        if switched:
            print(f"\n!! {len(switched)} PHANTOM POWER CHANGE(S) ON SOMETHING ALREADY RUNNING "
                  "-- 48V is switched the moment it is written:")
            for edit in switched:
                print(f"!!   {edit.line()}")
        if amendment.shifted:
            # An explicit insert rewrites every strip it moves, and audio
            # moves with the names: said before the notes, with each strip.
            print(f"\n!! {len(amendment.shifted)} RUNNING STRIP(S) RENUMBERED -- each is "
                  "rewritten whole on its new number the moment it is written:")
            for name, old, new in amendment.shifted:
                print(f"!!   {name!r}: {old} -> {new}")
        for info in amendment.infos:
            print(f"  INFO {info}")
        for warning in amendment.warnings:
            # A warning that states its own level (an explicit drop of a strip
            # the desk changed) is printed as one, not as a note.
            print(warning if warning.startswith("WARNING: ") else f"  note: {warning}",
                  file=sys.stderr)

        targets = amend_engine.amendment_targets(amendment)
        print("\n" + targets.summary())
        # A --confirm run lists the same warnings again under its summary line
        # (`_print_result_warnings`), which promises them: not twice.
        for warning in ([] if args.confirm else targets.warnings):
            print(f"  - {warning}", file=sys.stderr)

        # Apply's pre-flight: the verify gate over the
        # effective plan and the socket check over what this run
        # writes, against the desk's model. Before the review is written,
        # so a preview shows the refusal and the Patch screen never arms a
        # write it would refuse. Nothing to write is nothing to check.
        preflight = None
        list_notes: list[str] = []
        if targets.to_write:
            # The show's own input list, when it has one: the verify then
            # checks what a full build checks against it, and says it did.
            rows = None
            if show is not None and show.has(bundle.INPUT_LIST):
                try:
                    rows = load_input_list(str(show.path(bundle.INPUT_LIST)))
                except (OSError, InputListError) as exc:
                    reason = exc.strerror if isinstance(exc, OSError) else exc
                    list_notes.append(f"{bundle.INPUT_LIST}: couldn't be read ({reason}) -- "
                                      "the pre-flight ran without it")
            preflight = amend_engine.preflight(
                amendment,
                identity_args=(getattr(args, "console_identity", None)
                               if console is not None else None),
                address=args.console if console is not None else None,
                skip_verify=args.skip_verify,
                presets=preset_library,
                what="change" if mode == "patch" else "amend",
                rows=rows, rows_name=bundle.INPUT_LIST,
                layers=_plan_layers(amendment.effective_plan, show, args.plan),
                aes50_devices=aes50_devices)
            list_notes = preflight.infos + list_notes
            for info in list_notes:
                print(f"  INFO {info}")
            _print_amend_preflight(preflight, "the changed plan" if mode == "patch"
                                   else "the amended plan")

        timing = {"desk_read_s": None if desk_read_s is None else round(desk_read_s, 2),
                  "desk_addresses": read_count or None,
                  "model_s": None if model_s is None else round(model_s, 2),
                  "total_s": round(time.monotonic() - started, 2)}
        timing_line = _timing_line(timing, compiled_by, mode)
        if mode == "patch":
            # The question asked of a change; an amend
            # carries it in --review-json only, and prints as it always did.
            print(f"\n{timing_line}")

        # Before any refusal below, so a blocked review is written too --
        # the reason it is blocked is exactly what a reader needs to see.
        review = amend_engine.review_payload(occupancy, amendment, targets)
        review["infos"] = (source_infos + compile_infos + library_choice.infos
                           + review["infos"] + list_notes)
        if empty_warning:
            review["warnings"] = [empty_warning] + review["warnings"]
        # Drawn first in the review, as a WARNING, not among the notes.
        review["preset_warning"] = library_warning
        review["preflight"] = preflight.to_review() if preflight is not None else None
        if preflight is not None and preflight.refuses:
            # The one flag the page and `reviewIsWritable` already refuse
            # to arm on -- a pre-flight refusal is a blocked review.
            review["blocked"] = True
        review["mode"] = mode
        review["timing"] = {**timing, "line": timing_line}
        # The desk as scribble strips, with what this change
        # adds, edits and returns to free marked on it.
        review["desk"] = desk_view.patch_desk(occupancy, faces, amendment)
        review["change"] = None if mode == "amend" else {
            "text": change_text, "name": change["name"],
            "number": (journal_stack.next_change_number(show.directory)
                       if show is not None else None),
            "compiled_by": compiled_by, "change_set": saved,
        }
        if args.review_json and not _write_review_json(args.review_json, review):
            return 1

        if amendment.blocked:
            print(f"\nRefusing to {verb}: nothing was written.", file=sys.stderr)
            return 2
        if targets.collisions:
            # The independent cross-check. It firing means this tool's own
            # scope is wrong, not that the plan is -- so it is a refusal,
            # never a warning to read past.
            print(f"\nRefusing to {verb}: the scope overlaps the applied plan.",
                  file=sys.stderr)
            return 2
        if not targets.to_write:
            print("\nNothing to add and nothing to return to free. The console was not "
                  "written to.")
            return 0
        if preflight is not None and preflight.refuses:
            # After the review, and before the offline return: a preview
            # from --state is refused too, and says so with the exit code.
            print(f"\nERROR: {preflight.refusal}", file=sys.stderr)
            return 2
        if console is None:
            print("\nReviewed offline from --state; no console was contacted. Re-run with "
                  "--console to preview against the desk, and --confirm to write.")
            return 0

        # Stage 4 -- the write, with FR-2.2's proof read around it.
        journal_path = args.journal
        if journal_path is None and args.confirm:
            if show is not None:
                journal_path = _stack_journal_path(show, mode, args)
            else:
                journal_path = str(Path(args.plan).with_suffix("").with_suffix(
                    f".{mode}-journal.json"))
        # FR-2.2's before/after read. `witness_plan` decides whether it
        # runs, from the two facts separately -- is this a real write, and
        # did the user ask to skip it.
        proof = amend_engine.witness_plan(
            targets, confirm=args.confirm, skip=args.skip_untouched_proof)
        phases = _phases(args)
        if proof.read:
            before = _read_witness(console, proof, args, phases, "before")
        try:
            result = amend_engine.apply_amendment(
                amendment, console, dry_run=not args.confirm, journal_path=journal_path,
                targets=targets, desk=_desk_of(args),
                model_check=preflight.journal_model_check() if preflight else None,
                phases=phases)
        except amend_engine.AmendRefused as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 2
        if proof.read:
            after = _read_witness(console, proof, args, phases, "after")
    finally:
        if console is not None:
            console.close()

    print("\n" + result.summary())
    # One line per distinct warning, naming the strips it covers
    # (FR-X.15c); the journal keeps every one.
    _print_result_warnings(result)
    if journal_path and not result.dry_run:
        # Before the abort check, for the reason `apply_cmd` gives: a
        # partial journal is the one nobody planned for.
        if result.aborted:
            print(f"Journal: {journal_path}")
            _record_change_on_stack(
                show, mode, journal_path, applied,
                f"the plan it started from (this {verb} aborted partway)",
                desk=_desk_of(args), change=change)
            print(f"WARNING: this {verb} aborted partway, so the desk holds only part of it. "
                  "The journal records what landed; `atoo undo` takes that off again.",
                  file=sys.stderr)
        else:
            _record_change_on_stack(show, mode, journal_path, amendment.effective_plan,
                                    "the effective plan", desk=_desk_of(args), change=change)
            _say_plan_json_untouched(show, args.plan, modified=[
                c.where for c in amendment.changes
                if c.kind is amend_engine.ChangeKind.MODIFIED])
    if result.aborted:
        return 1

    moved = amend_engine.witness_changes(before, after, proof)
    if proof.read:
        proof_line = (f"Untouched-strip proof: {len(proof)} unrelated address(es) "
                      f"read before and after, {len(moved)} changed.")
    else:
        proof_line = proof.line()
    print(proof_line)
    if args.review_json:
        review["proof"] = {"read": proof.read, "addresses": len(proof),
                           "moved": list(moved), "line": proof_line}
        _write_review_json(args.review_json, review)
    for address in moved:
        print(f"  MOVED {address}: {before.get(address)!r} -> {after.get(address)!r}",
              file=sys.stderr)

    if result.dry_run:
        if mode == "patch":
            print("\nNothing was written -- this was a preview. Re-run with --confirm to write "
                  "the change. A --confirm run compiles it again unless it is given "
                  "--change-set: save this one with --save-change-set FILE to write exactly "
                  "what you just reviewed.")
        else:
            print("\nNothing was written -- this was a preview. Re-run with --confirm to amend.")
        return 0
    if journal_path:
        scope_line = ", ".join(amendment.strips) or "nothing added"
        if amendment.released:
            scope_line += f"; returned to free: {', '.join(amendment.released)}"
        if amendment.edited:
            scope_line += f"; edited: {', '.join(amendment.edited)}"
        if amendment.shifted:
            scope_line += (f"; renumbered {len(amendment.shifted)} strip(s): "
                           f"{amendment.shifted[0][1]}-{amendment.shifted[-1][1]} down to "
                           f"{amendment.shifted[0][2]}-{amendment.shifted[-1][2]}")
        print(f"Journal: {journal_path} (scope: {scope_line})")
    if moved:
        print(f"\n{len(moved)} address(es) belonging to strips this {verb} does not own "
              "CHANGED across the write. This is the failure the untouched-strip proof exists "
              "to catch.",
              file=sys.stderr)
        return 2
    if result.mismatches:
        print(f"\n{len(result.mismatches)} parameter(s) did NOT land:", file=sys.stderr)
        for m in result.mismatches:
            print(f"  - {m.address}: wanted {m.intended_value!r}, console reports "
                  f"{m.readback_value!r}", file=sys.stderr)
        return 2
    return 0


def _promote_change(args: argparse.Namespace) -> int:
    """`atoo patch --show DIR --promote REF` -- keep a change in the show
    for good (`atoo/promote.py`). Appends the
    change's text to instructions.md and its added inputs to input.csv;
    never plan.json. A preview unless `--confirm`. No console is contacted
    and no model is called."""
    from atoo import journal_stack, promote

    others = [flag for flag, value in (
        ("change text", args.change), ("--change-file", args.change_file),
        ("--change-set", args.change_set), ("--amended-plan", args.amended_plan))
        if value]
    if others:
        print(f"--promote keeps a change already written, so it takes no {others[0]} -- "
              "write the change first, then promote it", file=sys.stderr)
        return 1
    if not args.show:
        print("--promote needs --show DIR: the bundle whose journal records the change and "
              "whose instructions.md and input.csv it goes into", file=sys.stderr)
        return 1
    try:
        show = _open_bundle(args)
        result = promote.promotion(show.directory, args.promote)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (promote.PromoteError, journal_stack.JournalStackError) as exc:
        print(f"cannot promote: {exc}", file=sys.stderr)
        return 1
    print(result.summary())
    for info in result.infos:
        print(f"  INFO {info}")
    if result.already:
        return 0
    if not args.confirm:
        print("\nNothing was written -- this was a preview. Re-run with --confirm to keep "
              f"{result.label} in the show.")
        return 0
    try:
        written = promote.write(show.directory, result)
    except OSError as exc:
        print(f"cannot promote: {exc}", file=sys.stderr)
        return 1
    print(f"\nWritten: {', '.join(written)}. {result.label} is in the show now: rebuild "
          f"(`atoo build --show {args.show}`) and the next plan.json carries it.")
    return 0


def _read_witness(console, proof, args, phases, when: str):
    """One pass of FR-2.2's untouched-strip proof read, reported as a phase
    of its own: "reading the untouched strips, before
    writing"."""
    from atoo import amend as amend_engine

    label = f"reading the untouched strips, {when} writing"
    phase = None if phases is None else phases.start(label, len(proof.addresses))
    values = amend_engine.read_witness(console, proof, progress=phase,
                                       bulk=not args.per_leaf)
    if phase is not None:
        phase.finish()
    return values


def amend_cmd(args: argparse.Namespace) -> int:
    """`atoo amend` -- kept, with every flag it had, as the name of
    `atoo patch --amended-plan` (decision 8): scripts that
    call it keep running."""
    return patch_cmd(args)


def _timing_line(timing: dict, compiled_by: str | None, mode: str) -> str:
    """How long this change took, in the two halves an engineer wants to know: the model
    call that compiled it, and the desk read."""
    parts = []
    if timing.get("desk_read_s") is None:
        parts.append("desk read: none (--state)")
    else:
        parts.append(f"desk read {timing['desk_read_s']:.1f}s "
                     f"({timing.get('desk_addresses') or 0} addresses)")
    if mode == "patch":
        if timing.get("model_s") is None:
            parts.append(f"model call: none ({compiled_by})")
        else:
            parts.append(f"model call {timing['model_s']:.1f}s ({compiled_by})")
    parts.append(f"{timing['total_s']:.1f}s in all to this review")
    return "Timing: " + "; ".join(parts) + "."


def _add_patch_common_arguments(ap: argparse.ArgumentParser, *, what: str) -> None:
    """Every flag `patch` and `amend` share -- the whole of amend's, which is
    the back half both run."""
    _add_show_argument(ap)
    ap.add_argument(
        "--plan", default=None,
        help="The plan that is ALREADY on the desk. Normally left out: with --show, it is "
             "the plan the desk's own newest journal entry left on it, else the bundle's "
             "plan.json" + (", else an empty board." if what == "patch" else "."))
    # Same mutually-exclusive shape `audit` uses, and for the same reason:
    # argparse can enforce "not both", and the command enforces "at least
    # one" after --console has had its chance to resolve from the
    # environment or the config file.
    source_group = ap.add_mutually_exclusive_group()
    source_group.add_argument(
        "--console", default=None,
        help="Console IP address -- read which strips are free from the live desk. "
             + CONSOLE_FLAG_HELP.split(".", 1)[1].strip())
    source_group.add_argument(
        "--state", default=None,
        help="A JSON object of address -> value (the same shape `audit --state` takes) -- "
             "work out the delta from that instead of a live console. Reviews the whole "
             f"{'change' if what == 'patch' else 'amendment'} offline; it can never write.")
    ap.add_argument("--port", type=int, default=None, help="Console OSC port (default: 2223)")
    ap.add_argument("--timeout", type=float, default=None,
                    help="Per-request timeout in seconds (default: 1.0)")
    ap.add_argument("--channels", type=int, default=40,
                    help="Channel strips to read occupancy for (default: 40, WING Compact)")
    ap.add_argument("--aux", type=int, default=8,
                    help="Aux strips to read occupancy for (default: 8, WING Compact)")
    ap.add_argument(
        "--allow-strip", action="append", default=None, metavar="BANK:N",
        help=f"Let the {what} place a new object on one strip the desk says is occupied or "
             "did not answer, e.g. --allow-strip ch:20. Per strip and repeatable; there "
             "is deliberately no 'allow everything' switch. A strip the plan on the desk "
             "owns can never be opened this way.")
    ap.add_argument(
        "--confirm", action="store_true",
        help=f"Actually write. Without this, {what} is a preview that changes nothing -- the "
             "same arming `apply` requires, on the same reasoning. This ONE flag arms "
             "everything the preview showed, including returning a dropped channel's strip "
             "to free; there is deliberately no second switch for the clears, because a "
             "second switch is a second thing to tick past.")
    ap.add_argument(
        "--journal", default=None,
        help="Where to record every write with its prior value AND this run's scope -- "
             "which strips it was allowed to touch. Defaults to a new timestamped entry in "
             f"the bundle's journals/ directory, or <plan>.{what}-journal.json without --show. "
             "With --show, a confirmed run is added to the bundle's journals/ stack whatever "
             "this says, with the plan it left on the desk"
             + (" and the change's text and short name." if what == "patch" else "."))
    ap.add_argument(
        "--skip-verify", action="store_true",
        help=f"Write without the pre-flight verify of the {what}ed plan -- the same gate, "
             "and the same escape, as `apply --skip-verify`: without it, a verify ERROR "
             f"refuses the {what} (warnings never do). It does NOT skip the socket check: a "
             f"socket this {what} would write that the desk does not have is refused either "
             "way.")
    ap.add_argument(
        "--skip-untouched-proof", action="store_true",
        help="Do not read every unrelated address before and after the write. That read "
             "is the PROOF that nothing already in use moved -- not merely the absence of "
             "a write to it. It should rarely be worth skipping now: a PREVIEW never "
             "runs it at all (it writes nothing, so there is nothing to prove), and a "
             "--confirm run reads the set through the node-dump path -- about 140 requests "
             "rather than 670, roughly 1.4s a pass on a Compact. This flag only affects a "
             "--confirm run, and skipping leaves that run resting on the target filter "
             "alone.")
    # The same way back `audit` and `watch` have. The witness
    # read has been node-dump by default; this is its
    # opt-out. The occupancy read is per-leaf regardless -- see
    # `amend.read_occupancy` -- so this flag does not touch it.
    ap.add_argument(
        "--per-leaf", action="store_true",
        help="Read the before/after untouched-strip proof one request per leaf instead of "
             "by node dump -- about 670 requests a pass rather than 140, roughly 4-5x "
             "slower. The diagnostic path, as on audit and watch: the two read paths "
             "agreed on every value compared on a real WING Compact. The "
             "occupancy read is per-leaf either way.")
    ap.add_argument(
        "--review-json", default=None, metavar="FILE",
        help="Also write the review -- every strip's occupancy verdict, the delta, and "
             "what will and will NOT be written -- as JSON to FILE, using the same words "
             f"the command prints. Written before any refusal, so a blocked {what} still "
             "says why; a --confirm run adds the untouched-strip proof after the write. "
             "`atoo ui`'s Patch screen reads it.")
    ap.add_argument(
        "--no-progress", action="store_true",
        help=NO_PROGRESS_WRITE_HELP)


def _add_patch_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "change", nargs="?", default=None, metavar="CHANGE",
        help="The change, in plain English: what to add and what to drop, e.g. \"trumpet, "
             "sax and trombone on A 21-23, in the Horns DCA\". Quote it.")
    ap.add_argument(
        "--change-file", default=None, metavar="FILE",
        help="Read the change from FILE instead -- for a long one, or one written in an "
             "editor.")
    ap.add_argument(
        "--amended-plan", default=None, metavar="FILE",
        help="Patch from a rebuilt plan instead of a typed change: the same show, built "
             "again (`atoo build --out FILE`) with the change in its inputs. This is "
             "what `atoo amend` does, and is recorded as an amend.")
    ap.add_argument(
        "--change-set", default=None, metavar="FILE",
        help="Use this compiled change set instead of calling the model -- one "
             "--save-change-set wrote, or a --review-json file. How a --confirm run writes "
             "exactly the change set a preview showed, and how a change is reviewed with no "
             "model at all.")
    ap.add_argument(
        "--save-change-set", default=None, metavar="FILE",
        help="Also save the compiled change set (with the change's text) to FILE, for "
             "--change-set to write later.")
    ap.add_argument(
        "--promote", default=None, metavar="CHANGE",
        help="Keep a change already written in the show for good: append its text to the "
             "bundle's instructions.md, under a dated 'Promoted changes' heading, and a row "
             "to input.csv for each input it added that the list does not have. CHANGE is its "
             "number (3, or 'change 3'), its short name, or its journal entry. Needs --show; "
             "no console or model. A preview unless --confirm. plan.json is not touched: "
             "rebuild to put the change in it. A change that was undone is refused.")
    ap.add_argument(
        "--conventions", default=None, metavar="FILE",
        help="The house conventions to compile the change with. Default: the file the show "
             "on the desk was built from (recorded in its plan), else the [conventions] "
             "default in ~/.atoo.config. The bundle's instructions.md layers on top, as "
             "for a build.")
    ap.add_argument(
        "--presets", default=None, metavar="DIR",
        help="The preset library the change's new channels and busses take their presets "
             "from (.chn channel presets, .bus bus presets), expanded into the change as a "
             "build expands them into a plan. Not needed as a rule: without it, the library "
             "the plan on the desk was built with (or the packaged starter presets, when "
             "its files match them), else [presets] default in ~/.atoo.config; an INFO "
             "says which. With none, a change that names presets warns up front, as a "
             "WARNING, and its new strips are written without those presets' values.")
    _add_console_model_argument(ap)
    ap.add_argument(
        "--no-constrain", action="store_true",
        help="Do not constrain the model's reply to the change-set format (the same escape "
             "as `build --no-constrain`). The reply is still checked against it. The claude, "
             "ollama and api providers constrain decoding (the api provider sends it as "
             "`response_format`; ATOO_AI_STRUCTURED=0 also stops that).")
    ap.add_argument(
        "--prompt-dir", default=None, metavar="DIR",
        help="Read change_compile.md from DIR instead of the packaged prompts (sets "
             "ATOO_PROMPT_DIR for this run).")
    _add_patch_common_arguments(ap, what="patch")


def _add_amend_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--amended-plan", required=True, metavar="FILE",
        help="The rebuild: the same show, built again from the same conventions with "
             "the change in it (three horn rows added to input.csv, a line in "
             "instructions.md). `atoo build` produces it; amend works out what is "
             "new in it and writes only that. The same as `atoo patch --amended-plan`.")
    _add_patch_common_arguments(ap, what="amend")


PATCH_DESCRIPTION = (
    "Change a console that already has a show on it -- or nothing yet -- and move\n"
    "nothing else.\n"
    "\n"
    "  atoo patch --show ./touringband --console 192.0.2.16 \\\n"
    "      \"trumpet, sax and trombone on A 21-23, Horns DCA, send to MON2\"\n"
    "  ... --confirm --change-set horns.json      (write exactly what the preview showed)\n"
    "  atoo patch --show ./touringband --console 192.0.2.16 \"HPF 100 on the vocals\"\n"
    "  atoo patch --show ./touringband --promote 3 --confirm\n"
    "  atoo patch --show ./touringband --amended-plan ./touringband/rebuilt.plan.json ...\n"
    "\n"
    "What you type is a CHANGE, and it is called that in messages, the journal and\n"
    "the page (\"change 3: Add horns on A 21-23\"). \"Patch\" in findings and plan fields\n"
    "keeps meaning socket routing only; the command is called patch because it is\n"
    "the word for a small change on top of something that exists.\n"
    "\n"
    "A permanent change to the show means editing the input list, conventions or\n"
    "instructions and rebuilding. patch is for ad-hoc changes to what is on the\n"
    "board now, at short notice -- a horn section turning up, a vocalist leaving --\n"
    "and it works for building a show up one change at a time from an initialized\n"
    "board. A setup and rehearsal tool: use it before doors, not during the show.\n"
    "\n"
    "The model sees only your change, the plan the desk's own journal says is on it\n"
    "(else plan.json, else an empty board -- the review says which), and your\n"
    "conventions and the bundle's instructions.md. It returns a change set -- what to\n"
    "add, what to drop, which named fields to set on things already on the desk,\n"
    "and a short name -- never a whole plan. Code merges it and\n"
    "refuses a reference to anything that does not exist (a send to a bus that is\n"
    "neither on the desk nor added). Sockets the change names are honored; others\n"
    "are chosen, and each choice is said at INFO.\n"
    "\n"
    "Everything after that is amend's: new channels are placed on genuinely free\n"
    "strips (skipping occupied ones, never renumbering a running one unless the\n"
    "change says INSERT -- see below), a dropped\n"
    "channel's strip is RETURNED TO FREE -- one the change names, even where the desk\n"
    "no longer reads it as the strip the show built (said at WARNING, and Undo puts\n"
    "it back), the pre-flight verifies the result and checks every socket written\n"
    "against the desk, the review shows what will and will NOT be written, and only\n"
    "--confirm writes -- reading every unrelated address before and after to prove\n"
    "none moved, and journalling the run with the change's text and short name.\n"
    "`atoo undo --show DIR` takes the newest write off again.\n"
    "\n"
    "A change may also EDIT something already running -- \"move the sax to MON3 at\n"
    "-10\", \"rename ch 5 Kick In\", \"HPF 100 on the vocals\" -- but only in the fields\n"
    "it names. Code writes exactly the addresses those fields change, shows old -> new\n"
    "for each at INFO, and keeps every other address of the strip in the untouched\n"
    "proof. A fader moves only when the change says \"fader\"; a repatch of a running\n"
    "strip is marked MOVES AUDIO LIVE, and switching its 48V phantom power SWITCHES 48V\n"
    "LIVE. A strip's source can be changed in its phantom, type and model, not in\n"
    "which input it is or whether it is stereo. Undo puts the old values back.\n"
    "\n"
    "INSERT AND RENUMBER. \"insert HiHat after Snare and renumber the channels after\n"
    "it\" (or \"insert\", \"renumber\", \"move the rest down\") puts the channel there and\n"
    "moves the strips after it down: each is rewritten whole on its new number, with\n"
    "its patch, sends, DCA and mute groups, and the review lists every strip that\n"
    "moves. Undo puts them all back. \"add HiHat after Snare\" does NOT renumber: the\n"
    "channel goes on the next free strip and an INFO gives the words that would.\n"
    "\n"
    "A Line source patched to a head amp does not keep a mic's gain: it takes 0 dB\n"
    "unless a gain is stated for it, said at INFO. A socket past the end of a stage\n"
    "box on an AES50 port (A 17 on an S16) does not exist: the pre-flight REFUSES it,\n"
    "naming the box and its size.\n"
    "\n"
    "plan.json is never touched: only a build writes it, and a full apply warns\n"
    "before it replaces changes that are not in it. To keep a change for good,\n"
    "--promote it: its text goes into instructions.md, the inputs it added into\n"
    "input.csv, and the next rebuild owns them.\n"
    "\n"
    "Each run prints how long it took: the desk read and the model call. A preview\n"
    "compiles the change; a --confirm run compiles it again unless given\n"
    "--change-set, so save the one you reviewed with --save-change-set. --state FILE\n"
    "reviews offline against a saved capture. Exit 2 means it ran and found\n"
    "problems: a refused change (a reference, field or value the plan cannot take),\n"
    "a channel with no free strip, a pre-flight refusal, a readback mismatch, or an\n"
    "unrelated address that moved.\n"
    "\n"
    "A bus, DCA or mute group the starting plan does not know (a desk Atoo did\n"
    "not set up) is read off the desk when the change names it -- only that\n"
    "object, not a sweep -- and the change is carried out against what the desk\n"
    "holds. A name the desk does not hold either is REFUSED."
)


AMEND_DESCRIPTION = (
    "Change a console from a REBUILT plan -- the same as `atoo patch\n"
    "--amended-plan`, kept under this name so existing scripts keep running.\n"
    "\n"
    "  atoo amend --show ./touringband --amended-plan ./touringband/rebuilt.plan.json --console 192.0.2.16\n"
    "  atoo amend --show ./touringband --amended-plan ./touringband/rebuilt.plan.json --console 192.0.2.16 --confirm\n"
    "\n"
    "The horn section has turned up late in the setup window, the show is already\n"
    "built on the desk and there is a mix on it. `apply` would write the whole plan,\n"
    "every fader included. `amend` reads which strips are free, places only the new\n"
    "channels on them, and writes only those. To type the change in plain English\n"
    "instead of rebuilding, use `atoo patch`.\n"
    "\n"
    "This is a setup and rehearsal tool -- use it before doors, not during the show.\n"
    "Save a console snapshot once the board is patched and a bad amend costs you a\n"
    "reload rather than the rest of your setup time.\n"
    "\n"
    "The same operation covers a vocalist who has left and a set of delay speakers\n"
    "dropped from the rider. A channel the rebuild DROPPED is RETURNED TO FREE --\n"
    "unpatched (OFF, as a full apply leaves a strip the plan does not use, with an\n"
    "INFO), left unmuted, its fader at -inf, and its name, color and icon cleared on the strip\n"
    "and on the source socket -- only where the desk still reads as the strip your\n"
    "plan built: a strip somebody has renamed, repatched or named on its SOURCE\n"
    "socket since is reported and left exactly as it is, and so is one that did not\n"
    "answer. A change to a strip that is still in the plan and still running is\n"
    "reported and never written -- a full build is how one of those changes.\n"
    "\n"
    "Four stages, and the first three change nothing:\n"
    "  1. read the desk -- about 200 addresses, not audit's full sweep: a name, a\n"
    "     link-to-source flag and an input patch per strip, plus the name of every\n"
    "     socket a strip is patched to, which on a WING is where a name somebody\n"
    "     typed by hand actually lives. A strip that does not answer counts as\n"
    "     OCCUPIED, and so does one whose SOURCE carries somebody's name.\n"
    "  2. work out the delta against the plan on the desk, placing new channels on\n"
    "     free strips, skipping occupied ones and never renumbering a running one.\n"
    "  3. show what will be written AND what will not -- the target filter, not a\n"
    "     fader flag, is what keeps the running show still.\n"
    "  4. with --confirm, write the new strips and clear the dropped ones, read every\n"
    "     unrelated address before and after to prove none of them moved, and\n"
    "     journal the run with the scope it was allowed.\n"
    "\n"
    "Before step 4 -- and in the preview -- amend runs apply's pre-flight: the amended\n"
    "plan is verified against the desk's model (errors refuse, warnings do not;\n"
    "--skip-verify skips this, as on apply), and every socket the amend WRITES is\n"
    "checked against the desk's panel. A socket the desk does not have (LCL 20 on a\n"
    "full-size WING) is REFUSED, --skip-verify or not.\n"
    "\n"
    "plan.json is NOT replaced: only a build writes it.\n"
    "What is on the desk is recorded in that desk's journal entry, which the next\n"
    "amend or patch of the desk compares against -- so amending again from the same\n"
    "rebuild still finds nothing to add. `atoo undo` takes the amend off again.\n"
    "\n"
    "--state FILE reviews the whole thing offline against a saved capture, contacting\n"
    "no console at all. Exit 2 means it ran and found problems: a channel that could\n"
    "not be placed, a strip the rebuild tried to renumber, a pre-flight refusal, a\n"
    "readback mismatch, or an unrelated address that moved."
)


def _add_apply_arguments(ap: argparse.ArgumentParser) -> None:
    _add_show_argument(ap)
    _add_console_model_argument(ap)
    # Not `required=True` any more: --show DIR supplies it from the bundle.
    # apply_cmd checks for it after bundle resolution and gives the
    # same "you must say which plan" error argparse used to.
    ap.add_argument("--plan", default=None, help="A plan JSON produced by `atoo build`. Required unless --show supplies it.")
    ap.add_argument(
        "--input", help="The input list the plan was built from. Optional, but without it "
                        "the checks that need it are skipped: that every input became a "
                        "channel, that no channel was invented, and that phantom power is "
                        "safe for the microphones in use.")
    _add_presets_argument(ap)
    ap.add_argument(
        "--skip-verify", action="store_true",
        help="Apply the plan without verifying it against the console's limits first. "
             "Verification runs before the console is contacted; skipping it means an "
             "impossible plan reaches real hardware.")
    # Not `required=True` any more: ATOO_CONSOLE or the
    # config file may supply it. `apply_cmd` checks after resolution and
    # gives an error naming all three ways, which argparse could not.
    ap.add_argument("--console", default=None, help=CONSOLE_FLAG_HELP)
    # `default=None`, not 2223/1.0: argparse cannot tell "you typed 2223"
    # from "you typed nothing", and `_resolve_console_settings` needs to,
    # so the built-in default moved there. The help text is
    # unchanged because what a user gets is unchanged.
    ap.add_argument("--port", type=int, default=None, help="Console OSC port (default: 2223)")
    ap.add_argument("--timeout", type=float, default=None, help="Per-request timeout in seconds (default: 1.0)")
    ap.add_argument(
        "--confirm", action="store_true",
        help="Actually write to the console. Without this, apply is a preview that changes "
             "nothing.",
    )
    ap.add_argument(
        "--journal", default=None,
        help="Where to record every write with its prior value, enough to reverse this apply. "
             "Defaults, when --confirm is given, to a new timestamped entry in "
             "the bundle's journals/ directory, or to <plan>.apply-journal.json without "
             "--show. With --show, a confirmed run is added to the bundle's journals/ stack "
             "whatever this says, so `atoo undo --show DIR` can walk the show back one "
             "step at a time.",
    )
    ap.add_argument(
        "--raw-log", default=None,
        help="Append every raw OSC request/reply (address, typetag, args, hex bytes) to this "
             "file. Useful when a reported mismatch needs "
             "the literal reply bytes to diagnose, not just the extracted value the journal "
             "records.",
    )
    ap.add_argument(
        "--no-init", action="store_true",
        help="Do not reset the desk to its initialized state before writing the plan "
             "-- for a desk already initialized by hand. By default a full "
             "apply reads the desk and writes back, from the model's initialized capture, "
             "every setting that differs and that the plan does not set itself.")
    ap.add_argument(
        "--clean-output-sockets", default=None,
        help="Disconnect (`.grp = OFF`) any physical output socket in the given "
             "group(s) that no bus or output in the plan routes anywhere to, instead of "
             "leaving whatever was already patched there (e.g. from an earlier apply, a "
             "different show, or manual patching). A full apply already does this by "
             "default for the desk's own panel outputs; this reaches the groups beyond "
             "them, such as a stage box's. "
             "Same 'no confirmed default' syntax as `atoo audit`'s --output-sockets: "
             "'LCL=24,A=48'. A socket ALREADY undeclared and already disconnected costs one "
             "read and nothing else. Shown in the dry-run preview like every other write -- "
             "`--confirm` is what actually arms it, same as the rest of apply.",
    )
    ap.add_argument(
        "--no-progress", action="store_true",
        help=NO_PROGRESS_WRITE_HELP)


def _add_undo_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "journal_file", metavar="JOURNAL", nargs="?", default=None,
        help="The journal to reverse -- the file `atoo apply --confirm` or "
             "`atoo patch --confirm` wrote -- one of the timestamped entries in a show "
             "bundle's journals/ directory, or <plan>.apply-journal.json without a bundle. "
             "Reversing an undo's own journal is the redo. Optional: with --show and no "
             "JOURNAL, undo reverses the newest write recorded in that bundle.")
    _add_show_argument(ap)
    ap.add_argument("--console", default=None, help=CONSOLE_FLAG_HELP)
    ap.add_argument("--port", type=int, default=None, help="Console OSC port (default: 2223)")
    ap.add_argument("--timeout", type=float, default=None, help="Per-request timeout in seconds (default: 1.0)")
    ap.add_argument(
        "--state", default=None,
        help="A JSON object of address -> value (the same shape `atoo audit --state` "
             "takes) to preview the reversal against, instead of contacting a console. "
             "Preview only: a value read from a file says nothing about what the desk holds "
             "now, which is the whole question the 'still ours' guard asks, so --state can "
             "never be combined with --confirm.")
    ap.add_argument(
        "--only", default=None, metavar="SELECTORS",
        help="Reverse only part of the run: a comma-separated list of strip labels "
             "(ch:21, aux:3, bus:4, main:1, mtx:2, dca:7 -- the same spelling amend's "
             "--allow-strip and the journal's own scope use) or address prefixes "
             "(/io/in/A/5). Everything else in the journal is left exactly as it is. "
             "Without this, an amend journal defaults to the scope the amend itself was "
             "held to, and any other journal to all of it.")
    ap.add_argument(
        "--confirm", action="store_true",
        help="Actually write the prior values back. Without this, undo is a preview that "
             "changes nothing and shows, per address, what it would restore and what it "
             "would refuse.")
    ap.add_argument(
        "--out-of-order", action="store_true",
        help="Reverse a journal that is NOT the newest entry in the bundle's stack. "
             "Refused by default: undo's guard is per address and cannot see a later "
             "run, so reversing an apply that an amend was built on top of would pass "
             "every address and take the show off the desk under the amend. This says "
             "you know what is above it and want it reversed anyway.")
    ap.add_argument(
        "--journal", dest="undo_journal", default=None, metavar="PATH",
        help="Where to record this undo's own writes. Defaults to a new timestamped "
             "entry in the bundle's journals/ directory when reversing one of those, "
             "and to <JOURNAL stem>.undo.json beside the journal otherwise -- never "
             "over it, because overwriting the evidence destroys the only thing that "
             "could reverse the undo. It is an ordinary apply journal, so `atoo "
             "undo` on it is the redo.")
    ap.add_argument(
        "--raw-log", default=None,
        help="Append every raw OSC request/reply to this file, exactly as `apply --raw-log` "
             "does.")
    ap.add_argument(
        "--result-json", default=None, metavar="FILE",
        help="Write the run as JSON to FILE, for a page to draw: one row per address (the "
             "strip, the value the journalled run wrote, the value on the desk now, the "
             "value an undo puts back, and whether it goes back, is already back, has "
             "changed since, or has no earlier value), the counts, and one word for the "
             "whole run. Written for a preview and for a confirmed run alike.")
    ap.add_argument(
        "--no-progress", action="store_true",
        help=NO_PROGRESS_WRITE_HELP)


def _add_compare_arguments(ap: argparse.ArgumentParser) -> None:
    _add_show_argument(ap)
    # Not `required=True` any more: --show DIR supplies it from the bundle
    # (the gap -- `verify` and `compare` were the two commands the
    # original slice left out, which made the bundle a half-measure for the
    # loop that runs most often).
    ap.add_argument("--plan", default=None,
                    help="The plan to compare against. Required unless --show supplies it.")
    ap.add_argument("--snapshot", required=True,
                    help="A .snap show file saved on the console and copied off it "
                         "(USB stick or the console's own file browser). There is no "
                         "remote save-and-download; the desk writes it, you fetch it.")


def _add_verify_arguments(ap: argparse.ArgumentParser) -> None:
    _add_show_argument(ap)
    _add_console_model_argument(ap)
    # See `_add_compare_arguments` -- --show DIR supplies all three of
    # these, which is most of the point of a bundle for this command.
    ap.add_argument("--plan", default=None,
                    help="A plan JSON to check. Required unless --show supplies it.")
    ap.add_argument(
        "--input", help="The input list the plan was built from. Without it, the checks "
                        "that need it are skipped: that every input became a channel, that "
                        "no channel was invented, and that phantom power is safe.")
    _add_presets_argument(ap)


CONSOLE_FLAG_HELP = (
    "Console IP address. Falls back to $ATOO_CONSOLE, then to a "
    "[console] default in ~/.atoo.config -- a run that uses either prints "
    "where the address came from, on stderr."
)


def _add_console_read_arguments(ap: argparse.ArgumentParser) -> None:
    """Shared between `audit` and `watch`'s live-console path: everything
    `atoo.audit.read_console_state` needs to know how much of the
    console to read. Not shared with `apply` -- that reads only the
    addresses one specific plan touches, not a console-wide sweep."""
    # `default=None`, not 2223/1.0: argparse cannot tell "you typed 2223"
    # from "you typed nothing", and `_resolve_console_settings` needs to,
    # so the built-in default moved there. The help text is
    # unchanged because what a user gets is unchanged.
    ap.add_argument("--port", type=int, default=None, help="Console OSC port (default: 2223)")
    ap.add_argument("--timeout", type=float, default=None, help="Per-request timeout in seconds (default: 1.0)")
    ap.add_argument("--channels", type=int, default=40, help="Channel strips to read (default: 40, WING Compact)")
    ap.add_argument("--aux", type=int, default=8, help="Aux strips to read (default: 8, WING Compact)")
    ap.add_argument("--buses", type=int, default=16, help="Busses to read (default: 16, WING Compact)")
    ap.add_argument("--mains", type=int, default=4, help="Mains to read (default: 4, WING Compact)")
    ap.add_argument("--matrices", type=int, default=8, help="Matrices to read (default: 8, WING Compact)")
    ap.add_argument("--dcas", type=int, default=16, help="DCAs to read (default: 16, WING Compact)")
    ap.add_argument("--mute-groups", type=int, default=8, help="Mute groups to read (default: 8, WING Compact)")
    ap.add_argument(
        "--input-sockets", default=None,
        help="Physical input socket counts to read phantom power from, e.g. 'LCL=20,A=48'. "
             "Omit and Atoo reads the panel of whichever model the desk says it is, "
             "plus every group the --plan patches from. Pass this to override that.",
    )
    ap.add_argument(
        "--output-sockets", default=None,
        help="Physical output socket counts to read patch state from, e.g. 'LCL=16'. "
             "Omit and Atoo reads the panel of whichever model the desk says it is, "
             "plus every group the --plan patches to. Pass this for a stage box or a "
             "card the plan does not mention. The report says which sockets it read.",
    )
    ap.add_argument(
        "--raw-log", default=None, metavar="FILE",
        help="Append every raw OSC request and reply to FILE, exactly as `apply --raw-log` "
             "does -- the literal bytes, not the values made of them. For a read that is "
             "slow or comes back short: the progress line says how many addresses went "
             "unanswered, and this says which. Written line by line, so a read stopped "
             "with Ctrl-C still leaves a complete log. Live reads only.",
    )
    ap.add_argument(
        "--no-progress", action="store_true",
        help="Do not print the progress line while reading the console. A live read is "
             "a few hundred requests (thousands with --per-leaf) and normally reports "
             "'read 120/323 (37%%) 2s -- /io/in/USR/44 (node)' on stderr as it goes, plus how many addresses went "
             "unanswered at the end. Without it a slow read looks like a hung one, so "
             "pass this only when something downstream is parsing stderr.",
    )
    # The closing evidence, and the bar `--bulk-read`'s own help
    # text set ("off by default until one confirming run"): A11 on
    # 2026-09-24 read a Compact both ways, 5,860 values each, and found 0
    # only per-leaf, 0 only by dump, 0 differing -- 4.8s against 118.8s.
    # So the node-dump read is what a live read does, and `--per-leaf` is
    # the way back. The two are a mutually exclusive group because
    # together they contradict each other, and a script that says both
    # has a bug worth hearing about.
    read_path = ap.add_mutually_exclusive_group()
    read_path.add_argument(
        "--per-leaf", action="store_true",
        help="Read the console one request per leaf -- about 6,100 requests and two "
             "minutes on a WING Compact -- instead of the default, which fetches each "
             "object whole with the protocol's node-dump query (`,s *`): "
             "about 320 requests and five seconds. The two paths were compared address "
             "by address on a real WING Compact and agreed on all 5,860 values; "
             "the 304 insert and FX-slot leaves added since have not yet been "
             "compared on hardware. This "
             "is the diagnostic path: use it if a read looks wrong and you want to rule "
             "the node dump out, or if a desk misbehaves when asked for whole nodes. "
             "Names and tags are read one at a time either way, and so is any leaf a "
             "dump does not carry.",
    )
    read_path.add_argument(
        "--bulk-read", action="store_true",
        help="Accepted and ignored: reading by node dump is now the default. Kept so "
             "scripts written when it was opt-in still run. See --per-leaf.",
    )


def _add_ping_arguments(ap: argparse.ArgumentParser) -> None:
    """Deliberately NOT `_add_console_read_arguments` -- that
    helper's whole content is "how much of the console to read", and the
    point of this command is that the answer is `nothing`."""
    ap.add_argument("--console", default=None, help=CONSOLE_FLAG_HELP)
    # See `_add_console_read_arguments` on why these default to None.
    ap.add_argument("--port", type=int, default=None, help="Console OSC port (default: 2223)")
    ap.add_argument("--timeout", type=float, default=None,
                    help="Per-request timeout in seconds (default: 1.0)")


def _add_capture_arguments(ap: argparse.ArgumentParser) -> None:
    """One source, a live desk or a `.snap`; where the show goes."""
    ap.add_argument("--console", default=None, help=CONSOLE_FLAG_HELP)
    ap.add_argument("--snap", default=None, metavar="FILE",
                    help="Capture a .snap show file saved on the console instead of a live "
                         "desk. Needs --console-model: a .snap does not say which WING wrote it.")
    ap.add_argument("--console-model", choices=sorted(facts.CONSOLE_MODELS), default=None,
                    help="Which WING the --snap came from. A live desk states its own model.")
    ap.add_argument("--dir", default=None, metavar="DIR",
                    help="The folder to make the show in (default: your Atoo folder, "
                         "~/Documents/Atoo unless ~/.atoo.config's [workspace] says otherwise).")
    ap.add_argument("--name", default=None,
                    help="The show folder's name (default: the .snap's name, or the desk's "
                         "model and today's date). A name already taken gets -2, -3.")
    # See `_add_console_read_arguments` on why these default to None.
    ap.add_argument("--port", type=int, default=None, help="Console OSC port (default: 2223)")
    ap.add_argument("--timeout", type=float, default=None,
                    help="Per-request timeout in seconds (default: 1.0)")
    ap.add_argument("--no-progress", action="store_true",
                    help="Do not print the progress line while reading the console.")


def _add_audit_arguments(ap: argparse.ArgumentParser) -> None:
    _add_show_argument(ap)
    # Not `required=True` any more -- the environment or the
    # config file can supply --console, which argparse cannot see. The
    # group still enforces that --console and --state are not BOTH given;
    # `audit_cmd` enforces that one of them ends up resolved.
    source_group = ap.add_mutually_exclusive_group()
    source_group.add_argument(
        "--console", default=None,
        help="Console IP address -- read its live state and audit that. "
             + CONSOLE_FLAG_HELP.split(".", 1)[1].strip(),
    )
    source_group.add_argument(
        "--state", default=None,
        help="A JSON object of address -> value (an offline capture, or a hand-built demo -- "
             "try ~/Documents/Atoo/audit-demo/audit_demo_state.json, which `atoo init` copies) -- audit that instead of a live console. "
             "Lets a novice operator try this with no console attached at all.",
    )
    _add_console_read_arguments(ap)
    ap.add_argument(
        "--dump-state", default=None, metavar="FILE",
        help="After a live read, save everything read to FILE as the same address -> value "
             "JSON --state takes, so this exact reading can be audited again offline -- "
             "with a different --plan, after a fix to a rule, or by someone who was not at "
             "the desk. Written before the audit runs. Live reads only: refused with --state. "
             "It also records what is on each AES50 port (/$stat/A/dev, B, C; empty when nothing is "
             "connected), so an offline `patch` can check a socket against the stage box's size. "
             "The file does not record the console model; replay it with --plan to supply one.",
    )
    ap.add_argument(
        "--plan", default=None,
        help="A plan JSON file (the same shape `atoo build` produces). Independent of "
             "--console/--state -- it works on top of whichever live state source was already "
             "selected -- and it changes the report two ways. It ADDS conventions-diff "
             "findings, comparing live state against what the plan says it should be (mute, fader "
             "level, DCA/mute-group membership, patch, bus sends, direct-to-Main routes, and "
             "the trim, balance, invert, head-amp gain, high-pass, hi-cut, tilt and EQ it states; "
             "the compressor is not compared). And "
             "it WITHHOLDS structural findings the plan is not about: one about a strip or bus the "
             "plan never mentions, unless the rule is one that matters on any desk (48V on an "
             "unpatched socket, a mix that reaches no loudspeaker, a routed strip sitting silent), "
             "and any finding about a parameter the plan itself states, since the conventions diff "
             "already checks that against what you asked for. Nothing is dropped silently: the "
             "count and the reason are reported as S001. Without --plan, nothing is withheld.",
    )
    ap.add_argument(
        "--trace-from", default=None,
        help="Signal-graph node to trace from, e.g. 'input:LCL:3' or 'strip:/ch/12'.",
    )
    ap.add_argument(
        "--trace-to", default=None,
        help="Signal-graph node to trace to, e.g. 'output:LCL:1' or 'main:1'.",
    )


def _positive_int(text: str) -> int:
    """An argparse type: a whole number of 1 or more."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"{value} is less than 1")
    return value


def _add_watch_arguments(ap: argparse.ArgumentParser) -> None:
    _add_show_argument(ap)
    # See `_add_audit_arguments` -- same relaxation, same reason.
    source_group = ap.add_mutually_exclusive_group()
    source_group.add_argument(
        "--console", default=None,
        help="Console IP address -- poll its live state and audit each read. "
             + CONSOLE_FLAG_HELP.split(".", 1)[1].strip(),
    )
    source_group.add_argument(
        "--state-sequence", default=None,
        help="Comma-separated JSON state files, played in order and then repeated -- an offline "
             "demo of an operator making changes between polls, with no console attached. "
             "Try ~/Documents/Atoo/audit-demo/audit_demo_state_before.json and audit_demo_state.json, which `atoo init` copies.",
    )
    _add_console_read_arguments(ap)
    ap.add_argument(
        "--interval", type=float, default=2.0,
        help="Seconds between reads (default: 2.0). Read-only polling -- WING's OSC offers only "
             "a single, network-wide event subscription that expires every 10 seconds, so "
             "nothing here pushes. Note this is the gap BETWEEN reads, not their period: one "
             "read of a live console is 6,197 addresses, fetched by node dump in about 320 "
             "requests and ~5 seconds on a WING Compact, so at the default a pass starts "
             "every seven seconds or so. With --per-leaf a read is about two minutes and an "
             "interval this short changes almost nothing.",
    )
    ap.add_argument(
        "--count", type=int, default=None,
        help="Stop after this many reads. Default: run until Ctrl-C for --console, or once through "
             "the list for --state-sequence. Against a live console budget ~5s per read plus "
             "--interval between them: --count 8 is about a minute. With --per-leaf it is "
             "~2 minutes per read, so --count 8 is about 17 minutes. watch prints its "
             "own estimate before the first read, and each read reports its progress and "
             "how many addresses went unanswered.",
    )
    ap.add_argument(
        "--name-refresh", type=_positive_int, default=None, metavar="N",
        help="Read strip, bus, DCA, mute-group and input-socket names on the first read and "
             "then every N reads, instead of every read. A node dump cannot carry "
             "a name, so on a WING Compact names are 88 of a read's ~320 requests. Default: 5 "
             "-- about every 30 seconds at the default --interval -- or 1 with --per-leaf. 1 "
             "reads names every time. Between refreshes each read carries the last names "
             "read, so every rule still runs; a rename shows up at the next refresh, and "
             "the findings say so at INFO (W001).",
    )
    ap.add_argument(
        "--findings-log", default=None, metavar="FILE",
        help="Save what the watch finds to FILE as it runs (appended, flushed every pass, so "
             "Ctrl-C or a crash loses nothing): a header (atoo version and where it runs from, "
             "the console address and what the desk answered, the plan, the conditions, the "
             "start time), one JSON line per pass (findings standing, what appeared and what "
             "cleared, the meters, anything the desk did not answer) and a footer on a clean "
             "stop. Read-only: nothing is written to the desk, and no key is ever in it.",
    )
    ap.add_argument(
        "--record-meters", default=None, metavar="FILE",
        help="With --console: write every meter packet the console sends to FILE as it comes, "
             "with its time (JSON lines), so the clips a watch reported can be replayed and "
             "checked later exactly as the desk sent them. Read-only, like the rest of watch.",
    )
    ap.add_argument(
        "--watch-conditions", default=None,
        help="Path to a JSON file of operator-authored watch conditions -- alerts on top "
             "of the built-in structural rules, e.g. \"the crowd mic must never be unmuted.\" "
             "Optional; without it, only the built-in rules run. See "
             "the watch subcommand's own --help text for the file's shape.",
    )
    ap.add_argument(
        "--virtual-soundcheck", action="store_true",
        help="Say that a virtual soundcheck is under way, so channels on their alternate "
             "input (C004) and the global alternate switch (C005) are reported at INFO "
             "instead of as warnings. Every strip on its alternate is still named, and an "
             "INFO (W003) says the switch is on. It is for this run only; the next `atoo "
             "watch` starts with it off, and with it off a channel still on its alternate "
             "is a warning.",
    )


LESSONS_DESCRIPTION = (
    "Mine a show bundle's builds for what keeps being unclear -- recurring build-log\n"
    "notes, critic findings, conventions-audit entries, inferred markers, plan notes\n"
    "and verify warnings -- grouped by topic, most-recurring first. It opens with\n"
    "where each build's thinking went: every role's share of time spent on\n"
    "mechanical work, conventions questions, the plan format itself, writing the\n"
    "reply, and judgment. Read-only, no model call.\n"
    "\n"
    "  atoo lessons --show my-show\n"
    "  atoo lessons --show my-show --last 2  # only the 2 newest\n"
    "                                              # builds/ files\n"
    "  atoo lessons --show my-show --git 5   # + the last 5 committed\n"
    "                                              # versions of plan.json\n"
    "  atoo lessons --show my-show --json\n"
    "\n"
    "Every build writes its own thinking-summary lines (never sent back to a\n"
    "model) to <bundle>/builds/<timestamp>.json -- builds/\n"
    "keeps the newest 5 -- and this command reads every one of those files\n"
    "(newest first), plus the current\n"
    "plan's own findings, and -- with --git N, for an older plan that still\n"
    "carries its log inline -- committed versions of plan.json itself. A topic\n"
    "that shows up under one build is worth a look; one that recurs across builds\n"
    "is the kind of question that belongs in conventions.md or a show's\n"
    "instructions.md, once answered, so no future build has to work it out again.\n"
)


def _add_lessons_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--show", required=True, metavar="DIR",
                    help="The show bundle to mine -- its current plan.json is always read.")
    ap.add_argument("--last", type=int, default=0, metavar="N",
                    help="Only the N newest builds/ files (default: all of them -- "
                         "builds/ keeps the newest 5, so at most 5 are ever read).")
    ap.add_argument("--git", type=int, default=0, metavar="N",
                    help="Also read the last N committed versions of plan.json from git "
                         "history, if the bundle is inside a git repository -- otherwise "
                         "this notes it and reads the current plan only. Useful for an older "
                         "plan that still carries its build log inline.")
    ap.add_argument("--json", action="store_true",
                    help="Machine-readable output instead of the plain-text report.")


def lessons_cmd(args: argparse.Namespace) -> int:
    """`atoo lessons` -- a read-only report over one bundle's `plan.json`, every build's
    own log file (`builds/`), and its findings,
    optionally alongside its git history of `plan.json` itself.

    Writes nothing, and makes no model call: everything it reports was
    already written down by an earlier build.
    """
    try:
        report = lessons.gather(args.show, git_n=args.git, last_n=args.last)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"couldn't read {args.show}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(lessons.render_json(report))
    else:
        print(lessons.render_text(report), end="")
    return 0


PRESETS_DESCRIPTION = (
    "List a preset library: what each preset is CALLED, which file it came from, and\n"
    "anything wrong with it.\n"
    "\n"
    "  atoo presets --presets starter/presets\n"
    "  atoo presets                      # uses the [presets] default in ~/.atoo.config\n"
    "\n"
    "A preset's name lives in the `info_text` field INSIDE the .chn file -- it is the\n"
    "name the engineer gave it on the desk, and it is what a plan and a conventions\n"
    "file match on. It need not be the filename, nor the channel's name: the\n"
    "starter's `Kick In.chn` holds `Kick In`, and the Kick channel that uses it\n"
    "stays called Kick; rename the file and the preset keeps its name. So `ls` cannot answer \"what is my library called\", and\n"
    "this can -- it opens every file to do it. Bus presets (.bus) are listed after\n"
    "the channel presets, with the effect each one inserts: a bus names one by the\n"
    "same `info_text` name.\n"
    "\n"
    "It also reports two things that are otherwise invisible until some plan happens\n"
    "to name the preset carrying them: a preset with a field this tool does not\n"
    "recognize or a sidechain keyed off another channel, and two files claiming the\n"
    "same name. Neither stops a build -- the newest of two duplicates wins -- so this\n"
    "exits 0 either way. Nothing is read from a console and nothing is written.\n"
    "\n"
    "  atoo presets --presets starter/presets --expand plan.json\n"
    "\n"
    "--expand does what `build` does to a plan's named presets, without a model call:\n"
    "each preset's processing values are put INTO the plan, keyed by the address each\n"
    "is written to, so the plan says exactly what `apply` will write. Where the plan\n"
    "states a value of its own at the same address (a high-pass, an EQ band), the\n"
    "plan wins, with an INFO. Processing only -- a preset never writes sends, main\n"
    "routing, fader, mute, the input patch or tags. A bus preset also loads the\n"
    "effect it inserts into an FX engine, chosen by code (reverbs and delays on 1-8,\n"
    "the preset's own engine when it is free) and announced. Preset writes are read\n"
    "back like every other write; they have not yet been confirmed on a desk."
)


CAPTURE_DESCRIPTION = (
    "Capture a desk you didn't build as a show you can watch and edit.\n"
    "\n"
    "  atoo capture --console 192.0.2.148\n"
    "  atoo capture --snap CCC-20261024.snap --console-model wing-full\n"
    "\n"
    "Reads the desk, or a .snap saved on it, and makes a show folder in your Atoo\n"
    "folder: input.csv (one row per input, with its channel, DCAs and mute groups),\n"
    "busses.csv (one row per bus, Main and Matrix: what feeds it, where it goes, its\n"
    "effects), outputs.csv (one row per output socket the desk patches: a split, a\n"
    "recording feed, a bus's side), user.csv (only when the desk uses one: each USR\n"
    "slot a channel or an output reads, and what it takes), plan.json (the desk as\n"
    "it is: patch, routing, membership and widths, not faders or EQ), an empty\n"
    "watch.json, and the snapshot under captures/.\n"
    "\n"
    "No model, and nothing is written to the desk. Every name is written in: a\n"
    "channel with no name of its own takes its source's. What the desk does not\n"
    "state is decided and said, at INFO: a category from the channel's first DCA,\n"
    "a type from its source, the role fx for a bus whose effects are all reverbs,\n"
    "delays or modulation set fully wet. Every send is in the plan, on its source,\n"
    "with its tap: a channel sent to a Matrix, a bus sent to a bus. Every effect\n"
    "inserted on a channel, bus, Main or Matrix is in the plan with its engine's\n"
    "settings (from a live desk, one more request per engine after the desk's read),\n"
    "so apply loads it back. What the plan cannot hold yet (a GRP-mode tap) stays in\n"
    "the sheets and the snapshot, and is listed too.\n"
    "\n"
    "Then watch it with the show: atoo watch --show DIR --console ADDRESS, and edit\n"
    "its sheets in `atoo ui`, Build step 04, whose Save updates the plan. The UI's\n"
    "New show... > From a desk does the same as this command."
)

PING_DESCRIPTION = (
    "Check that a console is reachable, and say which one answered.\n"
    "\n"
    "  atoo ping --console 203.0.113.50\n"
    "\n"
    "One OSC round trip -- the same `/?` identity request every online command opens\n"
    "with -- and nothing else. No strip sweep, no writes, nothing touched, so this is\n"
    "safe to run in the middle of a show. Exits 0 when the desk answers, 1 when it\n"
    "does not.\n"
    "\n"
    "It also prints the model the desk states for itself, which is what `atoo\n"
    "apply` cross-checks a plan against before writing anything -- worth seeing\n"
    "before an apply rather than during one. A model it does not recognize is\n"
    "printed as the desk spelled it: that is the string to report."
)


AUDIT_DESCRIPTION = (
    "Audit a console's live state against deterministic structural rules, and\n"
    "optionally trace a signal path across it. Every finding names its rule\n"
    "by an ID that does not change when the wording does.\n"
    "\n"
    "  atoo audit --console 203.0.113.50\n"
    "  atoo audit --state ~/Documents/Atoo/audit-demo/audit_demo_state.json\n"
    "  atoo audit --state ~/Documents/Atoo/audit-demo/audit_demo_state.json --trace-from input:LCL:3 --trace-to output:LCL:1\n"
    "  atoo audit --state ~/Documents/Atoo/audit-demo/audit_demo_state.json --plan ~/Documents/Atoo/audit-demo/audit_demo_plan.json\n"
    "\n"
    "Read-only either way -- nothing here writes to a console. Every finding cites the\n"
    "specific rule it violated (its ID), never an inferred channel type: this audit works\n"
    "from confirmed routing/patch/mute/fader facts only, the same address scheme `apply`\n"
    "writes to, and never guesses what a channel is from its name.\n"
    "\n"
    "--state takes a JSON object of OSC address -> value, the same shape a live read\n"
    "produces -- try it with no console attached at all via the demo state `atoo init`\n"
    "copies into your working folder, ~/Documents/Atoo/audit-demo/audit_demo_state.json\n"
    "(run `atoo init` first if it is not there; if you chose another --dir, use that folder).\n"
    "--dump-state FILE writes that shape: a live read saved, to be audited again offline.\n"
    "\n"
    "  atoo audit --console 203.0.113.50 --dump-state tonight.state.json\n"
    "  atoo audit --state tonight.state.json --plan my_show_plan.json\n"
    "\n"
    "--plan adds the conventions-diff audit: compare live state against what a\n"
    "plan (a `atoo build` JSON output) says a channel's mute, fader level,\n"
    "DCA/mute-group membership, patch, bus sends, direct-to-Main routes, and the\n"
    "trim/balance/invert/head-amp-gain, high-pass/hi-cut/tilt and EQ a channel states should\n"
    "be, so a finding can cite the plan's own provenance text instead of just a structural\n"
    "fact. A filter or an EQ band is compared within 2%, the desk holding the nearest step of\n"
    "the control; a bus's, Main's and Matrix's EQ and a channel's PreSend EQ are diffed\n"
    "the same way. The compressor is not diffed.\n"
    "--plan also flags (CV009) any\n"
    "physical output socket --output-sockets read that's patched to something the plan\n"
    "never routes there at all -- catches stray/leftover routing an apply run never wrote,\n"
    "same finding `apply --clean-output-sockets` can act on. --plan is independent of\n"
    "--console/--state: it works on top of whichever live state source you picked.\n"
    "\n"
    "--plan also makes the report SHORTER, not just longer. A finding\n"
    "about a strip, bus or socket the plan never mentions is withheld unless its rule is one\n"
    "that matters on any desk, and any finding about a parameter the plan itself states is\n"
    "withheld too, because the conventions diff already checks that parameter against what\n"
    "you asked for. Hazards are never withheld for being outside the plan: 48V on an\n"
    "unpatched socket, a mix reaching no loudspeaker, a routed strip sitting silent. Nothing\n"
    "goes quietly -- S001 at the end of the report counts what was withheld and why, and\n"
    "running without --plan shows everything the rules produced."
)


WATCH_DESCRIPTION = (
    "Continuously re-run the audit against a console and alert on what CHANGED\n"
    "since the last read -- not the same finding restated every\n"
    "poll, only a finding that just started applying, or just stopped.\n"
    "\n"
    "  atoo watch --console 203.0.113.50\n"
    "  atoo watch --console 203.0.113.50 --interval 5\n"
    "  atoo watch --state-sequence ~/Documents/Atoo/audit-demo/audit_demo_state_before.json,~/Documents/Atoo/audit-demo/audit_demo_state.json\n"
    "\n"
    "Polling, not push: WING's OSC offers one event subscription for the whole network, and\n"
    "it dies after 10 seconds unless renewed, so this reads the same address set `audit` does\n"
    "on an interval and diffs. Every read says how far through it is and how many addresses\n"
    "went unanswered, so a slow pass can be told from a hung one. Session-based\n"
    "and read-only -- nothing here writes to a console, and it stops the moment you\n"
    "stop it (Ctrl-C); there is no background service and nothing persists between runs.\n"
    "\n"
    "Names (strips, buses, DCAs, mute groups, input sockets) are read on the first read and\n"
    "every --name-refresh reads after it (default 5, about every 30s; 1 with --per-leaf), not\n"
    "every read: a node dump cannot carry a name, so they are over a quarter of a read's requests.\n"
    "Between refreshes the rules see the last names read, and a rename shows up at the next\n"
    "refresh -- the findings say so at INFO (W001). --name-refresh 1 reads them every time.\n"
    "\n"
    "With --console it also listens to the console's meters (a read-only native connection on\n"
    "port 2222, one of its 24 client slots) and raises L003 Clipped, an ERROR, for a channel,\n"
    "aux, bus, main or matrix that clips (-0.5 dBFS) for 60 seconds after its last clip. A clip\n"
    "ends once the strip has been below -0.5 dBFS for 200 ms. If the connection cannot be had, or\n"
    "the meter data stops, it notes it at INFO (W002) and carries on.\n"
    "\n"
    "A channel on its alternate input (C004) and the global alternate switch (C005) are\n"
    "warnings, since a show never starts on them. During a virtual soundcheck they are\n"
    "right: --virtual-soundcheck reports them at INFO instead (each strip still named, and W003\n"
    "saying the switch is on) for this run only. Leave it off when the show is live.\n"
    "\n"
    "The first read is reported as a baseline, not an alert -- whatever's already wrong when\n"
    "you start watching isn't a change. --state-sequence plays a fixed list of JSON captures\n"
    "in order (then repeats) instead of a live console, so a novice operator can see an alert\n"
    "fire with no hardware at all.\n"
    "\n"
    "With --show, the bundle's plan adds drift checks, each a WARNING (CV018 an\n"
    "INFO) that clears when the desk is put back: a channel whose every planned send and Main route is off\n"
    "(CV016), a planned send switched off or flipped between pre and post (CV006), a\n"
    "channel's Main route off that the plan lists or on that it does not (CV007), a send\n"
    "to a Matrix, or a bus's route to a Main, that is on and the plan does not have\n"
    "(CV018), a channel, bus, DCA, Main or Matrix muted that the plan leaves unmuted\n"
    "(CV017), 48V that is on where the plan has none or off where it has it (CV019), a bus that\n"
    "is mono or stereo where the plan states the other (CV020), talkback that reaches\n"
    "some destinations but not a monitor mix the plan builds (CV021; CV022 is the INFO\n"
    "naming the busses it took for monitor mixes), and an\n"
    "effect the plan inserts bypassed or changed (CV015). The plan's output\n"
    "sockets are read too. With or without a plan, so are the outputs of any AES50\n"
    "stage box, and of any module or card, the desk reports.\n"
    "\n"
    "--watch-conditions PATH adds operator-authored alerts on top of the built-in\n"
    "structural rules -- deterministic, structured, no AI in the runtime path. Each\n"
    "condition says when to alert: it fires while it is true. A JSON file of:\n"
    "\n"
    "  { \"version\": 2, \"watch_conditions\": [\n"
    "      { \"id\": \"crowd-mic-muted\",\n"
    "        \"description\": \"Crowd Mic is muted\",\n"
    "        \"channel\": \"Crowd Mic\", \"field\": \"muted\", \"operator\": \"==\",\n"
    "        \"value\": true, \"severity\": \"error\" } ] }\n"
    "\n"
    "  atoo watch --console 203.0.113.50 --watch-conditions my_show.watch.json\n"
    "\n"
    "Fields: \"muted\" (bool), \"fader_db\" (number), \"dca\" and \"mute_group\" (a group NAME,\n"
    "e.g. \"Drums\"; \"not in\" alerts when the strip is not in it, \"in\" when it is) and\n"
    "\"patch\" (a socket written the way an input list's patch column writes one --\n"
    "\"AES50-A 12\", \"LCL 3\", \"AES 1\", \"CRD 64\"; \"!=\" alerts when it is patched anywhere\n"
    "else, \"==\" when it is patched there). Note \"AES 1\" (AES/EBU) and \"AES50-A 1\" are\n"
    "different sockets. A file without \"version\": 2 was written when a condition said\n"
    "what should hold, and is refused with how to convert it.\n"
    "\n"
    "Sends and 48V: \"send_on\" (bool), \"send_db\" (number) and \"send_mode\" (\"pre\", \"post\" or\n"
    "\"group\") are about the channel's send to the bus a \"bus\" key names -- written like\n"
    "\"channel\": a bus's name, \"BUS 5\", \"BUS 5-8\", \"ALL BUS\", \"MTX 3\" or \"MAIN 1\" -- and\n"
    "\"phantom\" (bool) is the 48V on the socket the strip is patched to (and the next, for\n"
    "a stereo source).\n"
    "\n"
    "  { \"id\": \"kick-out-of-drums\", \"description\": \"Kick is not in the Drums DCA\",\n"
    "    \"channel\": \"Kick\", \"field\": \"dca\", \"operator\": \"not in\", \"value\": \"Drums\",\n"
    "    \"severity\": \"warning\" }\n"
    "\n"
    "\"channel\" is a channel's or aux's name, matched case-insensitively; a name matching zero\n"
    "or more than one live channel is skipped for that poll cycle rather than guessed at, and\n"
    "a DCA or mute-group name is resolved the same way. It may instead be a position (\"CH 10\",\n"
    "\"BUS 3\", \"MAIN 1\", \"DCA 14\"), a range (\"DCA 10-16\"), a whole kind (\"ALL AUX\"), or a\n"
    "kind and a name (\"BUS Drums\", \"DCA Vocals\", \"MAIN PA\"). A kind and a name is resolved\n"
    "ONCE, at the first read, to a position -- said at INFO in the baseline -- and that\n"
    "position is what is watched; a rename or move after that is not followed until watch\n"
    "starts again, and a name matching no strip of its kind, or more than one, is a WARNING\n"
    "and is not watched.\n"
    "\n"
    "If --watch-conditions is omitted, a settled house watch-conditions file named in\n"
    "~/.atoo.config's [watch_conditions] section is used instead, mirroring\n"
    "[conventions]'s existing default (see `atoo build --help`); an explicit\n"
    "--watch-conditions always wins over that default."
)


#: The port `atoo ui` serves on unless told otherwise. A name, not a literal in
#: the parser, so a test can move it to a free port instead of needing 8420.
UI_DEFAULT_PORT = 8420


def ui_cmd(args: argparse.Namespace) -> int:
    try:
        show = _open_bundle(args)
        _fill_from_bundle(args, show, "plan", bundle.PLAN)
        _fill_from_bundle(args, show, "watch_conditions", bundle.WATCH_CONDITIONS)
    except bundle.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Imported here, not at module scope, for the same reason apply_cmd
    # keeps atoo.console out of `build`/`--help`'s import path --
    # fastapi/uvicorn are an extra (`.[ui]`), not a
    # dependency of the engine, and shouldn't be required to run a build.
    try:
        import uvicorn
        from atoo.webui import create_app
    except ImportError:
        # The command that fixes this depends on where Atoo is running:
        # `install_info.ui_extra_hint` picks it.
        print(install_info.ui_extra_hint(), file=sys.stderr)
        return 1

    # --plan: the plan Build step 04 shows, loaded up front so a bad
    # path fails fast, before uvicorn ever binds a socket -- same shape as
    # `_open_console`'s failure path for `watch`. Reuses `_load_plan_file`
    # (already prints a ready-to-show stderr message and returns None on
    # a read/parse failure) rather than a second copy of that handling.
    plan = None
    if getattr(args, "plan", None):
        plan = _load_plan_file(args.plan)
        if plan is None:
            return 1

    # --watch-conditions: the Watch page's watch-conditions
    # panel gets a starting path the same way --plan seeds the Setup
    # viewer -- validated up front, before uvicorn ever binds a socket,
    # same fail-fast posture as --plan's own check above. Falls back to
    # ~/.atoo.config's [watch_conditions] default when the flag
    # itself is omitted, same "explicit flag always wins" precedence
    # `watch_cmd` uses.
    watch_conditions_path = getattr(args, "watch_conditions", None)
    if not watch_conditions_path:
        default_watch_conditions = load_default_watch_conditions()
        if default_watch_conditions is not None:
            watch_conditions_path = str(default_watch_conditions)
            print(f"No --watch-conditions given -- using the default from {config_path()}: "
                  f"{watch_conditions_path}\n", file=sys.stderr)
    if watch_conditions_path and _load_watch_conditions_file(watch_conditions_path) is None:
        return 1

    # The Watch page's console
    # field seeds from ATOO_CONSOLE / ~/.atoo.config [console],
    # so the browser stops being the one way to reach a desk that still
    # makes you retype its address.
    #
    # `resolve_console_defaults()` is called DIRECTLY rather than through
    # `_resolve_console_settings`, and that is the whole point of the
    # split: `ui` has no `--console`, and its `--port` is the web
    # server's. A resolver that mutated args here would move
    # `atoo ui` to whatever ATOO_CONSOLE_PORT said and serve the
    # page somewhere nobody was looking (tests/test_console_address.py::
    # test_the_ui_port_is_not_a_console_port). This touches no args at
    # all -- it hands the values to the page, which puts them in a form
    # the operator still has to look at and press Start on.
    console_defaults = resolve_console_defaults()

    # Build step 01's house conventions file. Quiet when there is none:
    # `atoo ui` is not `atoo build`, and a missing house file
    # is not a reason to refuse to serve a page -- the tile says so, and
    # so does a finding in the dock.
    default_conventions = load_default_conventions()

    # The working folder `atoo init` made. Read only when
    # no --show was given -- with a bundle open, the file browser starts
    # beside it, and the workspace is not where anything happens.
    workspace = load_default_workspace() if show is None else None

    app = create_app(
        initial_plan=plan, initial_plan_path=args.plan if plan is not None else None,
        initial_watch_conditions_path=watch_conditions_path,
        initial_console=console_defaults,
        # The shell page's bundle bar (mockup version H).
        # `--show` is already resolved and validated by `_open_bundle`
        # above, so this is the directory it named, not a second reading
        # of the flag.
        initial_bundle=str(show.directory) if show is not None else None,
        # The shell's Build step 01 (same mockup, phase 2): the HOUSE
        # conventions file, which is not a bundle slot -- it is reused
        # across every show, so it lives outside the bundle
        # and is named in ~/.atoo.config's [conventions] section.
        # The same fallback `build` uses when no --conventions is given,
        # read through the same loader. `ui` has no --conventions flag,
        # deliberately: the page's own "Change file" is the per-session
        # override, and it needs no restart.
        initial_conventions=(
            str(default_conventions) if default_conventions is not None else None
        ),
        # Step 02's Preset chooser and the page's builds: `--presets`, else
        # the [presets] default, resolved by the page the way `build`
        # resolves it (`webui._preset_library_state`).
        initial_presets=getattr(args, "presets", None),
        initial_workspace=str(workspace) if workspace is not None else None,
    )
    # Bind BEFORE announcing. The commonest way `ui` fails to
    # start is a port already in use, and it used to print three URLs that
    # would never answer and then exit 3 -- uvicorn's own code, leaking
    # through this function's return, and a code the canonical exit-code
    # table does not list. Every other command in this tool fails before
    # it claims anything.
    #
    # The socket is HELD and handed to uvicorn, rather than bound, closed
    # and re-bound after the banner. A check-then-serve leaves a window in
    # which something else takes the port between the check and the serve,
    # and the banner would be a lie again -- rarely, which is the worst
    # kind. `Server.run(sockets=[...])` serves on a socket we already own,
    # so there is no second bind and no window.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Not on Windows: there SO_REUSEADDR lets a second server bind a
        # port that is already in use, so the EADDRINUSE below never comes.
        if sys.platform != "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((args.host, args.port))
        sock.listen(2048)
    except OSError as exc:
        # An Atoo UI already on that port is not a failure
        # -- it is the page someone wanted, and a launcher clicked twice
        # must not error. Open it instead. Anything else on the port is
        # still the refusal below.
        if exc.errno == errno.EADDRINUSE:
            sock.close()
            running = _atoo_ui_status(_browser_host(args.host), args.port)
            if running is not None:
                return _join_running_ui(args, show, running)
        # Atoo's voice, not `ERROR:    [Errno 98] error while
        # attempting to bind on address ...`. Same shape as the [ui]-extra
        # branch above, and as `_open_console`'s failure path.
        message = f"couldn't serve on {args.host}:{args.port} -- {exc.strerror or exc}."
        # The advice is only true for the failure it is about. A bad
        # --host fails here too (EADDRNOTAVAIL), and telling someone to
        # try the next port up would send them round the same wall.
        if exc.errno == errno.EADDRINUSE:
            message += (f"\nSomething else is already using that port; try "
                        f"`atoo ui --port {args.port + 1}`.")
        print(message, file=sys.stderr)
        return 1

    # Announce the port we ACTUALLY got, not the one we asked for. They
    # are the same for any explicit `--port N`, and they differ for
    # `--port 0`, where the kernel picks -- which used to print
    # `http://127.0.0.1:0`, an address nothing can open.
    port = sock.getsockname()[1]

    # Which copy of Atoo this is comes first: it is what a tester running a
    # branch checks before reading anything else. Short since 2026-10-27
    # (the maintainer asked for the start to be three lines: the version and
    # where it runs from, the console, the working folder); the branch and
    # commit are `atoo --version`'s and the page's.
    print(app.state.install["short"])
    # The page opens in the browser by itself; with --no-browser this line
    # is the only place its address is said, so it stays for that case.
    if args.no_browser:
        print(f"Atoo: http://{args.host}:{port} (Ctrl-C to stop)")
    if plan is not None:
        print(f"Plan: {args.plan} -- on Build step 04")
    if watch_conditions_path:
        print(f"Watch conditions: {watch_conditions_path}")
    # Said here as well as on the page. The terminal that launched
    # the server is where a stale `export` is most likely to be noticed,
    # and this line is the same announcement every other command makes
    # when it is pointed somewhere the command line never named.
    if console_defaults["address"]:
        print(f"Console: {console_defaults['address']} from {console_defaults['address_source']}")
    else:
        print("Console: none configured -- set one in the bundle bar (Change…) before "
              "Ping, Apply or a live Watch.")
    if workspace is not None:
        print(f"Working folder: {config_value_for(workspace)}")
    elif show is None:
        # The judgement call: say how to get started, once, on
        # stdout. Not stderr -- nothing is wrong, and nothing is refused.
        print("No show open and no working folder set -- `atoo init` makes "
              "~/Documents/Atoo with house conventions and a preset library.")
    # Not a terminal (a pipe, a file, `atoo ui | tee`): Python holds stdout
    # back until a block fills, and the server below blocks this thread, so
    # the announcement -- the only place the port is said -- would never
    # arrive. Say it now.
    sys.stdout.flush()
    # `Server.run(sockets=...)` rather than `uvicorn.run(host=, port=)`:
    # the listener above is already bound and already announced, so
    # uvicorn must serve on THAT socket rather than binding a second time.
    # Its own `Config.bind_socket` is the thing that used to exit 3 -- it
    # calls `sys.exit(STARTUP_FAILURE)` on OSError -- and this path never
    # reaches it. uvicorn closes the socket on shutdown.
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    # Open the page in the default browser once the server
    # ANSWERS -- not when it is bound, so the first load never fails. A
    # thread, because `server.run` blocks this one; it gives up when the
    # server stops, so a server that never comes up opens nothing.
    stop_waiting = threading.Event()
    opener = None
    if not args.no_browser:
        url = f"http://{_browser_host(args.host)}:{port}/"
        opener = threading.Thread(
            target=_open_browser_when_ready,
            args=(url, _browser_host(args.host), port, app.state.instance_id, stop_waiting),
            name="atoo-open-browser", daemon=True)
        opener.start()
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        # `uvicorn.run()` swallows this exact exception for this exact
        # reason, and going around it means doing so here. Its
        # `capture_signals` restores the original SIGINT handler and then
        # re-raises the signal it caught, so a Ctrl-C arrives back here as
        # KeyboardInterrupt after the server has already shut down
        # gracefully. That is a clean stop, and a clean stop is `0`.
        pass
    finally:
        stop_waiting.set()
        if opener is not None:
            opener.join(timeout=2)
    return 0


# ---- `atoo ui` opens the browser ------------------------

#: How long `ui` waits for its own server to answer before giving up on
#: opening a browser. Generous: a cold start on a slow laptop.
BROWSER_WAIT_S = 30.0


def _browser_host(host: str) -> str:
    """The address a browser on THIS machine should use: a wildcard bind
    (`--host 0.0.0.0`) is not an address anything can open, and loopback
    reaches it."""
    return "127.0.0.1" if host in ("", "0.0.0.0", "::") else host


def _local_get_json(url: str, timeout: float):
    """GET ``url`` and parse JSON, or None. Never through a proxy: this is
    always this machine (or the address `--host` named), and an
    `HTTP_PROXY` meant for the internet would answer for it instead."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def _atoo_ui_status(host: str, port: int, timeout: float = 2.0) -> dict | None:
    """`GET /api/status` from whatever holds ``host:port``, if it is a
    Atoo UI -- recognised by the keys only that endpoint answers with
    (`instance`, `bundle`, `running`), so a UI from an older Atoo is
    recognised too. None for anything else, or for nothing answering."""
    data = _local_get_json(f"http://{host}:{port}/api/status", timeout)
    if isinstance(data, dict) and {"instance", "bundle", "running"} <= set(data):
        return data
    return None


def _can_open_browser() -> bool:
    """Whether `webbrowser.open` would open a GRAPHICAL browser. On Linux
    with no display (an SSH session), Python's `webbrowser` falls back to
    a text browser -- lynx, w3m -- in this same terminal, on top of the
    server's output. So: macOS and Windows always; elsewhere only with a
    display, or a `$BROWSER` someone set on purpose."""
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("BROWSER") or os.environ.get("DISPLAY")
                or os.environ.get("WAYLAND_DISPLAY"))


def _open_browser(url: str) -> None:
    import webbrowser
    if not _can_open_browser():
        print(f"No display here, so no browser was opened -- open {url} yourself.", flush=True)
        return
    try:
        opened = webbrowser.open(url)
    except Exception:  # noqa: BLE001 -- a browser that will not start is not a server failure
        opened = False
    if not opened:
        print(f"Couldn't open a browser -- open {url} yourself.", flush=True)


def _open_browser_when_ready(url: str, host: str, port: int, instance: str,
                             stop: threading.Event, wait_s: float = BROWSER_WAIT_S) -> bool:
    """Poll this server's `/api/status` until it answers as THIS server
    (its `instance` id), then open ``url``. Stops when ``stop`` is set
    (the server has stopped) or after ``wait_s``. True if it opened."""
    deadline = time.monotonic() + wait_s
    while not stop.is_set() and time.monotonic() < deadline:
        status = _atoo_ui_status(host, port, timeout=1.0)
        if status is not None and status.get("instance") == instance:
            if stop.is_set():
                return False
            _open_browser(url)
            return True
        stop.wait(0.1)
    return False


def _join_running_ui(args: argparse.Namespace, show, running: dict) -> int:
    """The port is held by an Atoo UI already: say so, open it, exit 0.
    If it has a different show open from the one `--show` named, say that
    too -- this process cannot change it, and the page can."""
    url = f"http://{_browser_host(args.host)}:{args.port}/"
    print(f"Atoo is already running at {url} -- "
          + ("opening it." if not args.no_browser else "open that page."))
    if show is not None and running.get("bundle") != str(show.directory):
        has = running.get("bundle") or "no show"
        print(f"It has {has} open, not {show.directory}: open that one with the bundle bar's "
              f"Change…, or start a second Atoo with `--port {args.port + 1}`.")
    if not args.no_browser:
        _open_browser(url)
    return 0


INIT_DESCRIPTION = (
    "First-run setup: a working folder of your own, and\n"
    "~/.atoo.config pointed at it.\n"
    "\n"
    "  atoo init\n"
    "  atoo init --dir ~/shows\n"
    "  atoo init --demo\n"
    "\n"
    "Makes ~/Documents/Atoo (or --dir) and copies a starter set into it:\n"
    "\n"
    "  README.md          what each file is, and what to do next\n"
    "  conventions.md     example house conventions -- make them yours\n"
    "  presets/           your library of WING channel presets (.chn): the starter\n"
    "                     presets the conventions name, and three bus presets\n"
    "                     (.bus: one for mix busses, two for FX busses). Export\n"
    "                     your own into it\n"
    "\n"
    "and sets three defaults in ~/.atoo.config: [conventions] to conventions.md,\n"
    "[presets] to presets/, and [workspace] to the folder, where `atoo ui`\n"
    "starts. Every value written and every value left alone is printed.\n"
    "\n"
    "It makes no show: which show you start with is yours to choose. Make the\n"
    "first one with `atoo ui`'s New show…, in the folder init made.\n"
    "--demo also copies the Demo show into the folder as demo-show/, a bundle of\n"
    "your own to edit, build and apply to a desk (the one the UI opens is read-only).\n"
    "\n"
    "It never overwrites. A file already there is left alone and reported; a config\n"
    "value already set to something else is left alone, and the line says what init\n"
    "would have set. Run twice, the second run changes nothing and reports that. --force\n"
    "replaces those config values, and starter files that are UNCHANGED copies of an\n"
    "older starter set (init records what it copied in .atoo-starter.json) --\n"
    "never a file you have edited. A demo-show folder already there is left whole,\n"
    "with or without --force.\n"
    "\n"
    "Exit status: 0 done (including nothing to do); 1 the folder, a config value or\n"
    "the Demo show's copy could not be written."
)


def _add_init_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--dir", default=None, metavar="PATH",
        help="Where to make the working folder (default: ~/Documents/Atoo). Made if "
             "it is not there; a folder that is there already is filled in around what it "
             "holds.")
    ap.add_argument(
        "--force", action="store_true",
        help="Replace ~/.atoo.config values that name something else, and starter "
             "files that are unchanged copies of an older starter set. A file you have "
             "edited is never replaced.")
    ap.add_argument(
        "--demo", action="store_true",
        help="Also copy the Demo show into the folder as demo-show/, a writable bundle "
             "beside the starter conventions and presets. A demo-show already there is "
             "left alone.")


def init_cmd(args: argparse.Namespace) -> int:
    """`atoo init` -- see INIT_DESCRIPTION and `atoo.firstrun`."""
    from atoo import firstrun
    result = firstrun.run_init(args.dir, force=args.force, demo=args.demo)
    for line in firstrun.format_report(result):
        print(line)
    for error in result.errors:
        print(error, file=sys.stderr)
    return 1 if result.errors else 0


def _add_presets_arguments(ap: argparse.ArgumentParser) -> None:
    """`atoo presets` takes exactly one flag, and it is the SAME
    `--presets DIR` build/verify/apply take -- same spelling, same
    fallback to `[presets] default`. Anything else would give the command
    that exists to explain a library a different idea of where one is.

    `--expand PLAN` turns it from a listing into the
    one offline way to put a library's values into a plan -- what `build`
    does, without the model call."""
    _add_presets_argument(ap)
    ap.add_argument(
        "--expand", default=None, metavar="PLAN",
        help="Instead of listing, resolve every preset PLAN names into it -- the preset's "
             "processing values, keyed by the address each is written to, with the plan's own "
             "processing winning wherever both set one -- exactly as `build` does. Rewrites "
             "PLAN in place (only if something changed), or writes --out. For a plan built "
             "before presets were expanded, or without a library.")
    ap.add_argument(
        "--out", default=None, metavar="FILE",
        help="With --expand: write the expanded plan here instead of over PLAN.")


def _add_ui_arguments(ap: argparse.ArgumentParser) -> None:
    _add_show_argument(ap)
    ap.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1, loopback only). "
                    "On a network address a second machine may Watch; opening files "
                    "and every write from the page (apply, patch, undo, build, saving a file) "
                    "still answer this machine only")
    ap.add_argument("--port", type=int, default=UI_DEFAULT_PORT, help="Port to serve on (default: 8420). "
                    "If an Atoo UI is already serving there, that one is opened instead")
    ap.add_argument(
        "--no-browser", action="store_true",
        help="Do not open the page in a browser; only print its address. By default the "
             "page opens in the default browser once the server answers")
    ap.add_argument(
        "--plan", default=None,
        help="A plan.json to show at startup on Build step 04 -- the same shape "
             "`atoo build` produces. Optional; a plan can "
             "also be loaded (or replaced) later from the browser without restarting.",
    )
    ap.add_argument(
        "--watch-conditions", default=None,
        help="A watch-conditions JSON file to load at startup into Watch "
             "conditions, on the Watch screen -- the same file `atoo watch "
             "--watch-conditions` accepts. Optional; falls back to ~/.atoo.config's "
             "[watch_conditions] default when omitted (see `atoo watch --help`), and can "
             "also be loaded (or replaced) later from the browser without restarting.",
    )
    ap.add_argument(
        "--presets", default=None, metavar="DIR",
        help="Atoo's preset library (a directory of .chn exports): the names Build "
             "step 02's Preset column offers, and the library a build started from the page "
             "is given. Defaults to [presets] default in ~/.atoo.config; with neither, "
             "the column still takes a name as free text.",
    )


UI_DESCRIPTION = (
    "Serve the operator UI as a local web page: one page with three modes --\n"
    "Build | Apply | Watch -- over one show bundle and one console. A browser client\n"
    "over the same engine the commands use, not a separate implementation.\n"
    "\n"
    "  atoo ui\n"
    "  atoo ui --port 9000\n"
    "  atoo ui --show my-show\n"
    "  atoo ui --no-browser\n"
    "\n"
    "The page opens in your default browser once the server answers, and its address is\n"
    "printed too (--no-browser only prints it; with no display, as over SSH, nothing is\n"
    "opened). If an Atoo UI is already serving on the port, `ui` opens that one and\n"
    "exits 0 rather than failing. Loopback-only by default and no\n"
    "external network calls at any point -- this is meant to run on a laptop with no\n"
    "internet access, only LAN reach to the console.\n"
    "\n"
    "With no --show, the file browser starts in the working folder `atoo init` made\n"
    "(~/.atoo.config's [workspace] default), so Open… and New show… land there.\n"
    "\n"
    "Shared by all three modes: the bundle bar (--show opens one; it can be changed or\n"
    "created from the page), the console readout -- editable there with Change…, and\n"
    "nowhere else -- with a Ping button (one round trip, nothing read, safe mid-show),\n"
    "and the Findings panel: the one place findings are listed, each once -- a verdict\n"
    "first, then one line per finding, the critic's advice apart, and every info note\n"
    "folded.\n"
    "\n"
    "Build: the three files a build reads -- one not there yet is a to-do on its tile,\n"
    "and an error only if Build is pressed without it -- and 04 Plan, which runs\n"
    "`atoo build --show` from the page and shows the plan it writes -- a table, one\n"
    "row per input, each opening onto its detail and provenance -- with its verify and\n"
    "critic findings in the Findings panel. --plan seeds that step with a plan.json.\n"
    "\n"
    "Files and folders are chosen in a file browser on the page, which this server\n"
    "lists for this machine's own browser only. An input list, instructions file or\n"
    "watch-conditions file chosen from outside the open bundle is copied into it as\n"
    "input.csv, instructions.md or watch.json (asking before it replaces one); the house\n"
    "conventions file is used where it is.\n"
    "\n"
    "Apply: the one screen in Atoo that writes to a console. A pre-flight verify\n"
    "shown before the buttons rather than implied, a dry-run preview that is always\n"
    "available, an `Arm` checkbox that IS --confirm and gates the\n"
    "write, and the run's journal -- mismatches and unreadable addresses expanded, the\n"
    "rest counted and folded away, with the journal file named and the `atoo undo`\n"
    "line that reverses it. It runs `atoo apply --show` itself, so every gate that\n"
    "command has is the gate here.\n"
    "\n"
    "Watch: read-only, like `atoo watch`. It watches the console in the bundle bar.\n"
    "Alerts appear in a\n"
    "table, color-coded by severity, and disappear on their own once the operator fixes\n"
    "whatever tripped them. Under Watch conditions it edits\n"
    "the bundle's watch.json (Change file, New file, Save, as for Build's files), and\n"
    "marks each condition Drafted (a bundle build proposed it) or Yours.\n"
    "\n"
    "Demo (Console: Change…, then Demo) opens a packaged demo show on a built-in\n"
    "WING Compact rig that needs no console: Build's tiles and plan, Apply's pre-flight\n"
    "and Preview against the simulated rig, and Watch with the demo's own watch.json,\n"
    "whose conditions fire as the rig's faults come and go. The demo show is read-only\n"
    "-- Save, Build, New file and Change file are refused, and Apply never writes and\n"
    "never undoes. Choosing an address, or opening or creating a show, leaves it.\n"
    "\n"
    "--watch-conditions PATH loads a watch-conditions file into Watch conditions\n"
    "at startup, and threads its rules into any watch session started from the\n"
    "browser -- the same file `atoo watch --watch-conditions` accepts. With\n"
    "--show and no --watch-conditions, the bundle's own watch.json is loaded.\n"
    "\n"
    "There is no --console here, and the --port above is the WEB SERVER's, not a desk's.\n"
    "The console is resolved from $ATOO_CONSOLE / $ATOO_CONSOLE_PORT /\n"
    "$ATOO_CONSOLE_TIMEOUT, or from ~/.atoo.config's [console] section -- the\n"
    "same resolution `ping`, `apply`, `audit` and `watch` use -- and the page shows where\n"
    "it came from. That is only where it STARTS: the bundle bar's Console Change… sets\n"
    "another address (and port) without a restart. It is one\n"
    "console for the whole page -- Ping, Apply, Patch, Undo and Watch all use it, and no\n"
    "screen has a second box to type the wrong address into -- so one plan can be\n"
    "applied to a primary desk and then a backup by changing the bar between them. The\n"
    "bar cannot change while a write is running, and each desk keeps its own undo\n"
    "history (see `atoo undo --help`).\n"
    "\n"
    "The page is at /. /app redirects there.\n"
)


def _add_build_arguments(ap: argparse.ArgumentParser) -> None:
    _add_console_model_argument(
        ap, extra=" With --show, a show that has been built before takes the model "
                  "from its own plan.json, with an INFO; this flag overrides that.")
    _add_show_argument(ap)
    ap.add_argument(
        "--input", default=None,
        help="Input list CSV path -- one band/event/venue's physical inputs. "
             "Omit together with --conventions to auto-detect "
             "the pair in the current directory instead.",
    )
    ap.add_argument(
        "--conventions", default=None,
        help="Your conventions file (Markdown) -- standing house style, reusable across "
             "every show, like the conventions.md `atoo init` copies in. Plain English; the model reads it "
             "directly. Defaults to ~/.atoo.config's [conventions] default. A show "
             "bundle's instructions.md layers over this, it does not replace it.",
    )
    ap.add_argument(
        "--out", default=None,
        help="Write the plan JSON here. Default: <input-stem>+<conventions-stem>.plan.json "
             "in the current directory. Pass '-' to print to stdout instead of writing a file.",
    )
    ap.add_argument(
        "--critic", action="store_true",
        help="Run a second model pass in a separate reviewer role over the generated plan, "
             "looking for omissions first, then at the conventions text itself (every such "
             "finding must quote your files, and is downgraded to a note when it does not). "
             "It reads the first plan, before the fix-up round: an omission quoting a line of "
             "your instructions or conventions exactly goes back to the model in that round. "
             "Its other findings are printed, never enforced -- only the deterministic "
             "verifier gates anything.")
    ap.add_argument(
        "--no-constrain", action="store_true",
        help="Don't constrain decoding to the reply schema (the shorter form the model "
             "writes, which build expands into the plan). "
             "Constrained decoding makes a malformed or off-schema reply impossible on "
             "the providers that support it (claude, ollama, api), but a grammar can degrade "
             "the content it shapes and slows local generation -- this exists so that "
             "trade-off can be measured rather than argued about. The api provider "
             "(OpenAI-compatible) sends it as `response_format`, and stops with this.")
    ap.add_argument(
        "--prompt-dir",
        help="Read the generator and critic prompts from here instead of the packaged "
             "atoo/prompts. Copy that directory, edit the copy, point this at it -- "
             "prompt variants without a branch. Equivalent to ATOO_PROMPT_DIR.")
    ap.add_argument(
        "--no-resolve", action="store_true",
        help="Give the generator the raw conventions and the domain knowledge "
             "instead of the resolved conventions (<conventions-stem>.resolved.md "
             "beside your conventions file; see `atoo resolve`). Equivalent to "
             "ATOO_RESOLVE=0. For comparing builds with and without it.")
    ap.add_argument(
        "--no-category-rules", action="store_true",
        help="Ignore the resolved conventions' Category table: code writes no per-category "
             "channel setting (color, HPF, DCA, mute group, gain, trim, fader, Main routing) "
             "and the generator writes every one. Equivalent to "
             "ATOO_CATEGORY_RULES=0. For comparing builds with and without it; the plan "
             "records which at meta.resolved_conventions.category_table.")
    _add_presets_argument(ap)
    ap.add_argument(
        "--all-changes", action="store_true",
        help="In the \"Changed since the last build\" section a rebuild ends with, print "
             "every changed value of every strip, and why each change is graded as it is, "
             "instead of one short line per strip. The section compares the new plan with "
             "the show bundle's plan.previous.json, strip by strip: a change to a strip "
             "whose input-list rows or conventions lines changed is INFO; one to a strip "
             "nothing about changed is a WARNING, never an error. A first build has none.")
    ap.add_argument(
        "--skip-verify", action="store_true",
        help="Don't run the deterministic verifier over the finished plan. Verification "
             "checks the plan against the console's real limits, the input list it claims to "
             "cover, and equipment-safety rules. Skipping it is almost never what you want.")
    ap.add_argument("--pretty", action="store_true", help="Also print a human-readable rendering, not just the raw JSON plan")


BUILD_DESCRIPTION = (
    "Build a plan from an input list + conventions.\n"
    "\n"
    "A model lays the show out with both in front of it, and deterministic code\n"
    "verifies the result. Needs a provider -- see ATOO_AI_PROVIDER.\n"
    "\n"
    "A model call takes minutes, so each one says where it is on stderr while it runs --\n"
    "which call (generator, critic, watchlist), waiting / thinking / writing, its clock and\n"
    "the tokens so far: one redrawn line on a terminal, and in a log (2>&1 | tee build.log)\n"
    "a plain line at each change of stage and every 10-60 seconds, never one per token.\n"
    "\n"
    "Two ways to fill it in:\n"
    "  atoo build --input a.csv --conventions b.md [--out plan.json] [--pretty]\n"
    "  atoo build\n"
    "\n"
    "The second form is the easy button: with no --input/--conventions given, it looks in\n"
    "the current directory for exactly one .csv input list and exactly one conventions\n"
    "source and builds that pair into a plan. Given more than one candidate it prints\n"
    "what it found and the exact invocation to use, rather than guessing. See\n"
    "https://docs.atoo.app/build/build-a-show/\n"
    "\n"
    "The plan is written to a file either way -- an\n"
    "<input-stem>+<conventions-stem>.plan.json name unless --out says otherwise; pass\n"
    "--out - to print the JSON to stdout instead.\n"
    "\n"
    "A show bundle (--show DIR) supplies input.csv and instructions.md\n"
    "from one directory and writes plan.json back into it. An explicit flag always wins\n"
    "over the bundle. A bundle's busses.csv (the bus sheet: one row per bus, Main and\n"
    "Matrix), outputs.csv (one row per output socket: what feeds it) and user.csv (one\n"
    "row per USR slot: what it takes) are laid onto the plan, in that order: a filled\n"
    "cell wins over the conventions, each change is a note, and a cell that cannot\n"
    "work on the desk stops the build, naming it.\n"
    "\n"
    "A bundle build also DRAFTS that bundle's watch.json -- the short list of\n"
    "things worth an alert if they move mid-show. Drafted conditions are marked\n"
    "\"source\": \"drafted\" and are merged in, never written over the top: a condition you\n"
    "already have is left exactly as you wrote it, one you deleted is not re-added, and\n"
    "nothing watches until you run `atoo watch`. A draft that fails validation is\n"
    "reported and discarded -- it can never fail the build or replace a good watch.json.\n"
    "\n"
    "Your conventions file is NOT part of a bundle. It is your standing house style,\n"
    "reused across shows, so it is named by --conventions or once in ~/.atoo.config.\n"
    "A bundle's instructions.md is a LAYER over it -- how this one show works -- and wins\n"
    "where the two disagree. Every build prints the layers it read, in order, and records\n"
    "them in the plan at meta.conventions_stack -- each file relative to the bundle, with a\n"
    "sha256 of what it held -- so `atoo ui` reopens the bundle on the conventions file\n"
    "that built it. The input list is recorded the same way, at\n"
    "meta.input_list, so the UI and `apply --show` can say a plan is stale: one of its\n"
    "three inputs changed after it was built.\n"
    "\n"
    "RESOLVED CONVENTIONS. Before the generator runs, the build looks for\n"
    "<conventions-stem>.resolved.md beside your conventions file: your conventions and the\n"
    "domain knowledge restated once as explicit rules, each citing the line it comes from,\n"
    "with every open question marked \"Decided:\". When its fingerprint matches (the\n"
    "conventions, the domain knowledge and the resolve prompt are unchanged), the generator\n"
    "and the fix-up read it IN PLACE OF both. When it is missing or stale, the build makes\n"
    "it first -- one extra model call, role `resolve` -- and notes it. The critic still reads\n"
    "your raw conventions. --no-resolve (or ATOO_RESOLVE=0) turns this off; the plan\n"
    "records which it was at meta.resolved_conventions.\n"
    "\n"
    "CATEGORY TABLE. The resolved file ends with a Category table: each category's color,\n"
    "HPF, DCA, mute group, gain, trim, fader and Main routing, restating its prose. Code\n"
    "writes those values on every channel built from an input-list row of that category,\n"
    "wherever the generator's reply leaves them out -- a value the reply writes wins -- and\n"
    "notes it, one note per category. A channel the instructions ask for (Talkback) gets\n"
    "nothing from it. --no-category-rules (or ATOO_CATEGORY_RULES=0) turns it off.\n"
    "\n"
    "An HTML comment, <!-- like this -->, inline or across lines, is a note to yourself:\n"
    "the build strips every comment from both files before a model sees them, so nothing\n"
    "in one is built. An <!-- that never closes is NOT stripped -- the rest of the file is\n"
    "read as written, and the build warns with the file and line. (The recorded sha256\n"
    "is still over the whole file, comments included.)\n"
    "\n"
    "Where your conventions are silent about something the desk cannot be left without --\n"
    "a bus's mono/stereo width, a send's pre/post, a mix bus's route to Main, a stereo\n"
    "pairing -- the build DECIDES it, marks the decision in the plan (`inferred`), and\n"
    "verify reports each one as a note naming what it chose and why. Everything else your\n"
    "conventions do not state is left alone on the desk. The build also reads your\n"
    "conventions and instructions.md together for problems in the text itself -- two\n"
    "statements that disagree with nothing settling them, something declared that this\n"
    "show never uses -- and reports them, quoting the lines; a quote that is not really in\n"
    "your files is marked untrusted (meta.build_findings).\n"
    "\n"
    "What it tells you goes to stderr, severity-labeled, worst first:\n"
    "  ERROR    something you asked for will NOT happen -- read this before applying\n"
    "  WARNING  a default was applied, or a rule matched nothing\n"
    "  NOTE     a choice made where your conventions were silent, or nothing to do;\n"
    "           said out loud rather than hidden, and never blocks\n"
    "A finding that is a limitation of Atoo itself tells you -- editing your\n"
    "conventions file will not fix it. The code in parentheses is\n"
    "stable across rewordings; quote it in a bug report."
)


APPLY_DESCRIPTION = (
    "Write a plan to a console, then read every value back.\n"
    "\n"
    "  atoo apply --plan band+rules.plan.json --console 203.0.113.50\n"
    "  atoo apply --plan band+rules.plan.json --console 203.0.113.50 --confirm\n"
    "\n"
    "The first form changes nothing: it reads the console's current value for every\n"
    "address the plan would touch and shows you the before/after. Writing requires\n"
    "--confirm. It reads every address again before its writes and sends only\n"
    "those that differ, so the number written is the number the preview said would\n"
    "change (unless the console moved in between); each is journalled with its prior\n"
    "value so it can be reversed.\n"
    "\n"
    "Every address written is read back afterwards -- remote console writes can fail\n"
    "silently, so an acknowledgment is not proof. Anything that didn't land is\n"
    "reported by address, and the command exits 2 -- the code build, verify, compare\n"
    "and apply use for \"it ran and found problems\", as against 1 when the command\n"
    "could not run at all. audit and watch report their own findings\n"
    "with 1, not 2. The exit-code table is at https://docs.atoo.app/reference/cli-reference/\n"
    "\n"
    "Before writing, apply asks the desk what is in its two expansion bays\n"
    "(/cards/$type and /$syscfg/opt_mod) and REFUSES a plan that patches from or to\n"
    "one the console reports empty. A WING answers all 64 CRD and MOD\n"
    "sockets whether or not a card or module is fitted, and accepts the patch either\n"
    "way, so nothing else -- not the readback, not the journal, not audit -- would\n"
    "tell you the channel is silent.\n"
    "\n"
    "It asks what is on each AES50 port the plan uses (/$stat/A/dev) and REFUSES a\n"
    "socket past the end of the stage box there: an S16 has 16 inputs and 8 outputs,\n"
    "and A 17 is patched to nothing though the desk lists 48 on every port. A box\n"
    "whose size Atoo has not recorded is reported and its sockets are not checked.\n"
    "\n"
    "ONE PLAN, TWO MODELS. The desk states its own model on /?, and apply compares it\n"
    "with the plan's. A different model whose panel has every socket the plan patches\n"
    "-- a Compact plan on a Rack backup -- is applied, with an INFO naming both and the\n"
    "verify re-run against the desk's model. A socket the desk does not have (LCL 20 on\n"
    "a full-size WING) is REFUSED, each one named, --skip-verify or not. A desk whose\n"
    "model Atoo has never measured is applied with a WARNING, sockets checked\n"
    "against the plan's model only, and its token journalled as desk.model_token.\n"
    "--console-model states which model to check the plan for.\n"
    "\n"
    "THE WHOLE DESK. Every channel and aux strip the plan does not build is unpatched\n"
    "(its /in/conn/grp set to OFF, nothing else), so none listens to a socket the plan\n"
    "uses; a strip already OFF is not written. A talkback strip the plan builds on\n"
    "ch 40 or aux 8 sets Setup -> Audio's talkback assign (/cfg/talk/assign) to\n"
    "CH40/AUX8. One INFO line says each; both are journalled, so undo reverses them.\n"
    "amend and patch never do either.\n"
    "\n"
    "INITIALIZED FIRST. Before the plan, a full apply puts the desk into\n"
    "its initialized state: it reads the desk by node dump and writes back, from an\n"
    "initialized capture of the desk's model, every setting that differs -- except the\n"
    "ones the plan sets itself, and a skip-list (network, clock, expansion cards,\n"
    "meter/RTA display, monitor/solo listening). One INFO line counts it by area and\n"
    "says how long it took; every write is journalled, so undo reverses it. A desk whose\n"
    "model Atoo has no capture for gets a WARNING and the plan is applied without the\n"
    "reset. --no-init skips it, for a desk already initialized by hand.\n"
    "\n"
    "A plan may state a strip's parametric EQ: a channel's\n"
    "processing.eq, and a bus's or a Main/Matrix's own processing.eq/tilt_db. Stating\n"
    "any EQ value turns that strip's EQ on, the way stating a high-pass does. A band a\n"
    "strip does not have -- a channel has four numbered bands, a bus six -- is reported\n"
    "and skipped rather than written to an address the console does not answer.\n"
    "\n"
    "A full apply also disconnects every output socket on the desk's own panel that no bus,\n"
    "Main or Matrix in the plan is patched to, rather than leave it on what the desk shipped\n"
    "with or an earlier show put there; one INFO line names the sockets and undo restores them.\n"
    "\n"
    "--clean-output-sockets NAME=COUNT,... extends that to the groups beyond the panel, such\n"
    "as a stage box's: it disconnects any physical output socket in the given group(s)\n"
    "that no bus or output in the plan routes anywhere to, instead of leaving whatever was\n"
    "already patched there."
)


UNDO_DESCRIPTION = (
    "Reverse the last write to the console, from the journal that wrote it.\n"
    "\n"
    "  atoo undo --show touringband --console 203.0.113.50\n"
    "  atoo undo --show touringband --console 203.0.113.50 --confirm\n"
    "  atoo undo touringband/journals/<entry>.json --console 203.0.113.50\n"
    "\n"
    "The first form changes nothing: it reads the console's current value for every\n"
    "address the run wrote and shows you, per address, what it would restore and what\n"
    "it would refuse. Writing requires --confirm, same as apply.\n"
    "\n"
    "With --show and no journal named, undo walks the bundle back ONE STEP IN TIME.\n"
    "Every confirmed apply, patch (a change), amend and undo is recorded\n"
    "in the bundle's journals/ directory as a timestamped entry, and undo reverses the\n"
    "newest one still standing on the desk, whatever kind it was. It POPS: after\n"
    "undoing a change, the next undo reverses what is under it. journals/ keeps the\n"
    "newest 5 entries, so undo reaches back at most 5 writes: it stops, with nothing\n"
    "written, at a desk's last kept write when an older one was pruned while still on\n"
    "the desk. journals/ is the only\n"
    "record: a bundle with no journals/ has nothing to undo with --show.\n"
    "A journal file anywhere else -- <plan>.apply-journal.json, or one --journal\n"
    "wrote -- is undone by naming it, as in the third form.\n"
    "\n"
    "A change or an amend never writes plan.json -- only a build does -- so undoing\n"
    "one leaves it alone. An amend recorded by an older Atoo DID replace it; undoing\n"
    "that one puts the old plan.json back, but only while plan.json is still the file\n"
    "the amend wrote (a sha256 it recorded), and the redo re-installs it the same way.\n"
    "\n"
    "Naming a journal that is no longer the newest entry is REFUSED, because undo's\n"
    "guard is per address and cannot see a later run: an apply an amend was built on\n"
    "top of would pass every address and come off the desk under it. The refusal names\n"
    "what is above it; --out-of-order overrides it.\n"
    "\n"
    "PER DESK. One plan can be applied to two consoles -- a primary and a backup --\n"
    "and every entry records the desk it wrote to: the serial it states on /? (which\n"
    "also names the entry's file) and the address it was reached at. So \"the newest\"\n"
    "means the newest write on THE DESK THIS COMMAND REACHES: undo --show pops that\n"
    "desk's newest and leaves the other desk's history alone. Undo only ever reverses\n"
    "a journal on the desk it was written to. The serial is the desk: the same serial\n"
    "at a new address is the same desk (said at INFO), and a different serial is\n"
    "refused even at the same address, naming both. There is no override. A desk that\n"
    "states no serial is matched by its address. An entry recorded before entries\n"
    "named their desk is taken to be this desk's, and undo notes it.\n"
    "\n"
    "An undo reverses OUR RUN and nothing else -- which is what a console snapshot\n"
    "cannot do. A snapshot puts the whole desk back to a moment, throwing away every\n"
    "other change made since; this puts back only the addresses this journal records,\n"
    "and only where they are still the value we wrote.\n"
    "\n"
    "That last clause is the whole safety property. Before restoring an address, undo\n"
    "reads it: if it no longer holds what we wrote, somebody has changed it since, and\n"
    "reversing would clobber their change -- so that address is REFUSED and reported,\n"
    "never written. An address whose prior value the apply could never read has nothing\n"
    "to restore and is reported too; no default is invented for it. The summary counts\n"
    "the three apart: \"41 reversed, 2 refused (changed since), 1 unreversible\".\n"
    "\n"
    "Only writes that actually happened are candidates. A skipped_no_change was never\n"
    "written -- unless its selector (a delay mode, a dynamics or EQ model) was changed\n"
    "by the run and is being put back, when its recorded prior is written after the\n"
    "selector, at INFO. The journal of a dry run is refused outright rather than\n"
    "appearing to work. Reversals go out in reverse order -- except a strip's\n"
    "processing, restored selectors, then values, then switches -- are read back and\n"
    "proved like any other write, and are journalled themselves -- so `atoo undo`\n"
    "on the undo's own journal is the redo, and there is no separate command for it.\n"
    "An undo's journal is kept (it is the only record of what the undo REFUSED to\n"
    "touch) but is never a step forward: it pops the entry it reversed rather than\n"
    "becoming a new one.\n"
    "\n"
    "Exit codes: 0 clean, 1 the command could not run (bad journal, no console), 2 it\n"
    "ran and the console is not fully back -- something refused (changed since) or a\n"
    "reversal that did not land. An address with no earlier value (the run wrote it\n"
    "for the first time) has nothing to put back; it is named at INFO and exits 0."
)


def _full_help(parser: argparse.ArgumentParser, subparsers: dict[str, argparse.ArgumentParser]) -> str:
    """Top-level help with every subcommand's own options spliced in.

    argparse shows a bare command list at the top level and hides each
    command's real arguments one level down, behind `atoo <cmd>
    --help`. That was reported as a bug twice (2026-09-10, "the input,
    conventions, out and pretty are totally missing") and it's a fair
    reading: nobody discovers options they have to already know to ask
    for. Subcommands still exist -- apply/extract are coming and they
    need their own argument sets -- so the fix is to print everything on
    one screen rather than to flatten the command structure away."""
    blocks = [parser.format_help().rstrip()]
    for name, sub in subparsers.items():
        body = "\n".join(f"  {line}" if line else "" for line in sub.format_help().rstrip().splitlines())
        blocks.append(f"\n{'=' * 70}\natoo {name}\n{'=' * 70}\n{body}")
    return "\n".join(blocks) + "\n"


RESOLVE_DESCRIPTION = (
    "Resolve your house conventions (an experiment).\n"
    "\n"
    "One model call (role `resolve`) reads your conventions file and Atoo's domain\n"
    "knowledge and writes <conventions-stem>.resolved.md beside the conventions file:\n"
    "plain Markdown that states, per category, the HPF, color, DCA, mute group, monitor\n"
    "and bus sends, Main routing, gain, trim and phantom; the busses, outputs, groups,\n"
    "head-amp scope, faders and channel order; every open question settled once as a\n"
    "\"Decided:\" line with its reason; and every conventions line that yields no rule,\n"
    "under \"Lines with no effect\". Every rule cites the text it comes from, verbatim, as\n"
    "[conventions: \"...\"] or [domain: \"...\"].\n"
    "\n"
    "Code then checks it: every citation must be in the conventions or the domain\n"
    "knowledge, and every conventions line (not blank, not a heading, not a comment) must\n"
    "be cited or listed as having no effect. A citation not found is a WARNING; a line\n"
    "no rule covers is a note, and is given to the generator verbatim. A line of your\n"
    "preset map (- Kick: \"Kick In\", indented under a line that names presets) is\n"
    "covered when your preset library -- [presets] default in ~/.atoo.config -- has\n"
    "every preset it names (a bus preset under a line that says bus), cited or not; one\n"
    "naming a preset the library has not got is a note saying so, and so is one that\n"
    "also states a rule. A library that cannot be read is said at INFO. The file is\n"
    "still used with warnings, and refused only when\n"
    "it is empty or none of its citations is found.\n"
    "\n"
    "The file ends with a Category table: one JSON object per category restating its\n"
    "color, HPF, DCA, mute group, gain, trim, fader and Main routing, which the build\n"
    "writes on every channel of that category the generator leaves them out of. Code\n"
    "checks its shape; an invalid table is a WARNING and is not applied. --check says\n"
    "whether it is valid.\n"
    "\n"
    "`atoo build` does this for you when the file is missing or stale, so you run\n"
    "this command to resolve again on purpose (after reading the file and disagreeing\n"
    "with a decision, say), or with --check to check the file you have without a model\n"
    "call.\n"
    "\n"
    "  atoo resolve --conventions conventions.md\n"
    "  atoo resolve --conventions conventions.md --check\n"
    "\n"
    "Model and effort: ATOO_AI_RESOLVE_MODEL (default claude-sonnet-5-5,\n"
    "whatever the generator runs on) and ATOO_AI_RESOLVE_EFFORT (default medium).\n"
    "\n"
    "Exit status: 0 the file is fresh and every check passed; 2 it is usable, with\n"
    "warnings (or, with --check, stale); 1 it is missing, refused, or could not be made."
)


def _add_resolve_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--conventions", default=None,
        help="Your conventions file. Defaults to ~/.atoo.config's [conventions] "
             "default. The resolved file is written beside it.")
    ap.add_argument(
        "--check", action="store_true",
        help="Check the resolved file that is there -- its fingerprint, its citations and "
             "its coverage of your conventions -- and make no model call.")
    ap.add_argument(
        "--prompt-dir",
        help="Read the resolve prompt (conventions_resolve.md) from here instead of the "
             "packaged atoo/prompts. Equivalent to ATOO_PROMPT_DIR.")


def resolve_cmd(args: argparse.Namespace) -> int:
    """`atoo resolve`: make the resolved conventions now, or (--check)
    check the file there is. See RESOLVE_DESCRIPTION."""
    if getattr(args, "prompt_dir", None):
        os.environ["ATOO_PROMPT_DIR"] = args.prompt_dir
    conventions_path = args.conventions
    if not conventions_path:
        default = load_default_conventions()
        conventions_path = str(default) if default is not None else None
    if not conventions_path:
        print("no conventions file -- pass --conventions, or name one in "
              f"{config_path()}'s [conventions] default", file=sys.stderr)
        return 1
    try:
        conventions_raw = Path(conventions_path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"couldn't read {conventions_path}: {exc.strerror}", file=sys.stderr)
        return 1
    name = Path(conventions_path).name
    try:
        state = conventions_resolve.freshness(conventions_path, conventions_raw)
    except generate.PromptError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    shown = _display_resolved(state.path)
    # The library the preset map is checked against, and why (INFO):
    # said here too, not only by the build.
    preset_library = _resolve_preset_library(args, announce=True)

    if args.check:
        if state.text is None:
            print(f"{shown}: {state.reason}. `atoo resolve --conventions "
                  f"{conventions_path}` makes it (one model call).", file=sys.stderr)
            return 1
        result = conventions_resolve.check(state.text, conventions_raw,
                                           conventions_name=name, resolved_name=state.path.name,
                                           preset_library=preset_library)
        table = category_table_module.parse(state.text, resolved_name=state.path.name)
        strips = instructed_channels.drop_unquoted(
            instructed_channels.parse_strips(state.text, resolved_name=state.path.name),
            conventions_resolve.conventions_for_model(conventions_raw), conventions_name=name,
            resolved_name=state.path.name)
        print(f"{shown}: {state.state} ({state.reason})")
        print(f"{shown}: {result.summary()}")
        print(f"{shown}: Category table "
              + (f"valid, {len(table.table.entries)} categories" if table.table is not None
                 else table.state))
        print(f"{shown}: Instructed strips "
              + (f"valid, {len(strips.strips)} built by code"
                 + (f" ({', '.join(s.name for s in strips.strips)})" if strips.strips else "")
                 if strips.state == "valid" else strips.state))
        findings = result.findings + table.findings + strips.findings
        if findings:
            _emit_diagnostics(findings,
                              heading=f"\nResolved conventions -- {len(findings)} "
                                      "note(s):")
        if not result.usable:
            return 1
        # A missing table is a note (INFO), not a warning: the file is
        # used exactly as it was before tables existed.
        warned = [f for f in result.findings + table.findings + strips.findings
                  if f.severity != diagnostics.Severity.INFO]
        return 0 if state.fresh and not warned else 2

    try:
        provider = provider_from_env()
    except AIProviderError as exc:
        print(f"resolve failed: {exc}", file=sys.stderr)
        return 1
    announce = getattr(provider, "effort_announcement", None)
    line = announce(["resolve"]) if announce else None
    if line:
        print(line, file=sys.stderr, flush=True)
    print(f"INFO resolved conventions: {shown} is {state.state} ({state.reason}) -- resolving "
          "now: one model call, role resolve", file=sys.stderr, flush=True)
    findings: list = []
    try:
        resolved = conventions_resolve.obtain(state, conventions_raw, name, provider=provider,
                                              force=True, findings=findings,
                                              preset_library=preset_library)
    except (KeyboardInterrupt, BuildStopped):
        print("resolve: stopped -- nothing was written", file=sys.stderr)
        return 130
    if resolved is not None and resolved.table is not None:
        findings.extend(resolved.table.findings)
        if resolved.table.table is not None:
            print(f"resolve: Category table valid, {len(resolved.table.table.entries)} "
                  "categories", file=sys.stderr, flush=True)
    if resolved is not None and resolved.strips is not None:
        findings.extend(resolved.strips.findings)
        if resolved.strips.state == "valid":
            names = ", ".join(s.name for s in resolved.strips.strips)
            print(f"resolve: Instructed strips valid, {len(resolved.strips.strips)} built by code"
                  + (f" ({names})" if names else ""), file=sys.stderr, flush=True)
    if findings:
        _emit_diagnostics(findings,
                          heading=f"\nResolved conventions -- {len(findings)} note(s):")
    if resolved is None:
        return 1
    return 2 if any(f.severity != diagnostics.Severity.INFO for f in findings) else 0


def build_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    """The whole CLI, as an argparse tree plus its subparsers by name.

    Extracted from `main()` so something other than a user
    typing `--help` can read it: `docs/user/cli-reference.md` is
    GENERATED from this tree by a script in the development repository,
    whose suite regenerates it and fails on any difference. A hand-written reference
    drifts from `--help` -- the old hand-written one did, more than
    once -- and a generated one cannot.
    """
    ap = argparse.ArgumentParser(
        prog="atoo",
        description=(
            "Write your console conventions down once. Compile them into a show, apply it\n"
            "to the desk, and prove it landed.\n"
            "\n"
            "Every command's own options are listed below, after the command summary."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,  # -h is re-added below so it can print the full, spliced help
    )
    ap.add_argument("-h", "--help", action="store_true", help="Show this help (including every command's options) and exit")
    ap.add_argument("--version", action="store_true",
                    help="Print the version, where this copy of Atoo is running from, and, "
                         "for a git checkout, its branch and commit, and exit")
    sub = ap.add_subparsers(dest="command")

    init_ap = sub.add_parser(
        "init",
        help="First run: make ~/Documents/Atoo with a starter set, and point "
             "~/.atoo.config at it -- never overwrites",
        description=INIT_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_init_arguments(init_ap)
    init_ap.set_defaults(func=init_cmd)

    build_ap = sub.add_parser(
        "build",
        help="Compile an input list + conventions into a plan",
        description=BUILD_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_build_arguments(build_ap)
    build_ap.set_defaults(announce_install=True, func=build)

    verify_ap = sub.add_parser(
        "verify",
        help="Check an existing plan against the console's limits and the input list it "
             "claims to cover -- without rebuilding it.",
        add_help=False,
    )
    _add_verify_arguments(verify_ap)
    verify_ap.add_argument("-h", "--help", action="help")
    verify_ap.set_defaults(func=verify_cmd)

    compare_ap = sub.add_parser(
        "compare",
        help="Compare a plan against a .snap show file saved on the console.",
        add_help=False,
    )
    _add_compare_arguments(compare_ap)
    compare_ap.add_argument("-h", "--help", action="help")
    compare_ap.set_defaults(func=compare_cmd)

    apply_ap = sub.add_parser(
        "apply",
        help="Write a plan to a console and read every value back",
        description=APPLY_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_apply_arguments(apply_ap)
    apply_ap.set_defaults(announce_install=True, func=apply_cmd)

    patch_ap = sub.add_parser(
        "patch",
        help="Type a change -- add or drop channels -- and write only that to a console "
             "that already has a show on it",
        description=PATCH_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_patch_arguments(patch_ap)
    patch_ap.set_defaults(announce_install=True, func=patch_cmd)

    amend_ap = sub.add_parser(
        "amend",
        help="Change a console from a rebuilt plan, moving nothing else -- the same as "
             "`patch --amended-plan`",
        description=AMEND_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_amend_arguments(amend_ap)
    amend_ap.set_defaults(announce_install=True, func=amend_cmd)

    undo_ap = sub.add_parser(
        "undo",
        help="Reverse the last write to the console, where nobody has changed it since",
        description=UNDO_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_undo_arguments(undo_ap)
    undo_ap.set_defaults(announce_install=True, func=undo_cmd)

    ping_ap = sub.add_parser(
        "ping",
        help="Check a console is reachable and say which one answered",
        description=PING_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_ping_arguments(ping_ap)
    ping_ap.set_defaults(announce_install=True, func=ping_cmd)

    capture_ap = sub.add_parser(
        "capture",
        help="Capture a desk, or a .snap, as a show: input.csv, busses.csv, outputs.csv, "
             "user.csv when the desk uses a USR slot, and a plan of the desk as it is -- no model, nothing written to the desk",
        description=CAPTURE_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_capture_arguments(capture_ap)
    capture_ap.set_defaults(announce_install=True, func=capture_cmd)

    audit_ap = sub.add_parser(
        "audit",
        help="Audit a console's live state against structural rules, and trace signal paths",
        description=AUDIT_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_audit_arguments(audit_ap)
    audit_ap.set_defaults(announce_install=True, func=audit_cmd)

    watch_ap = sub.add_parser(
        "watch",
        help="Continuously audit a console and alert on what changed",
        description=WATCH_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_watch_arguments(watch_ap)
    watch_ap.set_defaults(announce_install=True, func=watch_cmd)

    presets_ap = sub.add_parser(
        "presets",
        help="List a preset library -- what each preset is called, and anything wrong with "
             "it; or, with --expand, put the presets a plan names into it",
        description=PRESETS_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_presets_arguments(presets_ap)
    presets_ap.set_defaults(func=presets_cmd)

    ui_ap = sub.add_parser(
        "ui",
        help="Serve the operator UI (Build, Apply, Watch) as a local web page, and open it "
             "in your browser",
        description=UI_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_ui_arguments(ui_ap)
    ui_ap.set_defaults(func=ui_cmd)

    lessons_ap = sub.add_parser(
        "lessons",
        help="Mine a show bundle's builds for what keeps being unclear -- no model call",
        description=LESSONS_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_lessons_arguments(lessons_ap)
    lessons_ap.set_defaults(func=lessons_cmd)

    resolve_ap = sub.add_parser(
        "resolve",
        help="Restate your conventions and the domain knowledge as one checked set of rules "
             "the generator reads -- or, with --check, check the one you have (no model call)",
        description=RESOLVE_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_resolve_arguments(resolve_ap)
    resolve_ap.set_defaults(announce_install=True, func=resolve_cmd)

    return ap, {
        "init": init_ap, "build": build_ap, "verify": verify_ap, "compare": compare_ap, "apply": apply_ap,
        "patch": patch_ap, "amend": amend_ap, "undo": undo_ap, "ping": ping_ap, "audit": audit_ap,
        "capture": capture_ap,
        "watch": watch_ap,
        "presets": presets_ap, "ui": ui_ap, "lessons": lessons_ap, "resolve": resolve_ap,
    }


def _stdout_is_a_pipe() -> bool:
    """True when stdout is a pipe or socket, the only places a reader can
    vanish from. A BrokenPipeError with stdout on a terminal or a file did
    not come from stdout, and must not be hidden."""
    import stat
    try:
        mode = os.fstat(sys.stdout.fileno()).st_mode
    except (AttributeError, OSError, ValueError):
        return False
    return stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)


def main(argv: list[str] | None = None) -> int:
    """The `atoo` entry point.

    When the reader of stdout goes away early (`atoo --help | head`,
    or quitting `less`), the command stops quietly with exit status 1,
    the recipe in the Python docs' note on SIGPIPE (the `signal` module):
    flush inside the try so the error is caught here and not at
    interpreter exit, then point stdout at devnull so the exit-time flush
    has nowhere to fail. Only BrokenPipeError is caught, and only while
    stdout is a pipe; every other error keeps its traceback.
    
    """
    try:
        try:
            status = _main(argv)
        except SystemExit:
            # argparse's own --help and usage errors leave by SystemExit;
            # their output gets the same flush.
            sys.stdout.flush()
            raise
        sys.stdout.flush()
        return status
    except BrokenPipeError:
        if not _stdout_is_a_pipe():
            raise
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 1


#: Subcommands that neither read or write a desk nor call a model, so they
#: print no install line. Every other subcommand sets `announce_install`.
NO_INSTALL_LINE = frozenset({"init", "verify", "compare", "presets", "ui", "lessons"})


def _main(argv: list[str] | None = None) -> int:
    ap, subparsers = build_parser()
    args = ap.parse_args(argv)

    if args.version:
        print(install_info.describe().version_text())
        return 0

    # No command, or an explicit -h: the full help, not argparse's
    # "the following arguments are required: command" stub.
    if args.help or not args.command:
        print(_full_help(ap, subparsers), end="")
        return 0

    # One place, before any command runs. A no-op for every
    # command that has no `--console` of its own.
    _resolve_console_settings(args)

    # Which atoo, and from where, is the first thing to know when a write to
    # a desk or a paid model call goes wrong. A command opts in with
    # `announce_install=True` in its `set_defaults`; a test requires every
    # subcommand to either do so or be named in `NO_INSTALL_LINE`.
    # On stderr: `build --out -` and the like put data on stdout.
    if getattr(args, "announce_install", False):
        print(install_info.describe().summary(), file=sys.stderr)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
