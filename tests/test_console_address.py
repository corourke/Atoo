"""Resolving which console a command talks to -- an earlier change.

The maintainer, from a console session: `--console <ip>` has to be retyped on
every `ping`, `apply`, `audit` and `watch`, and working through the
console checklist means typing the same IP a dozen times. Getting one
digit wrong on an `apply --confirm` is a write aimed at the wrong box on
the network.

Two properties are worth more than the convenience, and both are tested
here rather than described:

1. **Precedence is the same everywhere else in this CLI**: an explicit
   flag beats the environment, which beats `~/.atoo.config`, which
   beats the built-in default.
2. **Nothing defaults silently.** A run that connects somewhere the
   command line never named says so. The failure that guards against is
   a stale `export`, aimed at last week's desk, on a command carrying
   `--confirm`.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from atoo import cli as cli_module
from atoo.cli import main
from atoo.console import OscReply

IDENTITY = "WING,192.0.2.16,FOH,wing-compact,SN12345,3.1-0"


class ConnectRecorder:
    """Records what address/port/timeout a command actually connected to."""

    calls: list[dict] = []

    def __init__(self, ip, port=2223, timeout=1.0, raw_log=None):
        ConnectRecorder.calls.append({"ip": ip, "port": port, "timeout": timeout})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def identity(self):
        return OscReply(address="/?", typetag="s", args=[IDENTITY])

    def get(self, address):
        return None

    def close(self):
        pass


@pytest.fixture
def connected(monkeypatch):
    """A stand-in console, plus a clean environment and an empty home so
    no real `~/.atoo.config` or `export` leaks into a test."""
    import atoo.console as console_module

    ConnectRecorder.calls = []
    monkeypatch.setattr(console_module, "WingConsole", ConnectRecorder)
    for var in ("ATOO_CONSOLE", "ATOO_CONSOLE_PORT", "ATOO_CONSOLE_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    return ConnectRecorder


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """`~` pointed at a tmpdir, the way `tests/test_config.py` does it --
    `Path.home`, not `$HOME`, because `config.expand_home` reads the
    former on purpose."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _write_config(home: Path, body: str) -> None:
    (home / ".atoo.config").write_text(body)


# --------------------------------------------------------------- address


def test_the_flag_is_used_when_given(connected, fake_home, capsys):
    code = main(["ping", "--console", "192.0.2.16"])
    assert code == 0
    assert connected.calls[0]["ip"] == "192.0.2.16"
    # Nothing to announce: the command line said it.
    assert "Using console" not in capsys.readouterr().err


def test_the_environment_supplies_the_address(connected, fake_home, monkeypatch, capsys):
    monkeypatch.setenv("ATOO_CONSOLE", "192.0.2.17")
    assert main(["ping"]) == 0
    assert connected.calls[0]["ip"] == "192.0.2.17"
    assert "Using console 192.0.2.17 from ATOO_CONSOLE" in capsys.readouterr().err


def test_the_config_file_supplies_the_address(connected, fake_home, capsys):
    _write_config(fake_home, '[console]\ndefault = "192.0.2.18"\n')
    assert main(["ping"]) == 0
    assert connected.calls[0]["ip"] == "192.0.2.18"
    err = capsys.readouterr().err
    assert "Using console 192.0.2.18 from" in err
    assert "[console]" in err


def test_the_flag_beats_the_environment(connected, fake_home, monkeypatch, capsys):
    monkeypatch.setenv("ATOO_CONSOLE", "192.0.2.17")
    main(["ping", "--console", "192.0.2.16"])
    assert connected.calls[0]["ip"] == "192.0.2.16"
    assert "Using console" not in capsys.readouterr().err


def test_the_environment_beats_the_config_file(connected, fake_home, monkeypatch, capsys):
    _write_config(fake_home, '[console]\ndefault = "192.0.2.18"\n')
    monkeypatch.setenv("ATOO_CONSOLE", "192.0.2.17")
    main(["ping"])
    assert connected.calls[0]["ip"] == "192.0.2.17"
    assert "from ATOO_CONSOLE" in capsys.readouterr().err


# ------------------------------------------------------- port and timeout


def test_port_and_timeout_fall_back_to_the_built_in_defaults(connected, fake_home):
    """They stopped being argparse defaults so the resolver could tell
    "typed" from "not typed" -- the values a user gets must not change."""
    main(["ping", "--console", "192.0.2.16"])
    assert connected.calls[0]["port"] == 2223
    assert connected.calls[0]["timeout"] == 1.0


def test_port_and_timeout_come_from_the_environment(connected, fake_home, monkeypatch, capsys):
    monkeypatch.setenv("ATOO_CONSOLE_PORT", "9999")
    monkeypatch.setenv("ATOO_CONSOLE_TIMEOUT", "0.25")
    main(["ping", "--console", "192.0.2.16"])
    assert connected.calls[0]["port"] == 9999
    assert connected.calls[0]["timeout"] == 0.25
    err = capsys.readouterr().err
    assert "Using console port 9999 from ATOO_CONSOLE_PORT" in err
    assert "Using console timeout 0.25s from ATOO_CONSOLE_TIMEOUT" in err


