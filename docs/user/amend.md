# Patching from a rebuilt plan: `atoo amend`

*From the command line only. The Patch screen in the browser takes a typed change ([Patch a show](patch-a-show.md)); it does not take a rebuilt plan.*

`atoo patch --amended-plan FILE`, or `atoo amend`, takes a
**rebuilt plan** as the change instead of typed words — for a permanent change made
at a gig with a mix already on the desk: edit the inputs, rebuild beside
the applied plan, and write only the difference. It is recorded in the
journal as an amend, not a change. Everything below describes this route
and, from stage 1 on, the back half both routes share.

`amend` reads which strips are free, places only the new channels on
them, and writes only those. A change can add or take away: the same
operation covers a
vocalist who has left, a keyboard rig that went stereo, and a set of delay
speakers dropped from the rider.

You give it two plans. The **applied** plan is what is running. The
**amended** plan is the same show built again, from the same conventions
and instructions, with the change in it — three horn rows added to
`input.csv`, a line added to `instructions.md`, `atoo build` run
again. `amend` works out what is new between them.

Add the rows to the bundle's `input.csv`, say what changed in its
`instructions.md`, and run [`atoo build`](pipeline.md) again with
`--out touringband/rebuilt.plan.json` so the rebuild lands beside the
applied plan rather than over the top of it. Then:

```bash
atoo amend --show touringband --amended-plan touringband/rebuilt.plan.json \
    --console 192.0.2.16
```

Both paths are relative to **where you run the command**, not to the
bundle, so the bundle's name is part of them.

## The four stages, and the first three change nothing

