"""The *"cheaper thing to try first"*: `watch` does not need all
6,195 addresses, so work out exactly which ones the rules it is running
actually consume, and measure what scoping the read to those would buy.

**The answer is: not enough.** The numbers are in `scope_report()` and
reproduced in the requirements; the short version is that the
structural catalogue (`audit.DEFAULT_RULES`, which `watch` always runs)
reads **3,891 of the 6,195** addresses (3,392 of 5,712 when this was
measured; the alternate patch added 96 to both, the insert
points and FX slots another 304 to both, the comms half one
more, the socket widths 24, three AES50 link states and two
monitor sources, and each local
socket's own mute 24 more, a DCA's mute 16, and the width of each bus, Main and
Matrix 28), and
that is ~26s per-leaf against
~39s -- nowhere near the 3-4 second budget. Node dumps
(the default read) already get a full read to ~3.1-3.8s
at these rates, 4.8s measured on 2026-09-24, and scoping does
**not** improve on that at all, because the leaves scoping drops all live
inside object nodes the read still has to fetch for other leaves. Only
switching the structural rules off entirely -- leaving operator watch
conditions alone -- gets a per-leaf read under the budget (312 addresses,
~2.1s), and a `watch` that has stopped running the structural rules is
not the thing whose responsiveness was in question.

So this module exists to have **settled** that question with a measured
answer rather than to make the read faster. It is deliberately not wired
into the live read path; see "Wiring this in" below.

## What is in here

`RULE_ADDRESS_PATTERNS` maps each rule id in `audit.DEFAULT_RULES` to the
address families that rule reads, derived by hand from the rule's code
(and from every helper it calls -- `is_in_use`, `strip_bases`,
`objects_reaching_a_physical_output`, ...). `scoped_read_plan()` filters
`audit.console_read_plan()` down to the union for the rules in hand.

**A rule whose needs are not statically known keeps the whole plan.** An
address wrongly omitted is a rule that silently stops firing, which for a
monitoring tool is the worst available failure -- so an unrecognised rule
id widens the scope to everything and is named in
`ScopedReadPlan.unscoped_rule_ids` rather than guessed at. That is the
case for any rule a caller passes that this module has never heard of.

Operator watch conditions (`watch_conditions.build_watch_rules`) *are*
statically known, but not from the `AuditRule` -- the field is on the
condition dict, not the rule -- so `scoped_read_plan()` takes the
validated conditions as a separate argument and
`watch_conditions.condition_address_patterns()` turns them into patterns.
A `WATCH:*` rule with no matching condition falls back to the whole plan
for the same reason as any other unknown rule.

## Two ways this could have been got wrong, and what stops each

1. **Discovery.** Most rules do not name their addresses; they *discover*
   objects by scanning which addresses the state has at all
   (`audit._indices`, `send_targets`, `matrix_send_targets`,
   `main_route_targets`, `output_sockets`). Dropping the last address of
   an object therefore does not merely lose a value -- it makes the
   object vanish from the rule's world. `/mtx/{n}/mute` and `/mtx/{n}/fdr`
   are read by no rule's *logic* and are kept anyway, because they are
   the only thing that makes `audit.matrix_indices` see a matrix; same for
   `/main/{n}/mute` and `/main/{n}/fdr`.
2. **Trusting the table.** The table is hand-derived, so it is checked by
   running the rules rather than by reading them: `tests/test_watch_scope.py`
   audits a full-plan state and the same state restricted to the scoped
   plan and asserts the findings are **identical**, on states built so
   that every rule in the catalogue fires. Deleting a single address from
   the scoped plan makes that test fail.

## What actually gets dropped

Only one family, and it is genuinely unread:

* `/{ch,aux}/{n}/send/{bus|MXn}/{mode,pon}` -- 2,304 addresses, 40% of
  the plan. Pre/post and pan-link on a strip's send. The built-in rules
  read a send's `on` and `lvl` and nothing else. (CV006, bound to the
  show's plan, reads a bus send's `mode`; `STRIP_SEND_MODE` keeps it for
  that rule alone, so the default set still drops it.)

Everything else in `console_read_plan()` is consumed by at least one rule
the `watch` command runs by default.

## What did move the node-dump path: names

Scoping drops nothing a dump would have fetched; skipping names does. A
name is never taken from a dump (`audit.DUMP_UNSAFE_LEAVES`), so each is
its own request -- 88 of the 323 on a Compact, plus up to one source-
socket name per patched strip in the second pass. A live watch now reads
them at Start and every `watch.DEFAULT_NAME_REFRESH` passes, and a pass
between refreshes asks 235 (`ScopedReadPlan.node_dump_requests_between_refreshes`).
That is `watch.refreshing_names`, not this module; nothing here reads.

## Wiring this in

Nothing here touches the console. `audit.read_console_state` has no
address-subset parameter, and giving it one is the single change needed:

    def read_console_state(console, *, ..., only: Container[str] | None = None)

with the two loops skipping an address `only is not None and address not
in only`, and `group_plan_by_node` fed the filtered plan so a node nobody
wants is not dumped. `ScopedReadPlan.addresses` is exactly what that
parameter takes. It is not done here because `audit.py` was being
restructured at the same time, and because the measurement
below says the speed-up does not pay for the risk.

Run `python3 -m atoo.watch_scope` for the report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from atoo import audit
from atoo.audit import AuditRule, DEFAULT_RULES

# --------------------------------------------------------------------------
# Measured rates, derived from the A11 read-speed run of 2026-09-22
# -- a WING Compact, firmware 3.1.
#
# The capture's wall-clock totals are NOT the rates: 320 of the 6,032
# addresses it asked for do not exist on the desk, and each one costs
# `retries + 1` attempts at the 1.0s socket timeout
# (`console.WingConsole._request`, `WingConsole.__init__`), i.e. exactly
# 3.0s. 320 x 3.0 = 960.0s, which is the capture's own "about 960s of the
# time above" to the second, and those addresses were then removed
# from the plan. So the rate is (total - 960) / (requests that were
# answered), and that is what these two constants are.
# --------------------------------------------------------------------------

#: Addresses the desk does not have, in the A11 capture.
A11_UNANSWERED_ADDRESSES = 320
#: `retries + 1` attempts at the 1.0s default timeout, per unanswered address.
UNANSWERED_ADDRESS_COST_SECONDS = 3.0
#: What those 320 cost, and what comes off both totals below.
A11_TIMEOUT_SECONDS = A11_UNANSWERED_ADDRESSES * UNANSWERED_ADDRESS_COST_SECONDS

#: A11 [1/4], per-leaf: 998.58s total, 5,712 answered.
A11_PER_LEAF_SECONDS = 998.58
A11_PER_LEAF_ANSWERED = 5712
#: A11 [3/4], node dumps: 963.75s total, 684 requests of which 320 unanswered.
A11_NODE_DUMP_SECONDS = 963.75
A11_NODE_DUMP_REQUESTS = 684

#: Seconds per answered per-leaf GET. ~6.75ms.
PER_LEAF_SECONDS_PER_ADDRESS = (
    (A11_PER_LEAF_SECONDS - A11_TIMEOUT_SECONDS) / A11_PER_LEAF_ANSWERED)
#: Seconds per answered request on the node-dump path (a node dump or a
#: leaf the dump did not carry). ~10.3ms -- slower per request than a
#: per-leaf GET, because a dump datagram is ~2.2kB rather than ~40 bytes,
#: and worth it because one of them stands in for ~100 GETs.
NODE_DUMP_SECONDS_PER_REQUEST = (
    (A11_NODE_DUMP_SECONDS - A11_TIMEOUT_SECONDS)
    / (A11_NODE_DUMP_REQUESTS - A11_UNANSWERED_ADDRESSES))

#: A watch pass should land inside
#: this to feel like a monitor rather than a batch job.
RESPONSIVENESS_BUDGET_SECONDS = (3.0, 4.0)


# --------------------------------------------------------------------------
# Address families. Each is a regex over a whole address as
# `console_read_plan` writes it. They are named so the per-rule table
# below reads as an argument rather than as a wall of regex.
# --------------------------------------------------------------------------

_STRIP = r"/(?:ch|aux)/\d+"

#: A strip's own scalar leaves.
STRIP_NAME = rf"^{_STRIP}/name$"
STRIP_MUTE = rf"^{_STRIP}/mute$"
STRIP_FDR = rf"^{_STRIP}/fdr$"
STRIP_TAGS = rf"^{_STRIP}/tags$"
#: Both halves of a strip's input patch -- `ConsoleState.patch` reads them
#: together and one without the other answers nothing.
STRIP_PATCH = rf"^{_STRIP}/in/conn/(?:grp|in)$"
#: The alternate input patch's group and the switch between the two
#: patches. Both are needed to say which one the strip hears.
STRIP_ALT_PATCH = rf"^{_STRIP}/in/(?:conn/altgrp|set/altsrc)$"
#: The name of an INPUT SOCKET, `/io/in/{grp}/{n}/name`. Not in
#: `audit.console_read_plan` at all -- which socket to ask about is not
#: knowable until the patch has been read, so `read_console_state` fetches
#: these in a second pass. A rule that reads a strip's name
#: reads this too, because `clink` defaults ON and a name a human types
#: lands here rather than on the strip (the Podium). Kept as a
#: pattern so `ScopedReadPlan` can say whether a scope needs that second
#: pass; it filters nothing out of the plan, because none of it is in the
#: plan.
SOURCE_NAME = r"^/io/in/[A-Za-z0-9]+/\d+/name$"
#: A strip's `clink`, the switch that decides whether it displays its
#: source socket's name or its own. Second pass as well, and
#: for the same reason: whether to ask is not knowable until the patch has
#: been read (`audit.custom_link_addresses`). It travels with
#: `SOURCE_NAME` rather than getting a flag of its own -- the two are
#: consulted by the same pair of functions, `audit.source_is_named` and
#: `audit.effective_name`, so a scope that needs one needs the other.
#: Filters nothing out of the plan.
CUSTOM_LINK = rf"^{_STRIP}/clink$"
#: What is fitted in an expansion bay, `/cards/$type` and
#: `/$syscfg/opt_mod`. Second pass too, and for the same
#: reason: whether to ask is not knowable until the patches have been
#: read (`audit.expansion_bay_addresses`). Filters nothing out of the plan.
EXPANSION_BAY = r"^/(?:cards/\$type|\$syscfg/opt_mod)$"
#: A strip's send to a bus or a matrix, switched on. `send_targets` and
#: `matrix_send_targets` DISCOVER the targets from these addresses' mere
#: presence, so this family carries discovery as well as value.
STRIP_SEND_ON = rf"^{_STRIP}/send/(?:\d+|MX\d+)/on$"
STRIP_SEND_LVL = rf"^{_STRIP}/send/(?:\d+|MX\d+)/lvl$"
#: The same two for a strip's sends to a matrix only (CV018 no longer
#: looks at a send to a bus), so its Watch pass reads half as many leaves.
STRIP_MTX_SEND_ON = rf"^{_STRIP}/send/MX\d+/on$"
STRIP_MTX_SEND_LVL = rf"^{_STRIP}/send/MX\d+/lvl$"
#: A strip's send to a bus: pre or post (CV006, bound to a plan). Rides in
#: the same node as `on` and `lvl`, so a dump read asks for nothing more.
STRIP_SEND_MODE = rf"^{_STRIP}/send/\d+/mode$"
#: A strip's direct route to a Main; `main_route_targets` discovers from it.
STRIP_MAIN_ON = rf"^{_STRIP}/main/\d+/on$"

BUS_NAME = r"^/bus/\d+/name$"
BUS_MUTE = r"^/bus/\d+/mute$"
BUS_FDR = r"^/bus/\d+/fdr$"
#: A bus's, Main's or Matrix's width, `busmono` (R011, CV020): 1 is mono.
#: Read with the object's other leaves, in the same node.
BUS_WIDTH = r"^/bus/\d+/busmono$"
MAIN_WIDTH = r"^/main/\d+/busmono$"
MTX_WIDTH = r"^/mtx/\d+/busmono$"
BUS_SEND_ON = r"^/bus/\d+/send/MX\d+/on$"
BUS_SEND_LVL = r"^/bus/\d+/send/MX\d+/lvl$"
BUS_MAIN_ON = r"^/bus/\d+/main/\d+/on$"

#: A Main has no `name` in the read plan; `mute`/`fdr` are read by no
#: rule's logic and are kept because `audit.main_indices` -- which
#: `matrix_feed_bases` and L001's source list both walk -- discovers a
#: Main from `/main/{n}/...` and nothing else would put one there on a
#: desk whose Mains send to no matrix.
MAIN_PRESENCE = r"^/main/\d+/(?:mute|fdr)$"
MAIN_SEND_ON = r"^/main/\d+/send/MX\d+/on$"
MAIN_SEND_LVL = r"^/main/\d+/send/MX\d+/lvl$"

#: Same reasoning as MAIN_PRESENCE, for `audit.matrix_indices` inside
#: `_referenced_matrix_indices` (R003).
MTX_PRESENCE = r"^/mtx/\d+/(?:mute|fdr)$"

DCA_NAME = r"^/dca/\d+/name$"
DCA_FDR = r"^/dca/\d+/fdr$"
DCA_MUTE = r"^/dca/\d+/mute$"

MGRP_NAME = r"^/mgrp/\d+/name$"
MGRP_MUTE = r"^/mgrp/\d+/mute$"

#: Every insert point's switch and the FX slot it names, on any object
#: that has one (`console_facts.INSERT_POINTS`). These also
#: discover the object, which is how a Main or Matrix with an insert is
#: found at all.
INSERT = r"^/(?:ch|aux|bus|main|mtx)/\d+/(?:pre|post)ins/(?:on|ins)$"
#: What each FX slot holds.
FX_MODEL = r"^/fx/\d+/mdl$"
#: Which strip talkback uses, and where TALK A and TALK B are routed. The routing is a second-pass read, asked only when the
#: first is not OFF.
TALK = r"^/cfg/talk/(?:assign|[AB]/(?:B|MX|M)\d+)$"
#: Just which strip talkback is assigned to -- what CH001, L002 and
#: T002 need to recognise the talk mic's strip, without the 56 switches.
TALK_ASSIGN = r"^/cfg/talk/assign$"
GLOBAL_ALT_SWITCH = r"^/io/altsw$"

#: What feeds each USER PATCH slot (C001).
USER_PATCH = r"^/io/in/USR/\d+/user/(?:grp|in)$"
#: 48V on a physical input jack. `USR` is not a jack and carries none.
INPUT_PHANTOM = r"^/io/in/(?!USR/)[A-Za-z0-9]+/\d+/vph$"
#: A jack's width -- `ST` or `M/S` on an odd socket means the strip
#: patched there takes the next one too (C001).
INPUT_MODE = r"^/io/in/(?!USR/)[A-Za-z0-9]+/\d+/mode$"
#: A jack's own mute (C007): a muted socket silences every strip patched
#: to it. Read beside `vph` and `mode`, in the same node.
INPUT_MUTE = r"^/io/in/(?!USR/)[A-Za-z0-9]+/\d+/mute$"
#: What feeds each physical output socket -- both halves, as
#: `ConsoleState.output_source` reads them together.
OUTPUT_PATCH = r"^/io/out/[A-Za-z0-9]+/\d+/(?:grp|in)$"
#: Whether each AES50 port has a device on it. With the
#: strips' input patches, it decides which AES50 ports' outputs the
#: second pass reads (`audit.aes50_output_addresses`) -- so every rule
#: that reads the output patch reads these too, or a scoped read would
#: lose a stage box's outputs and call its busses unrouted.
AES50_STATUS = r"^/\$stat/[ABC]/stat$"
#: The outputs of an AES50 port in use: second pass, in no read plan,
#: and filters nothing out of it. Travels with `AES50_STATUS`.
AES50_OUTPUT = r"^/io/out/[ABC]/\d+/(?:grp|in)$"
#: What the desk's two monitor outputs listen to: a source
#: there reaches the phones with no socket of its own.
MONITOR_SOURCE = r"^/cfg/mon/[12]/src$"
#: Everything "does this reach an output" needs besides the routing: the
#: output patch, the AES50 ports that widen it, the strip patches that
#: also mark a port in use, and the monitor sources.
_OUTPUT_SIDE = (OUTPUT_PATCH, AES50_STATUS, STRIP_PATCH, MONITOR_SOURCE)


# `is_in_use(base)` for a strip, spelled out once: named, input patched,
# or sending anywhere it was not sending from the factory. Five families,
# and every rule that asks whether a strip is in use needs all five.
_IN_USE_STRIP = (STRIP_NAME, SOURCE_NAME, STRIP_PATCH, STRIP_SEND_ON,
                 STRIP_MAIN_ON)
# `is_in_use(base)` for a bus adds "receiving sends", which is read off
# the STRIPS' send addresses, not the bus's.
_IN_USE_BUS = (BUS_NAME, BUS_SEND_ON, BUS_MAIN_ON, STRIP_SEND_ON)
# `objects_reaching_a_physical_output` -- the reverse fixpoint R002,
# R005 and R006 share. Output patches, plus every bus->Main, bus->Matrix and
# Main->Matrix edge that is switched on, plus the Main discovery
# `_referenced_main_indices` does.
_REACHING = _OUTPUT_SIDE + (BUS_MAIN_ON, BUS_SEND_ON, MAIN_SEND_ON,
                            MAIN_PRESENCE, STRIP_MAIN_ON, STRIP_NAME, BUS_NAME)


#: rule id -> the address families that rule reads. Hand-derived from
#: `audit.py`, one entry per row of `DEFAULT_RULES` plus the plan-bound
#: rules Watch adds (`PLAN_RULE_IDS`), and verified end to
#: end by `tests/test_watch_scope.py` rather than trusted.
#: The rules Watch adds from the show's plan, not from `DEFAULT_RULES`.
PLAN_RULE_IDS = ("CV006", "CV007", "CV015", "CV016", "CV017", "CV018", "CV019", "CV020", "CV021", "CV022")

RULE_ADDRESS_PATTERNS: dict[str, tuple[str, ...]] = {
    # Is an in-use bus fed by any strip? Bus discovery and label from
    # `/bus/{n}/name`; "in use" from _IN_USE_BUS; "fed" from every strip's
    # `send/{bus}/on`.
    "R001": (BUS_NAME,) + _IN_USE_BUS,
    # Adds the reverse fixpoint over routing and output patches.
    "R002": (BUS_NAME,) + _IN_USE_BUS + _REACHING,
    # Is a matrix patched out but fed by nothing? Matrix discovery from
    # `/mtx/{n}/{mute,fdr}` and from every `send/MX{n}/on` there is;
    # `matrix_feed_bases` walks strips, busses AND Mains.
    "R003": _OUTPUT_SIDE + (MTX_PRESENCE, STRIP_NAME, BUS_NAME,
                MAIN_PRESENCE, STRIP_SEND_ON, BUS_SEND_ON, MAIN_SEND_ON),
    # Is a Main patched out but fed by nothing? Feeds are `main/{n}/on`
    # on a strip or a bus, never a send.
    "R004": _OUTPUT_SIDE + (MAIN_PRESENCE, STRIP_NAME, BUS_NAME,
                STRIP_MAIN_ON, BUS_MAIN_ON),
    # Fed but reaching no output -- R004's feeds plus R002's fixpoint.
    "R005": (OUTPUT_PATCH, MAIN_PRESENCE, STRIP_NAME, BUS_NAME,
                STRIP_MAIN_ON, BUS_MAIN_ON) + _REACHING,
    # Fed but patched nowhere -- R003's feeds plus the fixpoint.
    "R006": (OUTPUT_PATCH, MTX_PRESENCE, STRIP_NAME, BUS_NAME,
                MAIN_PRESENCE, STRIP_SEND_ON, BUS_SEND_ON, MAIN_SEND_ON)
               + _REACHING,
    # What R002, R005 and R006 stood down on: the
    # union of their reads, plus the names its labels quote.
    "R007": (OUTPUT_PATCH, MTX_PRESENCE, STRIP_NAME, BUS_NAME, SOURCE_NAME,
                MAIN_PRESENCE, STRIP_SEND_ON, BUS_SEND_ON, MAIN_SEND_ON)
               + _IN_USE_BUS + _REACHING,
    # A strip in use with no bus send, Matrix send or Main route on: every
    # strip's sends and routes, which busses, Matrices and Mains exist (so
    # that "every send was read" can be told), mute and fader, the talk
    # mic and the monitor sources that exempt a strip, and the names its
    # label quotes.
    "R008": (STRIP_MUTE, STRIP_FDR, TALK_ASSIGN, MONITOR_SOURCE, BUS_NAME,
                MAIN_PRESENCE, MTX_PRESENCE, STRIP_SEND_ON, STRIP_MAIN_ON)
               + _IN_USE_STRIP,
    # A loop through the sends and routes: each strip's patch (which strips
    # take a bus, Main or Matrix), the alternate and global switches that
    # hand a strip to C004 and C005, every send's switch and level, every
    # route to a Main, and which busses and Mains there are. Names for the
    # label. R010 reads the same.
    "R009": (STRIP_PATCH, STRIP_ALT_PATCH, GLOBAL_ALT_SWITCH, STRIP_SEND_ON, STRIP_SEND_LVL,
                STRIP_MAIN_ON, BUS_SEND_ON, BUS_SEND_LVL, BUS_MAIN_ON, MAIN_SEND_ON,
                MAIN_SEND_LVL, MAIN_PRESENCE, STRIP_NAME, SOURCE_NAME, BUS_NAME),
    "R010": (STRIP_PATCH, STRIP_ALT_PATCH, GLOBAL_ALT_SWITCH, STRIP_SEND_ON, STRIP_SEND_LVL,
                STRIP_MAIN_ON, BUS_SEND_ON, BUS_SEND_LVL, BUS_MAIN_ON, MAIN_SEND_ON,
                MAIN_SEND_LVL, MAIN_PRESENCE, STRIP_NAME, SOURCE_NAME, BUS_NAME),
    # A stereo bus, Main or Matrix patched on one side only: the output
    # patch and what makes it complete (AES50 ports, strip patches), each
    # kind's width, and what makes an object "in use" (a bus's name and
    # sends, a Main's or Matrix's feeds), with the names the label quotes.
    "R011": _OUTPUT_SIDE + (BUS_WIDTH, MAIN_WIDTH, MTX_WIDTH, BUS_NAME, STRIP_NAME,
                SOURCE_NAME, MAIN_PRESENCE, STRIP_SEND_ON, STRIP_MAIN_ON, BUS_SEND_ON,
                BUS_MAIN_ON, MAIN_SEND_ON),
    # A strip that reaches one Main or Matrix by two routes: every strip's
    # sends and Main routes with their levels, each bus's Main routes and
    # Matrix sends, each Main's Matrix sends, the mutes it names, and the
    # names the labels quote. R013 reads the same.
    "R012": (STRIP_SEND_ON, STRIP_SEND_LVL, STRIP_MAIN_ON, BUS_SEND_ON, BUS_SEND_LVL,
                BUS_MAIN_ON, MAIN_SEND_ON, MAIN_SEND_LVL, STRIP_MUTE, BUS_MUTE,
                MAIN_PRESENCE, MTX_PRESENCE, STRIP_NAME, SOURCE_NAME, BUS_NAME)
               + _IN_USE_STRIP,
    "R013": (STRIP_SEND_ON, STRIP_SEND_LVL, STRIP_MAIN_ON, BUS_SEND_ON, BUS_SEND_LVL,
                BUS_MAIN_ON, MAIN_SEND_ON, MAIN_SEND_LVL, STRIP_MUTE, BUS_MUTE,
                MAIN_PRESENCE, MTX_PRESENCE, STRIP_NAME, SOURCE_NAME, BUS_NAME)
               + _IN_USE_STRIP,
    # 48V on a jack nothing takes: every strip's patch, every USER PATCH
    # slot's source, the jack's own `vph`, and the width of the socket
    # before it -- a stereo strip takes the even socket too.
    "C001": (STRIP_PATCH, USER_PATCH, INPUT_PHANTOM, INPUT_MODE),
    # The finding labels each strip with the name the desk is SHOWING,
    # which `clink` puts on the socket.
    "C002": (STRIP_PATCH, STRIP_NAME, SOURCE_NAME),
    # A strip patched from, or an output routed to, a bay that reports
    # NONE. Names for the label, the bay reading from the second pass.
    "C003": (STRIP_PATCH, OUTPUT_PATCH, EXPANSION_BAY, STRIP_NAME,
                SOURCE_NAME),
    # An AES50 port's link and what depends on it: the status leaf (already
    # read for the outputs of a port in use), every strip's patch, the
    # alternate and global switches that hand a strip to C004 and C005, and
    # every output's source. Names for the label. C009 reads the same.
    "C008": (AES50_STATUS, STRIP_PATCH, STRIP_ALT_PATCH, GLOBAL_ALT_SWITCH, OUTPUT_PATCH,
                STRIP_NAME, SOURCE_NAME),
    "C009": (AES50_STATUS, STRIP_PATCH, STRIP_ALT_PATCH, GLOBAL_ALT_SWITCH, OUTPUT_PATCH,
                STRIP_NAME, SOURCE_NAME),
    # C010 counts the strips patched from the port and names none.
    "C010": (AES50_STATUS, STRIP_PATCH, STRIP_ALT_PATCH, GLOBAL_ALT_SWITCH),
    # The switch, the alternate's group, and the main patch the finding
    # says the strip is NOT hearing. Names for the label.
    "C004": (STRIP_ALT_PATCH, STRIP_PATCH, STRIP_NAME, SOURCE_NAME),
    "C005": (GLOBAL_ALT_SWITCH,),
    # A strip in use with nothing patched: its group, the alternate switch
    # and group that hand the strip to C004, the global switch, the talk
    # mic, and what makes it in use.
    "C006": (STRIP_ALT_PATCH, GLOBAL_ALT_SWITCH, TALK_ASSIGN) + _IN_USE_STRIP,
    # A strip in use whose source socket is muted: the strip's patch, the
    # alternate and global switches that hand it to C004 and C005, the
    # socket's mute and width (a stereo source takes the next socket too),
    # and what makes the strip in use. Names for the label.
    "C007": (STRIP_PATCH, STRIP_ALT_PATCH, GLOBAL_ALT_SWITCH, INPUT_MUTE, INPUT_MODE)
               + _IN_USE_STRIP,
    # An insert and the slot it names. Names for the label; a bus is
    # labelled with its own.
    "E001": (INSERT, FX_MODEL, STRIP_NAME, SOURCE_NAME, BUS_NAME),
    # Every insert on the desk, to know which slots are named at all.
    "E002": (INSERT, FX_MODEL),
    "E003": (INSERT, FX_MODEL, STRIP_NAME, SOURCE_NAME, BUS_NAME),
    # Not in DEFAULT_RULES: added by Watch when the show's plan loads an
    # FX bus's effect (`audit.plan_watch_rules`). The bus's
    # insert, the engine's model, and the bus's name for the label.
    "CV015": (INSERT, FX_MODEL, BUS_NAME),
    # Added by Watch when the plan routes a channel: every
    # send and Main route of a strip, its label, the buses' names it
    # quotes, and what else it still reaches.
    "CV016": (STRIP_SEND_ON, STRIP_SEND_LVL, STRIP_MAIN_ON, BUS_NAME)
                + _IN_USE_STRIP,
    # Added by Watch from any plan: the mute of every object
    # kind the plan leaves unmuted, the names its labels quote, and which
    # strip is the talk mic (exempt).
    "CV017": (STRIP_MUTE, BUS_MUTE, DCA_MUTE, MAIN_PRESENCE, MTX_PRESENCE,
                 BUS_NAME, DCA_NAME, TALK_ASSIGN) + _IN_USE_STRIP,
    # Added by Watch from a plan with sends: the switch and the pre/post
    # mode of every send, the buses' names that resolve the plan's, and the
    # strip's label. The level is `audit --plan`'s; it is read here only
    # because CV016's finding, which this stands down for, needs it.
    "CV006": (STRIP_SEND_ON, STRIP_SEND_MODE, STRIP_SEND_LVL, BUS_NAME)
                + _IN_USE_STRIP,
    # Added by Watch from a plan: every strip's Main routes. The same
    # addresses as CV016, whose finding it stands down for.
    "CV007": (STRIP_SEND_ON, STRIP_SEND_LVL, STRIP_MAIN_ON, BUS_NAME)
                + _IN_USE_STRIP,
    # Added by Watch from a plan: every strip's sends to a matrix and their
    # level (a send at the floor passes nothing), each bus's Main routes,
    # and the names the labels quote. A send to a bus is not CV018's.
    "CV018": (STRIP_MTX_SEND_ON, STRIP_MTX_SEND_LVL, BUS_MAIN_ON, BUS_NAME)
                + _IN_USE_STRIP,
    # Added by Watch from a plan that states a phantom: the socket each
    # strip is patched to, its 48V, and the names its label quotes.
    "CV019": (STRIP_PATCH, INPUT_PHANTOM, STRIP_NAME, SOURCE_NAME),
    # Added by Watch from a plan that states a bus width: the width and the
    # name the label quotes.
    "CV020": (BUS_WIDTH, BUS_NAME),
    # Added by Watch from a plan that builds a monitor mix: the talkback
    # assignment and its destination switches, and the bus name the label
    # quotes.
    "CV021": (TALK, BUS_NAME),
    "CV022": (TALK, BUS_NAME),
    # The assignment and all 56 destination switches.
    "T001": (TALK,),
    # Which strip is the talk mic, and whether it is in use.
    "T002": (TALK_ASSIGN,) + _IN_USE_STRIP,
    # Membership lives in the strip's own tags string.
    "CH001": (STRIP_TAGS, TALK_ASSIGN) + _IN_USE_STRIP,
    "CH002": (STRIP_TAGS, DCA_NAME, DCA_FDR) + _IN_USE_STRIP,
    "CH003": (STRIP_TAGS, MGRP_NAME, MGRP_MUTE) + _IN_USE_STRIP,
    "CH004": (STRIP_TAGS, DCA_NAME, DCA_MUTE) + _IN_USE_STRIP,
    "N001": (STRIP_NAME, STRIP_PATCH, SOURCE_NAME),
    "N002": (BUS_NAME,),
    # Every send there is, on a strip, a bus or a Main -- `on` to know it
    # is live, `lvl` to know it is dead. Names are the label only.
    "L001": (STRIP_NAME, BUS_NAME, MAIN_PRESENCE,
                STRIP_SEND_ON, STRIP_SEND_LVL,
                BUS_SEND_ON, BUS_SEND_LVL,
                MAIN_SEND_ON, MAIN_SEND_LVL),
    "L002": (STRIP_MUTE, STRIP_FDR, BUS_MUTE, BUS_FDR, TALK_ASSIGN)
               + _IN_USE_STRIP + _IN_USE_BUS,
    # Reads no address at all: the clips come from the console's meter
    # stream (`atoo.metering`), and the labels it quotes are
    # the names every pass already reads.
    "L003": (STRIP_NAME, BUS_NAME, MAIN_PRESENCE),
}


@dataclass(frozen=True)
class ScopedReadPlan:
    """What a read would have to fetch for one particular set of rules.

    `plan` is a strict subsequence of `full` -- same `(address,
    value_type)` pairs, same order, nothing invented. `unscoped_rule_ids`
    names every rule that widened the scope to everything because this
    module could not work out what it reads; when it is non-empty,
    `plan == full` and the scope saved nothing, which is the intended
    failure direction.
    """

    plan: tuple[tuple[str, str], ...]
    full: tuple[tuple[str, str], ...]
    unscoped_rule_ids: tuple[str, ...] = ()
    #: Whether a read for this scope must also run
    #: `read_console_state`'s **second pass** for input-socket names. Those addresses are in no read plan -- which socket
    #: to ask about is not knowable until the patch has been read -- so
    #: `plan` cannot carry them and a caller that honours only `plan`
    #: would hand the rules a state where every hand-named strip looks
    #: unnamed. Covers `CUSTOM_LINK` too, which the same two
    #: functions consult. It costs at most two addresses per PATCHED
    #: strip, 52 on a factory Compact.
    reads_source_names: bool = False
    #: The same, for the other half of that second pass: the fitted-card
    #: reading of any expansion bay in use (C003). At most
    #: two addresses, none on a desk that uses neither bay.
    reads_expansion_bays: bool = False
    #: The same, for where TALK A and TALK B are routed (T001): 56 switches, asked only when talkback is assigned.
    reads_talkback: bool = False
    #: The same, for the outputs of every AES50 port in use:
    #: 96 per port with a stage box on it, none on a desk without one.
    reads_aes50_outputs: bool = False

    @property
    def addresses(self) -> frozenset[str]:
        """The address set, for membership tests -- what a future
        `read_console_state(..., only=...)` would take."""
        return frozenset(address for address, _ in self.plan)

    @property
    def dropped(self) -> tuple[str, ...]:
        """Addresses in the full plan that no enabled rule reads."""
        kept = self.addresses
        return tuple(address for address, _ in self.full if address not in kept)

    @property
    def per_leaf_seconds(self) -> float:
        return len(self.plan) * PER_LEAF_SECONDS_PER_ADDRESS

    @property
    def node_dump_requests(self) -> int:
        """Requests the node-dump read (the default) makes for this scope: one
        per object node any wanted address lives under, plus one per
        `name`/`tags` leaf, which is never taken from a dump
        (`audit.DUMP_UNSAFE_LEAVES`)."""
        by_node, alone = audit.group_plan_by_node(list(self.plan))
        return len(by_node) + len(alone)

    @property
    def node_dump_seconds(self) -> float:
        return self.node_dump_requests * NODE_DUMP_SECONDS_PER_REQUEST

    @property
    def node_dump_requests_between_refreshes(self) -> int:
        """`node_dump_requests` for a watch pass between name refreshes, which takes every `name` from the last refresh and
        asks for none: 323 -> 235 on a Compact's full plan."""
        by_node, alone = audit.group_plan_by_node(
            [(a, t) for a, t in self.plan if not audit.is_name_address(a)])
        return len(by_node) + len(alone)


