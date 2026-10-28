"""Values a plan DECIDED rather than was TOLD -- and the announcing of them.

The principle (2026-09-23): it is OK to use the conventions and
domain knowledge to make a reasonable choice here, and not OK to leave
the mono/stereo decision undecided, because it affects how we patch.
This is why we have INFO messages. The test is **"can the board be put
into working order without this, and if we choose wrong, does it break or
merely displease?"** An inferred value is fine. An inferred value that
does not announce itself is the defect.

This module is the machinery for the short list of fields where that rule
overrides the generator's rule 4 ("do not guess a value the conventions
did not state -- leave it null"):

  * `inferred_diagnostics(plan)` turns every `inferred` marker (see
    `plan_schema.INFERABLE_FIELDS`) into an INFO finding naming the
    object, the field, the value chosen and what it was chosen from.
    `verify_plan` calls it, so build, verify, apply's pre-flight and amend
    all say the same thing.
  * `decide_unstated(plan)` is the deterministic fallback for a plan that
    still arrives with one of those fields null -- a plan built before
    this rule, a hand edit, a model that ignored the prompt. It fills the
    value and records a marker with `by: "fallback"`, so the fallback
    announces itself exactly as a model's decision does.

## Where the fallback runs, and why there

In `generate.generate_plan`, after index allocation -- so the plan on
disk carries the decided value and its marker, and a reader of plan.json
sees what the desk will be set to. And again, on a COPY, at the top of
`apply._build_write_targets` (which amend shares) and inside
`verify_plan` -- so a plan written before this rule, or edited by hand
since, is decided the same way by every consumer. The function is pure
and deterministic, so the three can never disagree about a value.

## The field audit -- which nullable fields are on this list, and why

Every nullable field in `plan_schema.py`, asked that question.

ON the list (null leaves the board undecided or the plan blocked, and a
wrong choice displeases rather than breaks):

  * bus `mono` -- null left the width to whatever the desk had, and on a
    bus feeding a dedicated output it BLOCKED the plan
    (`bus.unstated-width-for-dedicated-output`, now retired). A wrong
    width is audible at soundcheck; an unset one is a patch that may not
    work. Fallback: see `bus_width_fallback`.
  * a bus send's `mode` -- null BLOCKED the plan (`value.send-mode-unknown`
    fired on None). Pre vs post is a textbook judgement call: a wrong
    choice makes a monitor mix follow the FOH fader, which displeases.
    Fallback: see `send_mode_fallback`.
  * bus `destination`, for a mix or FX bus the conventions route nowhere
    -- null BLOCKS the plan (`bus.no-destination`), and "a mix bus goes to
    Main" is the domain knowledge's own statement. Generator-side only:
    **no deterministic fallback**, because code cannot tell a mix bus from
    a monitor bus by name, and routing a musician's monitor mix into the
    PA breaks rather than displeases. `bus.no-destination` stays an ERROR.
  * a bus send's `level_db` -- apply writes no `/send/{b}/lvl` for null,
    so the send keeps the desk's own level, and a fresh desk's is -144:
    the send is switched ON and passes nothing, and a mix or FX bus fed
    that way is silent. That is a patch that does not work. The slice-C
    reply prompt said "omit level_db for unity" on the belief that null
    meant unity to apply; it never did, and a festival build of
    2026-09-29 came back with every unity send null. A wrong level is
    heard at soundcheck; an unset one is no signal. Fallback: see
    `send_level_fallback` -- unity, 0 dB.
  * channel `source.stereo` -- not nullable, and rule 3a already makes it
    the generator's decision; it is on the list so a pairing made from the
    sources' NAMES ("Keys L"/"Keys R") rather than a stated rule
    announces itself too.

OFF the list (rule 4 stands -- null is a working board):

  * channel `processing.*` (hpf, hi-cut, tilt, trim, balance, invert,
    gain, eq, presend_eq, preset), `fader`/`muted`, `color`/`col`/`icon`,
    and a bus's or output's own `fader`/`processing`/`col`/`icon` --
    apply writes nothing for null and the desk keeps its value. Every one
    of those is a soundcheck decision, and a board with its previous
    filter or colour still passes audio.
  * output `patch` and a bus's dedicated-output `patch` -- a socket
    number is WHERE A CABLE IS, not a preference; no convention or domain
    knowledge implies which jack a wedge amp is plugged into, and a wrong
    guess sends a mix into the wrong device, which breaks. So a null patch
    is never guessed. An output with none is still set up -- its feed,
    level and processing -- and routed to no socket, said at WARNING
    (`output.no-patch`, 2026-10-09: a Matrix used as the phones
    source has no socket, and that is a working desk). A bus whose only
    destination is an unresolved socket is refused
    (`bus.unresolved-destination`).
  * output `fed_by`, `kind` -- a Matrix with no stated feed is warned
    about and not written; nothing is left in a state that cannot work.
  * `user_sources.*.tap`/`leg`, `name` -- a null leaves the desk's value
    (`apply.user_source_targets`).

ALLOCATED, and marked the same way (`plan_schema.ALLOCATED_FIELDS`):

  * output `index` -- which Main or Matrix strip an output entry IS. The
    model is not asked for it (D11: numbering is code's job), and
    `allocate.allocate_console_indices` fills one the plan left out: the
    slot a name like "Matrix 3" states, else the first free one, a lone
    Main being Main 1. Unlike a bus's index, something in the plan refers
    to it by number -- a Matrix's `fed_by: {type: main, index: N}` -- so
    the filled value marks itself `by: "fallback"` and verify reports it
    (`inferred.output-index`). Haiku 4.5 left it off both outputs of
    smallband's plan, 2026-09-28.

  * bus `destination.index`, for a bus whose destination is a Main with
    no number stated (review 2026-09-28, R6) -- which of up to four Mains
    the bus is summed into. `main_index_fallback` picks it: the output
    named "Main", else the lowest-numbered Main the plan carries, else
    Main 1. `allocate` fills it at build time and `decide_unstated` for a
    plan that was never built; both mark it `by: "fallback"` and verify
    reports it (`inferred.bus-main-index`). A plain "routes to main" means
    the main mix, so a wrong pick displeases rather than breaks.

A LINE SOURCE'S HEAD-AMP GAIN FOLLOWS ITS TYPE, and is announced
(`settle_line_gain`):

  * a channel whose source type is Line, patched to a socket with a head
    amp, takes `LINE_GAIN_DB` (0) where the plan gave it more than
    `LINE_GAIN_CEILING_DB` (10 dB) when no gain is stated anywhere. "Gain
    20 dB on each channel" is a mic's gain, and a model that copies it
    onto a playback feed unprompted clips the preamp, which breaks where a
    low gain merely displeases. But a gain the engineer states -- in the
    conventions (a line about every channel included), the instructions, the
    change or the Category table -- stands: his number, not a default.
    Anything else is chosen from the type and said.
    Build (`reply_expand.expand`) and Patch (`patch.merge_change`) both
    run it.

READ AS ONE VALUE FOR TWO SOCKETS, and announced:

  * a stereo channel's 48V. Phantom lives on each socket, so apply writes
    `/io/in/{grp}/{n}/vph` on both -- but the desk switches a stereo
    pair's two sockets together, so a pair has ONE value, never two.
    Build states it twice alike (`source.phantom` and `source.pair_phantom`
    equal): 48V is on if EITHER input-list row wants it, and the build
    says so at INFO naming the row that asked (`reply.pair-phantom`). A
    wrong choice displeases (48V on a dynamic is harmless; a condenser
    left off is silent, which is what breaks), and a passive ribbon on
    either socket is refused by verify, because that destroys it.
    Where the plan carries one value for the pair -- a single stereo row,
    a channel from the instructions -- `socket_phantom` reads `phantom` as
    both sockets', reported as `inferred.pair-phantom`, one INFO naming
    every channel where the reading puts 48V ON (off is what the reset
    before a full apply leaves on the second socket anyway, so nothing
    was chosen there). A plan on disk that states two different values is
    read the same way (on if either is) and reported by verify
    (`phantom.pair-differs`), not rewritten.

A marker naming any other field has no value to announce. `build` drops
it, with a repair note that keeps its basis (`drop_unmarkable`), rather
than refusing a whole plan over an annotation; the schema still refuses
one in a plan.json edited by hand.
"""

