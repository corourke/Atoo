"""R002 and R005 must not assert a negative from
addresses nobody read.

The maintainer, watching a live full-size WING on 2026-09-24, saw both:

    R005  /main/1 has active sends feeding it, but it reaches no
             physical output ...
    R002  /bus/1 (Drums) is in use but has no route to a physical
             output ...

Neither was true. Main 1 was patched to Matrix 1 and Matrix 1 to LCL 7,8,
exactly as `examples/conventions.md` describes. The rules were right about
the state they were handed and wrong about the desk, because that state
had no `/io/out/*` in it at all -- the desk states `wing-fullsize`, which
`socket_groups_to_read` did not recognise, so no output sockets were
requested.

The distinction these tests pin down is between **"we looked and there is
no route"** -- which is what R002 is for, and which must keep firing --
and **"we never looked"**, which is a gap in the read and not a finding.
`render_coverage` could already tell them apart; the rules never asked it.

These tests build their own states rather than reading a bundle: nothing
here depends on a file the maintainer edits.
"""

import pytest

from atoo.audit import (
    ConsoleState,
    coverage_caveat,
    output_patch_was_read,
    render_coverage,
    run_audit,
    unanswerable_rule_ids,
)
from atoo.cli import main


def _rule_ids(findings):
    return {f.rule_id for f in findings}


# `examples/conventions.md`, and the rig the maintainer was actually watching:
# *"Main should be the full mix... Send to Matrix 1. Matrix 1 takes its
# feed from Main... Patch output to internal XLRs 7 and 8."* Drums is a
# bus feeding that Main, so the chain is bus -> Main -> Matrix -> jack and
# R002 and R005 are the two rules that walk it.
DRUMS_TO_THE_XLRS = {
    "/bus/1/name": "Drums",
    "/ch/1/name": "Kick",
    "/ch/1/send/1/on": 1,
    "/ch/1/send/1/lvl": -10.0,
    "/bus/1/main/1/on": 1,
    "/main/1/send/MX1/on": 1,
    "/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1,
    "/io/out/LCL/8/grp": "MTX", "/io/out/LCL/8/in": 2,
}

#: The same desk, read by a run that never asked for an output socket --
#: which is exactly what `read_console_state` produces when the model is
#: unrecognised and no `--plan` names a patch.
DRUMS_WITH_THE_OUTPUT_PATCH_UNREAD = {
    address: value for address, value in DRUMS_TO_THE_XLRS.items()
    if not address.startswith("/io/out/")
}


def test_the_chain_is_clean_when_the_output_patch_was_read():
    """The control. Both rules are CORRECT on this state -- the fix is
    not about their logic, and a test that only checked the unread case
    could pass with the rules deleted."""
    assert not (_rule_ids(run_audit(ConsoleState(DRUMS_TO_THE_XLRS)))
                & {"R002", "R005"})


def test_neither_rule_fires_when_the_output_patch_was_never_read():
    """The false ERROR and the false WARNING the maintainer saw, word for word,
    on the same routing the test above calls clean."""
    findings = run_audit(ConsoleState(DRUMS_WITH_THE_OUTPUT_PATCH_UNREAD))
    assert not (_rule_ids(findings) & {"R002", "R005"})


def test_the_read_says_the_check_could_not_be_made():
    """Silence is not the fix. A report that drops two rules and says
    nothing reads exactly like a report that ran them and found nothing
    -- the same argument an earlier change made for the four rules already withheld
    here."""
    state = ConsoleState(DRUMS_WITH_THE_OUTPUT_PATCH_UNREAD)
    assert not output_patch_was_read(state)

    paragraph = render_coverage(state)
    for rule_id in ("R002", "R005"):
        assert rule_id in paragraph
    assert "could not be checked" in paragraph

    line = coverage_caveat(state)
    assert line is not None
    assert "R002" in line and "R005" in line
    assert "\n" not in line  # read at a desk, mid-show

    assert {"R002", "R005"} <= set(unanswerable_rule_ids(state))


