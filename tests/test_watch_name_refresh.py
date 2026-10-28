"""A live watch reads names at Start and every N passes, not
every pass.

A node dump cannot carry a name (`audit.DUMP_UNSAFE_LEAVES`), so on a
WING Compact the 88 strip, bus, DCA and mute-group names, plus the second
pass's source-socket names, were separate requests on every pass. Now:

1. a pass between refreshes asks for none of them, and the request
   counts say by how much;
2. every rule still sees the names on those passes -- the last ones read;
3. a rename reaches the state at the next refresh, not before;
4. `--name-refresh 1` is the old watch exactly;
5. the session says so once, at INFO (W001), and the CLI, the Watch
   page and the scoped names all go through the same provider.

Every desk here is built in the test. No test reads a bundle under
`examples/`, and none touches a console.
"""

from __future__ import annotations

import json
import time

import pytest

from atoo import audit, cli, watch as watch_module
from atoo.audit import (ConsoleState, console_read_plan, group_plan_by_node,
                             is_name_address, names_read, read_console_state, run_audit,
                             socket_groups_to_read)
from atoo.cli import main
from atoo.watch import (DEFAULT_NAME_REFRESH, NAME_REFRESH_RULE_ID, refreshing_names,
                             watch)
from test_bulk_read import TwoWayConsole

INPUTS, OUTPUTS = socket_groups_to_read("wing-compact")
COMPACT = dict(input_sockets=INPUTS, output_sockets=OUTPUTS)
DEFAULTS = {"s": "OFF", "i": "0", "f": "0.0"}


def _compact_desk(**overrides) -> dict[str, str]:
    """A whole Compact answering every address the plan asks for, with
    channels 1-24 patched from their own local sockets (the factory
    patch, so the second pass has 24 socket names and 24 `clink`s to
    read) and whatever `overrides` say."""
    desk = {address: DEFAULTS[value_type]
            for address, value_type in console_read_plan(**COMPACT)}
    for n in range(1, 25):
        desk[f"/ch/{n}/in/conn/grp"] = "LCL"
        desk[f"/ch/{n}/in/conn/in"] = str(n)
        desk[f"/ch/{n}/clink"] = "1"
        desk[f"/io/in/LCL/{n}/name"] = f"LCL {n}"
    # Both bays empty, in the desk's own word: "OFF" is not
    # one of their values, and would read as something fitted.
    desk["/cards/$type"] = desk["/$syscfg/opt_mod"] = "NONE"
    desk.update(overrides)
    return desk


class _Counting(TwoWayConsole):
    """`TwoWayConsole`, with the requests of each pass kept apart."""

    def requests(self) -> int:
        return len(self.gets) + len(self.dumps)

    def reset(self) -> None:
        self.gets.clear()
        self.dumps.clear()


def _provider(desk: _Counting, every: int, *, bulk: bool = True):
    plan = console_read_plan(**COMPACT)
    return refreshing_names(
        lambda names: read_console_state(desk, names=names, bulk=bulk, **COMPACT),
        plan, every)


# -- 1. what a pass costs -----------------------------------------------------


def test_a_pass_between_refreshes_asks_for_no_names_and_88_fewer_requests():
    """The first-pass plan: 325 requests by node dump, of which 88 are
    names (40 ch + 8 aux + 16 bus + 16 DCA + 8 mute group). A pass
    between refreshes asks for 237. (323 and 235 until an earlier change read
    what is fitted in each expansion bay: two leaves, neither a name.) Counted from the plan, the way
    `cli.read_requests` and `watch_scope.ScopedReadPlan` count it."""
    plan = console_read_plan(**COMPACT)
    names = [a for a, _ in plan if is_name_address(a)]
    assert len(names) == 88
    assert {a.split("/")[1] for a in names} == {"ch", "aux", "bus", "dca", "mgrp"}

    by_node, alone = group_plan_by_node(plan)
    assert len(by_node) + len(alone) == 325
    without = [(a, t) for a, t in plan if not is_name_address(a)]
    by_node, alone = group_plan_by_node(without)
    assert len(by_node) + len(alone) == 237

    kwargs = dict(COMPACT, bulk=True)
    assert cli.read_requests(kwargs) == 325
    assert cli.read_requests(kwargs, names_known=True) == 237
    per_leaf = dict(COMPACT, bulk=False)
    assert cli.read_requests(per_leaf) - cli.read_requests(per_leaf, names_known=True) == 88


