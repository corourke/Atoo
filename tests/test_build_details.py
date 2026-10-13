"""An earlier change and an earlier change.

#510: some INFOs say how Atoo read the model's reply, not a choice
an engineer might disagree with. `finding_groups` names them (build
details) and the page reads the list from its startup data. Only an INFO
is ever one.

#514: the critic writes a short `claim`, carried as the finding's
`title`, with its reasoning as `message`.

Nothing here reads `examples/`: the findings are built in the test, or
come from the frozen `tests/fixtures/sixpiece_2026-10-01.plan.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import diagnostics, finding_groups, generate
from atoo.diagnostics import Diagnostic, Severity

FIXTURE = Path(__file__).parent / "fixtures" / "sixpiece_2026-10-01.plan.json"


# ---- #510: which findings are build details ----------------------------

@pytest.mark.parametrize("code", sorted(finding_groups.BUILD_DETAIL_CODES))
def test_a_build_detail_is_an_info_with_one_of_the_codes(code):
    assert finding_groups.is_build_detail({"severity": "info", "code": code})
    assert finding_groups.is_build_detail(Diagnostic(Severity.INFO, code, "m"))


@pytest.mark.parametrize("severity", ["warning", "error"])
@pytest.mark.parametrize("code", sorted(finding_groups.BUILD_DETAIL_CODES))
def test_a_warning_or_error_is_never_a_build_detail(code, severity):
    # Never hide an ERROR or WARNING, whatever its code says.
    assert not finding_groups.is_build_detail({"severity": severity, "code": code})
    assert not finding_groups.is_build_detail(Diagnostic(Severity(severity), code, "m"))


@pytest.mark.parametrize("code", [
    # Choices an engineer might disagree with: announced at INFO and shown
    # as choices (CLAUDE.md's INFO principle).
    # (`reply.category-rule` was one: it is the Category
    # table obeyed, so a build detail now.) The FX notes that ARE choices
    # stay choices.
    "inferred.bus-width", "inferred.output-index", "reply.sockets-chosen",
    "fx.engine-allocated", "fx.insert-switched-on", "preset.overridden", "apply.unbuilt-strips",
    "apply.talkback-assign", "critic.conventions",
    # A fix-up round that did NOT fix everything is a WARNING code.
    "build.fixup-unresolved",
])
def test_choices_are_not_build_details(code):
    assert not finding_groups.is_build_detail({"severity": "info", "code": code})


def test_every_build_detail_code_has_words_for_its_row():
    # The page's fold shows one row per code with these words; a code
    # without them would read "N notes: reply.sends-expanded".
    assert not finding_groups.BUILD_DETAIL_CODES - set(finding_groups.CODE_SUMMARIES)


def test_on_a_real_plan_only_the_plumbing_is_a_build_detail():
    from atoo.webui import _plan_findings

    plan = json.loads(FIXTURE.read_text())
    shown = _plan_findings(plan)
    details = [f for f in shown if finding_groups.is_build_detail(f)]
    # The Category table obeyed (seven categories) and the
    # preset values carried (build and verify, one row each) are build
    # details too.
    assert sorted(set(f["code"] for f in details)) == [
        "preset.expanded", "reply.category-rule", "reply.channels-numbered",
        "reply.sends-expanded"]
    # Every warning the plan carries stays out of the fold.
    assert all(f["severity"] == "info" for f in details)
    assert [f for f in shown if f["severity"] == "warning"]


def test_repair_notes_are_build_details_and_model_notes_are_not():
    assert finding_groups.is_detail_note({"text": "reply: 'x' left out once", "source": "repair"})
    assert not finding_groups.is_detail_note({"text": "Drums Comp: No Stressor", "source": "model"})
    assert not finding_groups.is_detail_note("a bare-string note")
    assert finding_groups.DETAIL_NOTE_SOURCES <= set(
        __import__("atoo.plan_schema", fromlist=["NOTE_SOURCES"]).NOTE_SOURCES)


def test_the_page_gets_both_lists_from_python():
    from conftest import require_fastapi_testclient
    from atoo.webui import create_app

    testclient = require_fastapi_testclient()
    with testclient.TestClient(create_app()) as c:
        page = c.get("/").text
    blob = page.split('id="initial-shell"', 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    startup = json.loads(blob)
    assert startup["build_detail_codes"] == sorted(finding_groups.BUILD_DETAIL_CODES)
    assert startup["detail_note_sources"] == ["repair"]


# ---- #514: the critic's claim ------------------------------------------

def _reply(**finding) -> str:
    return json.dumps({"findings": [finding]})


def test_the_critics_claim_is_the_findings_title_and_message_its_reasoning():
    [f] = generate.parse_critic_findings(_reply(
        severity="warning", kind="intent", where="Keys bus",
        claim="Keys bus created,\n but there is only one keyboard.",
        message="The conventions make a Keys bus only for several keyboards."))
    assert f.title == "Keys bus created, but there is only one keyboard"
    assert f.message == "The conventions make a Keys bus only for several keyboards."
    assert f.to_dict()["title"] == f.title


def test_a_critic_reply_without_a_claim_still_reads():
    [f] = generate.parse_critic_findings(_reply(
        severity="warning", kind="intent", where="TRAX", message="gain not set"))
    assert f.title == ""
    assert "title" not in f.to_dict()
    [g] = generate.parse_critic_findings(_reply(
        severity="info", kind="intent", where="TRAX", message="m", claim=["not", "text"]))
    assert g.title == ""


def test_the_terminal_prints_the_claim_first():
    [f] = generate.parse_critic_findings(_reply(
        severity="warning", kind="intent", where="TRAX channel",
        claim="TRAX gain not set (conventions: 20 dB)",
        message="It is on a stage-box line input, which has a head amp."))
    text = diagnostics.render([f])
    first = text.splitlines()[0]
    assert "TRAX gain not set (conventions: 20 dB) -- TRAX channel:" in first


def test_a_quote_checked_conventions_finding_keeps_its_claim():
    from atoo import conventions_audit

    layer = conventions_audit.Layer(role="conventions", name="c.md",
                                    text="## DCAs\n- Speech DCA for talk mics\n")
    [f] = generate.parse_critic_findings(_reply(
        severity="info", kind="conventions", where="DCAs", claim="Speech DCA declared, never used",
        message="No speech channel in this show.", quotes=["Speech DCA for talk mics"]),
        layers=[layer])
    assert f.title == "Speech DCA declared, never used"


def test_the_prompt_asks_for_a_short_claim_and_no_field_names():
    crit = " ".join(generate.critic_system().split())
    assert '"claim": "what is wrong, in at most ten words"' in crit
    assert "never a field name" in crit
