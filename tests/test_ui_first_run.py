"""`atoo ui` on first run: it opens the browser once
the server answers, `--no-browser` does not, an Atoo UI already on
the port is opened rather than refused, and with no `--show` the page
starts in `[workspace] default`.

The browser tests serve for real -- a stubbed server cannot show the
"only once it answers" half -- and stop the server from inside the
patched `webbrowser.open`, so the test ends the moment the browser would
have opened. A safety timer stops it regardless, so a regression fails
rather than hangs.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import webbrowser
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient
from atoo import cli
from atoo.cli import main

uvicorn = pytest.importorskip("uvicorn")


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(Path, "home", lambda: h)
    return h


@pytest.fixture
def display(monkeypatch):
    """A graphical session, whatever the machine running the suite has."""
    monkeypatch.setattr(cli, "_can_open_browser", lambda: True)


def _serve_until_browser_opens(monkeypatch, argv: list[str]) -> tuple[int, list[str], list]:
    """Run `main(argv)` for real; returns (exit code, URLs opened, the
    status the server gave at the moment each was opened)."""
    servers: list = []
    opened: list[str] = []
    answered: list = []
    original_run = uvicorn.Server.run

    def run(self, sockets=None):
        servers.append(self)
        # The safety net: a server that never opens a browser still stops.
        threading.Timer(20, lambda: setattr(self, "should_exit", True)).start()
        return original_run(self, sockets=sockets)

    def fake_open(url, *args, **kwargs):
        opened.append(url)
        answered.append(cli._local_get_json(url + "api/status", timeout=2))
        servers[0].should_exit = True
        return True

    monkeypatch.setattr(uvicorn.Server, "run", run)
    monkeypatch.setattr(webbrowser, "open", fake_open)
    code = main(argv)
    return code, opened, answered


def test_ui_opens_the_browser_by_default_once_the_server_answers(home, display, monkeypatch,
                                                                 capsys):
    code, opened, answered = _serve_until_browser_opens(monkeypatch, ["ui", "--port", "0"])
    assert code == 0
    assert len(opened) == 1
    out = capsys.readouterr().out
    # The page opens by itself, so the start does not print its address
    # ; --no-browser still does.
    assert opened[0].startswith("http://127.0.0.1:")
    assert "http://" not in out
    # When the browser was opened, the page's server was already answering.
    assert answered[0] is not None and "instance" in answered[0]


def test_no_browser_opens_nothing(home, display, monkeypatch, stub_ui_server, capsys):
    opened: list = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: opened.append(a) or True)
    assert main(["ui", "--port", "0", "--no-browser"]) == 0
    assert opened == []
    assert "http://127.0.0.1:" in capsys.readouterr().out


def test_a_server_that_never_answers_opens_no_browser(home, display, monkeypatch,
                                                      stub_ui_server):
    """The stub returns without serving: nothing ever answered, so nothing
    may be opened -- the browser waits for the server, not for the bind."""
    opened: list = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: opened.append(a) or True)
    assert main(["ui", "--port", "0"]) == 0
    time.sleep(0.3)
    assert opened == []


def test_no_display_opens_nothing_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    for name in ("BROWSER", "DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    opened: list = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: opened.append(a) or True)
    cli._open_browser("http://127.0.0.1:8420/")
    assert opened == []
    # The start no longer prints the address (2026-10-27), so this says it.
    assert "open http://127.0.0.1:8420/ yourself" in capsys.readouterr().out


class _RunningUi:
    """A real Atoo UI on a kernel-chosen port, in a thread."""

    def __init__(self, bundle_dir=None):
        from atoo.webui import create_app
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(
            create_app(initial_bundle=bundle_dir), log_level="warning"))
        self.thread = threading.Thread(target=self.server.run,
                                       kwargs={"sockets": [self.sock]}, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 15
        while cli._atoo_ui_status("127.0.0.1", self.port) is None:
            assert time.monotonic() < deadline, "the background UI never answered"
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)


def test_a_atoo_ui_already_on_the_port_is_opened_not_refused(home, display, monkeypatch,
                                                                   capsys):
    require_fastapi_testclient()
    opened: list = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    with _RunningUi() as running:
        assert main(["ui", "--port", str(running.port)]) == 0
    assert opened == [f"http://127.0.0.1:{running.port}/"]
    out, err = capsys.readouterr()
    assert f"Atoo is already running at http://127.0.0.1:{running.port}/" in out
    assert "couldn't serve" not in err


def test_the_running_ui_with_another_show_open_is_named(home, display, monkeypatch, tmp_path,
                                                        capsys):
    require_fastapi_testclient()
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)
    wanted = tmp_path / "myshow"
    wanted.mkdir()
    with _RunningUi() as running:
        assert main(["ui", "--port", str(running.port), "--show", str(wanted)]) == 0
    out = capsys.readouterr().out
    assert f"It has no show open, not {wanted}" in out


def test_something_else_on_the_port_is_still_refused(home, capsys):
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        assert main(["ui", "--port", str(port), "--no-browser"]) == 1
    finally:
        holder.close()
    assert f"--port {port + 1}" in capsys.readouterr().err


# ---- [workspace] default: where the page starts --------------------------

def _shell_blob(html: str) -> dict:
    start = html.index('id="initial-shell"')
    return json.loads(html[html.index(">", start) + 1:html.index("</script>", start)])


def test_ui_with_no_show_starts_in_the_workspace(home, stub_ui_server, capsys):
    fastapi_testclient = require_fastapi_testclient()
    workspace = home / "Documents" / "Atoo"
    workspace.mkdir(parents=True)
    (home / ".atoo.config").write_text('[workspace]\ndefault = "~/Documents/Atoo"\n')
    assert main(["ui", "--port", "0", "--no-browser"]) == 0
    out = capsys.readouterr().out
    assert "Working folder: ~/Documents/Atoo\n" in out
    assert "atoo init" not in out
    app = stub_ui_server[0].app
    with fastapi_testclient.TestClient(app) as client:
        assert _shell_blob(client.get("/").text)["workspace"] == str(workspace)


def test_ui_with_no_show_and_no_workspace_suggests_init(home, stub_ui_server, capsys):
    assert main(["ui", "--port", "0", "--no-browser"]) == 0
    out, err = capsys.readouterr()
    assert "`atoo init`" in out
    assert err == ""


def test_the_page_starts_its_file_browser_in_the_workspace():
    """The Python suite cannot run the page (`web/static/`): this
    is the served-asset check that the blob key is what the page reads,
    and that each no-bundle start falls back to it."""
    fastapi_testclient = require_fastapi_testclient()
    from atoo.webui import create_app
    with fastapi_testclient.TestClient(create_app(initial_workspace="/w")) as client:
        assert _shell_blob(client.get("/").text)["workspace"] == "/w"
        shell = client.get("/static/shell.js").text
        files = client.get("/static/filebrowser.js").text
    assert "const workspace = startup.workspace || \"\";" in shell
    assert shell.count("start: bundle ? parentOf(bundle.directory) : workspace,") == 2
    assert "workspace: () => workspace," in shell
    assert "SP.workspace()" in files


@pytest.mark.parametrize("platform, expected", [("linux", True), ("darwin", True),
                                                ("win32", False)])
def test_the_ui_socket_sets_reuseaddr_except_on_windows(home, stub_ui_server, monkeypatch,
                                                        platform, expected):
    """On Windows SO_REUSEADDR lets a second server bind a port already in
    use, so a second `atoo ui` would share the port instead of
    finding the running one. Elsewhere it only lets a restart reuse a port
    in TIME_WAIT, which is wanted."""
    set_options: list = []

    class RecordingSocket(socket.socket):
        def setsockopt(self, level, option, value, *rest):
            set_options.append((level, option))
            return super().setsockopt(level, option, value, *rest)

    monkeypatch.setattr(cli.socket, "socket", RecordingSocket)
    monkeypatch.setattr(cli.sys, "platform", platform)
    assert main(["ui", "--port", "0", "--no-browser"]) == 0
    assert ((socket.SOL_SOCKET, socket.SO_REUSEADDR) in set_options) is expected
