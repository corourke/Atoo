"""Deterministic verification of a plan -- the bounded half.

The experiment's thesis: a *deterministic parser of conventions* must model
English, which is unbounded, so its schema grows forever. A *deterministic
verifier of plans* must model only what a WING can be set to, which is
finished. This module is that verifier.

It knows nothing about conventions files, categories, patch order, or
intent. It is handed a plan and the input list that plan claims to cover,
and it answers one question: could this plan be applied to a real console
and would it mean what it says? Everything it checks comes from
`console_facts.py` (read off the hardware) or from the input list itself.

Findings are split the way `atoo apply` needs them split:

  error   -- do not apply. The plan is impossible, self-contradictory,
             loses an input, invents one, or would damage equipment.
  warning -- apply is possible but a human should look first.
  info    -- a note: a value was decided where the conventions were silent
             (`inferred.py`), or something declared is used by nothing.
             An error of judgement is not an error of
             patching -- a choice that may displease is said, not refused.

Deliberately NOT checked here: whether the plan is a good reading of the
conventions. No deterministic code can check that, which is the entire
reason the generator half exists. That judgement belongs to the critic
pass and to the human reading the diff.
"""

from __future__ import annotations

import difflib

import re
from dataclasses import dataclass, field, replace

from atoo import console_facts as facts
from atoo import diagnostics
from atoo import inferred
from atoo import finding_groups
from atoo.diagnostics import Diagnostic, Severity

# Reading the input list's free-text `patch` column is shared input
# parsing, not plan derivation. It used to be borrowed from the compiler;
# since that path was retired it lives with the input list itself, which
# is whose column format it is.
from atoo.input_list import InputRow, InputRows, format_socket, parse_socket_spec as _parse_socket_spec
from atoo import plan_compat
from atoo.plan_schema import PLAN_SCHEMA
from atoo.schema_check import validate as validate_schema

# These are `atoo.diagnostics.Severity` members now, not
# bare strings. `Severity` is a `str` enum, so every existing comparison
# against "error"/"warning" -- here, in snapshot.py and in the tests --
# keeps meaning what it meant.
SEVERITY_ERROR = Severity.ERROR
SEVERITY_WARNING = Severity.WARNING

# Microphone models that must never see phantom power. Passive ribbons
# only: 48V across a passive ribbon element destroys the microphone, and
# it is not recoverable by undoing the setting afterwards
# (atoo/domain/knowledge.md). Active ribbons *require* phantom, which
# is why this is a model list and not a "ribbon" substring match.
PASSIVE_RIBBON_MODELS = (
    "r-121", "r121", "r-122v", "r-84", "m160", "m130",
    "royer", "coles 4038", "beyerdynamic m160",
)


# The canonical type. `Finding` was already the closest of
# the older shapes -- severity, stable code, where, message -- so it is
# the name kept here, now pointing at the shared class rather than a
# fourth private copy of it. Its `__str__` is unchanged:
# "[error] bus Vocals: ...  (bus.no-members)".
Finding = Diagnostic


@dataclass
class VerifyResult:
    findings: list[Finding] = field(default_factory=list)

    def add(
        self,
        severity: Severity | str,
        code: str,
        where: str,
        message: str,
        *,
        fix: str | None = None,
        issue: int | None = None,
    ) -> None:
        """`fix`/`issue` are optional and new: `fix` says what the
        engineer should change, `issue` says this one isn't theirs to fix
        at all. Neither is required, so the ~50 existing call sites in
        this module and in snapshot.py are unchanged."""
        self.findings.append(Diagnostic(
            severity=diagnostics.coerce_severity(severity),
            code=code,
            message=message,
            where=where,
            fix=fix,
            issue=issue,
            source="verify",
        ))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_WARNING]

    @property
    def infos(self) -> list[Finding]:
        """Notes: a choice was made where the conventions were silent
        (`inferred.py`), or the conventions declared something nothing
        uses. Never blocks, never even warns (an error of
        judgement is not an error of patching)."""
        return [f for f in self.findings if f.severity == Severity.INFO]

    @property
    def ok(self) -> bool:
        """True only when nothing blocks apply. Warnings do not block."""
        return not self.errors

    def report(self, *, omit_details: bool = False) -> str:
        """The verdict as text. `omit_details` leaves out the notes that
        are build details (`finding_groups.BUILD_DETAIL_CODES`) and says
        how many: `build` prints its own account of the same presets and
        effects just above, so verify's would repeat it.
        `atoo verify` prints every one."""
        if not self.findings:
            return "VERIFIED: no findings. Plan is applicable."
        infos = self.infos
        held = [f for f in infos if finding_groups.is_build_detail(f)] if omit_details else []
        if held:
            infos = [f for f in infos if f not in held]
        head = f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        if self.infos:
            head += f", {len(self.infos)} note(s)"
        if held:
            head += (f" ({len(held)} of them build details the build reported above, not "
                     "repeated -- `atoo verify` lists every one)")
        lines = [head, ""]
        blocks = [block for block in (self.errors, self.warnings, infos) if block]
        # One line per distinct message, naming the items it covers
        # (`finding_groups`, FR-X.15c); the counts above, and `findings`
        # itself, stay one per finding.
        for i, block in enumerate(blocks):
            if i:
                lines.append("")
            lines += [f"  {f}" for f in finding_groups.group(block)]
        if self.errors:
            verdict = "BLOCKED: do not apply."
        elif self.warnings:
            verdict = "APPLICABLE: warnings only."
        else:
            verdict = "APPLICABLE: notes only -- choices made where the conventions were silent."
        lines += ["", verdict]
        return "\n".join(lines)


def _in_range(value, lo: float, hi: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and lo <= value <= hi


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip().casefold()


# --------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------

_TOP_LEVEL = ("channels", "dcas", "mute_groups", "busses", "outputs")
_CHANNEL_REQUIRED = ("channel", "name", "source", "patch")


def _check_structure(plan: dict, r: VerifyResult) -> bool:
    """Returns False when the plan is too malformed for later checks to say
    anything meaningful -- better one clear finding than twenty cascading
    ones off a missing key."""
    if not isinstance(plan, dict):
        r.add(SEVERITY_ERROR, "plan.not-an-object", "plan", f"expected a JSON object, got {type(plan).__name__}")
        return False
    for key in _TOP_LEVEL:
        if key not in plan:
            r.add(SEVERITY_ERROR, "plan.missing-section", "plan", f"missing top-level {key!r}")
    if not isinstance(plan.get("channels"), list):
        r.add(SEVERITY_ERROR, "plan.channels-not-a-list", "plan.channels", "must be a list")
        return False
    if not plan["channels"]:
        r.add(SEVERITY_ERROR, "plan.no-channels", "plan.channels", "plan assigns no channels at all")
        return False

    ok = True
    # Review 2026-09-28, R4: an `outputs` or `busses` entry that is not an
    # object (a null, a list) reached `.get` in the checks below and
    # raised, breaking this function's never-raises contract. The schema
    # has already named it; stop here, as for a malformed channel.
    for key, label in (("outputs", "output"), ("busses", "bus")):
        section = plan.get(key)
        if section is None:
            continue
        if not isinstance(section, dict):
            r.add(SEVERITY_ERROR, f"plan.{key}-not-an-object", f"plan.{key}",
                  "must be an object keyed by name")
            ok = False
            continue
        for name, entry in section.items():
            if not isinstance(entry, dict):
                r.add(SEVERITY_ERROR, f"{label}.not-an-object", f"{key}[{name}]",
                      f"must be an object, got {type(entry).__name__}")
                ok = False
    for i, ch in enumerate(plan["channels"]):
        where = f"channels[{i}]"
        if not isinstance(ch, dict):
            r.add(SEVERITY_ERROR, "channel.not-an-object", where, "must be an object")
            ok = False
            continue
        for key in _CHANNEL_REQUIRED:
            if key not in ch:
                r.add(SEVERITY_ERROR, "channel.missing-field", where, f"missing required field {key!r}")
                ok = False
    return ok


# --------------------------------------------------------------------------
# strips: index range, bank capacity, uniqueness, name length
# --------------------------------------------------------------------------

def _check_strips(plan: dict, r: VerifyResult) -> None:
    seen: dict[tuple[str, int], str] = {}
    for ch in plan["channels"]:
        bank = ch.get("bank", "ch")
        idx = ch.get("channel")
        name = ch.get("name", "")
        where = f"channels[{name}]"

        if bank not in ("ch", "aux"):
            r.add(SEVERITY_ERROR, "strip.unknown-bank", where,
                  f"bank {bank!r} is not an input bank -- WING has 'ch' and 'aux' only")
            continue

        cap = facts.CAPACITY[bank]
        if not isinstance(idx, int) or isinstance(idx, bool):
            r.add(SEVERITY_ERROR, "strip.index-not-an-int", where, f"strip index {idx!r} is not an integer")
            continue
        if not 1 <= idx <= cap:
            r.add(SEVERITY_ERROR, "strip.index-out-of-range", where,
                  f"{bank} {idx} does not exist -- a {facts.CONSOLE_MODEL} has {bank} 1..{cap}")
            continue

        key = (bank, idx)
        if key in seen:
            r.add(SEVERITY_ERROR, "strip.double-booked", where,
                  f"{bank} {idx} is already assigned to {seen[key]!r} -- two sources cannot share one strip")
        else:
            seen[key] = name

        if len(str(name)) > facts.NAME_MAX_CHARS:
            r.add(SEVERITY_ERROR, "strip.name-too-long", where,
                  f"name is {len(str(name))} characters -- the console truncates at "
                  f"{facts.NAME_MAX_CHARS}, so the console would not show {name!r}")


def _check_colours_are_writable(plan: dict, r: VerifyResult) -> None:
    """A stated colour that `apply` cannot write must say so here.

    The plan has two colour fields and they are not the same thing. `color`
    is free text the conventions can state ("Red", "the drums are red");
    `col` is the console's own integer 1..18 at `{strip}/col`, and it is
    the only one `apply` writes. **There is no confirmed name-to-index
    mapping**, so a plan that states `color` and not `col` loses the
    colour silently, between a plan that reads as if it had one and a desk
    that does not.

    Confirmed on hardware 2026-09-21. The touringband plan
    states a colour for all 19 channels; the snapshot taken straight after
    the apply
    (the A1 snapshot of 2026-09-21) has `col: 1`
    on all 40 -- the default, untouched. It was found by looking at
    the desk, which is the only place it was visible.

    A warning, not an error: nothing about the rest of the plan is unsafe,
    and blocking an apply over a colour would be absurd. But it is the
    plan making a promise it does not keep, so it does not get to be
    silent. 

    **One finding for the whole plan, not one per strip.** touringband
    would emit nineteen identical warnings, which is how a real finding
    gets scrolled past. Same call `preset.no-library` already makes, and
    for the same reason: this is one systemic gap, not nineteen separate
    mistakes.
    """
    # Since the palette was measured on hardware (2026-09-22), a stated
    # colour usually DOES get written -- `apply` resolves it through
    # `facts.colour_index`. What is left is the narrower case this finding
    # should always have been about: a colour word the desk does not have.
    unresolved: dict[str, list[str]] = {}
    aliased: dict[str, list[str]] = {}
    for ch in plan.get("channels", []):
        if ch.get("col") is not None:
            continue
        colour = ch.get("color")
        if colour and facts.colour_index(colour) is None:
            unresolved.setdefault(str(colour), []).append(str(ch.get("name", "?")))
        elif colour and facts.colour_alias(colour) is not None:
            aliased.setdefault(str(colour), []).append(str(ch.get("name", "?")))
    _report_unwritable_colours(r, "strip.colour-not-writable", "strip(s)", "strips", unresolved)
    _report_colour_aliases(r, "strip.colour-alias", aliased)

    # A bus states its colour the same way (bus
    # colours come from the conventions), and an unknown name is lost the
    # same way, so it is reported the same way -- its own code, because
    # the thing that keeps its old colour is a bus, not a strip.
    unresolved_busses: dict[str, list[str]] = {}
    aliased_busses: dict[str, list[str]] = {}
    busses = plan.get("busses")
    for name, bus in (busses.items() if isinstance(busses, dict) else ()):
        if not isinstance(bus, dict) or bus.get("col") is not None:
            continue
        colour = bus.get("color")
        if colour and facts.colour_index(colour) is None:
            unresolved_busses.setdefault(str(colour), []).append(str(name))
        elif colour and facts.colour_alias(colour) is not None:
            aliased_busses.setdefault(str(colour), []).append(str(name))
    _report_unwritable_colours(r, "bus.colour-not-writable", "bus(ses)", "busses", unresolved_busses)
    _report_colour_aliases(r, "bus.colour-alias", aliased_busses)


def _report_colour_aliases(r: VerifyResult, code: str, aliased: dict[str, list[str]]) -> None:
    """One INFO per retired colour name the plan still uses (A24, 2026-09-28).

    "Crimson" and "Magenta" were Atoo's words for the desk's Red (9)
    and Pink (11) until the desk was asked. They still resolve -- a
    conventions file written with them keeps colouring what it meant to --
    but the engineer should know which colour the desk will call it, and
    that the conventions can say so in the desk's own word next time.
    """
    for colour, names in sorted(aliased.items()):
        index = facts.colour_alias(colour)
        desk = facts.COLOUR_NAMES[index]
        r.add(Severity.INFO, code, "plan",
              f"{colour!r} is the desk's {desk} ({index}): {', '.join(names)}. The desk has "
              f"no color called {colour!r}; Atoo used that name for {index} until the "
              f"desk was asked, so it still resolves. Say {desk!r} to use the desk's own word")


def _report_unwritable_colours(r: VerifyResult, code: str, counted: str, those: str,
                               unresolved: dict[str, list[str]]) -> None:
    """One WARNING for every colour name the desk lacks, across the plan."""
    if not unresolved:
        return
    named = "; ".join(f"{colour!r} ({', '.join(strips)})" for colour, strips in sorted(unresolved.items()))
    r.add(SEVERITY_WARNING, code, "plan",
          f"{sum(len(v) for v in unresolved.values())} {counted} state a color the console does "
          f"not have: {named}. The desk's eighteen are "
          f"{', '.join(facts.COLOUR_NAMES[i] for i in sorted(facts.COLOUR_NAMES))}. Those {those} "
          f"keep whatever color they already had -- pick one of the eighteen, or set 'col' "
          f"directly to the index you want")


# --------------------------------------------------------------------------
# patch: socket existence and exclusivity
# --------------------------------------------------------------------------

def _check_patch(plan: dict, r: VerifyResult, console_model: str | None) -> None:
    occupied: dict[tuple[str, int], str] = {}
    for ch in plan["channels"]:
        name = ch.get("name", "")
        where = f"channels[{name}].patch"
        patch = ch.get("patch")
        if patch is None and _unpatched_if_available(ch):
            # Asked for "if available", and its socket was not: built
            # unpatched on purpose, and said by `_check_instructed`.
            continue
        if not isinstance(patch, dict):
            r.add(SEVERITY_ERROR, "patch.missing", where, "channel has no patch object -- it is connected to nothing")
            continue

        group = patch.get("group")
        sockets = patch.get("sockets")
        if group not in facts.INPUT_SOCKETS:
            r.add(SEVERITY_ERROR, "patch.unknown-group", where,
                  f"input group {group!r} does not exist -- known groups: "
                  f"{', '.join(sorted(facts.INPUT_SOCKETS))}")
            continue
        if not isinstance(sockets, list) or not sockets:
            r.add(SEVERITY_ERROR, "patch.no-sockets", where, f"sockets {sockets!r} is not a non-empty list")
            continue

        # Panel count, not address-space count: the walk reports
        # /io/in/AUX/1..8 on a Compact that has no aux jacks at all, so
        # facts.INPUT_SOCKETS would pass a patch nobody can make. With no
        # console model the bound is unknowable, so the socket NUMBER goes
        # unchecked here (reported once, by verify_plan) while everything
        # else about the patch -- shape, group, double-booking -- still runs.
        limit = None if console_model is None else facts.input_socket_limit(group, console_model)
        for n in sockets:
            if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                r.add(SEVERITY_ERROR, "patch.socket-out-of-range", where,
                      f"{group} socket {n!r} is not a positive integer")
                continue
            if limit is not None and n > limit:
                model_label = facts.CONSOLE_MODELS[console_model]["label"]
                detail = (f"{group} {n} does not exist -- the {model_label} has no {group} "
                          f"inputs at all" if limit == 0 else
                          f"{group} {n} does not exist -- {group} inputs are 1..{limit} on a "
                          f"{model_label}")
                r.add(SEVERITY_ERROR, "patch.socket-out-of-range", where, detail)
                continue
            key = (group, n)
            if key in occupied:
                # Legal on real hardware -- two strips sharing one source is
                # a normal request (a separate monitor mix, or a socket
                # reused between acts; see knowledge.md) -- but worth
                # confirming somebody asked for it.
                #
                # **What it costs them depends on the group.** This message
                # said "one preamp between them, so head-amp gain and
                # phantom are common to both" unconditionally until
                # 2026-09-22, which is untrue of every group without a head
                # amp: a USR slot, PLAY, OSC, USB and the rest carry no
                # preamp to share. Only `facts.PHANTOM_CAPABLE_GROUPS` --
                # the physical mic inputs -- have one, so only they get that
                # sentence. Telling an engineer their two playback strips
                # share a gain knob that does not exist is the kind of
                # confident wrongness this project is trying not to emit.
                shares_a_preamp = group in facts.PHANTOM_CAPABLE_GROUPS
                cost = (" One preamp between them, so head-amp gain and phantom are common to both "
                        "and cannot differ." if shares_a_preamp else
                        f" {group} has no head amp, so there is no gain or phantom to share -- "
                        "the strips differ in everything after the source.")
                r.add(SEVERITY_WARNING, "patch.socket-shared", where,
                      f"{group} {n} is also patched to {occupied[key]!r}." + cost +
                      " A second strip off one input is a normal request; apply names each strip "
                      "directly and labels the source for both, since one source cannot carry two "
                      "names. Worth confirming the input list or instructions actually asked for it")
            else:
                occupied[key] = name

        stereo = bool(ch.get("source", {}).get("stereo"))
        if stereo and len(sockets) != 2:
            r.add(SEVERITY_ERROR, "patch.stereo-socket-count", where,
                  f"source is stereo but occupies {len(sockets)} socket(s) -- every input is mono, so a "
                  "stereo channel consumes exactly two")
        if not stereo and len(sockets) != 1:
            r.add(SEVERITY_ERROR, "patch.mono-socket-count", where,
                  f"source is mono but occupies {len(sockets)} sockets")

        # Two sockets is necessary but not sufficient: the desk pairs only
        # [odd, even] consecutive sources (protocol PDF p.225).
        # An error rather than a warning because the patch cannot be made at
        # all, not because it is unusual; the same reason
        # patch.stereo-socket-count is one. Nothing downstream would catch
        # it: apply writes `mode: ST` to both sockets and `in/conn/in` to
        # the first, neither of which fails, so a pair the desk cannot form
        # would report as a clean apply.
        if stereo:
            problem = facts.stereo_pair_problem(sockets)
            if problem:
                r.add(SEVERITY_ERROR, "patch.stereo-pair-not-odd-even", where,
                      f"{group} {sockets[0]}+{sockets[1]} cannot be a stereo pair -- {problem}. "
                      "The console's routing hardware forms a stereo pair only from consecutive "
                      "[odd, even] sockets, so this patch cannot be made as written",
                      # The rule is right, but "cannot be made as
                      # written" was the whole of what this finding said, and
                      # a show whose two halves genuinely are not adjacent was
                      # left with nowhere to go. The desk's own way round it
                      # is the USR group; name it, and say exactly how far
                      # Atoo has got with it.
                      fix="re-cable so the pair is consecutive and starts on an odd socket, or "
                          "route it through the desk's USER SIGNAL / USER PATCH layer: two "
                          "consecutive USR slots (odd first) can carry two totally disjoint "
                          "sources, and the channel patches that pair. A plan can now state "
                          "those slots in its `user_sources` section and `verify` checks them, "
                          "but `apply` does not write them yet -- so for now they have to be "
                          "set up on the console by hand")


# --------------------------------------------------------------------------
# alt_patch: the alternate input patch
# --------------------------------------------------------------------------

def _check_alt_patch(plan: dict, r: VerifyResult, console_model: str | None) -> None:
    """A channel's alternate input, where the plan states one.

    Absent or null is not a finding: an unset alternate breaks nothing,
    the strip works on its main input. What is checked is what cannot be
    set on a desk -- a group or socket that does not exist, a width the
    socket count contradicts, a pair the routing cannot form -- and
    those are errors, the same codes `patch` uses under `alt-patch.`.

    Sharing is where it differs. A socket feeding two strips is normal
    (`patch.socket-shared` is a WARNING), and so is an alternate on a
    socket another strip hears as its main: said at WARNING, because on
    the day the desk is switched to alternate that strip hears somebody
    else's source. It becomes an ERROR only when the two uses disagree
    about the socket's width: stereo/mono lives on the SOCKET
    (`/io/in/{grp}/{n}/mode`), apply writes it for both uses, and one
    socket cannot be both -- a physical setting that cannot work.
    """
    claims: dict[tuple[str, int], tuple[str, bool]] = {}
    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        patch = ch.get("patch")
        if isinstance(patch, dict) and isinstance(patch.get("sockets"), list):
            stereo = len(patch["sockets"]) > 1
            for n in patch["sockets"]:
                claims.setdefault((patch.get("group"), n), (f"{ch.get('name', '')!r}'s main patch", stereo))

    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict) or ch.get("alt_patch") is None:
            continue
        name = ch.get("name", "")
        where = f"channels[{name}].alt_patch"
        alt = ch["alt_patch"]
        if not isinstance(alt, dict):
            r.add(SEVERITY_ERROR, "alt-patch.malformed", where,
                  f"alt_patch {alt!r} is not a {{group, sockets, stated}} object")
            continue
        group, sockets = alt.get("group"), alt.get("sockets")
        if group not in facts.INPUT_SOCKETS:
            r.add(SEVERITY_ERROR, "alt-patch.unknown-group", where,
                  f"input group {group!r} does not exist -- known groups: "
                  f"{', '.join(sorted(facts.INPUT_SOCKETS))}")
            continue
        if not isinstance(sockets, list) or not sockets:
            r.add(SEVERITY_ERROR, "alt-patch.no-sockets", where,
                  f"sockets {sockets!r} is not a non-empty list")
            continue
        limit = None if console_model is None else facts.input_socket_limit(group, console_model)
        good = []
        for n in sockets:
            if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                r.add(SEVERITY_ERROR, "alt-patch.socket-out-of-range", where,
                      f"{group} socket {n!r} is not a positive integer")
            elif limit is not None and n > limit:
                model_label = facts.CONSOLE_MODELS[console_model]["label"]
                r.add(SEVERITY_ERROR, "alt-patch.socket-out-of-range", where,
                      f"{group} {n} does not exist -- " + (
                          f"the {model_label} has no {group} inputs at all" if limit == 0 else
                          f"{group} inputs are 1..{limit} on a {model_label}"))
            else:
                good.append(n)
        stereo = bool((ch.get("source") or {}).get("stereo"))
        if len(sockets) != (2 if stereo else 1):
            r.add(SEVERITY_ERROR, "alt-patch.stereo-socket-count" if stereo else
                  "alt-patch.mono-socket-count", where,
                  f"source is {'stereo' if stereo else 'mono'} but its alternate occupies "
                  f"{len(sockets)} socket(s) -- the alternate feeds the same strip, so it "
                  f"takes {'two' if stereo else 'one'}")
        elif stereo and len(good) == 2:
            problem = facts.stereo_pair_problem(good)
            if problem:
                r.add(SEVERITY_ERROR, "alt-patch.stereo-pair-not-odd-even", where,
                      f"{group} {good[0]}+{good[1]} cannot be a stereo pair -- {problem}. The "
                      "console forms a pair only from consecutive [odd, even] sockets")
        main = ch.get("patch") if isinstance(ch.get("patch"), dict) else {}
        if main.get("group") == group and main.get("sockets") == sockets:
            r.add(SEVERITY_WARNING, "alt-patch.same-as-main", where,
                  f"the alternate is {group} {'+'.join(map(str, sockets))}, the channel's own main "
                  "patch -- switching this strip to its alternate changes nothing")
            continue
        for n in good:
            key = (group, n)
            if key in claims:
                other, other_stereo = claims[key]
                if other_stereo != stereo:
                    r.add(SEVERITY_ERROR, "alt-patch.socket-width-conflict", where,
                          f"{group} {n} is {other}, {'stereo' if other_stereo else 'mono'}, and "
                          f"this {'stereo' if stereo else 'mono'} alternate. Width lives on the "
                          "socket, not the strip, so one socket cannot be both",
                          fix="give the alternate its own socket(s), or make the two uses agree")
                else:
                    r.add(SEVERITY_WARNING, "alt-patch.socket-shared", where,
                          f"{group} {n} is also {other}. Switched to its alternate, this strip "
                          "hears that source. Worth confirming the conventions asked for it")
            else:
                claims[key] = (f"{name!r}'s alternate", stereo)


