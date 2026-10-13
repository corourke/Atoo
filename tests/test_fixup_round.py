"""One fix-up round (the maintainer, 2026-09-29).

When a generated plan fails verify with ERRORS -- or the reply fails the
format check -- the build sends the model's own reply and the exact error
messages back to the generator's model once, as its own role `fixup`, and
the corrected reply goes through the same pipeline. If it passes, it is
the plan; if not, the build fails as it always did, showing both rounds.
Warnings do not trigger it -- except a strip whose audio reaches no
output, a routing slip rather than a judgement -- and `ATOO_AI_FIXUP_ROUNDS=0` turns it off.

No model is called: the provider is `FakeProvider`, scripted one reply per
call. The dangling-DCA reply is derived from Haiku 4.5's festival build of
2026-09-29 and frozen under `tests/fixtures/`; nothing reads `examples/`.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from atoo import generate
from atoo.ai_provider import FakeProvider
from atoo.cli import main
from atoo.progress import BuildStopped

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# Three rows of the festival input list, and Haiku's reply for them: it
# declared a DCA 'Bass' and then put BassDI in a DCA 'Band' it never
# declared -- verify's `reference.dangling`, word for word as the real build.
DANGLING_REPLY = FIXTURES / "haiku45_festival_dangling_dca.reply.json"
DANGLING_CSV = FIXTURES / "haiku45_festival_dangling_dca.csv"
DANGLING_ERROR = ("channels[BassDI].dca: joins DCA 'Band', which the plan never "
                  "declares (reference.dangling)")

CONVENTIONS = """# House conventions

