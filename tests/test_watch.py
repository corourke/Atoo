"""FR-6.4 proof of concept, fully offline: no real sleep, no wall clock,
no console -- `sleep`/`clock` are injected no-ops/fakes, and `state_provider`
is a plain Python iterator over hand-built ConsoleStates."""

from atoo.audit import ConsoleState
from atoo.watch import render_event, watch


def _sequence_provider(states):
    it = iter(states)
    return lambda: next(it)


def _fake_sleep_calls():
    calls = []
    return calls, calls.append


def test_first_iteration_has_no_new_or_cleared_findings():
    """Whatever's already wrong when watching starts is the baseline, not
    a "change" -- it must not come out as an alert."""
    dirty = ConsoleState({"/ch/1/name": "Vox", "/ch/1/tags": "#D1", "/ch/2/name": "Vox", "/ch/2/tags": "#D1"})
    calls, fake_sleep = _fake_sleep_calls()
    events = list(watch(
        _sequence_provider([dirty]), interval=5, max_iterations=1,
        sleep=fake_sleep, clock=lambda: "t0",
    ))
    assert len(events) == 1
    event = events[0]
    assert event.iteration == 0
    assert event.new_findings == []
    assert event.cleared_findings == []
    assert len(event.all_findings) == 1  # the duplicate-name finding is still reported
    assert calls == []  # nothing to wait for after the only iteration


def test_new_finding_detected_on_second_cycle():
    clean = ConsoleState({"/ch/1/name": "Vox", "/ch/1/tags": "#D1"})
    now_duplicated = ConsoleState({
        "/ch/1/name": "Vox", "/ch/1/tags": "#D1",
        "/ch/2/name": "Vox", "/ch/2/tags": "#D1",
    })
    calls, fake_sleep = _fake_sleep_calls()

    events = list(watch(
        _sequence_provider([clean, now_duplicated]), interval=3, max_iterations=2,
        sleep=fake_sleep, clock=lambda: "t",
    ))

    assert events[0].new_findings == []
    assert len(events[1].new_findings) == 1
    assert events[1].new_findings[0].rule_id == "N001"
    assert events[1].cleared_findings == []
    assert calls == [3]  # slept once, between the two reads -- not after the last


def test_cleared_finding_detected_when_operator_fixes_it():
    duplicated = ConsoleState({"/ch/1/name": "Vox", "/ch/2/name": "Vox"})
    fixed = ConsoleState({"/ch/1/name": "Vox", "/ch/2/name": "Kick"})

    events = list(watch(
        _sequence_provider([duplicated, fixed]), interval=1, max_iterations=2,
        sleep=lambda s: None, clock=lambda: "t",
    ))

    assert events[1].new_findings == []
    assert len(events[1].cleared_findings) == 1
    assert events[1].cleared_findings[0].rule_id == "N001"


def test_no_change_between_identical_reads_yields_no_alert_text():
    state = ConsoleState({"/ch/1/name": "Vox"})
    events = list(watch(
        _sequence_provider([state, state]), interval=1, max_iterations=2,
        sleep=lambda s: None, clock=lambda: "t",
    ))
    assert render_event(events[0]) is None or events[0].iteration == 0
    assert render_event(events[1]) is None


def test_same_rule_on_different_channel_is_a_distinct_finding():
    """N001 firing for a NEW pair of duplicate names, while the OLD
    pair is still duplicated, must show up as a new finding -- not get
    silently absorbed because a finding with the same rule_id already
    existed last cycle."""
    one_pair = ConsoleState({
        "/ch/1/name": "Vox", "/ch/1/tags": "#D1",
        "/ch/2/name": "Vox", "/ch/2/tags": "#D1",
    })
    two_pairs = ConsoleState({
        "/ch/1/name": "Vox", "/ch/1/tags": "#D1",
        "/ch/2/name": "Vox", "/ch/2/tags": "#D1",
        "/ch/3/name": "Kick", "/ch/3/tags": "#D1",
        "/ch/4/name": "Kick", "/ch/4/tags": "#D1",
    })
    events = list(watch(
        _sequence_provider([one_pair, two_pairs]), interval=1, max_iterations=2,
        sleep=lambda s: None, clock=lambda: "t",
    ))
    assert len(events[1].new_findings) == 1
    assert events[1].new_findings[0].addresses == ("/ch/3/name", "/ch/4/name")
    assert events[1].cleared_findings == []


def test_render_event_formats_new_and_cleared():
    duplicated = ConsoleState({"/ch/1/name": "Vox", "/ch/2/name": "Vox"})
    fixed = ConsoleState({"/ch/1/name": "Vox", "/ch/2/name": "Kick"})
    events = list(watch(
        _sequence_provider([duplicated, fixed]), interval=1, max_iterations=2,
        sleep=lambda s: None, clock=lambda: "2026-09-12T00:00:00+00:00",
    ))
    text = render_event(events[1])
    assert "CLEARED" in text
    assert "N001" in text
    assert "2026-09-12T00:00:00+00:00" in text


def test_max_iterations_none_is_bounded_by_provider_exhaustion():
    # A finite provider used without max_iterations naturally ends the
    # watch when it runs out -- watch() doesn't need to know the count
    # in advance, and a caller iterating it with a plain `for` loop never
    # sees an exception (PEP 479 would otherwise turn the provider's
    # StopIteration into a RuntimeError inside this generator).
    states = [ConsoleState({}), ConsoleState({})]
    provider = _sequence_provider(states)
    events = list(watch(provider, interval=1, sleep=lambda s: None, clock=lambda: "t"))
    assert len(events) == 2