from __future__ import annotations

import copy
import re

from atoo import plan_compat
from atoo.diagnostics import Diagnostic, Severity
from atoo.plan_schema import INFERRED_BY, markable_fields

# Codes, one per field. Stable: the Setup UI's dock filters on them and a
# user quotes them in a bug report.
CODE_BUS_WIDTH = "inferred.bus-width"
CODE_BUS_DESTINATION = "inferred.bus-destination"
CODE_SEND_MODE = "inferred.send-mode"
CODE_CHANNEL_STEREO = "inferred.channel-stereo"
CODE_OUTPUT_INDEX = "inferred.output-index"
CODE_BUS_MAIN_INDEX = "inferred.bus-main-index"
CODE_SEND_LEVEL = "inferred.send-level"
CODE_PAIR_PHANTOM = "inferred.pair-phantom"

# The WING's own width for a bus nobody has set: every bus, Main and
# Matrix of `tests/fixtures/Initialized-Full.snap` (a factory-reset
# capture, 2026-09-23) reads `busmono: false`.
FACTORY_BUS_MONO = False

# The level a send the plan lists but gives no level is written at: unity.
UNITY_SEND_DB = 0.0


def _destinations(bus: dict) -> list[dict]:
    """Every destination a bus states -- `destinations` when non-empty,
    else the singular `destination`, the same reading apply
    and verify use."""
    dests = (bus or {}).get("destinations")
    if not dests:
        single = (bus or {}).get("destination")
        dests = [single] if single is not None else []
    return [d for d in dests if isinstance(d, dict)]