def test_a_live_pass_between_refreshes_asks_the_desk_for_no_name():
    """The same, counted at a desk: the refresh pass is the 325 plus the
    second pass's 24 socket names and 24 `clink`s; the pass between drops
    the 88 names and the 24 socket names and keeps the `clink`s, which
    are switches, not names."""
    desk = _Counting(_compact_desk())
    provider = _provider(desk, every=3)

    provider()
    assert desk.requests() == 325 + 24 + 24
    assert sum(is_name_address(a) for a in desk.gets) == 88 + 24
    desk.reset()

    provider()
    assert desk.requests() == 237 + 24
    assert not [a for a in desk.gets if is_name_address(a)]
    assert len([a for a in desk.gets if a.endswith("/clink")]) == 24
    assert len([a for a in desk.gets if a.endswith("/tags")]) == 48, "tags every pass"


def test_names_come_back_on_the_refresh_pass():
    desk = _Counting(_compact_desk())
    provider = _provider(desk, every=3)
    counts = []
    for _ in range(7):
        desk.reset()
        provider()
        counts.append(desk.requests())
    full, between = 325 + 48, 237 + 24
    assert counts == [full, between, between, full, between, between, full]


# -- 2. every rule still sees the names ---------------------------------------


def test_every_rule_sees_the_names_on_a_pass_between_refreshes():
    """Built so the name-reading rules fire: two channels called 'Vox'
    (N001), two buses called 'Mon' (N002), a named bus fed by
    nothing (R001), a DCA and a mute group named for membership. The
    pass between refreshes must hand the rules the same state."""
    desk = _Counting(_compact_desk(**{
        "/ch/30/name": "Vox", "/ch/31/name": "Vox",
        "/bus/1/name": "Mon", "/bus/2/name": "Mon",
        "/dca/1/name": "Drums", "/mgrp/1/name": "FX",
        "/ch/30/tags": "#D1",
    }))
    provider = _provider(desk, every=4)
    first = provider()
    second = provider()

    assert second.values == first.values
    assert second.name("/ch/30") == "Vox"
    assert second.text("/dca/1/name") == "Drums"
    assert second.text("/io/in/LCL/3/name") == "LCL 3"
    ids = {f.rule_id for f in run_audit(first)}
    assert {"N001", "N002", "R001"} <= ids
    assert run_audit(second) == run_audit(first)


def test_an_unanswered_name_is_not_asked_again_until_the_refresh():
    """A name the desk did not answer stays unknown between refreshes --
    absent from the state, as it was on the refresh pass -- and is not a
    request every pass."""
    table = _compact_desk()
    del table["/dca/16/name"]
    desk = _Counting(table)
    provider = _provider(desk, every=3)
    first = provider()
    desk.reset()
    second = provider()
    assert "/dca/16/name" not in first.values
    assert "/dca/16/name" not in second.values
    assert "/dca/16/name" not in desk.gets


def test_a_strip_patched_since_the_refresh_has_its_socket_name_read_at_once():
    """The cache is of names already read, not of which sockets matter:
    a channel patched to a new socket between refreshes has that
    socket's name read on the pass it appears, and only that pass."""
    desk = _Counting(_compact_desk(**{"/io/in/A/7/name": "Podium"}))
    provider = _provider(desk, every=5)
    provider()
    desk.values["/ch/30/in/conn/grp"] = "A"
    desk.values["/ch/30/in/conn/in"] = "7"
    desk.reset()
    state = provider()
    assert desk.gets.count("/io/in/A/7/name") == 1
    assert state.text("/io/in/A/7/name") == "Podium"
    assert audit.is_in_use(state, "/ch/30")
    desk.reset()
    provider()
    assert "/io/in/A/7/name" not in desk.gets


# -- 3. a rename waits for the refresh -----------------------------------------


def test_a_rename_is_picked_up_at_the_next_refresh():
    desk = _Counting(_compact_desk(**{"/ch/30/name": "Kick", "/io/in/LCL/5/name": "Snare"}))
    provider = _provider(desk, every=3)
    assert provider().name("/ch/30") == "Kick"
    desk.values["/ch/30/name"] = "Kick In"
    desk.values["/io/in/LCL/5/name"] = "Snare Top"
    seen = [provider() for _ in range(3)]
    assert [s.name("/ch/30") for s in seen] == ["Kick", "Kick", "Kick In"]
    assert [s.text("/io/in/LCL/5/name") for s in seen] == ["Snare", "Snare", "Snare Top"]


def test_anything_but_a_name_is_read_every_pass():
    desk = _Counting(_compact_desk())
    provider = _provider(desk, every=5)
    provider()
    desk.values["/ch/3/mute"] = "1"
    desk.values["/ch/3/tags"] = "#D2"
    desk.values["/ch/3/clink"] = "0"
    state = provider()
    assert state.flag("/ch/3/mute") is True
    assert state.text("/ch/3/tags") == "#D2"
    assert state.flag("/ch/3/clink") is False


