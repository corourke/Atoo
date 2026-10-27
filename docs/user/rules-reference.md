<!-- GENERATED FILE -- edit the preamble block only.

     Every rule below comes from the rule catalogue in the code, by a
     script in the development repository. Editing a rule here by hand
     will be overwritten there.

     Text inside the `<!-- preamble:start/end -->` block IS hand-written
     and is preserved across regeneration.
-->

# Rules reference

<!-- preamble:start -->
Every rule `atoo audit` and Watch can report, listed by its code. A finding ends with the code of the rule that produced it (`R005`, `CV016`), so this is where to look one up: what the rule checks, how serious it is, and whether it needs the show's plan.

Each rule says:

- **Its severity.** An **Error** is a desk that cannot work as it stands, a **Warning** is probably not what you meant, and an **Info** is worth knowing but needs nothing done. [Reading findings](reading-findings.md) has more on each.
- **When it runs.** *With or without a plan* means it reads the desk alone, in `atoo audit` and in Watch. *Needs the plan* means it compares the desk with the show's plan, so it runs only when you give it one: `atoo audit --plan`, and Watch started with the show. *Watch only* means it speaks during a live Watch.
- **What to do about it**, where the [troubleshooting page](troubleshooting-audit.md) has a section for it.

With a plan, a finding about a strip the plan never mentions can be left out, and a rule stands down where the plan states the setting it would judge, because the comparison with the plan checks that instead. `S001` counts what was left out, and why. Findings whose code starts `WATCH:` come from your own [watch conditions](watch-conditions.md), and say in their own words what they check.

**"In use"**, wherever a rule below says it, means **active**: on the open show's sheets, or in use on the desk. A channel, aux or bus is in use on the desk when it is named, patched to a socket other than the factory's, or sending, and a bus also when something sends to it. So a bus the show's sheets have is checked even before anything on the desk uses it. With no show open, only the desk counts. A watch condition can use the same test with the word `ACTIVE` ([Only active strips](watch-conditions.md#only-active-strips)).

This page is generated from the rules themselves, so it lists every one the version you are reading the docs for can report.
<!-- preamble:end -->

## Routing

Where signal goes: buses, Mains and Matrices that are fed or reach an output, strips that reach nothing, loops and splits.

### R001: Bus No Inputs

**Warning** · with or without a plan

A bus in use has no channel or aux sending to it.

### R002: Bus No Output

**Warning** · with or without a plan

A bus in use reaches no output socket, either directly or through a Main or Matrix.

### R003: Matrix Orphan

**Warning** · with or without a plan

A Matrix is patched to a physical output but nothing sends to it.

### R004: Main Patched But Unfed

**Warning** · with or without a plan

A Main is patched to a physical output but nothing sends to it.

### R005: Main Not Patched

**Error** · with or without a plan

A Main has active sends feeding it but reaches no physical output.

### R006: Matrix Fed But Not Patched

**Warning** · with or without a plan

A Matrix has an active send feeding it but is patched to no physical output.

### R007: Output Route Not Checked

**Info** · with or without a plan

A bus, Main or Matrix reaches none of the output sockets read, and an AES50 port in use was not read, so the route could not be checked.

### R008: Strip Reaches Nothing

**Warning** · with or without a plan

A channel or aux that is in use, unmuted and up has no bus send, Matrix send or Main route switched on.

