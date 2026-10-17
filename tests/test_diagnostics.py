"""The canonical diagnostic type and its one renderer."""

import json

import pytest

from atoo import diagnostics
from atoo.diagnostics import (
    COMPILE_PATH_ISSUE,
    Diagnostic,
    DiagnosticList,
    Severity,
    coerce_severity,
    render,
    sort_key,
    summary_line,
)


# --------------------------------------------------------------------------
# the type
# --------------------------------------------------------------------------

def test_severity_compares_equal_to_its_string_spelling():
    """The whole migration rests on this: five layers were written
    against bare "error"/"warning" strings, and a `str` enum lets them
    keep working while the type unifies underneath them."""
    assert Severity.ERROR == "error"
    assert Severity.WARNING == "warning"
    assert Severity.INFO == "info"
    assert str(Severity.ERROR) == "error"


def test_severity_serializes_as_a_plain_string():
    assert json.dumps({"severity": Severity.WARNING}) == '{"severity": "warning"}'


def test_coerce_severity_accepts_either_spelling():
    assert coerce_severity("error") is Severity.ERROR
    assert coerce_severity(Severity.ERROR) is Severity.ERROR


def test_coerce_severity_rejects_an_unknown_one():
    # Not silently downgraded to a warning: a severity nothing produces
    # is a bug in the producer, and swallowing it hides that.
    with pytest.raises(ValueError):
        coerce_severity("catastrophic")


def test_only_severity_code_and_message_are_required():
    d = Diagnostic(Severity.ERROR, "dca.member-category-unknown", "was dropped")
    assert d.where == "" and d.fix is None and d.issue is None and d.addresses == ()


def test_diagnostic_is_frozen():
    d = Diagnostic(Severity.INFO, "x", "y")
    with pytest.raises(Exception):
        d.severity = Severity.ERROR


def test_str_carries_severity_where_message_and_code():
    d = Diagnostic(Severity.ERROR, "bus.no-members", "nothing joins it", where="bus Vocals")
    assert str(d) == "[error] bus Vocals: nothing joins it  (bus.no-members)"


# --------------------------------------------------------------------------
# the named constructors, one per layer's calling convention
# --------------------------------------------------------------------------

def test_audit_constructor_keeps_the_rule_id_as_the_stable_code():
    d = Diagnostic.audit(
        "R001", Severity.WARNING, "routing", "Bus No Inputs",
        "Bus 3 is named but no strip sends to it.", ("/bus/3/name",),
    )
    assert d.code == "R001"
    assert d.rule_id == "R001"        # FR-4.3's name, still available
    assert d.detail == "Bus 3 is named but no strip sends to it."
    assert d.category == "routing"
    assert d.addresses == ("/bus/3/name",)
    assert d.source == "audit"


def test_audit_constructor_accepts_a_string_severity():
    assert Diagnostic.audit("X", "error", "c", "t", "d").severity is Severity.ERROR


def test_convention_constructor_keeps_section_and_line_provenance():
    d = Diagnostic.convention("warning", "Busses", "the line as written", "had no effect")
    assert d.where == "Busses"
    assert d.section == "Busses"
    assert d.line == "the line as written"
    assert d.source == "conventions"


def test_convention_constructor_can_override_where():
    d = Diagnostic.convention("info", "(preamble)", "a line", "prose", where="preamble")
    assert d.where == "preamble"
    assert d.section == "(preamble)"     # provenance is not overwritten


def test_dropped_constructor_is_a_warning_that_carries_a_tracking_issue():
    """The category an earlier change was filed about. The maintainer's call (2026-09-19)
    was that a limitation is not its own severity -- it is a warning. What
    makes it legible is the tracking issue, not a fifth severity."""
    d = Diagnostic.dropped("busses.Vocals", "membership exclusions aren't representable")
    assert d.severity is Severity.WARNING
    assert d.issue == COMPILE_PATH_ISSUE
    assert d.where == "busses.Vocals"


def test_dropped_constructor_takes_a_specific_tracking_issue():
    assert Diagnostic.dropped("watch", "not carried", issue=49).issue == 49


# --------------------------------------------------------------------------
# the wire shape the Setup UI consumes (D9)
# --------------------------------------------------------------------------

def test_to_dict_omits_fields_the_producer_never_set():
    d = Diagnostic(Severity.ERROR, "plan.no-channels", "assigns no channels at all",
                   where="plan.channels")
    assert d.to_dict() == {
        "severity": "error",
        "code": "plan.no-channels",
        "message": "assigns no channels at all",
        "where": "plan.channels",
    }


