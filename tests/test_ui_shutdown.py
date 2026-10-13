"""`atoo ui` must stop on SIGTERM (and SIGINT) with a
Watch socket open.

The Watch WebSocket handler used to wait only on its event queue and never
read the socket, so it could not see a close. uvicorn's shutdown sends
every socket a close and then waits for every handler to return -- and
this one never did. Opening `/` once was enough: the server outlived
`kill`, held its port, and a later run hit "Address already in use".

These start the real server in a subprocess, because the thing under test
is the process exiting, which no in-process client can see.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time

import pytest

pytest.importorskip("uvicorn")
ws_client = pytest.importorskip("websockets.sync.client")

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")

EXIT_WITHIN = 10.0  # seconds; a healthy stop takes well under one


@pytest.fixture
def ui_server(tmp_path):
    # No ~/.atoo.config; and the atoo under test, not whatever
    # happens to be installed -- the subprocess runs from tmp_path, so
    # without this an editable install of another checkout answers.
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "HOME": str(tmp_path),
           "PYTHONPATH": os.pathsep.join(filter(None, [repo, os.environ.get("PYTHONPATH")]))}
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; from atoo.cli import main; sys.exit(main())",
         "ui", "--port", "0"],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        line = proc.stdout.readline()
        match = re.search(r"http://([\d.]+):(\d+)", line)
        assert match, f"no URL banner from `atoo ui`: {line!r}"
        yield proc, f"ws://{match.group(1)}:{match.group(2)}/ws/watch"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_ui_exits_on_signal_with_a_watch_socket_open(ui_server, sig):
    proc, url = ui_server
    with ws_client.connect(url, open_timeout=10) as ws:
        # The handler has sent its first status, so it is past `accept`
        # and waiting on the queue -- the state that used to hang.
        assert '"type": "status"' in ws.recv(timeout=10)
        started = time.monotonic()
        proc.send_signal(sig)
        try:
            proc.wait(timeout=EXIT_WITHIN)
        except subprocess.TimeoutExpired:
            pytest.fail(f"`atoo ui` still running {EXIT_WITHIN}s after {sig.name} "
                        "with a Watch socket open")
    assert time.monotonic() - started < EXIT_WITHIN