def _dedicated_sockets(bus: dict) -> list[dict]:
    """The physical socket objects of every dedicated-output destination."""
    out = []
    for dest in _destinations(bus):
        if dest.get("type") != "dedicated_output":
            continue
        sockets = plan_compat.output_patches(dest)
        out.extend(s for s in sockets if isinstance(s, dict))
    return out


def _socket_text(socket: dict) -> str:
    nums = socket.get("sockets") or []
    return f"{socket.get('group', '?')} {'/'.join(str(n) for n in nums)}"


def bus_width_fallback(bus: dict) -> tuple[bool, str]:
    """(mono, basis) for a bus whose width nobody stated.

    * A bus feeding a dedicated output on a socket PAIR is stereo -- a
      pair takes the bus's L and R slots (`apply._output_slot`), which is
      only a stereo feed if the bus is stereo.
    * A bus feeding dedicated outputs on single sockets only is mono --
      one jack carries one signal, and a stereo bus on one jack would
      deliver only its left side.
    * A bus feeding no physical output at all (a mix or FX bus summed into
      a Main) has no jack depending on its width, and is stereo: the
      WING's factory width, so it passes whatever panning its sources
      carry into the stereo Main.
    """
    sockets = _dedicated_sockets(bus)
    if sockets:
        where = ", ".join(_socket_text(s) for s in sockets)
        if any(len(s.get("sockets") or []) >= 2 for s in sockets):
            return False, (f"it feeds a dedicated output on a socket pair ({where}), "
                           "and a pair carries a stereo bus's left and right")
        return True, (f"it feeds a dedicated output on a single socket ({where}), "
                      "and one jack carries one signal")
    return FACTORY_BUS_MONO, ("no physical output socket depends on its width, so it keeps "
                              "the WING's factory width, stereo")


def _is_monitor_bus(bus: dict) -> bool:
    """A bus that reaches a physical socket and never a Main: how a stage
    monitor mix looks in a plan (`domain/knowledge.md`: "an ordinary bus
    whose output routing targets a physical socket instead of the main
    mix")."""
    dests = _destinations(bus)
    return (bool(_dedicated_sockets(bus))
            and not any(d.get("type") == "main" for d in dests))


def send_mode_fallback(bus_name: str, bus: dict) -> tuple[str, str]:
    """(mode, basis) for a send into `bus` whose mode nobody stated.

    Pre into a bus that feeds a physical output and no Main -- a monitor
    send, and monitor sends are pre-fader so a front-of-house move does not
    change what a musician hears. Post otherwise -- a mix or FX bus, whose
    sends follow the channel fader. Both from `domain/knowledge.md`.
    """
    if _is_monitor_bus(bus):
        return "pre", (f"{bus_name} feeds a physical output and no Main -- a monitor mix, "
                       "and monitor sends are pre-fader")
    return "post", (f"{bus_name} is not a monitor mix (it reaches a Main, or no physical "
                    "output) -- a mix or FX send, which is post-fader")


def send_level_fallback(bus_name: str, mode: str | None) -> tuple[float, str]:
    """(level_db, basis) for a listed send whose level nobody stated.

    Unity, whatever the bus. A send the plan lists is a send the
    conventions asked for, and is applied switched ON; left without a
    level it keeps the desk's own, which on a fresh desk is -144 -- on,
    and silent. Unity is where the domain starts a mix or FX send ("sends
    to these busses at unity, POST fader") and the level the reply format
    has always told the model to mean by leaving one out. A convention
    that wants a send down says so, and the model writes that level.
    """
    if mode == "pre":
        return UNITY_SEND_DB, ("a listed send starts at unity; left unset, a fresh desk's "
                               f"-144 would pass nothing to {bus_name}")
    return UNITY_SEND_DB, ("a post-fader send into a mix or FX bus starts at unity; left "
                           f"unset, a fresh desk's -144 would leave {bus_name} silent")