# --------------------------------------------------------------------------
# user_sources: the USR slots this plan defines
# --------------------------------------------------------------------------

def _check_user_sources(plan: dict, r: VerifyResult, console_model: str | None) -> None:
    """The plan's `user_sources` section, and every `USR` patch against it.

    A WING stereo pair is two consecutive sockets starting on an
    odd one, which the desk enforces in hardware
    (`facts.STEREO_PAIR_RULE_CONFIRMED_ON_HARDWARE`). A show whose two halves
    are neither adjacent nor in the same group could not be planned here at
    all. The desk's answer is its `USR` group -- 56 virtual slots, each
    pointed at any source you like, paired two-at-a-time like ordinary
    sockets -- and `user_sources` is how a plan states what those slots are.

    So the pairing rule is untouched: `_check_patch` runs
    `stereo_pair_problem` over a `USR` pair exactly as over an `LCL` one, and
    `[25, 26]` passes it for the same reason `[15, 16]` does. What changes is
    that a plan can now say what USR 25 and USR 26 *are*.

    Three kinds of finding come out of here:

    * the entries' own correctness -- a real slot, one entry per slot, a
      source group that kind of slot accepts, an index that exists, and no
      `tap`/`leg` on a user patch, which has neither leaf;
    * a `USR` patch with no definition behind it, which is the hidden desk
      state this issue was filed about;
    * one warning per plan that `apply` does not write this section yet.

    That last one is the load-bearing one. Everything else here is checking;
    that one keeps a section apply silently ignores from reading like a
    section it honoured -- the same posture as `patch.not-checked` and
    `patch.expansion-bay-not-checked`, and the reason this slice is safe to
    ship before the write path exists.
    """
    entries = plan.get("user_sources")
    defined: dict[int, dict] = {}

    for i, entry in enumerate(entries or []):
        where = f"user_sources[{i}]"
        if not isinstance(entry, dict):
            continue                    # the schema check already said so
        slot = entry.get("slot")
        kind = facts.user_slot_kind(slot)
        if kind is None:
            r.add(SEVERITY_ERROR, "user-source.slot-out-of-range", where,
                  f"USR slot {slot!r} does not exist -- the console has "
                  f"{facts.USER_SIGNAL_SLOTS[1]} user signals (USR "
                  f"{facts.USER_SIGNAL_SLOTS[0]}..{facts.USER_SIGNAL_SLOTS[1]}) and "
                  f"{facts.USER_PATCH_SLOTS[1] - facts.USER_PATCH_SLOTS[0] + 1} user "
                  f"patches (USR {facts.USER_PATCH_SLOTS[0]}..{facts.USER_PATCH_SLOTS[1]})")
            continue
        if slot in defined:
            r.add(SEVERITY_ERROR, "user-source.duplicate-slot", where,
                  f"USR {slot} is defined twice in this plan -- one slot holds one source, "
                  "so the second definition would overwrite the first")
            continue
        defined[slot] = entry

        source = entry.get("source")
        if not isinstance(source, dict):
            continue                    # schema again
        group = source.get("group")
        index = source.get("index")
        allowed = facts.user_source_groups(slot)
        if group not in allowed:
            # The two kinds take completely different source groups, and a
            # JSON Schema cannot tell which slot an entry is for, so this is
            # the only place the distinction is made.
            other = (facts.USER_PATCH if kind == facts.USER_SIGNAL else facts.USER_SIGNAL)
            hint = ""
            if group in facts.user_source_groups(
                    facts.USER_PATCH_SLOTS[0] if kind == facts.USER_SIGNAL
                    else facts.USER_SIGNAL_SLOTS[0]):
                hint = (f" -- that is a source a {other} takes, and USR "
                        f"{facts.USER_SIGNAL_SLOTS[0]}..{facts.USER_SIGNAL_SLOTS[1]} are the "
                        f"user signals, USR {facts.USER_PATCH_SLOTS[0]}.."
                        f"{facts.USER_PATCH_SLOTS[1]} the user patches")
            r.add(SEVERITY_ERROR, "user-source.group-not-allowed", where,
                  f"USR {slot} is a {kind} and cannot take {group!r} as its source{hint}. "
                  f"A {kind} accepts: {', '.join(allowed)}")
            continue

        limit = facts.user_source_index_limit(slot, group, console_model)
        if isinstance(index, int) and not isinstance(index, bool) and limit is not None:
            if index < 1 or index > limit:
                if kind == facts.USER_SIGNAL:
                    detail = (f"{group} {index} does not exist -- the console has "
                              f"{limit} of them")
                else:
                    detail = (f"{group} {index} does not exist -- {group} inputs are "
                              f"1..{limit}")
                    if console_model is not None:
                        detail += f" on a {facts.CONSOLE_MODELS[console_model]['label']}"
                r.add(SEVERITY_ERROR, "user-source.index-out-of-range", where, detail)

        # `tap` and `lr` are leaves of `/io/in/USR/1..24/user` only. A user
        # patch connects a jack straight through: there is no strip to tap
        # and no stereo source to take one leg of. Writing either would be
        # writing an address that is not there.
        if kind == facts.USER_PATCH:
            for field_name, leaf in (("tap", "tap"), ("leg", "lr")):
                if entry.get(field_name) is not None:
                    r.add(SEVERITY_ERROR, "user-source.field-not-on-user-patch", where,
                          f"USR {slot} is a {facts.USER_PATCH} and has no {field_name!r} "
                          f"-- `/io/in/USR/{slot}/user` carries no `{leaf}` leaf at all. "
                          f"Only a {facts.USER_SIGNAL} (USR {facts.USER_SIGNAL_SLOTS[0]}.."
                          f"{facts.USER_SIGNAL_SLOTS[1]}) has one, because only it taps a "
                          "strip")

    used: set[int] = set()
    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        patch = ch.get("patch")
        if not isinstance(patch, dict) or patch.get("group") != "USR":
            continue
        name = ch.get("name", "")
        where = f"channels[{name}].patch"
        sockets = patch.get("sockets")
        if not isinstance(sockets, list):
            continue
        for slot in sockets:
            if facts.user_slot_kind(slot) is None:
                continue                # patch.socket-out-of-range said it
            used.add(slot)
            if slot not in defined:
                r.add(SEVERITY_WARNING, "patch.user-source-undefined", where,
                      f"patched to USR {slot}, a {facts.user_slot_kind(slot)}, but nothing "
                      "in this plan says what USR "
                      f"{slot} is. The slot exists on every console and the patch will be "
                      "accepted, so the channel is silent unless someone has already "
                      "assigned that slot a source by hand -- exactly the hidden desk state "
                      "a plan is meant to remove",
                      fix=f"add a `user_sources` entry for slot {slot} saying what feeds it, "
                          "or patch the channel at the physical socket instead")

    # An output socket fed from a USR slot reads it too (`direct_outputs`): a processed or post-fader feed to a recorder.
    for entry in plan.get("direct_outputs") or []:
        source = entry.get("source") if isinstance(entry, dict) else None
        if not isinstance(source, dict) or source.get("group") != "USR":
            continue
        slot = source.get("index")
        if facts.user_slot_kind(slot) is None:
            continue                    # direct-output.source-out-of-range said it
        used.add(slot)
        if slot not in defined:
            socket = format_socket(entry.get('group'), entry.get('socket'))
            r.add(SEVERITY_WARNING, "patch.user-source-undefined",
                  f"direct_outputs[{socket}]",
                  f"{socket} is fed from USR {slot}, a {facts.user_slot_kind(slot)}, but "
                  f"nothing in this plan says what USR {slot} is, so the output carries "
                  "whatever that slot is assigned to on the desk now",
                  fix=f"add a `user_sources` entry for slot {slot} saying what feeds it")

    # A slot nothing reads is kept, so a feed can be defined before it is
    # patched (the maintainer's default); said at INFO, since a
    # mistyped slot number looks exactly like this.
    for slot in sorted(set(defined) - used):
        r.add(Severity.INFO, "user-source.unused", f"user_sources[slot {slot}]",
              f"USR {slot} is defined here but no channel patches it and no output is fed "
              "from it yet: it is kept, and written to the desk, so a feed can be defined "
              "before it is patched. If it was meant to feed something, check the slot "
              "number: a mistyped one looks exactly like this")