def test_port_and_timeout_come_from_the_config_file(connected, fake_home):
    _write_config(fake_home, '[console]\ndefault = "192.0.2.18"\nport = 9000\ntimeout = 2.5\n')
    main(["ping"])
    assert connected.calls[0]["port"] == 9000
    assert connected.calls[0]["timeout"] == 2.5


def test_flags_beat_both_for_port_and_timeout(connected, fake_home, monkeypatch):
    monkeypatch.setenv("ATOO_CONSOLE_PORT", "9999")
    _write_config(fake_home, "[console]\nport = 9000\n")
    main(["ping", "--console", "192.0.2.16", "--port", "2223", "--timeout", "3.0"])
    assert connected.calls[0]["port"] == 2223
    assert connected.calls[0]["timeout"] == 3.0


def test_a_restated_default_port_is_not_announced(connected, fake_home, monkeypatch, capsys):
    """A config file or environment that restates 2223 changes nothing,
    and a line saying so is noise on every single command."""
    monkeypatch.setenv("ATOO_CONSOLE_PORT", "2223")
    main(["ping", "--console", "192.0.2.16"])
    assert "Using console port" not in capsys.readouterr().err


def test_an_unparseable_port_in_the_environment_is_ignored_with_one_line(
        connected, fake_home, monkeypatch, capsys):
    """A stale or fat-fingered `export` must not turn every command into
    a traceback -- same posture `config.py` takes for its own file."""
    monkeypatch.setenv("ATOO_CONSOLE_PORT", "two-two-two-three")
    assert main(["ping", "--console", "192.0.2.16"]) == 0
    assert connected.calls[0]["port"] == 2223
    assert "is not a port number" in capsys.readouterr().err


# ------------------------------------------------- required-or-resolvable


def test_ping_with_no_address_anywhere_says_all_three_ways(connected, fake_home, capsys):
    code = main(["ping"])
    assert code == 2  # what argparse's own `required=True` exited with
    err = capsys.readouterr().err
    assert "no console address" in err
    assert "--console <ip>" in err
    assert "ATOO_CONSOLE" in err
    assert "[console] default" in err


def test_apply_with_no_address_anywhere_refuses_before_reading_a_plan(
        connected, fake_home, capsys):
    """`apply` is the one command that writes. It checks first, so a
    missing address cannot be discovered after a plan has been read and
    verified."""
    code = main(["apply", "--plan", "/nonexistent/plan.json", "--confirm"])
    assert code == 2
    err = capsys.readouterr().err
    assert "no console address" in err
    assert "couldn't read plan" not in err


def test_audit_with_no_address_also_names_the_offline_route(connected, fake_home, capsys):
    code = main(["audit"])
    assert code == 2
    err = capsys.readouterr().err
    assert "no console address" in err
    assert "--state FILE" in err


def test_watch_with_no_address_also_names_the_offline_route(connected, fake_home, capsys):
    code = main(["watch"])
    assert code == 2
    err = capsys.readouterr().err
    assert "no console address" in err
    assert "--state-sequence FILES" in err


def test_console_and_state_together_are_still_refused(connected, fake_home):
    """Relaxing `required=True` must not relax the mutual exclusion:
    naming both a console and an offline capture is still a usage error."""
    with pytest.raises(SystemExit):
        main(["audit", "--console", "192.0.2.16", "--state", "x.json"])


# ------------------------------------------------------- offline commands


def test_an_explicit_offline_source_does_not_announce_a_console(
        connected, fake_home, monkeypatch, capsys, tmp_path):
    """`audit --state` never opens a socket. Announcing a console it will
    not contact would be a lie in the one place this feature exists to
    tell the truth."""
    monkeypatch.setenv("ATOO_CONSOLE", "192.0.2.17")
    state = tmp_path / "state.json"
    state.write_text('{"/ch/1/mute": 0}')

    main(["audit", "--state", str(state)])

    assert connected.calls == []
    assert "Using console" not in capsys.readouterr().err


def test_the_ui_port_is_not_a_console_port(connected, fake_home, monkeypatch):
    """`atoo ui --port` is the web server's, and `ui` has no
    `--console` at all -- so the resolver must not run for it. This is the
    one way a single central resolver could have gone quietly wrong."""
    monkeypatch.setenv("ATOO_CONSOLE_PORT", "9999")
    from atoo.cli import build_parser, _resolve_console_settings

    ap, _subs = build_parser()
    args = ap.parse_args(["ui", "--port", "8420"])
    _resolve_console_settings(args)
    assert args.port == 8420
    assert not hasattr(args, "console")


def test_build_is_untouched_by_the_console_environment(connected, fake_home, monkeypatch):
    """`build` never connects to anything. The resolver is a no-op for it
    -- it has no `--console`, and its own `--port` does not exist."""
    monkeypatch.setenv("ATOO_CONSOLE", "192.0.2.17")
    from atoo.cli import build_parser, _resolve_console_settings

    ap, _subs = build_parser()
    args = ap.parse_args(["build", "--input", "x.csv", "--conventions", "y.md"])
    _resolve_console_settings(args)
    assert not hasattr(args, "console")


