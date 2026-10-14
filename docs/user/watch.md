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

**With `--show`, it also watches the desk drift from your plan.** Three
rules come from the bundle's plan, each a WARNING that clears itself
when the desk is put back:

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

The plan also quiets one rule: `L002 Active Strip Fader At Floor`
(INFO) is not raised for a fader the plan itself puts at the floor --
under conventions that start every fader down, that is every channel
until you bring it up. A fader the plan puts anywhere else, found at the
floor on the desk, is still reported.

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
no console attached. [`atoo init`](install.md#first-run-atoo-init) copies
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
rules (R001, R002, L002 and the CH rules), the duplicate-name
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