# -- 4. N=1 is today's watch ----------------------------------------------------


@pytest.mark.parametrize("bulk", [True, False])
def test_name_refresh_1_reads_exactly_what_every_pass_read_before(bulk):
    """With N=1 every pass is what `read_console_state` with no `names`
    asks -- the same requests, in the same order -- and the state is not
    marked, so no W001."""
    old = _Counting(_compact_desk())
    new = _Counting(_compact_desk())
    provider = _provider(new, every=1, bulk=bulk)
    for _ in range(3):
        expected = read_console_state(old, bulk=bulk, **COMPACT)
        got = provider()
        assert got == expected
        assert got.name_refresh is None
        assert new.gets == old.gets and new.dumps == old.dumps


def test_per_leaf_between_refreshes_reads_the_same_state():
    """`--per-leaf` with an explicit refresh is just as correct: the
    pass between asks for 88 + 24 fewer GETs and returns the same
    values."""
    desk = _Counting(_compact_desk(**{"/ch/30/name": "Vox"}))
    provider = _provider(desk, every=2, bulk=False)
    first = provider()
    asked_first = len(desk.gets)
    desk.reset()
    second = provider()
    assert desk.dumps == []
    assert asked_first - len(desk.gets) == 88 + 24
    assert second.values == first.values


# -- 5. announced once, at INFO --------------------------------------------------


def _states(every):
    desk = _Counting(_compact_desk(**{"/ch/30/name": "Vox", "/ch/31/name": "Vox"}))
    return _provider(desk, every=every)


def test_the_session_carries_one_info_saying_names_are_refreshed():
    events = list(watch(_states(DEFAULT_NAME_REFRESH), max_iterations=3, sleep=lambda s: None))
    for event in events:
        notes = [f for f in event.all_findings if f.rule_id == NAME_REFRESH_RULE_ID]
        assert len(notes) == 1
        assert notes[0].severity.value == "info"
        assert f"every {DEFAULT_NAME_REFRESH} readings" in notes[0].detail
        assert "next refresh" in notes[0].detail
    # In the baseline, so never news and never cleared.
    assert not any(f.rule_id == NAME_REFRESH_RULE_ID
                   for e in events for f in e.new_findings + e.cleared_findings)


def test_no_info_when_names_are_read_every_pass():
    events = list(watch(_states(1), max_iterations=2, sleep=lambda s: None))
    assert not any(f.rule_id == NAME_REFRESH_RULE_ID for e in events for f in e.all_findings)


def test_a_demo_or_a_captured_state_says_nothing_about_names():
    """A demo state's names are fixed and nothing reads them: no INFO."""
    events = list(watch(lambda: ConsoleState({"/ch/1/name": "Kick"}),
                        max_iterations=2, sleep=lambda s: None))
    assert not any(f.rule_id == NAME_REFRESH_RULE_ID for e in events for f in e.all_findings)


def test_the_default_is_about_thirty_seconds_at_the_measured_cycle():
    """A11 (2026-09-24): 4.8s a node-dump pass, plus the default 2s
    interval; a pass between refreshes drops its names. One refresh and
    N-1 passes between should land near 30s."""
    kwargs = dict(COMPACT, bulk=True)
    full = cli.estimated_pass_seconds(kwargs) + 2.0
    between = cli.estimated_pass_seconds(kwargs, names_known=True) + 2.0
    cycle = full + (DEFAULT_NAME_REFRESH - 1) * between
    assert 25 <= cycle <= 35, cycle


# -- the scoped names still resolve from Start -------------------------------------


def test_scoped_names_resolve_from_the_start_reading_and_keep_the_marking():
    from atoo.watch_conditions import read_names_at_start

    desk = _Counting(_compact_desk(**{"/bus/3/name": "Drums"}))
    asked = []

    def read_name(address):
        asked.append(address)
        return "PA" if address == "/main/1/name" else None

    provider = read_names_at_start(_provider(desk, every=3), read_name,
                                   [f"/main/{n}/name" for n in range(1, 5)])
    first = provider()
    second = provider()
    assert first.text("/main/1/name") == "PA"
    assert first.text("/bus/3/name") == "Drums"
    assert first.name_refresh == second.name_refresh == 3
    assert len(asked) == 4, "a Main's names are read once, at Start"


# -- the CLI -----------------------------------------------------------------------


class _Desk:
    def close(self):
        pass