def _marker(obj: dict, field: str) -> dict | None:
    for entry in obj.get("inferred") or []:
        if isinstance(entry, dict) and entry.get("field") == field:
            return entry
    return None


def set_marker(obj: dict, field: str, basis: str, by: str) -> None:
    """Record that `obj[field]` was decided, from `basis`, by `by`.
    Also `allocate`'s, for an output index it fills."""
    # A stale marker for the same field (the value was nulled by hand
    # since) is replaced, never duplicated.
    kept = [e for e in obj.get("inferred") or []
            if not (isinstance(e, dict) and e.get("field") == field)]
    obj["inferred"] = kept + [{"field": field, "basis": basis, "by": by}]


def main_index_fallback(main_indices: dict[str, int]) -> tuple[int, str]:
    """Which Main a bus's plain "routes to main" (no number) means, and
    why -- `main_indices` maps each Main output's name to its index.
    Prefers an output literally named "Main"; else the lowest-numbered
    Main the plan carries; else Main 1 ("Main" defaults to
    Main 1 unless otherwise specified)."""
    exact = next((name for name in main_indices if name.lower() == "main"), None)
    if exact is not None:
        n = main_indices[exact]
        return n, f"the plan's output named {exact!r} is Main {n}"
    if main_indices:
        n = min(main_indices.values())
        if len(main_indices) == 1:
            name = next(iter(main_indices))
            return n, f"the plan carries one Main, {name!r}, which is Main {n}"
        return n, (f"the plan carries {len(main_indices)} Mains and none is named 'Main', so "
                   f"the lowest-numbered, Main {n}")
    return 1, "the plan carries no Main output, so Main 1"


def _plan_main_indices(plan: dict) -> dict[str, int]:
    return {name: out["index"] for name, out in (plan.get("outputs") or {}).items()
            if isinstance(out, dict) and out.get("kind") == "main"
            and isinstance(out.get("index"), int) and not isinstance(out.get("index"), bool)}


def _unnumbered_main_destinations(bus: dict) -> list[dict]:
    """The Main destinations of `bus` that state no index -- the mirror
    `destination` and every `destinations` entry."""
    found = []
    for dest in [bus.get("destination")] + list(bus.get("destinations") or []):
        if isinstance(dest, dict) and dest.get("type") == "main" and "index" not in dest:
            found.append(dest)
    return found


def fill_main_destination_index(bus: dict, main_indices: dict[str, int]) -> bool:
    """Give every unnumbered Main destination of `bus` the fallback Main,
    IN PLACE, marking the bus. Returns True when anything was filled."""
    targets = _unnumbered_main_destinations(bus)
    if not targets:
        return False
    index, basis = main_index_fallback(main_indices)
    for dest in targets:
        dest["index"] = index
    set_marker(bus, "destination.index", basis, "fallback")
    return True


def needs_deciding(plan: dict) -> bool:
    """True when some bus width, send mode, send level or Main destination
    number is still unstated."""
    busses = plan.get("busses") or {}
    if any(isinstance(b, dict) and b.get("mono") is None for b in busses.values()):
        return True
    if any(isinstance(b, dict) and _unnumbered_main_destinations(b) for b in busses.values()):
        return True
    for ch in plan.get("channels") or []:
        for send in (ch or {}).get("bus_sends") or []:
            if not isinstance(send, dict) or send.get("bus") not in busses:
                continue
            if send.get("mode") is None or send.get("level_db") is None:
                return True
    return False


#: `meta.made_from` on a plan `atoo capture` wrote.
CAPTURED_FROM = ("desk", "snap")


def plan_states_the_mix(plan: dict) -> bool:
    """Does an unstated fader, mute or send level in this plan mean the
    documented default (unity, unmuted, the fallback send level), as in a
    plan a build wrote, or "whatever the desk has"?

    A captured plan (`meta.made_from` `desk` or `snap`) leaves the mix out on
    purpose: Atoo never mixes, a fader or mute moved during a service is not
    a contradiction, and a capture applied back to its own desk must change
    nothing. So for it, the second: `decide_unstated` fills no
    send level or mode, `apply` writes no fader or mute the plan does not
    state and does no whole-desk reset, and CV017 reports only a mute the
    plan states."""
    meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
    return meta.get("made_from") not in CAPTURED_FROM