def _check_expansion_bays(plan: dict, r: VerifyResult) -> None:
    """Say out loud that a CRD/MOD patch was not checked against what is
    actually in the bay -- once per plan, and only when the plan uses one.

    `CRD` and `MOD` are bays, not sockets. The firmware
    answers `/io/in/{CRD,MOD}/1..64` on a console with an empty slot, and
    a WING leaves the factory with `/$syscfg/opt_mod` reading `NONE`, so
    `facts.INPUT_SOCKETS`'s 64 is an address space rather than an
    inventory -- the same distinction the model-variant table draws for the panel counts one
    layer up. Measured on hardware 2026-09-21: the desk ACCEPTS a patch
    into an empty bay and reads it back unchanged
    (`facts.UNFITTED_BAY_PATCH_IS_ACCEPTED`).

    **This module cannot answer the question, and deliberately does not
    pretend to.** Verification is offline by contract (FR-1.2): it gets a
    plan and an input list, and neither of them states what is plugged
    into the console. The obvious-looking fixes are both worse than this
    warning:

    - *Refuse every CRD/MOD patch.* Wrong on any desk that does have the
      card -- which is most desks that patch from it.
    - *Let the plan or a flag state what is fitted.* That is a
      human-entered claim about hardware, believed over the hardware. The lesson of
      the model cross-check: a walk of the address tree is not a measurement of
      the console, and neither is a person typing what they remember
      being in the slot.

    So the finding says what was not checked and where it WILL be --
    `atoo apply` reads `/cards/$type` and `/$syscfg/opt_mod` in
    pre-flight and refuses the plan there, with the desk's own answer in
    hand. That is the same shape as `patch.not-checked` and
    `reconcile.not-checked` above: a skipped check that announces itself
    rather than passing silently, because a clean verify that quietly
    omitted something is indistinguishable from one that checked it.
    """
    used: dict[str, int] = {}

    def note(group: object) -> None:
        if isinstance(group, str) and group in facts.EXPANSION_BAY_ADDRESSES:
            used[group] = used.get(group, 0) + 1

    for ch in plan.get("channels") or []:
        if isinstance(ch, dict) and isinstance(ch.get("patch"), dict):
            note(ch["patch"].get("group"))
        # An alternate from WING LIVE is a CRD patch like any
        # other, and just as silent when the slot is empty.
        if isinstance(ch, dict) and isinstance(ch.get("alt_patch"), dict):
            note(ch["alt_patch"].get("group"))

    # A USER PATCH pointed at a bay is the same silence one hop
    # further back. The channel patches `USR 25`, which always exists, so
    # nothing above notices that USR 25 is fed from an empty card slot.
    for entry in plan.get("user_sources") or []:
        if isinstance(entry, dict) and isinstance(entry.get("source"), dict):
            note(entry["source"].get("group"))

    # Output side too: a Main routed to a card bay with no card in it is a
    # mix going nowhere, and the desk accepts that write just as happily.
    for bus in (plan.get("busses") or {}).values():
        destinations = (bus or {}).get("destinations")
        if not destinations:
            single = (bus or {}).get("destination")
            destinations = [single] if single is not None else []
        for dest in destinations:
            if not isinstance(dest, dict):
                continue
            for socket in plan_compat.output_patches(dest):
                if isinstance(socket, dict):
                    note(socket.get("group"))
    for out in (plan.get("outputs") or {}).values():
        for socket in plan_compat.output_patches(out):
            if isinstance(socket, dict):
                note(socket.get("group"))

    if not used:
        return
    named = ", ".join(
        f"{group} ({facts.GROUP_ALIASES.get(group, group)}), {count} time(s)"
        for group, count in sorted(used.items())
    )
    r.add(SEVERITY_WARNING, "patch.expansion-bay-not-checked", "plan",
          f"this plan uses an expansion bay -- {named} -- and nothing here checked that the "
          "console has anything in that slot. The bay can be empty and the console still "
          "answers all 64 sockets, accepts the patch and reads it back unchanged, so the "
          "channel would be silent with nothing reporting it",
          fix="`atoo apply` reads /cards/$type and /$syscfg/opt_mod from the desk before "
              "writing and refuses the plan if the bay is empty -- this cannot be checked "
              "offline, so run the apply preview against the console you will use",
          issue=115)


# --------------------------------------------------------------------------
# values: every number in its real domain
# --------------------------------------------------------------------------

def _check_eq(eq: dict | None, strip: str, where: str, r: VerifyResult) -> None:
    """One strip's `processing.eq`, against what that strip class has.

    Three of the four checks here cannot be expressed
    in the JSON schema at all: one CHANNEL_SCHEMA serves both the `ch` and
    `aux` banks, whose shelf-type and EQ-model enums differ, so the schema
    can only hold their union -- this is where the bank is finally known.
    The fourth (a filter type on a parametric band) is a constraint on a
    sibling key's value, which the schema's flat per-key bounds cannot
    reach either.

    All of it is about writing to a leaf that is not there. The console
    does not complain about those; it just goes on sounding like it did
    before, which is the failure mode this project keeps meeting.
    """
    if not eq:
        return
    valid_bands = facts.eq_band_ids(strip)
    if not valid_bands:
        # An unknown bank is `strip.unknown-bank`'s finding, not this
        # one's -- but this must not raise on the way past it, or the
        # verifier fails instead of reporting.
        r.add(SEVERITY_ERROR, "value.eq-strip-unknown", where,
              f"states an EQ, but {strip!r} is not a strip class this project has confirmed EQ facts for")
        return
    seen: set[str] = set()
    for entry in eq.get("bands") or []:
        band = entry.get("band")
        if band in seen:
            r.add(SEVERITY_ERROR, "value.eq-band-duplicate", where,
                  f"EQ band {band!r} is stated more than once -- which of the two is meant is not recoverable")
            continue
        seen.add(band)
        if band not in valid_bands:
            r.add(SEVERITY_ERROR, "value.eq-band-unavailable", where,
                  f"EQ band {band!r} does not exist on a {strip} strip, which has "
                  f"{', '.join(valid_bands)}")
            continue
        shape = entry.get("shape")
        if shape is not None:
            if band not in ("low", "high"):
                r.add(SEVERITY_ERROR, "value.eq-shape-on-parametric-band", where,
                      f"EQ band {band} states filter type {shape!r}, but only the low and high bands "
                      "have one (eq.leq/eq.heq) -- a parametric band is always a bell")
            elif shape not in facts.EQ_SHELF_TYPES[strip]:
                r.add(SEVERITY_ERROR, "value.eq-shape-unavailable", where,
                      f"EQ {band} band filter type {shape!r} is not offered on a {strip} strip "
                      f"({', '.join(facts.EQ_SHELF_TYPES[strip])})")
        if all(entry.get(k) is None for k in ("freq_hz", "gain_db", "q", "shape")):
            r.add(SEVERITY_WARNING, "value.eq-band-empty", where,
                  f"EQ band {band} is listed with no frequency, gain, Q or filter type -- "
                  "nothing would be written for it")

    model = eq.get("model")
    if model is not None and model not in facts.EQ_MODELS[strip]:
        r.add(SEVERITY_ERROR, "value.eq-model-unavailable", where,
              f"EQ model {model!r} is not offered on a {strip} strip "
              f"({', '.join(facts.EQ_MODELS[strip])})")


def _check_presend_eq(peq: dict | None, strip: str, where: str, r: VerifyResult) -> None:
    """A channel's PreSend EQ (`ch.{n}.peq`) -- three bells, channel-only.

    Its own check rather than a parameter on `_check_eq`, for the same
    reason it has its own schema: it is a different node with a different
    shape, not the main EQ with fewer bands.
    """
    if not peq:
        return
    valid_bands = facts.presend_eq_band_ids(strip)
    if not valid_bands:
        r.add(SEVERITY_ERROR, "value.presend-eq-unavailable", where,
              f"states a PreSend EQ, but a {strip} strip has no peq node -- only a ch strip does")
        return
    seen: set[str] = set()
    for entry in peq.get("bands") or []:
        band = entry.get("band")
        if band in seen:
            r.add(SEVERITY_ERROR, "value.presend-eq-band-duplicate", where,
                  f"PreSend EQ band {band!r} is stated more than once -- which of the two is meant "
                  "is not recoverable")
            continue
        seen.add(band)
        if band not in valid_bands:
            r.add(SEVERITY_ERROR, "value.presend-eq-band-unavailable", where,
                  f"PreSend EQ band {band!r} does not exist -- the peq node has "
                  f"{', '.join(valid_bands)}, and no shelf bands at all")
            continue
        if all(entry.get(k) is None for k in ("freq_hz", "gain_db", "q")):
            r.add(SEVERITY_WARNING, "value.presend-eq-band-empty", where,
                  f"PreSend EQ band {band} is listed with no frequency, gain or Q -- "
                  "nothing would be written for it")


def _check_values(plan: dict, r: VerifyResult) -> None:
    for ch in plan["channels"]:
        name = ch.get("name", "")

        proc = ch.get("processing") or {}
        hpf = proc.get("hpf_hz")
        if hpf is not None and not _in_range(hpf, *facts.HPF_HZ_RANGE):
            lo, hi = facts.HPF_HZ_RANGE
            r.add(SEVERITY_ERROR, "value.hpf-out-of-range", f"channels[{name}].processing",
                  f"high-pass {hpf!r} is outside the console's {lo:g}..{hi:g} Hz range")

        fader = ch.get("fader") or {}
        fdr = fader.get("fader_db")
        if fdr is not None and not _in_range(fdr, *facts.FADER_DB_RANGE):
            lo, hi = facts.FADER_DB_RANGE
            r.add(SEVERITY_ERROR, "value.fader-out-of-range", f"channels[{name}].fader",
                  f"fader {fdr!r} dB is outside {lo:g}..{hi:g} (-oo is exactly {facts.MINUS_INF_DB:g})")
        muted = fader.get("muted")
        if muted is not None and not isinstance(muted, bool):
            r.add(SEVERITY_ERROR, "value.mute-not-boolean", f"channels[{name}].fader",
                  f"muted {muted!r} is not true/false")

        for send in ch.get("bus_sends") or []:
            where = f"channels[{name}].bus_sends[{send.get('bus')}]"
            mode = send.get("mode")
            # None is not a finding: an unstated mode is decided, not
            # refused (`inferred.send_mode_fallback`, reported as an INFO
            # by `_check_inferred`). Only a mode that IS stated and is not
            # one this format can write is an error.
            if mode is not None and mode not in facts.PLAN_SEND_MODES:
                if str(mode).upper() in facts.SEND_MODES:
                    r.add(SEVERITY_ERROR, "value.send-mode-unrepresented", where,
                          f"send mode {mode!r} exists on the console but the plan schema models only "
                          f"{facts.PLAN_SEND_MODES} -- apply would not know what to write")
                else:
                    r.add(SEVERITY_ERROR, "value.send-mode-unknown", where,
                          f"send mode {mode!r} is not one of {facts.SEND_MODES}")
            lvl = send.get("level_db")
            if lvl is not None and not _in_range(lvl, *facts.SEND_LEVEL_DB_RANGE):
                lo, hi = facts.SEND_LEVEL_DB_RANGE
                r.add(SEVERITY_ERROR, "value.send-level-out-of-range", where,
                      f"send level {lvl!r} dB is outside {lo:g}..{hi:g}")

        for route in ch.get("main_routes") or []:
            idx = route.get("index")
            if not isinstance(idx, int) or isinstance(idx, bool) or not 1 <= idx <= facts.CAPACITY["main"]:
                r.add(SEVERITY_ERROR, "value.main-index-out-of-range", f"channels[{name}].main_routes",
                      f"Main {idx!r} does not exist -- a {facts.CONSOLE_MODEL} has Main 1..{facts.CAPACITY['main']}")

        # `bank` is the strip class here, and it is
        # load-bearing: a `ch` low band takes PEQ/SHV, an `aux` one also
        # takes CUT, and the schema above them both had to allow either.
        _check_eq(proc.get("eq"), ch.get("bank") or "ch", f"channels[{name}].processing", r)
        _check_presend_eq(proc.get("presend_eq"), ch.get("bank") or "ch",
                          f"channels[{name}].processing", r)

    for bus_name, bus in (plan.get("busses") or {}).items():
        bus_proc = bus.get("processing") or {}
        _check_eq(bus_proc.get("eq"), "bus", f"busses[{bus_name}].processing", r)

    for out_name, out in (plan.get("outputs") or {}).items():
        out_proc = out.get("processing") or {}
        strip = facts.OUTPUT_KIND_TO_EQ_STRIP.get(out.get("kind"))
        if strip is None:
            # An output that never says whether it is a Main or a Matrix
            # has no internal strip to put an EQ on. apply.py already
            # refuses to guess one from the name; the existing
            # output.unidentified finding covers the cause, so this adds
            # its consequence rather than a second diagnosis of it.
            if out_proc.get("eq") or out_proc.get("tilt_db") is not None:
                r.add(SEVERITY_WARNING, "value.eq-strip-unidentified", f"outputs[{out_name}].processing",
                      "states processing, but the plan never says whether this output is a Main or a "
                      "Matrix (kind+index) -- there is no strip to write it to")
            continue
        _check_eq(out_proc.get("eq"), strip, f"outputs[{out_name}].processing", r)


# --------------------------------------------------------------------------
# referential integrity + object capacity
# --------------------------------------------------------------------------

