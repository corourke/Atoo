"""Say what a long, silent console read is doing while it does it.

A live `audit --console` asks a WING Compact for 6,197
addresses -- one at a time, then; 325 requests by node dump, pipelined
eight in flight, today -- and, until this
module existed, printed **nothing at all** until it was finished. Run at the desk
mid-session, it could not be told from a hang.

That is the second time this exact shape has cost a run. On 2026-09-22 a
correct `watch` produced a zero-byte log for minutes -- Python
block-buffers stdout when it is not a terminal -- and it was killed.
The desk-run scripts' shared setup sets `PYTHONUNBUFFERED=1` now, and it
did not help here, because there was nothing to flush. **A tool that
cannot be told apart from a hung one gets killed**, and the run is lost
along with the desk time it cost.

So two rules govern everything here:

- **Flush every write, explicitly.** Not `PYTHONUNBUFFERED`, not the
  caller's environment, not a terminal's line buffering -- this module
  calls `flush()` itself, every time, because the one case that matters
  is the redirected one.
- **Name the address in flight, not the last one finished.** A stall has
  to be attributable. `read 1200/6143 (19%) /ch/13/send/4/lvl` sitting
  still for three seconds says which address is timing out; the same
  line showing the previously completed address does not.

Two shapes, chosen by `stream.isatty()`:

- **A terminal** gets one line rewritten in place with `\\r`, throttled to
  `TTY_MIN_INTERVAL` so a fast read does not spend its time on escape
  codes.
- **A pipe** gets a plain appended line every N addresses, because every
  desk-run script redirects to a log and a log full of
  carriage returns is not a log. N is derived from the total
  (`_default_every`) so a read of any size produces about twenty lines.

The same two rules, and the same two shapes, govern the other long silent
wait in this tool: **a model call** (`ModelCallProgress`, below). A build
on a hosted model spends minutes thinking before it writes a character;
on a local one, the better part of an hour. Until 2026-09-25 that wait
printed one "sending" line when stderr was not a terminal -- which is
every build the Setup UI runs -- and then nothing until the call ended
(progress while a build is running was asked for). A model call has a
third consumer a console read does not: the Setup UI's Build step 04,
which wants the numbers, not a line of text to scrape. So a model call
also reports to a *listener* -- a callable the caller registers for its
own thread with `model_progress_listener()` -- and the web UI's build
runner is the one that does.

**Stop, and what the model is writing** (progress updates from the
build step, or progressive output, and a way to stop it if things are
going haywire). Two more things live here for that:

- `StopSignal`, registered for a thread with `stop_scope()` the same way
  a listener is. `StopSignal.stop()` -- the Setup UI's Stop button --
  does not wait for the stream loop to notice: it runs every closer the
  provider registered, which shuts the call's socket from the stopping
  thread. That is what makes Stop work in the silent thinking stretch,
  when the loop is blocked in a read and there is nothing to notice with.
  The provider then raises `BuildStopped`, a `BaseException` like
  `KeyboardInterrupt`, so that no `except Exception` on the way up (the
  critic's, the watchlist draft's) can mistake a stop for a failed pass
  and carry on to write files.
- A bounded tail of the text the model has written (`TAIL_CHARS`), the
  latest line of any thinking it streams (a summary, where the provider
  asks for one), and an outline of the partial plan JSON read tolerantly
  as it arrives (`stream_outline.StreamOutline`). The snapshot carries all
  three, and stays small, because `/api/build/status` is polled.
"""

from __future__ import annotations

import _socket
import contextlib
import contextvars
import shutil
import socket
import sys
import threading
import time
from typing import Callable

from atoo.stream_outline import StreamOutline

# How often, at most, the in-place terminal line is redrawn. A loopback
# read gets through 13,000 addresses a second (measured), and
# redrawing that often is pure cost.
TTY_MIN_INTERVAL = 0.1

# About this many progress lines over the whole read, on a pipe.
PIPE_LINES = 20

# How many silent addresses the end-of-read summary names. Enough to
# identify a handful outright (eight on a full-size WING) or
# to show the family a few hundred belong to (the 320 were all
# `/bus|/main/*/send/*/mode|pon`), without printing hundreds of lines.
NAMED_UNANSWERED = 10