def decide_unstated(plan: dict) -> int:
    """Fill every null bus width, send mode and send level, and every Main
    destination with no number (R6), IN PLACE, marking each one
    `by: "fallback"`. Returns how many values were decided.

    Idempotent: a second call finds nothing null and changes nothing. A
    send into a bus the plan never declares is left alone -- that is
    `reference.dangling`'s to report, and there is no bus to decide from.

    A captured plan (`plan_states_the_mix` false) keeps its null send
    levels and modes: they are the desk's, and apply leaves them there.
    """
    decided = 0
    states_mix = plan_states_the_mix(plan)
    busses = plan.get("busses") or {}
    main_indices = _plan_main_indices(plan)
    for bus in busses.values():
        if isinstance(bus, dict) and fill_main_destination_index(bus, main_indices):
            decided += 1
    for bus in busses.values():
        if not isinstance(bus, dict) or bus.get("mono") is not None:
            continue
        mono, basis = bus_width_fallback(bus)
        bus["mono"] = mono
        set_marker(bus, "mono", basis, "fallback")
        decided += 1
    for ch in plan.get("channels") or []:
        for send in (ch or {}).get("bus_sends") or []:
            if not isinstance(send, dict):
                continue
            bus = busses.get(send.get("bus"))
            if not isinstance(bus, dict) or not states_mix:
                continue
            if send.get("mode") is None:
                mode, basis = send_mode_fallback(send["bus"], bus)
                send["mode"] = mode
                set_marker(send, "mode", basis, "fallback")
                decided += 1
            if send.get("level_db") is None:
                decide_send_level(send, send["bus"])
                decided += 1
    return decided


def decide_send_level(send: dict, bus_name: str) -> None:
    """Give `send` the fallback level, IN PLACE, and mark it -- build's
    expansion of the reply (`reply_expand.expand_sends`) and this module's
    `decide_unstated` both come here, so they cannot disagree."""
    level, basis = send_level_fallback(bus_name, send.get("mode"))
    send["level_db"] = level
    set_marker(send, "level_db", basis, "fallback")


def with_decisions(plan: dict) -> dict:
    """`plan` itself when nothing is left to decide, else a decided COPY.

    For the consumers that read a plan they must not modify -- verify,
    apply, amend. The copy is only taken when needed, so a plan built
    since this rule (which is already decided) costs nothing.
    """
    if not isinstance(plan, dict) or not needs_deciding(plan):
        return plan
    decided = copy.deepcopy(plan)
    decide_unstated(decided)
    return decided


def tag_model_markers(plan: dict) -> None:
    """Give every marker the generator wrote without a `by` the tag
    `"model"`, the same courtesy `generate._tag_model_notes` extends to
    `notes`. A `by` outside the vocabulary is left for the schema check to
    refuse."""
    def tag(obj):
        for entry in (obj or {}).get("inferred") or []:
            if isinstance(entry, dict) and "by" not in entry:
                entry["by"] = "model"

    for _where, _kind, obj in _marked_objects(plan):
        tag(obj)


def _marked_objects(plan: dict):
    """(where, kind, object) for every object that may carry `inferred`,
    `kind` being the key into `plan_schema.markable_fields`."""
    for name, bus in (plan.get("busses") or {}).items():
        if isinstance(bus, dict):
            yield f"busses[{name}]", "bus", bus
    for name, out in (plan.get("outputs") or {}).items():
        if isinstance(out, dict):
            yield f"outputs[{name}]", "output", out
    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        where = f"channels[{ch.get('name', '?')}]"
        yield where, "channel", ch
        for send in ch.get("bus_sends") or []:
            if isinstance(send, dict):
                yield f"{where}.bus_sends[{send.get('bus', '?')}]", "send", send


def drop_unmarkable(plan: dict) -> list[str]:
    """Remove, IN PLACE, every `inferred` entry naming a field its object
    may not mark, and return one repair sentence per entry removed.

    A marker is an annotation: it changes nothing apply writes, it only
    announces a value. So a marker naming a field the object has no such
    value for -- Haiku 4.5 wrote `{"field": "destination"}` on a Main
    output, 2026-09-28, where an output has no destination (a Main reaches
    a Matrix by the Matrix's own `fed_by`) -- has nothing to announce, and
    refusing the whole plan for it throws away a build over prose. Its
    basis is kept in the sentence so nothing the model said is lost.

    Only the `field` is judged here. A malformed entry (not an object, a
    `by` outside the vocabulary) is left for the schema check to report.
    """
    dropped: list[str] = []
    for where, kind, obj in _marked_objects(plan):
        entries = obj.get("inferred")
        if not isinstance(entries, list):
            continue
        allowed = markable_fields(kind)
        kept = []
        for entry in entries:
            field = entry.get("field") if isinstance(entry, dict) else None
            if isinstance(field, str) and field not in allowed:
                dropped.append(
                    f"{where}: dropped an 'inferred' marker for {field!r} -- not a value "
                    f"this object carries, so there is nothing to announce (its basis was: "
                    f"{entry.get('basis', '')!s})")
                continue
            kept.append(entry)
        if len(kept) != len(entries):
            if kept:
                obj["inferred"] = kept
            else:
                del obj["inferred"]
    return dropped


