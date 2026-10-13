"""A live console read that says nothing while it works is
indistinguishable from a hung one, and a tool that looks hung gets killed.

These tests pin the three things that made the difference: that something
is printed at all, that it is printed in a shape a redirected log can
hold, and that every write is flushed rather than left in a buffer the
way the 2026-09-22 `watch` run's output was.
"""

import io

import pytest

from atoo.progress import PIPE_LINES, ReadProgress, _default_every


class RecordingStream(io.StringIO):
    """A stream that remembers how many times it was flushed, and can
    claim to be a terminal or not."""

    def __init__(self, isatty=False):
        super().__init__()
        self._isatty = isatty
        self.flushes = 0
        self.writes = []

    def isatty(self):
        return self._isatty

    def write(self, text):
        self.writes.append(text)
        return super().write(text)

    def flush(self):
        self.flushes += 1
        return super().flush()


def run(progress, addresses, unanswered=()):
    for address in addresses:
        progress.start_address(address)
        progress.finish_address(answered=address not in unanswered)


# -- a pipe: plain appended lines, never a carriage return -----------------


def test_a_redirected_log_gets_plain_lines_not_carriage_returns():
    stream = RecordingStream(isatty=False)
    progress = ReadProgress(100, stream=stream, every=25)
    run(progress, [f"/ch/{n}/fdr" for n in range(1, 101)])
    text = stream.getvalue()
    assert "\r" not in text, "a log full of carriage returns is not a log"
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 4
    assert lines[0].startswith("  read 25/100 (25%)")
    assert lines[-1].startswith("  read 100/100 (100%)")


def test_a_pipe_line_names_the_address_in_flight():
    # Not the last address finished: a stall has to be attributable, and
    # the address that is timing out is the one still in flight.
    stream = RecordingStream(isatty=False)
    progress = ReadProgress(4, stream=stream, every=2)
    run(progress, ["/ch/1/fdr", "/ch/2/fdr", "/ch/3/fdr", "/ch/4/fdr"])
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert lines[0].endswith("/ch/2/fdr")
    assert lines[1].endswith("/ch/4/fdr")


def test_every_write_is_flushed_explicitly():
    # Python block-buffers stdout when it is not a terminal. On
    # 2026-09-22 that turned a correct `watch` run into a zero-byte file
    # and it was killed. PYTHONUNBUFFERED is not a substitute -- this
    # module does not get to assume the caller's environment.
    stream = RecordingStream(isatty=False)
    progress = ReadProgress(10, stream=stream, every=2)
    run(progress, [f"/ch/{n}/fdr" for n in range(1, 11)])
    assert stream.flushes == len(stream.writes) > 0


def test_a_stream_with_no_isatty_is_treated_as_a_pipe():
    class Bare:
        def __init__(self):
            self.text = ""

        def write(self, t):
            self.text += t

        def flush(self):
            pass

    stream = Bare()
    progress = ReadProgress(4, stream=stream, every=2)
    run(progress, ["/ch/1/fdr", "/ch/2/fdr", "/ch/3/fdr", "/ch/4/fdr"])
    assert "\r" not in stream.text
    assert "read 2/4" in stream.text


def test_default_every_never_divides_by_zero():
    # `total // PIPE_LINES` is 0 for any read shorter than PIPE_LINES,
    # and `done % 0` is a crash in the middle of a console session.
    assert _default_every(1) == 1
    assert _default_every(0) == 1
    assert _default_every(6032) == 6032 // PIPE_LINES

    stream = RecordingStream(isatty=False)
    progress = ReadProgress(3, stream=stream)
    run(progress, ["/ch/1/fdr", "/ch/2/fdr", "/ch/3/fdr"])
    assert "read 3/3" in stream.getvalue()


# -- a terminal: one line, rewritten in place ------------------------------


def test_a_terminal_gets_one_line_rewritten_in_place():
    stream = RecordingStream(isatty=True)
    progress = ReadProgress(3, stream=stream, every=1)
    run(progress, ["/ch/1/fdr", "/ch/2/fdr", "/ch/3/fdr"])
    text = stream.getvalue()
    assert text.count("\r") >= 1
    assert "\n" not in text, "an in-place line must not scroll the terminal"


def test_the_first_address_is_drawn_immediately_on_a_terminal():
    # Throttling must not swallow the first draw: a read that stalls on
    # address 1 would then print nothing at all, which is the whole
    # defect this exists to fix.
    stream = RecordingStream(isatty=True)
    progress = ReadProgress(6032, stream=stream)
    progress.start_address("/ch/1/name")
    assert "/ch/1/name" in stream.getvalue()


def test_a_shorter_address_does_not_leave_the_longer_one_behind_it():
    stream = RecordingStream(isatty=True)
    progress = ReadProgress(2, stream=stream)
    progress.start_address("/ch/1/send/MX8/mode")
    progress.finish_address(answered=True)
    progress._last_draw = 0.0  # defeat the redraw throttle for the test
    progress.start_address("/ch/1/fdr")
    last = stream.writes[-1]
    assert last.endswith(" "), "the line is padded to erase the previous one"


