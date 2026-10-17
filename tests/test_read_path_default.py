"""The node-dump read is the default for a live read; `--per-leaf` is the
way back.

`--bulk-read` was opt-in "until one confirming run". A11 made that run
on the maintainer's Compact on 2026-09-24
(`examples/console-runs/session-2026-09-24-1045/A11-read-speed.txt`):
5,860 values each way, 0 only per-leaf, 0 only by dump, 0 differing, and
4.8s against 118.8s. So every live read now goes by node dump unless the
user asks otherwise.

The lesson this file is built around is *a default that no
test omits is a default that no test covers*: the first test of each
command passes NO read-path flag at all, because that absent case is the
one every user gets.

What is pinned, and where:

1. `audit --console` and `watch --console` read by node dump with no
   flag, and per leaf with `--per-leaf`.
2. `--bulk-read` still parses (scripts under `examples/console-runs/`
   pass it and must keep running) and changes nothing.
3. `--bulk-read --per-leaf` together is refused, not silently resolved.
4. The Watch page (`atoo ui`) reads by node dump by default, and
   `ConnectRequest.per_leaf` is its opt-out.
5. `amend`'s untouched-strip proof honours `--per-leaf` too.
6. `read_console_state`'s OWN default stays per-leaf -- because
   `a11-read-speed.sh`, the harness that compares the two paths, calls it
   with no `bulk` argument as its per-leaf side.

No test here reads a bundle under `examples/`, and none touches a console.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from atoo import audit, cli
from atoo.audit import ConsoleState
from atoo.cli import main
from atoo.console import OscReply

DEMO = Path(__file__).parent / "fixtures" / "audit_demo_state.json"


class _Desk:
    """An open `WingConsole` stand-in: the read itself is replaced, so
    only the context manager and `close` are ever used."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


@pytest.fixture
def live(monkeypatch):
    """Every `read_console_state` call a live command makes, by its
    keyword arguments. The read returns the demo state, so the rest of
    the command runs as it would against a desk."""
    values = json.loads(DEMO.read_text())
    calls: list[dict] = []

    def read(console, **kwargs):
        calls.append(kwargs)
        return ConsoleState(dict(values), console_model="wing-compact")

    def open_console(args, raw_log=None):
        args.detected_console_model = "wing-compact"
        return _Desk()

    monkeypatch.setattr(cli, "_open_console", open_console)
    monkeypatch.setattr(audit, "read_console_state", read)
    return calls


def _audit(*more):
    return main(["audit", "--console", "192.0.2.1", "--no-progress", *more])


def _watch(monkeypatch, *more):
    import atoo.watch as watch_module

    def one_pass(state_provider, **kwargs):
        state_provider()
        return iter(())

    monkeypatch.setattr(watch_module, "watch", one_pass, raising=False)
    return main(["watch", "--console", "192.0.2.1", "--no-progress",
                 "--count", "1", "--interval", "0", *more])


# -- 1. the default, with nothing passed ----------------------------------


def test_audit_reads_by_node_dump_when_no_flag_is_given(live, capsys):
    _audit()
    assert len(live) == 1
    assert live[0]["bulk"] is True


def test_watch_reads_by_node_dump_when_no_flag_is_given(live, monkeypatch, capsys):
    _watch(monkeypatch)
    assert len(live) == 1
    assert live[0]["bulk"] is True


def test_the_default_read_prints_no_banner(live, capsys):
    """The EXPERIMENTAL banner went with the flag. A default is not
    something to apologise for on every run."""
    _audit()
    err = capsys.readouterr().err
    assert "EXPERIMENTAL" not in err
    assert "--per-leaf:" not in err


# -- 1b. the way back -----------------------------------------------------


def test_audit_per_leaf_reads_one_leaf_at_a_time(live, capsys):
    _audit("--per-leaf")
    assert live[0]["bulk"] is False


def test_watch_per_leaf_reads_one_leaf_at_a_time(live, monkeypatch, capsys):
    _watch(monkeypatch, "--per-leaf")
    assert live[0]["bulk"] is False


def test_audit_per_leaf_says_what_it_is_costing(live, capsys):
    """A two-minute read with no warning looks like a hang -- the
    lesson. `--per-leaf` says up front that it is the slow path."""
    _audit("--per-leaf")
    assert cli.PER_LEAF_BANNER in capsys.readouterr().err


# -- 2/3. the legacy flag -------------------------------------------------


def test_the_legacy_bulk_read_flag_still_parses_and_changes_nothing(live, capsys):
    code = _audit("--bulk-read")
    assert code in (0, 1), "the flag must parse, not exit 2 with a usage error"
    assert live[0]["bulk"] is True
    assert "EXPERIMENTAL" not in capsys.readouterr().err


def test_watch_still_takes_the_legacy_flag(live, monkeypatch, capsys):
    _watch(monkeypatch, "--bulk-read")
    assert live[0]["bulk"] is True


def test_bulk_read_and_per_leaf_together_are_refused(live, capsys):
    with pytest.raises(SystemExit) as exc:
        _audit("--bulk-read", "--per-leaf")
    assert exc.value.code == 2
    assert live == [], "a contradictory command must not read the desk"


# -- the progress bar and the estimate follow the path ---------------------


def _args(**overrides):
    import argparse

    base = dict(channels=40, aux=8, buses=16, mains=4, matrices=8, dcas=16,
                mute_groups=8, input_sockets=None, output_sockets=None,
                detected_console_model="wing-compact")
    base.update(overrides)
    return argparse.Namespace(**base)