# --------------------------------------------------------------------------
# markers -> INFO findings
# --------------------------------------------------------------------------

def _decided_by(entry: dict) -> str:
    by = entry.get("by") if entry.get("by") in INFERRED_BY else "model"
    return ("decided by Atoo's fallback rule" if by == "fallback"
            else "decided by the generator")


def _destination_text(bus: dict) -> str:
    parts = []
    for dest in _destinations(bus):
        kind = dest.get("type")
        if kind == "main":
            parts.append(f"Main {dest.get('index', 1)}")
        elif kind == "matrix":
            parts.append(f"Matrix {dest.get('index', '?')}")
        else:
            sockets = _dedicated_sockets({"destination": dest})
            parts.append("output " + (", ".join(_socket_text(s) for s in sockets) or "(no socket)"))
    return " and ".join(parts) or "nowhere"


_FIX = ("if that is not what you want, say so in your conventions or this show's "
        "instructions and rebuild")


def stated_socket_phantom(channel: dict) -> list[tuple[int, bool]]:
    """`(socket, phantom the plan states)` for each socket of `channel`'s
    patch, in patch order, exactly as the plan carries it: the first socket
    takes `source.phantom`, a stereo pair's second takes
    `source.pair_phantom`, and `source.phantom` where the plan states one
    value for the pair (`pair_phantom_is_inferred`). Empty for an
    unpatched channel. A plan Build writes states the same value on both
    sockets; verify reports one that does not (`pair_phantom_differs`)."""
    source = channel.get("source") or {}
    sockets = [s for s in ((channel.get("patch") or {}).get("sockets") or [])
               if isinstance(s, int)]
    first = bool(source.get("phantom"))
    pair = source.get("pair_phantom")
    second = pair if isinstance(pair, bool) else first
    return [(socket, first if i == 0 else second) for i, socket in enumerate(sockets)]


def socket_phantom(channel: dict) -> list[tuple[int, bool]]:
    """`(socket, phantom wanted)` for each socket of `channel`'s patch, in
    patch order: the value `apply` writes and `verify` and the audit check.

    A stereo channel's two sockets switch 48V together on the desk -- the
    second one reads back on the moment the first is written -- so a pair
    has ONE value: on if either socket's stated value is on
    (`stated_socket_phantom`). A plan Build writes already states it
    twice alike; one that does not (an older build, a hand edit) is read
    the same way and reported by verify. Empty for an unpatched channel."""
    stated = stated_socket_phantom(channel)
    if len(stated) < 2:
        return stated
    pair_on = any(on for _socket, on in stated)
    return [(socket, pair_on) for socket, _on in stated]


def pair_phantom_differs(channel: dict) -> bool:
    """True when a stereo channel's plan states 48V on one socket and off
    on the other -- a state the desk cannot hold."""
    stated = stated_socket_phantom(channel)
    return len(stated) >= 2 and len({on for _socket, on in stated}) > 1


def pair_phantom_is_inferred(channel: dict) -> bool:
    """True for a stereo pair whose plan states one phantom value for its
    two sockets -- `socket_phantom` then reads it as both sockets'."""
    source = channel.get("source") or {}
    sockets = (channel.get("patch") or {}).get("sockets") or []
    return (bool(source.get("stereo")) and len(sockets) == 2
            and not isinstance(source.get("pair_phantom"), bool))


#: A Line source's head-amp gain, and the most it may keep when nothing was
#: stated for it. 0 dB is inside the range of every head amp this project has
#: seen (`console_facts.HEAD_AMP_GAIN_DB_RANGE` is -3 to 45.5 dB).
LINE_GAIN_DB = 0.0
LINE_GAIN_CEILING_DB = 10.0
_LINE_TYPES = frozenset({"line", "line level", "line-level"})


def is_line_source(channel: dict) -> bool:
    """A channel whose source type says it is line level."""
    kind = (channel.get("source") or {}).get("type")
    return isinstance(kind, str) and kind.strip().casefold() in _LINE_TYPES