def _compile(patterns: Iterable[str]) -> list[re.Pattern]:
    return [re.compile(p) for p in dict.fromkeys(patterns)]


def rule_address_patterns(
    rule: AuditRule, conditions: Sequence[dict] = (),
) -> tuple[str, ...] | None:
    """The address families `rule` reads, or None when they are not
    statically known -- which the caller must treat as "this rule needs
    the whole plan", never as "this rule needs nothing".

    A `WATCH:*` rule is answered from `conditions`, because the field it
    checks lives on the condition dict rather than on the `AuditRule`."""
    if rule.id in RULE_ADDRESS_PATTERNS:
        return RULE_ADDRESS_PATTERNS[rule.id]
    if rule.id.startswith("WATCH:"):
        # Imported here rather than at module scope: watch_conditions
        # imports audit, and this module is imported by watch.py; a
        # top-level import would make the cycle harder to reason about
        # than it needs to be.
        from atoo.watch_conditions import condition_address_patterns

        wanted = rule.id[len("WATCH:"):]
        for cond in conditions:
            if cond.get("id") == wanted:
                return condition_address_patterns(cond)
    return None


def scoped_read_plan(
    rules: Sequence[AuditRule] | None = None,
    conditions: Sequence[dict] = (),
    **plan_kwargs,
) -> ScopedReadPlan:
    """`audit.console_read_plan(**plan_kwargs)` narrowed to the addresses
    `rules` (default `audit.DEFAULT_RULES`, which is what `atoo
    watch` runs) actually read.

    `conditions` is the validated watch-condition list behind any
    `WATCH:*` rule in `rules` (`watch_conditions.parse_watch_conditions`).
    A `WATCH:*` rule whose condition is not in that list is treated as
    unknown, and an unknown rule widens the scope to the whole plan --
    see the module docstring."""
    rule_list = list(DEFAULT_RULES if rules is None else rules)
    full = tuple(audit.console_read_plan(**plan_kwargs))

    patterns: list[str] = []
    unscoped: list[str] = []
    for rule in rule_list:
        rule_patterns = rule_address_patterns(rule, conditions)
        if rule_patterns is None:
            unscoped.append(rule.id)
        else:
            patterns.extend(rule_patterns)

    if unscoped:
        return ScopedReadPlan(full, full, tuple(unscoped),
                              reads_source_names=True,
                              reads_expansion_bays=True,
                              reads_talkback=True,
                              reads_aes50_outputs=True)

    compiled = _compile(patterns)
    plan = tuple((address, value_type) for address, value_type in full
                 if any(rx.match(address) for rx in compiled))
    return ScopedReadPlan(plan, full, reads_source_names=SOURCE_NAME in patterns,
                          reads_expansion_bays=EXPANSION_BAY in patterns,
                          reads_talkback=TALK in patterns,
                          reads_aes50_outputs=AES50_STATUS in patterns)