def _check_references(plan: dict, r: VerifyResult, console_model: str | None) -> None:
    dcas = plan.get("dcas") or {}
    mgrps = plan.get("mute_groups") or {}
    busses = plan.get("busses") or {}
    # Every claim on a physical output socket, gathered across
    # both kinds of object that can make one -- a bus with a
    # dedicated_output destination, and an `outputs` entry (Main, Matrix)
    # -- and reported together once both have been walked, by
    # `_report_output_socket_collisions` at the bottom of this function.
    output_claims: dict[tuple[str, int], list[str]] = {}

    for label, declared, cap_key in (
        ("DCA", dcas, "dca"),
        ("mute group", mgrps, "mgrp"),
        ("bus", busses, "bus"),
    ):
        cap = facts.CAPACITY[cap_key]
        if len(declared) > cap:
            r.add(SEVERITY_ERROR, "capacity.exceeded", f"plan.{cap_key}",
                  f"plan declares {len(declared)} {label}s -- a {facts.CONSOLE_MODEL} has {cap}")

    # Every name that actually joins a DCA/mute-group, from either kind of
    # member -- a channel (always could) or a bus (real shows
    # put busses in mute groups, e.g. Festival_STANDALONE.snap's MONITORS).
    # Tracked here rather than left to apply.py, so "this group does
    # nothing" is visible before anything is written, not discovered at
    # the desk.
    dca_members: dict[str, int] = {}
    mgrp_members: dict[str, int] = {}

    for ch in plan["channels"]:
        name = ch.get("name", "")
        for label, declared, key, members in (
            ("DCA", dcas, "dca", dca_members),
            ("mute group", mgrps, "mute_group", mgrp_members),
        ):
            for member in ch.get(key) or []:
                if member not in declared:
                    r.add(SEVERITY_ERROR, "reference.dangling", f"channels[{name}].{key}",
                          f"joins {label} {member!r}, which the plan never declares")
                else:
                    members[member] = members.get(member, 0) + 1
        for send in ch.get("bus_sends") or []:
            if send.get("bus") not in busses:
                r.add(SEVERITY_ERROR, "reference.dangling", f"channels[{name}].bus_sends",
                      f"sends to bus {send.get('bus')!r}, which the plan never declares")

    for bus_name, bus in busses.items():
        where = f"busses[{bus_name}]"
        # A bus can state BOTH a main route AND a dedicated
        # output at once (Festival_STANDALONE.snap's VOCALS bus) --
        # `destinations` (plural) is authoritative when non-empty;
        # `destination` (singular) covers an older/generated plan that
        # only ever set the one.
        destinations = (bus or {}).get("destinations")
        if not destinations:
            single = (bus or {}).get("destination")
            destinations = [single] if single is not None else []
        # A bus that sends on to another bus or a Matrix
        # feeds something, even with no destination of its own.
        if not destinations and not (bus or {}).get("bus_sends") \
                and not (bus or {}).get("matrix_sends"):
            r.add(SEVERITY_ERROR, "bus.no-destination", where,
                  "bus feeds nothing -- every channel sent to it would be inaudible")
        for i, dest in enumerate(destinations):
            dwhere = where if len(destinations) == 1 else f"{where}.destinations[{i}]"
            if dest.get("type") == "main":
                pass
            elif dest.get("type") == "matrix":
                # Legal per the schema, but this is the wrong field for it: a
                # bus's own `destination` is its exclusive physical/Main
                # routing, while feeding a Matrix is a non-exclusive SEND
                # (confirmed: /bus/{n}/send/MX{m}), the same shape as this
                # bus's own bus_sends. That's expressed on the MATRIX's own
                # outputs entry (outputs[name].fed_by), not here --
                # apply.py has no write path for a bus DESTINATION of type
                # "matrix" and never will, since it doesn't match how the
                # hardware is actually wired.
                r.add(SEVERITY_WARNING, "bus.matrix-destination-unsupported", dwhere,
                      "destination is 'matrix' -- not how a Matrix feed is expressed; state it on the "
                      "matrix's own outputs[name].fed_by instead. This bus's own fader/mute "
                      "still applies")
            else:
                # A dedicated output can itself fan out to
                # several physical sockets -- `patches` (plural) is
                # authoritative when non-empty; `patch` (singular)
                # covers a plan that only set the one. plan_compat also
                # reads the older `sockets`/`socket` spelling.
                sockets = plan_compat.output_patches(dest)
                if not sockets:
                    r.add(SEVERITY_ERROR, "bus.unresolved-destination", dwhere,
                          f"destination is {dest.get('type')!r} but no physical socket was resolved")
                # An unstated width on a bus feeding a dedicated output
                # used to be refused here (`bus.unstated-width-for-
                # dedicated-output`, 2026-09-19): apply wrote
                # /bus/{n}/busmono only when stated, so the jack's signal
                # depended on whatever width the desk had. Retired
                # 2026-09-25 under the judgement-vs-patching rule:
                # the width is now always DECIDED -- by the generator, or
                # by `inferred.bus_width_fallback` from the socket count --
                # and apply always writes it. `_check_inferred` reports
                # the decision as an INFO instead.
                for socket in sockets:
                    _check_output_socket(socket, dwhere, r, console_model, output_claims)

        for label, declared, key, members in (
            ("DCA", dcas, "dca", dca_members),
            ("mute group", mgrps, "mute_group", mgrp_members),
        ):
            for member in (bus or {}).get(key) or []:
                if member not in declared:
                    r.add(SEVERITY_ERROR, "reference.dangling", f"{where}.{key}",
                          f"joins {label} {member!r}, which the plan never declares")
                else:
                    members[member] = members.get(member, 0) + 1

    # FR-6.2's deterministic half: something declared that nothing uses.
    # INFO, not WARNING (2026-09-25, the judgement rule): an empty
    # DCA, mute group or bus is a desk in working order that carries one
    # object too many -- usually a convention written for a band this
    # input list does not have. It says so; it never blocks.
    for label, declared, members in (("DCA", dcas, dca_members), ("mute group", mgrps, mgrp_members)):
        for name in declared:
            if members.get(name, 0) == 0:
                r.add(Severity.INFO, "group.empty", f"plan.{'dcas' if label == 'DCA' else 'mute_groups'}[{name}]",
                      f"{label} {name!r} is declared but no channel or bus joins it -- it does nothing",
                      fix="drop it from the conventions for shows like this one, or give it members")

    fed = {send.get("bus") for ch in plan["channels"] for send in (ch.get("bus_sends") or [])
           if isinstance(send, dict)}
    for bus_name in busses:
        if bus_name not in fed:
            r.add(Severity.INFO, "bus.empty", f"busses[{bus_name}]",
                  f"bus {bus_name!r} is declared but no channel sends to it -- it carries silence",
                  fix="drop it from the conventions for shows like this one, or send something to it")

    outputs = plan.get("outputs") or {}

    # A Main has no routing table of its own on real hardware --
    # its only way out to a physical socket besides its own `patch` field
    # is a SEND into a Matrix, expressed on the MATRIX's own `fed_by`, not
    # on the Main. So a Main with no socket of its own isn't stranded if
    # some other output is a Matrix fed_by this exact Main index AND that
    # Matrix itself resolves to a real socket -- that IS the signal
    # reaching a physical output, just one hop further along than this
    # entry. Resolved before the loop below so order in the dict doesn't
    # matter.
    main_indices_reached_via_a_matrix = set()
    for out in outputs.values():
        out = out or {}
        fed_by = out.get("fed_by") or {}
        has_socket = bool(plan_compat.output_patches(out))
        if out.get("kind") == "matrix" and fed_by.get("type") == "main" and has_socket:
            main_indices_reached_via_a_matrix.add(fed_by.get("index"))
    # The same, for a Main's own `matrix_sends`.
    for out in outputs.values():
        if not isinstance(out, dict) or out.get("kind") != "main":
            continue
        for send in out.get("matrix_sends") or []:
            target = outputs.get(send.get("matrix")) if isinstance(send, dict) else None
            if isinstance(target, dict) and plan_compat.output_patches(target):
                main_indices_reached_via_a_matrix.add(out.get("index"))

    for out_name, out in outputs.items():
        where = f"outputs[{out_name}]"
        # A Main/Matrix can fan out to several physical sockets
        # at once -- `patches` (plural) is authoritative when non-empty;
        # `patch` (singular) covers a plan that only ever set the one, and
        # plan_compat reads the older `sockets`/`socket` spelling.
        sockets = plan_compat.output_patches(out)
        if not sockets:
            reached = ((out or {}).get("kind") == "main"
                       and (out or {}).get("index") in main_indices_reached_via_a_matrix)
            if not reached:
                # `output.no-socket`: what is missing is
                # the patch -- the link to a socket -- not the socket.
                #
                # A WARNING, not an ERROR: an
                # unpatched Main or Matrix is a working desk state. Apply
                # still writes its fader, mute, processing and what feeds
                # it (`fed_by`); it skips only the `/io/out/...` routing. A
                # Matrix used inside the desk -- the phones or monitor
                # source -- is meant to have no socket. The socket itself
                # is still never guessed: where a cable is plugged in is
                # not a convention.
                kind = (out or {}).get("kind")
                message = ("nothing is patched from this output to a physical socket -- apply "
                           "sets it up (its feed, level and processing) but routes it to no "
                           "output socket")
                if kind == "matrix":
                    message += (" -- right when the Matrix is used inside the desk, for example "
                                "as the phones or monitor source")
                fix = "state a \"patch\" for it if it should reach a socket"
                # A Main with no `index` cannot be matched to a Matrix fed
                # from "Main N" -- the real cause, when one exists. `build`
                # fills the index (allocate, INFO `inferred.output-index`);
                # a plan that reaches verify without one was not built, or
                # was edited since, so say which field is missing.
                if (kind == "main" and "index" not in (out or {})
                        and main_indices_reached_via_a_matrix):
                    fed = ", ".join(f"Main {i}" for i in
                                    sorted(i for i in main_indices_reached_via_a_matrix
                                           if isinstance(i, int)))
                    message += (f" -- and it states no \"index\", so it cannot be matched to the "
                                f"Matrix fed from {fed}, which would otherwise carry it to a socket")
                    fix = ("give this Main its \"index\" (the Main number the Matrix's fed_by "
                           "names), or rebuild -- build numbers an unnumbered Main itself")
                r.add(SEVERITY_WARNING, "output.no-patch", where, message, fix=fix)
        else:
            for socket in sockets:
                _check_output_socket(socket, where, r, console_model, output_claims)

        # What feeds this Matrix -- a Main or a bus, dangling
        # exactly like a channel's bus_sends above (a bus name that
        # doesn't exist in this plan is not applyable, whichever field
        # named it).
        fed_by = (out or {}).get("fed_by")
        if (out or {}).get("kind") == "matrix" and fed_by is not None:
            if fed_by.get("type") == "bus" and fed_by.get("name") not in busses:
                r.add(SEVERITY_ERROR, "reference.dangling", f"{where}.fed_by",
                      f"fed by bus {fed_by.get('name')!r}, which the plan never declares")

    _check_direct_outputs(plan, r, console_model, output_claims)
    _report_output_socket_collisions(output_claims, r, console_model)
    _report_output_index_duplicates(outputs, r)


def _check_direct_outputs(plan: dict, r: VerifyResult, console_model: str | None,
                          claims: dict[tuple[str, int], list[str]]) -> None:
    """`direct_outputs`: the sockets fed straight from a source, not a bus,
    Main or Matrix -- the splits and recording feeds a capture records, and
    Apply writes. Each socket must exist and is claimed like
    any output's, so one a bus, a Main or a Matrix also patches is
    `output.socket-collision`, naming both. Its source must be one the
    desk's output routing offers, at a number that exists: a physical
    group's own count, as for an input patch, or the routing's 1..64."""
    for entry in plan.get("direct_outputs") or []:
        if not isinstance(entry, dict):
            continue
        group, sock, source = entry.get("group"), entry.get("socket"), entry.get("source") or {}
        socket = (format_socket(group, sock) if isinstance(group, str) else f"{group} {sock}")
        where = f"direct_outputs[{socket}]"
        _check_output_socket({"group": group, "sockets": [sock]}, where, r, console_model, claims)
        source_group, index = source.get("group"), source.get("index")
        if source_group not in facts.OUTPUT_SOURCE_GROUPS or source_group == "OFF":
            offered = ", ".join(g for g in facts.OUTPUT_SOURCE_GROUPS if g != "OFF")
            r.add(SEVERITY_ERROR, "direct-output.unknown-source", where,
                  f"{socket} is fed from {source_group!r}, which the desk's output routing "
                  f"does not offer -- it offers {offered}")
            continue
        if source_group in facts.INPUT_SOCKETS:
            try:
                limit = facts.input_socket_limit(source_group, console_model)
            except facts.UnknownConsoleModel:
                limit = facts.INPUT_SOCKETS[source_group]
            what = f"{format_socket(source_group, 1)[:-2]} inputs are 1..{limit}"
        else:
            limit = facts.OUTPUT_SOURCE_INDEX_MAX
            what = f"the routing numbers {source_group} 1..{limit}"
        if (not isinstance(index, int) or isinstance(index, bool)
                or not 1 <= index <= limit):
            r.add(SEVERITY_ERROR, "direct-output.source-out-of-range", where,
                  f"{socket} is fed from {format_socket(source_group, index)}, which does not "
                  f"exist -- {what}")


def _report_output_index_duplicates(outputs: dict, r: VerifyResult) -> None:
    """Two outputs of one kind stating one `index` (review 2026-09-28, R2).

    One Main is one mix: `FOH` and `Broadcast` both at Main 2 means apply
    patches both socket pairs from Main 2 and writes `/main/2/fdr` twice,
    and whatever the plan meant for the other Main never reaches a jack.
    That is a physical setting that cannot work, so it is an
    error, naming every output that claims the slot. The mirror of
    `output.socket-collision`, which is two sources on one socket.
    """
    holders: dict[tuple[str, int], list[str]] = {}
    for name, out in outputs.items():
        if not isinstance(out, dict) or out.get("kind") not in ("main", "matrix"):
            continue
        index = out.get("index")
        if isinstance(index, int) and not isinstance(index, bool):
            holders.setdefault((out["kind"], index), []).append(name)
    for (kind, index), names in sorted(holders.items()):
        if len(names) < 2:
            continue
        label = "Main" if kind == "main" else "Matrix"
        named = ", ".join(repr(n) for n in names)
        r.add(SEVERITY_ERROR, "output.index-duplicated", f"outputs[{names[1]}]",
              f"{len(names)} outputs state {label} {index} -- {named} -- and one {label} is one "
              f"mix. Apply would patch every one of them from {label} {index}, so what the plan "
              f"meant for the other {label} never reaches a jack",
              fix=f"give each its own {label} number, or drop the \"index\" from all but one "
                  "and rebuild -- build numbers an unnumbered output from the free slots")


