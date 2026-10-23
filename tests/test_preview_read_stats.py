"""Every Preview says what it read of the desk, on whichever path it took.

A Rack Preview took 18.8 s against the Compact's 3.7 s, and nothing in its
output said why: only the reset's own line counted requests. The preview now
prints one line with the requests (node dumps and single reads), how long the
read took and which path it took, with the reset on, with it off, on a console
with no initialized capture, and one request at a time. Without a reset, the
plan's values are read by the same pass the reset's read is (node dumps where
a dump is trusted, and a cut-off for a family the desk does not answer), which
is what made a console with no capture slow: it asked for every plan address
by itself, and a desk that does not have one (a Rack has no AUX) cost the full
timeout each.
"""

from __future__ import annotations

import json
import re
import time

import pytest

from atoo import apply as apply_module
from atoo.apply import apply_plan
from tests.test_combined_preview_read import PLAN_FIXTURE, _desk_for, _plan, _wired

MODELS = ["wing-compact", "wing-full", "wing-rack"]
NO_CAPTURE_MODEL = "wing-not-measured"


def _line(result) -> str:
    [line] = [w for w in result.warnings if w.startswith("INFO the preview read the desk")]
    return line


def assert_line_equals_what_the_desk_received(line: str, udp) -> None:
    """The line's requests plus the ones it says went out again are what the desk received.

    The fake desk reads its socket on its own thread, so on a loaded machine its count can
    trail the client's last sends by a moment: wait for it to catch up (up to 3 s) before
    comparing. A desk that received MORE than the line says is never waited out."""
    expected = _received(line)
    deadline = time.monotonic() + 3.0
    while len(udp.requests) < expected and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(udp.requests) == expected


def _received(line: str) -> int:
    """What the desk received for the read: the requests the line counts plus the
    sends it says went out again (a slow answer on a loaded machine is retried)."""
    again = re.search(r"; ([\d,]+) more sent again", line)
    return _numbers(line)[0] + (int(again.group(1).replace(",", "")) if again else 0)


def _numbers(line: str) -> tuple[int, int, int]:
    m = re.search(r"with ([\d,]+) requests \(([\d,]+) node dumps, ([\d,]+) single reads\)", line)
    return tuple(int(g.replace(",", "")) for g in m.groups())


def _preview(model, *, window=8, initialize=True, desk_model=None, **network):
    desk = _desk_for(desk_model or model if model != NO_CAPTURE_MODEL else "wing-compact")
    with _wired(desk, window=window, **network) as (console, udp):
        result = apply_plan(_plan(), console, dry_run=True, full_apply=True,
                            initialize=initialize, init_model=model)
    return result, udp


@pytest.mark.parametrize("model", MODELS + [NO_CAPTURE_MODEL])
@pytest.mark.parametrize("initialize", [True, False])
def test_the_line_counts_the_requests_the_desk_got(model, initialize):
    result, udp = _preview(model, initialize=initialize)
    requests, dumps, singles = _numbers(_line(result))
    assert requests == dumps + singles
    assert_line_equals_what_the_desk_received(_line(result), udp)


@pytest.mark.parametrize("model", MODELS + [NO_CAPTURE_MODEL])
def test_the_line_counts_the_requests_one_at_a_time_too(model):
    result, udp = _preview(model, window=1)
    requests, dumps, singles = _numbers(_line(result))
    assert_line_equals_what_the_desk_received(_line(result), udp)
    assert "one request at a time (console window 1)" in _line(result)


@pytest.mark.parametrize("model", MODELS)
def test_it_says_which_path_it_took(model):
    on, _ = _preview(model)
    off, _ = _preview(model, initialize=False)
    assert "node dumps for the reset and the plan's settings" in _line(on)
    assert "the reset is off (--no-init)" in _line(off)
    none, _ = _preview(NO_CAPTURE_MODEL)
    assert "no initialized capture, so there is no reset" in _line(none)


@pytest.mark.parametrize("model", MODELS + [NO_CAPTURE_MODEL])
def test_without_a_reset_the_plans_values_are_read_by_node_dump(model):
    """The change that makes a console with no capture, and --no-init, fast: the
    same pass as the reset's, not one request for each of ~2,800 addresses."""
    plan = json.loads(PLAN_FIXTURE.read_text())
    desk = _desk_for("wing-compact" if model == NO_CAPTURE_MODEL else model)
    with _wired(desk, window=8) as (console, udp):
        result = apply_plan(plan, console, dry_run=True, full_apply=True, initialize=False,
                            init_model=model)
    requests, dumps, singles = _numbers(_line(result))
    assert dumps > 50
    assert requests < 1000


