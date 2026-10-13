"""`atoo ... | head` exits quietly when the reader goes away.

The full `--help` is far larger than a pipe's buffer, so a reader that
closes after the first line leaves the writer with a broken pipe. Before
the guard in `cli.main`, that ended in a BrokenPipeError traceback.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from atoo import cli

REPO = Path(__file__).resolve().parent.parent

RUN_MAIN = "import sys; from atoo.cli import main; sys.exit(main())"


def _run_into_a_closed_pipe(*args: str) -> tuple[int, str]:
    """Run a command whose stdout is a pipe with no reader, as `| true`
    or a `| head` that has already gone gives it. A reader that takes the
    first line and then closes is a race (the writer can finish into the
    pipe's buffer first), so the read end is closed before the command
    starts: the first write breaks, every time."""
    env = dict(os.environ, PYTHONPATH=str(REPO))
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", RUN_MAIN, *args],
            stdout=write_end,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(REPO),
            timeout=60,
        )
    finally:
        os.close(write_end)
    return proc.returncode, proc.stderr.decode("utf-8", "replace")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipe semantics")
@pytest.mark.parametrize("args", [("--help",), ("build", "--help")],
                         ids=["full-help", "argparse-help"])
def test_help_into_a_closed_pipe_leaves_no_traceback(args):
    # `build --help` leaves through argparse's SystemExit, not a return.
    status, stderr = _run_into_a_closed_pipe(*args)
    assert "Traceback" not in stderr
    assert "BrokenPipeError" not in stderr
    assert stderr == ""
    # The Python docs' recipe: exit 1, not 0 -- the output was cut short.
    # argparse's own help is the exception: it ignores a failed write to
    # stdout and exits 0 itself, which is quiet too.
    if args == ("--help",):
        assert status == 1
    else:
        assert status in (0, 1)


def test_a_broken_pipe_not_on_stdout_keeps_its_traceback(monkeypatch):
    # Under capsys stdout is not a pipe, so a BrokenPipeError from
    # somewhere else (a socket, say) must not be swallowed.
    def boom(argv=None):
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(cli, "_main", boom)
    with pytest.raises(BrokenPipeError):
        cli.main(["--help"])


def test_other_errors_are_not_caught(monkeypatch):
    def boom(argv=None):
        raise ValueError("a real error")

    monkeypatch.setattr(cli, "_main", boom)
    with pytest.raises(ValueError):
        cli.main(["--help"])