def _format_seconds(seconds: float) -> str:
    return f"{seconds:.1f}s"


def _verdict(seconds: float) -> str:
    low, high = RESPONSIVENESS_BUDGET_SECONDS
    if seconds <= low:
        return "inside the 3-4s budget"
    if seconds <= high:
        return "at the edge of the 3-4s budget"
    return "OVER the 3-4s budget"


def scope_report(
    scopes: Sequence[tuple[str, ScopedReadPlan]] | None = None,
) -> str:
    """The requested measurement, as text: how big each scope
    is and what it would cost down each of the two read paths, at the
    rates A11 measured on hardware.

    With no argument it reports the scopes that answer the question --
    the full plan, `watch`'s real rule set, and the two watch-conditions-
    only cases that show what scoping could buy if the structural rules
    were not running."""
    if scopes is None:
        scopes = default_scopes()
    full_size = len(scopes[0][1].full) if scopes else 0
    lines = [
        "watch read-scope measurement",
        f"  rates measured on a WING Compact,"
        f" net of {A11_UNANSWERED_ADDRESSES} unanswered addresses"
        f" x {UNANSWERED_ADDRESS_COST_SECONDS:g}s:",
        f"    per-leaf GET   {PER_LEAF_SECONDS_PER_ADDRESS * 1000:.2f} ms/address",
        f"    node-dump path {NODE_DUMP_SECONDS_PER_REQUEST * 1000:.2f} ms/request",
        "",
        f"  {'scope':<48} {'addresses':>11} {'per-leaf':>9} {'bulk':>7} {'reqs':>5}",
    ]
    for label, scoped in scopes:
        share = f"{len(scoped.plan) / full_size:.0%}" if full_size else "-"
        lines.append(
            f"  {label:<48} {len(scoped.plan):>5} ({share:>4}) "
            f"{_format_seconds(scoped.per_leaf_seconds):>9} "
            f"{_format_seconds(scoped.node_dump_seconds):>7} "
            f"{scoped.node_dump_requests:>5}")
    lines.append("")
    for label, scoped in scopes:
        lines.append(f"  {label}: per-leaf {_verdict(scoped.per_leaf_seconds)}; "
                     f"node dumps {_verdict(scoped.node_dump_seconds)}.")
    return "\n".join(lines)