def _check_output_socket(socket: dict, where: str, r: VerifyResult,
                         console_model: str | None,
                         claims: dict[tuple[str, int], list[str]] | None = None) -> None:
    """Check one physical output socket spec, and record what claims it.

    `claims` maps (group, socket number) -> the `where` of every object
    that routes to it. Only sockets that actually exist are recorded --
    an out-of-range one is already reported below and adding it here
    would say the same wrong thing twice.
    """
    group = socket.get("group")
    if group not in facts.OUTPUT_SOCKETS:
        r.add(SEVERITY_ERROR, "output.unknown-group", where,
              f"output group {group!r} does not exist -- known output groups: "
              f"{', '.join(sorted(facts.OUTPUT_SOCKETS))}")
        return
    # Apply.py resolves each physical socket's `/in` value from
    # its POSITION in this list (position 0 = the source's own "L"/mono
    # channel slot, position 1 = "R") -- a third socket here has no slot
    # left to mean anything and would silently land on the NEXT bus/Main/
    # Matrix's own L slot instead, exactly the kind of wrong-jack routing
    # this whole issue was about.
    n_sockets = len(socket.get("sockets") or [])
    if n_sockets > 2:
        r.add(SEVERITY_ERROR, "output.too-many-sockets-for-one-source", where,
              f"{n_sockets} physical sockets stated for one source -- a source has at most an L and an "
              "R channel (2 sockets); a third has no channel of its own to carry and would collide with "
              "the next bus/Main/Matrix's own routing")
    if console_model is None:
        # No model, no panel bound -- verify_plan has already reported that
        # once; silently re-reporting it per socket would bury it. Two
        # objects on one socket is a collision whatever the model is,
        # though, so the claims are still worth recording.
        if claims is not None:
            for n in socket.get("sockets") or []:
                if isinstance(n, int) and not isinstance(n, bool):
                    claims.setdefault((group, n), []).append(where)
        return
    limit = facts.output_socket_limit(group, console_model)
    in_limit = facts.input_socket_limit(group, console_model)
    model_label = facts.CONSOLE_MODELS[console_model]["label"]
    for n in socket.get("sockets") or []:
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= limit:
            r.add(SEVERITY_ERROR, "output.socket-out-of-range", where,
                  (f"{group} output {n} does not exist -- the {model_label} has no {group} "
                   f"outputs at all" if limit == 0 else
                   f"{group} output {n} does not exist -- {group} outputs are 1..{limit} on a "
                   f"{model_label}")
                  + (f" (note {group} has {in_limit} INPUTS but only {limit} outputs)"
                     if in_limit > limit else ""))
        elif claims is not None:
            claims.setdefault((group, n), []).append(where)


def _report_output_socket_collisions(claims: dict[tuple[str, int], list[str]],
                                     r: VerifyResult,
                                     console_model: str | None) -> None:
    """One physical output socket carries one source.

    The socket-existence check above is half of a physical fact; this is
    the other half. `apply` writes each claimant's routing to
    `/io/out/{GROUP}/{n}` in turn, so two objects on one XLR is not a
    shared feed -- it is the last write winning and the other object
    going silently dead, discovered at soundcheck when a wedge or a
    broadcast feed has nothing in it. An engineer cannot resolve that by
    preference (there is no second jack to prefer), so, because
    a physical setting that cannot work is an error, this is an ERROR,
    not a warning.

    Both claimants are named, because "LCL 7 is taken" without saying by
    what sends someone hunting through the plan. When the group has no
    free socket left, the message says so -- that is the sentence that
    tells an engineer to move the sends somewhere with room rather than
    shuffle within a group that is already full.

    Deliberately NOT mirrored on the input side. Sharing one physical
    INPUT between two channels is legitimate -- a split to a broadcast
    truck, one socket reused between festival acts -- and is already
    reported as advice, not refusal (`reconcile.duplicated-input` here,
    C002 on a live desk).
    """
    if not claims:
        return
    claimed_per_group: dict[str, set[int]] = {}
    for group, n in claims:
        claimed_per_group.setdefault(group, set()).add(n)

    # A stereo pair colliding with another stereo pair is ONE problem, not
    # two -- report it once, naming both sockets, rather than emitting the
    # same sentence per XLR.
    collisions: dict[tuple[str, tuple[str, ...]], list[int]] = {}
    for (group, n), holders in sorted(claims.items()):
        if len(holders) < 2:
            continue
        collisions.setdefault((group, tuple(holders)), []).append(n)

    for (group, holders), numbers in collisions.items():
        if len(holders) == 2:
            who = f"{holders[0]} and {holders[1]}"
        else:
            who = ", ".join(holders[:-1]) + f" and {holders[-1]}"
        if len(numbers) == 1:
            what = f"{group} output {numbers[0]} is"
        else:
            what = (f"{group} outputs " + ", ".join(str(n) for n in numbers[:-1])
                    + f" and {numbers[-1]} are")
        detail = (f"{what} claimed by {len(holders)} sources at once -- {who} -- and "
                  f"one physical socket carries one signal. Whichever of them apply writes last wins; "
                  f"the other is silently dead at the jack")
        try:
            limit = facts.output_socket_limit(group, console_model)
        except facts.UnknownConsoleModel:
            limit = None
        if limit:
            model_label = facts.CONSOLE_MODELS[console_model]["label"]
            free = sorted(set(range(1, limit + 1)) - claimed_per_group.get(group, set()))
            if not free:
                detail += (f". {group} has {limit} outputs on a {model_label} and all {limit} are "
                           f"claimed, so there is no free {group} socket to move one of them to")
                if group not in ("A", "B", "C"):
                    detail += (" -- the AES50 groups (A, B, C) have 48 outputs each, which is where "
                               "IEM and monitor sends usually live")
            else:
                shown = ", ".join(f"{group} {f}" for f in free[:6])
                detail += (f". {group} has {limit} outputs on a {model_label} and "
                           f"{len(free)} of them {'is' if len(free) == 1 else 'are'} still free "
                           f"({shown}{', ...' if len(free) > 6 else ''}) -- move one of these "
                           f"claimants there")
        r.add(SEVERITY_ERROR, "output.socket-collision", holders[0], detail)


# --------------------------------------------------------------------------
# reconciliation with the input list -- the omission and invention checks
# --------------------------------------------------------------------------

def _check_send_references(plan: dict, r: VerifyResult) -> None:
    """The sends a plan states on a channel, a bus or a Main beyond a
    channel's `bus_sends`: each `matrix_sends` entry
    must name a Matrix the plan has, and each bus's `bus_sends` entry another
    bus it has. A send to something the plan does not have cannot be applied,
    exactly as a channel's send to an undeclared bus (`reference.dangling`).
    A bus sending to itself is not a route the desk has."""
    outputs = plan.get("outputs") or {}
    busses = plan.get("busses") or {}
    matrices = {name for name, out in outputs.items()
                if isinstance(out, dict) and out.get("kind") == "matrix"}

    def check(where: str, entry: dict, field: str, key: str, known: set, own: str | None = None):
        for i, send in enumerate((entry.get(field) or []) if isinstance(entry, dict) else []):
            target = send.get(key) if isinstance(send, dict) else None
            if target == own:
                r.add(SEVERITY_ERROR, "reference.dangling", f"{where}.{field}[{i}]",
                      f"bus {own!r} sends to itself, which is not a route the desk has")
            elif target not in known:
                kind = "Matrix" if key == "matrix" else "bus"
                r.add(SEVERITY_ERROR, "reference.dangling", f"{where}.{field}[{i}]",
                      f"send to {kind} {target!r}, which the plan never declares")

    for ch in plan.get("channels") or []:
        if isinstance(ch, dict):
            check(f"channels[{ch.get('name')}]", ch, "matrix_sends", "matrix", matrices)
    for name, bus in busses.items():
        check(f"busses[{name}]", bus, "bus_sends", "bus", set(busses), own=name)
        check(f"busses[{name}]", bus, "matrix_sends", "matrix", matrices)
    for name, out in outputs.items():
        if not isinstance(out, dict) or not out.get("matrix_sends"):
            continue
        if out.get("kind") != "main":
            r.add(SEVERITY_ERROR, "reference.dangling", f"outputs[{name}].matrix_sends",
                  f"only a Main sends to a Matrix; {name!r} is a {out.get('kind') or 'output'}")
            continue
        check(f"outputs[{name}]", out, "matrix_sends", "matrix", matrices)


def _check_channels_reach_an_output(plan: dict, r: VerifyResult) -> None:
    """A channel whose audio reaches no output
    (`routing.channel-reaches-nothing`, a WARNING): no route to a Main, no
    send into a monitor bus, and no send above -144 dB (-oo) into any
    other bus the plan declares.

    Haiku's smallband plan of 2026-09-29 built the Playback aux with none
    of these; nothing caught it but the critic. A WARNING, not an ERROR:
    the desk works, and a strip nobody hears may be deliberate -- a spare.

    A monitor bus (`inferred._is_monitor_bus`: a physical socket, no Main)
    is an output, since it goes to a wedge, and a send into one counts AT
    ANY LEVEL: the conventions start monitor sends all the way down and
    raise them at soundcheck, so a click track sent only to the monitors
    at -144 (festival's 'T Click/Guide') is routed, not lost. A send into
    a mix or FX bus counts when it is above -144 dB, or has no level
    (`null` is decided unity, `inferred.decide_send_level`). A bus that
    itself feeds nothing is `bus.no-destination`'s ERROR already, so it
    is not chased here."""
    from atoo.inferred import _is_monitor_bus

    busses = plan.get("busses") or {}

    def reaches(send) -> bool:
        if not isinstance(send, dict) or send.get("bus") not in busses:
            return False
        if _is_monitor_bus(busses[send["bus"]] or {}):
            return True
        level = send.get("level_db")
        return level is None or (isinstance(level, (int, float)) and level > facts.MINUS_INF_DB)

    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict) or ch.get("main_routes") or ch.get("matrix_sends"):
            # A send straight to a Matrix reaches an
            # output: a Matrix is one.
            continue
        sends = [s for s in ch.get("bus_sends") or [] if isinstance(s, dict)]
        if any(reaches(s) for s in sends):
            continue
        name = ch.get("name")
        strip = f"{ch.get('bank') or 'ch'} {ch.get('channel')} {name!r}"
        why = (f"its only sends ({', '.join(str(s.get('bus')) for s in sends)}) are all the way "
               "down (-144 dB)" if sends else "it sends to no bus")
        r.add(SEVERITY_WARNING, "routing.channel-reaches-nothing", f"channels[{name}]",
              f"{strip} reaches no output: it has no route to a Main, no monitor send, and "
              f"{why}, so nothing on it is heard",
              fix="route it to a Main or send it into a bus, or confirm it is meant to be "
                  "silent (a spare)")


# A strip the conventions keep off Main by name (`domain/knowledge.md`,
# "Playback and tracks": click and guide "must never be routed to the main
# mix, only to monitor busses"), and talkback, which goes to the stage and
# never the PA. Matched as a word in the channel name or its input, so
# festival's 'T Click/Gd' is one and 'Clicky Snare' is not.
_OFF_MAIN_BY_NAME = re.compile(
    r"(?<![a-z])(click|clk|guide|gd|talkback|talk ?back|tb|comms?)(?![a-z])", re.I)


def _stays_off_main(ch: dict) -> bool:
    source = ch.get("source") or {}
    return any(_OFF_MAIN_BY_NAME.search(str(text or ""))
               for text in (ch.get("name"), source.get("input")))


def _check_channels_reach_main(plan: dict, r: VerifyResult) -> None:
    """A channel whose audio reaches no Main
    (`routing.channel-misses-main`, a WARNING; 2026-09-29:
    routing is checked by code, not by the critic). A channel reaches a
    Main by a `main_routes` entry, or by an audible send -- above -144 dB,
    or `null`, decided unity -- into a bus whose destination is a Main.

    A bus counts when its destination is a Main, or when it sends (its own
    `bus_sends`) to a bus that does, however many buses
    along. A bus feeding only a Matrix does not count; a Matrix is an output,
    not the Main mix.

    Quiet for a click, guide or talkback strip, recognised by name
    (`_OFF_MAIN_BY_NAME`): the domain knowledge keeps click and guide off
    Main, and talkback belongs to the stage. Quiet too for a channel
    `routing.channel-reaches-nothing` already reports, which says more.
    A bus feeding a Main that nothing sends to is not a finding here."""
    busses = plan.get("busses") or {}

    def feeds_main(bus_name, seen=frozenset()) -> bool:
        bus = busses.get(bus_name) if isinstance(bus_name, str) else None
        if not isinstance(bus, dict) or bus_name in seen:
            return False
        dests = bus.get("destinations") or ([bus["destination"]] if bus.get("destination") else [])
        if any(isinstance(d, dict) and d.get("type") == "main" for d in dests):
            return True
        return any(isinstance(s, dict) and feeds_main(s.get("bus"), seen | {bus_name})
                   for s in bus.get("bus_sends") or [])

    def audible(send: dict) -> bool:
        level = send.get("level_db")
        return level is None or (isinstance(level, (int, float)) and level > facts.MINUS_INF_DB)

    reaches_nothing = {f.where for f in r.findings if f.code == "routing.channel-reaches-nothing"}
    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict) or ch.get("main_routes"):
            continue
        sends = [s for s in ch.get("bus_sends") or [] if isinstance(s, dict)]
        if any(feeds_main(s.get("bus")) and audible(s) for s in sends):
            continue
        name = ch.get("name")
        where = f"channels[{name}]"
        if where in reaches_nothing or _stays_off_main(ch):
            continue
        strip = f"{ch.get('bank') or 'ch'} {ch.get('channel')} {name!r}"
        to_main = [s for s in sends if feeds_main(s.get("bus"))]
        if to_main:
            why = (f"its sends into busses that feed a Main ("
                   f"{', '.join(str(s.get('bus')) for s in to_main)}) are all the way down (-144 dB)")
        else:
            why = (f"it sends only to busses that feed no Main "
                   f"({', '.join(str(s.get('bus')) for s in sends)})")
        r.add(SEVERITY_WARNING, "routing.channel-misses-main", where,
              f"{strip} reaches no Main: it has no Main route, and {why}, so it is not "
              f"in the front-of-house mix",
              fix="route it to a Main or send it into a bus that feeds one, or confirm it "
                  "is meant for the stage only")


def _unpatched_if_available(ch: dict) -> bool:
    """A strip the conventions or instructions ask for with a condition on
    its socket ("if available"), built unpatched because the socket was
    taken (`reply_expand.build_instructed_strips`)."""
    source = ch.get("source") if isinstance(ch.get("source"), dict) else {}
    return (ch.get("patch") is None and source.get("from") in ("conventions", "instructions")
            and bool(str(source.get("condition") or "").strip()))


def _socket_holders(plan: dict, rows) -> dict[tuple[str, int], list[str]]:
    """Every input socket, to what holds it: the input list's stated
    sockets (by row) and every channel's patch (by strip). A channel
    patched where its own row states is named once, by its row."""
    from atoo.input_list import parse_socket_spec

    held: dict[tuple[str, int], list[str]] = {}
    for row in rows or []:
        stated = parse_socket_spec(row.patch) if getattr(row, "patch", None) else None
        if stated:
            held.setdefault(stated, []).append(f"input list row {row.name!r}")
    for ch in plan.get("channels") or []:
        patch = ch.get("patch") if isinstance(ch, dict) else None
        if not isinstance(patch, dict):
            continue
        row = f"input list row {((ch.get('source') or {}).get('input'))!r}"
        for n in patch.get("sockets") or []:
            names = held.setdefault((patch.get("group"), n), [])
            if row not in names:
                names.append(f"{ch.get('bank') or 'ch'} {ch.get('channel')} {ch.get('name')!r}")
    return held


