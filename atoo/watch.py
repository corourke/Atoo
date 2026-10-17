"""FR-6.4 proof of concept: "continuous audit" -- O4's static, comparative
check (`atoo.audit`), re-run against a live console on an interval
instead of once, surfacing only what *changed* since the last read (a
finding that just started applying, or just stopped) rather than restating
the same finding every cycle.

WING's OSC protocol has no general change-notification mechanism -- only
one event subscription that auto-expires after 10 seconds
(`WING_Remote-Protocols-3.1-03.pdf` p16, p30), and "one" is literal:
"WING's OSC remote protocol enables only one (1) subscription to data ...
at any given time", handed to the last requester. Taking it would take it
from whatever else is holding it, and we would then stop receiving
silently the moment anything took it back.

**What else on a desk might hold it is narrower than this paragraph used
to claim.** As established 2026-09-23: **WING-Edit does not use OSC** -- it
speaks the native binary protocol on TCP 2222, so it is not
a competitor for the subscription at all. Mixing Station's OSC mode is a
genuine hazard, and so is any other OSC client on the network, including
a second copy of this tool.

"Continuous" here means polling: read the same address set
`atoo.audit.read_console_state` already reads, on an interval, and
diff. This is a deliberate, simpler answer than a push architecture, not
a missed opportunity -- the protocol doesn't offer one that can be
scoped, and the one it does offer can be taken away without notice.

**Could a poll simply read less?** `atoo.watch_scope` answers that
with measured numbers rather than an estimate. The rules
`watch` runs read 3,891 of a Compact's 6,195 addresses, so a scoped
per-leaf pass is ~26s against ~41s -- better, and still six times the 3-4
second budget -- and it saves the node-dump read (the default) nothing at all,
because the leaves it drops live inside object nodes the read still has
to fetch. Scoping alone does not make `watch` responsive. That module is
not wired into the read path for exactly that reason; see its docstring.

**Names are read at Start and refreshed, not read every pass** (2026-10-01). A node dump cannot carry a name
(`audit.DUMP_UNSAFE_LEAVES`), so on a Compact the 88 strip, bus, DCA and
mute-group names -- plus the second pass's ~26 source-socket names --
were separate requests every pass: about a third of a pass's requests.
`refreshing_names` reads them on the first pass (the baseline Start
takes, which scoped names resolve against) and then every
`DEFAULT_NAME_REFRESH` passes; the passes between carry the last names
read, so every rule still sees a complete state. A socket a strip was
patched to since the last refresh is read the pass it appears. The cost
is that a rename reaches the in-use and duplicate-name rules only at the
next refresh, and every pass's findings carry one INFO, W001, saying
so. `atoo watch --name-refresh 1` reads them every pass, as before.

Session-based and read-only (FR-6.7, O6's own scope): this module never
writes to a console, holds no state between separate runs, and stops the
instant the caller stops iterating it -- there is no background service.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
from typing import Callable, Iterator, Mapping

from atoo.audit import (AuditRule, ConsoleState, DEFAULT_RULES, Finding, SEVERITY_ORDER,
                             names_read, rule_groups, run_audit, shared_sentence)
from atoo.diagnostics import Diagnostic, Severity

#: How many passes a live watch goes between reading names.
#: Chosen for a refresh about every 30 seconds at the measured cycle: a
#: node-dump pass took 4.8s on a WING Compact (A11, 2026-09-24), about
#: 1s less without its names, plus the default 2s `--interval` -- so one
#: refresh pass of ~6.8s and four of ~5.9s is ~30s. 1 reads names every
#: pass, which is what every watch did before this.
DEFAULT_NAME_REFRESH = 5

#: The refresh interval's target, in seconds, for the INFO's wording.
NAME_REFRESH_TARGET_SECONDS = 30

#: The INFO a watch carries while its names are refreshed rather than
#: read every pass. Not in `audit.DEFAULT_RULES`: it is a fact about how
#: the session reads, not a check over console state -- the same
#: standing as `audit.SCOPE_SUMMARY_RULE_ID`.
NAME_REFRESH_RULE_ID = "W001"

#: The INFO a live watch carries about its clip detection:
#: that it is listening, or why it is not. A fact about the session, like
#: W001, not a check over console state.
CLIP_STATUS_RULE_ID = "W002"

FindingKey = tuple

#: Every watch condition's rule id starts with this
#: (`watch_conditions.build_watch_rules`).
CONDITION_RULE_PREFIX = "WATCH:"


@dataclass(frozen=True)
class WatchNote(Diagnostic):
    """A fact about the watch session itself, not about the desk: which strip a scoped name resolved to at Start, that a
    condition is read as a position or as MAIN 1, that a scoped name
    matched nothing and is not watched, that names are refreshed rather
    than read every pass (W001).

    It is a `Diagnostic` like any finding, so `atoo watch` prints it
    at its severity exactly as before. The Watch page does not put it in
    the alert table -- the table is what is wrong on the desk -- but in a
    status line under the Watch header (`present_findings`), where
    `group` and `summary` give it a short form: `Resolved at Start` /
    `DCA Band -> DCA 1`. The full sentence stays in `message`."""

    group: str = ""
    summary: str = ""


def watch_note(finding: Diagnostic, group: str, summary: str) -> WatchNote:
    """`finding`, as a `WatchNote` with its short form."""
    return WatchNote(**{f.name: getattr(finding, f.name) for f in fields(Diagnostic)},
                     group=group, summary=summary)


@dataclass
class PresentedFindings:
    """One reading's findings as the Watch page shows them
    (`present_findings`): `alerts` for the table, `notes` for the status
    line, and `folded` -- each condition finding's key to the built-in
    findings shown under its row instead of in rows of their own."""

    alerts: list[Finding]
    notes: list[WatchNote]
    folded: dict[FindingKey, list[Finding]] = field(default_factory=dict)


#: Plan-bound rules that host a row the way a watch condition does: CV015 says an FX bus is bypassed, so E003 (and E001)
#: about the same insert fold under it rather than repeat it.
PLAN_HOST_RULE_IDS = frozenset({"CV015"})


def _is_host(f: Finding) -> bool:
    return f.rule_id.startswith(CONDITION_RULE_PREFIX) or f.rule_id in PLAN_HOST_RULE_IDS


def present_findings(findings: list[Finding]) -> PresentedFindings:
    """Split one reading's findings the way the Watch page shows them.

    - **Notes leave the table**: a `WatchNote` is status
      about the session, not an alert, and goes to `notes`.
    - **One fault, one row**: a built-in finding whose
      addresses are all cited by a firing `WATCH:` condition -- the same
      strip and field, `/dca/1/fdr` for CH002 and a `fader_db`
      condition on DCA 1 -- is folded under the condition's row. The
      engineer wrote that condition about that strip, so theirs is the
      row that matters, at the severity they gave it; the built-in is
      named under it rather than dropped. When the condition stops firing
      and the built-in still does, the built-in gets its own row back.

    `atoo watch` does not call this: on the command line the notes
    print at INFO and every finding prints on its own line, as before."""
    notes = [f for f in findings if isinstance(f, WatchNote)]
    rest = [f for f in findings if not isinstance(f, WatchNote)]
    conditions = [f for f in rest if _is_host(f)]
    alerts: list[Finding] = []
    folded: dict[FindingKey, list[Finding]] = {}
    for f in rest:
        host = None
        if not _is_host(f) and f.addresses:
            cited = set(f.addresses)
            host = next((c for c in conditions if cited <= set(c.addresses)), None)
        if host is None:
            alerts.append(f)
        else:
            folded.setdefault(finding_key(host), []).append(f)
    return PresentedFindings(alerts, notes, folded)


def finding_key(f: Finding) -> FindingKey:
    # (rule_id, addresses, severity) -- addresses is what the rule cited, so
    # the same rule firing for a *different* channel is correctly treated as
    # a different finding, not a repeat of one already known about. The
    # severity is part of it so a finding that is reported at another grade
    # (C004 at INFO while virtual soundcheck is on, a WARNING once it is
    # off) is the old row cleared and a new one, not a quiet recolouring.
    return (f.rule_id, f.addresses, f.severity)


@dataclass
class WatchEvent:
    iteration: int
    at: str
    all_findings: list[Finding]
    new_findings: list[Finding]
    cleared_findings: list[Finding]


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def watch(
    state_provider: Callable[[], ConsoleState],
    *,
    rules: list[AuditRule] | None = None,
    interval: float = 2.0,
    max_iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], str] = _default_clock,
    session_notes: Callable[[], list[Finding]] | None = None,
) -> Iterator[WatchEvent]:
    """Poll `state_provider()` every `interval` seconds, run `rules`
    (default `audit.DEFAULT_RULES`) against each read, and yield one
    WatchEvent per cycle.

    The first cycle (`iteration == 0`) always has empty `new_findings`/
    `cleared_findings` -- whatever's already wrong when you START
    watching isn't a change, it's the baseline (`all_findings` still
    carries it, for the caller to report once up front). From the second
    cycle on, `new_findings` is exactly what an operator needs an alert
    for: a finding that wasn't there last cycle. `cleared_findings` is
    the mirror -- something that WAS wrong and now isn't.

    A generator, not a thread or a background loop: the caller decides
    how to consume it (print every event, filter to alerts only, stop
    after `max_iterations`). `sleep`/`clock` are injectable so a test (or
    a bounded offline demo cycling through canned states) needs no real
    waiting and no wall-clock dependence.

    `session_notes`, when given, is called every cycle for the notes that
    are about the watch itself and not about the desk (the Virtual
    soundcheck switch, `virtual_soundcheck_note`); a caller whose switch
    changes mid-watch passes a function that reads it.
    """
    previous: dict[FindingKey, Finding] | None = None
    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        try:
            state = state_provider()
        except StopIteration:
            # A finite provider (an offline demo cycling through canned
            # states with no --count given) ends the watch cleanly rather
            # than raising -- PEP 479 would otherwise turn this into a
            # RuntimeError inside a generator, which is not a useful
            # surprise for a caller who just ran out of states to show.
            return
        # A copy per cycle: a caller may swap the list's contents while
        # this runs (the Watch page's Save does, `WatchSession.replace_rules`),
        # and the next cycle then audits with the new rules.
        findings = run_audit(state, list(rules) if rules is not None else None)
        noted = False
        if state.name_refresh is not None and state.name_refresh > 1:
            # The same finding every pass, so it is in the baseline and
            # never "new" or "cleared": announced once and kept (the Watch
            # page shows it in its status line, `present_findings`).
            findings.append(name_refresh_note(state.name_refresh))
            noted = True
        if state.clip_status is not None:
            findings.append(clip_status_note(state.clip_status))
            noted = True
        for note in (session_notes() if session_notes is not None else ()):
            findings.append(note)
            noted = True
        if noted:
            findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
        current = {finding_key(f): f for f in findings}

        if previous is None:
            new_findings: list[Finding] = []
            cleared_findings: list[Finding] = []
        else:
            new_findings = [f for key, f in current.items() if key not in previous]
            cleared_findings = [f for key, f in previous.items() if key not in current]

        yield WatchEvent(iteration, clock(), findings, new_findings, cleared_findings)

        previous = current
        iteration += 1
        if max_iterations is None or iteration < max_iterations:
            sleep(interval)


def render_event(event: WatchEvent) -> str | None:
    """None means "nothing changed this cycle" -- the caller's cue to
    print nothing rather than repeat the same all-clear every interval.
    Not meant for `iteration == 0` (the baseline) -- render that with
    `atoo.audit.render_findings(event.all_findings)` instead."""
    if not event.new_findings and not event.cleared_findings:
        return None
    lines = [f"[{event.at}] change detected:"]
    for verb, findings in (("NEW", event.new_findings), ("CLEARED", event.cleared_findings)):
        for group in rule_groups(findings):
            lines += _change_lines(verb, group)
    return "\n".join(lines)


def _change_lines(verb: str, group: list[Finding]) -> list[str]:
    """One rule's NEW or CLEARED entry. Several strips that started (or
    stopped) tripping one rule in the same pass are one line, as `audit`
    groups them:

        NEW     [INFO] CH001 Channel Not In Any DCA (2): CH 3 "Vocal", CH 4 "Vocal" -- each is in use but belongs to no DCA group.

    and where the sentences differ past the strip, one line each under one
    heading."""
    first = group[0]
    head = f"  {verb:<7} [{first.severity.value.upper()}] {first.rule_id} {first.title}"
    if len(group) == 1:
        return [f"{head}: {first.detail}"]
    head += f" ({len(group)})"
    shared = shared_sentence(group)
    if shared is not None:
        items, rest = shared
        return [f"{head}: {', '.join(items)} -- each{rest}"]
    return [f"{head}:"] + [f"            {f.detail}" for f in group]


def name_refresh_note(every: int) -> Finding:
    """W001: the INFO saying names are read at Start and every
    `every` passes, and what that costs."""
    about = (f" (about every {NAME_REFRESH_TARGET_SECONDS}s at the default 2s interval)"
             if every == DEFAULT_NAME_REFRESH else "")
    short = (f"refreshed about every {NAME_REFRESH_TARGET_SECONDS}s"
             if every == DEFAULT_NAME_REFRESH else f"refreshed every {every} readings")
    return watch_note(Diagnostic.audit(
        NAME_REFRESH_RULE_ID, Severity.INFO, "watch",
        "Names are refreshed, not read every pass",
        f"Strip, bus, DCA, mute-group and input-socket names are read at Start and "
        f"refreshed every {every} readings{about}; a rename shows up at the next refresh. "
        f"Everything else is read every pass. atoo watch --name-refresh 1 reads "
        f"names every pass.",
        (),
    ), "Names", short)


#: The rule id of the INFO saying the Virtual soundcheck switch is on.
VIRTUAL_SOUNDCHECK_RULE_ID = "W003"


def virtual_soundcheck_note() -> Finding:
    """W003: the INFO saying Virtual soundcheck is on, and what that
    changes -- C004 and C005 report at INFO instead of WARNING -- so a quiet
    desk is never mistaken for one with nothing on its alternate inputs.
    Present while the switch is on and absent when it is off."""
    return watch_note(Diagnostic.audit(
        VIRTUAL_SOUNDCHECK_RULE_ID, Severity.INFO, "watch", "Virtual soundcheck is on",
        "Virtual soundcheck is on: a channel on its alternate input (C004) and the global "
        "alternate switch (C005) are reported at INFO, not as warnings, and every one is still "
        "named. Turn it off when soundcheck ends, and any that is still on its alternate becomes "
        "a warning at once.",
        (),
    ), "Virtual soundcheck", "on, alternate inputs at INFO")


def clip_status_note(status) -> Finding:
    """W002: the INFO saying whether the console's meters are being
    listened to for clips (`metering.ClipMonitor`), and if not,
    why -- the connection could not be had, was lost, or no packets come.
    Keyed on on/off, so the command line says it again when it changes."""
    title = "Clip detection is on" if status.on else "Clip detection is off"
    return watch_note(Diagnostic.audit(
        CLIP_STATUS_RULE_ID, Severity.INFO, "watch", title, status.detail,
        ("clip:on" if status.on else "clip:off",),
    ), "Clip detection", status.summary)


#: The Watch page's note for a non-default or rejected
#: `ATOO_CONSOLE_WINDOW`.
WINDOW_NOTE_CODE = "console.window"


def window_note(environ=None) -> "WatchNote | None":
    """The Watch page's INFO note saying what `ATOO_CONSOLE_WINDOW`
    did to a live watch's reads, or None when the window is
    the default. Its message is the line `atoo watch` prints for the
    same setting (`console.window_notice`); `atoo watch` does not
    use this -- it prints that line already."""
    from atoo.console import WINDOW_ENV, window_notice, window_setting

    notice = window_notice(environ)
    if notice is None:
        return None
    window, _source, problem = window_setting(environ)
    short = (f"{window}, from {WINDOW_ENV}" if problem is None
             else f"{window} ({WINDOW_ENV} not taken as set)")
    return watch_note(Diagnostic.audit(
        WINDOW_NOTE_CODE, Severity.INFO, "watch",
        "Reads in flight", notice + ".", (),
    ), "Console window", short)


def refreshing_names(
    read: Callable[[Mapping[str, object] | None], ConsoleState],
    plan: list[tuple[str, str]],
    every: int = DEFAULT_NAME_REFRESH,
) -> Callable[[], ConsoleState]:
    """A state provider that reads names only on the first pass and on
    every `every`-th pass after it.

    `read(names)` is one live read: `audit.read_console_state(console,
    names=names, ...)`. It gets None on a refresh pass -- read every name
    -- and, on the passes between, the names the last refresh read
    (`audit.names_read` over `plan`, the read plan it was made from), so
    those passes do not ask for them and still hand the rules a complete
    state. Each state a pass between refreshes returns says how often
    names are refreshed (`ConsoleState.name_refresh`), which is what puts
    W001 in the findings; so does the first.

    `every <= 1` is today's watch exactly: `read(None)` every pass and
    the state untouched.
    """
    if every <= 1:
        return lambda: read(None)

    passes = 0
    known: dict[str, object] | None = None

    def provider() -> ConsoleState:
        nonlocal passes, known
        refresh = known is None or passes % every == 0
        state = read(None if refresh else known)
        if refresh:
            known = names_read(state, plan)
        else:
            # A socket a strip was patched to since the refresh was read
            # this pass (`read_console_state` asks for any name it was
            # not handed); keep it, so the next pass need not ask again.
            for address, value in names_read(state, []).items():
                known.setdefault(address, value)
        passes += 1
        return replace(state, name_refresh=every)

    return provider
