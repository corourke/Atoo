"""Hand-authored ground truth for the *critic* pass.

This scores the second model pass: given a plan with known gaps in it,
here is what the critic is expected to notice. It is a **research
instrument** for the generator experiments, not part of any show
workflow -- nothing a user runs reads one of these files.

Note the name. A now-retired feature called *expectations*
made the same kind of hand-authored TOML assertion about a *plan*; this
module is a different thing that survives it, and the shared word is the
only thing they had in common. Its file is a `.critic-expect.toml` in the experiments tree,
never a bundle slot, and its question is "did
the critic see this gap", not "is this the show the engineer asked for".
That question has no deterministic answer, which is why it is
hand-authored.

What is scored is **recall**, and only recall. Every entry in the file is
a gap this project has already found in at least one real run, so "did
the critic flag this" has a right answer. "Is this other critic finding
spurious" does not -- there is no ground truth for it -- so an inflated
finding count is reported as a raw number for a human to judge and never
charged against the score. Measuring precision here would mean inventing
the oracle this file exists to avoid.

Three outcomes per entry, not two:

- **hit** -- some finding matched.
- **under-severity** -- a finding matched, but called it less serious than
  `severity_at_least` asks. The critic saw it and under-rated it, which is
  neither a clean catch nor a miss, and collapsing it into either one
  loses the only interesting half of the result.
- **miss** -- nothing matched.

And one state that is not an outcome at all: a critic pass that **never
ran** (no provider, a timeout, a reply that was not findings JSON) scores
nothing. `generate.critique_plan` returns an empty list both for "ran and
found nothing" and for "did not run", and those are opposite facts; a
scorecard that reported 0/3 for both would read as a model failing a test
it was never given. `score_critic()` takes `ran` explicitly and refuses
to guess.

Format (TOML, read with stdlib `tomllib` on Python 3.11+):

    [[expect]]
    id = "missing-monitor-sends"
    description = "qwen2.5-coder:7b (2026-09-11) dropped all 3 monitor sends"
    match_text = ["monitor", "send"]
    severity_at_least = "warning"

`match_text` is a list of substrings, matched case-insensitively against
one finding's text (its message, where and category, joined). **Every**
string must appear in the **same** finding. "Any of these" was the other
option and is wrong for this job: a critic finding saying "the monitor
sends look correct" would score as a hit for "dropped all three monitor
sends", which is precisely the false pass this file exists to catch. Two
gaps means two entries.
"""

from __future__ import annotations

import tomllib as _toml
from dataclasses import dataclass
from pathlib import Path

from atoo import diagnostics
from atoo.diagnostics import SEVERITY_ORDER, Diagnostic, Severity

EXPECT_KEYS = frozenset({"id", "description", "match_text", "severity_at_least"})

HIT = "hit"
UNDER_SEVERITY = "under-severity"
MISS = "miss"
# Not an outcome: the critic never ran, so this expectation was never put
# to it. Kept out of `misses` on purpose -- see this module's docstring.
NOT_SCORED = "not-scored"


class CriticExpectationsError(ValueError):
    """The critic-expectations file itself is wrong -- bad TOML, an unknown
    key, a value of the wrong shape. Distinct from "the critic missed
    something", which is a result, not an exception."""


@dataclass(frozen=True)
class CriticExpectation:
    id: str
    description: str
    match_text: tuple[str, ...]
    severity_at_least: Severity | None = None


@dataclass(frozen=True)
class CriticExpectations:
    source: str
    expectations: tuple[CriticExpectation, ...]

    def __len__(self) -> int:
        return len(self.expectations)


@dataclass(frozen=True)
class Outcome:
    expectation: CriticExpectation
    state: str
    matched: tuple[Diagnostic, ...] = ()

    @property
    def id(self) -> str:
        return self.expectation.id


