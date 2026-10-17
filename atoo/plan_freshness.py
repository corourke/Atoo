"""Is a plan still what its inputs would build?

The input list is meant to be editable on its tab. The plan then
shows 'stale', with a button to rebuild it. The same holds for the house
conventions and the show's `instructions.md`: a plan built from one text
and applied after another was edited is the plan as built, not as the
engineer now means it -- and nothing on screen said so.

**Content, not timestamps.** A plan records the sha256 of every file it
was built from: the conventions layers, and the
input list since this change (`meta.input_list`, the same record). A
file whose bytes still hash to what the plan recorded is the file it was
built from, whatever its mtime says -- copying a bundle, checking it out
of git or saving it unchanged moves an mtime and changes nothing about
the plan.

**"Cannot tell" is not "stale".** A plan built before a record existed
has nothing to compare with, and calling it stale would put a warning on
every old plan on every page load, which teaches people to ignore the
warning. So each file is one of: *current*, *changed* (the plan is
stale, and the reason names the file), or *unrecorded* (the plan cannot
say; rebuilding records it). The plan is **stale** if any file changed,
**unknown** if none changed but one is unrecorded, else **current**.

Read-only: nothing here writes, and nothing refuses. Staleness announces
itself -- on the Build page's plan tile and status line, and as a
WARNING in Apply's pre-flight -- and never blocks: applying a plan
built before an edit is a choice an engineer may make on purpose
(a judgement call is announced, not refused).
"""

from __future__ import annotations

from pathlib import Path

from atoo import conventions_ref

CURRENT = "current"
STALE = "stale"
UNKNOWN = "unknown"
NONE = "none"


def input_list_record(path: "str | Path", bundle_dir: "str | Path | None") -> dict:
    """What `atoo build` writes at ``meta.input_list``: the path as
    given, plus `conventions_ref.layer_record`'s absolute path, path
    relative to the bundle and sha256 -- the same record a conventions
    layer carries, so both are read back the same way."""
    return {"path": str(path), **conventions_ref.layer_record(path, bundle_dir)}


def _label(path: "Path | None", display) -> str:
    if path is None:
        return "(none)"
    return display(path) if display else Path(path).name


