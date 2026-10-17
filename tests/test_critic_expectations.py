"""Hand-authored ground truth for the critic pass, and the scorer.

`tests/test_expectations.py` protects one distinction; this file protects
the next one along. The critic is a model, so "how many findings did it
produce" measures nothing -- twenty confident inventions score better than
three correct catches. What can be measured is recall against gaps a human
wrote down after finding them in a real run, and the three states that
measurement has to keep apart:

  * the critic caught it;
  * the critic saw it and under-rated it;
  * the critic never ran, which is not a score at all.

No model runs anywhere in this file. Every finding here is canned, because
the thing under test is the scorer, not a model.
"""

from __future__ import annotations

import pytest

from atoo.critic_expectations import (
    CriticExpectationsError,
    load_critic_expectations,
    parse_critic_expectations,
    score_critic,
)
from atoo.diagnostics import Diagnostic, Severity
from atoo.generate import parse_critic_findings

ONE = """
[[expect]]
id = "missing-monitor-sends"
description = "no channel sends to a monitor bus"
match_text = ["monitor", "send"]
severity_at_least = "warning"
"""


def finding(message: str, *, severity: str = "warning", where: str = "channels",
            kind: str = "omission") -> Diagnostic:
    return Diagnostic(
        severity=Severity(severity),
        code=f"critic.{kind}",
        message=message,
        where=where,
        category=kind,
        source="critic",
    )


# --- the file itself ------------------------------------------------------


def test_parses_one_entry():
    expectations = parse_critic_expectations(ONE, "f.toml")
    assert len(expectations) == 1
    one = expectations.expectations[0]
    assert one.id == "missing-monitor-sends"
    assert one.match_text == ("monitor", "send")
    assert one.severity_at_least is Severity.WARNING


def test_severity_at_least_is_optional():
    expectations = parse_critic_expectations(
        '[[expect]]\nid = "a"\nmatch_text = ["x"]\n', "f.toml")
    assert expectations.expectations[0].severity_at_least is None
    assert expectations.expectations[0].description == ""


def test_unknown_key_is_an_error():
    """The same posture as expectations.py: a typo that passes silently
    makes the file report success while checking nothing."""
    with pytest.raises(CriticExpectationsError, match="match_txt"):
        parse_critic_expectations(
            '[[expect]]\nid = "a"\nmatch_txt = ["x"]\nmatch_text = ["x"]\n', "f.toml")


def test_unknown_top_level_section_is_an_error():
    with pytest.raises(CriticExpectationsError, match="plan"):
        parse_critic_expectations('[plan]\nchannels = 19\n', "f.toml")


def test_empty_file_is_an_error():
    """0/0 is a perfect score, and an empty file would hand one out."""
    with pytest.raises(CriticExpectationsError, match="no \\[\\[expect\\]\\] entries"):
        parse_critic_expectations("# nothing here\n", "f.toml")


def test_missing_id_is_an_error():
    with pytest.raises(CriticExpectationsError, match="'id'"):
        parse_critic_expectations('[[expect]]\nmatch_text = ["x"]\n', "f.toml")


def test_duplicate_id_is_an_error():
    with pytest.raises(CriticExpectationsError, match="duplicate id"):
        parse_critic_expectations(
            '[[expect]]\nid = "a"\nmatch_text = ["x"]\n'
            '[[expect]]\nid = "a"\nmatch_text = ["y"]\n', "f.toml")


@pytest.mark.parametrize("bad", ['match_text = "monitor"', "match_text = []",
                                 'match_text = [""]', "match_text = [3]"])
def test_match_text_must_be_a_non_empty_list_of_strings(bad):
    with pytest.raises(CriticExpectationsError, match="match_text"):
        parse_critic_expectations(f'[[expect]]\nid = "a"\n{bad}\n', "f.toml")


def test_unknown_severity_is_an_error():
    with pytest.raises(CriticExpectationsError, match="severity_at_least"):
        parse_critic_expectations(
            '[[expect]]\nid = "a"\nmatch_text = ["x"]\nseverity_at_least = "urgent"\n',
            "f.toml")


def test_not_valid_toml_names_the_file():
    with pytest.raises(CriticExpectationsError, match="f.toml: not valid TOML"):
        parse_critic_expectations("[[expect]\n", "f.toml")


# --- matching -------------------------------------------------------------


def test_every_term_must_appear_in_the_same_finding():
    """The design decision this whole file turns on. "Any of these terms"
    would score a finding saying the monitor sends are *correct* as a
    catch for "the monitor sends are missing"."""
    expectations = parse_critic_expectations(ONE, "f.toml")
    one_term_only = score_critic([finding("the monitor busses look right")], expectations)
    assert len(one_term_only.misses) == 1

    both_but_split = score_critic(
        [finding("the monitor busses look right"), finding("every send is present")],
        expectations)
    assert len(both_but_split.misses) == 1

    both_together = score_critic(
        [finding("no channel has a send to any monitor bus")], expectations)
    assert len(both_together.hits) == 1