@dataclass(frozen=True)
class Scorecard:
    """What one critic run scored against one expectations file.

    `ran=False` means the critic pass did not happen, and then every
    other number here is meaningless on purpose: `recall` is None rather
    than 0.0, because 0.0 is a claim about a model and this is a claim
    about the harness.
    """

    source: str
    outcomes: tuple[Outcome, ...]
    total_findings: int
    ran: bool = True

    @property
    def hits(self) -> tuple[Outcome, ...]:
        return tuple(o for o in self.outcomes if o.state == HIT)

    @property
    def under_severity(self) -> tuple[Outcome, ...]:
        return tuple(o for o in self.outcomes if o.state == UNDER_SEVERITY)

    @property
    def misses(self) -> tuple[Outcome, ...]:
        return tuple(o for o in self.outcomes if o.state == MISS)

    @property
    def expected(self) -> int:
        return len(self.outcomes)

    @property
    def recall(self) -> float | None:
        """Hits over expectations, or None if the critic never ran.

        An under-severity match is not counted as a hit. It is a partial
        credit the score deliberately does not award -- the point of
        `severity_at_least` is that calling a dropped channel a note is
        not the same as catching it.
        """
        if not self.ran:
            return None
        return len(self.hits) / self.expected if self.expected else 0.0

    @property
    def column(self) -> str:
        """`hits/expected` for a sweep table, or `--` if it never ran."""
        if not self.ran:
            return "--"
        return f"{len(self.hits)}/{self.expected}"

    def findings(self) -> list[Diagnostic]:
        """The scorecard in the project's one diagnostic vocabulary, so
        `diagnostics.render()` prints it like everything else."""
        if not self.ran:
            return [Diagnostic(
                severity=Severity.WARNING,
                code="critic-expect.not-run",
                where=self.source,
                message="the critic pass did not run, so nothing was scored -- this is "
                        "not the same as a critic that ran and found nothing",
                source="critic-expect",
            )]
        out: list[Diagnostic] = []
        for o in self.outcomes:
            if o.state == HIT:
                continue
            if o.state == UNDER_SEVERITY:
                worst = min(o.matched, key=lambda f: SEVERITY_ORDER[f.severity])
                out.append(Diagnostic(
                    severity=Severity.WARNING,
                    code="critic-expect.under-severity",
                    where=f"{self.source}: {o.id}",
                    message=f"critic flagged this but as {worst.severity.value}, where "
                            f"{o.expectation.severity_at_least.value} or worse was expected "
                            f"-- {o.expectation.description}",
                    source="critic-expect",
                ))
            else:
                out.append(Diagnostic(
                    severity=Severity.ERROR,
                    code="critic-expect.missed",
                    where=f"{self.source}: {o.id}",
                    message=f"critic did not flag this -- {o.expectation.description} "
                            f"(looked for all of: "
                            f"{', '.join(repr(t) for t in o.expectation.match_text)})",
                    source="critic-expect",
                ))
        return out

    def report(self) -> str:
        if not self.ran:
            return f"{self.source}: critic did not run -- nothing scored."
        lines = [
            f"{self.source}: {len(self.hits)}/{self.expected} expected findings caught "
            f"({len(self.under_severity)} under-severity, {len(self.misses)} missed) "
            f"out of {self.total_findings} critic finding(s) in total."
        ]
        for o in self.outcomes:
            mark = {HIT: "caught", UNDER_SEVERITY: "under ", MISS: "MISSED"}[o.state]
            lines.append(f"  [{mark}] {o.id}: {o.expectation.description}")
        return "\n".join(lines)


