"""One diagnostic type, and one place that renders it.

Before this module there were five vocabularies for "something the
pipeline wants to tell a human": `conventions.Diagnostic`,
`verify_plan.Finding` (shared by `snapshot.py`),
`generate.CriticFinding`, `audit.Finding`, and bare `list[str]` in
`extract`/`rules`/`compiler`/`apply`/`ai_conventions`. Four of them were
structured, none of them agreed, and `cli.py` flattened all five to the
same undifferentiated ``  - {x}`` bullet on stderr -- which was the actual complaint: a limitation *we* need to fix looked exactly
like an error the engineer could fix in their own prose.

Everything now produces `Diagnostic` and is rendered by `render()`.

Severity is flat -- ``error`` / ``warning`` / ``info``, and that is
the whole list. The maintainer's call, on the issue (2026-09-19): a
"limitation" is not a fifth severity, it is a warning. A fourth,
``critical``, existed from #18 until 2026-09-23 and was dropped for the
same kind of reason -- **nothing in this codebase ever emitted one**, so
it was a rung of the ladder with no members, and `error` already blocked
everything a `critical` would have. The maintainer: *"Since we never emit
CRITICAL, let's drop it everywhere. ERROR suffices."*
What makes a limitation legible is not its severity but the two fields
below it -- `fix` (what the engineer should change, when they can) and
`issue` (the tracking issue, when they can't). A diagnostic carrying
`issue` renders "Not something you can fix in your conventions file",
which is the distinction #18 was filed to get.

`to_dict()` is the wire shape the Setup UI consumes, so the
UI is a client against the same engine (D9) rather than a second
renderer with its own opinions.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class Severity(str, Enum):
    """Flat severity, ordered worst-first by `SEVERITY_ORDER`.

    A `str` mixin, deliberately: `Severity.ERROR == "error"` is True, so
    the string comparisons that the pre-#18 layers were written against
    keep working, and `json.dumps` needs no encoder. (`enum.StrEnum`
    would be the modern spelling, but this package supports 3.9.)
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    __str__ = str.__str__


SEVERITY_ORDER = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}

# What a human sees at the head of a rendered block. "NOTE" rather than
# "INFO" for the quiet one, matching the mock-up.
SEVERITY_LABEL = {
    Severity.ERROR: "ERROR",
    Severity.WARNING: "WARNING",
    Severity.INFO: "NOTE",
}

_LABEL_WIDTH = max(len(label) for label in SEVERITY_LABEL.values()) + 2
_INDENT = " " * _LABEL_WIDTH


# The default tracker for "Atoo can't represent this yet" on the
# deterministic compile path. #29 ("retire the deterministic compile
# path") is the right one rather than #6: #6 asked for the compiler to
# consume the IR's richer membership and was closed not-planned in favour
# of `--strategy generate`, so every drop below is a symptom of the path
# #29 tracks retiring, not of a gap anyone intends to fill.
COMPILE_PATH_ISSUE = 29


def coerce_severity(value: Severity | str) -> Severity:
    """Accept either the enum or its string spelling.

    Call sites that predate this module pass `"error"`; the ones that
    came from `audit.py` pass `Severity.ERROR`. Both are correct.
    """
    return value if isinstance(value, Severity) else Severity(str(value))


