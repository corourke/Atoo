---
title: "Checking a desk: atoo audit"
description: "A desk that has been through soundcheck, a changeover and three engineers is rarely what anyone thinks it is: phantom on an empty socket, a bus nobody sends to, a DCA pulled to the floor with the…"
sidebar: 
  order: 4
---

<!-- Generated from docs/user/audit.md by tools/docs_to_starlight.py in the development repository. Edit it there. -->
A desk that has been through soundcheck, a changeover and three
engineers is rarely what anyone thinks it is: phantom on an empty socket,
a bus nobody sends to, a DCA pulled to the floor with the band in it.
`atoo audit` reads the desk once and reports what does not add up.

**It never writes to a console.** It needs no plan, input list,
conventions file or model; a plan is optional and asks a second question
([below](#auditing-against-your-plan---plan)). To run the same check on a
loop during a show, see [Watching from the command line](/watch/watch/).

Every transcript on this page runs against a captured state file, with
no console attached, from the frozen copies under
`docs/user/demo/audit-demo/` in the repository:

```bash
cd docs/user/demo/audit-demo
```

## One read


```bash
atoo audit --state audit_demo_state.json
```

`audit_demo_state.json` is a hand-built capture of what a live console
read looks like, with a handful of faults seeded on purpose. Against a
real desk, swap `--state FILE` for `--console 192.0.2.16`.

```
Audit findings: 7 warning, 8 info.

[WARNING] C001 Phantom Power On Unpatched Socket
  48V is on for LCL 9 but nothing is patched to it -- no channel, no aux and no user patch.

[WARNING] CH002 DCA Fader Low With Active Members
  DCA 1 "Drums" is at the floor (-20dB or lower) but controls 2 active member(s): CH 1 "Kick", CH 2 "Snare".

[WARNING] L001 Send On But Near-Silent
  CH 2 "Snare"'s send to BUS 1 is on at -105dB -- audible in principle, in practice dead.

[WARNING] N001 Duplicate Channel/Aux Names
  2 channel/aux strips share the name 'Vocal': CH 3, CH 4.

[WARNING] R001 Bus No Inputs
  BUS 3 "FX" is in use but no strip has an active send to it.

[WARNING] R002 Bus No Output (2)
  BUS 2 "Monitor 1", BUS 3 "FX"
  Each is in use but has no route to a physical output -- not directly, not through a Main, and not through a Matrix.

[INFO] C002 Shared Physical Input
  LCL 5 feeds more than one strip: CH 5 "Bass", CH 6 "Bass DI".

[INFO] CH001 Channel Not In Any DCA (5)
  CH 3 "Vocal", CH 4 "Vocal", CH 5 "Bass", CH 6 "Bass DI", CH 7 "Playback"
  Each is in use but belongs to no DCA group.

[INFO] CH003 Mute Group Active, Silencing Routed Members
  MGRP 1 "Vocals" is engaged and is silencing 1 active member(s): CH 3 "Vocal".

[INFO] L002 Active Strip Fader At Floor
  CH 7 "Playback" is unmuted and in use, but its own fader is at -144dB.

Physical sockets read: in LCL 1-9; out LCL 1.
```

**Strips are named the way the desk names them** -- `CH 3 "Vocal"`,
`BUS 2 "Monitor 1"`, `DCA 1`, `MGRP 1` (a mute group), and a socket as
`LCL 9` -- with the name the desk is showing in quotes.

**A rule that fires on several strips is one entry**, with the count in
brackets: `CH001 ... (5)` above is five channels, listed once, and the
sentence they share is said once. Where the strips differ in something
you would act on -- a level, a socket -- each keeps its own line under
the one heading. The count on the first line is still per finding: 15,
not 10.

**The last line is not a finding — it is what the reading covered.** Some
rules can only answer for sockets that were actually read, and a report
that quietly skipped them would look exactly like one that ran them and
found nothing. See ["Socket counts, and when you need to say
them"](#socket-counts-and-when-you-need-to-say-them) below.

A clean desk says so and says nothing else:

```
No findings -- every rule in this audit passed.
```

**Every finding cites the rule it broke**, by an ID that does not change
when the wording does: `CH002` above. Quote it in a bug report;
`docs/developer/audit-rules.md` lists them
all. No rule guesses what a channel is from its name: every rule works
from the desk's routing, patch, mute and fader values.

**`audit` exits `0` on warnings and info, and `1` on an error**, or
when it could not run at all (a missing `--state` file, a desk that did
not answer). Stdout tells them apart: a run that found errors prints its
`Audit findings:` line there, and one that could not start prints only
to stderr. This is not the `2` that `build`, `verify` and `apply` use;
see the [exit-code table](/reference/cli-reference/#exit-codes).

## How long a live read takes, and what it prints while it works

A read of a live WING Compact takes **about five seconds** at most: some
6,000 values, fetched a whole channel, bus or socket at a time. That was
timed one request at a time. Reads now keep several requests on the wire
at once (8 by default; see [A desk read is
slow](/troubleshooting/troubleshooting-desk/#a-desk-read-is-slow)), which should make it
shorter, and has not yet been timed on a desk. It is the
slowest thing Atoo does. A progress line on **stderr** names the
address in flight, so stdout stays a clean report; `--no-progress` turns
it off.

- **If the line sits still,** that address is not being answered. Each
  one costs 3 seconds (three tries at the `--timeout`); `--timeout 0.3`
  cuts that without changing anything on a desk that answers.
- **"went unanswered" is not "off" or "empty".** Those values are not in
  the report at all. On a healthy desk the count is zero; hundreds means
  something is wrong. `--raw-log FILE` records every request and reply.
- **A kind of address that goes silent is cut short**, with an
  `INFO: stopped asking for ...` line. See [`audit` or `watch` looks
  like it has hung](/troubleshooting/troubleshooting-audit/#audit-or-watch-looks-like-it-has-hung).

## Reading by object, and `--per-leaf`

A read asks for whole objects by default. `--per-leaf` asks for every
address on its own instead, which takes about two minutes on a Compact. Use it to rule the whole-object read out
when a value in a report looks wrong, or on a network that misbehaves
with the larger replies. `watch`, `patch` and `amend` take it too.

## Keeping the reading: `--dump-state`

A live read costs desk time, and its report is only one view of it. Save
the reading itself, and it can be audited again later with no console —
against a different plan, after a rule has been fixed, or by someone who
was not at the desk:

```
atoo audit --console 192.0.2.16 --dump-state tonight.state.json
atoo audit --state tonight.state.json --plan my_show_plan.json
```

The file is written as soon as the read finishes, before any rule runs.
It does not record which WING model it came from, so pass the `--plan`
when you replay it: its console model is used. `--dump-state` saves a
live read only, and is refused with `--state`.

## Socket counts, and when you need to say them

Two families of rule need to know which physical sockets the desk
actually has: phantom power on the input side, output patching on the
output side.

You usually do not have to say. Atoo reads the panel of whichever
model the desk states it is when it connects — on a Compact that is local
inputs 1-24 and local outputs 1-8 — and, if you gave it a plan, every
socket group that plan patches, which is how it learns about the stage
box on AES50-A that no console model table could know about.

Pass the flag when your rig has something neither of those covers — a
card, or a stage box the plan does not mention:

| flag | what it covers |
|---|---|
| `--input-sockets LCL=24,A=48` | phantom-power rules, for those groups |
| `--output-sockets LCL=16` | physical output-patch rules, for those groups |

Either flag replaces the derived list for its own direction rather than
adding to it, so name everything you want read.

**Every run tells you which sockets it read**, at the end of the audit
report or under `watch`'s baseline:

```
Physical sockets read: in LCL 1-24, A 1-20; out LCL 1-8.
```

and, if it read none — no plan, and a desk whose model it does not
recognise — it names the rules that therefore did not run rather than
leaving you to read their silence as an all-clear:

```
Physical sockets read: none. R002 (Bus No Output), R003 (Matrix Orphan), R004 (Main Patched But Unfed), R005 (Main Not Patched), R006 (Matrix Fed But Not Patched), CV009 (Undeclared Physical Output Patch) and C001 (Phantom Power On Unpatched Socket) could not be checked -- with no output patch in hand, "reaches no physical output" is a question nobody asked rather than an answer.
```

Those rules stand down only when no output socket was read at all. A
partial read still runs them, and the line says what it covered.

`watch` says the same in one `Coverage:` line, before its baseline and
under every change, and the browser's Watch shows it above the table. If
you care about those rules, give the run an `--output-sockets` list.

## Following a signal: `--trace-from` / `--trace-to`

A different question again: not "is anything wrong" but "why can I not
hear this". Give it two endpoints and it walks the routing graph between
them. The answer prints after the usual audit report, which is elided
here:

```bash
atoo audit --state audit_demo_state.json --trace-from input:LCL:1 --trace-to output:LCL:1
```

```
Audit findings: 7 warning, 8 info.
...
Physical sockets read: in LCL 1-9; out LCL 1.
OK: input:LCL:1 reaches output:LCL:1 via input:LCL:1 -> strip:/ch/1 -> bus:1 -> main:1 -> output:LCL:1
```

When it does not reach, the answer is **how far it got and what stopped
it**, which is the part you cannot see from the surface of a desk:

```bash
atoo audit --state audit_demo_state.json --trace-from input:A:1 --trace-to output:LCL:1
```

```
Audit findings: 7 warning, 8 info.
...
Physical sockets read: in LCL 1-9; out LCL 1.
BROKEN: input:A:1 does not reach output:LCL:1.
  Reached: input:A:1 -> strip:/ch/7
  First break: /ch/7's fader is at the floor (-144dB)
```

A path that was never built at all reads differently from one that is
built and muted:

```bash
atoo audit --state audit_demo_state.json --trace-from input:LCL:3 --trace-to output:LCL:1
```

```
Audit findings: 7 warning, 8 info.
...
Physical sockets read: in LCL 1-9; out LCL 1.
BROKEN: input:LCL:3 does not reach output:LCL:1.
  Reached: input:LCL:3
  First break: no routing path exists from input:LCL:3 to output:LCL:1 at all
```

Endpoints are written `input:GROUP:N`, `output:GROUP:N`, `strip:/ch/12`,
`bus:3` or `main:1`.

## Auditing against your plan: `--plan`

Everything above asks whether the desk is internally consistent. `--plan`
asks a second question: **does this desk match what this show's plan says
it should be?**

```bash
atoo audit --state audit_demo_state.json --plan audit_demo_plan.json
```

```
Audit findings: 5 warning, 3 info.
```

**Fewer than the fifteen you got without it, not more.** `--plan` both
adds and subtracts, and the subtraction is covered further down. Two
findings go on top of the structural ones, and the first is the reason to
do this at all:

```
[WARNING] CV006 Bus Send Contradicts Plan
  CH 1 "Kick": plan says send to Drums is -6dB, live console reads 0dB (tolerance 0.5dB). (plan provenance: Busses: Drums (post, -6dB))
```

It quotes **the plan's own provenance** — the line of your conventions
that asked for `-6dB` — rather than just two numbers. That is what a diff
against a plan buys you over a diff against nothing.

```
[WARNING] CV009 Undeclared Physical Output Patch
  LCL 1 is patched to MAIN 1 on the live console, but no bus or output in the plan routes anywhere to this socket -- likely leftover from an earlier apply, a different show, or manual patching.
```

That one catches leftovers: a socket patched by last week's show that
this plan never routes to. `atoo apply --clean-output-sockets` is
what actually disconnects one; the audit only reports it.

`--plan` covers mute, fader level, DCA and mute-group membership, patch,
bus sends, direct-to-Main routes, and a narrow trim/balance/invert/
head-amp-gain slice of processing. Two of its checks are about drift and
are what [Watch](/watch/watch/) runs from the plan too: a channel whose every
planned send and Main route is off (CV016), and a channel, bus, DCA,
Main or Matrix the plan leaves unmuted that is muted on the desk
(CV017). The filter family, the parametric EQ
and the compressor are **not** diffed yet — see
`docs/developer/audit-rules.md` for the
field-by-field table. `--plan` also works with `--console`, and with
`--show` it comes from the [show bundle](/build/show-bundles/).

### What `--plan` stops saying, and why it tells you

A house rig has forty channels; your show uses nineteen. Without a plan
the audit comments on all forty, and a note about a strip you never
touched is the kind of line that makes people stop reading.

So when you give it a plan, it stops commenting on strips, busses and
sockets the plan never mentions, and on anything the plan itself states
(a fader your plan puts at `-inf` is not a fault; the plan diff above
already checks it).

**What it never stops saying is anything dangerous**, on any strip,
yours or not: 48V live on a socket nobody patched, a mix that reaches no
loudspeaker, a matrix feeding an output with nothing in it, a mute group
silencing something that is routed — and a strip that is routed, unmuted
and sitting at the floor, which is the classic "why can't I hear it" and
is *more* worth saying about a strip that is not part of your show, not
less.

And it never does it quietly. Whatever it held back is counted, named
and explained at the end of the report:

```
[INFO] S001 Findings Withheld From This Report
  10 finding(s) are not listed above because a plan was supplied: 1 C002 (1 about an object the plan never mentions); 5 CH001 (5 about an object the plan never mentions); 1 L001 (1 about an object the plan never mentions); 1 N001 (1 about an object the plan never mentions); 2 R002 (2 about an object the plan never mentions). Re-run the same audit with no plan to see every finding the rules produced.
```

Drop `--plan` and you get all fifteen back. A shorter report should never
be something you can mistake for a clean desk.

## See also

- [Watching from the command line](/watch/watch/) — the same rules on a loop
- [Troubleshooting](/troubleshooting/troubleshooting/) — when it cannot reach the console
- `docs/developer/audit-rules.md` — every rule ID
- [Command reference](/reference/cli-reference/) — every flag, generated from the code