- DCAs: Drums (all drum channels), Bass, Vocals (all vocal channels).
- Mute groups: Band (all band instruments), Vocals.
- Main is on LCL 7/8.
"""


def _broken() -> dict:
    reply = json.loads(DANGLING_REPLY.read_text())
    # The fixture is three rows cut from a whole festival reply, and two of
    # them lost their route to the Main in the cut. Routed here, so the one
    # thing wrong with it is the dangling DCA: a strip that reaches no
    # output goes to the fix-up too (`test_a_strip_that_reaches_nothing_...`).
    for channel in reply["channels"]:
        channel["main_routes"] = channel.get("main_routes") or [{"index": 1}]
    return reply


def _fixed() -> dict:
    reply = _broken()
    bass = next(c for c in reply["channels"] if c["input"] == "BassDI")
    bass["dca"] = ["Bass"]
    bass["provenance"]["dca"] = "DCAs: Bass"
    return reply


@dataclass
class ScriptedProvider(FakeProvider):
    """`FakeProvider`, answering each call with the next reply in
    `script` -- a generator and a fix-up see different prompts, and both
    are built inside `build`, so a scripted sequence is the honest stub.
    Streams (with no delay) so each call leaves a build-log entry, as the
    real providers do."""
    script: list[str] = field(default_factory=list)
    stream_chunks: int = 2
    model: str = "claude-haiku-4-5"

    def complete(self, *, system, user, response_schema=None, label=""):
        self.response = self.script[len(self.calls)]
        return super().complete(system=system, user=user,
                                response_schema=response_schema, label=label)


@pytest.fixture
def show(tmp_path):
    (tmp_path / "input.csv").write_text(DANGLING_CSV.read_text())
    (tmp_path / "conventions.md").write_text(CONVENTIONS)
    return tmp_path


def _use(monkeypatch, *replies) -> ScriptedProvider:
    provider = ScriptedProvider(script=[r if isinstance(r, str) else json.dumps(r)
                                        for r in replies])
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    return provider


def _build(show) -> int:
    return main(["build", "--console-model", "wing-compact",
                 "--input", str(show / "input.csv"),
                 "--conventions", str(show / "conventions.md"),
                 "--out", str(show / "plan.json")])


def _build_log(show) -> dict:
    meta = json.loads((show / "plan.json").read_text())["meta"]
    return json.loads((show / meta["build_log_file"]).read_text())


def test_a_dangling_dca_is_sent_back_once_and_the_fixed_reply_is_the_plan(
        show, monkeypatch, capsys):
    monkeypatch.delenv("ATOO_AI_FIXUP_ROUNDS", raising=False)
    provider = _use(monkeypatch, _broken(), _fixed())

    assert _build(show) == 0
    err = capsys.readouterr().err
    assert "fix-up: 1 verify error sent back to claude-haiku-4-5" in err

    # Two calls, the second in its own role, carrying the reply and the
    # exact message -- and the conventions and input list as the generator
    # had them.
    assert provider.labels == ["generator", "fixup"]
    system, user = provider.calls[1]
    assert DANGLING_ERROR in user
    assert '"dca":["Band"]' in user           # the reply, compact
    assert "BassDI" in user and "House conventions" in user
    assert "Return the WHOLE corrected reply" in system
    assert "# Domain knowledge" not in user   # not needed to mend an error

    plan = json.loads((show / "plan.json").read_text())
    bass = next(c for c in plan["channels"] if c["name"] == "BassDI")
    assert bass["dca"] == ["Bass"]
    meta = plan["meta"]
    assert meta["verify_findings"]["errors"] == []
    fix = [f for f in meta["build_findings"] if f["code"] == "build.fixup"]
    assert len(fix) == 1 and fix[0]["severity"] == "info"
    assert DANGLING_ERROR in fix[0]["message"] and "claude-haiku-4-5" in fix[0]["message"]

    # The build log records the fix-up as its own role, with its usage.
    log = _build_log(show)["build_log"]
    assert set(log) >= {"generator", "fixup"}
    assert log["fixup"]["usage"]["model"] == "claude-haiku-4-5"


def test_a_fixup_that_is_still_broken_fails_the_build_showing_both_rounds(
        show, monkeypatch, capsys):
    monkeypatch.delenv("ATOO_AI_FIXUP_ROUNDS", raising=False)
    still = _fixed()
    vox = next(c for c in still["channels"] if c["input"] == "VOX 1")
    vox["dca"] = ["Singers"]
    provider = _use(monkeypatch, _broken(), still)

    assert _build(show) == 2
    assert provider.labels == ["generator", "fixup"]      # one round, never a loop
    err = capsys.readouterr().err
    assert "Verification of the first reply -- 1 error(s)" in err
    assert DANGLING_ERROR in err
    assert "DCA 'Singers'" in err

    meta = json.loads((show / "plan.json").read_text())["meta"]
    assert [e["where"] for e in meta["verify_findings"]["errors"]] == ["channels[VOX 1].dca"]
    unresolved = [f for f in meta["build_findings"] if f["code"] == "build.fixup-unresolved"]
    assert len(unresolved) == 1 and DANGLING_ERROR in unresolved[0]["message"]


def test_fixup_rounds_zero_makes_no_second_call(show, monkeypatch, capsys):
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")
    provider = _use(monkeypatch, _broken(), _fixed())

    assert _build(show) == 2
    assert provider.labels == ["generator"]
    assert "fix-up" not in capsys.readouterr().err
    meta = json.loads((show / "plan.json").read_text())["meta"]
    assert not [f for f in meta["build_findings"] if f["code"].startswith("build.fixup")]


def test_a_format_failure_is_fixed_by_the_fixup(show, monkeypatch, capsys):
    """A reply the format check refuses -- here a DCA written as a string,
    not a list -- is sent back with the format check's message, and the
    corrected reply becomes the plan."""
    monkeypatch.delenv("ATOO_AI_FIXUP_ROUNDS", raising=False)
    slip = _fixed()
    slip["channels"][0]["dca"] = "Drums"
    provider = _use(monkeypatch, slip, _fixed())

    assert _build(show) == 0
    err = capsys.readouterr().err
    assert "fix-up: 1 format error sent back to claude-haiku-4-5" in err
    assert provider.labels == ["generator", "fixup"]
    assert "reply.channels[0].dca: expected array, got str" in provider.calls[1][1]
    meta = json.loads((show / "plan.json").read_text())["meta"]
    fix = [f for f in meta["build_findings"] if f["code"] == "build.fixup"]
    assert len(fix) == 1 and "the format check" in fix[0]["message"]


def test_a_format_failure_twice_fails_the_build_naming_both(show, monkeypatch, capsys):
    monkeypatch.delenv("ATOO_AI_FIXUP_ROUNDS", raising=False)
    slip = _fixed()
    slip["channels"][0]["dca"] = "Drums"
    provider = _use(monkeypatch, slip, "I cannot do that.")

    assert _build(show) == 1
    assert provider.labels == ["generator", "fixup"]
    err = capsys.readouterr().err
    assert "generation failed" in err
    assert "did not contain a usable plan" in err                 # the second round
    assert "reply.channels[0].dca: expected array, got str" in err  # and the first
    assert not (show / "plan.json").exists()


def test_a_warnings_only_plan_triggers_no_fixup(show, monkeypatch, capsys):
    """Two strips off one socket is a WARNING (`patch.socket-shared`): a
    judgement to confirm, not an error, so nothing is sent back."""
    monkeypatch.delenv("ATOO_AI_FIXUP_ROUNDS", raising=False)
    # VOX 1's socket left to the model, which puts it on BassDI's.
    csv = show / "input.csv"
    csv.write_text(csv.read_text().replace("LCL 12,VOX 1", ",VOX 1"))
    shared = _fixed()
    shared["channels"][2]["patch"] = {"group": "LCL", "sockets": [7]}
    provider = _use(monkeypatch, shared)

    assert _build(show) == 0
    assert provider.labels == ["generator"]
    meta = json.loads((show / "plan.json").read_text())["meta"]
    assert meta["verify_findings"]["warnings"]
    assert "fix-up" not in capsys.readouterr().err


def test_a_strip_that_reaches_nothing_is_sent_back_as_a_warning(show, monkeypatch, capsys):
    """Smallband on Haiku, 2026-09-29: the Playback aux was routed nowhere,
    a warning, so no fix-up ran and the strip stayed silent. That warning
    (`routing.channel-reaches-nothing`) is a routing slip, not a judgement
    call, and it now spends the round, marked as a warning."""
    monkeypatch.delenv("ATOO_AI_FIXUP_ROUNDS", raising=False)
    silent = _fixed()
    silent["channels"][0]["main_routes"] = []            # Kick, heard by no one
    provider = _use(monkeypatch, silent, _fixed())

    assert _build(show) == 0
    err = capsys.readouterr().err
    assert "fix-up: 1 routing warning sent back to claude-haiku-4-5" in err
    assert provider.labels == ["generator", "fixup"]
    system, user = provider.calls[1]
    assert "routing.channel-reaches-nothing; a warning, not a refusal" in user
    assert "Only if the show means it" in system

    meta = json.loads((show / "plan.json").read_text())["meta"]
    assert not [w for w in meta["verify_findings"]["warnings"]
                if w["code"] == "routing.channel-reaches-nothing"]
    [fix] = [f for f in meta["build_findings"] if f["code"] == "build.fixup"]
    assert "found 0 error(s) and 1 routing warning(s)" in fix["message"]


def test_a_strip_left_silent_by_the_fixup_is_said_and_the_build_still_passes(
        show, monkeypatch, capsys):
    """The model may mean a strip to be silent: the warning stands, the
    plan is written, and the round says it did not change it."""
    monkeypatch.delenv("ATOO_AI_FIXUP_ROUNDS", raising=False)
    silent = _fixed()
    silent["channels"][0]["main_routes"] = []
    provider = _use(monkeypatch, silent, silent)

    assert _build(show) == 0
    assert provider.labels == ["generator", "fixup"]     # one round, never a loop
    meta = json.loads((show / "plan.json").read_text())["meta"]
    [fix] = [f for f in meta["build_findings"] if f["code"] == "build.fixup-unresolved"]
    assert fix["severity"] == "warning" and "still has 1 of them" in fix["message"]


def test_a_stop_during_the_fixup_is_a_stopped_build(show, monkeypatch, capsys):
    monkeypatch.delenv("ATOO_AI_FIXUP_ROUNDS", raising=False)
    provider = _use(monkeypatch, _broken(), _fixed())
    real = provider.complete

    def stop_on_fixup(**kw):
        if kw.get("label") == "fixup":
            raise BuildStopped("stopped by you")
        return real(**kw)

    monkeypatch.setattr(provider, "complete", stop_on_fixup)
    assert _build(show) == 130
    assert "stopped" in capsys.readouterr().err.lower()
    assert not (show / "plan.json").exists()
    logs = list((show / "builds").glob("*.json"))
    assert len(logs) == 1 and json.loads(logs[0].read_text())["outcome"]["status"] == "stopped"


def test_critic_findings_are_never_fed_back(show, monkeypatch):
    """A passing plan with a critic that objects: the critic runs once,
    after verify, and no fix-up follows -- its findings are opinion."""
    monkeypatch.delenv("ATOO_AI_FIXUP_ROUNDS", raising=False)
    critique = json.dumps({"findings": [{"severity": "error", "kind": "intent",
                                         "where": "Kick", "message": "HPF should be 60"}]})
    provider = _use(monkeypatch, _fixed(), critique)
    code = main(["build", "--console-model", "wing-compact",
                 "--input", str(show / "input.csv"),
                 "--conventions", str(show / "conventions.md"),
                 "--critic", "--out", str(show / "plan.json")])
    assert code == 0
    assert provider.labels == ["generator", "critic"]


@pytest.mark.parametrize("raw, want", [("", 1), ("0", 0), ("1", 1), ("3", 1),
                                       ("-2", 0), ("lots", 1)])
def test_fixup_rounds_setting(raw, want):
    assert generate.fixup_rounds({"ATOO_AI_FIXUP_ROUNDS": raw}) == want


def test_the_fixup_prompt_is_short():
    """It is paid for on every fix-up, on top of the generator's prompt."""
    assert len(generate.load_prompt("plan_fixup.md")) < 1500