@dataclass(frozen=True)
class Diagnostic:
    """One thing the pipeline wants to tell a human.

    Only `severity`, `code` and `message` are ever required. The rest
    carry provenance that some layers have and others don't -- an audit
    rule knows its `category` and the `addresses` it read, a conventions
    parser knows the source `line`, a plan verifier knows neither.

    `code` is stable and greppable: an audit rule's id (``R001``), or
    a dotted ``layer.what-happened`` (``rules.malformed-member``). It is
    what a user quotes in a bug report and what a UI filters on, so it
    must not be reworded when the message is.
    """

    severity: Severity
    code: str
    message: str
    where: str = ""              # the object it concerns ("bus Vocals", "channel 12")
    title: str = ""              # short label, when the producer has one (audit rules do)
    category: str = ""           # audit category, or the conventions section it came from
    fix: str | None = None       # what the engineer should change -- only when they can
    issue: int | None = None     # tracking issue -- set when this is ours to fix, not theirs
    addresses: tuple[str, ...] = ()   # console addresses the finding was read from
    source: str = ""             # which layer produced it ("extraction", "critic", "audit", ...)
    line: str = ""               # the verbatim source line, when there is one

    # ---- named constructors, one per layer's calling convention ----

    @classmethod
    def audit(
        cls,
        rule_id: str,
        severity: Severity | str,
        category: str,
        title: str,
        detail: str,
        addresses: tuple[str, ...] = (),
    ) -> "Diagnostic":
        """`audit.py`'s argument order, which 28 rules are written in.

        FR-4.3 ("findings shall cite the specific rule that was
        violated") is why `rule_id` leads and is never reconstructed
        after the fact -- it becomes `code`.
        """
        return cls(
            severity=coerce_severity(severity),
            code=rule_id,
            message=detail,
            where=addresses[0] if addresses else "",
            title=title,
            category=category,
            addresses=tuple(addresses),
            source="audit",
        )

    @classmethod
    def convention(
        cls,
        severity: Severity | str,
        section: str,
        line: str,
        message: str,
        code: str = "conventions.unparsed",
        where: str | None = None,
        **kw,
    ) -> "Diagnostic":
        """`conventions.py`'s (severity, section, line, message) shape.

        `section`/`line` provenance is load-bearing -- it is what
        surfaced #27's two hidden plan-changing drops -- so it is kept
        rather than flattened into the message. `where` defaults to the
        section and is overridden only where the section name isn't what
        a reader should be shown (preamble prose).
        """
        return cls(
            severity=coerce_severity(severity),
            code=code,
            message=message,
            where=section if where is None else where,
            category=section,
            line=line,
            source="conventions",
            **kw,
        )

    @classmethod
    def dropped(
        cls,
        area: str,
        detail: str,
        *,
        issue: int | None = COMPILE_PATH_ISSUE,
        code: str = "conventions.detail-dropped",
    ) -> "Diagnostic":
        """Something the rules IR stated that the compiler's narrower
        shape cannot carry (`ai_conventions.DroppedDetail`).

        This is the category an earlier change was actually filed about: it is
        *not* the engineer's mistake, and no amount of editing their
        conventions file will fix it. It is a warning like any other now
        (the maintainer's call -- a limitation is not its own severity), but it
        carries `issue`, which is what makes the renderer say so out
        loud instead of letting it sit in a bullet list next to genuine
        user error.
        """
        return cls(
            severity=Severity.WARNING,
            code=code,
            message=detail,
            where=area,
            issue=issue,
            source="conventions-adapter",
        )

    # ---- accessors the pre-#18 names still reach for ----

    @property
    def rule_id(self) -> str:
        """`audit.Finding.rule_id`, which `watch.py` keys findings on."""
        return self.code

    @property
    def detail(self) -> str:
        """`audit.Finding.detail`, which the Watch UI renders."""
        return self.message

    @property
    def section(self) -> str:
        """`conventions.Diagnostic.section`."""
        return self.category

    def __str__(self) -> str:
        where = f"{self.where}: " if self.where else ""
        code = f"  ({self.code})" if self.code else ""
        return f"[{self.severity.value}] {where}{self.message}{code}"

    def to_dict(self) -> dict:
        """The wire shape, for the UI and for `--json` output.

        Empty optional fields are dropped rather than sent as `""`/
        `null`: a consumer checking `if "fix" in d` is asking the right
        question, and a plan verifier's finding genuinely has no
        `category` rather than having an empty one.
        """
        out = {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
        }
        for name in ("where", "title", "category", "source", "line"):
            value = getattr(self, name)
            if value:
                out[name] = value
        if self.fix:
            out["fix"] = self.fix
        if self.issue is not None:
            out["issue"] = self.issue
        if self.addresses:
            out["addresses"] = list(self.addresses)
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Diagnostic":
        return cls(
            severity=coerce_severity(d["severity"]),
            code=d.get("code", ""),
            message=d.get("message", ""),
            where=d.get("where", ""),
            title=d.get("title", ""),
            category=d.get("category", ""),
            fix=d.get("fix"),
            issue=d.get("issue"),
            addresses=tuple(d.get("addresses", ())),
            source=d.get("source", ""),
            line=d.get("line", ""),
        )

    def with_source(self, source: str) -> "Diagnostic":
        """Same diagnostic, tagged with the layer that surfaced it."""
        return replace(self, source=source)


