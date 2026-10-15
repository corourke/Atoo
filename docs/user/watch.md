# Watching from the command line: `atoo watch`

Mid-show, nobody re-checks the whole desk after every change. Someone
bumps a fader, re-patches a stage box line or mutes the wrong group, and
you find out when the crowd does. `atoo watch` re-reads the desk on
an interval and tells you only what **changed**: a rule that just tripped,
or one that just cleared.

**It never writes to a console.** It runs the same rules as
[`atoo audit`](audit.md), plus your own
[watch conditions](watch-conditions.md). In the browser, the same watch
runs behind **Start watching**: see [Watch the desk during a show](watch-a-show.md),
or try it on the [Demo show](demo.md) with no desk.

**With `--show`, it also watches the desk drift from your plan.** Nine
rules come from the bundle's plan, each a WARNING that clears itself
when the desk is put back, and a tenth, an INFO, says what one of them
took for a monitor mix:

- `CV006 Bus Send Contradicts Plan`: a send the plan states, switched
  off, or in the other pre/post mode. *CH 1 "Kick": plan says send to
  Drum IEM mode is 'pre' (PRE), live console reads POST.* This is how a
  monitor send flipped post-fader mid-show shows up. Watch compares the
  switch and pre/post only, **not the level**: a send level is what you
  ride at soundcheck, so a moved fader is not a row. `atoo audit --plan`
  still compares the level.
- `CV007 Main Route Contradicts Plan`: a channel's direct route to a Main
  that the plan lists, switched off, or one it does not list, switched
  on. *CH 2 "Click": plan lists no direct route from this channel to
  Main 1, live console reads on.*
- `CV018 Send Or Route Not In Plan`: a send or route that is **on** and
  that the plan does not have. A channel's send to a bus the plan does
  not list for it, or to any Matrix, above the floor; or a bus routed to
  a Main its plan entry does not list. *CH 2 "Click": a send to BUS 2
  "Drums" is on at 0dB; the plan has no send from this channel to that
  bus.* It is how a click or talk mic opened into the PA, or a wedge bus
  summed into Main, is caught. A WARNING rather than an error, because
  adding a send is an ordinary act at a desk: if you added it on purpose,
  the row names it and you can leave it, or add it to your conventions
  and rebuild. The plan has no way to say that a channel feeds a Matrix,
  so a Matrix you feed from a strip on purpose stays a row until the
  send is off.

- `CV019 Phantom Contradicts Plan`: 48V on an input socket that is not
  what the plan states for the channel patched to it. *CH 1 "Kick": the
  plan has 48V on at AES50-A 1; the desk has it off, so a condenser
  patched there is silent.* The other way round is a warning too: *CH 2
  "Snare": the plan has no 48V at AES50-A 2; the desk has it on, which can
  damage a source that does not want it.* A stereo pair is two sockets,
  each with its own value. Only the local inputs and the AES50 ports
  have 48V to compare; a channel patched from a card or USB is not
  checked.

