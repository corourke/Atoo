"""The critic runs before the fix-up round, and an omission quoting a line
of the instructions or conventions verbatim joins that one round.

A build whose model dropped "Video Feed: Send the main mix to USB 18-19"
and whose critic said so, quoting the line, sends the line back with
verify's errors; the corrected plan is kept only when verify finds it no
worse, and each omission is checked again against the plan written, with
no second critic call.

The show is `tests/fixtures/video-feed/`'s input list and instructions; the
model's replies and the critic's are scripted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from atoo.ai_provider import FakeProvider
from atoo.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "video-feed"
LINE = "Video Feed: Send the main mix to USB 18-19"
CONVENTIONS = """# House conventions

- Main 1 is named PA, on LCL 1 and 2.
"""

INPUTS = ["Kick", "Snare", "Rack Tom", "Floor Tom", "OH L", "OH R", "Bass DI", "Gtr 1",
          "Gtr 2", "Keys L", "Keys R", "Lead Vox", "BV Gtr", "BV Keys", "Playback L",
          "Playback R"]


def _reply(main_patches: list | None = None, extra_runs: list | None = None) -> str:
    main = {"name": "PA", "kind": "main", "index": 1, "patch": {"group": "LCL", "sockets": [1, 2]}}
    if main_patches:
        main["patches"] = main_patches
    return json.dumps({
        "channels": [{"input": name, "main_routes": [{"index": 1}]} for name in INPUTS],
        "busses": [],
        "outputs": [main],
        "unassigned_inputs": [],
        "output_runs": [{
            "to": "USB 1", "from": "inputs",
            "quote": "Recording split: patch every input socket connected to a channel to USB "
                     "out starting at USB 1, sequentially in channel order."}]
        + (extra_runs or []),
        "notes": [],
    })


FIRST = _reply()
FIXED = _reply([{"group": "LCL", "sockets": [1, 2]}, {"group": "USB", "sockets": [18, 19]}])


def _critic(quote: str) -> str:
    return json.dumps({"findings": [
        {"severity": "warning", "kind": "omission", "where": "PA",
         "claim": "Main not sent to USB 18-19", "message": "The instructions ask for a video feed.",
         "quotes": [quote]},
        {"severity": "info", "kind": "intent", "where": "Kick", "claim": "No high-pass",
         "message": "An opinion, never sent back."}]})


@dataclass
class _Scripted(FakeProvider):
    script: list[str] = field(default_factory=list)
    model: str = "stand-in"

    def complete(self, *, system, user, response_schema=None, label=""):
        self.response = self.script[len(self.calls)]
        return super().complete(system=system, user=user, response_schema=response_schema,
                                label=label)


def _build(tmp_path, monkeypatch, script: list[str]) -> tuple[int, dict, _Scripted]:
    show = tmp_path / "video-feed"
    show.mkdir()
    for name in ("input.csv", "instructions.md"):
        (show / name).write_bytes((FIXTURE / name).read_bytes())
    conventions = tmp_path / "conventions.md"
    conventions.write_text(CONVENTIONS)
    provider = _Scripted(script=script)
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "1")
    monkeypatch.setattr("atoo.generate.draft_watch_conditions", lambda *a, **k: [])
    status = main(["build", "--show", str(show), "--console-model", "wing-full",
                   "--conventions", str(conventions), "--critic"])
    plan = json.loads((show / "plan.json").read_text())
    return status, plan, provider


def _main_sockets(plan: dict) -> list:
    main = plan["outputs"]["PA"]
    return [(p["group"], p["sockets"]) for p in main.get("patches") or [main["patch"]]]


def _codes(findings: list[dict]) -> list[str]:
    return [f["code"] for f in findings]


def test_a_quoted_omission_is_sent_to_the_fixup_and_carried_out(tmp_path, monkeypatch):
    status, plan, provider = _build(tmp_path, monkeypatch, [FIRST, _critic(LINE), FIXED])
    assert status == 0
    # The critic read the first plan, then the round ran: no second critic call.
    assert provider.labels == ["generator", "critic", "fixup"]
    _, user = provider.calls[2]
    assert f"PA: Main not sent to USB 18-19 -- not carried out: '{LINE}' (critic.omission)" in user
    assert "No high-pass" not in user
    assert ("USB", [18, 19]) in _main_sockets(plan)
    assert plan["meta"]["verify_findings"]["errors"] == []
    [repair] = [f for f in plan["meta"]["build_findings"] if f["code"] == "build.critic-repair"]
    assert repair["severity"] == "info" and repair["line"] == LINE
    assert repair["message"] == (
        f"the critic found '{LINE}' not carried out in the first reply (Main not sent to USB "
        "18-19); the fix-up round carried it out: the plan written patches USB 18-19")
    [fixup] = [f for f in plan["meta"]["build_findings"] if f["code"].startswith("build.fixup")]
    assert fixup["code"] == "build.fixup" and fixup["message"].startswith(
        "the critic found 1 line(s) of the instructions or conventions not carried out in the "
        "first reply; one fix-up round sent them back")
    # Carried out, so it is no longer the critic's: only its opinion stays,
    # saying it was about the first plan, which the round replaced.
    [opinion] = plan["meta"]["critic_findings"]
    assert opinion["code"] == "critic.intent"
    assert opinion["title"] == "On the first plan: No high-pass"


def test_a_line_code_cannot_check_is_not_claimed_as_carried_out(tmp_path, monkeypatch):
    # The conventions' Main line names LCL 1-2, which the first plan already
    # patches, so code cannot tell whether the round did what was missing.
    line = "Main 1 is named PA, on LCL 1 and 2."
    status, plan, provider = _build(tmp_path, monkeypatch, [FIRST, _critic(line), FIXED])
    assert provider.labels == ["generator", "critic", "fixup"]
    [repair] = [f for f in plan["meta"]["build_findings"] if f["code"] == "build.critic-repair"]
    assert repair["severity"] == "info"
    assert repair["message"] == (
        f"the critic found '{line}' not carried out in the first reply (Main not sent to USB "
        "18-19); the fix-up round was asked to carry it out, and code can't check this kind of "
        "line, so confirm it in the plan or at soundcheck")
    assert "carried it out" not in repair["message"]


def test_an_omission_whose_quote_is_not_verbatim_is_not_sent(tmp_path, monkeypatch):
    status, plan, provider = _build(
        tmp_path, monkeypatch, [FIRST, _critic("Send the main mix to the video desk on USB 18-19")])
    assert status == 0
    assert provider.labels == ["generator", "critic"]
    assert ("USB", [18, 19]) not in _main_sockets(plan)
    assert not [f for f in plan["meta"]["build_findings"]
                if f["code"].startswith(("build.fixup", "build.critic-repair"))]
    omission = plan["meta"]["critic_findings"][0]
    assert omission["code"] == "critic.omission" and omission["severity"] == "warning"
    # No round ran, so the plan is the one the critic read.
    assert omission["title"] == "Main not sent to USB 18-19"


def test_a_repaired_plan_worse_on_verify_is_not_kept(tmp_path, monkeypatch):
    # The corrected reply carries the line out, but adds a feed past the
    # last USB socket: verify refuses it, so the first plan stands.
    worse = _reply([{"group": "LCL", "sockets": [1, 2]}, {"group": "USB", "sockets": [18, 19]}],
                   [{"to": "USB 48", "from": "AES50-A 1", "count": 2, "quote": "A spare feed."}])
    status, plan, provider = _build(tmp_path, monkeypatch, [FIRST, _critic(LINE), worse])
    assert provider.labels == ["generator", "critic", "fixup"]
    assert ("USB", [18, 19]) not in _main_sockets(plan)
    assert plan["meta"]["verify_findings"]["errors"] == []
    [fixup] = [f for f in plan["meta"]["build_findings"] if f["code"].startswith("build.fixup")]
    assert fixup["code"] == "build.fixup-rejected" and fixup["severity"] == "warning"
    assert "worse on verify" in fixup["message"] and LINE in fixup["message"]
    assert not [f for f in plan["meta"]["build_findings"] if f["code"] == "build.critic-repair"]
    [omission] = [f for f in plan["meta"]["critic_findings"] if f["code"] == "critic.omission"]
    assert omission["severity"] == "warning"
    assert omission["message"].endswith("still not carried out after the fix-up round")


def test_an_omission_of_an_input_list_row_is_reported_not_sent():
    """Only a line of the instructions or conventions steers the build: an
    omission quoting nothing, or the input list, is the critic's report."""
    from atoo import conventions_audit, generate

    layers = conventions_audit.layers_for(CONVENTIONS, "conventions.md",
                                          (FIXTURE / "instructions.md").read_text(),
                                          "instructions.md")
    raw = json.dumps({"findings": [
        {"kind": "omission", "where": "Guest Vox", "claim": "Guest Vox not built"},
        {"kind": "omission", "where": "Guest Vox", "claim": "Guest Vox not built",
         "quotes": ["AES50-A 16,Guest Vox,vocals"]},
        {"kind": "omission", "where": "PA", "claim": "No video feed", "quotes": LINE}]})
    findings = generate.parse_critic_findings(raw, layers=layers)
    assert [f.line for f in findings] == ["", "", LINE]


def test_a_split_that_leaves_inputs_out_says_which():
    """A recording split counted short of every input names what it left
    out: the model weighed the Music aux against the video feed's sockets."""
    from atoo.reply_expand import expand_output_runs

    plan = json.loads((FIXTURE / "plan.json").read_text())
    plan["output_runs"] = [{"to": "USB 1", "from": "inputs", "count": 16,
                            "quote": "Recording split: patch every input socket connected to a "
                                     "channel to USB out starting at USB 1"}]
    findings: list = []
    assert expand_output_runs(plan, findings) == 16
    [said] = findings
    assert said.code == "inferred.output-run"
    assert said.message.endswith(
        "; its count of 16 leaves out 2 of the 18 input sockets the channels are patched from: "
        "LCL 3 and LCL 4 (Music)")