# ------------------------------------------- the Watch page's field
#
# An earlier change shipped the resolution for the CLI and deliberately left the
# browser out, which made `atoo ui` the one way to reach a console
# that still made you retype the address. An earlier change closes that, and the trap
# it has to walk past is the one `test_the_ui_port_is_not_a_console_port`
# above guards: `ui`'s `--port` is the WEB SERVER's. So `ui_cmd` calls
# `resolve_console_defaults()` -- which touches no args at all -- rather
# than `_resolve_console_settings`.


def test_resolve_console_defaults_reports_the_environment_and_its_source(
        connected, fake_home, monkeypatch):
    monkeypatch.setenv("ATOO_CONSOLE", "192.0.2.17")
    from atoo.cli import resolve_console_defaults

    resolved = resolve_console_defaults()
    assert resolved["address"] == "192.0.2.17"
    assert resolved["address_source"] == "ATOO_CONSOLE"
    # Nothing set these, so there is no provenance to show for them.
    assert (resolved["port"], resolved["port_source"]) == (2223, None)
    assert (resolved["timeout"], resolved["timeout_source"]) == (1.0, None)


def test_resolve_console_defaults_reports_the_config_file_and_its_path(
        connected, fake_home):
    _write_config(fake_home, '[console]\ndefault = "192.0.2.18"\nport = 9000\n')
    from atoo.cli import resolve_console_defaults

    resolved = resolve_console_defaults()
    assert resolved["address"] == "192.0.2.18"
    assert ".atoo.config [console]" in resolved["address_source"]
    assert resolved["port"] == 9000
    assert ".atoo.config [console]" in resolved["port_source"]


def test_resolve_console_defaults_with_nothing_set_has_nothing_to_announce(
        connected, fake_home):
    from atoo.cli import resolve_console_defaults

    resolved = resolve_console_defaults()
    assert resolved["address"] is None and resolved["address_source"] is None
    assert resolved["port_source"] is None and resolved["timeout_source"] is None


def test_the_environment_still_beats_the_config_file_for_the_page(
        connected, fake_home, monkeypatch):
    """Same precedence the CLI gets, from the same function -- this is
    the whole reason an earlier change reuses it instead of writing a second copy."""
    monkeypatch.setenv("ATOO_CONSOLE", "192.0.2.17")
    _write_config(fake_home, '[console]\ndefault = "192.0.2.18"\n')
    from atoo.cli import resolve_console_defaults

    assert resolve_console_defaults()["address"] == "192.0.2.17"


def test_ui_seeds_the_page_without_moving_its_own_web_port(
        connected, fake_home, monkeypatch, stub_ui_server, capsys):
    """The half of `test_the_ui_port_is_not_a_console_port`: with a
    console port in the environment, `atoo ui` still serves on 8420
    and hands the console port to the PAGE. A resolver that mutated args
    here would have served the UI on 9999 -- somewhere nobody is
    looking.

    The assertion is on the address of the LISTENING SOCKET now, not on a
    `port=` keyword: since an earlier change `ui_cmd` binds the socket itself and
    hands it over, so the socket is where the truth about which port got
    served lives. This test is the one place in the suite that must bind
    the real default port, because 8420-not-9999 is the thing it is
    about."""
    monkeypatch.setenv("ATOO_CONSOLE", "192.0.2.17")
    monkeypatch.setenv("ATOO_CONSOLE_PORT", "9999")
    # The default web port, moved to a free one: a machine that is already
    # serving the real 8420 (an Atoo UI left open) must not fail this test.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        default_port = probe.getsockname()[1]
    monkeypatch.setattr(cli_module, "UI_DEFAULT_PORT", default_port)

    assert main(["ui", "--no-browser"]) == 0
    assert len(stub_ui_server) == 1
    app, (_host, served_port) = stub_ui_server[0]
    assert served_port == default_port != 9999
    assert app.state.console_defaults["address"] == "192.0.2.17"
    assert app.state.console_defaults["port"] == 9999

    out = capsys.readouterr().out
    assert f"http://127.0.0.1:{default_port}" in out
    # It announces in the terminal too, not only on the page -- the
    # launching shell is where a stale `export` is likeliest to be spotted.
    assert "192.0.2.17" in out and "ATOO_CONSOLE" in out


def test_ui_with_no_console_anywhere_seeds_nothing(
        connected, fake_home, stub_ui_server, capsys):
    # `--port 0`: this test does not care which port it gets, and hard-
    # coding the default would collide with the test above.
    assert main(["ui", "--port", "0"]) == 0
    app, _address = stub_ui_server[0]
    assert app.state.console_defaults["address"] is None
    out = capsys.readouterr().out
    assert "Console: none configured" in out and " from " not in out.split("Console:")[1]