def test_to_dict_includes_fix_and_issue_when_set():
    d = Diagnostic(Severity.WARNING, "c", "m", fix="rename it", issue=29)
    assert d.to_dict()["fix"] == "rename it"
    assert d.to_dict()["issue"] == 29


def test_to_dict_is_json_serializable():
    d = Diagnostic.audit("R001", Severity.ERROR, "safety", "t", "d", ("/a",))
    assert json.loads(json.dumps(d.to_dict()))["severity"] == "error"


def test_dict_round_trip():
    d = Diagnostic(Severity.WARNING, "rules.malformed-member", "dropped it",
                   where="dcas Band", title="T", category="c", fix="f", issue=29,
                   addresses=("/a", "/b"), source="rules", line="raw line")
    assert Diagnostic.from_dict(d.to_dict()) == d


def test_with_source_tags_without_mutating():
    d = Diagnostic(Severity.INFO, "c", "m")
    assert d.with_source("audit").source == "audit"
    assert d.source == ""


# --------------------------------------------------------------------------
# ordering and counting
# --------------------------------------------------------------------------

def test_sort_is_worst_first():
    items = [
        Diagnostic(Severity.INFO, "d", "m"),
        Diagnostic(Severity.ERROR, "b", "m"),
        Diagnostic(Severity.WARNING, "a", "m"),
    ]
    assert [d.severity for d in sorted(items, key=sort_key)] == [
        Severity.ERROR, Severity.WARNING, Severity.INFO,
    ]


def test_sort_is_stable_and_total_so_rendered_output_is_diffable():
    items = [
        Diagnostic(Severity.ERROR, "b", "m", where="z"),
        Diagnostic(Severity.ERROR, "a", "m", where="y"),
        Diagnostic(Severity.ERROR, "a", "m", where="x"),
    ]
    assert [(d.code, d.where) for d in sorted(items, key=sort_key)] == [
        ("a", "x"), ("a", "y"), ("b", "z"),
    ]


def test_summary_line_counts_by_severity_not_as_one_total():
    """A count was what hid the two plan-changing drops inside 25."""
    items = [
        Diagnostic(Severity.ERROR, "a", "m"),
        Diagnostic(Severity.WARNING, "b", "m"),
        Diagnostic(Severity.WARNING, "c", "m"),
        Diagnostic(Severity.INFO, "d", "m"),
    ]
    assert summary_line(items) == "1 error(s), 2 warning(s), 1 note(s)"


def test_summary_line_is_empty_for_nothing():
    assert summary_line([]) == ""


def test_diagnostic_list_counts_error_as_blocking_and_warning_as_not():
    dl = DiagnosticList()
    dl.add(Diagnostic(Severity.ERROR, "a", "m"))
    dl.add(Diagnostic(Severity.WARNING, "b", "m"))
    assert len(dl.errors) == 1 and not dl.ok
    assert len(dl.warnings) == 1
    assert len(dl) == 2 and bool(dl)


# --------------------------------------------------------------------------
# the renderer -- the actual complaint
# --------------------------------------------------------------------------

def test_render_of_nothing_is_empty_so_a_caller_need_not_count_first():
    assert render([]) == ""


def test_each_severity_gets_its_own_label():
    text = render([
        Diagnostic(Severity.ERROR, "b", "m2"),
        Diagnostic(Severity.WARNING, "c", "m3"),
        Diagnostic(Severity.INFO, "d", "m4"),
    ])
    assert text.startswith("ERROR")
    for label in ("ERROR", "WARNING", "NOTE"):
        assert f"\n{label}" in f"\n{text}"


def test_critical_is_gone_and_stays_gone():
    """Dropped 2026-09-23: nothing ever emitted one, and `error` already
    blocked everything it would have. A watch.json is the only file on
    disk that can still carry the word, and the loader says what to
    change -- see `test_watch_conditions.py`."""
    assert [s.value for s in Severity] == ["error", "warning", "info"]
    assert not hasattr(Severity, "CRITICAL")