#: A WING Compact reading its own panel -- the desk A11 was captured on,
#: and the shape every number in this module and in
#: the requirements is quoted for.
COMPACT_PLAN_KWARGS = dict(input_sockets={"LCL": 24}, output_sockets={"LCL": 8})

#: A watchlist of the shape a show bundle's `watch.json` carries -- one
#: condition of each field that has its own address family. (The send and
#: phantom fields read every strip's sends and each jack's 48V, which the
#: structural rules `watch` runs already keep, so they widen no scope that
#: has them.)
REALISTIC_CONDITIONS: tuple[dict, ...] = (
    {"id": "crowd-mic-never-muted", "channel": "Crowd Mic", "field": "muted"},
    {"id": "crowd-mic-fader-capped", "channel": "Crowd Mic", "field": "fader_db"},
    {"id": "kick-in-drums-dca", "channel": "Kick", "field": "dca"},
    {"id": "spare-in-fx-mutes", "channel": "Spare", "field": "mute_group"},
    {"id": "talkback-patch", "channel": "Talkback", "field": "patch"},
)

#: The smallest watchlist there is: one condition, one scalar field.
MINIMAL_CONDITIONS: tuple[dict, ...] = (REALISTIC_CONDITIONS[0],)


def default_scopes() -> list[tuple[str, ScopedReadPlan]]:
    """The four scopes that answer the question, for a Compact."""
    from atoo.watch_conditions import build_watch_rules

    realistic = list(REALISTIC_CONDITIONS)
    minimal = list(MINIMAL_CONDITIONS)
    realistic_rules = build_watch_rules(_as_conditions(realistic))
    minimal_rules = build_watch_rules(_as_conditions(minimal))
    full = tuple(audit.console_read_plan(**COMPACT_PLAN_KWARGS))
    return [
        ("full read plan (no scoping)", ScopedReadPlan(full, full)),
        ("watch: DEFAULT_RULES + realistic watchlist",
         scoped_read_plan(rules=list(DEFAULT_RULES) + realistic_rules,
                          conditions=realistic, **COMPACT_PLAN_KWARGS)),
        ("watch: DEFAULT_RULES + minimal watchlist",
         scoped_read_plan(rules=list(DEFAULT_RULES) + minimal_rules,
                          conditions=minimal, **COMPACT_PLAN_KWARGS)),
        ("watch conditions ONLY, realistic (hypothetical)",
         scoped_read_plan(rules=realistic_rules, conditions=realistic,
                          **COMPACT_PLAN_KWARGS)),
        ("watch conditions ONLY, minimal (hypothetical)",
         scoped_read_plan(rules=minimal_rules, conditions=minimal,
                          **COMPACT_PLAN_KWARGS)),
    ]


def _as_conditions(sketches: Sequence[dict]) -> list[dict]:
    """Fill a `(id, channel, field)` sketch out into a condition the
    validator accepts, so the report's watchlists are real conditions
    rather than a second, looser shape of the same thing."""
    from atoo.watch_conditions import parse_watch_conditions
    import json as _json

    defaults = {
        "muted": ("==", False),
        "fader_db": ("<=", -10.0),
        "dca": ("==", "Drums"),
        "mute_group": ("!=", "FX"),
        "patch": ("==", "LCL 3"),
    }
    out = []
    for sketch in sketches:
        operator, value = defaults[sketch["field"]]
        out.append({
            "id": sketch["id"],
            "description": f"{sketch['channel']} {sketch['field']} check",
            "channel": sketch["channel"],
            "field": sketch["field"],
            "operator": operator,
            "value": value,
            "severity": "warning",
        })
    return parse_watch_conditions(_json.dumps({"watch_conditions": out}),
                                  source="<watch_scope report>")


if __name__ == "__main__":  # pragma: no cover
    print(scope_report())