def _default_every(total: int) -> int:
    """How many addresses between printed lines on a pipe. Never zero --
    `total // PIPE_LINES` is 0 for any read shorter than 20 addresses,
    and a modulus by zero is a crash in the middle of a console session."""
    return max(1, total // PIPE_LINES)


class ReadProgress:
    """Progress for a request-per-address console read.

    Call `start_address(address)` before each request and
    `finish_address(answered=...)` after it, then `finish()` once. The
    counts it keeps are the report at the end: how many addresses were
    asked for, how many answered, and how many the console never replied
    to at all -- naming the first `NAMED_UNANSWERED` of those.

    `unanswered` is not a diagnostic detail. On an initialized desk a
    great many of the 2,560 send leaves have never been touched, and
    whether those answer decides whether the read takes forty seconds or
    ten minutes -- an unanswered address costs `(retries + 1) x timeout`,
    which is 3.0s at the defaults. The end-of-read line states the
    number for the same reason `audit.render_coverage` states which
    sockets were read: a report says what it covered.
    """

    def __init__(self, total: int, *, stream=None, label: str = "read",
                 every: int | None = None, isatty: bool | None = None,
                 timeout: float | None = None, retries: int = 2,
                 noun: str = "addresses", answers: bool = True, window: int = 1):
        self.total = total
        # How many requests the read keeps in flight. Above 1,
        # unanswered requests wait side by side, so their count times the
        # timeout is no longer what they cost; see `summary`.
        self.window = max(1, int(window))
        self.stream = sys.stderr if stream is None else stream
        self.label = label
        # What is being counted, for the summary line ("settings" for a
        # write phase). `answers` False leaves the answered/unanswered part
        # out of the summary: a write phase's verdicts are the run's own
        # report (match, mismatch, unreadable), not this line's.
        self.noun = noun
        self.answers = answers
        self.every = _default_every(total) if every is None else max(1, every)
        self._every_derived = every is None
        # A stream with no isatty() at all (a StringIO in a test, some
        # wrappers) is treated as a pipe, which is the safe shape: a
        # readable log rather than carriage returns nobody can read.
        if isatty is None:
            try:
                isatty = bool(self.stream.isatty())
            except Exception:
                isatty = False
        self.isatty = isatty
        self.timeout = timeout
        self.retries = retries

        self.done = 0
        self.answered = 0
        self.unanswered = 0
        # Set by a write phase before `finish`: how many of the settings it
        # went through it actually wrote (see `summary`).
        self.written: int | None = None
        self.unanswered_addresses: list[str] = []
        # Family -> how many of it the read did not ask for,
        # after enough of it went unanswered (`audit.UnansweredFamilies`).
        self.skipped_families: dict[str, int] = {}
        self.current: str | None = None
        self.started = time.monotonic()
        self._last_draw = 0.0
        self._line_width = 0

    # -- the calls the read loop makes -------------------------------------

    def set_total(self, total: int) -> None:
        """Restate the total once the read knows it exactly.

        A node-dump read (`read_console_state(bulk=True)`) cannot know its
        total up front: a leaf the dump turns out not to carry is read on
        its own afterwards, and that is one more request than planned.
        Better to move the denominator than to print 103%.

        A pipe's spacing is re-derived from the new total unless the caller
        fixed it: a phase started before its request count is known (the
        reset's read is told it once the leaves are grouped into nodes)
        would otherwise print two lines for a read of two thousand."""
        self.total = max(total, self.done)
        if self._every_derived:
            self.every = _default_every(self.total)

    def add_total(self, extra: int = 1) -> None:
        self.total += extra

    def start_address(self, address: str) -> None:
        self.current = address
        if self.isatty:
            now = time.monotonic()
            # Always draw the first address: otherwise a read that stalls
            # on address 1 prints nothing, which is the whole defect.
            if self.done == 0 or now - self._last_draw >= TTY_MIN_INTERVAL:
                self._last_draw = now
                self._draw_tty()

    def finish_address(self, *, answered: bool) -> None:
        self.done += 1
        if answered:
            self.answered += 1
        else:
            self.unanswered += 1
            # The address in flight is the one that went silent. Named at
            # the end, because a count alone left the eight
            # unidentifiable: a `--dump-state` capture holds only what
            # answered, and `--raw-log` has to be asked for beforehand.
            if self.current is not None:
                self.unanswered_addresses.append(self.current)
        if not self.isatty and self.done % self.every == 0:
            self._write(self._line() + "\n")

    def skip_address(self, address: str, family: str) -> None:
        """An address the read decided not to ask for, because its family
        has already gone unanswered with the desk still answering. It counts toward `done` so the bar still reaches its
        total, and is named by family in the summary -- never as
        answered, and never as a default."""
        self.done += 1
        self.current = address
        self.skipped_families[family] = self.skipped_families.get(family, 0) + 1
        if not self.isatty and self.done % self.every == 0:
            self._write(self._line() + "\n")

    # -- rendering ---------------------------------------------------------

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def _line(self) -> str:
        pct = (100 * self.done // self.total) if self.total else 100
        return (f"  {self.label} {self.done}/{self.total} ({pct}%) "
                f"{self.elapsed:.0f}s -- {self.current or ''}")

    def _draw_tty(self) -> None:
        line = self._line()
        # Pad to the previous line's width so a shorter address does not
        # leave the tail of the longer one behind it on screen.
        pad = max(0, self._line_width - len(line))
        self._line_width = len(line)
        self._write("\r" + line + " " * pad)

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            # Explicitly, every time. See this module's docstring: the
            # case that matters is the one where the stream is a file.
            self.stream.flush()
        except Exception:
            # Progress reporting must never be the reason a console read
            # fails. A closed or broken stream costs the display, not
            # the run.
            pass

    def finish(self) -> str:
        """Clear the in-place line (if any), print the summary, return it."""
        if self.isatty and self._line_width:
            self._write("\r" + " " * self._line_width + "\r")
        summary = self.summary()
        self._write(summary + "\n")
        return summary

    def summary(self) -> str:
        parts = [f"  {self.label}: {self.done} of {self.total} {self.noun} "
                 f"in {self.elapsed:.1f}s"]
        if not self.answers:
            # A write phase that checks more settings than it writes says
            # how many it wrote: the count of settings alone reads as every
            # one of them having been sent.
            if self.written is not None:
                parts[0] += f" -- {self.written} written and read back"
            return parts[0]
        if self.unanswered:
            cost = ""
            if self.timeout:
                # Not an estimate of the whole read -- just this term of
                # it, and it is arithmetic on two numbers we know: an
                # address nobody answers is sent (retries + 1) times and
                # each send waits the full socket timeout.
                each = (self.retries + 1) * self.timeout
                if self.window > 1:
                    # Up to `window` of them waited at once,
                    # so a sum would overstate the time several times
                    # over (18 unanswered "about 54s" after a 3.4s read).
                    # What is known exactly is what each one cost.
                    cost = (f", each waiting about {each:.0f}s, up to {self.window} "
                            f"at a time")
                else:
                    seconds = self.unanswered * each
                    cost = f", about {seconds:.0f}s of the time above"
            parts.append(f"  {self.unanswered} address(es) went unanswered"
                         f"{cost}. Those values are unknown -- not defaults.")
            if self.unanswered_addresses:
                named = self.unanswered_addresses[:NAMED_UNANSWERED]
                more = len(self.unanswered_addresses) - len(named)
                tail = (f", and {more} more (--raw-log FILE records every one)"
                        if more else "")
                parts.append("  unanswered: " + ", ".join(named) + tail)
        else:
            parts.append("  every address answered.")
        for family, count in self.skipped_families.items():
            parts.append(
                f"  INFO: stopped asking for {family} once {self._cutoff()} of "
                f"them had gone unanswered while the desk kept answering; the "
                f"other {count} were not asked. Those values are unknown -- "
                f"not defaults.")
        return "\n".join(parts)

    @staticmethod
    def _cutoff() -> int:
        # Imported here: `audit` imports half the project, and this module
        # is imported by `build`, which reads no console.
        from atoo.audit import UNANSWERED_FAMILY_CUTOFF
        return UNANSWERED_FAMILY_CUTOFF


class _NoProgress:
    """A phase nobody is shown: every call is a no-op. What `NO_PHASES`
    hands out, so a run loop calls the same methods either way."""

    def set_total(self, total: int) -> None:
        pass

    def add_total(self, extra: int = 1) -> None:
        pass

    def start_address(self, address: str) -> None:
        pass

    def finish_address(self, *, answered: bool) -> None:
        pass

    def skip_address(self, address: str, family: str) -> None:
        pass

    def finish(self) -> str:
        return ""


class Phases:
    """One `ReadProgress` per phase of a run that reads and writes a desk.

    A full `apply` is several long silent stretches in a row -- the reset's
    read, the reset's writes, the plan's writes, the re-read of what did
    not read back right -- and at the desk on 2026-10-12 the first of them
    alone took 39.6s with nothing on screen, so the run was taken for a
    hang. The rules apply unchanged: stderr, flushed, the address
    in flight named. What this adds is the phase's NAME as the line's
    label ("reading the desk for the reset 812/2448 (33%) 13s -- /ch/12"),
    so whoever is watching can tell which step is the slow one, and a
    summary line as each phase ends.

    `start(label, total)` returns the phase's progress; the caller calls
    `finish()` on it when the phase is over. `timeout`/`retries` are
    passed through for a read phase's unanswered-cost arithmetic.
    """

    def __init__(self, *, stream=None, timeout: float | None = None, retries: int = 2,
                 isatty: bool | None = None, window: int = 1):
        self.stream = stream
        self.timeout = timeout
        self.retries = retries
        self.isatty = isatty
        self.window = window

    def start(self, label: str, total: int, *, writes: bool = False) -> "ReadProgress":
        """A phase of `total` steps. `writes` True: a step is one setting
        written and read back, and the summary counts settings rather than
        answers."""
        return ReadProgress(
            total, stream=self.stream, label=label, isatty=self.isatty,
            timeout=None if writes else self.timeout, retries=self.retries,
            noun="settings" if writes else "addresses", answers=not writes,
            window=self.window)


class _NoPhases:
    def start(self, label: str, total: int, *, writes: bool = False) -> _NoProgress:
        return _NoProgress()


#: The silent `Phases`: what a run uses when nobody asked to be told
#: (`--no-progress`, a test, a library caller).
NO_PHASES = _NoPhases()


# ---------------------------------------------------------------------------
# Model calls
# ---------------------------------------------------------------------------

# How often the background ticker wakes. It is the ONLY thing that draws,
# prints or notifies -- the stream loop just counts -- so this is also the
# fastest any consumer hears about a call: a terminal redraw, a listener
# update. Never one write per token, whatever the model's token rate.
MODEL_TICK = 0.5


def _pipe_interval(elapsed: float) -> float:
    """Seconds between plain progress lines on a pipe, by how long the call
    has run: every 10s for the first minute (the stretch where "is it even
    running?" gets asked), every 30s to ten minutes, then every minute. A
    five-minute hosted build writes about 14 lines; a forty-minute local
    one about 54 -- inside the 200 lines the Setup UI keeps of a build's
    log, and readable in a saved one. A change of stage (waiting ->
    thinking -> writing) also gets a line, since that is news whatever the
    clock says."""
    if elapsed < 60:
        return 10.0
    if elapsed < 600:
        return 30.0
    return 60.0


def _fmt_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m{secs:02d}s"


# How much of the model's text the snapshot carries: enough to read the
# last few channels being written, small enough to poll every second.
TAIL_CHARS = 2048
# The latest thinking line shown, at most. A summary paragraph is a few
# sentences; the page shows one line of it.
THINKING_LINE_CHARS = 240

# Build-log bounds: the
# notes are for a human reviewing a batch of builds later, not a live
# transcript, so they are capped hard rather than left to grow with a
# call's length. ~200 notes at ~400 chars is on the order of a plan's own
# existing meta fields, not a new file's worth of bytes.
BUILD_LOG_MAX_NOTES = 200
BUILD_LOG_NOTE_CHARS = 400


class BuildStopped(BaseException):
    """The person stopped the run: the Setup UI's Stop, through a
    `StopSignal`. A `BaseException`, like `KeyboardInterrupt`, on purpose:
    `generate.critique_plan` and the watchlist draft each catch `Exception`
    so that a failed pass never stops a build -- and a stop that one of
    them swallowed would let the build carry on and write plan.json, the
    one thing a stop promises not to do."""


def _shutdown_socket(sock) -> None:
    """Shut `sock` for reading and writing from ANY thread, which wakes a
    read blocked on it in another. Called through the plain socket's
    method so an `ssl.SSLSocket` is shut at the TCP level rather than
    through its TLS close, which would need the reading thread's lock."""
    if sock is None:
        return
    try:
        _socket.socket.shutdown(sock, socket.SHUT_RDWR)
    except (OSError, ValueError, TypeError):
        pass


class StopSignal:
    """One run's Stop button.

    `stop()` sets the flag and runs every closer registered with
    `closing()` -- each shuts one model call's connection -- in the calling
    thread, at once. A closer registered after `stop()` runs as it is
    registered. `check()` raises `BuildStopped` once stopped; the provider
    calls it before it connects, after it connects, per streamed line, and
    after the stream ends, so a call that was stopped never returns text.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._closers: dict[int, Callable[[], None]] = {}
        self._next = 0
        self.requested_at: float | None = None

    @property
    def stopped(self) -> bool:
        return self._event.is_set()

    def stop(self) -> bool:
        """Stop. False when it had already been stopped."""
        with self._lock:
            if self._event.is_set():
                return False
            self.requested_at = time.time()
            self._event.set()
            closers = list(self._closers.values())
        for closer in closers:
            try:
                closer()
            except Exception:
                pass
        return True

    def check(self) -> None:
        if self._event.is_set():
            raise BuildStopped("stopped by you")

    def wait(self, timeout: float) -> bool:
        """Sleep up to `timeout`, waking at once on a stop. True if stopped."""
        return self._event.wait(timeout)

    @contextlib.contextmanager
    def closing(self, closer: Callable[[], None]):
        with self._lock:
            key = self._next
            self._next += 1
            self._closers[key] = closer
            already = self._event.is_set()
        if already:
            try:
                closer()
            except Exception:
                pass
        try:
            yield
        finally:
            with self._lock:
                self._closers.pop(key, None)


_STOP: contextvars.ContextVar = contextvars.ContextVar(
    "atoo_stop_signal", default=None)


@contextlib.contextmanager
def stop_scope(signal: StopSignal):
    """Register `signal` for every model call made in this context (in
    practice, the build's thread), as `model_progress_listener` does."""
    token = _STOP.set(signal)
    try:
        yield signal
    finally:
        _STOP.reset(token)


def current_stop_signal() -> StopSignal | None:
    return _STOP.get()


def check_stopped() -> None:
    """Raise `BuildStopped` if this thread's run has been stopped. For the
    places between model calls that are about to write something."""
    signal = _STOP.get()
    if signal is not None:
        signal.check()


def fmt_duration(seconds: float) -> str:
    """`2m 14s`, `9s`: a stop sentence's time, as a person says it."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m {secs:02d}s"


def stopped_message(elapsed_s: float, written: list[str], *, how: str = "") -> str:
    """The one sentence a stopped build ends with, in the terminal and on
    the page alike. `written` is what DID land before the stop (file
    names); the caller knows it -- the CLI by recording each write, the
    web UI by comparing the bundle before and after -- so the sentence is
    never a promise, only a report."""
    head = f"Stopped by you{how} after {fmt_duration(elapsed_s)}."
    if not written:
        return head + " Nothing was written to the show; plan.json is unchanged."
    names = " and ".join(written)
    verb = "was" if len(written) == 1 else "were"
    return (head + f" {names} {verb} already written before the stop; "
            "nothing else was changed.")


def _last_line(text: str, limit: int = THINKING_LINE_CHARS) -> str:
    """The last line of `text` worth showing: the last non-empty one,
    markdown emphasis dropped (a summary's headings arrive as `**...**`)."""
    for line in reversed(text.splitlines()):
        line = line.strip().strip("*#").strip()
        if line:
            return line if len(line) <= limit else line[:limit - 1] + "\u2026"
    return ""


_LISTENER: contextvars.ContextVar = contextvars.ContextVar(
    "atoo_model_progress_listener", default=None)


@contextlib.contextmanager
def model_progress_listener(listener: Callable[[dict], None]):
    """Register `listener` for every model call made in this context --
    in practice, this thread -- until the block exits.

    A context variable, not a global: the web UI's server runs a build in
    one worker thread while other threads (a watch loop, uvicorn) carry on,
    and only the build's own calls are the build's progress. A
    `ModelCallProgress` reads the listener once, when it is created in the
    calling thread; its ticker thread calls that same function after."""
    token = _LISTENER.set(listener)
    try:
        yield
    finally:
        _LISTENER.reset(token)


def current_model_listener() -> Callable[[dict], None] | None:
    return _LISTENER.get()


def _stopping() -> bool:
    """Is the exception now propagating a stop (Stop, or Ctrl-C)? A
    provider calls `finish` from `finally`, where this can be asked."""
    exc = sys.exc_info()[0]
    return exc is not None and issubclass(exc, (BuildStopped, KeyboardInterrupt))


def _resolve_stream(stream):
    """The stream the CALLING thread's writes would reach.

    The ticker writes from its own thread. The web UI routes a build's
    stderr by the writing thread (`webui._ThreadRoutedStream`), so a line
    the ticker wrote to `sys.stderr` directly would land in the server's
    console instead of the build's log. A stream that routes by thread
    offers `for_current_thread()`, answered here, in the thread that owns
    the call."""
    resolve = getattr(stream, "for_current_thread", None)
    if callable(resolve):
        try:
            return resolve()
        except Exception:
            return stream
    return stream


def input_total(usage: dict) -> int:
    """Every input token of a call: what the provider reports as input plus,
    for Claude, what was written to and read from the prompt cache --
    `usage.input_tokens` there counts only what follows the last cache
    breakpoint. For any other provider `input_tokens` is already the whole
    prompt and the two cache keys are absent."""
    return ((usage.get("input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0))


class ModelCallProgress:
    """Say what one model call is doing while it does it.

    The provider's stream loop calls `thinking_started()`, `add_thinking(n)`
    and `add_text(n)` as deltas arrive -- counting only, never writing --
    and `finish()` once, however the call ends. Everything visible is done
    by `tick()`, which a daemon thread calls every `MODEL_TICK` seconds.

    **Why a ticker and not the stream loop.** The loop only runs when bytes
    arrive, and the longest stretch of a hosted build is the one where none
    do: with thinking display omitted (the default on current Claude
    models) a thinking block streams with empty text, so minutes pass with
    nothing to count. A progress line driven by the loop froze exactly
    there -- the stretch that needs it most. The ticker keeps the elapsed
    time moving while the socket is silent.

    Three outputs, each optional:

    - **a terminal** (stderr is a tty): one line redrawn in place;
    - **a pipe**: a plain line on the `_pipe_interval` cadence, and on each
      change of stage;
    - **a listener** (`model_progress_listener`): a dict snapshot at the
      start, on every tick, and at the end -- the Setup UI's channel.

    `stage` is `waiting` (sent, nothing back yet), `thinking`, `writing`,
    then `done` or `failed`. Thinking tokens are known while the call runs
    only if the model streams its thinking text; otherwise the snapshot's
    `thinking_tokens` is None, and the real spend arrives with the usage
    the provider reports at the end (`finish(usage=...)`). Token counts
    mid-call are estimates from characters (`chars_per_token`, which the
    caller passes: `ai_provider.CHARS_PER_TOKEN`); `estimated` says so.
    """

    def __init__(self, label: str, model: str = "", *, enabled: bool = True,
                 stream=None, isatty: bool | None = None,
                 listener=..., stop=...,
                 chars_per_token: float = 3.4, streams: bool = True,
                 ticker: bool = True, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time, effort: str = "") -> None:
        self.label = label
        self.model = model
        # The effort the call was sent at, where the provider has one
        # (Claude's per-role effort); "" otherwise. Named in the progress
        # line and carried in the snapshot for the Setup page's chips.
        self.effort = effort
        inner = ", ".join(p for p in (label, f"effort {effort}" if effort else "") if p)
        self.who = f"{model} ({inner})" if model and inner else (model or inner)
        self.stream = _resolve_stream(sys.stderr if stream is None else stream)
        # A stream with no isatty() at all is treated as a pipe, as
        # ReadProgress does: a readable log, not carriage returns.
        if isatty is None:
            try:
                isatty = bool(self.stream.isatty())
            except Exception:
                isatty = False
        self.isatty = isatty
        self.enabled = enabled
        # `...` means "whoever registered for this thread"; None means no
        # listener, explicitly.
        self.listener = current_model_listener() if listener is ... else listener
        # The run's Stop (`stop_scope`), read the same way: once, here, in
        # the calling thread. Only `finish` consults it, to say "stopped".
        self.stop = current_stop_signal() if stop is ... else stop
        self.chars_per_token = chars_per_token
        self.streams = streams
        self._clock = clock
        self.started = clock()
        self.started_at = wall()

        self.stage = "waiting"
        self.thinking_chars = 0
        self.text_chars = 0
        self.thinking_seen = False
        self.usage: dict = {}
        # What the model has written, not just how much: the last
        # TAIL_CHARS of its text, the tail of any thinking it streams, and
        # the outline of the JSON it is writing. All three are bounded.
        self._tail = ""
        self._thinking_tail = ""
        self._outline = StreamOutline()
        # The build log:
        # every distinct thinking-SUMMARY line seen, with its elapsed
        # seconds, for a human reviewing a batch of builds later (or the
        # host's own reasoning text, where it streams that instead of a
        # summary -- `add_thinking`). Never fed back into a
        # prompt (see `atoo.patch` and `generate.py`'s prompt assembly, which
        # both exclude `meta.build_log`). `_notes_buf` holds a summary
        # line still arriving; a line completes on its own newline, the
        # same boundary Claude's summaries use between thoughts.
        self._notes: list[dict] = []
        self._notes_buf = ""

        self._lock = threading.Lock()
        self._line_width = 0
        self._last_pipe = self.started
        self._pipe_stage = self.stage
        self._finished = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        if enabled:
            # Printed at once, before any request goes out: the gap from
            # "sent" to the first byte (connection, TLS, the model deciding
            # to start) can itself be tens of seconds.
            suffix = "" if self.isatty else \
                " (a progress line every 10-60s -- stderr is not a terminal)"
            self._write(f"{self.who}: sending, waiting for the first reply...{suffix}\n")
        self._notify("start")
        if ticker and (enabled or self.listener is not None):
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name=f"progress-{label or model}")
            self._thread.start()

    # -- what the stream loop calls: counting only --------------------------

    def thinking_started(self) -> None:
        self.thinking_seen = True
        if self.stage == "waiting":
            self.stage = "thinking"

    def add_thinking(self, chars: int, text: str = "") -> None:
        """Raw reasoning, counted as thinking. Where a host streams its
        reasoning as text (an OpenAI-compatible `reasoning_content`,
        Ollama's `thinking`) that text is the only record of the model's
        thinking there is -- such hosts send no summary -- so its lines
        feed the build log too, under the same bounds as a
        summary's. Claude with display omitted sends no text here."""
        self.thinking_seen = True
        self.thinking_chars += chars
        if text:
            # Twice the line limit: enough to hold the last line whole.
            self._thinking_tail = (self._thinking_tail + text)[-2 * THINKING_LINE_CHARS:]
            self._feed_notes(text)
        if self.stage == "waiting":
            self.stage = "thinking"

    def set_usage(self, usage: dict) -> None:
        """The provider's own running token counts, mid-call. Anthropic's
        `message_delta` events carry a CUMULATIVE `usage.output_tokens`;
        where one arrives, the snapshot reports the real figure instead of
        the character estimate (`estimated` false) -- which also makes the
        count shown at the moment of a Stop a true one."""
        with self._lock:
            if not self._finished:
                self.usage = dict(usage)

    def add_thinking_summary(self, text: str) -> None:
        """A SUMMARY of the thinking (Claude's `display: "summarized"`):
        shown as the latest line, never counted -- a summary is a few
        sentences for minutes of reasoning, and counting its characters
        as thinking tokens would understate the spend a hundredfold. The
        real count arrives with the usage at the end, as with none."""
        self.thinking_seen = True
        if text:
            self._thinking_tail = (self._thinking_tail + text)[-2 * THINKING_LINE_CHARS:]
            self._feed_notes(text)
        if self.stage == "waiting":
            self.stage = "thinking"

    def _feed_notes(self, text: str) -> None:
        """Split streamed summary text on newlines and record each
        completed line as a build-log note. Bounded to
        `BUILD_LOG_MAX_NOTES` entries of at most `BUILD_LOG_NOTE_CHARS`
        each -- see `build_log_notes()`, which flushes whatever is still
        buffered without a trailing newline."""
        self._notes_buf += text
        while "\n" in self._notes_buf:
            line, self._notes_buf = self._notes_buf.split("\n", 1)
            self._record_note(line)

    def _record_note(self, line: str) -> None:
        line = line.strip().strip("*#").strip()
        if not line or len(self._notes) >= BUILD_LOG_MAX_NOTES:
            return
        if len(line) > BUILD_LOG_NOTE_CHARS:
            line = line[:BUILD_LOG_NOTE_CHARS - 1] + "…"
        self._notes.append({"t": round(self.elapsed, 1), "text": line})

    def build_log_notes(self) -> list[dict]:
        """Every distinct thinking-summary line seen, `{"t", "text"}`,
        flushing anything still buffered without a trailing newline.
        Call once, after `finish()` -- for the build log,
        never sent to a model."""
        if self._notes_buf.strip():
            self._record_note(self._notes_buf)
            self._notes_buf = ""
        return list(self._notes)

    def usage_summary(self, *, model: str | None = None, effort: str | None = None,
                      cost: float | None = None) -> dict:
        """The final usage for the build log, alongside the notes: input
        and output tokens, the model and effort this call ran at, and its
        cost where the caller can price it. `reasoning_tokens_as_reported`
        is the provider's OWN separate count of reasoning tokens, when it
        reports one (e.g. an OpenAI-compatible `completion_tokens_details.
        reasoning_tokens`) -- None where it doesn't, which is not the same
        as zero: Claude's thinking is billed inside `output_tokens` with
        no separate count, so this is honestly unknown rather than a
        computed estimate presented as fact.

        `thinking` is the thinking count to compare builds by, and
        `thinking_source` says where it came from:
        "reported" is the provider's own count, as above; "estimated" is
        the output total less the text received, at the chars-per-token
        ratio -- the same subtraction as the usage line's "~N of it
        thinking" and the live page's thinking figure (`snapshot()`).
        Both are None when neither is known, e.g. a call that ended
        without reporting usage while its thinking was not streamed."""
        usage = self.usage or {}
        reported = usage.get("reasoning_tokens")
        if reported is not None:
            thinking, source = reported, "reported"
        else:
            thinking = self.snapshot()["thinking_tokens"]
            source = "estimated" if thinking is not None else None
        return {
            # Every input token: Anthropic's `input_tokens` is only what
            # fell after the last cache breakpoint (`input_total`).
            "input": input_total(usage) if usage.get("input_tokens") is not None else None,
            # What the prompt cache did (Claude); None where
            # the provider reports no cache counts.
            "cache_write": usage.get("cache_creation_input_tokens"),
            "cache_read": usage.get("cache_read_input_tokens"),
            "output": usage.get("output_tokens"),
            "reasoning_tokens_as_reported": reported,
            "thinking": thinking,
            "thinking_source": source,
            "model": model if model is not None else (self.model or None),
            "effort": effort if effort is not None else (self.effort or None),
            "cost": cost,
        }

    def build_log_entry(self, *, model: str | None = None, effort: str | None = None,
                        cost: float | None = None) -> dict:
        """`{"notes": [...], "usage": {...}}` -- the whole of what one
        call contributes to `plan["meta"]["build_log"][role]`. Call once,
        after `finish()`."""
        return {
            "notes": self.build_log_notes(),
            "usage": self.usage_summary(model=model, effort=effort, cost=cost),
        }

    def add_text(self, chars: int, text: str = "") -> None:
        """Count `chars` of reply. Pass the `text` itself too and the
        snapshot carries its tail and outline -- every streaming provider
        does; a caller that only knows a count still gets the count."""
        self.text_chars += chars
        if text:
            with self._lock:
                self._tail = (self._tail + text)[-TAIL_CHARS:]
                self._outline.feed(text)
        if chars and self.stage in ("waiting", "thinking"):
            self.stage = "writing"

    # -- what is shown -------------------------------------------------------

    @property
    def elapsed(self) -> float:
        return self._clock() - self.started

    def _tokens(self, chars: int) -> int:
        return int(chars / self.chars_per_token) if self.chars_per_token else chars

    def snapshot(self) -> dict:
        usage = self.usage or {}
        total_out = usage.get("output_tokens")
        output_tokens = self._tokens(self.text_chars)
        if total_out is not None:
            # The provider's own count, which includes any thinking. What
            # is left after the text we received is the thinking nobody
            # saw -- the subtraction `ClaudeProvider._report_usage` makes.
            # Where nothing announced thinking, a small remainder is the
            # chars-per-token estimate's own error, not hidden reasoning --
            # the same 25% threshold the usage line uses.
            thinking_tokens = max(0, total_out - output_tokens)
            if not self.thinking_seen and thinking_tokens <= total_out * 0.25:
                thinking_tokens = 0
        elif self.thinking_chars:
            thinking_tokens = self._tokens(self.thinking_chars)
        else:
            # Thinking under way but not streamed: unknown until the end,
            # which is not the same as none.
            thinking_tokens = None if self.thinking_seen else 0
        return {
            "label": self.label,
            "model": self.model,
            "effort": self.effort,
            "stage": self.stage,
            "started_at": self.started_at,
            "elapsed_s": round(self.elapsed, 1),
            "streams": self.streams,
            "thinking_seen": self.thinking_seen,
            "thinking_streamed": self.thinking_chars > 0,
            "thinking_chars": self.thinking_chars,
            "output_chars": self.text_chars,
            "thinking_tokens": thinking_tokens,
            "output_tokens": output_tokens,
            "input_tokens": input_total(usage) if usage.get("input_tokens") is not None else None,
            "total_output_tokens": total_out,
            "estimated": total_out is None,
            # The live view (issue: "show progress updates from the build
            # step ... and stop it if things are going haywire").
            "tail": self._tail,
            "thinking_line": _last_line(self._thinking_tail),
            "outline": self._outline_snapshot(),
        }

    def _outline_snapshot(self) -> dict | None:
        # Read by the ticker's `_notify` while the stream loop feeds the
        # outline in another thread; the lock keeps a half-updated dict
        # from being read. Never called with `_lock` already held.
        with self._lock:
            return self._outline.snapshot()

    def line(self) -> str:
        """The progress line, without any carriage return."""
        when = _fmt_elapsed(self.elapsed)
        if self.stage == "waiting":
            what = ("waiting for the first reply" if self.streams
                    else "waiting for the reply (this provider does not stream)")
            return f"  {self.who}: {what} -- {when}"
        if self.stage == "thinking":
            summary = _last_line(self._thinking_tail, 120) if not self.thinking_chars else ""
            if self.thinking_chars:
                return (f"  {self.who}: thinking -- {when}, "
                        f"~{self._tokens(self.thinking_chars):,} tokens so far")
            if summary:
                # A summary streams, the reasoning does not: say what it is
                # on, and that the tokens come at the end.
                return (f"  {self.who}: thinking -- {when} (tokens counted when the "
                        f"call ends): {summary}")
            return (f"  {self.who}: thinking -- {when}, not streamed "
                    "(counted when the call ends)")
        detail = f"~{self._tokens(self.text_chars):,} tokens of output so far"
        if self.thinking_chars:
            detail += f", after ~{self._tokens(self.thinking_chars):,} thinking"
        return f"  {self.who}: {self.stage} -- {when}, {detail}"

    def tick(self) -> None:
        """Draw, print and notify as the cadence allows. Safe from any
        thread and at any rate; the ticker calls it every MODEL_TICK."""
        with self._lock:
            if self._finished:
                return
            if self.enabled:
                if self.isatty:
                    # Never wider than the terminal: a line that wraps
                    # cannot be redrawn with `\r`, and every tick would
                    # leave a copy of itself behind.
                    columns = shutil.get_terminal_size((100, 20)).columns
                    text = self.line()[:max(20, columns - 1)]
                    # Pad to the previous width so a shorter line does not
                    # leave the tail of the longer one on screen.
                    pad = max(0, self._line_width - len(text))
                    self._line_width = len(text)
                    self._write("\r" + text + " " * pad)
                else:
                    now = self._clock()
                    changed = self.stage != self._pipe_stage
                    if changed or now - self._last_pipe >= _pipe_interval(now - self.started):
                        self._last_pipe = now
                        self._pipe_stage = self.stage
                        self._write(self.line() + "\n")
        self._notify("update")

    def finish(self, *, ok: bool = True, usage: dict | None = None) -> None:
        """Stop the ticker, clear the terminal line, send the last snapshot.
        Idempotent -- a provider calls it from `finally`, and the line that
        follows (the usage line) must never race a redraw."""
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2 * MODEL_TICK + 1)
        with self._lock:
            if self._finished:
                return
            self._finished = True
            if usage:
                self.usage = dict(usage)
            if ok:
                self.stage = "done"
            elif (self.stop is not None and self.stop.stopped) or _stopping():
                # A stop is not a failure: the page says "Stopped by you".
                self.stage = "stopped"
            else:
                self.stage = "failed"
            if self.enabled and self.isatty and self._line_width:
                self._write("\r" + " " * self._line_width + "\r")
        self._notify("end")

    # -- plumbing ------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.wait(MODEL_TICK):
            try:
                self.tick()
            except Exception:
                # Progress must never be the reason a build fails.
                pass

    def _notify(self, event: str) -> None:
        if self.listener is None:
            return
        try:
            self.listener({"event": event, **self.snapshot()})
        except Exception:
            # A listener that raises costs the display, never the call.
            pass

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            # Explicitly, every time: the case that matters is a pipe.
            self.stream.flush()
        except Exception:
            pass
