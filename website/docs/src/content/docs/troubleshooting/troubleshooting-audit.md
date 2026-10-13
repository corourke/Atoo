---
title: "Troubleshooting: audit and watch"
description: "What a finding from audit or watch means when the cause is not obvious, and what to do when a reading looks wrong or slow."
sidebar: 
  order: 5
---

<!-- Generated from docs/user/troubleshooting-audit.md by tools/port_user_docs.py. Edit it there, then re-run the port. -->
What a finding from `audit` or `watch` means when the cause is not
obvious, and what to do when a reading looks wrong or slow.

## `audit` or `watch` says `C003`

The same fault, found on a desk that already has it: a show applied
before `apply` checked for it, a patch made by hand at the desk, or a
card pulled after the show went in. The three things to check are the
ones for [`apply` says the console has nothing in a
bay](/troubleshooting/troubleshooting-desk/#apply-says-the-console-has-nothing-in-a-bay).

```
$ atoo audit --state mod.state.json
Audit findings: 1 error, 1 info.

[ERROR] C003 Patch Uses An Empty Expansion Bay
  CH 40 "Podium" is patched from MOD 1, but /$syscfg/opt_mod reports 'NONE': there is nothing in that bay, so no audio passes. The desk accepts and shows this patch without complaint.

[INFO] CH001 Channel Not In Any DCA
  CH 40 "Podium" is in use but belongs to no DCA group.
...
```

It is an error, so `audit` exits `1`. A live run asks the desk about a
bay only when something on it is patched from or routed to that bay, so
a desk that uses neither pays nothing for the check.

A capture that was taken without the bay's reading cannot answer the
question, and the audit says so instead of passing quietly. The line
comes just above the socket summary:

```
Expansion bay MOD (/ch/40/in/conn/grp) is in use but /$syscfg/opt_mod was not read: C003 (Patch Uses An Empty Expansion Bay) could not check it.
```

## A channel is silent but its patch is right: `C004`

A WING channel has two input patches, a main one and an alternate, and a
switch between them. The alternate is how virtual soundcheck works: the
show is recorded to the WLIVE card and played back into the channels
from there. A channel left on its alternate afterwards hears the card,
not the stage — and its main patch, which is what the desk's patch
screen and every other check show you, still looks exactly right.

```
$ atoo audit --state alt.state.json
Audit findings: 1 warning, 1 info.

[WARNING] C004 Channel On Its Alternate Input
  CH 12 "Kick In" is listening to its alternate patch from CRD, not its main patch (AES50-A 1). After a virtual soundcheck this is a channel that does not hear the stage; switch it back on the desk if the show is live.

[INFO] CH001 Channel Not In Any DCA
  CH 12 "Kick In" is in use but belongs to no DCA group.
...
```

It is a warning, not an error, because during a virtual soundcheck it is
exactly what you want; `audit` exits `0`. Switch the channel back to its
main input on the desk. A capture taken before this check existed has no
reading of the switch, and the rule then says nothing either way.

`atoo apply` puts every strip it builds back on its main input, so
after an apply this finding means somebody switched the strip since.
The desk's **global** alternate switch is reported separately, once for
the desk, as `C005 Global Alternate Switch Engaged`: it moves every
strip set to follow it without any strip's own switch changing, so
`C004` cannot see it. Switch it off on the desk; `apply` never writes
it.

## An effect is on the strip but you cannot hear it: `E001`, `E002`

A WING effect is heard only through an **insert**: the strip's pre- or
post-insert names an FX slot (`FX1`-`FX16`), and the slot holds the
effect. There is no FX send and return. So the insert button can be lit
on a vocal channel while the slot it names is empty, and a reverb can be
loaded in a slot that no strip inserts. Either way the mix sounds dry,
and nothing on the strip itself looks wrong.

```
$ atoo audit --state fx.state.json
Audit findings: 1 warning, 2 info.

[WARNING] E001 Insert On An Empty FX Slot
  CH 3 "Lead Vox"'s pre-insert is on and names FX4, which has no effect loaded. Nothing is processing this strip; load the effect into FX4 or point the insert at the slot that has it.

[INFO] CH001 Channel Not In Any DCA
  CH 3 "Lead Vox" is in use but belongs to no DCA group.

[INFO] E002 FX Loaded But Not Inserted
  FX5 (DE-S2) has an effect loaded, but no channel, aux, bus, Main or Matrix inserts it, so nothing is heard through it.
...
```

Here the de-esser went into FX5 but the insert still names FX4. Point
the insert at FX5 on the desk and both findings go. The E001 warning
leaves `audit` exiting `0`, because audio still passes.

A third rule, `E003`, reports an insert that names a loaded slot but
is switched off, meaning the effect is bypassed. It is only INFO, since
engineers bypass effects on purpose. A capture taken before these checks
existed has no reading of the inserts, and all three rules then stay
silent.

**An FX bus your plan set up from a bus preset** is checked against the
plan instead: `CV015 FX Bus Effect Contradicts Plan` is a WARNING when
its insert is switched off, names another engine, or the engine holds
another effect than the bus preset's ([Bus presets](/build/bus-presets/)).
`audit` runs it when given the plan, and Watch runs it from the open
show's plan, with two more plan checks: a channel cut off from every
planned route (CV016) and a mute the plan does not have (CV017)
([Watching from the command line](/watch/watch/)). On that bus E001 and E003 then stay quiet in `audit`,
so the problem is said once.

## The band cannot hear talkback: `T001`

Talkback is two settings on a WING, and it takes both. **Assign** picks
the strip the talk mic comes through (`CH40` or `AUX8`). Then **TALK A**
and **TALK B** each pick which busses, Matrices and Mains they reach when
pressed. Talkback that is assigned but has no destinations on either
button looks set up and reaches nobody:

```
$ atoo audit --state talk.state.json
Audit findings: 1 warning.

[WARNING] T001 Talkback Goes Nowhere
  Talkback is assigned to CH40, but neither TALK A nor TALK B is routed to any bus, Matrix or Main, so pressing either reaches nobody. Pick TALK A's destinations (and TALK B's, if it is used) on the desk's talkback page.
...
```

On the desk's talkback page, turn on the monitor busses TALK A should
reach, and the finding goes. One destination on either button is enough.
It is a warning, so `audit` exits `0`. Talkback left unassigned is the
factory setting and says nothing. A read only asks where TALK A and B
go when talkback is assigned, so an unassigned desk pays for one address
and no more.

**The talk mic's own strip is left out of the mix checks.** A talk mic
is normally kept out of the mix: fader down, in no DCA. So when
talkback is assigned, `audit` does not report that strip as "in no DCA"
(`CH001`) or "fader at floor" (`L002`). It says once that it did
this, so the exemption is never silent:

```
[INFO] T002 Talkback Strip Left Out Of Mix Checks
  CH 40 "TALKBACK" is the strip talkback is assigned to (CH40), so it is treated as the talk mic: 'in no DCA' (CH001) and 'fader at floor' (L002) are not reported for it.
```

## Talkback and a band input on one strip: `CV014`

With `--plan`, `audit` also checks that talkback's strip is free. When
talkback is assigned to `CH40` and the plan puts an input on channel 40,
the talk mic and that input share one strip. The same goes for `AUX8`
and aux 8. On this desk talkback does reach a monitor bus, so `T001`
stays quiet, and channel 40 carries the plan's `Tom 3`:

```
$ atoo audit --state tom3.state.json --plan plan.json
Audit findings: 1 warning, 1 info.

[WARNING] CV014 Talkback Strip Holds A Plan Input
  Talkback is assigned to CH40, and the plan puts 'Tom 3' on ch 40, so the talk mic and that input share one strip. Move the input off ch 40, or set talkback's assign to OFF or the other strip on the desk's talkback page.

[INFO] T002 Talkback Strip Left Out Of Mix Checks
  CH 40 "Tom 3" is the strip talkback is assigned to (CH40), so it is treated as the talk mic: 'in no DCA' (CH001) and 'fader at floor' (L002) are not reported for it.
...
```

The INFO is the exemption above, applied to a strip that is really a tom.
It goes once channel 40 is empty again.

Move the input to another channel in the input list and rebuild, or
change the assign on the desk. If channel 40 in the plan *is* the talk
mic, name it so: an entry whose name or source starts with "talk"
(`Talkback`, `Talk Mic`), or is `TB` or `T/B`, is taken as the talk mic
and says nothing.

## `audit` or `watch` says rules "could not be checked"

```
Coverage: no output sockets read -- R002, R003, R004, R005, R006 and CV009 could not be checked.
```

That is `watch`'s one-line form; `audit` says the same in a sentence
after its `Physical sockets read:` line. If no input sockets were read
either, C001 (phantom power on an unpatched socket) joins the list.

Nothing is broken. The six output rules are all about the **output patch** —
which bus, Main or Matrix feeds which physical jack — and this run never
read it, so they declined to answer rather than guess.

That happens when both of the sources that know what jacks the desk has
come up empty: no `--plan` naming the sockets it patches, and a console
whose model string Atoo does not recognise, so it cannot look up the
panel. It is the normal case for `--state` captures taken before those
sockets were being read at all.

**Give it the sockets and the rules come back.**

```bash
atoo watch --console 192.0.2.16 --output-sockets LCL=8
```

or point the run at the plan for the show, which names every socket it
patches, stage boxes included.

**A partial read is still a read.** The rules only stand down when *no*
output socket was read. If you named `LCL` and the mix goes out on a
card, they will run and they may well fire — the coverage line tells you
what was covered, and that is the thing to check first.

## `audit` says "No findings" on a console that is visibly wrong

Kick and snare are crossed at the stage box. The desk has Kick on
`LCL 2` and Snare on `LCL 1`, and it sounds wrong from the first hit.
`audit` still passes:

```
$ atoo audit --state swapped.state.json
No findings -- every rule in this audit passed.

Physical sockets read: in LCL 1-2; out LCL 1.
```

**Without `--plan`, `audit` checks that the desk works, not that it is
your show.** Every rule it runs alone is structural: a bus nothing feeds,
48V on a socket with nothing patched, a mix that reaches no loudspeaker.
Two channels on two different sockets, both reaching Main, break none of
those. Nothing on the desk says which socket the kick mic is plugged
into; only your input list says that.

**Give it the plan, and it compares the desk against what you asked
for:**

```
$ atoo audit --state swapped.state.json --plan swapped.plan.json
Audit findings: 2 warning.

[WARNING] CV005 Patch Contradicts Plan (2)
  CH 1 "Kick": plan says patched to LCL 1, live console reads LCL 2. (plan provenance: Input list: LCL 1)
  CH 2 "Snare": plan says patched to LCL 2, live console reads LCL 1. (plan provenance: Input list: LCL 2)

Physical sockets read: in LCL 1-2; out LCL 1.
```

Both exit `0`, because a WARNING does not fail the run. Against a live
desk the command is the same with `--console` in place of `--state`, or
`atoo audit --show DIR` on a bundle, which picks up the bundle's
`plan.json` by itself.

If a plan is already there and the finding still does not appear, check
these, in this order:

- **The plan does not state it.** The comparison covers what a plan
  states: patch, mute, fader, DCA and mute-group membership, bus sends,
  routes to Main, and trim, balance, invert and head-amp gain. It does
  not cover the filters, the parametric EQ or the compressor yet
  (`atoo audit --help` names them), so a wrong EQ passes.
- **The finding was withheld.** With `--plan`, a finding about a strip
  the plan never mentions is left out, unless its rule matters on any
  desk. `S001 Findings Withheld From This Report`, at the end of the
  report, counts what was withheld and why. Run it again without `--plan` to see
  all of them.
- **That part of the desk was never read.** The `Physical sockets read:`
  line at the foot of the report lists the sockets this run covered. A
  patch on a socket outside that list is not checked, and neither is
  anything left out with `--channels`, `--buses` and the other count
  flags. See [the section above](#audit-or-watch-says-rules-could-not-be-checked).
- **No rule covers it.** Some things are left out on purpose. Listenback
  is one, and word clock against the expansion bays is another. The
  "What is not covered" list in
  `audit-rules.md`
  says why for each.

## `audit` or `watch` reports a duplicate name that is not on the desk

```
[WARNING] N001 Duplicate Channel/Aux Names
  2 channel/aux strips share the name 'Acoustic': CH 4, CH 7.
```

— and the desk plainly shows one channel called "Acoustic" and one called
"Acoustic 2".

A WING strip normally displays the name of the **socket** it is patched
to, not its own (the desk's "Link Customization to Source" switch,
`clink`, which is on from the factory). Rename a channel on the desk and
the name goes to the socket; whatever was on the strip stays there and
goes stale. Repatch that channel to a different socket and the two
disagree.

Atoo reads that switch and prefers whichever name the desk is
actually showing. **So a duplicate it reports is a real collision** — two strips the desk
really is showing the same name for.

One case that is deliberately *not* a collision: two strips fed from one
socket, a festival split or a monitor feed. That is one name in one
place, and `C002 Shared Physical Input` reports it as what it is.

## `audit` or `watch` looks like it has hung

**Look for the `read N/…` progress line before you stop it.** Every live
read prints one on stderr, and while it moves, the run is working. This
one was captured on a WING Compact by a version whose read counted to
300; today's counts to about 323:

```
  read 120/300 (40%) 2s -- /io/in/USR/44 (node)
```

**Five seconds or less is normal** for a WING Compact, read a whole object
at a time. With `--per-leaf`, one request per address, about two minutes
is normal.

**No progress line at all** means you passed `--no-progress`, or the desk
never answered, in which case stderr says so and
[`atoo ping`](/troubleshooting/troubleshooting/#atoo-cannot-reach-the-console)
is the next step.

**A line that moves slowly, or sits on one address,** means the desk is
not answering some addresses. Each silent one is asked three times and
costs about 3 seconds at the default `--timeout`, though several silent
at once wait side by side, so a handful costs about 3 seconds between
them. The read counts them
at the end and names the first ten:

```
  read: 6112 of 6112 addresses in 0.9s
  3 address(es) went unanswered, about 0s of the time above. Those values are unknown -- not defaults.
  unanswered: /ch/5/fdr, /bus/2/name, /io/out/LCL/3/grp
```

Those values are reported as unknown, never as defaults. `--raw-log
FILE` records every request and reply, line by line, so it survives a
read you stop with Ctrl-C. A `(node)` on an address means a whole-object
request went unanswered; the read then falls back to that object's
values one at a time, so nothing is lost but time.

When three addresses of the same kind (`/fx/{n}/mdl`, say) go unanswered
while the desk answers everything else, the read stops asking for the
rest of that kind and says so in an `INFO: stopped asking for …` line.
If that line names something your desk does have, such as a fader or a
send level, the link is slow or lossy: run the read again, and report
it in an issue.

Ways out, in this order:

| Try | What it does |
|---|---|
| `--timeout 0.3` | cuts each silent request from 3s to 0.9s; changes nothing for a desk that answers |
| `--per-leaf` | only if the `(node)` requests go unanswered: skips them, at about two minutes a read ([Checking a desk](/watch/audit/#reading-by-object-and---per-leaf)) |
| drop `--per-leaf`, if you passed it | about 323 requests instead of 6,143: ~5s or less instead of ~2 minutes |
| fewer objects (`--channels 16`, `--matrices 0`) | last resort: a rule that goes quiet because you narrowed the read is still a rule that went quiet, though the report says what it covered |

## See also

- [Troubleshooting](/troubleshooting/troubleshooting/) — every symptom, and the page it is on
- [Checking a desk](/watch/audit/) — `atoo audit`
- [Watching from the command line](/watch/watch/) — `atoo watch`
- `docs/developer/audit-rules.md` — every rule ID
