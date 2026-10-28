"""The resolved conventions (2026-09-30, `atoo/conventions_resolve.py`).

One `resolve` call restates the house conventions and the domain knowledge
as cited rules in `<conventions>.resolved.md`; code checks every citation
and every conventions line; `build` gives the generator and the fix-up
that text in place of both, resolving first when it is missing or stale;
the critic keeps the raw conventions; `--no-resolve` turns it off.

No model is called: providers are scripted, one reply per call, as in
`tests/test_fixup_round.py`. The show is three rows frozen under
`tests/fixtures/`, and every conventions and resolved text is written
here; nothing reads `examples/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from atoo import conventions_audit, conventions_resolve, generate, instructed_channels
from atoo.ai_provider import AIProviderError, ClaudeProvider, FakeProvider, provider_from_env
from atoo.cli import main
from atoo.diagnostics import Severity

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CSV = FIXTURES / "haiku45_festival_dangling_dca.csv"
REPLY = FIXTURES / "haiku45_festival_dangling_dca.reply.json"

CONVENTIONS = """# House conventions

<!-- A note to myself: never read. -->

## Groups
- DCAs: Drums (all drum channels), Bass, Vocals (all vocal channels).
- Mute groups: Band (all band instruments), Vocals.

## Outputs
- Main is on LCL 7/8.
- Talkback mic on channel 40, source A 40.
- We usually have a good time.
"""

# What a resolve call might write for CONVENTIONS: every line cited or
# listed as having no effect, a "Decided:", and a domain citation.
RESOLVED_REPLY = """## Categories
### Drums
- DCA: Drums. [conventions: "Drums (all drum channels)"]
- Mute group: Band. Decided: drums are band instruments. [conventions: "Band (all band instruments)"] [domain: "\"Band\" usually means all instruments"]
### Bass
- DCA: Bass. [conventions: "DCAs: Drums (all drum channels), Bass, Vocals (all vocal channels)."]
### Vocals
- DCA: Vocals; mute group: Vocals. [conventions: "Mute groups: Band (all band instruments), Vocals."]

## Outputs
- Main: patch to LCL 7 and LCL 8. [conventions: "Main is on LCL 7/8."]
- Talkback: a mic on channel 40 from AES50-A 40, feeding monitors only. Decided: not to Main. [conventions: "Talkback mic on channel 40, source A 40."]

## Lines with no effect
- [conventions: "We usually have a good time."] a remark, not a setting.
"""


def _reply(fixed: bool = True) -> dict:
    reply = json.loads(REPLY.read_text())
    for channel in reply["channels"]:
        channel["main_routes"] = channel.get("main_routes") or [{"index": 1}]
    if fixed:
        bass = next(c for c in reply["channels"] if c["input"] == "BassDI")
        bass["dca"] = ["Bass"]
    return reply


@dataclass
class ScriptedProvider(FakeProvider):
    script: list[str] = field(default_factory=list)
    stream_chunks: int = 2
    model: str = "claude-sonnet-5"

    def complete(self, *, system, user, response_schema=None, label=""):
        if len(self.calls) >= len(self.script):
            raise AIProviderError("the script has no reply for this call")
        self.response = self.script[len(self.calls)]
        return super().complete(system=system, user=user,
                                response_schema=response_schema, label=label)


@pytest.fixture
def show(tmp_path, monkeypatch):
    monkeypatch.delenv("ATOO_RESOLVE", raising=False)
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "1")
    (tmp_path / "input.csv").write_text(CSV.read_text())
    (tmp_path / "conventions.md").write_text(CONVENTIONS)
    return tmp_path


def _use(monkeypatch, *replies) -> ScriptedProvider:
    provider = ScriptedProvider(script=[r if isinstance(r, str) else json.dumps(r)
                                        for r in replies])
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    return provider


def _build(show, *extra) -> int:
    return main(["build", "--console-model", "wing-compact",
                 "--input", str(show / "input.csv"),
                 "--conventions", str(show / "conventions.md"),
                 "--out", str(show / "plan.json"), *extra])


def _meta(show) -> dict:
    return json.loads((show / "plan.json").read_text())["meta"]


def _write_resolved(show, body: str = RESOLVED_REPLY) -> Path:
    """A fresh resolved file, as a resolve call would have left it."""
    text = conventions_resolve.run(CONVENTIONS, "conventions.md",
                                   provider=FakeProvider(response=body),
                                   now="2026-09-30T00:00:00Z")
    path = show / "conventions.resolved.md"
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# the check
# ---------------------------------------------------------------------------

def test_a_complete_resolution_checks_clean():
    result = conventions_resolve.check(RESOLVED_REPLY, CONVENTIONS,
                                       conventions_name="conventions.md")
    assert result.usable
    assert result.findings == []
    assert result.uncovered == []
    # Headings, the blank lines and the comment are not lines to cover.
    assert result.substantive == 5
    kinds = {c.kind for c in result.citations}
    assert kinds == {"conventions", "domain"} and all(c.found for c in result.citations)


# The maintainer's first real resolve, 2026-09-30: 46 of 173 citations "not
# found" and 14 lines "uncovered", every one a quote the checker misread.
# The model had retyped a line's double quotes as single ones, joined two
# quotes as "a" / "b", elided a middle with "...", escaped a quote, and
# quoted a domain sentence across its line wrap. Real lines, real quotes.
REAL_CONVENTIONS = """# Conventions
## Colours
- Color coding: Drums-Red, Bass-Blue, Vocals-Green, Speech-Purple
## Busses
- Sends to these busses are generally at unity, POST fader, unless noted below.
  - "VOX Reverb" -- All vocal channels
  - "Snare Verb" -- Snare channels. Sends from channels at -10db, PRE fader.
  - If there are multiple horns, create a "Horns" bus.