[What to do about it](troubleshooting-audit.md#a-channel-is-on-named-and-up-but-you-hear-nothing-r008)

### R009: Feedback Loop

**Error** · with or without a plan

A channel or aux takes a bus, Main or Matrix as its input and its signal comes back round to it, every leg open.

[What to do about it](troubleshooting-audit.md#a-channel-feeds-itself-and-howls-or-could-r009-r010)

### R010: Feedback Loop Held Closed

**Warning** · with or without a plan

The same loop with a leg switched off or at the floor: silent today, feeding back the moment it is opened.

[What to do about it](troubleshooting-audit.md#a-channel-feeds-itself-and-howls-or-could-r009-r010)

### R011: Stereo Output Patched On One Side

**Warning** · with or without a plan

A stereo bus, Main or Matrix in use whose output patches all use the same side of its pair, so anything panned to the other side is not heard.

[What to do about it](troubleshooting-audit.md#a-bus-is-heard-on-one-side-only-or-is-not-the-width-the-plan-says-r011-cv020)

### R012: Signal Splits And Recombines

**Warning** · with or without a plan

A strip in use reaches one Main or Matrix by two or more routes, every one on and above the floor, unless the plan includes every one of those routes.

[What to do about it](troubleshooting-audit.md#a-channel-reaches-the-same-main-or-matrix-by-two-routes-r012-r013-r014)

### R013: Signal Split Asked For

**Info** · with or without a plan

A split R012 would report, said at INFO instead because the plan includes every one of its routes.

[What to do about it](troubleshooting-audit.md#a-channel-reaches-the-same-main-or-matrix-by-two-routes-r012-r013-r014)

### R014: Signal Split Through An Effect Send

**Info** · with or without a plan

A split R012 would report, said at INFO instead because every route but one passes through a bus with a reverb, delay or modulation effect inserted on it: an effect send.

[What to do about it](troubleshooting-audit.md#a-channel-reaches-the-same-main-or-matrix-by-two-routes-r012-r013-r014)

## Patch, sockets and stage boxes

What each strip is patched from, 48V, alternate inputs, expansion bays and the AES50 links to stage boxes.

### C001: Phantom Power On Unpatched Socket

**Warning** · with or without a plan

48V is enabled on a physical input patched to no channel or user patch.

### C002: Shared Physical Input

**Info** · with or without a plan

More than one channel or aux sources from the same physical input socket.

### C003: Patch Uses An Empty Expansion Bay

**Error** · with or without a plan

A channel is patched from, or an output routed to, an expansion bay the desk reports empty.

[What to do about it](troubleshooting-audit.md#audit-or-watch-says-c003)

### C004: Channel On Its Alternate Input

**Warning** · with or without a plan

A channel or aux is switched to its alternate input patch rather than its main one.

[What to do about it](troubleshooting-audit.md#a-channel-is-silent-but-its-patch-is-right-c004)

### C005: Global Alternate Switch Engaged

**Warning** · with or without a plan

The console's global alternate-input switch is engaged.

### C006: Strip In Use Has No Source

**Warning** · with or without a plan

A channel or aux that is in use has nothing patched to its main input.

[What to do about it](troubleshooting-audit.md#a-channel-is-on-and-named-but-nothing-is-patched-to-it-c006)

### C007: Strip's Input Socket Muted

**Warning** · with or without a plan

A channel or aux in use is patched to an input socket that is muted at the socket, or to one leg of a stereo source whose other leg is not.

[What to do about it](troubleshooting-audit.md#a-channel-is-silent-and-nothing-on-it-is-muted-c007)

### C008: Stage Box Not Connected Or In Error

**Error** · with or without a plan

A channel takes its input from an AES50 stage box, or an output on one carries a signal, while the desk reads that link as not connected (-) or in error (ERR).

[What to do about it](troubleshooting-audit.md#a-stage-box-is-on-the-patch-but-no-audio-comes-from-it-c008-c009-c010)

### C009: AES50 Stage Box Link Not OK

**Warning** · with or without a plan

An AES50 stage box link reads ERR, though nothing is patched to or from it.

[What to do about it](troubleshooting-audit.md#a-stage-box-is-on-the-patch-but-no-audio-comes-from-it-c008-c009-c010)

### C010: AES50 Stage Box Firmware Needs Updating

**Info** · with or without a plan

An AES50 port reads UPD: the desk flags the stage box's firmware as older than it expects.

[What to do about it](troubleshooting-audit.md#a-stage-box-is-on-the-patch-but-no-audio-comes-from-it-c008-c009-c010)

## Effects

Effects loaded into FX slots and inserted on strips.

### E001: Insert On An Empty FX Slot

**Warning** · with or without a plan

A strip's insert is switched on but names an FX slot with no effect loaded.

[What to do about it](troubleshooting-audit.md#an-effect-is-on-the-strip-but-you-cannot-hear-it-e001-e002)

### E002: FX Loaded But Not Inserted

**Info** · with or without a plan

An FX slot has an effect loaded that no strip's insert names.

[What to do about it](troubleshooting-audit.md#an-effect-is-on-the-strip-but-you-cannot-hear-it-e001-e002)

### E003: FX Inserted But Switched Off

**Info** · with or without a plan

A strip's insert names a loaded FX slot but is switched off.

## Talkback

Whether talkback reaches anyone.

### T001: Talkback Goes Nowhere

**Warning** · with or without a plan

Talkback is assigned to a strip, but neither TALK A nor TALK B is routed to any bus, Matrix or Main.

[What to do about it](troubleshooting-audit.md#the-band-cannot-hear-talkback-t001)

### T002: Talkback Strip Left Out Of Mix Checks

**Info** · with or without a plan

The strip talkback is assigned to is in use; L002, R008, C006 and C007 skip it.

## DCAs and mute groups

DCAs and mute groups that silence what they control.

### CH002: DCA Fader Low With Active Members

**Warning** · with or without a plan

A DCA's fader is low while it controls active members.

### CH003: Mute Group Active, Silencing Routed Members

**Info** · with or without a plan

An engaged mute group is silencing active members.

### CH004: DCA Muted, Silencing Active Members

**Info** · with or without a plan

A DCA's mute is on while it controls active members.

[What to do about it](troubleshooting-audit.md#a-whole-group-of-channels-is-silent-and-every-one-is-up-ch004)

## Names

Names that two strips or two buses share.

### N001: Duplicate Channel/Aux Names

**Warning** · with or without a plan

Two or more channels or auxes share a name you gave them.

### N002: Duplicate Bus Names

**Warning** · with or without a plan

Two or more buses share a name you gave them.

## Levels

Faders, sends and clipping.

### L001: Send On But Near-Silent

**Warning** · with or without a plan

Any send is enabled but pulled to within 44dB of the floor without being fully off.

### L002: Active Strip Fader At Floor

**Info** · with or without a plan

An unmuted, in-use channel, aux or bus's own fader sits at the floor.

### L003: Clipped

**Error** · Watch only

A channel, aux, bus, Main or Matrix clipped within the last minute, read from the console's meters.

## Compared with the plan

The desk against the show's plan: each rule here needs the plan, and speaks where the desk differs from what the plan states.

### CV001: Mute Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

The plan mutes a channel or aux, and it is unmuted on the desk.

### CV002: Fader Level Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

A channel or aux fader is more than 0.5dB from the level the plan states.

### CV003: DCA Membership Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

The plan puts a channel or aux in a DCA, and the desk does not have it there.

### CV004: Mute Group Membership Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

The plan puts a channel or aux in a mute group, and the desk does not have it there.

### CV005: Patch Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

A channel or aux is patched from a different input socket than the plan states, or from none.

### CV006: Bus Send Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan` and Watch

A send the plan states, from a channel or aux to a bus or Matrix, is off on the desk, in the other pre/post mode, or (in `atoo audit --plan`) more than 0.5dB from the plan's level.

[What to do about it](troubleshooting-audit.md#a-send-or-route-you-did-not-plan-cv018-cv006-cv007)

### CV007: Main Route Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan` and Watch

A channel's route to a Main is off where the plan routes it, or on where the plan has no such route.

[What to do about it](troubleshooting-audit.md#a-send-or-route-you-did-not-plan-cv018-cv006-cv007)

### CV008: Processing Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

A channel's trim, balance, polarity, head-amp gain, high-pass, hi-cut, tilt or EQ is not what the plan states.

[What to do about it](troubleshooting-audit.md#trim-gain-a-high-pass-hi-cut-tilt-or-eq-is-not-what-the-plan-says-cv008)

### CV009: Undeclared Physical Output Patch

**Warning** · needs the plan · `atoo audit --plan`

An output socket carries a signal the plan does not put there: nothing in the plan routes to that socket, or the plan routes something else to it. Often left over from an earlier show or from patching by hand.

### CV010: Bus Mute Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

The plan mutes a bus, and it is unmuted on the desk.

### CV011: Bus Fader Level Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

A bus fader is more than 0.5dB from the level the plan states.

### CV012: DCA Mute Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

The plan mutes a DCA, and it is unmuted on the desk.

### CV013: DCA Fader Level Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan`

A DCA fader is more than 0.5dB from the level the plan states.

### CV014: Talkback Strip Holds A Plan Input

**Warning** · needs the plan · `atoo audit --plan`

Talkback is assigned to channel 40 or aux 8, and the plan puts an ordinary input on that strip, so the talk mic and the input share it.

[What to do about it](troubleshooting-audit.md#talkback-and-a-band-input-on-one-strip-cv014)

### CV015: Effect Insert Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan` and Watch

An insert on a channel, bus, Main or Matrix is not what the plan sets: it names another FX slot or none, it is switched off, the slot holds another effect, or an insert the plan takes off is back on.

### CV016: Planned Routes All Off

**Warning** · needs the plan · `atoo audit --plan` and Watch

Every send and route the plan gives a channel is off on the desk, so it reaches none of the places the plan sends it.

### CV017: Muted Against Plan

**Warning** · needs the plan · `atoo audit --plan` and Watch

A channel, aux, bus, DCA, Main or Matrix is muted on the desk, and the plan leaves it unmuted.

### CV018: Send Or Route Not In Plan

**Info** · needs the plan · `atoo audit --plan` and Watch

A send or route is on at the desk that the plan does not have, such as a channel sent to a bus, Matrix or Main the plan never sends it to.

[What to do about it](troubleshooting-audit.md#a-send-or-route-you-did-not-plan-cv018-cv006-cv007)

### CV019: Phantom Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan` and Watch

48V on a channel's input socket is not what the input list's phantom column says: on where it says FALSE, or off where it says TRUE.

[What to do about it](troubleshooting-audit.md#a-condenser-is-silent-or-48v-is-on-where-it-should-not-be-cv019)

### CV020: Bus Width Contradicts Plan

**Warning** · needs the plan · `atoo audit --plan` and Watch

A bus is mono on the desk where the plan makes it stereo, or stereo where the plan makes it mono.

[What to do about it](troubleshooting-audit.md#a-bus-is-heard-on-one-side-only-or-is-not-the-width-the-plan-says-r011-cv020)

### CV021: Talkback Misses A Monitor Mix

**Warning** · needs the plan · `atoo audit --plan` and Watch

Talkback reaches some of the monitor mixes the plan builds but not this one, so whoever listens to it cannot hear you.

[What to do about it](troubleshooting-audit.md#talkback-that-misses-one-monitor-mix-cv021-cv022)

### CV022: Monitor Mixes Talkback Was Checked Against

**Info** · needs the plan · `atoo audit --plan` and Watch

Names the monitor mixes the talkback check counted, and how many talkback reaches, so a mix it did not count is plain to see.

[What to do about it](troubleshooting-audit.md#talkback-that-misses-one-monitor-mix-cv021-cv022)

## Sheets

Edits saved in Build's step 04 that the desk does not have yet.

### CV023: Sheet Differs From Desk

**Warning** · needs the plan · `atoo audit --plan` and Watch

An edit saved in Build's step 04 is not on the desk yet. The finding quotes the cell, and clears once you apply the plan, undo the edit, or set the desk to match.

## The report itself

What a report with a plan leaves out, and why.

### S001: Findings Withheld From This Report

**Info** · needs the plan · `atoo audit --plan` and Watch

With a plan, a finding about a strip the plan never mentions, or about a setting the plan states and a comparison with the plan already checks, is left out. This line counts what was left out and why, so a shorter report is never mistaken for a healthier desk.

## Watch

Notes Watch gives about the session itself, not about the desk.

### W001: Names are refreshed, not read every pass

**Info** · Watch only

Strip, bus, DCA, mute-group and input-socket names are read at Start and refreshed every few readings, so a rename shows up at the next refresh. `atoo watch --name-refresh 1` reads names every pass.

### W002: Clip detection is on, or off

**Info** · Watch only

Whether Watch is listening to the console's meters for clips (L003), and if not, why: the connection could not be made, was lost, or no meter data arrives.

### W003: Virtual soundcheck is on

**Info** · Watch only

While the desk's Virtual soundcheck switch is on, a channel on its alternate input (C004) and the global alternate switch (C005) are reported at INFO, not as warnings. Turn it off when soundcheck ends, and any still on its alternate becomes a warning at once.

### W004: The plan changed since Watch started

**Info** · Watch only

The show's plan changed after Watch started (a rebuild or an apply), and Watch is still judging the desk against the plan as it was at Start. Stop Watch and start it again to use the new plan.

### W005: Watching without a plan

**Info** · Watch only

Watch has no plan, or could not read the one it was given, so the checks listed under Compared with the plan are off, and a few others may warn about something the plan asked for. Start Watch with the show (`atoo watch --show DIR`) to judge the desk against it.
