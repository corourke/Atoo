"""atoo/report.py -- an earlier change: `plan.json["meta"]["verify_at_generation"]`'s
BLOCKED/OK status logic. (The module used to also render a `.report.md`
file beside the plan; retired once an earlier change folded that same
data into `plan.json` itself -- see report.py's module docstring.)"""

from __future__ import annotations

from atoo.report import verify_at_generation_status
from atoo.verify_plan import VerifyResult


def test_verify_at_generation_status_skipped_when_verify_result_is_none():
    status = verify_at_generation_status(verify_result=None)
    assert status == {
        "skipped": True, "ok": None, "error_count": 0, "warning_count": 0,
        "summary": "Verification skipped (--skip-verify) -- not checked at generation time.",
    }


def test_verify_at_generation_status_ok_when_clean():
    verdict = VerifyResult()
    status = verify_at_generation_status(verify_result=verdict)
    assert status["skipped"] is False
    assert status["ok"] is True
    assert status["error_count"] == 0
    assert status["summary"] == "OK"


def test_verify_at_generation_status_blocked_by_verify_errors():
    verdict = VerifyResult()
    verdict.add("error", "output.socket-out-of-range", "outputs[Matrix]", "LCL output 99 does not exist")
    status = verify_at_generation_status(verify_result=verdict)
    assert status["ok"] is False
    assert status["error_count"] == 1
    assert status["summary"] == "BLOCKED -- do not apply"


def test_verify_at_generation_status_counts_only_the_verifier():
    """An earlier change retired expectations, and with it the second error source this
    status used to fold in. The verifier's own count is the whole count."""
    verdict = VerifyResult()
    verdict.add("warning", "preset.unknown", "channels[Kick]", "no such preset")
    status = verify_at_generation_status(verify_result=verdict)
    assert status["ok"] is True
    assert status["error_count"] == 0
    assert status["warning_count"] == 1
    assert status["summary"] == "OK"