def test_finish_clears_the_terminal_line_before_the_summary():
    stream = RecordingStream(isatty=True)
    progress = ReadProgress(1, stream=stream)
    run(progress, ["/ch/1/fdr"])
    progress.finish()
    text = stream.getvalue()
    assert text.rstrip("\n").endswith("every address answered.")
    assert "\r" in text


# -- the end-of-read report ------------------------------------------------


def test_the_summary_reports_how_many_addresses_went_unanswered():
    stream = RecordingStream(isatty=False)
    progress = ReadProgress(10, stream=stream, every=100, timeout=1.0, retries=2)
    run(progress, [f"/ch/{n}/fdr" for n in range(1, 11)],
        unanswered={"/ch/3/fdr", "/ch/7/fdr"})
    summary = progress.finish()
    assert "10 of 10 addresses" in summary
    assert "2 address(es) went unanswered" in summary
    # 2 addresses x (2 retries + 1) attempts x 1.0s -- arithmetic on two
    # numbers we know, not a guess at the whole read.
    assert "about 6s of the time above" in summary
    assert "not defaults" in summary


def test_the_summary_says_so_when_every_address_answered():
    stream = RecordingStream(isatty=False)
    progress = ReadProgress(3, stream=stream, every=100)
    run(progress, ["/a", "/b", "/c"])
    assert "every address answered." in progress.finish()
    assert "unanswered" not in progress.summary()


def test_the_unanswered_cost_is_left_out_when_the_timeout_is_unknown():
    stream = RecordingStream(isatty=False)
    progress = ReadProgress(2, stream=stream, every=100, timeout=None)
    run(progress, ["/a", "/b"], unanswered={"/a"})
    summary = progress.summary()
    assert "1 address(es) went unanswered" in summary
    assert "of the time above" not in summary


# -- the denominator moves when a node dump omits a leaf -------------------


def test_the_total_can_be_restated_and_grown():
    progress = ReadProgress(10, stream=RecordingStream(), every=100)
    progress.set_total(300)
    assert progress.total == 300
    progress.add_total()
    assert progress.total == 301


def test_set_total_never_drops_below_what_is_already_done():
    stream = RecordingStream(isatty=False)
    progress = ReadProgress(10, stream=stream, every=100)
    run(progress, ["/a", "/b", "/c"])
    progress.set_total(1)
    assert progress.total == 3, "a percentage over 100 is worse than a moved total"


# -- progress must never be the reason a read fails ------------------------


def test_a_broken_stream_costs_the_display_not_the_run():
    class Broken:
        def write(self, text):
            raise OSError("stream closed")

        def flush(self):
            raise OSError("stream closed")

        def isatty(self):
            return False

    progress = ReadProgress(2, stream=Broken(), every=1)
    run(progress, ["/a", "/b"])
    progress.finish()  # must not raise
    assert progress.done == 2


@pytest.mark.parametrize("isatty", [True, False])
def test_the_counts_are_the_same_either_way(isatty):
    progress = ReadProgress(4, stream=RecordingStream(isatty=isatty), every=1)
    run(progress, ["/a", "/b", "/c", "/d"], unanswered={"/b"})
    assert (progress.done, progress.answered, progress.unanswered) == (4, 3, 1)


# -- the silent addresses are named ---------------------------


def test_the_summary_names_the_addresses_that_went_unanswered():
    stream = RecordingStream(isatty=False)
    progress = ReadProgress(10, stream=stream, every=100, timeout=1.0)
    run(progress, [f"/ch/{n}/fdr" for n in range(1, 11)],
        unanswered={"/ch/3/fdr", "/ch/7/fdr"})
    summary = progress.finish()
    # In the order they were asked for, and only the silent ones.
    assert "  unanswered: /ch/3/fdr, /ch/7/fdr" in summary
    assert "/ch/4/fdr" not in summary
    assert "and" not in summary.splitlines()[-1]


def test_a_long_list_of_silent_addresses_is_capped_and_says_how_many_more():
    from atoo.progress import NAMED_UNANSWERED
    addresses = [f"/bus/{n}/send/1/mode" for n in range(1, 31)]
    progress = ReadProgress(30, stream=RecordingStream(), every=100)
    run(progress, addresses, unanswered=set(addresses))
    last = progress.summary().splitlines()[-1]
    named = addresses[:NAMED_UNANSWERED]
    assert last.startswith("  unanswered: " + ", ".join(named) + ",")
    assert addresses[NAMED_UNANSWERED] not in last
    assert f"and {30 - NAMED_UNANSWERED} more" in last
    assert "--raw-log" in last


def test_a_silent_node_request_is_named_as_a_node():
    progress = ReadProgress(2, stream=RecordingStream(), every=100)
    run(progress, ["/ch/1 (node)", "/ch/2 (node)"], unanswered={"/ch/2 (node)"})
    assert "  unanswered: /ch/2 (node)" in progress.summary()


def test_no_unanswered_line_when_every_address_answered():
    progress = ReadProgress(2, stream=RecordingStream(), every=100)
    run(progress, ["/a", "/b"])
    assert "unanswered:" not in progress.summary()