"""
REAL_REPLY = """## Busses
- VOX Reverb: every vocal channel, unity, POST. [conventions: "'VOX Reverb' -- All vocal channels" / "Sends to these busses are generally at unity, POST fader, unless noted below."]
- Snare Verb: snare at -10 dB PRE. [conventions: "'Snare Verb' -- Snare channels. Sends from channels at -10db, PRE fader."]
- Horns bus with two or more horns. [conventions: "If there are multiple horns, create a \\"Horns\\" bus."]
## Categories
- Colours by category. [conventions: "Color coding: Drums-Red...Speech-Purple"]
- Band covers the music. [domain: "'Band' usually means all instruments (drums, bass, guitars, keyboards, and any strings or brass) plus the vocals and any backing tracks -- everything that makes up the music."]
- Click and guide. [domain: "If there are multiple track channels, there may be a channel called click, or guide, or a combination of the two."]
## Lines with no effect
"""


def test_the_ways_a_model_retypes_a_quote_are_all_found():
    result = conventions_resolve.check(REAL_REPLY, REAL_CONVENTIONS,
                                       conventions_name="conventions.md")
    assert [c.quote for c in result.missing] == []
    assert result.uncovered == []
    assert len(result.citations) == 7            # the joined citation is two


def test_a_quote_that_is_not_there_is_a_warning_and_the_file_is_still_used():
    text = RESOLVED_REPLY.replace('"Main is on LCL 7/8."', '"Main goes to LCL 7 and 8."')
    result = conventions_resolve.check(text, CONVENTIONS, conventions_name="conventions.md")
    assert result.usable
    codes = [(f.code, f.severity) for f in result.findings]
    assert (conventions_resolve.CODE_QUOTE, Severity.WARNING) in codes
    missing = [f for f in result.findings if f.code == conventions_resolve.CODE_QUOTE]
    assert missing[0].line == "Main goes to LCL 7 and 8." and missing[0].category == "Outputs"
    # ...and the line it failed to cite is now uncovered, so it is said too.
    assert result.uncovered == ["- Main is on LCL 7/8."]


def test_an_uncovered_line_is_an_info_and_reaches_the_generator_verbatim():
    text = RESOLVED_REPLY.replace('- [conventions: "We usually have a good time."] a remark, '
                                  'not a setting.\n', "")
    result = conventions_resolve.check(text, CONVENTIONS, conventions_name="conventions.md")
    assert result.usable
    assert [f.code for f in result.findings] == [conventions_resolve.CODE_UNCOVERED]
    assert result.findings[0].line == "- We usually have a good time."
    body = conventions_resolve.prompt_text(text, result.uncovered, "conventions.md")
    assert "## Conventions lines the rules above do not cover" in body
    assert body.rstrip().endswith("- - We usually have a good time.")


def test_a_short_fragment_covers_a_line_only_when_it_is_the_whole_line():
    conventions = "- Kick: Red\n- Snare: Red, and gate it\n"
    text = '- Kick is red [conventions: "Kick: Red"]\n- Snare [conventions: "Snare: Red"]\n'
    result = conventions_resolve.check(text, conventions)
    # "Kick: Red" is a whole line (its list marker aside); "Snare: Red"
    # is a two-word fragment of a longer one.
    assert result.uncovered == ["- Snare: Red, and gate it"]


def test_a_quote_across_two_lines_covers_both():
    conventions = "- Every channel sends to MON1,\n  pre fader, level down.\n"
    text = '- Monitors [conventions: "Every channel sends to MON1, pre fader, level down."]\n'
    assert conventions_resolve.check(text, conventions).uncovered == []


@pytest.mark.parametrize("text, why", [
    ("", "it is empty"),
    ("## Categories\n- Drums are red.\n", "it cites nothing"),
    ('- Drums are red. [conventions: "Drums are always crimson here"]\n',
     "none of its rules cites text that is in the conventions"),
])
def test_a_file_that_is_no_resolution_is_refused(text, why):
    result = conventions_resolve.check(text, CONVENTIONS)
    assert not result.usable and result.refused.startswith(why)
    assert any(f.code == conventions_resolve.CODE_REFUSED for f in result.findings)


def test_the_header_is_never_given_to_the_generator():
    text = conventions_resolve.run(CONVENTIONS, "conventions.md",
                                   provider=FakeProvider(response=RESOLVED_REPLY))
    header = conventions_resolve.parse_header(text)
    assert set(conventions_resolve.FINGERPRINT_KEYS) <= set(header)
    assert header["conventions"] == "conventions.md" and header["model"] == "fake"
    assert "sha256" not in conventions_resolve.prompt_text(text, [], "conventions.md")


def test_a_fenced_reply_is_unwrapped():
    text = conventions_resolve.run(
        CONVENTIONS, "conventions.md",
        provider=FakeProvider(response="```markdown\n" + RESOLVED_REPLY + "```\n"))
    assert "```" not in text
    assert conventions_resolve.check(text, CONVENTIONS).findings == []


# ---------------------------------------------------------------------------
# freshness
# ---------------------------------------------------------------------------

def test_freshness_follows_the_conventions_the_domain_and_the_prompt(show, monkeypatch, tmp_path):
    conventions = show / "conventions.md"
    assert conventions_resolve.freshness(conventions, CONVENTIONS).state == "missing"
    _write_resolved(show)
    assert conventions_resolve.freshness(conventions, CONVENTIONS).fresh

    # A comment is a note, not a rule: editing one costs no re-resolve.
    noted = CONVENTIONS.replace("never read", "still never read")
    assert conventions_resolve.freshness(conventions, noted).fresh

    changed = conventions_resolve.freshness(conventions, CONVENTIONS + "- Kick is red.\n")
    assert changed.state == "stale" and changed.reason == "the conventions changed"

    monkeypatch.setattr(generate, "_domain_knowledge", lambda: "# Other knowledge\n")
    assert conventions_resolve.freshness(conventions, CONVENTIONS).reason \
        == "the domain knowledge changed"
    monkeypatch.undo()

    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for f in generate._DEFAULT_PROMPT_DIR.glob("*.md"):
        (prompts / f.name).write_text(f.read_text())
    (prompts / conventions_resolve.PROMPT).write_text("Resolve them differently.\n")
    monkeypatch.setenv("ATOO_PROMPT_DIR", str(prompts))
    assert conventions_resolve.freshness(conventions, CONVENTIONS).reason \
        == "the resolve prompt changed"


def test_the_resolved_file_sits_beside_the_conventions():
    assert conventions_resolve.resolved_path("examples/conventions.md") \
        == Path("examples/conventions.resolved.md")


# ---------------------------------------------------------------------------
# the build
# ---------------------------------------------------------------------------

def test_a_build_with_no_resolved_file_resolves_first_and_the_generator_reads_it(
        show, monkeypatch, capsys):
    provider = _use(monkeypatch, RESOLVED_REPLY, _reply())

    assert _build(show) == 0
    err = capsys.readouterr().err
    assert "conventions.resolved.md is missing" in err and "role resolve" in err

    assert provider.labels == ["resolve", "generator"]
    system, user = provider.calls[0]
    assert "Lines with no effect" in system
    assert "We usually have a good time." in user and "# Audio domain knowledge" in user
    assert "A note to myself" not in user           # comments never reach a model

    resolved = show / "conventions.resolved.md"
    header = conventions_resolve.parse_header(resolved.read_text())
    assert header["model"] == "claude-sonnet-5"

    _system, user = provider.calls[1]
    assert "# The engineer's conventions, resolved (conventions.resolved.md)" in user
    assert "Decided: drums are band instruments" in user
    assert "# Domain knowledge" not in user
    assert "# The engineer's conventions (conventions.md)" not in user

    meta = _meta(show)
    record = meta["resolved_conventions"]
    assert record["used"] is True and record["made_in_this_build"] is True
    assert record["fingerprint"]["conventions_sha256"] == header["conventions_sha256"]
    assert record["lines_not_covered"] == 0 and record["quotes_not_found"] == 0
    log = json.loads((show / meta["build_log_file"]).read_text())
    assert "resolve" in log["build_log"]


def test_a_fresh_resolved_file_costs_no_call(show, monkeypatch, capsys):
    _write_resolved(show)
    provider = _use(monkeypatch, _reply())

    assert _build(show) == 0
    assert provider.labels == ["generator"]
    assert "is fresh" in capsys.readouterr().err
    record = _meta(show)["resolved_conventions"]
    assert record["used"] and record["made_in_this_build"] is False


def test_a_stale_resolved_file_is_made_again(show, monkeypatch):
    path = _write_resolved(show)
    (show / "conventions.md").write_text(CONVENTIONS.replace("7/8", "9/10"))
    provider = _use(monkeypatch, RESOLVED_REPLY.replace("7/8", "9/10"), _reply())

    assert _build(show) == 0
    assert provider.labels == ["resolve", "generator"]
    assert conventions_resolve.freshness(show / "conventions.md",
                                         (show / "conventions.md").read_text()).fresh
    assert "9/10" in path.read_text()


@pytest.mark.parametrize("how", ["flag", "env"])
def test_no_resolve_gives_the_generator_the_raw_texts(show, monkeypatch, how):
    _write_resolved(show)
    provider = _use(monkeypatch, _reply())
    extra = ["--no-resolve"] if how == "flag" else []
    if how == "env":
        monkeypatch.setenv("ATOO_RESOLVE", "0")

    assert _build(show, *extra) == 0
    assert provider.labels == ["generator"]
    _system, user = provider.calls[0]
    assert "# Domain knowledge" in user and "# The engineer's conventions (conventions.md)" in user
    assert "Decided:" not in user
    record = _meta(show)["resolved_conventions"]
    assert record == {"used": False,
                      "reason": "--no-resolve" if how == "flag" else "ATOO_RESOLVE=0"}


def test_a_failed_resolve_call_falls_back_to_the_raw_texts(show, monkeypatch):
    provider = _use(monkeypatch, _reply())

    def complete(*, system, user, response_schema=None, label=""):
        if label == "resolve":
            raise AIProviderError("overloaded")
        return ScriptedProvider.complete(provider, system=system, user=user,
                                         response_schema=response_schema, label=label)

    monkeypatch.setattr(provider, "complete", complete)
    assert _build(show) == 0
    _system, user = provider.calls[0]
    assert "# Domain knowledge" in user
    meta = _meta(show)
    assert meta["resolved_conventions"] == {"used": False, "reason": "the resolve call failed"}
    assert any(f["code"] == conventions_resolve.CODE_FAILED for f in meta["build_findings"])
    assert not (show / "conventions.resolved.md").exists()


def test_a_refused_resolution_is_written_but_not_used(show, monkeypatch):
    provider = _use(monkeypatch, "I could not do that.", _reply())
    assert _build(show) == 0
    _system, user = provider.calls[1]
    assert "# Domain knowledge" in user
    meta = _meta(show)
    assert meta["resolved_conventions"]["used"] is False
    assert any(f["code"] == conventions_resolve.CODE_REFUSED for f in meta["build_findings"])


def test_the_generator_reads_the_rules_without_their_citations(show, monkeypatch):
    """The citations were 60% of his resolved file,
    and every build paid for them. They stay in the file, for the check
    and for him; the generator gets the rules alone."""
    _write_resolved(show)
    provider = _use(monkeypatch, _reply())
    assert _build(show) == 0
    _system, user = provider.calls[0]
    assert "[conventions:" not in user and "[domain:" not in user
    assert "LCL 7/8" in user or "Main" in user                     # the rules are there
    assert "[conventions:" in (show / "conventions.resolved.md").read_text()


def test_the_findings_of_the_check_are_kept_in_the_plan(show, monkeypatch, capsys):
    partial = RESOLVED_REPLY.replace('- [conventions: "We usually have a good time."] a remark, '
                                     'not a setting.\n', "")
    provider = _use(monkeypatch, partial, _reply())
    assert _build(show) == 0
    _system, user = provider.calls[1]
    assert "- - We usually have a good time." in user
    codes = [f["code"] for f in _meta(show)["build_findings"]]
    assert conventions_resolve.CODE_UNCOVERED in codes
    # Kept in full, but a build prints them as one line (the maintainer,
    # 2026-09-30: sixty blocks before the generator had started).
    err = capsys.readouterr().err
    # An INFO: the line reaches the generator verbatim.
    assert ("INFO resolved conventions: 1 conventions line(s) cited by no rule, given to "
            "the generator verbatim") in err
    assert "citation(s) not found" not in err
    assert "(resolve.line-not-covered)" not in err


def test_the_fixup_reads_the_resolved_text_and_the_critic_the_raw(show, monkeypatch):
    _write_resolved(show)
    # The critic reads the first plan, before the fix-up round.
    provider = _use(monkeypatch, _reply(fixed=False), "[]", _reply())

    assert _build(show, "--critic") == 0
    assert provider.labels == ["generator", "critic", "fixup"]
    _system, fixup_user = provider.calls[2]
    assert "Decided: drums are band instruments" in fixup_user
    assert "# The engineer's conventions (conventions.md)" not in fixup_user
    _system, critic_user = provider.calls[1]
    assert "# The engineer's conventions (conventions.md)" in critic_user
    assert "# Domain knowledge" in critic_user and "Decided:" not in critic_user


# ---------------------------------------------------------------------------
# quotes of the resolved text
# ---------------------------------------------------------------------------

def _layers():
    return conventions_audit.layers_for(CONVENTIONS, "conventions.md", None, None,
                                        resolved=RESOLVED_REPLY,
                                        resolved_name="conventions.resolved.md")


def test_a_quote_of_a_resolved_rule_maps_back_to_the_raw_line_it_cites():
    spot = conventions_audit.locate("Main: patch to LCL 7 and LCL 8.", _layers())
    assert spot.role == "conventions" and spot.section == "Outputs"
    assert spot.raw_quote == "Main is on LCL 7/8." and spot.via == "conventions.resolved.md"

    plan = {"conventions_audit": [{"kind": "unused", "quotes": ["Main: patch to LCL 7 and LCL 8"],
                                   "message": "nothing else"}]}
    [finding] = conventions_audit.findings_from_plan(plan, _layers())
    assert finding.code == "conventions.unused"
    assert finding.line == "Main is on LCL 7/8." and finding.where == "conventions § Outputs"


def test_a_decision_with_no_raw_line_is_credited_to_the_resolved_file():
    text = RESOLVED_REPLY + "\n## Faders\n- Decided: every fader starts fully down.\n"
    layers = conventions_audit.layers_for(CONVENTIONS, "conventions.md", None, None,
                                          resolved=text, resolved_name="conventions.resolved.md")
    spot = conventions_audit.locate("every fader starts fully down", layers)
    assert spot.via == "conventions.resolved.md" and spot.raw_quote == ""
    assert conventions_audit._where(spot) == "conventions.resolved.md § Faders"


def test_a_raw_quote_is_still_credited_to_the_raw_file_first():
    spot = conventions_audit.locate("Main is on LCL 7/8.", _layers())
    assert spot.via == "" and spot.role == "conventions"


def test_an_instructed_channel_may_quote_the_resolved_rule():
    quote = "Talkback: a mic on channel 40 from AES50-A 40, feeding monitors only"
    layer = instructed_channels.find(quote, _layers())
    assert layer is not None and layer.role == "conventions"
    assert layer.name == "conventions.md (via conventions.resolved.md)"
    assert instructed_channels.sockets_for(quote, layer) == [("A", 40)]  # AES50-A 40
    assert instructed_channels.stated_channel(quote, layer) == 40
    # Without the resolved layer, the same words are nobody's.
    raw = conventions_audit.layers_for(CONVENTIONS, "conventions.md", None, None)
    assert instructed_channels.find(quote, raw) is None


def test_verify_reads_the_resolved_file_the_plan_records(show, tmp_path):
    path = _write_resolved(show)
    from atoo import conventions_ref
    plan = {"meta": {
        "conventions_stack": [{"path": str(show / "conventions.md"), "role": "conventions",
                               **conventions_ref.layer_record(show / "conventions.md", None)}],
        "resolved_conventions": {"used": True, **conventions_ref.layer_record(path, None)}}}
    layers = instructed_channels.layers_from_plan(plan)
    assert [layer.resolved for layer in layers] == [False, True]


# ---------------------------------------------------------------------------
# `atoo resolve`
# ---------------------------------------------------------------------------

def test_resolve_check_makes_no_call_and_says_how_the_file_stands(show, monkeypatch, capsys):
    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: pytest.fail("--check made a model call"))
    conventions = str(show / "conventions.md")
    assert main(["resolve", "--conventions", conventions, "--check"]) == 1
    assert "there is no resolved file yet" in capsys.readouterr().err

    _write_resolved(show)
    assert main(["resolve", "--conventions", conventions, "--check"]) == 0
    out = capsys.readouterr().out
    assert "fresh" in out and "8 of 8 citation(s) found; 5 of 5 conventions line(s)" in out

    (show / "conventions.md").write_text(CONVENTIONS + "- Kick is red.\n")
    assert main(["resolve", "--conventions", conventions, "--check"]) == 2
    captured = capsys.readouterr()
    assert "stale (the conventions changed)" in captured.out
    assert "- Kick is red." in captured.err


def test_resolve_always_makes_the_file_again(show, monkeypatch, capsys):
    _write_resolved(show, RESOLVED_REPLY.replace("Decided: not to Main", "Decided: monitors"))
    provider = _use(monkeypatch, RESOLVED_REPLY)
    assert main(["resolve", "--conventions", str(show / "conventions.md")]) == 0
    assert provider.labels == ["resolve"]
    assert "Decided: not to Main" in (show / "conventions.resolved.md").read_text()


# ---------------------------------------------------------------------------
# the role's model and effort
# ---------------------------------------------------------------------------

def test_the_resolve_role_runs_on_sonnet_at_high_whatever_the_generator():
    """The reading every build relies on gets the
    careful model, even when the generator is Haiku."""
    for generator in ("claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5"):
        provider = provider_from_env({"ATOO_AI_PROVIDER": "claude",
                                      "ANTHROPIC_API_KEY": "k", "ATOO_AI_MODEL": generator})
        assert isinstance(provider, ClaudeProvider)
        assert provider.model_for("resolve") == "claude-sonnet-5-5"
        assert provider.effort_for("resolve") == "medium"


def test_the_resolve_role_takes_its_own_model_and_effort():
    provider = provider_from_env({"ATOO_AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": "k",
                                  "ATOO_AI_MODEL": "claude-sonnet-5",
                                  "ATOO_AI_RESOLVE_MODEL": "claude-opus-5",
                                  "ATOO_AI_RESOLVE_EFFORT": "high"})
    assert provider.model_for("resolve") == "claude-opus-5"
    assert provider.effort_for("resolve") == "high"
    line = provider.effort_announcement(["resolve"])
    assert "resolve claude-opus-5 at high (ATOO_AI_RESOLVE_MODEL, " \
           "ATOO_AI_RESOLVE_EFFORT)" in line


def test_a_budget_model_thinks_for_the_resolve_step():
    provider = provider_from_env({"ATOO_AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": "k",
                                  "ATOO_AI_MODEL": "claude-haiku-4-5",
                                  "ATOO_AI_RESOLVE_MODEL": "claude-haiku-4-5"})
    assert provider.thinking_budget_for("resolve") is not None
    assert provider.thinking_budget_for("critic") is None


# ======================================================================
# The maintainer's resolve of 2026-10-01: 9 notes, every one a checker miss
# ======================================================================


@pytest.mark.parametrize("quote", [
    "there\\nmay be a channel called click, or guide, or a combination of the two",
    "Click and Guide\\nare for the musicians on stage only.",
    "A WING forms a stereo pair only from two **consecutive** sockets starting\\non an **odd** one",
    'Do not treat\\n\\"misc\\" as automatically meaning aux — look at what the source actually is.',
])
def test_a_line_break_written_as_backslash_n_is_whitespace(quote):
    """The model wrote the domain text's line wraps as the two characters
    `\\` `n`; the check dropped the backslash and read `therenmay`. The
    quotes are from the domain knowledge of that time, so the test reads the
    frozen copy of it beside the Demo fixture, not the shipped file."""
    from atoo import conventions_audit as ca
    frozen = Path(__file__).parent / "fixtures" / "demo_2026-10-13" / "knowledge.md"
    domain = ca.normalise(frozen.read_text())
    assert ca.contains(domain, ca._quote_core(quote))


def test_a_list_line_quoted_item_by_item_is_covered():
    conventions = ("## Channels\n- Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, "
                   "Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, "
                   "Tracks/Plaback-Yellow, Speech-Purple\n")
    items = ["Drums-Red", "Bass-Blue", "Guitars-Magenta", "Vocals-Green", "Speech-Purple"]
    assert conventions_resolve._covered_lines(conventions, items) == {1}
    # One item of eight is a word that happens to be there, not the line.
    assert conventions_resolve._covered_lines(conventions, ["Drums-Red"]) == set()
    # A part of an item is not an item.
    assert conventions_resolve._covered_lines(conventions, ["Red", "Blue", "Cyan", "Green",
                                                            "Purple"]) == set()


def test_the_fingerprint_is_the_same_whatever_the_line_endings_or_unicode_form():
    """The same words hash the same on any machine (2026-10-02)."""
    import unicodedata
    text = "## Inputs\n- Café vocals — HPF 120 Hz.\n"
    base = conventions_resolve.fingerprint(text)
    assert conventions_resolve.fingerprint(text.replace("\n", "\r\n")) == base
    assert conventions_resolve.fingerprint(unicodedata.normalize("NFD", text)) == base


def test_a_resolved_file_records_and_reports_the_atoo_that_made_it(tmp_path, monkeypatch):
    conventions = tmp_path / "house.md"
    conventions.write_text(CONVENTIONS)
    text = conventions_resolve.run(CONVENTIONS, "house.md",
                                   provider=FakeProvider(response="# x\n"), now="t")
    assert conventions_resolve.parse_header(text)["atoo"] == conventions_resolve.made_by()
    resolved = conventions_resolve.resolved_path(conventions)
    resolved.write_text(text.replace(f"atoo: {conventions_resolve.made_by()}",
                                     "atoo: 0.0.9 (abc1234)"))
    conventions.write_text(CONVENTIONS + "\n- One more line.\n")
    state = conventions_resolve.freshness(conventions, conventions.read_text())
    assert state.state == "stale"
    assert "it was made by Atoo 0.0.9 (abc1234), and this is" in state.reason