def gain_stated_for(channel: dict, texts=()) -> bool:
    """Whether a head-amp gain was STATED anywhere the plan answers to: the
    conventions' Category table set it for this channel's category, or a
    line of one of `texts` (the conventions, the show's instructions, the
    change) says gain. A line about every channel ("set the input gain on
    each channel to 20dB") is a stated gain for a line source too, and it
    stands: the type decides only when nothing
    anywhere states one, so the plan's number was the model's own."""
    cited = str((channel.get("provenance") or {}).get("processing") or "").casefold()
    if "category table:" in cited and "gain" in cited:
        return True
    return any(re.search(r"\bgain\b", str(text or ""), re.IGNORECASE) for text in texts)


def settle_line_gain(channel: dict, *, stated: bool = False) -> str | None:
    """A Line source patched to a head amp does not keep a mic's gain.

    Returns the sentence that announces the choice (INFO), or None when the
    channel is not one this applies to. `stated` is the caller's word that
    the gain was asked for this channel (`gain_stated_for`, or the change's
    own words). Mutates `channel` and records the choice in its provenance;
    never touches a channel with no gain set, since an unset gain leaves
    the head amp as the desk had it."""
    from atoo import console_facts as facts

    processing = channel.get("processing")
    group = (channel.get("patch") or {}).get("group")
    gain = processing.get("gain_db") if isinstance(processing, dict) else None
    if (not is_line_source(channel) or group not in facts.PHANTOM_CAPABLE_GROUPS
            or isinstance(gain, bool) or not isinstance(gain, (int, float))
            or gain <= LINE_GAIN_CEILING_DB or stated):
        return None
    processing["gain_db"] = LINE_GAIN_DB
    sockets = "+".join(str(n) for n in (channel.get("patch") or {}).get("sockets") or [])
    name = channel.get("name")
    note = (f"head-amp gain {LINE_GAIN_DB:g} dB, chosen because the source is line level "
            f"(the plan had {gain:g} dB)")
    provenance = channel.setdefault("provenance", {})
    if isinstance(provenance, dict):
        before = provenance.get("processing")
        provenance["processing"] = f"{before}; {note}" if before else note
    return (f"channel {name!r}: a Line source on {group} {sockets}, a head amp, so its gain is "
            f"{LINE_GAIN_DB:g} dB, not the {gain:g} dB the plan had -- that is a mic's gain, "
            f"and a line-level feed with it would clip the preamp. Chosen from the source "
            f"type, because no gain is stated in your conventions or instructions. Say a gain "
            f"for {name!r} (say, 'gain 6 dB') if you want another.")