def test_an_address_the_desk_does_not_answer_costs_a_few_timeouts_not_one_each():
    """A Rack has no AUX: every AUX leaf the plan reads is silent. With the
    family cut-off, a console with no capture reads them like the reset does."""
    desk = _desk_for("wing-rack")
    silent = {a for a in desk.values if a.startswith(("/io/in/AUX/", "/io/out/AUX/", "/aux/"))}
    plan = json.loads(PLAN_FIXTURE.read_text())
    with _wired(desk, window=8, timeout=0.2, silent=silent) as (console, udp):
        result = apply_plan(plan, console, dry_run=True, full_apply=True, initialize=False,
                            init_model="wing-rack")
    requests, _, _ = _numbers(_line(result))
    assert requests < 1000
    assert "did not answer" in _line(result)
    # Before: one request for every plan address, each silent one a full timeout.
    assert len(udp.requests) < 700


def test_the_unanswered_addresses_are_counted_in_the_line_when_there_are_some():
    desk = _desk_for("wing-compact")
    with _wired(desk, window=8, timeout=0.2, silent={"/ch/1/name"}) as (console, udp):
        result = apply_plan(_plan(), console, dry_run=True, full_apply=True, initialize=False,
                            init_model="wing-compact")
    assert "1 address(es) did not answer" in _line(result)


@pytest.mark.parametrize("model", MODELS)
def test_a_real_run_prints_no_preview_line(model):
    desk = _desk_for(model)
    with _wired(desk, window=8) as (console, _udp):
        result = apply_plan(_plan(), console, dry_run=False, full_apply=True, initialize=True,
                            init_model=model)
    assert not [w for w in result.warnings if w.startswith("INFO the preview read the desk")]


# -- a slow read says where the time went --------------------------------------


def test_a_slow_read_says_which_pass_took_the_time_and_what_one_request_costs(monkeypatch):
    """A Rack's Preview took 24.8 s for ~2,600 requests, ~9 ms each, with nothing to say
    why. Past a few seconds the line splits the time, names a few of the families that did
    not answer, and times a request on its own, to say whether the window is doing its work."""
    monkeypatch.setattr(apply_module, "SLOW_READ_SECONDS", 0.0)
    desk = _desk_for("wing-rack")
    silent = {a for a in desk.values if a.startswith("/io/in/AUX/")}
    plan = json.loads(PLAN_FIXTURE.read_text())
    with _wired(desk, window=8, timeout=0.1, latency=0.004, silent=silent) as (console, udp):
        result = apply_plan(plan, console, dry_run=True, full_apply=True, initialize=True,
                            init_model="wing-rack")
    line = _line(result)
    assert "slow: the node dumps took" in line and "single reads" in line
    assert "with 8 requests at a time" in line
    assert "one request on its own took about" in line
    assert "(for example /io/in/AUX/" in line


def test_a_read_that_is_not_slow_says_nothing_more():
    result, _ = _preview("wing-compact")
    assert "slow:" not in _line(result)


@pytest.mark.parametrize("model", MODELS + [NO_CAPTURE_MODEL, None])
def test_the_estimates_quote_a_rate_only_for_a_console_that_has_one(model):
    from atoo import initialize as init

    words = init.write_estimate_words(100, model)
    if model == "wing-compact":
        assert words.startswith("about ") and "measured on a WING Compact" in words
    else:
        assert words.startswith("no measured request rate for ")
        assert "Compact" not in words or "WING Compact" == init.facts.CONSOLE_MODELS.get(
            model, {}).get("label")


@pytest.mark.parametrize("model", ["wing-full", "wing-rack"])
def test_the_reset_lines_never_quote_the_compacts_rate_for_another_console(model):
    from atoo import initialize as init

    result, _ = _preview(model)
    [line] = [w for w in result.warnings if w.startswith("INFO reset to initialized")]
    assert "measured on a WING Compact" not in line
    assert "no measured request rate for the" in line
    code, note = init.preflight_note(_plan(), model)
    assert "no measured request rate for the" in note and "measured on a WING Compact" not in note


def test_a_request_that_is_sent_again_is_counted_apart_and_the_total_is_what_the_desk_received():
    """A slow answer is retried: that is real traffic the desk receives. The line counts the
    requests Atoo asked for and says how many more went out again, so the two add up to what
    the desk received on a loaded machine too, not only when nothing is retried."""
    desk = _desk_for("wing-compact")
    # Every reply takes longer than the timeout: each request goes out again.
    with _wired(desk, window=8, timeout=0.01, latency=0.02) as (console, udp):
        result = apply_plan(_plan(), console, dry_run=True, full_apply=True, initialize=False,
                            init_model="wing-compact")
    line = _line(result)
    assert "more sent again because a request was not answered in time" in line
    assert console.resends > 0
    assert_line_equals_what_the_desk_received(line, udp)