def _check_instructed(ch: dict, r: VerifyResult, layers, holders=None) -> None:
    """A channel that is not on the input list and says the conventions
    or instructions asked for it (`source.from`, `source.quote`; 2026-09-29,
    `instructed_channels.py`). Reported every time, so the
    engineer sees the one strip their list does not have
    (`reconcile.from-instructions`) -- at INFO when it was asked for
    explicitly, else as a WARNING (`_explicitly_requested`; 2026-10-11). The quote is checked against the
    texts, the way the critic's are: one that is not there, or that states
    no socket, is invention -- `reconcile.invented-source`, an ERROR. A
    patch other than the stated socket is `patch.contradicts-instructions`.
    With no texts to check against, the WARNING says the quote was not
    checked, as `reconcile.not-checked` does for a missing input list."""
    from atoo import instructed_channels as ic

    source = ch.get("source") or {}
    name = ch.get("name")
    where = f"channels[{name}]"
    quote = str(source.get("quote") or "").strip()
    role = source.get("from")
    strip = f"{ch.get('bank') or 'ch'} {ch.get('channel')} {name!r}"
    if not quote:
        r.add(SEVERITY_ERROR, "reconcile.invented-source", where,
              f"{strip} is not on the input list and says the {role} asked for it, but quotes "
              "nothing -- the plan invented an input that nobody is going to plug in")
        return
    layer = ic.find(quote, layers) if layers else None
    if layers and layer is None:
        r.add(SEVERITY_ERROR, "reconcile.invented-source", where,
              f"{strip} is not on the input list, and the {role} it quotes ({quote!r}) do not "
              "say that -- the plan invented an input that nobody is going to plug in",
              fix="add it to the input list, or state it in the instructions with its socket")
        return
    # Stated in the quote, or in the line of the text it was quoted from.
    stated = ic.sockets_for(quote, layer)
    if not stated:
        r.add(SEVERITY_ERROR, "reconcile.invented-source", where,
              f"{strip} is not on the input list, and {quote!r} states no source socket for it "
              "-- a channel asked for in words is built only when its socket is stated",
              fix="state its socket in the instructions (e.g. 'source A 40'), or add it to "
                  "the input list")
        return
    said = f"{layer.name} says" if layer is not None else f"the {role} say"
    checked = "" if layer is not None else (
        ". The quote was not checked: no conventions or instructions were given to verify it "
        "against -- verify the bundle the plan was built in (--show)")
    if ch.get("patch") is None and _unpatched_if_available(ch):
        # Asked for "if available", and its socket was taken: built
        # unpatched, on purpose (`reply_expand.build_instructed_strips`).
        taken = "; ".join(f"{format_socket(*s)} is taken by {', '.join(holders[s])}"
                          for s in stated if holders and holders.get(s)) or \
            "its socket was taken when it was built"
        r.add(SEVERITY_WARNING, "reconcile.from-instructions", where,
              f"{strip} is not on the input list; built because {said} {quote!r}{checked}. "
              f"Left unpatched ({source.get('condition')}): {taken}",
              fix="confirm it is wanted, and patch it at soundcheck, or free the socket")
        return
    patch = ch.get("patch") or {}
    first = (patch.get("sockets") or [None])[0]
    if (patch.get("group"), first) not in stated:
        r.add(SEVERITY_ERROR, "patch.contradicts-instructions", f"{where}.patch",
              f"plan patches {name!r} to {patch.get('group')} {patch.get('sockets')}, but the "
              f"{role} it is built from state "
              + ", ".join(format_socket(*s) for s in stated) + f": {quote!r}")
    # Its stated socket held by something else: a physical conflict
    # (2026-10-01). A strip asked for "if available" would have been left
    # unpatched; this one was asked for outright, so the plan cannot stand.
    me = f"{ch.get('bank') or 'ch'} {ch.get('channel')} {name!r}"
    for n in patch.get("sockets") or []:
        others = [h for h in (holders or {}).get((patch.get("group"), n), []) if h != me]
        if others:
            r.add(SEVERITY_ERROR, "reconcile.instructed-conflict", f"{where}.patch",
                  f"{strip} is built because {said} {quote!r}, on "
                  f"{format_socket(patch.get('group'), n)} -- which is taken by "
                  f"{', '.join(others)}. Two sources cannot come from one socket",
                  fix="move one of them in the input list or the conventions, or say "
                      "\"if available\" in the conventions so the strip is built unpatched")
    conflicted = any(h != me for n in patch.get("sockets") or []
                     for h in (holders or {}).get((patch.get("group"), n), []))
    if (not conflicted and (patch.get("group"), first) in stated
            and _explicitly_requested(quote, layer)):
        socks = patch.get("sockets") or []
        at = format_socket(patch.get("group"), first) + (
            f"-{socks[-1]}" if len(socks) > 1 else "")
        r.add(Severity.INFO, "reconcile.from-instructions", where,
              f"{strip} is not on the input list; built because {said} {quote!r}, "
              f"on {at} as it states")
        return
    r.add(SEVERITY_WARNING, "reconcile.from-instructions", where,
          f"{strip} is not on the input list; built because {said} {quote!r}{checked}",
          fix="confirm it is wanted, or add it to the input list")


def _explicitly_requested(quote: str, layer) -> bool:
    """Whether an instructed strip was asked for in so many words, which
    makes `reconcile.from-instructions` an INFO rather than a WARNING.

    The rule (2026-10-11): downgrade reconcile.from-instructions
    to INFO when the instructions quote the strip verbatim and state its
    socket; keep it a WARNING when the strip was inferred, paraphrased or
    has no stated socket. So all of:

    - the quote was checked and found in the engineer's own text -- the
      conventions or a show's instructions as written, not the model's
      restatement of them in the resolved conventions (`layer.resolved`,
      a paraphrase), and not unchecked for want of a text;
    - it is the request itself, verbatim: at least `MIN_QUOTE_WORDS`
      words of it (a short fragment is found only as a whole line, and
      does not vouch for a strip on its own);
    - the quote itself states the socket, not merely the line it came
      from.

    The caller adds the rest: the plan patches the stated socket, and no
    other source holds it. A strip built unpatched ("if available", its
    socket taken) stays a WARNING before it gets here."""
    from atoo import instructed_channels as ic
    if layer is None or getattr(layer, "resolved", False):
        return False
    core = ic.clean_quote(quote)
    if len(core.split()) < ic.MIN_QUOTE_WORDS:
        return False
    return bool(ic.stated_sockets(core))


def _unassigned_because(entry: dict, row: InputRow, layers) -> str:
    """The clause naming why a row was left out: its quote, and whether
    the quote was found -- in the conventions, the instructions or the
    row's own notes (`reply_expand.build_left_out_rows` checks the same)."""
    from atoo import instructed_channels as ic
    from atoo.reply_expand import _unassigned_quote_layers

    quote = str(entry.get("quote") or "").strip()
    if not quote:
        return ""
    said = {"input list": "its notes"}.get(entry.get("from"), f"the {entry.get('from') or 'text'}")
    if ic.find(quote, _unassigned_quote_layers(row, layers)) is not None:
        return f", because {said} say {quote!r}"
    if layers is None and entry.get("from") != "input list":
        return (f", because {said} say {quote!r} (not checked: no conventions or instructions "
                "were given)")
    return f", quoting {quote!r} -- which is not in the conventions, the instructions or its notes"


def rows_for_a_change(plan: dict, rows: list[InputRow], *, changed=()
                      ) -> "tuple[InputRows, list[str], list[str]]":
    """The input list as a typed change can be held to it; the names of the
    plan's channels the list does not have; and the names of channels whose
    socket the change states against a different one on the list.

    A full build is held to the whole list: every row became a channel and
    no channel came from nowhere. A change is not a rebuild. The channel it
    adds is not on the list, nor is one a previous change added, and a row
    the plan has no channel for is simply a row the show has not used yet --
    calling either "invented" or "dropped" would refuse a change for being
    one. So the list is cut down to the rows the plan's channels name, and
    each channel the list lacks gets a stand-in row of its own, which leaves
    everything else the list says to check: a stated socket the plan
    disagrees with, a stated preset, two channels from one row, phantom power
    against the microphone. A channel built from a row the list has since
    skipped still reads as that, not as a stand-in.

    `changed` names the channels the change adds or repatches. The socket
    the change states for one stands over the socket the list states for the
    same row (the list is what the change is correcting at short notice), so
    that row is checked without its `patch` rather than refused for
    disagreeing; the third result names those.
    """
    by_norm = {_norm(row.name): row for row in rows}
    skipped = {_norm(row.name) for row in getattr(rows, "skipped", None) or ()}
    kept: dict[str, InputRow] = {}
    stand_ins: list[str] = []
    set_aside: list[str] = []
    changed = set(changed)
    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        source = ch.get("source") or {}
        for raw in (source.get("input") or ch.get("name"), source.get("pair_input")):
            if not raw:
                continue
            key = _norm(raw)
            if key in by_norm:
                row = by_norm[key]
                if ch.get("name") in changed and row.patch:
                    stated = _parse_socket_spec(row.patch)
                    here = ch.get("patch") or {}
                    if stated is None or stated[0] != here.get("group") \
                            or stated[1] not in (here.get("sockets") or []):
                        set_aside.append(str(ch.get("name")))
                    row = replace(row, patch="")
                kept.setdefault(key, row)
            elif key not in skipped and key not in kept:
                kept[key] = InputRow(name=str(raw), category=str(ch.get("category") or ""),
                                     type=str(source.get("type") or ""),
                                     phantom=bool(source.get("phantom")))
                stand_ins.append(str(ch.get("name") or raw))
    cut = InputRows(kept.values())
    cut.skipped = list(getattr(rows, "skipped", None) or [])
    return cut, stand_ins, set_aside


def _check_reconciliation(plan: dict, rows: list[InputRow], r: VerifyResult,
                          layers=None) -> None:
    """The check the whole experiment turns on.

    A wrong fader value shows up in the plan diff and a human catches it. A
    channel that silently isn't in the plan is invisible until sound check,
    when a musician is standing at a dead microphone. So: every input list
    row must be accounted for, explicitly, and nothing may appear that the
    input list never mentioned.
    """
    by_norm = {_norm(row.name): row for row in rows}
    # Rows `-` in the `order` column left out (FR-1.1): not on the list
    # as far as a build is concerned. A channel for one is a plan built
    # before the row was skipped -- a WARNING, not an ERROR (2026-10-10; an
    # error of judgement is not an error of patching): the desk still works, it just
    # builds a strip for an input
    # nobody will plug in, and the plan already reads Stale.
    skipped = {_norm(row.name) for row in getattr(rows, "skipped", None) or ()}
    claimed: dict[str, list[str]] = {}
    holders = _socket_holders(plan, rows)

    def skipped_source(ch, raw) -> None:
        r.add(SEVERITY_WARNING, "reconcile.skipped-source", f"channels[{ch.get('name')}]",
              f"source {raw!r} is skipped on the input list ('-' in its order cell), but this "
              "plan builds a channel for it -- it was built before the row was skipped",
              fix="rebuild the plan to leave it out, or clear the '-' if this show uses it")

    for ch in plan["channels"]:
        source = ch.get("source") or {}
        raw = source.get("input") or ch.get("name") or ""
        key = _norm(raw)
        if key not in by_norm and source.get("from") in ("conventions", "instructions"):
            _check_instructed(ch, r, layers, holders)
            continue
        if key not in by_norm and key in skipped:
            skipped_source(ch, raw)
            continue
        if key not in by_norm:
            r.add(SEVERITY_ERROR, "reconcile.invented-source", f"channels[{ch.get('name')}]",
                  f"source {raw!r} is not on the input list -- the plan invented an input that "
                  "nobody is going to plug in")
            continue
        claimed.setdefault(key, []).append(str(ch.get("name")))

    # A stereo channel's `source.input` only ever names ONE half of the
    # pair -- WING convention (plan_schema.py) has a stereo channel's
    # patch reference just the first socket, and `source.input` mirrors
    # whichever input-list row that first socket came from. The SECOND
    # row it physically consumes is recorded nowhere on the channel by
    # name, only by socket -- so without this, that row always reads as
    # dropped, on every stereo channel any plan has ever produced (a real
    # hosted run: 'Keys R' flagged reconcile.dropped-input despite being
    # physically patched as the second half of the 'Keys' stereo
    # channel). Match by the input list's own stated socket, not by a
    # guessed naming convention (L/R, Left/Right, ...) -- the socket is
    # the one thing here that isn't ambiguous.
    #
    # Unless the plan names the second row outright: `source.pair_input`
    # (2026-09-29), written when a compact reply paired two rows. That is
    # the only record of a pair whose rows state no socket -- the
    # expander counted the sockets itself, so there is nothing on the
    # input list to match. A name that is not a row of the list is an
    # invented source, as for `source.input`.
    for ch in plan["channels"]:
        source = ch.get("source") or {}
        patch = ch.get("patch") or {}
        sockets = patch.get("sockets") or []
        if not source.get("stereo") or len(sockets) != 2:
            continue
        pair_input = source.get("pair_input")
        if pair_input:
            pair_key = _norm(pair_input)
            if pair_key not in by_norm and pair_key in skipped:
                skipped_source(ch, pair_input)
            elif pair_key not in by_norm:
                r.add(SEVERITY_ERROR, "reconcile.invented-source", f"channels[{ch.get('name')}]",
                      f"stereo pair's second input {pair_input!r} is not on the input list -- "
                      "the plan invented an input that nobody is going to plug in")
            elif str(ch.get("name")) not in claimed.get(pair_key, []):
                claimed.setdefault(pair_key, []).append(str(ch.get("name")))
            continue
        group = patch.get("group")
        for row in rows:
            key = _norm(row.name)
            if key in claimed or not row.patch:
                continue
            if _parse_socket_spec(row.patch) in ((group, sockets[0]), (group, sockets[1])):
                claimed.setdefault(key, []).append(str(ch.get("name")))

    # A bare name (every plan before 2026-09-29) or `{input, quote, from}`:
    # the words that said to leave the row out, shown with the warning.
    declared_unassigned: dict[str, dict] = {}
    for entry in plan.get("unassigned_inputs") or []:
        name = entry.get("input") if isinstance(entry, dict) else entry
        if isinstance(name, str) and name.strip():
            declared_unassigned[_norm(name)] = entry if isinstance(entry, dict) else {"input": name}

    for row in rows:
        key = _norm(row.name)
        where = f"input list[{row.name}]"
        holders = claimed.get(key, [])
        if not holders:
            if key in declared_unassigned:
                r.add(SEVERITY_WARNING, "reconcile.deliberately-unassigned", where,
                      "is on the input list and the plan declares it deliberately unassigned"
                      + _unassigned_because(declared_unassigned[key], row, layers)
                      + " -- confirm that is intended before the show")
            else:
                r.add(SEVERITY_ERROR, "reconcile.dropped-input", where,
                      f"appears on the input list ({row.category}) but no channel in the plan uses it, "
                      "and the plan does not declare it deliberately unassigned")
        elif len(holders) > 1:
            # A warning, not an error, since 2026-09-22. It said "one
            # physical source cannot be two channels", which is simply not
            # true: there can be a situation where we want
            # another channel strip to share the input but with different
            # processing, generally because that strip is sent
            # to monitors, or one physical socket is used
            # for two different instrument types during a festival.
            # `atoo/domain/knowledge.md` has both cases.
            #
            # Refusing it meant a monitor-split plan could never be
            # applied, which is the one outcome that is definitely wrong.
            # We still cannot tell from the plan alone whether the share
            # was ASKED FOR -- the rule is that a deliberate one is called
            # out in the input list or the instructions -- so the finding
            # stays, and says what to check.
            r.add(SEVERITY_WARNING, "reconcile.duplicated-input", where,
                  f"feeds {len(holders)} channels ({', '.join(holders)}). That is legitimate when "
                  "it was asked for -- a separate strip for monitors, or one socket reused between "
                  "acts -- and a mistake when it was not, so confirm the input list or the show's "
                  "instructions called for it. Either way the strips share one head amp, so gain "
                  "and phantom cannot differ between them")

    for name, entry in declared_unassigned.items():
        if name not in by_norm:
            r.add(SEVERITY_WARNING, "reconcile.unknown-unassigned", "plan.unassigned_inputs",
                  f"declares {entry.get('input')!r} unassigned, but it is not on the input list "
                  "either")