@dataclass
class DiagnosticList:
    """A stream of diagnostics, with the counts callers keep recomputing."""

    items: list[Diagnostic] = field(default_factory=list)

    def add(self, diagnostic: Diagnostic) -> None:
        self.items.append(diagnostic)

    def extend(self, diagnostics) -> None:
        self.items.extend(diagnostics)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def of(self, *severities: Severity) -> list[Diagnostic]:
        return [d for d in self.items if d.severity in severities]

    @property
    def errors(self) -> list[Diagnostic]:
        """Blocking, and the top of the ladder since `critical` was
        dropped (2026-09-23)."""
        return self.of(Severity.ERROR)

    @property
    def warnings(self) -> list[Diagnostic]:
        return self.of(Severity.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors


def sort_key(d: Diagnostic) -> tuple:
    """Worst first, then by code, then by the object concerned.

    Stable and total, so rendered output is diffable between runs --
    which is what makes a golden-output test on the renderer meaningful.
    """
    return (SEVERITY_ORDER[d.severity], d.code, d.where, d.message)


def _wrap(text: str, width: int) -> list[str]:
    """Greedy wrap that never breaks a word.

    Deliberately not `textwrap`: these messages embed quoted user input
    (`"the band category"`) and address lists, and `textwrap`'s
    whitespace normalisation rewrites them.
    """
    words = str(text).split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render(diagnostics, *, width: int = 78, heading: str | None = None,
           group: bool = True) -> str:
    """The one renderer. Blocks, severity-labelled, worst first.

        ERROR  DCA "Band" was dropped -- nothing will be assigned to it.
               You wrote "the band category", but your patch order defines:
               drums, bass, guitars, keyboards, strings, brass, vocals, misc
               Fix: use one of those names, or add "band" to your patch order.

        WARNING  Bus "INST Reverb": membership exclusions aren't supported yet.
               Not something you can fix in your conventions file -- it's a
               limitation of Atoo itself.

    The tracking issue stays in the data (`issue`), not in the text: a
    user reading this has no use for this repository's issue numbers.

    Returns "" for an empty stream, so a caller can `if text: print(text)`
    without first counting.

    Repeated findings -- the same code saying the same thing about
    twenty-two channels -- are printed as ONE block naming the items
    (`finding_groups`, FR-X.15c). Only the rendering is grouped: the list
    passed in is not changed, and neither is anything it was read from.
    `group=False` prints one block per finding.
    """
    items = sorted(diagnostics, key=sort_key)
    if group:
        from atoo.finding_groups import group as _group
        items = _group(items)
    if not items:
        return ""

    body_width = max(width - _LABEL_WIDTH, 32)
    out: list[str] = []
    if heading:
        out += [heading, ""]

    for i, d in enumerate(items):
        if i:
            out.append("")
        label = SEVERITY_LABEL[d.severity]
        headline = f"{d.where}: {d.message}" if d.where else d.message
        if d.title and d.title.lower() not in headline.lower():
            headline = f"{d.title} -- {headline}"

        first, *rest = _wrap(headline, body_width)
        out.append(f"{label.ljust(_LABEL_WIDTH - 2)}  {first}")
        out += [f"{_INDENT}{line}" for line in rest]

        if d.line:
            out += [f"{_INDENT}{line}" for line in _wrap(f"Your line: {d.line}", body_width)]
        if d.fix:
            out += [f"{_INDENT}{line}" for line in _wrap(f"Fix: {d.fix}", body_width)]
        if d.issue is not None:
            out += [
                f"{_INDENT}{line}" for line in _wrap(
                    "Not something you can fix in your conventions file -- "
                    "it's a limitation of Atoo itself.",
                    body_width,
                )
            ]
        if d.code:
            out.append(f"{_INDENT}({d.code})")

    return "\n".join(out)


def summary_line(diagnostics) -> str:
    """"2 error(s), 1 warning(s), 3 note(s)" -- or "" when there's nothing.

    Counted by severity rather than a single total, because the total was
    exactly what hid #27's two plan-changing drops inside a count of 25.
    """
    items = list(diagnostics)
    if not items:
        return ""
    counts = {s: 0 for s in Severity}
    for d in items:
        counts[d.severity] += 1
    parts = []
    for sev, noun in (
        (Severity.ERROR, "error"),
        (Severity.WARNING, "warning"),
        (Severity.INFO, "note"),
    ):
        if counts[sev]:
            parts.append(f"{counts[sev]} {noun}(s)")
    return ", ".join(parts)