def test_matching_is_case_insensitive():
    expectations = parse_critic_expectations(ONE, "f.toml")
    assert score_critic([finding("NO MONITOR SEND EXISTS")], expectations).hits


def test_where_and_category_are_searched_too():
    """A critic naming the place rather than repeating it in the message
    has still found the thing."""
    expectations = parse_critic_expectations(
        '[[expect]]\nid = "a"\nmatch_text = ["mon1", "omission"]\n', "f.toml")
    assert score_critic([finding("nothing sends here", where="busses[MON1]")],
                        expectations).hits


# --- the three outcomes ---------------------------------------------------


def test_under_severity_is_neither_a_hit_nor_a_miss():
    expectations = parse_critic_expectations(ONE, "f.toml")
    card = score_critic([finding("no monitor send anywhere", severity="info")],
                        expectations)
    assert not card.hits
    assert not card.misses
    assert [o.id for o in card.under_severity] == ["missing-monitor-sends"]
    assert card.recall == 0.0
    assert "under-severity" in card.findings()[0].code


def test_a_worse_severity_than_asked_for_is_a_hit():
    expectations = parse_critic_expectations(ONE, "f.toml")
    assert score_critic([finding("no monitor send", severity="error")], expectations).hits


def test_one_matching_finding_at_severity_rescues_the_others():
    """Two findings match, one under-rated and one not: the critic caught
    it. Recall asks whether it was found, not how many times."""
    expectations = parse_critic_expectations(ONE, "f.toml")
    card = score_critic([finding("no monitor send", severity="info"),
                         finding("monitor sends missing", severity="error")], expectations)
    assert len(card.hits) == 1


def test_miss_renders_as_an_error_naming_the_terms_it_looked_for():
    expectations = parse_critic_expectations(ONE, "f.toml")
    card = score_critic([finding("the faders are fine")], expectations)
    rendered = card.findings()[0]
    assert rendered.severity is Severity.ERROR
    assert "missing-monitor-sends" in rendered.where
    assert "'monitor'" in rendered.message


def test_a_critic_that_never_ran_scores_nothing():
    """The failure mode this module was written around: `critique_plan`
    returns `[]` both for "ran and found nothing" and for "no provider",
    and reporting 0/1 for the second blames a model for a missing Ollama.
    """
    expectations = parse_critic_expectations(ONE, "f.toml")
    card = score_critic([], expectations, ran=False)
    assert card.recall is None
    assert card.column == "--"
    assert not card.misses          # not-scored is not a miss
    assert card.findings()[0].code == "critic-expect.not-run"
    assert "did not run" in card.report()


def test_a_critic_that_ran_and_found_nothing_scores_zero():
    expectations = parse_critic_expectations(ONE, "f.toml")
    card = score_critic([], expectations, ran=True)
    assert card.recall == 0.0
    assert card.column == "0/1"
    assert len(card.misses) == 1


def test_total_findings_is_reported_but_never_scored():
    """Precision has no oracle here, so an inflated finding count is
    visible and never charged."""
    expectations = parse_critic_expectations(ONE, "f.toml")
    card = score_critic([finding("no monitor send")] + [finding(f"invention {i}")
                                                        for i in range(20)], expectations)
    assert card.total_findings == 21
    assert card.recall == 1.0


# --- the committed fixtures, and the product path they score --------------


@pytest.mark.parametrize("name", ["touringband.critic-expect.toml",
                                  "touringband.qwen2.5-coder-7b.critic-expect.toml"])
def test_committed_fixtures_parse(name):
    """They are hand-edited TOML that nothing else loads, so nothing else
    would notice a typo in them."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    if not (root / "experiments").is_dir():
        pytest.skip("needs experiments/, which this tree does not have")
    expectations = load_critic_expectations(root / "experiments" / "generator" / name)
    assert len(expectations) >= 2


def test_scoring_consumes_what_the_product_path_produces():
    """`parse_critic_findings` is `critique_plan`'s own parser (an earlier change split
    it out so the harness could not drift from it). A model reply goes
    through it and straight into the scorer, with no shape translation in
    between -- which is the whole reason both sides speak `Diagnostic`."""
    expectations = parse_critic_expectations(ONE, "f.toml")
    findings = parse_critic_findings(
        '{"findings": [{"kind": "omission", "severity": "error", '
        '"where": "channels", "message": "no monitor send on any channel"}]}')
    assert score_critic(findings, expectations).column == "1/1"
