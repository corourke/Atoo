"""`atoo lessons` -- mine a bundle's builds for what keeps being
unclear (docs/developer/build-lessons-2026-09-27.md, part C).

`docs/developer/build-lessons-2026-09-27.md` was written by hand, from
lines the maintainer copied out of a terminal across several builds of one
show. That page's own proposal C is a build log (kept by
`atoo.progress.ModelCallProgress`) plus this command: a read-only
report over one bundle's CURRENT `plan.json`, EVERY build's log file,
and, optionally, the versions git already has of `plan.json`, so the
same page can be produced any time without anyone copying terminal
lines by hand.

**One file per build, not one field on the plan.** The maintainer, 2026-09-28:
*"I'm not sure the plan.json is the best place to keep it."* Since then,
each build writes `<bundle>/builds/<timestamp>.json`
(`atoo/build_log.py`) and `plan.json` keeps only a pointer. This
command reads every file in that folder (newest first, `--last N`
limits how many), so a lesson can recur across builds that never all
fit inside one plan.json's history. A plan built before this shipped
may still carry its log inline (`meta.build_log`); `items_from_plan`
below still mines that shape, so an old bundle's history (via `--git N`)
keeps working.

**No model call.** Everything here is string matching over what a build
already wrote down: each build log's notes, `meta.critic_findings`,
`meta.build_findings`, the plan's own `conventions_audit` entries, its
`inferred` markers, its `notes`, and `meta.verify_findings`. A question
that shows up once is one build's noise; the same question across two
builds, or across several items in one, is what part B of that page
calls a lesson worth writing down -- so items are grouped by a rough
"topic" (a channel/bus/output name if one is mentioned, else the plan
field involved) and topics that recur are ranked first.

The heuristics here are deliberately simple (substring/keyword matching,
no NLP) -- see `_topic_for`. Good enough to point a human at the right
handful of items to read in full; the reading and the writing-down (part
B of the design doc) stay human work.

**Where the thinking went** (slice D of `docs/developer/build-cost-
reduction.md`). Every build log that carries notes also gets a time
breakdown: each note is filed under one of five buckets by keyword
(`_bucket_for`, the same substring/regex style as `_topic_for`) --
*mechanical* (counting, numbering, socket tallies, overflow),
*conventions* (conflicts, ambiguity, whether a rule applies), *prompt*
(the plan format itself: schema, fields, key order, nulls), *writing*
(assembling the reply) and *judgement* for everything else -- and the
seconds between one note's `t` and the one before it (the call's start,
for the first) are summed per bucket, per role, per build. A thinking
summary describes the thinking that led up to it, so the gap BEFORE a
note is what that note is about. Time after the last note (the reply
itself streaming) has no note to describe it and is not counted. It is
the measurement slices B and C of that page are judged by. It is a
section of the default text and JSON reports rather than a flag: it is
a few lines per build, and a comparison across builds is the point.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from atoo import build_log as build_log_module

# The plan fields this heuristic recognises by name, so an item about
# "main_routes" and one about "the main route" land in the same topic
# even when neither mentions a channel or bus.
_FIELD_WORDS = (
    "main_routes", "main route", "bus_sends", "mute_group", "dca",
    "phantom", "hpf", "high-pass", "stereo", "inferred", "socket",
    "patch", "processing", "gain", "fader", "destination", "watch",
    "preset", "conventions_audit", "conventions conflict",
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{2,}")


@dataclass
class LessonItem:
    source: str            # "current", or a short commit sha
    kind: str               # build_log | critic | build_finding |
                             # conventions_audit | inferred | note | verify
    role: str | None        # generator/critic/watchlist, when the item has one
    text: str
    topic: str

    def to_dict(self) -> dict:
        return {"source": self.source, "kind": self.kind, "role": self.role,
                "text": self.text, "topic": self.topic}


@dataclass
class Topic:
    name: str
    items: list[LessonItem] = field(default_factory=list)

    @property
    def sources(self) -> set[str]:
        return {i.source for i in self.items}

    def to_dict(self) -> dict:
        return {"topic": self.name, "count": len(self.items),
                "sources": sorted(self.sources),
                "items": [i.to_dict() for i in self.items]}


# "Where the thinking went": the buckets, in the order they are tried --
# the first that matches a note owns it, like `_topic_for`'s own
# first-match rule -- and the seed patterns for each, from the festival
# build log read in docs/developer/build-cost-reduction.md. Matched against
# the lower-cased note. `\b` on the leading edge only, so "count" takes
# "counting" and "counts" but not "accounted". "required" is not counted
# after "phantom": an input list's "phantom required" is the model
# reading a row, not worrying about a required field.
BUCKETS = ("mechanical", "conventions", "prompt", "writing", "judgement")

_BUCKET_PATTERNS: tuple[tuple[str, tuple[re.Pattern, ...]], ...] = tuple(
    (bucket, tuple(re.compile(p) for p in patterns))
    for bucket, patterns in (
        ("mechanical", (
            r"\bcount", r"\bnumber", r"\btall(y|ies)", r"\bsequential",
            r"\boverflow", r"\bmaps? to\b", r"\bnext free\b",
            r"\bsockets?\s+\S*\d", r"\d\s*\u00d7\s*\d|\u00d7 ", r"\btotal",
        )),
        ("conventions", (
            r"\bconflict", r"\bambigu", r"\bwhether\b", r"\bdoes\b.*\bapply",
            r"\bscope\b", r"\bwhat\b.*\bmeans\b", r"\breconsider", r"\btricky\b",
        )),
        ("prompt", (
            r"\bschema", r"\bfields?\b", r"\bkey order\b", r"\bformat",
            r"\bexamples?\b", r"\bindex field\b", r"(?<!phantom )\brequired\b",
            r"\bnull\b",
        )),
        ("writing", (
            r"\bwriting\b", r"\bassembling\b", r"\bjson\b", r"\bprovenance\b",
        )),
    )
)


def _bucket_for(text: str) -> str:
    """The bucket a build-log note's time is filed under: the first of
    `BUCKETS` whose seed patterns match, else "judgement"."""
    lowered = text.lower()
    for bucket, patterns in _BUCKET_PATTERNS:
        if any(p.search(lowered) for p in patterns):
            return bucket
    return "judgement"


@dataclass
class RoleTime:
    """One role's share of one build's thinking time, per bucket."""
    notes: int = 0
    seconds: dict[str, float] = field(default_factory=lambda: {b: 0.0 for b in BUCKETS})

    @property
    def total(self) -> float:
        return sum(self.seconds.values())

    def share(self, bucket: str) -> float:
        return self.seconds[bucket] / self.total if self.total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "notes": self.notes,
            "seconds": round(self.total, 1),
            "buckets": {b: {"seconds": round(self.seconds[b], 1),
                            "share": round(self.share(b), 3)} for b in BUCKETS},
        }


def thinking_time(build_log: dict) -> dict[str, RoleTime]:
    """`{role: RoleTime}` for one build's `{role: {notes, usage}}` log.
    Each note is charged the seconds since the note before it (since the
    call's start, t=0, for the first); a `t` that goes backwards or is
    missing charges nothing rather than a negative gap. A role with no
    notes is left out -- there is no time to divide."""
    out: dict[str, RoleTime] = {}
    if not isinstance(build_log, dict):
        return out
    for role, entry in build_log.items():
        if not isinstance(entry, dict):
            continue
        rt = RoleTime()
        prev = 0.0
        for note in entry.get("notes") or []:
            if not isinstance(note, dict):
                continue
            try:
                t = float(note.get("t"))
            except (TypeError, ValueError):
                continue
            gap = max(0.0, t - prev)
            prev = max(prev, t)
            rt.notes += 1
            rt.seconds[_bucket_for(str(note.get("text", "")))] += gap
        if rt.notes:
            out[str(role)] = rt
    return out


@dataclass
class BuildTime:
    source: str                    # the build log's file stem, "current", or a sha
    roles: dict[str, RoleTime]

    def to_dict(self) -> dict:
        return {"source": self.source,
                "roles": {r: t.to_dict() for r, t in self.roles.items()}}


@dataclass
class LessonsReport:
    sources: list[str]             # "current", then commit shas, newest first
    items: list[LessonItem]
    topics: list[Topic]            # ranked, recurring first
    git_note: str | None = None    # e.g. "<dir> is not a git repository"
    thinking_time: list[BuildTime] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sources": self.sources,
            "git_note": self.git_note,
            "thinking_time": [b.to_dict() for b in self.thinking_time],
            "topics": [t.to_dict() for t in self.topics],
        }


def _collect_names(plan: dict) -> set[str]:
    """Every channel, bus, DCA and output name this plan defines --
    what `_topic_for` looks for first, since a build's own thinking talks
    about the desk in these terms."""
    names: set[str] = set()
    for ch in plan.get("channels") or []:
        if isinstance(ch, dict) and ch.get("name"):
            names.add(str(ch["name"]))
    for key in ("busses", "dcas", "outputs", "mute_groups"):
        section = plan.get(key)
        if isinstance(section, dict):
            names.update(str(k) for k in section)
    return names


def _topic_for(text: str, names: set[str]) -> str:
    """The topic an item is filed under: the first channel/bus/DCA/output
    name from this plan that appears in `text` (case-insensitive, whole
    word), else the first recognised plan-field word, else the first
    word of four-plus letters -- a bucket that is at worst as specific as
    the text itself, never "unknown".

    Among the names found, the longest wins (so "Kick In" beats "Kick"),
    then the one earliest in the text, then alphabetical. Without the
    last two, a note naming both "Strings" and "Guitars" went to
    whichever the set's hash order offered first, and the same bundle
    printed a different report from one run to the next."""
    lowered = text.lower()
    found = []
    for name in names:
        match = name and re.search(r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])", lowered)
        if match:
            found.append((-len(name), match.start(), name))
    if found:
        return min(found)[2]
    for word in _FIELD_WORDS:
        if word in lowered:
            return word
    match = _WORD_RE.search(text)
    return match.group(0) if match else "general"


def items_from_plan(plan: dict, source: str) -> list[LessonItem]:
    """Every item this design mines out of one plan, tagged with `source`
    (the bundle's current plan is "current"; a git revision is its short
    sha, from `_git_versions`)."""
    if not isinstance(plan, dict):
        return []
    names = _collect_names(plan)
    items: list[LessonItem] = []

    def add(kind: str, role: str | None, text: str) -> None:
        text = text.strip()
        if text:
            items.append(LessonItem(source, kind, role, text, _topic_for(text, names)))

    meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}

    build_log = meta.get("build_log") if isinstance(meta.get("build_log"), dict) else {}
    for role, entry in build_log.items():
        if not isinstance(entry, dict):
            continue
        for note in entry.get("notes") or []:
            if isinstance(note, dict):
                add("build_log", str(role), str(note.get("text", "")))

    for f in meta.get("critic_findings") or []:
        if isinstance(f, dict):
            add("critic", "critic", str(f.get("message", "")))

    for f in meta.get("build_findings") or []:
        if isinstance(f, dict):
            add("build_finding", None, str(f.get("message", "")))

    for entry in plan.get("conventions_audit") or []:
        if isinstance(entry, dict):
            text = str(entry.get("message") or entry.get("statement") or "")
            add("conventions_audit", None, text)

    def add_inferred(owner: str, markers) -> None:
        for m in markers or []:
            if not isinstance(m, dict):
                continue
            basis = m.get("basis", "")
            add("inferred", None, f"{owner}: {m.get('field', '?')} inferred"
                                  f"{f' ({basis})' if basis else ''}")

    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        owner = str(ch.get("name", "?"))
        add_inferred(owner, ch.get("inferred"))
        for send in ch.get("bus_sends") or []:
            if isinstance(send, dict):
                add_inferred(f"{owner} -> {send.get('bus', '?')}", send.get("inferred"))

    for key in ("busses", "dcas"):
        section = plan.get(key)
        if isinstance(section, dict):
            for name, obj in section.items():
                if isinstance(obj, dict):
                    add_inferred(str(name), obj.get("inferred"))

    for n in plan.get("notes") or []:
        text = n.get("text") if isinstance(n, dict) else n
        add("note", None, str(text or ""))

    verify_findings = meta.get("verify_findings") if isinstance(meta.get("verify_findings"), dict) else {}
    for sev in ("errors", "warnings"):
        for f in verify_findings.get(sev) or []:
            if isinstance(f, dict):
                add("verify", None, str(f.get("message", "")))

    return items


def items_from_build_log_file(entry: dict, source: str, names: set[str]) -> list[LessonItem]:
    """Every thinking-summary note in one build's OWN log file
    (`atoo/build_log.py`) -- what `items_from_plan`'s
    `build_log` mining above still does for a plan that carries it
    inline (built before this shipped). `source` is that file's
    filename, minus `.json` -- its build's own timestamp, so a lesson
    that recurs across builds still names each one it came from."""
    items: list[LessonItem] = []
    build_log = entry.get("build_log") if isinstance(entry, dict) else None
    if not isinstance(build_log, dict):
        return items
    for role, role_entry in build_log.items():
        if not isinstance(role_entry, dict):
            continue
        for note in role_entry.get("notes") or []:
            if not isinstance(note, dict):
                continue
            text = str(note.get("text", "")).strip()
            if text:
                items.append(LessonItem(source, "build_log", str(role), text,
                                        _topic_for(text, names)))
    return items


def _git_versions(directory: Path, plan_rel: str, n: int) -> tuple[list[tuple[str, dict]], str | None]:
    """Up to `n` OLDER committed versions of `plan_rel`, each
    `(short sha, parsed plan)`, newest first -- or `([], note)` when
    `directory` isn't a git repository at all. A version that isn't valid
    JSON is skipped rather than raising: an old plan mid-repair, or one
    from before this file existed at that path, is not this command's
    problem to solve."""
    if n <= 0:
        return [], None
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=directory, capture_output=True, text=True, check=True, timeout=10, encoding="utf-8")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return [], f"{directory} is not a git repository -- --git is skipped"

    try:
        log = subprocess.run(
            ["git", "log", f"-n{n}", "--format=%h", "--", plan_rel],
            cwd=directory, capture_output=True, text=True, check=True, timeout=20, encoding="utf-8")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return [], f"couldn't read {plan_rel}'s git history: {exc}"

    shas = [line.strip() for line in log.stdout.splitlines() if line.strip()]
    out: list[tuple[str, dict]] = []
    for sha in shas:
        try:
            # `:./<path>` (not `:<path>`), since git resolves a bare
            # `rev:path` relative to the repo ROOT, but this runs with
            # `cwd=directory` -- exactly like `git log`'s pathspec above,
            # which resolves relative to cwd already.
            show = subprocess.run(
                ["git", "show", f"{sha}:./{plan_rel}"],
                cwd=directory, capture_output=True, text=True, check=True, timeout=20, encoding="utf-8")
            plan = json.loads(show.stdout)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
                json.JSONDecodeError):
            continue
        if isinstance(plan, dict):
            out.append((sha, plan))
    return out, None


def gather(show_dir: str | Path, *, git_n: int = 0, last_n: int = 0) -> LessonsReport:
    """The report for the bundle at `show_dir`: its current `plan.json`
    (findings, conventions-audit entries, inferred markers, notes,
    verify warnings), every build's log file in `builds/` (issue
    #240 -- newest first, capped at `last_n` when given), plus (with
    `git_n`) up to that many older committed versions of `plan.json`
    itself, for a plan built before this shipped and still carrying its
    build log inline (`items_from_plan`'s own `meta.build_log` mining
    below reads that shape).

    Raises `FileNotFoundError` when `show_dir` has no `plan.json` at
    all -- there is nothing to mine, and that is worth a clear error
    rather than an empty report that reads as "no findings"."""
    directory = Path(show_dir)
    plan_path = directory / "plan.json"
    if not plan_path.is_file():
        raise FileNotFoundError(f"{plan_path} does not exist -- build this show first")

    current = json.loads(plan_path.read_text(encoding="utf-8"))
    names = _collect_names(current)
    sources = ["current"]
    all_items = list(items_from_plan(current, "current"))
    times: list[BuildTime] = []

    def add_time(source: str, build_log) -> None:
        roles = thinking_time(build_log)
        if roles:
            times.append(BuildTime(source, roles))

    current_meta = current.get("meta") if isinstance(current, dict) else None
    if isinstance(current_meta, dict):
        add_time("current", current_meta.get("build_log"))

    log_files = build_log_module.read_all(directory / build_log_module.DIRNAME)
    if last_n > 0:
        log_files = log_files[:last_n]
    for entry in log_files:
        file_source = Path(entry["file"]).stem
        sources.append(file_source)
        all_items.extend(items_from_build_log_file(entry, file_source, names))
        add_time(file_source, entry.get("build_log"))

    git_note = None
    if git_n > 0:
        versions, git_note = _git_versions(directory, "plan.json", git_n)
        for sha, plan in versions:
            sources.append(sha)
            all_items.extend(items_from_plan(plan, sha))
            meta = plan.get("meta")
            if isinstance(meta, dict):
                add_time(sha, meta.get("build_log"))

    topics = _rank_topics(all_items)
    return LessonsReport(sources=sources, items=all_items, topics=topics,
                         git_note=git_note, thinking_time=times)


def _rank_topics(items: list[LessonItem]) -> list[Topic]:
    """Topics ranked by how much they recur: first by how many DISTINCT
    sources (builds) raised something under that topic, then by how many
    items in total, then alphabetically -- so a topic one build mentioned
    five times does not outrank one that showed up in every build."""
    by_topic: dict[str, Topic] = {}
    for item in items:
        by_topic.setdefault(item.topic, Topic(item.topic)).items.append(item)
    ranked = sorted(by_topic.values(),
                    key=lambda t: (-len(t.sources), -len(t.items), t.name))
    return ranked


def render_text(report: LessonsReport) -> str:
    lines = [f"Sources: {', '.join(report.sources)} "
            f"({len(report.sources)} build{'s' if len(report.sources) != 1 else ''})."]
    if report.git_note:
        lines.append(f"  ({report.git_note})")
    if not report.items:
        lines.append("\nNothing to mine -- no build-log notes, findings, audit entries, "
                     "inferred markers, plan notes or verify warnings in any source read.")
        return "\n".join(lines)
    lines.append("")
    if report.thinking_time:
        lines.extend(render_thinking_time(report.thinking_time))
        lines.append("")
    for topic in report.topics:
        recurs = f", across {len(topic.sources)} builds" if len(topic.sources) > 1 else ""
        lines.append(f"## {topic.name} ({len(topic.items)} item(s){recurs})")
        for item in topic.items:
            role = f" [{item.role}]" if item.role else ""
            lines.append(f"  - ({item.source}, {item.kind}{role}) {item.text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_thinking_time(times: list[BuildTime]) -> list[str]:
    """The "Where the thinking went" section: one line per role per
    build, each bucket's share of the seconds the role's notes cover."""
    lines = ["## Where the thinking went (share of the time each role's notes cover)"]
    for build in times:
        lines.append(f"  {build.source}")
        width = max(len(r) for r in build.roles)
        for role, rt in build.roles.items():
            shares = ", ".join(f"{b} {rt.share(b) * 100:.0f}%" for b in BUCKETS)
            lines.append(f"    {role:<{width}}  {rt.total:6.1f}s over {rt.notes:>3} note(s): {shares}")
    return lines


def render_json(report: LessonsReport) -> str:
    return json.dumps(report.to_dict(), indent=2)
