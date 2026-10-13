"""`atoo ping` -- an earlier change.

The command exists because "is the desk reachable" was only answerable by
running a command that does something else: `atoo audit --console
<ip>` prints the identity line, but reads the whole console first. So the
property these tests exist to defend is not that `ping` prints something
nice -- it is that **it reads nothing beyond the identity reply**. That
is what makes it safe to type during a show, and it is the thing a later
change could quietly break (a shared helper grows a read; someone
"helpfully" reuses `_add_console_read_arguments`). A docstring would not
notice. A fake console that records every request it is given does.
"""

from __future__ import annotations

import pytest

from atoo.cli import main
from atoo.console import OscReply

IDENTITY = "WING,192.0.2.16,FOH,wing-compact,SN12345,3.1-0"


class RecordingConsole:
    """Answers `/?` and records every request, so a test can assert on
    what was asked rather than on what the code claims it asks."""

    instances: list["RecordingConsole"] = []

    def __init__(self, ip, port=2223, timeout=1.0, raw_log=None):
        self.ip, self.port, self.timeout = ip, port, timeout
        self.requests: list[str] = []
        self.closed = False
        RecordingConsole.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False

    def identity(self):
        self.requests.append("/?")
        return OscReply(address="/?", typetag="s", args=[IDENTITY])

    def get(self, address):
        self.requests.append(address)
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def recording_console(monkeypatch):
    RecordingConsole.instances = []
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole", RecordingConsole)
    return RecordingConsole


def test_ping_prints_the_identity_line_and_exits_zero(recording_console, capsys):
    code = main(["ping", "--console", "192.0.2.16"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Console: " + IDENTITY in out


def test_ping_reads_nothing_beyond_the_identity(recording_console):
    """The whole point of the command: "Reads nothing else.
    No strip sweep -- the point is that it is instant and cannot disturb
    anything." Exactly one request, and it is `/?`."""
    main(["ping", "--console", "192.0.2.16"])
    console, = recording_console.instances
    assert console.requests == ["/?"]


def test_ping_closes_the_socket(recording_console):
    main(["ping", "--console", "192.0.2.16"])
    console, = recording_console.instances
    assert console.closed


def test_ping_names_the_model_the_desk_states_for_itself(recording_console, capsys):
    """An earlier change asks for the detected model specifically, because it is
    what `apply` cross-checks a plan against and there was no
    way to see it without running an apply."""
    main(["ping", "--console", "192.0.2.16"])
    out = capsys.readouterr().out
    assert "Detected model: WING Compact (wing-compact)" in out


def test_ping_says_so_when_the_model_is_not_one_we_know(monkeypatch, capsys):
    """A desk that answers but names a model `console_facts` does not
    recognise is a successful ping -- exit 0 -- but `apply`'s model
    cross-check will silently not fire against it, which is worth one
    line here rather than a surprise later."""
    import atoo.console as console_module

    class UnknownModelConsole(RecordingConsole):
        def identity(self):
            self.requests.append("/?")
            return OscReply(address="/?", typetag="s",
                            args=["WING,192.0.2.16,FOH,wing-zeppelin,SN1,3.1-0"])

    RecordingConsole.instances = []
    monkeypatch.setattr(console_module, "WingConsole", UnknownModelConsole)

    code = main(["ping", "--console", "192.0.2.16"])
    assert code == 0
    assert "Detected model: not recognised" in capsys.readouterr().out


def test_ping_reports_no_reply_on_stderr_and_exits_one(monkeypatch, capsys):
    import atoo.console as console_module

    class SilentConsole(RecordingConsole):
        def identity(self):
            self.requests.append("/?")
            return None

    RecordingConsole.instances = []
    monkeypatch.setattr(console_module, "WingConsole", SilentConsole)

    code = main(["ping", "--console", "192.0.2.16"])
    assert code == 1
    captured = capsys.readouterr()
    assert "no reply from 192.0.2.16:2223" in captured.err
    assert "is its OSC remote enabled?" in captured.err
    # The failure belongs on stderr, so `atoo ping ... > file` in a
    # checklist still shows the operator what went wrong.
    assert "no reply" not in captured.out


def test_ping_distinguishes_a_socket_error_from_silence(monkeypatch, capsys):
    """The distinction, which until now existed only inside
    `apply_cmd`: a SOCKET_ERROR reply is truthy, so treating it as a
    successful connect printed `Console: OSError: [Errno 65] No route to
    host`. `_open_console` -- which `ping`, `audit` and `watch` all use --
    had never been given the same guard."""
    import atoo.console as console_module

    class UnreachableConsole(RecordingConsole):
        def identity(self):
            self.requests.append("/?")
            return OscReply(address="/?", typetag="SOCKET_ERROR",
                            args=["OSError: [Errno 65] No route to host"])

    RecordingConsole.instances = []
    monkeypatch.setattr(console_module, "WingConsole", UnreachableConsole)

    code = main(["ping", "--console", "192.0.2.16"])
    assert code == 1
    captured = capsys.readouterr()
    assert "couldn't reach 192.0.2.16:2223" in captured.err
    assert "No route to host" in captured.err
    assert "Console: OSError" not in captured.out


def test_audit_also_gets_the_socket_error_guard(monkeypatch, capsys):
    """The same guard, reached through `audit` rather than `ping` -- this
    is the command that had the bug, and it is the reason the fix went
    into `_open_console` rather than into `ping_cmd`."""
    import atoo.console as console_module

    class UnreachableConsole(RecordingConsole):
        def identity(self):
            self.requests.append("/?")
            return OscReply(address="/?", typetag="SOCKET_ERROR",
                            args=["OSError: [Errno 61] Connection refused"])

    RecordingConsole.instances = []
    monkeypatch.setattr(console_module, "WingConsole", UnreachableConsole)

    code = main(["audit", "--console", "192.0.2.16"])
    assert code == 1
    captured = capsys.readouterr()
    assert "couldn't reach 192.0.2.16:2223" in captured.err
    assert "Console: OSError" not in captured.out


def test_ping_honours_port_and_timeout(recording_console):
    main(["ping", "--console", "192.0.2.16", "--port", "9999", "--timeout", "0.25"])
    console, = recording_console.instances
    assert (console.port, console.timeout) == (9999, 0.25)


def test_ping_handles_an_identity_reply_with_no_args(monkeypatch, capsys):
    """`_open_console`'s fallback branch -- a reply with an empty arg list
    is still a reply, so the desk is reachable and the exit code says so."""
    import atoo.console as console_module

    class TerseConsole(RecordingConsole):
        def identity(self):
            self.requests.append("/?")
            return OscReply(address="/?", typetag="", args=[])

    RecordingConsole.instances = []
    monkeypatch.setattr(console_module, "WingConsole", TerseConsole)

    code = main(["ping", "--console", "192.0.2.16"])
    assert code == 0
    assert "Console at 192.0.2.16" in capsys.readouterr().out