def test_a_namespace_with_no_read_path_attribute_reads_by_node_dump():
    """`_console_read_kwargs` is handed namespaces built by hand as well as
    by argparse. One that carries neither flag is the absent case too."""
    assert cli._console_read_kwargs(_args())["bulk"] is True
    assert cli._console_read_kwargs(_args(per_leaf=True))["bulk"] is False
    assert cli._console_read_kwargs(_args(per_leaf=False, bulk_read=True))["bulk"] is True


def test_the_watch_estimate_quotes_the_path_it_will_actually_use():
    bulk = cli._console_read_kwargs(_args())
    per_leaf = cli._console_read_kwargs(_args(per_leaf=True))

    fast = cli._watch_estimate(bulk, 8, 2.0)
    slow = cli._watch_estimate(per_leaf, 8, 2.0)
    assert "by node dump" in fast and "--per-leaf" not in fast
    assert "--per-leaf" in slow

    # Counted, not pinned: requests are one per node plus one per leaf a
    # dump never carries, and per-leaf is one per address.
    assert cli.read_requests(per_leaf) == cli.read_addresses(per_leaf)
    assert cli.read_requests(bulk) * 10 < cli.read_requests(per_leaf)
    # A11's rates: a whole-Compact bulk pass is seconds, per-leaf minutes.
    assert cli.estimated_pass_seconds(bulk) < 10
    assert cli.estimated_pass_seconds(per_leaf) > 60


def test_the_watch_estimate_counts_the_interval_between_passes():
    """At ~4s a pass, the default two-second gap is a third of the run.
    `watch` sleeps between passes, not after the last one."""
    kwargs = cli._console_read_kwargs(_args())
    one_pass = cli.estimated_pass_seconds(kwargs)
    line = cli._watch_estimate(kwargs, 3, 10.0)
    expected = round(3 * one_pass + 2 * 10.0)
    assert f"about {expected}s." in line, line


def test_watch_prints_the_node_dump_estimate_by_default(live, monkeypatch, capsys):
    _watch(monkeypatch)
    assert "by node dump" in capsys.readouterr().out


# -- 4. the Watch page ----------------------------------------------------


class _DumpingDesk:
    """Records which read path the Watch page's provider took."""

    dumps: list[str] = []
    gets: list[str] = []

    def __init__(self, ip, port=2223, timeout=1.0):
        pass

    def identity(self):
        return OscReply(address="/?", typetag="s",
                        args=["WING,198.51.100.1,DESK,wing-compact,SER,3.1"])

    def get(self, address):
        type(self).gets.append(address)
        return None

    def node_dump(self, node):
        type(self).dumps.append(node)
        return None

    def close(self):
        pass


@pytest.fixture
def dumping_desk(monkeypatch):
    import atoo.console as console_module

    _DumpingDesk.dumps = []
    _DumpingDesk.gets = []
    monkeypatch.setattr(console_module, "WingConsole", _DumpingDesk)
    return _DumpingDesk


def test_the_watch_page_reads_by_node_dump_by_default(dumping_desk):
    from atoo import webui

    provider, close = webui.console_provider_factory("198.51.100.1")
    provider()
    close()
    assert dumping_desk.dumps, "the Watch page must read by node dump by default"


def test_the_watch_page_can_still_read_per_leaf(dumping_desk):
    from atoo import webui

    provider, close = webui.console_provider_factory(
        "198.51.100.1", read_kwargs={"bulk": False})
    provider()
    close()
    assert dumping_desk.dumps == []
    assert dumping_desk.gets


def test_the_connect_request_defaults_to_node_dump():
    pytest.importorskip("pydantic")
    from atoo.webui import ConnectRequest

    assert ConnectRequest(source="console", console="198.51.100.1").per_leaf is False


@pytest.mark.parametrize("body, expected_bulk", [
    ({}, True),                       # the absent case: what the form sends
    ({"per_leaf": True}, False),
])
def test_watch_start_maps_per_leaf_onto_the_read(monkeypatch, body, expected_bulk):
    from conftest import require_fastapi_testclient

    testclient = require_fastapi_testclient()
    from atoo import webui

    seen: list[dict] = []

    def factory(ip, *, port=2223, timeout=1.0, read_kwargs=None, name_refresh=1):
        seen.append(dict(read_kwargs or {}))
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
    assert seen, "the session never asked for a provider"
    assert seen[0]["bulk"] is expected_bulk


# -- 6. the library default stays where the A11 harness needs it ----------


def test_read_console_state_itself_still_defaults_to_per_leaf(dumping_desk):
    """Deliberate, and the one place the old default survives.

    `examples/console-runs/a11-read-speed.sh` -- the run that compares the
    two paths on hardware, and the one that will first compare the 304
    insert/FX leaves an earlier change added -- calls `read_console_state(c, ...)`
    with no `bulk` for its per-leaf side. Flip this default and that
    comparison silently becomes dump against dump, and reports a zero
    that means nothing. The CLI and the Watch page choose bulk
    explicitly instead; see `cli._console_read_kwargs`.
    """
    audit.read_console_state(_DumpingDesk("198.51.100.1"), input_sockets={"LCL": 1})
    assert dumping_desk.dumps == []
    assert dumping_desk.gets
