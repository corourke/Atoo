"""`plan.json["meta"]["verify_at_generation"]`'s own status logic.

Originally this module also rendered a `.report.md` file beside the plan
 -- generation warnings, critic findings and verification,
saved rather than only printed to a terminal that vanishes when closed.
Retired once an earlier change folded that same data directly into `plan.json`
itself (`meta.critic_findings`/`verify_findings`, alongside
`verify_at_generation` below): a UI or a human reading the plan file no
longer needs a second file open, so `build` stopped writing one.
`verify_at_generation_status()` is what's left -- the one piece of
report-shaping logic still in active use.
"""

from __future__ import annotations


def verify_at_generation_status(*, verify_result) -> dict:
    """`plan.json["meta"]["verify_at_generation"]`: a BLOCKED/OK
    summary of the plan's own state at build time, so a human or a future
    UI can see it without a second file open.

    Named `verify_at_generation`, not `valid`/`good_to_apply`, on purpose:
    this is a snapshot of what `verify_plan()` said *at build time*. It is
    never re-read as a live answer -- see cli.py's
    `apply_cmd`, which re-runs `verify_plan()` fresh every time regardless
    of anything already sitting in the file. A stale `"ok": true` in an
    old plan.json must never be mistaken for "still safe to apply".

    `verify_result` is None exactly when `--skip-verify` was passed --
    that is reported as `skipped: True`, distinct from "verification ran
    and found nothing to block on", which is `skipped: False, ok: True`.
    """
    if verify_result is None:
        return {
            "skipped": True,
            "ok": None,
            "error_count": 0,
            "warning_count": 0,
            "summary": "Verification skipped (--skip-verify) -- not checked at generation time.",
        }
    blocked = bool(verify_result.errors)
    error_count = len(verify_result.errors)
    return {
        "skipped": False,
        "ok": not blocked,
        "error_count": error_count,
        "warning_count": len(verify_result.warnings),
        # Notes never block (verify_plan's `info`); counted so a reader of
        # plan.json alone can see there are choices to review.
        "note_count": len(getattr(verify_result, "infos", []) or []),
        "summary": "BLOCKED -- do not apply" if blocked else "OK",
    }