def test_a_read_that_covered_the_output_patch_has_no_caveat():
    """Not vacuous in the other direction either: the caveat must go away
    when there is nothing to caveat, or it is wallpaper."""
    state = ConsoleState(dict(DRUMS_TO_THE_XLRS, **{"/io/in/LCL/1/vph": 0}))
    assert coverage_caveat(state) is None
    assert unanswerable_rule_ids(state) == ()


# --------------------------------------------------------------------------
# What must not weaken: a bus that genuinely reaches nothing
# --------------------------------------------------------------------------


def test_a_bus_that_really_reaches_nothing_is_still_a_finding():
    """R002's actual job. The output patch WAS read here -- every LCL
    jack answered, and every one of them is OFF -- so "no route to a
    physical output" is a measurement, not an assumption."""
    state = ConsoleState({
        "/bus/1/name": "Drums",
        "/ch/1/name": "Kick",
        "/ch/1/send/1/on": 1,
        "/io/out/LCL/7/grp": "OFF", "/io/out/LCL/7/in": 0,
        "/io/out/LCL/8/grp": "OFF", "/io/out/LCL/8/in": 0,
    })
    assert "R002" in _rule_ids(run_audit(state))


def test_a_main_that_really_reaches_nothing_is_still_an_error():
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/main/1/on": 1,
        "/io/out/LCL/7/grp": "OFF", "/io/out/LCL/7/in": 0,
    })
    assert "R005" in _rule_ids(run_audit(state))


def test_a_partial_output_read_does_not_silence_either_rule():
    """The line is drawn at "no output sockets at all", where
    `render_coverage` already draws it -- NOT at "every socket was read".
    A read that covered LCL but not A/B/C can still miss a route, and
    standing down on any gap would hide the fault R002 exists for.
    The partial coverage is reported instead."""
    state = ConsoleState({
        "/bus/1/name": "Drums",
        "/ch/1/name": "Kick",
        "/ch/1/send/1/on": 1,
        "/ch/1/main/1/on": 1,
        "/io/out/LCL/7/grp": "OFF", "/io/out/LCL/7/in": 0,
    })
    assert {"R002", "R005"} <= _rule_ids(run_audit(state))
    assert output_patch_was_read(state)


# --------------------------------------------------------------------------
# `watch` says it too
# --------------------------------------------------------------------------


@pytest.fixture
def unread_output_state(tmp_path):
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps(DRUMS_WITH_THE_OUTPUT_PATCH_UNREAD))
    return path


def test_watch_leads_with_the_coverage_caveat(unread_output_state, capsys):
    """Until an earlier change `watch` printed the coverage paragraph AFTER the
    baseline findings and never again, so a bare ERROR arriving on pass
    47 of a live watch carried no caveat at all. The one-line form now
    comes first, and again with every change event."""
    assert main(["watch", "--state-sequence", str(unread_output_state),
                 "--count", "1", "--interval", "0"]) == 0
    out = capsys.readouterr().out
    caveat = out.index("R002")
    assert caveat < out.index("baseline")
    assert "could not be checked" in out
    # And the findings themselves are gone -- the rule ids appear only
    # in the coverage text, never as a `[WARNING]`/`[ERROR]` line.
    assert "[WARNING] R002" not in out
    assert "[ERROR] R005" not in out
    assert "baseline -- 1 finding(s)" in out


def test_watch_repeats_the_caveat_with_a_change_event(tmp_path, capsys):
    """A change event is where an engineer at the desk is reading. A new
    finding there, on a read with rules it could not run, must arrive
    with that stated."""
    import json

    first = tmp_path / "a.json"
    first.write_text(json.dumps(DRUMS_WITH_THE_OUTPUT_PATCH_UNREAD))
    second = tmp_path / "b.json"
    second.write_text(json.dumps(
        dict(DRUMS_WITH_THE_OUTPUT_PATCH_UNREAD, **{"/ch/1/send/1/lvl": -110.0})))

    assert main(["watch", "--state-sequence", f"{first},{second}",
                 "--interval", "0"]) == 0
    out = capsys.readouterr().out
    after_change = out[out.index("change detected"):]
    assert "Coverage:" in after_change
    assert "R002" in after_change