def _check_stated_sockets(plan: dict, rows: list[InputRow], r: VerifyResult) -> None:
    """An input list's `patch` column is a fact about this show -- which
    jack the cable is in. A plan is free to disagree only if it says so;
    disagreeing silently means the plan points at the wrong XLR."""
    by_norm = {_norm(row.name): row for row in rows}
    for ch in plan["channels"]:
        source = ch.get("source") or {}
        row = by_norm.get(_norm(source.get("input") or ch.get("name") or ""))
        if row is None or not row.patch:
            continue
        stated = _parse_socket_spec(row.patch)
        if stated is None:
            r.add(SEVERITY_WARNING, "patch.unparsable-stated-socket", f"input list[{row.name}]",
                  f"patch {row.patch!r} could not be read as '<group> <number>' -- the plan's patch "
                  "for this row could not be checked against it")
            continue
        group, n = stated
        patch = ch.get("patch") or {}
        if patch.get("group") != group or n not in (patch.get("sockets") or []):
            r.add(SEVERITY_ERROR, "patch.contradicts-input-list", f"channels[{ch.get('name')}].patch",
                  f"plan patches to {patch.get('group')} {patch.get('sockets')}, but the input list says "
                  f"{row.name!r} is cabled into {group} {n}")


def _check_stated_presets(plan: dict, rows: list[InputRow], r: VerifyResult) -> None:
    """The input list's `preset` column wins over the
    conventions and instructions, as a stated patch does -- `build` puts it
    on the channel (`reply_expand.apply_stated_presets`). A plan that
    names a different preset, or none, for a row that states one was
    edited by hand or built before the list said so.

    **A warning, not an error** -- unlike `patch.contradicts-input-list`.
    A preset is a judgement about how the strip sounds, not a physical
    setting that cannot work: the desk is in working order either way
    (an error of judgement is not an error of patching).

    A stereo pair's two rows naming different presets is said here too:
    the first row's wins (`input_list.stated_preset`), and the engineer
    should make them agree."""
    from atoo.input_list import rows_feeding, stated_preset
    from atoo.presets import normalize_preset_name

    for ch in plan["channels"]:
        if not isinstance(ch, dict):
            continue
        stated = stated_preset(rows_feeding(ch, rows))
        if stated is None:
            continue
        name, row, others = stated
        where = f"channels[{ch.get('name')}].processing.preset"
        if others:
            r.add(SEVERITY_WARNING, "preset.input-list-pair-disagrees", f"input list[{row.name}]",
                  f"the stereo pair's rows state different presets: {row.name!r} says {name!r}, "
                  + ", ".join(f"{o.name!r} says {o.preset!r}" for o in others)
                  + f" -- the first row's, {name!r}, is the channel's",
                  fix="give both rows of the pair the same preset")
        processing = ch.get("processing") if isinstance(ch.get("processing"), dict) else {}
        planned = processing.get("preset")
        if planned and normalize_preset_name(str(planned)) == normalize_preset_name(name):
            continue
        r.add(SEVERITY_WARNING, "preset.contradicts-input-list", where,
              (f"plan names the preset {planned!r}" if planned else "plan names no preset")
              + f", but the input list's preset column states {name!r} for {row.name!r} -- "
              "the list wins over the conventions, so this plan was edited by hand or built "
              "before the list said so",
              fix="rebuild, or set processing.preset to the list's value and run "
                  "`atoo presets --expand PLAN`")


def _check_captured_mix(plan: dict, r: VerifyResult) -> None:
    """A captured plan states no mix (`inferred.plan_states_the_mix`), and
    `apply` leaves it to the desk. Said once, at INFO, because
    on a built plan an unstated fader means unity and here it does not."""
    from atoo.inferred import plan_states_the_mix

    if not plan_states_the_mix(plan):
        r.add(Severity.INFO, "capture.mix-left-to-desk", "plan",
              "this plan was captured from a desk and states no faders, mutes or send "
              "levels: `atoo apply` leaves them as the desk has them, does not reset the "
              "desk to initialized and does not unpatch the strips it does not hold, so "
              "applied back to the desk it came from it changes nothing")


def _check_sheet_columns(plan: dict, rows: list[InputRow], r: VerifyResult) -> None:
    """The desk sheets' `channel`, `dca` and `mute_group` columns
    against the plan, wherever a row fills one.

    `atoo capture` writes them from the desk and a build places channels by
    them, and a Save in Build's step 04 carries them into the
    plan, so a plan made any of those ways agrees with them. Where a filled
    cell and the plan disagree, the plan was changed after it was made (an
    edit by hand, `atoo patch`) or the list after the plan, and the cell has
    had no effect: that is said, never left to look honoured. A WARNING, as
    `preset.contradicts-input-list` is: which strip and which DCA are
    judgements, and the desk works either way."""
    from atoo.input_list import rows_feeding

    for ch in plan["channels"]:
        if not isinstance(ch, dict):
            continue
        feeding = rows_feeding(ch, rows)
        if not feeding:
            continue
        row = feeding[0]
        where = f"channels[{ch.get('name')}]"
        said = []
        if row.channel is not None and row.channel != (ch.get("bank") or "ch", ch.get("channel")):
            bank, number = row.channel
            on = f"{'Aux ' if ch.get('bank') == 'aux' else ''}{ch.get('channel')}"
            said.append(f"puts {row.name} on channel {'Aux ' if bank == 'aux' else ''}"
                        f"{number}, but the plan has it on {on}")
        # Matched as the build matches a group, without case or extra spaces:
        # the list's `DRUMS` is the plan's `Drums` (the report).
        for column, word, cells, planned in (
                ("dca", "DCA", row.dca, ch.get("dca")),
                ("mute_group", "mute group", row.mute_group, ch.get("mute_group"))):
            planned = list(planned or [])
            if cells and sorted(map(_norm, cells)) != sorted(map(_norm, planned)):
                said.append(f"puts {row.name} in {word} {'; '.join(cells)}, but the plan has it "
                            f"in {'; '.join(planned) or f'no {word}'}")
        for text in said:
            r.add(SEVERITY_WARNING, "input-list.column-not-followed", where,
                  f"The input list {text}: the plan was changed after it was built, or the list "
                  "after the plan. Rebuild, or Save the input list in Build 04, to apply the "
                  "cell; or clear the cell if the plan is right")


# --------------------------------------------------------------------------
# domain safety -- the one class of finding that is about the physical world
# --------------------------------------------------------------------------

def _check_pair_phantom(plan: dict, r: VerifyResult) -> None:
    """A stereo channel states one 48V value for its pair. The desk switches
    the two sockets together, so a plan stating two different values
    (an older build, a hand edit) is read as on for both and reported here;
    it needs no input list to see."""
    for ch in plan["channels"]:
        if not inferred.pair_phantom_differs(ch):
            continue
        stated = inferred.stated_socket_phantom(ch)
        side = lambda on: "on" if on else "off"  # noqa: E731
        r.add(SEVERITY_WARNING, "phantom.pair-differs", f"channels[{ch.get('name')}]",
              f"the plan states 48V {side(stated[0][1])} for socket {stated[0][0]} and "
              f"{side(stated[1][1])} for socket {stated[1][0]}, but the desk switches a stereo "
              "channel's two sockets together -- apply writes 48V on both (on if either is). "
              "Rebuild (a build states one value for the pair), or split the pair into two "
              "mono channels")


def _check_safety(plan: dict, rows: list[InputRow], r: VerifyResult) -> None:
    by_norm = {_norm(row.name): row for row in rows}
    for ch in plan["channels"]:
        source = ch.get("source") or {}
        # The same lookup as `_check_reconciliation`: `source.input`, else
        # the channel's name (review 2026-09-28, R5). Matching by input
        # alone let a channel with `source.input: null` reconcile against
        # its row here and find no row -- so no model -- for this check.
        row = by_norm.get(_norm(source.get("input") or ch.get("name") or ""))
        stated_model = source.get("model") or (row.model if row else "") or ""
        model = _norm(stated_model)
        phantom = source.get("phantom")
        if phantom is None and row is not None:
            phantom = row.phantom
        where = f"channels[{ch.get('name')}]"
        # A stereo channel's two sockets switch 48V together on the desk,
        # so the pair has one value (`inferred.socket_phantom`: on if either
        # row wants it) and a passive ribbon on EITHER side meets it.
        pair_row = by_norm.get(_norm(source.get("pair_input") or ""))
        paired = len(inferred.socket_phantom(ch)) >= 2
        if paired:
            phantom = bool(phantom) or any(on for _socket, on in inferred.socket_phantom(ch))
        sides = [(stated_model, model, source.get("input") or ch.get("name"), "")]
        if pair_row is not None and paired:
            sides.append((pair_row.model, _norm(pair_row.model), pair_row.name,
                          ", the pair's second socket"))
        if not phantom:
            continue
        for shown, normal, row_name, role in sides:
            if not (normal and any(rb in normal for rb in PASSIVE_RIBBON_MODELS)):
                continue
            together = (" -- a stereo channel's two sockets switch 48V together, so the "
                        "pair takes it if either row wants it" if paired else "")
            mend = (". Split the pair into two mono channels, or set the other row to a "
                    "source that takes no 48V (phantom FALSE)" if paired else "")
            r.add(SEVERITY_ERROR, "safety.phantom-on-passive-ribbon", where,
                  f"{shown!r} ({row_name}{role}) is a passive ribbon microphone and the plan "
                  f"sends it phantom power{together} -- 48V destroys a ribbon element and "
                  f"undoing the setting does not undo the damage{mend}")


# --------------------------------------------------------------------------

def _check_presets(plan: dict, library, r: VerifyResult) -> None:
    """Report on every channel's preset: the values the plan carries
    from one, and a named preset the plan carries none of.

    **Warnings, not errors**: presets are strip
    settings that add detail to the patch, but it is not a blocker if the
    user chooses to ignore the warning. So nothing here ever stops an
    apply; it tells you what the strip will and will not get.

    Since slice B `build`
    EXPANDS a named preset into the plan (`processing.preset_values`), and
    `apply` writes those values without opening the library. So the two
    halves of this check ask different questions:

    - A channel that CARRIES values is self-contained: the library is not
      needed to apply it, so `preset.no-library` never fires for it. What
      is worth saying is what will be written (`preset.expanded`, one INFO
      for the plan), where the plan's own processing won
      (`preset.overridden`, INFO), any value `apply` will refuse
      (`preset.leaf-not-written`), values that came from a different
      preset than the one named (`preset.stale-expansion`), and -- when a
      library is given -- a library copy that changed since
      (`preset.library-changed`, INFO).
    - A channel that only NAMES a preset writes nothing from it. That is
      `preset.no-library` / `preset.unknown` as before, or
      `preset.not-expanded` when the library has it and the plan simply
      predates expansion.

    Note these presets are **Atoo's own** -- a directory of `.chn`
    exports this project reads -- and never the console's internal preset
    or scene mechanism, which cannot be driven remotely at all (D7).
    """
    from atoo import preset_expand
    from atoo.presets import PresetError

    channels = [c for c in plan.get("channels") or []
                if isinstance(c, dict) and isinstance(c.get("processing"), dict)]
    expanded = [c for c in channels if preset_expand.preset_values(c) is not None]
    named_only = [c for c in channels
                  if c["processing"].get("preset") and preset_expand.preset_values(c) is None]

    _check_expanded_presets(expanded, library, r)

    # Named by the strip's name: a number is ambiguous across banks, and
    # `channels[2]` on aux 2 (HOST) jumped to ch 2 (Snare) on the page.
    named = [(f"channels[{c.get('name') or c.get('channel', '?')}]", c["processing"]["preset"])
             for c in named_only]
    if not named:
        return

    if library is None:
        # One finding, not one per channel: the cause is single (no
        # library configured) and repeating it per strip buries it.
        unique = sorted({name for _, name in named})
        r.add(SEVERITY_WARNING, "preset.no-library", "plan",
              f"{len(named)} channel(s) name a preset ({', '.join(unique)}) but no preset "
              f"library is configured and the plan carries none of their values, so those "
              f"strips will be built without the processing those presets carry",
              fix="pass --presets DIR, or set [presets] default in ~/.atoo.config, and "
                  "rebuild (or run `atoo presets --expand` on the plan)")
        return

    try:
        available = [p.name for p in library]
    except PresetError as exc:
        r.add(SEVERITY_WARNING, "preset.unreadable-library", "plan",
              f"the preset library could not be read ({exc}), so no preset named in this "
              f"plan could be resolved")
        return

    for where, name in named:
        found = library.matches(name)
        if not found:
            # A few near names, not the whole library: a hundred names
            # in one warning filled the findings panel (2026-10-02).
            near = difflib.get_close_matches(name, available, n=5, cutoff=0.4)
            close = (f"Closest in the library: {', '.join(near)}" if near
                     else "Nothing in the library is close")
            r.add(SEVERITY_WARNING, "preset.unknown", where,
                  f"names the preset {name!r}, which is not in the library at "
                  f"{library.directory} ({len(available)} presets) -- that strip will be "
                  f"built without it. {close}",
                  fix="check the spelling, or add the preset to the library")
            continue
        if len(found) > 1:
            # Two files naming the same name is a Warning; pick
            # the newest one. Said out loud because picking silently is
            # how the wrong one gets applied for a month.
            others = ", ".join(str(p.source_path) for p in found[1:])
            r.add(SEVERITY_WARNING, "preset.ambiguous", where,
                  f"{len(found)} presets in {library.directory} are named {name!r} -- "
                  f"using the newest, {found[0].source_path}, ignoring {others}",
                  fix="give them distinct names, or remove the stale one")
        r.add(SEVERITY_WARNING, "preset.not-expanded", where,
              f"names the preset {name!r}, which the library has ({found[0].source_path.name}), "
              f"but the plan carries none of its values -- it was built before presets were "
              f"expanded into the plan, or without a library -- so nothing from it will be "
              f"written",
              fix="rebuild with the library, or run `atoo presets --expand PLAN`")