1. **Read the desk.** A short read of each strip's name, patch and
   source socket's name: about 200 addresses and a few seconds. Two
   rules matter here; see
   [What "occupied" means](#what-occupied-means-and-the-strip-that-nearly-got-written-over)
   below.
2. **Work out the delta.** New channels go on free strips, skipping
   occupied ones and never renumbering a strip that is already running. A
   channel with nowhere to go fails by name rather than shuffling the
   show to make room. A channel the rebuild **dropped** has its strip
   returned to free — see
   [A channel the rebuild dropped](#a-channel-the-rebuild-dropped) below.
3. **Show what will be written, and what will not.** The second half is
   the point. The safety mechanism is a **target filter** — an address
   belonging to a strip this amend does not own is never generated, so it
   is never read and never written.
4. **With `--confirm`, write**: the same arming, readback and journal
   as `apply`, plus a before/after read of every unrelated address to
   prove none of them moved. One `--confirm` arms everything the preview
   showed, clears included.
   `plan.json` is left exactly as it was — see
   [After a confirmed amend or change](#after-a-confirmed-amend-or-change-planjson-is-unchanged).

**A preview does not run the before/after read**, since it writes
nothing; it says how many unrelated addresses a `--confirm` run will
read. On a WING Compact a preview took under two seconds, and a
`--confirm` run about five, most of it the before/after read, when reads
went one request at a time; with several in flight they should be
shorter.

## What "occupied" means, and the strip that nearly got written over

**A strip that did not answer counts as occupied.** An address Atoo
could not read is an absence of evidence, never evidence of an empty
strip, and the summary lists those strips under "never answered,
therefore treated as OCCUPIED" rather than quietly counting them free.

**A name a human types on a WING lands on the socket, not the strip.**
Name channel 20 "Podium" on the desk, and the desk stores the name on
socket `LCL 20` and leaves the strip's own name blank, while showing
"Podium" on the strip. On its factory patch, with no name of its own,
that strip looks free. So the read asks each patched socket for its name
too, and a strip whose *source* is named is occupied, whoever typed it:

```
  in use by somebody else: ch:11 -- named 'Podium' on its source LCL 11
```

A socket that carries the desk's own label rather than somebody's name —
`USB 1` reads `USB 1/2`, `PLAY 1` reads `2TR` — does not count, or every
WING's `/aux/1` and `/aux/2` would be refused on an untouched board.

## Try it with no console attached

`--state FILE` takes an offline capture instead of a desk, as
`audit --state` does, so the whole review can be done on the way to the
venue. `docs/user/demo/amend-demo/`, in an Atoo checkout, holds a small band's
applied plan, a rebuild of it with a trumpet and a tenor sax added, and a
capture of a desk running the show with somebody else's "Podium" on
strip 11:

```
atoo amend --plan docs/user/demo/amend-demo/applied.plan.json --amended-plan docs/user/demo/amend-demo/rebuilt.plan.json --state docs/user/demo/amend-demo/occupancy.json
```

```
48 strip(s) read over 204 address(es): 11 ours, 1 theirs, 20 free, 16 unknown
  in use by somebody else: ch:11 -- named 'Podium' on its source LCL 11
  never answered, therefore treated as OCCUPIED: ch:25, ch:26, ch:27, ch:28, ch:29, ch:30, ch:31, ch:32, ch:33, ch:34, ch:35, ch:36, ch:37, ch:38, ch:39, ch:40
  this read asked each strip for its name, its link-to-source flag and its input patch, and asked every patched socket for ITS name -- which on a WING is where a name somebody typed actually lives. It did not ask what anything is routed to, so a strip that is routed somewhere but neither named nor patched reads as free here. `atoo audit` asks the rest.

3 added, 11 unchanged
  ADDED            channel 'Trumpet' -> ch:12 (the rebuild asked for ch:11): new channel, placed on a free strip
  ADDED            channel 'T.Sax' -> ch:13 (the rebuild asked for ch:12): new channel, placed on a free strip
  ADDED            dca 'Horns' -> dca:7: new dca
  writes to: ch:12, ch:13
  INFO channel 'Trumpet': the rebuild proposed ch:11, which is not free -- placed on ch:12 instead, and nothing already on the desk moved
  INFO channel 'T.Sax': the rebuild proposed ch:12, which is not free -- placed on ch:13 instead, and nothing already on the desk moved
  INFO dca 'Horns' (index 7) was judged free from the applied plan alone -- the occupancy read covers strips, not groups

57 address(es) will be written; 532 belonging to objects this amend does not own will NOT be.

Pre-flight verify of the amended plan against the WING Compact the plan is for (reviewed offline: no desk was asked): no errors, 1 warning(s) (reconcile.not-checked) -- warnings do not block.

Reviewed offline from --state; no console was contacted. Re-run with --console to preview against the desk, and --confirm to write.
```

Fifty-seven addresses for two new strips and a new DCA; 532 that a full
`apply` of the same plan would have rewritten, and this will not.

## What it refuses, and what it reports without writing

- **A strip the rebuild tried to renumber.** If the same source has moved
  to a different strip number between the two plans, `amend` stops and
  names the strip. Re-planning to make room is a deliberate, separate operation,
  never an automatic one.
- **A channel with no free strip.** Named, and the run exits `2`.
- **A strip that is already running and whose settings changed.**
  Reported as `MODIFIED` and left alone — that is a strip in use, and a
  full build is how one of those changes.
- **A channel the rebuild dropped, whose strip somebody has since taken
  over.** Reported as `REMOVED, LEFT ALONE`, with the reading that
  refused it. See below.
- **A socket this amend would write that the desk does not have**, and
  **an amended plan that does not verify** — the pre-flight, next.

## The pre-flight: the same checks as `apply`

Before its preview is offered for arming, and again before a `--confirm`
run writes anything, `amend` asks the questions
[`apply` asks](two-desks.md#a-plan-built-for-a-different-model), and the
stage-box one `apply` asks too.

1. **The verify gate**, over the *effective* plan — the rebuild with this
   amend's placements in it, which is what `plan.json` becomes after a
   confirmed bundle amend — against the model the desk states on `/?`.
   Errors refuse the amend; warnings never do. It is apply's gate, with
   apply's escape: `--skip-verify`.
2. **The socket check**, over the sockets this amend actually **writes**:
   each new strip's input patch and each output socket a new bus or output
   is given. A socket the desk
   does not have is refused, naming the socket and the channel, **with or
   without `--skip-verify`** — that flag is about the plan's findings,
   and this is about the hardware. Unlike apply's, it runs on the same
   model too, not only across models: with `--skip-verify` it is the only
   thing between a bad rebuild and the panel.
3. **The stage-box check**, over the same sockets: the desk is asked what
   is on each AES50 port (`/$stat/A/dev`), and a socket written past the
   end of that box (`A 17` on an S16, which has 16 inputs and 8 outputs)
   is refused the same way, naming the box and its size. The desk lists 48
   sockets on every port whatever is plugged in, so it would take the
   patch and the channel would be silent. A box Atoo has no size for is
   said at INFO and its sockets are not checked.

The show is on a full-size WING — 8 local inputs — and the rebuild, made
for the Compact, patches the new Trumpet to `LCL 20`. On a copy of the
touring-band show against the test suite's simulated desk
(`tests/test_amend_preflight.py`'s, answering `/?` as a full-size WING),
the preview's review ends:

```bash
atoo amend --show touringband --amended-plan touringband/rebuilt.plan.json \
    --console 198.51.100.10
```

```
66 address(es) will be written; 867 belonging to objects this amend does not own will NOT be.

Pre-flight verify of the amended plan against the WING (full-size console) at 198.51.100.10:
1 error(s), 1 warning(s), 8 note(s)

  [error] channels[Trumpet].patch: LCL 20 does not exist -- LCL inputs are 1..8 on a WING (full-size console)  (patch.socket-out-of-range)

  [warning] plan: no input list was supplied, so nothing checked that every input became a channel, that no channel was invented, or that phantom power is safe for the microphones in use -- pass the input list to check those  (reconcile.not-checked)

  [info] busses[Drums, Drums Comp, Vocals, Horns, VOX Reverb, VOX Delay, Snare Verb, INST Reverb] (8 busses): width set to stereo -- the conventions did not state it; decided by Atoo's fallback rule: no physical output socket depends on its width, so it keeps the WING's factory width, stereo  (inferred.bus-width)

BLOCKED: do not apply.

ERROR: This amend would patch 1 socket(s) that do not exist on the WING (full-size console) at 198.51.100.10:
  - LCL 20 (input) -- channel 'Trumpet'; LCL inputs are 1..8 on a WING (full-size console); channel 'Trumpet', new on ch:21
The rebuild is for a WING Compact; this desk is a WING (full-size console).
Refusing to amend: LCL 20 (channel 'Trumpet', new on ch:21) does not exist on the WING (full-size console) at 198.51.100.10. Nothing was written; --skip-verify does not change that. Rebuild for this desk (--console-model wing-full), or repatch to sockets it has.
```

Exit `2`, and the same with `--confirm` or `--skip-verify`: nothing is
written, `plan.json` is left alone, and no journal is filed. The
refusal names the strip the channel *would* have gone on (`ch:21`, since
20 is somebody's), because that is the one you would go and look at.

A socket past the end of a stage box is refused in the same way. On
the Demo's capture with an S16 on AES50-A, and a change that puts a hi-hat
on `A 17`:

```bash
python3 -c "import json; d=json.load(open('atoo/web/demo_states/before.json')); d['/\$stat/A/dev']='S16'; json.dump(d, open('/tmp/s16.json','w'))"
atoo patch --show starter/demo-show --change-set docs/user/demo/demo-show/hihat-a17.change-set.json --state /tmp/s16.json "HiHat on A 17"
```

```
ERROR: This change would patch 1 socket(s) that do not exist on the S16 on AES50-A:
  - A 17 (input) -- channel 'HiHat'; the S16 on AES50-A has 16 inputs, so A 17 does not exist
Refusing to write this change: A 17 (channel 'HiHat') does not exist on the S16 on AES50-A. Nothing was written; --skip-verify does not change that. Repatch the change to sockets the box has.
```

Exit `2`. A socket the change leaves to Atoo is chosen within the box in
the first place.

**A different model, every socket present: it proceeds, with apply's
INFO.** The same rebuild, Trumpet on `A 21`, amending the Rack backup:

```
Pre-flight verify of the amended plan against the WING Rack (19", 4U) at 198.51.100.6: no errors, 1 warning(s) (reconcile.not-checked) -- warnings do not block.

INFO: This plan is for a WING Compact, but 198.51.100.6 is a WING Rack (19", 4U). Every socket the plan patches exists on this desk, so it is applied as it stands, with the pre-flight verify re-run against wing-rack -- the desk being written to.
```

A desk whose model Atoo has never measured proceeds with apply's
WARNING. A clean verify with only warnings is one line, since `build`
already reported them. With `--state` the plan's own model stands in.

A verify **error** refuses the amend with `Refusing to amend: the amended
plan does not verify against …` after the full report. It is often a
finding on a running strip the amend does not write — which is why
`--skip-verify` exists here as it does on `apply`: a finding you chose to
write past with `apply --skip-verify` is still in every rebuild of that
show, and without the flag the show could never be amended at all.

**In the browser** a typed change is refused the same way: the review
shows the refusal word for word and the write cannot be armed.
`--skip-verify` is command-line only for an amend.

## A channel the rebuild dropped

Take the vocalist out of `input.csv`, rebuild, and `amend` **returns that
strip to free**: unpatched (`OFF`), and its name, colour,
icon, DCA/mute-group tags, bus sends and **the processing your plan set**
all cleared, and its direct Main routing back to the factory's (Main 1
on, the others off) — on the
input socket as well as the strip, because with `clink` on that is where
the name the desk shows actually lives. The end state is the reading an
untouched strip gives, so the next person allocating a strip finds this
one genuinely free rather than nearly free.

**The patch goes `OFF`, exactly as a full apply leaves a strip your plan
does not use.** A freed strip reads the same whichever way it was freed,
so a change followed by a full apply ends with the same desk, and an INFO
line says what was done. A strip an earlier run left
blank on its factory socket still counts as free, so a clear that got
partway is finished rather than refused.

**The strip is muted while it is cleared, its fader goes to −∞, and it
is left unmuted**, as an untouched strip reads. The fader comes down
because the strip is routed to Main 1 again:
left where your plan put it, it would pass whatever is plugged in there
to the PA.

**The processing it clears is the processing your plan wrote, and
nothing else.** If your plan asked for a 120Hz high-pass on that strip,
the high-pass comes back off and its frequency goes back to the reading
an untouched strip gives. If somebody set an EQ on that strip by hand,
your plan never wrote it, so Atoo never clears it. **Head-amp gain
is deliberately left alone** — it belongs to the input socket rather than
the strip, it is shared by every strip on a split, and nobody has said
what a freed socket's gain should read.

**It only clears a strip it can still prove is yours.** The applied plan
claiming the strip is not enough — that plan was applied some time ago,
and people have been at the desk since. Before it writes anything,
`amend` compares the fresh read against what your plan actually wrote,
and refuses on any disagreement:

| The desk says | `amend` does |
|---|---|
| the strip did not answer | refuses — an unread strip is not a safe strip to clear |
| it is patched somewhere your plan did not put it | refuses — somebody has repatched it |
| it carries a name your plan did not write | refuses — somebody has renamed it |
| its **source socket** carries a name your plan did not write | refuses — that is where a name typed on the desk lands |
| blank, or your own name, on your own patch | clears it |
| already unpatched and blank | clears it — somebody started tidying and this finishes it |
| blank, on the strip's factory patch | clears it — that is what a strip returned to free looks like, so an earlier run that got partway is finished rather than refused |

A refusal names the strip and the reading behind it, and not one address
of that strip is written. A clear is shown in the preview, read back and
journalled like any other write, and counted on its own line: **`3
added, 1 returned to free`**.

One thing this does *not* do: anything about state on the desk your plan
never mentioned. A channel from last week's show that your plan says
nothing about is untracked, and untracked state is reported, never
cleared.

`--allow-strip ch:11` opens exactly one occupied or unanswered strip,
for the case where you can see the desk and know better. It is per
strip and repeatable; there is deliberately no switch that opens all of
them, and it can never open a strip the **applied** plan owns.

`--skip-untouched-proof` drops the before/after read on a `--confirm`
run; it is rarely worth it. `--review-json FILE` writes stages 1–3 as
JSON, even for a refused amend.

## After a confirmed amend or change, `plan.json` is unchanged

**Only a build writes `plan.json`**, because it is made from the input
list, the conventions and the instructions, and an amend changes none of
them. A confirmed amend, like a confirmed [change](patch.md),
records what it put on the desk in **that desk's journal entry** — the
effective plan, each new channel on the strip it was actually placed on —
and leaves `plan.json` as the last build made it.

This is still what makes a second amend from the same rebuild safe. The
next amend of the same desk compares against the plan that desk's newest
entry left on it, not against `plan.json`. On a copy of the touring-band
show against the test suite's simulated desk (answering `/?` as serial
S2203A1), the first run ends:

```
APPLIED: 66 address(es) evaluated, 39 written, 0 mismatch(es).
plan.json is unchanged -- only a build writes it. What is on this desk now is recorded in its journal entry, which the next patch or amend of this desk reads; a full `atoo apply --show touringband` would replace it, and warns before it does.
Untouched-strip proof: 867 unrelated address(es) read before and after, 0 changed.
Journal: touringband/journals/20260926T004554.758608Z-amend-S2203A1.json (scope: ch:21, ch:22, ch:23)
```

and the same command again finds nothing to do:

```
  INFO applied plan: the one this desk's newest write left on it -- journals/20260926T004554.758608Z-amend-S2203A1.json (amend).
  INFO plan.json differs from it: plan.json is the bundle's last build, and the changes, amends and applies recorded since -- to this desk or another -- are in the journal, not in it.
48 strip(s) read over 215 address(es): 22 ours, 1 theirs, 17 free, 8 unknown
...
22 unchanged
  INFO channel 'Trumpet': the rebuild numbers it ch:20, and an earlier amend placed it on ch:21 -- it stays there
  INFO channel 'Trombone': the rebuild numbers it ch:21, and an earlier amend placed it on ch:22 -- it stays there
  INFO channel 'T.Sax': the rebuild numbers it ch:22, and an earlier amend placed it on ch:23 -- it stays there

0 address(es) will be written; 933 belonging to objects this amend does not own will NOT be.

Nothing to add and nothing to return to free. The console was not written to.
```

**Placement is remembered.** A rebuild still numbers the horns 20–22,
because `build` knows nothing of the desk; the amend placed them on
21–23 because 20 was somebody's. The desk's journal entry records that,
so the next amend recognises Trumpet on 21 as the rebuild's ch:20 rather
than refusing it as a renumber.

**`verify` and `watch --show` read `plan.json`**, so after a change they
describe the last build, not the desk. A full `apply` of the bundle puts
the last build back on the desk and [warns first](patch.md#the-rules)
that it replaces the changes standing there.

## See also

- [Applying a plan](applying.md) — `apply`, flags and exit codes; [the journal](journals.md)
- [Undoing a write](undo.md) — `atoo undo`
- [Patching a running show](patch.md) — `atoo patch`
- [One plan, two desks](two-desks.md)
- [Command reference](cli-reference.md) — every flag, generated from the code