def inferred_diagnostics(plan: dict) -> list[Diagnostic]:
    """One INFO per decided value, fallback included.

    Reads the plan AS DECIDED (`with_decisions`), so a plan on disk that
    still has a null width reports the value apply will actually write,
    and a plan built since this rule reports the markers it carries --
    the same sentence either way. A marker whose field is null (edited by
    hand since) is superseded by the fallback's own; one naming a field
    the object does not carry is ignored rather than reported as a value.

    Sends are reported once per (bus, mode or level, basis), naming the channels,
    rather than once per send: sixteen channels into one wedge would
    otherwise bury the dock in the same sentence.
    """
    plan = with_decisions(plan)
    if not isinstance(plan, dict):
        return []
    out: list[Diagnostic] = []

    for name, bus in (plan.get("busses") or {}).items():
        if not isinstance(bus, dict):
            continue
        where = f"busses[{name}]"
        width = _marker(bus, "mono")
        if width is not None and isinstance(bus.get("mono"), bool):
            value = "mono" if bus["mono"] else "stereo"
            out.append(Diagnostic(
                severity=Severity.INFO, code=CODE_BUS_WIDTH, where=where, source="verify",
                message=(f"width set to {value} -- the conventions did not state it; "
                         f"{_decided_by(width)}: {width.get('basis', '')}"),
                fix=_FIX))
        dest = _marker(bus, "destination")
        if dest is not None and _destinations(bus):
            out.append(Diagnostic(
                severity=Severity.INFO, code=CODE_BUS_DESTINATION, where=where, source="verify",
                message=(f"routed to {_destination_text(bus)} -- the conventions did not say "
                         f"where this bus goes; {_decided_by(dest)}: {dest.get('basis', '')}"),
                fix=_FIX))
        main_index = _marker(bus, "destination.index")
        mains = sorted({d.get("index") for d in _destinations(bus)
                        if d.get("type") == "main" and isinstance(d.get("index"), int)})
        if main_index is not None and mains:
            which = " and ".join(f"Main {n}" for n in mains)
            out.append(Diagnostic(
                severity=Severity.INFO, code=CODE_BUS_MAIN_INDEX, where=where, source="verify",
                message=(f"summed into {which} -- the plan routes this bus to a Main without "
                         f"saying which; {_decided_by(main_index)}: {main_index.get('basis', '')}"),
                fix=('if that is the wrong Main, name it in the conventions ("FX returns go '
                     'to Main 2") and rebuild')))

    for name, output in (plan.get("outputs") or {}).items():
        if not isinstance(output, dict):
            continue
        index = _marker(output, "index")
        if index is not None and isinstance(output.get("index"), int):
            strip = "Matrix" if output.get("kind") == "matrix" else "Main"
            out.append(Diagnostic(
                severity=Severity.INFO, code=CODE_OUTPUT_INDEX, where=f"outputs[{name}]",
                source="verify",
                message=(f"{strip} index set to {output['index']} -- the plan left it out; "
                         f"{_decided_by(index)}: {index.get('basis', '')}"),
                fix=('if that is the wrong strip, number it in the conventions '
                     '("Main 2", "Matrix 3") and rebuild')))

    sends: dict[tuple, list[str]] = {}
    levels: dict[tuple, list[str]] = {}
    one_phantom: list[str] = []
    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        name = ch.get("name", "?")
        # Only where the reading puts 48V ON the second socket: off is
        # what the reset before a full apply leaves there anyway, so
        # nothing was chosen.
        if pair_phantom_is_inferred(ch) and (ch.get("source") or {}).get("phantom"):
            one_phantom.append(name)
        stereo = _marker(ch, "stereo")
        source = ch.get("source") or {}
        if stereo is not None and isinstance(source.get("stereo"), bool):
            value = ("linked as a stereo pair" if source["stereo"]
                     else "kept mono, not linked to a pair")
            out.append(Diagnostic(
                severity=Severity.INFO, code=CODE_CHANNEL_STEREO, where=f"channels[{name}]",
                source="verify",
                message=(f"{value} -- no convention states it; {_decided_by(stereo)}: "
                         f"{stereo.get('basis', '')}"),
                fix=_FIX))
        for send in ch.get("bus_sends") or []:
            if not isinstance(send, dict):
                continue
            level = _marker(send, "level_db")
            if level is not None and isinstance(send.get("level_db"), (int, float)):
                key = (send.get("bus"), float(send["level_db"]), level.get("basis", ""),
                       _decided_by(level))
                levels.setdefault(key, []).append(name)
            mode = _marker(send, "mode")
            if mode is None or send.get("mode") is None:
                continue
            key = (send.get("bus"), send["mode"], mode.get("basis", ""), _decided_by(mode))
            sends.setdefault(key, []).append(name)

    if one_phantom:
        shown = ", ".join(one_phantom[:6]) + (
            f" and {len(one_phantom) - 6} more" if len(one_phantom) > 6 else "")
        out.append(Diagnostic(
            severity=Severity.INFO, code=CODE_PAIR_PHANTOM, where="channels", source="verify",
            message=(f"48V on both sockets of {len(one_phantom)} stereo channel(s) ({shown}) -- "
                     "the plan states one phantom value for each pair, so the second socket "
                     "takes the first's"),
            fix=("the desk switches a stereo pair's two sockets together; if one of them "
                 "must be without 48V, split the pair into two mono channels")))

    for (bus, mode, basis, decided_by), channels in sends.items():
        shown = ", ".join(channels[:6]) + (f" and {len(channels) - 6} more" if len(channels) > 6 else "")
        out.append(Diagnostic(
            severity=Severity.INFO, code=CODE_SEND_MODE, where=f"busses[{bus}]", source="verify",
            message=(f"sends into {bus} set {mode}-fader on {len(channels)} channel(s) ({shown}) "
                     f"-- the conventions did not say pre or post; {decided_by}: {basis}"),
            fix=_FIX))
    for (bus, level, basis, decided_by), channels in levels.items():
        shown = ", ".join(channels[:6]) + (f" and {len(channels) - 6} more" if len(channels) > 6 else "")
        out.append(Diagnostic(
            severity=Severity.INFO, code=CODE_SEND_LEVEL, where=f"busses[{bus}]", source="verify",
            message=(f"sends into {bus} set to {level:g} dB on {len(channels)} channel(s) ({shown}) "
                     f"-- the plan states no level for them; {decided_by}: {basis}"),
            fix=('if they should start lower, state the level in your conventions ("sends to '
                 'X all the way down") and rebuild')))
    return out