def _check_bus_presets(plan: dict, library, r: VerifyResult) -> None:
    """Every bus's preset and the effect it inserts.

    The preset half is the channel's (`_check_presets`), at WARNING: a bus
    preset is strip settings, and a missing one is a bus built without
    them. The EFFECT half is an ERROR only for what the desk cannot be put
    into (an error of patching, not of judgement):

    - `fx.unknown-model` -- a model no engine offers;
    - `fx.engine-not-offered` -- an engine that cannot hold the model (a
      reverb or delay on 9-16), or no engine of that number;
    - `fx.no-engine` -- more effects than engines that can hold them;
    - `fx.engine-shared` -- two inserts naming one engine: each would load
      its own model into it, and the second would replace the first;
    - `fx.value-not-offered` -- a parameter value the engine has no
      choice for.

    A parameter NAME the parameter map lacks is not an error: the map was
    walked with other models loaded, so it cannot say what V-REV has.
    Build announced those at INFO (`fx.parameter-typed-from-value`)."""
    from atoo import bus_presets, fx_engines
    from atoo.presets import PresetError

    busses = {n: e for n, e in (plan.get("busses") or {}).items() if isinstance(e, dict)}
    named_only = [(n, e) for n, e in busses.items()
                  if e.get("preset") and bus_presets.preset_values(e) is None]
    if named_only:
        if library is None:
            names = sorted({str(e["preset"]) for _, e in named_only})
            r.add(SEVERITY_WARNING, "preset.no-library", "plan",
                  f"{len(named_only)} bus(ses) name a bus preset ({', '.join(names)}) but no preset "
                  f"library is configured and the plan carries none of their values, so those "
                  f"busses will be built without their processing or effect",
                  fix="pass --presets DIR, or set [presets] default in ~/.atoo.config, and "
                      "rebuild (or run `atoo presets --expand` on the plan)")
        else:
            for name, entry in named_only:
                where = bus_presets.bus_where(name)
                try:
                    found = library.bus_matches(entry["preset"])
                    available = [p.name for p in library.bus_presets()]
                except PresetError as exc:
                    r.add(SEVERITY_WARNING, "preset.unreadable-library", where,
                          f"the preset library could not be read ({exc})")
                    continue
                if not found:
                    near = difflib.get_close_matches(entry["preset"], available, n=5, cutoff=0.4)
                    r.add(SEVERITY_WARNING, "preset.unknown", where,
                          f"names the bus preset {entry['preset']!r}, which is not in the library "
                          f"at {library.directory} ({len(available)} bus presets) -- that bus will "
                          f"be built without it. "
                          + (f"Closest: {', '.join(near)}" if near else "Nothing is close"),
                          fix="check the spelling, or export the bus preset from the desk as a "
                              ".bus file into the library")
                else:
                    r.add(SEVERITY_WARNING, "preset.not-expanded", where,
                          f"names the bus preset {entry['preset']!r}, which the library has "
                          f"({found[0].source_path.name}), but the plan carries none of its "
                          f"values, so neither its processing nor its effect will be written",
                          fix="rebuild with the library, or run `atoo presets --expand PLAN`")

    claims: dict[int, list[str]] = {}
    summary: list[str] = []
    processing: list[str] = []
    for name, entry in busses.items():
        values = bus_presets.preset_values(entry)
        if values is None:
            continue
        where = bus_presets.bus_where(name)
        preset = values.get("preset")
        if not bus_presets.expansion_matches_name(entry):
            r.add(SEVERITY_WARNING, "preset.stale-expansion", where,
                  f"carries values from the bus preset {preset!r} but "
                  + (f"names {entry.get('preset')!r}" if entry.get("preset") else "names none")
                  + " -- the values it carries are what will be written",
                  fix="rebuild, or run `atoo presets --expand PLAN`")
        leaves = values.get("leaves") if isinstance(values.get("leaves"), dict) else {}
        refused = []
        for address, value in leaves.items():
            why = bus_presets.leaf_refusal(address)
            if why is None:
                _, why = bus_presets.coerce_leaf(address, value)
            if why is not None:
                refused.append(f"{address} ({why})")
        if refused:
            r.add(SEVERITY_WARNING, "preset.leaf-not-written", where,
                  f"{len(refused)} of the bus preset {preset!r} values in this plan will not be "
                  f"written: " + "; ".join(refused))
        if len(leaves) > len(refused):
            processing.append(f"{name}: {preset!r} ({len(leaves) - len(refused)})")
        for ins in bus_presets.inserts(entry):
            owner = bus_presets.insert_owner(name, entry, ins.get("point"))
            model = ins.get("model")
            engine = ins.get("engine")
            if not fx_engines.is_known_model(model):
                r.add(SEVERITY_ERROR, "fx.unknown-model", where,
                      f"{owner}: the bus preset {preset!r} loads the effect {model!r}, which no FX "
                      f"engine on this desk offers",
                      fix="re-save the bus preset on the desk, or name another")
                continue
            legal = fx_engines.engines_for(model)
            if engine is None:
                r.add(SEVERITY_ERROR, "fx.no-engine", where,
                      f"{owner}: no FX engine is left for {model} -- every engine that can hold it "
                      f"({fx_engines.engine_range_text(legal)}) is taken by another bus in this "
                      f"plan, so it cannot be loaded",
                      fix="use fewer effects of this kind, or one that engines 9-16 can hold")
                continue
            if not isinstance(engine, int) or engine not in legal:
                what = (f"FX{engine} cannot hold {model} (only engines "
                        f"{fx_engines.engine_range_text(legal)} offer it)"
                        if isinstance(engine, int) and 1 <= engine <= 16
                        else f"there is no engine FX{engine}")
                r.add(SEVERITY_ERROR, "fx.engine-not-offered", where,
                      f"{owner}: {what}",
                      fix="rebuild, or run `atoo presets --expand PLAN`, to allocate it")
                continue
            claims.setdefault(engine, []).append(owner)
            bad = []
            for param, value in (ins.get("parameters") or {}).items():
                if not fx_engines.is_engine_parameter(param):
                    continue
                _, why, _ = fx_engines.coerce_param(param, value)
                if why is not None:
                    bad.append(f"{param}: {why}")
            if bad:
                r.add(SEVERITY_ERROR, "fx.value-not-offered", where,
                      f"{owner}: {len(bad)} of {model}'s parameter values cannot be set on the "
                      f"desk -- " + "; ".join(bad),
                      fix="re-save the bus preset on the desk")
            switched = " (saved bypassed, switched on)" if ins.get("saved_on") is False else ""
            summary.append(f"{name}: {model} on FX{engine}{switched}")
        if library is not None and entry.get("preset") and values.get("sha256"):
            try:
                found = library.bus_matches(entry["preset"])
            except PresetError:
                found = []
            if found and preset_expand_sha(found[0].source_path) != values["sha256"]:
                r.add(Severity.INFO, "preset.library-changed", where,
                      f"the library's copy of {entry['preset']!r} ({found[0].source_path}) has "
                      f"changed since this plan was built; the plan's values are what will be "
                      f"written",
                      fix="rebuild, or run `atoo presets --expand PLAN`")
    for engine, owners in sorted(claims.items()):
        if len(owners) > 1:
            r.add(SEVERITY_ERROR, "fx.engine-shared", "plan",
                  f"FX{engine} is inserted by {len(owners)} strips ({'; '.join(owners)}) -- one "
                  f"engine holds one effect, so the last one loaded would replace the others",
                  fix="rebuild, or run `atoo presets --expand PLAN`, to allocate them")
    if processing:
        # A mix bus's preset carries processing and no effect, so without
        # this line verify would say nothing about what it writes.
        r.add(Severity.INFO, "preset.bus-expanded", "plan",
              f"{len(processing)} bus(ses) carry a bus preset's processing, written at the "
              f"processing stage and read back like every other write: " + ", ".join(processing))
    if summary:
        r.add(Severity.INFO, "fx.inserts", "plan",
              f"{len(summary)} FX insert(s) are loaded and switched on, each read back: "
              + "; ".join(summary))


def preset_expand_sha(path) -> str:
    from atoo.preset_expand import file_sha256

    return file_sha256(path)


def _check_expanded_presets(channels: list[dict], library, r: VerifyResult) -> None:
    """The half of `_check_presets` for channels that carry values."""
    from atoo import apply as apply_module
    from atoo import preset_expand
    from atoo.presets import PresetError

    summary = []
    for channel in channels:
        # Keyed by name, as every other check is: a number alone does not
        # say whether it is ch 2 or aux 2.
        where = f"channels[{channel.get('name') or (channel.get('bank', 'ch') + ' ' + str(channel.get('channel', '?')))}]"
        bank = channel.get("bank", "ch")
        values = preset_expand.preset_values(channel)
        preset = values.get("preset")
        leaves = values.get("leaves") if isinstance(values.get("leaves"), dict) else {}
        named = channel["processing"].get("preset")

        if not preset_expand.expansion_matches_name(channel):
            r.add(SEVERITY_WARNING, "preset.stale-expansion", where,
                  f"carries values from the preset {preset!r} but "
                  + (f"names the preset {named!r}" if named else "names no preset")
                  + f" -- the {len(leaves)} values it carries are what will be written",
                  fix="rebuild, or run `atoo presets --expand PLAN`, so the values and "
                      "the name agree")

        explicit = apply_module.explicit_processing_addresses(channel)
        refused, won = [], []
        for address in leaves:
            refusal = preset_expand.leaf_refusal(address, bank)
            if refusal is None:
                value, refusal = preset_expand.coerce_value(address, leaves[address])
                if refusal is None:
                    refusal = preset_expand.value_refusal(address, bank, value)
            if refusal is not None:
                refused.append(f"{address} ({refusal})")
            elif address in explicit:
                won.append(address)
        if refused:
            r.add(SEVERITY_WARNING, "preset.leaf-not-written", where,
                  f"{len(refused)} of the preset {preset!r} values in this plan will not be "
                  f"written: " + "; ".join(refused))
        if won:
            # A plan edited by hand can hold both; build never writes one.
            r.add(Severity.INFO, "preset.overridden", where,
                  f"the plan's own processing is written at {', '.join(won)} instead of the "
                  f"value the preset {preset!r} carries there -- the plan wins")
        written = len(leaves) - len(refused) - len(won)
        summary.append(f"{bank} {channel.get('channel')} {preset} ({written})")

        if library is not None and named:
            try:
                found = library.matches(named)
            except PresetError:
                found = []
            if len(found) > 1:
                r.add(SEVERITY_WARNING, "preset.ambiguous", where,
                      f"{len(found)} presets in {library.directory} are named {named!r} "
                      f"({', '.join(p.source_path.name for p in found)}) -- this plan carries "
                      f"the values of {values.get('file') or preset!r}, the newest when it was "
                      f"built",
                      fix="give them distinct names, or remove the stale one")
            if found and values.get("sha256") and found[0].source_path.is_file():
                current = preset_expand.file_sha256(found[0].source_path)
                if current != values["sha256"]:
                    r.add(Severity.INFO, "preset.library-changed", where,
                          f"the library's copy of {named!r} ({found[0].source_path}) has changed "
                          f"since this plan was built; the plan's values are what will be "
                          f"written, not the library's",
                          fix="rebuild, or run `atoo presets --expand PLAN`, to take the "
                              "library's current values")

    if summary:
        r.add(Severity.INFO, "preset.expanded", "plan",
              f"{len(summary)} channel(s) carry a preset's values, written at the processing "
              f"stage and read back like every other write: " + ", ".join(summary))



def _check_inferred(plan: dict, r: VerifyResult) -> None:
    """Every value the plan DECIDED rather than was told, as an INFO.

    An inferred value is not a defect to be eliminated; an
    inferred value that does not announce itself is. The markers are the
    generator's (`inferred` lists on busses, channels and sends), or the
    deterministic fallback's -- an output index `build`'s allocation
    filled, and a bus width or send mode -- which also covers a plan on disk that still
    has a null width or send mode -- `inferred.with_decisions` decides it
    here exactly as apply will, so the note names the value that will be
    written rather than a null.
    """
    for diag in inferred.inferred_diagnostics(plan):
        r.findings.append(diag)


def _check_talkback(plan: dict, r: VerifyResult) -> None:
    """A talkback strip the desk's talkback cannot use
    (`talkback.unassignable`, a WARNING; 2026-10-02).

    Setup -> Audio's talkback assign (`/cfg/talk/assign`) names CH40, AUX8
    or OFF, nothing else: the TALK buttons can only use ch 40 or aux 8. A
    full apply sets it to the plan's talkback strip there
    (`apply.talkback_assign`). A talkback strip -- named as one,
    `console_facts.is_talkback_name` -- built anywhere else is still a mic
    channel, but the talk buttons cannot reach it, and that is a physical
    limit, not a preference, so it is said here. The strip is never moved:
    where it goes is the engineer's call. Quiet when some talkback strip is
    on ch 40 or aux 8 -- the desk's talkback has one, and a second talk
    mic elsewhere is an ordinary channel."""
    talk = [c for c in plan.get("channels") or []
            if isinstance(c, dict)
            and facts.is_talkback_name(c.get("name"), (c.get("source") or {}).get("input"))]
    if not talk or any((c.get("bank") or "ch", c.get("channel")) in facts.TALK_ASSIGN_STRIPS
                       for c in talk):
        return
    for c in talk:
        name = c.get("name")
        r.add(SEVERITY_WARNING, "talkback.unassignable", f"channels[{name}]",
              f"{c.get('bank') or 'ch'} {c.get('channel')} {name!r} reads as talkback, but the "
              "desk's talkback (Setup -> Audio, talkback assign) can only use CH 40 or AUX 8, "
              "so the TALK buttons cannot reach it -- apply leaves the assign as it is",
              fix="put the talkback strip on ch 40 or aux 8 (instructions.md or the "
                  "conventions), or confirm it is an ordinary mic channel")


def resolve_console_model(plan: dict, console_model: str | None = None) -> str | None:
    """Which console this plan is for: the caller's answer, else the plan's own.

    A plan records it in `meta.console_model` so that verifying the same
    file twice cannot quietly check it against two different consoles.
    Returns None when neither says -- which is a hard stop, not a default;
    see `verify_plan`.
    """
    if console_model:
        return console_model
    meta = plan.get("meta")
    if isinstance(meta, dict):
        stated = meta.get("console_model")
        if isinstance(stated, str) and stated:
            return stated
    return None


def verify_plan(plan: dict, rows: list[InputRow] | None = None, *,
                presets=None, console_model: str | None = None,
                layers=None) -> VerifyResult:
    """Check a plan against the console and, when given, against the input
    list it claims to cover.

    `rows=None` is for callers that hold a plan but not the list it was
    built from -- `atoo apply` being the one that matters. Everything
    checkable against the console alone still runs; the three checks that
    need the list are skipped and *said* to be skipped, because silently
    returning a clean result would imply an assurance nobody made. The
    omission check in particular is the most important one there is, so it
    must never look like it passed when it did not run.

    `layers` are the conventions and instructions the plan was built
    from (`conventions_audit.Layer`; `instructed_channels.layers_from_plan`
    finds them from `meta.conventions_stack`). They are needed only for a
    channel built from them rather than from the input list, whose quote
    is checked against them; None says that check did not run.

    `presets` is a `presets.PresetLibrary` or None. None means
    no library was configured, which is itself reportable when the plan
    names one; see `_check_presets`.

    Never raises on a bad plan -- a malformed plan is a finding, not an
    exception, because the caller needs the whole report rather than the
    first problem.
    """
    r = VerifyResult()

    # The schema first. A document that is not a plan makes every finding
    # below noise, and "not a field this format has" is a far more useful
    # message than whatever a later check would say about a typo'd key.
    # Checked as `plan_compat` reads it: a plan built
    # names an output's patch `socket`, and that is not a schema error.
    for violation in validate_schema(plan_compat.normalise_plan(plan), PLAN_SCHEMA):
        r.add(SEVERITY_ERROR, "schema", "plan", violation)

    if not _check_structure(plan, r):
        return r

    # An unknown console model is a hard
    # stop, because we have no way of knowing what its capabilities are
    # and any plan would be meaningless. It lands as an ERROR finding
    # rather than an exception to keep this function's never-raises
    # contract -- but the socket checks below genuinely cannot run without
    # it, so they are skipped and *said* to be skipped, the same way the
    # input-list checks are.
    resolved = resolve_console_model(plan, console_model)
    try:
        facts.panel_for(resolved)
    except facts.UnknownConsoleModel as exc:
        r.add(SEVERITY_ERROR, "console.unknown-model", "plan", str(exc),
              fix="pass --console-model, or set meta.console_model in the plan")
        r.add(SEVERITY_WARNING, "patch.not-checked", "plan",
              "no console model, so nothing checked that the physical sockets this plan "
              "patches actually exist on the console -- these counts differ between the "
              "WING, Rack and Compact")
        resolved = None

    _check_strips(plan, r)
    _check_colours_are_writable(plan, r)
    _check_patch(plan, r, resolved)
    _check_alt_patch(plan, r, resolved)
    _check_user_sources(plan, r, resolved)
    _check_captured_mix(plan, r)
    _check_expansion_bays(plan, r)
    _check_values(plan, r)
    _check_references(plan, r, resolved)
    _check_send_references(plan, r)
    _check_channels_reach_an_output(plan, r)
    _check_channels_reach_main(plan, r)
    _check_talkback(plan, r)
    _check_inferred(plan, r)
    _check_pair_phantom(plan, r)
    _check_presets(plan, presets, r)
    _check_bus_presets(plan, presets, r)
    if rows is None:
        r.add(SEVERITY_WARNING, "reconcile.not-checked", "plan",
              "no input list was supplied, so nothing checked that every input became a "
              "channel, that no channel was invented, or that phantom power is safe for "
              "the microphones in use -- pass the input list to check those")
        return r
    _check_reconciliation(plan, rows, r, layers)
    _check_stated_sockets(plan, rows, r)
    _check_stated_presets(plan, rows, r)
    _check_sheet_columns(plan, rows, r)
    _check_safety(plan, rows, r)
    return r