def assess(plan: object, *, conventions: "Path | None", instructions: "Path | None",
           input_list: "Path | None", display=None) -> dict:
    """Compare what ``plan`` records against the three files a build would
    read now.

    ``conventions``/``instructions``/``input_list`` are those files'
    paths -- the ones the next build would use (``instructions`` may name
    a file that does not exist: a bundle with no `instructions.md`).
    ``display`` turns a path into the short form the page shows.

    Returns ``{"state", "reasons", "unknown", "built_at"}``: ``reasons``
    is one ``{"slot", "code", "message"}`` per changed file, ``unknown``
    one ``{"slot", "message"}`` per file the plan cannot speak for.
    """
    if not isinstance(plan, dict):
        return {"state": NONE, "reasons": [], "unknown": [], "built_at": None}
    meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
    stack = meta.get("conventions_stack") if isinstance(meta.get("conventions_stack"), list) else []
    layers = {layer.get("role"): layer for layer in stack if isinstance(layer, dict)}
    reasons: list[dict] = []
    unknown: list[dict] = []

    def changed(slot: str, code: str, message: str) -> None:
        reasons.append({"slot": slot, "code": code, "message": message})

    # ---- the house conventions, and instructions.md -------------------
    house = layers.get("conventions")
    if not house or not house.get("sha256"):
        unknown.append({
            "slot": "conventions",
            "message": "This plan records no fingerprint of the conventions it was built "
                       "from (it predates that record), so an edit to the house conventions "
                       "or instructions.md cannot be detected. Rebuilding records one.",
        })
    else:
        now = conventions_ref.file_sha256(conventions) if conventions is not None else None
        if conventions is None or now is None:
            changed("conventions", "plan.conventions-gone",
                    "There is no house conventions file now; this plan was built from "
                    f"{house.get('bundle_relative_path') or house.get('path')}.")
        elif now != house["sha256"]:
            recorded = house.get("absolute_path")
            if recorded and conventions_ref.same_file(conventions, recorded):
                changed("conventions", "plan.conventions-edited",
                        f"{_label(conventions, display)} (house conventions) changed after "
                        "this plan was built.")
            else:
                changed("conventions", "plan.conventions-other-file",
                        f"Step 01 shows {_label(conventions, display)}, not the conventions "
                        "file this plan was built from, and its contents differ.")

        show = layers.get("instructions")
        present = instructions is not None and Path(instructions).is_file()
        if show is None:
            if present:
                changed("instructions", "plan.instructions-added",
                        f"{_label(instructions, display)} was added after this plan was "
                        "built, which had no show instructions.")
        elif not show.get("sha256"):
            unknown.append({"slot": "instructions",
                            "message": "This plan records no fingerprint of its "
                                       "instructions.md. Rebuilding records one."})
        elif not present:
            changed("instructions", "plan.instructions-gone",
                    "This plan was built with an instructions.md that is no longer there.")
        elif conventions_ref.file_sha256(instructions) != show["sha256"]:
            changed("instructions", "plan.instructions-edited",
                    f"{_label(instructions, display)} changed after this plan was built.")

    # ---- the input list ------------------------------------------------
    recorded_list = meta.get("input_list") if isinstance(meta.get("input_list"), dict) else None
    if not recorded_list or not recorded_list.get("sha256"):
        unknown.append({
            "slot": "input_list",
            "message": "This plan records no fingerprint of its input list (it was built "
                       "before that was recorded), so an edit to input.csv cannot be "
                       "detected. Rebuilding records one.",
        })
    else:
        now = conventions_ref.file_sha256(input_list) if input_list is not None else None
        if now is None:
            changed("input_list", "plan.input-list-gone",
                    "There is no input list now; this plan was built from "
                    f"{recorded_list.get('bundle_relative_path') or recorded_list.get('path')}.")
        elif now != recorded_list["sha256"]:
            changed("input_list", "plan.input-list-edited",
                    f"{_label(input_list, display)} changed after this plan was built.")

    state = STALE if reasons else (UNKNOWN if unknown else CURRENT)
    return {"state": state, "reasons": reasons, "unknown": unknown,
            "built_at": meta.get("generated_at")}


STALE_CODE = "plan.older-than-inputs"


def stale_diagnostic(assessment: dict, plan_display: str = "plan.json"):
    """The WARNING Apply's pre-flight shows for a stale plan -- the same
    words from `atoo apply --show` and the Apply screen, because the
    screen runs that command. None unless the plan is stale."""
    from atoo.diagnostics import Diagnostic, Severity

    if not assessment or assessment.get("state") != STALE:
        return None
    return Diagnostic(
        severity=Severity.WARNING, code=STALE_CODE, where=plan_display, source="apply",
        message=(f"{plan_display} is older than its inputs: "
                 + " ".join(reason["message"] for reason in assessment["reasons"])
                 + " Applying writes the plan as it was built, without those edits."),
        fix="rebuild it (Build step 04, Rebuild) so the edits reach the desk -- or apply as "
            "it is, if those edits are not meant to reach the desk",
    )


def assess_bundle(plan: object, show, conventions: "Path | None" = None) -> dict:
    """`assess` for a show bundle's own plan: its `input.csv` and
    `instructions.md`, and ``conventions`` -- by default the house file the
    plan records (`conventions_ref`), which is the one a rebuild from the
    Setup page starts on."""
    from atoo import bundle as bundle_module

    recorded = conventions_ref.recorded_conventions(plan)
    if conventions is None and recorded is not None:
        conventions, _how = conventions_ref.resolve_recorded(recorded, show.directory)
    if conventions is None and recorded is not None and recorded.get("sha256"):
        # The recorded file is gone (or the plan predates the record):
        # the next build falls back to the configured house default.
        from atoo import config

        conventions = config.load_default_conventions()
    return assess(plan, conventions=conventions,
                  instructions=show.path(bundle_module.INSTRUCTIONS),
                  input_list=show.path(bundle_module.INPUT_LIST),
                  display=lambda p: _bundle_display(p, show))


def _bundle_display(path: "Path", show) -> str:
    try:
        return f"{show.directory.name or show.directory}/{Path(path).relative_to(show.directory)}"
    except ValueError:
        return Path(path).name
