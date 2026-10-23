"""`atoo watch --findings-log FILE`: what a live Watch found, saved as it runs.

A Watch session that cannot be saved cannot be reported or replayed: the
engineer copies text off a terminal and someone separately asks for a
`--dump-state`. This writes one JSON object per line, appended and flushed
once per pass, so a crash or Ctrl-C loses nothing:

- one **header** (`"type": "header"`): the atoo version and where it runs
  from, the console address and what the desk answered to `/?` (model and
  firmware as it spelled them), the plan or none, the watch conditions in
  force, the start time;
- one **pass** line per pass (`"type": "pass"`): the time, the pass number,
  the clip/meter status, anything the desk did not answer, what appeared and
  what cleared since the last pass, and -- on the baseline and on every
  pass that changed something -- every finding standing, each in the same
  vocabulary as `--review-json` and the Watch page (`Diagnostic.to_dict`:
  `code` is the rule id, with `severity`, `message`, `where`, `addresses`);
- one **footer** (`"type": "footer"`) on a clean stop (the count reached or
  Ctrl-C).

It only ever writes to the file it is given. It never touches the desk and
holds no secret: the header names the address the user typed and nothing from
the environment, and no field of a finding is a key.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import IO, Callable

from atoo.watch import WatchEvent

#: Bumped when a line's shape changes, so a later reader knows what it has.
FORMAT = "atoo-findings-log/1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def header_line(*, install: dict | None, console: str | None, identity: list | None,
                plan: str | None, conditions: dict | None, started: str) -> dict:
    """The first line. `identity` is the `/?` reply exactly as the desk gave
    it (`WING,<ip>,<name>,<model>,<serial>,<firmware>`), or None offline."""
    return {
        "type": "header",
        "format": FORMAT,
        "started": started,
        "atoo": install,
        "console": console,
        "console_identity": identity,
        "plan": plan or "no plan",
        "conditions": conditions,
    }


def clip_summary(state) -> dict | None:
    """What the meters said this pass: whether they are being listened to,
    the strips whose clip stands, and how many strips carry signal."""
    status = getattr(state, "clip_status", None)
    clips = getattr(state, "clips", ()) or ()
    live = getattr(state, "live_strips", None)
    if status is None and not clips and live is None:
        return None
    return {
        "listening": getattr(status, "on", None),
        "summary": getattr(status, "summary", None),
        "clipped": [{"strip": c.base, "count": c.count, "seconds_ago": round(c.ago, 1)}
                    for c in clips],
        "strips_with_signal": None if live is None else len(live),
    }


def aes50_words(state) -> dict | None:
    """The raw words the desk gave for each AES50 port this pass,
    `{"A": {"stat": "UPD", "dev": "S32"}, ...}`: `/$stat/{A,B,C}/stat` and
    `/$stat/{A,B,C}/dev` exactly as read, so a status that flaps shows as a
    timeline whatever any rule made of it. None when the pass
    read none."""
    from atoo import console_facts

    ports = {}
    for port in console_facts.AES50_PORTS:
        stat = state.text(console_facts.aes50_status_address(port))
        dev = state.text(console_facts.aes50_device_address(port))
        if stat is not None or dev is not None:
            ports[port] = {"stat": stat, "dev": dev}
    return ports or None


def unanswered(state) -> dict | None:
    """What the desk did not answer: the families never asked, and the
    coverage caveat Watch prints."""
    from atoo.audit import coverage_caveat

    families = getattr(state, "unasked_families", None) or {}
    caveat = coverage_caveat(state)
    if not families and not caveat:
        return None
    return {"coverage": caveat, "unasked": {k: len(v) for k, v in families.items()}}


class FindingsLog:
    """An open findings log. `record(event, state)` once per pass,
    `close(reason)` for the footer. Appends, and flushes every line."""

    def __init__(self, sink: IO[str], header: dict, clock: Callable[[], str] = _now) -> None:
        self._sink = sink
        self._clock = clock
        self.passes = 0
        self._write(header)

    @classmethod
    def open(cls, path: str, header: dict) -> "FindingsLog":
        """Append to `path` (created if needed). OSError propagates: a log
        that cannot be written is reported before the watch starts."""
        return cls(open(path, "a", encoding="utf-8"), header)

    def _write(self, line: dict) -> None:
        self._sink.write(json.dumps(line, ensure_ascii=False, sort_keys=False) + "\n")
        self._sink.flush()

    def record(self, event: WatchEvent, state=None) -> None:
        changed = event.iteration == 0 or bool(event.new_findings or event.cleared_findings)
        line: dict = {
            "type": "pass",
            "pass": event.iteration,
            "at": event.at,
            "baseline": event.iteration == 0,
            "changed": changed,
            "appeared": [f.to_dict() for f in event.new_findings],
            "cleared": [f.to_dict() for f in event.cleared_findings],
            "finding_count": len(event.all_findings),
        }
        if changed:
            line["findings"] = [f.to_dict() for f in event.all_findings]
        if state is not None:
            meters = clip_summary(state)
            if meters is not None:
                line["meters"] = meters
            aes50 = aes50_words(state)
            if aes50 is not None:
                line["aes50"] = aes50
            missing = unanswered(state)
            if missing is not None:
                line["unanswered"] = missing
        self.passes += 1
        self._write(line)

    def close(self, reason: str = "stopped") -> None:
        """The footer, then the file. Written for a clean stop only."""
        try:
            self._write({"type": "footer", "stopped": self._clock(), "passes": self.passes,
                         "reason": reason})
        finally:
            self._sink.close()

    def close_footer(self, reason: str = "stopped") -> None:
        """The footer without closing the sink (an in-memory log that is
        still read after the watch ends)."""
        self._write({"type": "footer", "stopped": self._clock(), "passes": self.passes,
                     "reason": reason})

    def abandon(self) -> None:
        """Close without a footer (an error stopped the watch)."""
        self._sink.close()