- `CV020 Bus Width Contradicts Plan`: a bus that is mono where the plan has it
  stereo, or stereo where the plan has it mono. *BUS 3 "Drummer": the plan
  has this bus mono; the desk has it stereo, so an output patched to its left
  side carries only the left of the mix and anything panned right is lost.*
  The plan states a width for a bus and nothing else, so a Main's and a
  Matrix's width are not compared. Without a plan,
  [`R011`](troubleshooting-audit.md#a-bus-is-heard-on-one-side-only-or-is-not-the-width-the-plan-says-r011-cv020)
  notes a stereo bus, Main or Matrix patched on one side only.

- `CV021 Talkback Misses A Monitor Mix`: talkback is assigned and reaches
  something, but not a monitor mix the plan builds. *Talkback is assigned
  to CH40 and reaches other mixes, but not BUS 4 "Drum IEM", a monitor mix
  the plan builds: neither TALK A nor TALK B is routed to it, so whoever
  listens to that mix cannot hear you.* One row per mix, so each clears
  when its own switch is back on. The plan says which busses are monitor
  mixes, never a bus's name: a bus the plan feeds to an output socket and
  to no Main, unless the sends the plan lists into it are all post-fader.
  `CV022 Monitor Mixes Talkback Was Checked Against` is the INFO that names
  them (*Talkback reaches 3 of the 4 monitor mixes the plan builds: BUS 1
  "Vox Wedge", ...*), so a mix it did not take for one is easy to spot. Both
  say nothing when talkback is `OFF`, when the plan builds no monitor mix, and
  when talkback is routed nowhere at all, which
  [`T001`](troubleshooting-audit.md#the-band-cannot-hear-talkback-t001) says
  once. Reading them costs nothing: the destination switches are read
  whenever talkback is assigned.

- `CV016 Planned Routes All Off`: a channel whose every send and Main
  route the plan built is switched off or pulled to the floor. *CH 1
  "Kick": the plan sends it to Drums and Drums Comp; neither send is on.
  Its signal reaches nothing the plan routes it to.*
  One send off is not this rule (moving a channel between busses is your
  call); a monitor send the plan leaves at the floor for you to bring up
  is not a planned route.
- `CV017 Muted Against Plan`: a channel, bus, DCA, Main or Matrix the
  plan leaves unmuted, muted on the desk. *BUS 9 "Vocals" is muted on the
  desk; the plan leaves it unmuted.* A WARNING rather than an error,
  because muting between songs is normal; if a particular mute should be
  an error, write a [watch condition](watch-conditions.md) for it. The
  talkback mic is left out: it is muted between talks on purpose.
- `CV015 FX Bus Effect Contradicts Plan`, when the plan loads an
  effect from a bus preset (a reverb on the Vox Verb bus, say: see
  [Bus presets](bus-presets.md)): that bus's
  insert switched off (the effect bypassed, so the bus returns nothing),
  pointing at another engine, or its engine holding another effect.

A strip whose every planned route is off is one row, `CV016`, which names
each send and route; `CV006` and `CV007` do not repeat them. A desk left
exactly as `atoo apply` set it raises none of the three above, and
a send or route that did not answer says nothing.

For example, with a plan that sends Kick to the Drum IEM bus in pre-fader
and Click to the same bus only, and a desk where Kick's IEM send goes
post-fader and Click is opened to the Drums bus and to Main 1 (a capture of
the desk as the plan left it, then one taken after those changes, then the
first again):

```
atoo watch --show bundle --state-sequence ok.state.json,touched.state.json,ok.state.json --count 3 --interval 0.1
```

```
[2026-10-15T10:00:30+00:00] change detected:
  NEW     [WARNING] CV006 Bus Send Contradicts Plan: CH 1 "Kick": plan says send to Drum IEM mode is 'pre' (PRE), live console reads POST.
  NEW     [WARNING] CV007 Main Route Contradicts Plan: CH 2 "Click": plan lists no direct route from this channel to Main 1, live console reads on.
  NEW     [WARNING] CV018 Send Or Route Not In Plan: CH 2 "Click": a send to BUS 2 "Drums" is on at 0dB; the plan has no send from this channel to that bus.
  Coverage: no input sockets read -- C001 and C007 could not be checked.
[2026-10-15T10:00:30+00:00] change detected:
  CLEARED [WARNING] CV006 Bus Send Contradicts Plan: CH 1 "Kick": plan says send to Drum IEM mode is 'pre' (PRE), live console reads POST.
  ...
```

The plan also quiets two rules. `L002 Active Strip Fader At Floor`
(INFO) is not raised for a fader the plan itself puts at the floor --
under conventions that start every fader down, that is every channel
until you bring it up. A fader the plan puts anywhere else, found at the
floor on the desk, is still reported. `R008 Strip Reaches Nothing`
(WARNING: a channel in use with no send or Main route on) is not raised
for a channel the plan routes somewhere, because `CV016` above says it
with the plan's own words; it still speaks for a channel the plan does
not route.

**Clips are listened for too.** With `--console`, a watch also listens
to the desk's meters, on one more connection (port 2222) that only reads,
and raises `L003 Clipped` (an ERROR) for any channel, aux, bus, main or
matrix that clips, for about a minute after its last clip. It prints as
a NEW line when the strip clips and a CLEARED line when the minute is up;
a second clip inside the minute is the same finding with the timer
moved on, so it does not print again. If the connection cannot be had,
`W002 Clip detection is off` says why, at INFO, and the watch goes on.
`--state-sequence` has no meters and no clips. See
[Watch the desk during a show](watch-a-show.md#a-clip).

Everything else is the desk and your watch conditions.

**Where your outputs go is read, wherever they are.** A watch reads the
output sockets your plan patches as well as the desk's own panel, and
the outputs of every AES50 stage box the desk reports a device on (or a
channel takes its input from). A Matrix that the phones or the monitor
speakers listen to counts as reaching an output with no socket of its
own. If a reading still could not see a stage box's outputs, the
monitor busses on it are not called unrouted: `R007 Output Route Not
Checked` says, at INFO, which outputs were not read.

Every transcript on this page runs against a captured state file, with
no console attached. [`atoo init`](install.md#6-first-run-atoo-init-then-atoo-ui) copies
the captures into your Atoo folder, as `audit-demo/` (run it again if
yours was made before they existed; it adds what is missing and touches
nothing you have changed):

```bash
cd ~/Documents/Atoo/audit-demo
```


```bash
atoo watch --console 192.0.2.16
```

Same rules, re-run on an interval, reporting only the difference. An
operator moves a fader or unplugs a cable mid-show, and the next pass
catches whatever rule that just tripped.

To see it without a desk, play a list of captures in order.
`audit_demo_state_before.json` is the same small rig with every fault
fixed, so the pair is a scripted stand-in for "the operator just changed
several things":

```bash
atoo watch --state-sequence audit_demo_state_before.json,audit_demo_state.json --interval 0.5
```

```
Watching 2 state file(s) in sequence every 0.5s (Ctrl-C to stop) -- read-only, nothing here writes to a console.

[2026-09-22T05:57:47+00:00] baseline -- 0 finding(s) already present:
No findings -- every rule in this audit passed.

Physical sockets read: in LCL 1-9; out LCL 1-2.
[2026-09-22T05:57:48+00:00] change detected:
  NEW     [WARNING] C001 Phantom Power On Unpatched Socket: 48V is on for LCL 9 but nothing is patched to it -- no channel, no aux and no user patch.
  NEW     [WARNING] CH002 DCA Fader Low With Active Members: DCA 1 "Drums" is at the floor (-20dB or lower) but controls 2 active member(s): CH 1 "Kick", CH 2 "Snare".
  NEW     [WARNING] L001 Send On But Near-Silent: CH 2 "Snare"'s send to BUS 1 is on at -105dB -- audible in principle, in practice dead.
  ...
  NEW     [INFO] CH001 Channel Not In Any DCA (5): CH 3 "Vocal", CH 4 "Vocal", CH 5 "Bass", CH 6 "Bass DI", CH 7 "Playback" -- each is in use but belongs to no DCA group.
  ... 2 more NEW lines
```

Three things to read here.

**The first pass is a baseline, not an alert.** Whatever is already wrong
when you start watching is not a change, so it is reported once, in full,
and then never again. If you start watching a desk mid-show, the baseline
is your inventory of what you inherited.

**A finding that stops applying is reported too.** Run the same two
captures the other way round and every line comes back `CLEARED` —
somebody fixed it, and that is news:

```bash
atoo watch --state-sequence audit_demo_state.json,audit_demo_state_before.json --interval 0.5
```

```
[2026-09-22T06:14:12+00:00] change detected:
  CLEARED [WARNING] C001 Phantom Power On Unpatched Socket: 48V is on for LCL 9 but nothing is patched to it -- no channel, no aux and no user patch.
  CLEARED [WARNING] CH002 DCA Fader Low With Active Members: DCA 1 "Drums" is at the floor (-20dB or lower) but controls 2 active member(s): CH 1 "Kick", CH 2 "Snare".
  ... 8 more CLEARED lines
```

**Nothing changing is nearly silent.** A pass with no news says so in one
line and moves on — no repeated all-clear, no re-listing of findings you
have already seen:

```bash
atoo watch --state-sequence audit_demo_state_before.json,audit_demo_state_before.json --interval 0.5 --count 3
```

```
[2026-09-22T05:57:54+00:00] baseline -- 0 finding(s) already present:
No findings -- every rule in this audit passed.

Physical sockets read: in LCL 1-9; out LCL 1-2.
[2026-09-22T05:57:55+00:00] pass 1: no change.
[2026-09-22T05:57:55+00:00] pass 2: no change.
```

**When it stops, its exit code is about the last pass only.** `watch`
exits `1` if the pass it ended on held a finding at error severity —
an audit rule or one of your own watch conditions — and `0`
otherwise, warnings and info included. Like `audit`, and for the same
reason, that is `1` rather than the `2` `apply` uses; and
like `audit`, `1` is also what it returns when it could not start, which
stdout tells apart. See the
[full exit-code table](cli-reference.md#exit-codes).

A run watching a live desk only ends when you stop it or `--count` runs
out, so this matters most for the `--count` form — a scheduled
"check the desk N times and tell me" job.

## Picking an interval

`watch` re-reads the whole desk on every pass and compares. **One read
of a Compact takes about five seconds** at most
([timed one request at a time](audit.md#how-long-a-live-read-takes-and-what-it-prints-while-it-works)),
longer if addresses go unanswered, with the same progress line
[`audit` prints](audit.md#how-long-a-live-read-takes-and-what-it-prints-while-it-works).
`--interval` is the gap *between* reads, not their period, so at the
default 2 seconds a new pass starts roughly every seven; `--count` counts
reads, so `--count 8` is about a minute. `watch` prints its own estimate
before the first read. For `atoo watch --console 192.0.2.16 --count 8`
on a Compact:

```
Reading 6143 addresses per pass, as 323 requests by node dump -- roughly 4s each on hardware. Names are read at Start and every 5 passes; the passes between ask 235 requests, roughly 3s, so 8 pass(es) is about 42s.
```

With `--name-refresh 1`, every pass is 323 requests: 8 passes is about
49s.

With `--per-leaf` a pass is about two minutes, an interval this short
changes almost nothing, and `--count 8` is about 17 minutes — the
estimate line says so.

## Names are read at Start and refreshed

A watch reads every strip, bus, DCA, mute-group and input-socket name on
its **first pass** — the baseline Start takes — and then **every fifth
pass** (`--name-refresh 5`, the default). The passes in between carry the
names the last refresh read, so every rule still has them: the in-use
rules (R001, R002, R008, C006, L002 and the CH rules), the duplicate-name
rules N001 and N002, a watch condition that names a strip, and DCA
and mute-group membership by group name.

That takes a pass between refreshes from 323 requests to 235, about a
second less on a Compact. Five passes is a refresh about every **30
seconds** at the default 2-second `--interval`; a longer interval
stretches it, and `--name-refresh N` changes it.

**What it costs: a rename is seen at the next refresh, not the next
pass.** Rename a channel, or give two strips the same name, and N001
says so up to five passes later. The findings carry one INFO for the whole
session saying exactly that, in the baseline and in every pass's table
(never as a change), so a quiet table between refreshes is never mistaken
for a check that ran:

```
[INFO] W001 Names are refreshed, not read every pass
  Strip, bus, DCA, mute-group and input-socket names are read at Start and refreshed every 5 readings (about every 30s at the default 2s interval); a rename shows up at the next refresh. Everything else is read every pass. atoo watch --name-refresh 1 reads names every pass.
```

A strip **patched** to a different socket between refreshes is not left
waiting: the socket's name is read on the pass the new patch appears.

- `--name-refresh 1` reads names on every pass, with no W001.
- With `--per-leaf` the default is 1: a pass is about two minutes, so a
  refresh every five would leave a rename unseen for ten of them, to save
  88 of ~6,100 requests. `--name-refresh N` still applies if you say it.
- The Watch screen in `atoo ui` does the same, and has no control
  for it. It shows W001 on the **This watch** line under the table, not as a
  row in the table.
- `--state-sequence` and the Demo console read no names at all — their
  states are fixed — so neither carries W001.
- A scoped name in a watch condition (`BUS Drums`) still resolves once,
  against the first pass, which always reads every name.

`watch` is read-only and session-based: Ctrl-C stops it, nothing is left
running, and there is no background service or state kept between runs.


## See also

- [Watch conditions](watch-conditions.md) — your own alerts, and the file format
- [Checking a desk](audit.md) — one read, the rules, `--plan`
- [Show bundles](show-bundles.md) — where `watch.json` lives
- [Command reference](cli-reference.md) — every flag, generated from the code