def test_the_four_kinds_from_the_issue_render_distinguishably():
    """The acceptance criterion, as its own table states it: an
    error the engineer can fix, a warning they probably can, an info
    nobody needs to act on, and a limitation that is *not theirs to fix*
    must not all read as the same bullet.

    The limitation is a warning by severity (the maintainer's call), so what has
    to distinguish it is the tracking-issue line -- and that is exactly
    what the older output had no way to say.
    """
    text = render([
        Diagnostic(Severity.ERROR, "dca.member-category-unknown",
                   'was dropped -- nothing will be assigned to it',
                   where='DCA "Band"',
                   fix='use one of the patch-order names, or add "band" to your patch order'),
        Diagnostic(Severity.WARNING, "channel.socket-auto-assigned",
                   "no socket stated -- auto-assigned LCL 1",
                   where='channel "Kick"'),
        Diagnostic(Severity.INFO, "conventions.prose-not-acted-on",
                   "prose, not acted on", where="preamble"),
        Diagnostic.dropped('bus "INST Reverb"',
                           "membership exclusions aren't supported yet"),
    ])

    assert "ERROR" in text and "NOTE" in text
    # the engineer's error says what to change
    assert 'Fix: use one of the patch-order names' in text
    # the limitation says, in as many words, that changing prose won't help
    assert "Not something you can fix in your conventions file" in text
    assert "a limitation of Atoo itself" in " ".join(text.split())
    # ...without the tracker's number: a user reading this cannot use it, so it stays in the data, not the text.
    assert f"issue #{COMPILE_PATH_ISSUE}" not in text
    # ...and the ordinary warning says neither of those things
    kick_block = [b for b in text.split("\n\n") if "Kick" in b][0]
    assert "Fix:" not in kick_block
    assert "Not something you can fix" not in kick_block


def test_render_shows_the_stable_code_so_it_can_be_quoted_in_a_bug_report():
    assert "(R001)" in render([Diagnostic.audit(
        "R001", Severity.WARNING, "routing", "Bus No Inputs", "no strip sends to it")])


def test_render_omits_the_code_line_when_there_is_no_code():
    """The retiring compile path has no stable codes; a placeholder under
    every line would be noise rather than information."""
    text = render([Diagnostic(Severity.WARNING, "", "a note from the compile path")])
    assert "(" not in text


def test_render_shows_the_source_line_when_the_producer_captured_one():
    text = render([Diagnostic.convention(
        "warning", "Busses", "Vocals bus does the thing", "had no effect")])
    assert "Your line: Vocals bus does the thing" in text


def test_render_wraps_long_messages_under_the_label_not_past_it():
    long = "word " * 60
    text = render([Diagnostic(Severity.ERROR, "c", long.strip())], width=60)
    lines = text.splitlines()
    assert len(lines) > 2
    assert all(len(line) <= 60 for line in lines)
    # continuation lines are indented to sit under the first, never
    # re-labelled as if they were separate findings
    assert all(line.startswith(" ") for line in lines[1:] if line)


def test_render_never_splits_a_word():
    text = render([Diagnostic(Severity.ERROR, "c", "supercalifragilistic " * 4)], width=40)
    assert "supercalifragilistic" in text
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("("):
            for word in stripped.replace("ERROR", "").split():
                assert word in ("supercalifragilistic",)


def test_render_includes_the_heading_when_given_one():
    text = render([Diagnostic(Severity.INFO, "c", "m")], heading="Reading your conventions:")
    assert text.startswith("Reading your conventions:\n\n")


def test_render_prefixes_the_title_only_when_it_adds_something():
    titled = render([Diagnostic.audit(
        "R001", Severity.WARNING, "routing", "Bus No Inputs",
        "Bus 3 is named but no strip sends to it.")])
    assert "Bus No Inputs --" in titled

    # ...and not when the message already opens with it, which would read
    # as "Bus No Inputs -- Bus No Inputs: ..."
    redundant = render([Diagnostic.audit(
        "R001", Severity.WARNING, "routing", "Bus No Inputs",
        "Bus No Inputs: nothing sends to it.")])
    assert "Bus No Inputs --" not in redundant


def test_render_is_deterministic_for_the_same_input():
    items = [
        Diagnostic(Severity.WARNING, "b", "second"),
        Diagnostic(Severity.ERROR, "a", "first"),
    ]
    assert render(items) == render(list(reversed(items)))


# --------------------------------------------------------------------------
# the layers that were migrated onto it still agree on the type
# --------------------------------------------------------------------------

def test_every_migrated_layer_produces_the_same_class():
    """An earlier change retired `conventions.py` and `ai_conventions.py`, so two of the
    five aliases an earlier change unified are gone with the modules that defined them.
    The ones that survive still have to be the one class."""
    from atoo import audit, generate, verify_plan
    for alias in (audit.Finding, verify_plan.Finding, generate.CriticFinding):
        assert alias is Diagnostic


def test_severity_order_is_shared_not_re_declared():
    from atoo import audit
    assert audit.SEVERITY_ORDER is diagnostics.SEVERITY_ORDER