@pytest.fixture
def live(monkeypatch):
    """Every `read_console_state` call `watch --console` makes, by its
    `names` argument."""
    calls: list = []

    def read(console, **kwargs):
        calls.append(kwargs.get("names"))
        return ConsoleState({"/ch/1/name": "Kick", "/bus/1/name": "Mon"},
                            console_model="wing-compact")

    def open_console(args, raw_log=None):
        args.detected_console_model = "wing-compact"
        return _Desk()

    monkeypatch.setattr(cli, "_open_console", open_console)
    monkeypatch.setattr(audit, "read_console_state", read)
    return calls


def _watch(*more):
    return main(["watch", "--console", "192.0.2.1", "--no-progress",
                 "--interval", "0", *more])


def test_watch_reads_names_on_the_first_pass_and_every_fifth(live, capsys):
    _watch("--count", "7")
    assert [names is None for names in live] == [True, False, False, False, False,
                                                 True, False]
    # The names the refresh read, and the ones it asked and got nothing for.
    assert live[1]["/ch/1/name"] == "Kick"
    assert live[1]["/bus/1/name"] == "Mon"
    assert live[1]["/ch/2/name"] is None
    out = capsys.readouterr().out
    assert "W001" in out
    assert "Names are read at Start and every 5 passes" in out


@pytest.mark.parametrize("flags, expected", [
    ([], DEFAULT_NAME_REFRESH),
    (["--per-leaf"], 1),
    (["--name-refresh", "1"], 1),
    (["--name-refresh", "3"], 3),
    (["--per-leaf", "--name-refresh", "4"], 4),
])
def test_the_name_refresh_default_and_the_flag(flags, expected):
    _root, subparsers = cli.build_parser()
    args = subparsers["watch"].parse_args(["--console", "x", *flags])
    assert cli.watch_name_refresh(args) == expected


def test_name_refresh_1_reads_names_every_pass_and_says_nothing(live, capsys):
    _watch("--count", "3", "--name-refresh", "1")
    assert live == [None, None, None]
    out = capsys.readouterr().out
    assert "W001" not in out
    assert "Names are read at Start" not in out


def test_name_refresh_0_is_refused(capsys):
    with pytest.raises(SystemExit):
        main(["watch", "--console", "x", "--name-refresh", "0"])
    assert "less than 1" in capsys.readouterr().err


# -- the Watch page ------------------------------------------------------------------


@pytest.mark.parametrize("body, expected", [
    ({}, DEFAULT_NAME_REFRESH),            # what the page sends
    ({"per_leaf": True}, 1),
    ({"name_refresh": 1}, 1),
    ({"name_refresh": 2}, 2),
])
def test_watch_start_passes_the_name_refresh_to_the_provider(monkeypatch, body, expected):
    from conftest import require_fastapi_testclient

    testclient = require_fastapi_testclient()
    from atoo import webui

    seen: list[int] = []

    def factory(ip, *, port=2223, timeout=1.0, read_kwargs=None, name_refresh=1, **extra):
        seen.append(name_refresh)
        raise webui.ConsoleUnreachable("test: stop here")

    monkeypatch.setattr(webui, "console_provider_factory", factory)
    with testclient.TestClient(webui.create_app()) as client:
        r = client.post("/api/watch/start", json={
            "source": "console", "console": "192.0.2.1", "interval": 0.1, **body})
        assert r.status_code == 200
        deadline = time.monotonic() + 5
        while not seen and time.monotonic() < deadline:
            time.sleep(0.01)
        client.post("/api/watch/stop")
    assert seen == [expected]


def test_watch_start_refuses_a_name_refresh_below_1():
    from conftest import require_fastapi_testclient

    testclient = require_fastapi_testclient()
    from atoo import webui

    with testclient.TestClient(webui.create_app()) as client:
        r = client.post("/api/watch/start", json={
            "source": "console", "console": "192.0.2.1", "name_refresh": 0})
        assert r.status_code == 400
        assert "name_refresh" in r.json()["error"]


def test_the_watch_page_provider_skips_names_between_refreshes(monkeypatch):
    from atoo import webui
    import atoo.console as console_module

    desk = _Counting(_compact_desk())
    desk.identity = lambda: console_module.OscReply(
        address="/?", typetag="s", args=["WING,198.51.100.1,DESK,wing-compact,SER,3.1"])
    desk.close = lambda: None
    monkeypatch.setattr(console_module, "WingConsole", lambda *a, **k: desk)

    provider, close = webui.console_provider_factory("198.51.100.1", name_refresh=2)
    first = provider()
    asked = [a for a in desk.gets if is_name_address(a)]
    desk.reset()
    second = provider()
    close()
    assert asked
    assert not [a for a in desk.gets if is_name_address(a)]
    assert second.values == first.values
    assert second.name_refresh == 2