def parse_critic_expectations(text: str, source: str = "<string>") -> CriticExpectations:
    try:
        data = _toml.loads(text)
    except _toml.TOMLDecodeError as exc:
        raise CriticExpectationsError(f"{source}: not valid TOML -- {exc}") from exc

    top = set(data) - {"expect"}
    if top:
        raise CriticExpectationsError(
            f"{source}: unknown top-level section(s) {', '.join(sorted(top))}. "
            "Expected [[expect]] entries only."
        )

    raw = data.get("expect", [])
    if not isinstance(raw, list):
        raise CriticExpectationsError(f"{source}: [expect] must be written as [[expect]]")
    if not raw:
        raise CriticExpectationsError(
            f"{source}: no [[expect]] entries. An empty expectations file scores every "
            "critic run as a perfect 0/0, which reads as a pass."
        )

    out: list[CriticExpectation] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        where = f"{source}: [[expect]] #{i + 1}"
        if not isinstance(entry, dict):
            raise CriticExpectationsError(f"{where}: must be a table")
        unknown = sorted(set(entry) - EXPECT_KEYS)
        if unknown:
            raise CriticExpectationsError(
                f"{where}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
                f"Known keys: {', '.join(sorted(EXPECT_KEYS))}. "
                "Unknown keys are refused rather than ignored -- a typo that passes "
                "silently would make this file report success while checking nothing."
            )
        ident = entry.get("id")
        if not isinstance(ident, str) or not ident.strip():
            raise CriticExpectationsError(
                f"{where}: needs a non-empty string 'id' -- it is how a result names "
                "which expectation was missed"
            )
        if ident in seen:
            raise CriticExpectationsError(
                f"{where}: duplicate id {ident!r}. Ids name results, so two entries "
                "sharing one makes the scorecard ambiguous."
            )
        seen.add(ident)

        match_text = entry.get("match_text")
        if not isinstance(match_text, list) or not match_text:
            raise CriticExpectationsError(
                f"{where} ({ident}): 'match_text' must be a non-empty list of strings"
            )
        terms: list[str] = []
        for term in match_text:
            if not isinstance(term, str) or not term.strip():
                raise CriticExpectationsError(
                    f"{where} ({ident}): every 'match_text' entry must be a non-empty "
                    f"string, got {term!r}"
                )
            terms.append(term)

        severity = entry.get("severity_at_least")
        floor: Severity | None = None
        if severity is not None:
            if not isinstance(severity, str) or severity not in tuple(
                    s.value for s in Severity):
                raise CriticExpectationsError(
                    f"{where} ({ident}): 'severity_at_least' must be one of "
                    f"{', '.join(s.value for s in Severity)}, got {severity!r}"
                )
            floor = diagnostics.coerce_severity(severity)

        description = entry.get("description", "")
        if not isinstance(description, str):
            raise CriticExpectationsError(
                f"{where} ({ident}): 'description' must be a string"
            )

        out.append(CriticExpectation(
            id=ident,
            description=description,
            match_text=tuple(terms),
            severity_at_least=floor,
        ))

    return CriticExpectations(source=source, expectations=tuple(out))


def load_critic_expectations(path: str | Path) -> CriticExpectations:
    p = Path(path)
    return parse_critic_expectations(p.read_text(encoding="utf-8"), source=str(p))


# --------------------------------------------------------------------------


def _haystack(finding: Diagnostic) -> str:
    """Everything about a finding a human would read when deciding whether
    it is the gap they meant -- message, the place it names, and the kind
    the model gave it."""
    return " ".join(str(x) for x in (
        finding.message, finding.where, finding.category or "", finding.code or "")).lower()


def _matches(expectation: CriticExpectation, finding: Diagnostic) -> bool:
    text = _haystack(finding)
    return all(term.lower() in text for term in expectation.match_text)


def score_critic(findings: list[Diagnostic], expectations: CriticExpectations, *,
                 ran: bool = True) -> Scorecard:
    """Score one critic run against hand-authored expectations.

    `ran` is required to be passed honestly by the caller: an empty
    `findings` list means "ran and found nothing" only when `ran` is
    True. See this module's docstring.
    """
    if not ran:
        return Scorecard(source=expectations.source, outcomes=tuple(
            Outcome(expectation=e, state=NOT_SCORED) for e in expectations.expectations
        ), total_findings=0, ran=False)

    outcomes: list[Outcome] = []
    for expectation in expectations.expectations:
        matched = tuple(f for f in findings if _matches(expectation, f))
        if not matched:
            outcomes.append(Outcome(expectation, MISS))
            continue
        floor = expectation.severity_at_least
        if floor is not None and not any(
                SEVERITY_ORDER[f.severity] <= SEVERITY_ORDER[floor] for f in matched):
            outcomes.append(Outcome(expectation, UNDER_SEVERITY, matched))
        else:
            outcomes.append(Outcome(expectation, HIT, matched))
    return Scorecard(source=expectations.source, outcomes=tuple(outcomes),
                     total_findings=len(findings), ran=True)
