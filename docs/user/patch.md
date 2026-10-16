# Patching a running show: `atoo patch`

*From the command line. In the browser, see [Patch a show that is already on the desk](patch-a-show.md).*

The horn section has turned up during the setup window. The show is
already applied, there is a mix on the desk, and you cannot re-run
`apply`: it resets the desk to its initialized state and sets the whole
plan, every fader included, so the mix on the desk is lost. You type what
changed, and `atoo patch` writes only that:

```bash
atoo patch --show touringband --console 192.0.2.16 \
    "trumpet, sax and trombone on LCL 21-23, Band DCA, send to MON2"
```

**Use it before doors, not during the show.** Save a snapshot on the
desk once the board is patched, and the worst a change can cost you is a
reload.

## Why "patch", and what a "change" is

On a WING, "patch" already means routing a socket to a channel, and
Atoo's findings and plan fields use it only that way. So **what you
type is a *change***, and it is called that in messages, in the journal
and on the page: `change 3: Add horns on A 21-23`.

## What it is for

- A **permanent** change to the show means editing the input list, the
  conventions or `instructions.md`, and rebuilding. `plan.json` is the
  build's, and only a build writes it.
- `patch` is for **ad-hoc** changes to what is on the board right now,
  typically at short notice: a horn section turning up, a vocalist
  leaving. It also works for **building a show up one change at a time**
  from an initialized board, dictating one piece at a time.

## How it works

1. **The plan on the desk.** The desk's own newest journal entry records
   the plan it left there (each desk keeps its own —
   [One plan, two desks](two-desks.md#one-plan-two-desks)). A desk this bundle has
   never written falls back to `plan.json`, with an INFO; a desk with
   neither starts from an **empty board**, with an INFO. The review says
   which, in its first line.
2. **One model call.** The model sees only your change, that plan (as
   read-only context), and your house conventions with the bundle's
   `instructions.md` layered on top. It answers with a **change set**:
   what to add, drop or edit, and a short name for the change, never a
   whole plan, because a model asked to restate the show re-decides
   things nobody asked about.
3. **The merge**, in code. New channels, and any bus, DCA, mute group or
   output the change needs, are added to a copy of the plan on the desk,
   with console indices the plan leaves free. Dropped channels are taken
   out. **A reference to anything that does not exist is refused**, and
   the whole change with it: a send to a bus that is neither on the desk
   nor added by the change cannot be set, so nothing is written
   half-connected. **Sockets the change names are honoured**; one it did
   not name is checked against every socket in use and chosen afresh if
   it is taken — and either way an INFO says what was chosen.
4. **Everything after that is amend's**, unchanged: placement on
   genuinely free strips (skipping occupied ones, never renumbering a
   running one), [the pre-flight](amend.md#the-pre-flight-the-same-checks-as-apply),
   the review, the one `--confirm`, the write, the proof that nothing
   else moved, the journal and undo.

## Try it with no console, and no model

`--state FILE` reads an offline capture instead of a desk, and
`--change-set FILE` uses a change set compiled earlier instead of calling
the model. The Demo show has both: `atoo/web/demo_states/before.json`
is the Demo console's rig (the desk as the Demo show leaves it), and
`docs/user/demo/demo-show/horns.change-set.json`, in an Atoo checkout, is
the change set for the Demo's 6pm change, *"trumpet, sax and trombone on LCL
21-23, Band DCA"*, written by hand as a model would answer under the
starter conventions. Run it from the top of an Atoo checkout:

```
atoo patch --show starter/demo-show --change-set docs/user/demo/demo-show/horns.change-set.json --state atoo/web/demo_states/before.json
```

```
  INFO no desk was contacted (--state), so the applied plan is plan.json -- the bundle's last build. A run against the desk compares against the plan that desk's own newest write left on it, which may differ.

Change: Add Trumpet, Sax and Trombone on LCL 21-23
  INFO preset library: starter/presets -- the library the plan on the desk was built with (its strips' preset values record it)
48 strip(s) read over 206 address(es): 14 ours, 0 theirs, 34 free, 0 unknown
  this read asked each strip for its name, its link-to-source flag and its input patch, and asked every patched socket for ITS name -- which on a WING is where a name somebody typed actually lives. It did not ask what anything is routed to, so a strip that is routed somewhere but neither named nor patched reads as free here. `atoo audit` asks the rest.

4 added, 14 unchanged
  ADDED            channel 'Trumpet' -> ch:14: new channel, placed on a free strip
  ADDED            channel 'Sax' -> ch:15: new channel, placed on a free strip
  ADDED            channel 'Trombone' -> ch:16: new channel, placed on a free strip
  ADDED            bus 'Horns' -> bus:8: new bus
  writes to: ch:14, ch:15, ch:16
  INFO bus 'Horns' is new, given index 8 -- the lowest the plan on the desk leaves free
  INFO channel 'Trumpet': patched to LCL 21, the socket the change named
  INFO channel 'Sax': patched to LCL 22, the socket the change named
  INFO channel 'Trombone': patched to LCL 23, the socket the change named
  INFO channel 'Trumpet': the preset 'Trumpet' (Trumpet.chn) puts 83 processing values into the change, written with it and read back like every other write
  INFO channel 'Sax': the preset 'A Sax' (A Sax.chn) puts 83 processing values into the change, written with it and read back like every other write
  INFO channel 'Trombone': the preset 'T Bone' (T Bone.chn) puts 83 processing values into the change, written with it and read back like every other write
  INFO 1 bus(ses) carry a bus preset's values, resolved from starter/presets: Horns: 'Mix Bus'
  INFO the model said: 'sax' read as an alto sax, so it takes the A Sax preset; say 'baritone sax' for B Sax.
  INFO the model said: The Horns mix bus is new: the Demo show has no horns until now.
  INFO bus 'Horns' (index 8) was judged free from the applied plan alone -- the occupancy read covers strips, not busses

379 address(es) will be written; 1625 belonging to objects this amend does not own will NOT be.

Pre-flight verify of the changed plan against the WING Compact the plan is for (reviewed offline: no desk was asked): no errors, 1 warning(s) (reconcile.not-checked) -- warnings do not block.
  ...
```

The run ends by saying how long the review took, and that no console was
contacted.

Each horn lands on the next free strip, on the socket you named, and
takes its starter preset (Trumpet, A Sax, T Bone). The conventions put
every horns channel on a **Horns** mix bus, which the Demo does not have
yet, so the change adds it, with the **Mix Bus** bus preset: its
compressor is among the writes, read back like the rest
([Bus presets](bus-presets.md)).

The presets come from the library the show was built with, found
without a flag, and the first INFO line says which one and why:

1. `--presets DIR`, when you give it;
2. else the library the plan on the desk records (every strip a build
   gave a preset's values names the library it came from), so the new
   strips match the ones already running. A plan built from the starter
   presets somewhere else (the Demo show, or a copy of it in `/tmp`)
   finds the packaged starter presets by their contents;
3. else `[presets] default` in `~/.atoo.config`. One that is not a
   folder, or holds no presets, is passed over, and the INFO says so.

With none of them, a change that names presets says so first, before the
review, as a `WARNING: no preset library was found ...` line naming
them: the strips are still written and pass audio, without their
presets' processing. Pass `--presets DIR` and preview again.

**A sax, with no kind named.** Where your conventions give presets by
kind of instrument (alto and baritone sax) and the change does not say
which, the most common kind is chosen and the notes say so, naming the
other: *"'sax' read as an alto sax, so it takes the A Sax preset; say
'baritone sax' for B Sax."* The model is told never to leave a strip
without its preset for want of a word.

Nothing already on the desk is written: the 1625 addresses that belong
to the Demo's own strips are left alone, and on a real desk they are
read before and after the write, as the proof that nothing else moved.
A change can also edit what is running; see
[Editing what is already running](#editing-what-is-already-running).

## The rules

- **`plan.json` is never touched.** Only a build writes it. What a change
  put on a desk is recorded in that desk's journal entry, which the next
  change (or amend) of the same desk reads as its starting point — so
  typing the same change twice finds the horns already there and writes
  nothing.
- **Add, remove, and edit only what is named.** A change adds channels,
  busses, DCAs, mute groups and outputs, drops channels, and sets the
  fields it names on anything already running — nothing else about a
  running strip moves. Dropping a bus, DCA, mute group or output is shown
  as `MODIFIED`, *not written*: nothing returns one of those to free yet.
- **A channel can move.** *"Move Playback to Aux 8"* builds the channel
  on its new strip and returns the old strip to free, leaving the input
  sockets alone. The review lists it twice, `ADDED` on the new strip and
  `RELEASED` on the old one, with an INFO saying it was moved. If the
  strip you name is not free, the channel goes on a free one instead, and
  the review says which.
- **What the change leaves out is not a reason to refuse it.** A change
  that adds one channel and says nothing of busses, DCAs or outputs goes
  on, with an INFO: *the change set left out add.busses, ...; each is
  read as empty*. The same holds for a file given to `--change-set`.
  An answer Atoo cannot use at all is kept as `change.partial.json` in
  the show bundle, and the error says why.
- **Something the plan or the desk cannot take refuses the change**
  (`REFUSED`, exit `2`): a reference to something that is not there
  (*"it names bus 'MON9', which is neither on the desk nor added by this
  change"*), a field a running object does not carry, or a value out of
  range. Say it again naming what is there, or add the missing object in
  the same change. The browser heads the review "Refused: cannot be
  written as asked", and each line says which it is.
- **Each change's text and short name are recorded** in the desk's
  journal entry, numbered in the order they are written, so the journal
  stack reads as a list of changes. `atoo undo --show DIR` pops a
  change exactly as it pops an amend, and names it:

  ```
  Reversing the newest entry in touringband/journals on this desk:
    2026-09-26T00:45:16.925926+00:00  patch  change 1: Add Trumpet, Trombone and T.Sax on A 21-23  APPLIED: 51 address(es) evaluated, 39 written, 0 mismatch(es).  (scope: ch:21, ch:22, ch:23)  [on FOH-A (wing-compact) serial S2203A1, at 198.51.100.9:2223]
  ```
- **A full apply warns before it replaces changes** that are not in
  `plan.json` — in `atoo apply`'s output and in the Apply screen's
  pre-flight, as a WARNING, not an error:

  ```
  WARNING  plan.json: a full apply replaces 1 change(s) on this desk (FOH-A
           (wing-compact) serial S2203A1, at 198.51.100.9:2223) that are not in
           plan.json: change 1: Add Trumpet, Trombone and T.Sax on A 21-23. The apply writes the plan as
           built: a channel a change dropped comes back, and a channel a change
           added stays on its strip but is no longer tracked -- the next patch
           treats that strip as somebody else's.
           Fix: to keep a change for good, `atoo patch --promote <change>`
           puts it in instructions.md and input.csv -- then rebuild; to take an
           added channel off the desk, undo that change before the apply; to
           drop a channel again after the apply, patch the drop again.
           (apply.replaces-changes)
  ```

  Do not "patch it back on" after an apply: the added channel is still
  on its strip, and a second patch would place a second copy of it. A
  change already promoted is still listed until the rebuilt show is
  applied, marked `(promoted)`.
- **On a desk Atoo did not set up, a change can only name groups the
  plan knows.** A DCA, mute group or bus that is on the desk but not in
  the plan patch starts from is refused, as above. Leave it out of the
  change, or add it in the change itself. Existing channels are safe
  either way: a new channel only ever lands on a free strip.

## Editing what is already running

A change may also change something **already on the desk** — *"move the
sax to MON3 at -10"*, *"rename ch 5 Kick In"*, *"HPF 100 on the vocals"*,
*"put the horns in the Band DCA"*, *"mute group Speech on the host"* — but
**only in the fields it names**. That is enforced in code, not left to
the model:

- **Code sets those fields and no others**, and refuses a field the
  object cannot carry or a change may not set (a channel's strip number,
  a bus's index), the whole change with it. Only the addresses whose
  value moves are written; the rest of the strip is in the before/after
  read that proves nothing unrelated moved.
- **A show built with presets edits like any other.** A channel or bus
  that carries a preset's values (see [Presets](presets.md)) is renamed,
  moved, muted or given a new fader like any other, and the preset's
  values on it are left exactly as they were: they are not among the
  fields the change names, so none of them is written. A change cannot
  set those values themselves, and asking a running channel or bus for a
  *different* preset is shown as `MODIFIED`, not written (the values on
  it are the old preset's); set the processing fields themselves, or
  rebuild.
- **The review shows old -> new for every field**, as an `EDITED` line, in
  the "fields changed" block of the summary, and at INFO:
  `ch:9: the change edits bus_sends: MON3 level -144 -> -10.0`.
- **A fader moves only when the change says "fader"** (and a mute only
  when it says "mute" — "mute group" is a membership, not the mute). A
  fader the model set anyway is shown as `MODIFIED`, not written.
- **A repatch of a running strip moves audio the moment it is written**,
  so it is said first, on its own (from Atoo's test desk and a stubbed
  model):

  ```
  !! 1 PATCH CHANGE(S) ON SOMETHING ALREADY RUNNING -- these move audio the moment they are written:
  !!   MOVES AUDIO LIVE -- channel 'BassDI' on ch:7: patch A 6 -> A 30
  ```

  The new socket's own name, colour, phantom and gain are written with it —
  unless another strip on the desk uses that socket, when they are that
  strip's and are left alone, with a note. The old socket keeps its name.
- **Taking something away is written as off**: a send the change removes
  is switched off, a high-pass it removes is switched off, and a strip
  that leaves every DCA and mute group has those tags cleared (other tags
  kept).
- **An edit that would rewrite another object is refused.** Patching a
  running strip onto a socket another running strip uses turns that other
  strip's source link off too — and that strip is not named, so the
  change is refused.
- **Undo puts every edited field back**: the journal records each
  address's value before the write, as it does for every write.

## Keeping a change for good: `--promote`

A change is ad hoc: `plan.json` does not have it, and a full apply
replaces it. When the horns turn out to be permanent, **promote** the
change instead of retyping it into your files:

```bash
atoo patch --show touringband --promote 1
```

`1` is the change's number (`change 1` works too), or give its short name
or its journal entry. The run below is Atoo's own test desk and a
stubbed model standing in for the WING and the change compile — the
change was *"congas on A 21 and 22, in the Drums DCA and the
Drums bus"*, written to that desk first:

```
Promote change 1: Add Conga Hi and Conga Lo on A 21-22 into the show:

  instructions.md gains:
    | ## Promoted changes
    |
    | Changes typed at the desk with `atoo patch` and kept in the show with `--promote`. Each is an instruction for every rebuild from now on.
    |
    | ### 2026-09-28: change 1: Add Conga Hi and Conga Lo on A 21-22
    |
    | <!-- atoo: promoted 20260928T215445.655174Z-patch-192.0.2.16.json -->
    |
    | congas on A 21 and 22, in the Drums DCA and the Drums bus

  input.csv gains 2 row(s):
    socket,name,category,type,model,phantom,notes
    AES50-A 21,Conga Hi,drums,Mic,,FALSE,promoted from change 1: Add Conga Hi and Conga Lo on A 21-22
    AES50-A 22,Conga Lo,drums,Mic,,FALSE,promoted from change 1: Add Conga Hi and Conga Lo on A 21-22

  plan.json is not touched -- rebuild the show to put the change in it (only a build writes plan.json).
  INFO 'Conga Hi': category 'drums' -- the category of 'Kick', which shares its DCA 'Drums'
  INFO 'Conga Lo': category 'drums' -- the category of 'Kick', which shares its DCA 'Drums'

Nothing was written -- this was a preview. Re-run with --confirm to keep change 1: Add Conga Hi and Conga Lo on A 21-22 in the show.
```

`--confirm` writes both files, and then **a normal rebuild owns the
change**:

```
Written: instructions.md, input.csv. change 1: Add Conga Hi and Conga Lo on A 21-22 is in the show now: rebuild (`atoo build --show touringband`) and the next plan.json carries it.
```

- **The change's words go into `instructions.md` as you typed them.**
  Edit the instruction afterwards if the words describe a one-off rather
  than a permanent show.
- **Each input the change added gets a row in `input.csv`**, at the socket
  it is on now, keeping the file's own header and column order. A stereo
  channel is two rows. Its category and type are inferred and said at
  INFO; correct the row if the guess is wrong.
- **A change that dropped or edited something is promoted as text only.**
  No input-list row is removed: a source that has gone for good is yours
  to delete from the list.
- **Refused**: a change that was **undone** (it is not on the desk, so
  there is nothing to keep), one that aborted partway, and an amend from a
  rebuilt plan (it has no typed text). Promoting the same change twice
  writes nothing the second time.
- **`plan.json` is never touched**, as for every change. In the browser,
  each change on the Patch screen has a **Keep this in the show** button
  that does the same.

## Write exactly the change you reviewed

A preview compiles the change; a `--confirm` run compiles it **again**,
and a model asked twice can answer differently. So save the one you read
and write that:

```bash
atoo patch --show touringband --console 192.0.2.16 \
    "trumpet, sax and trombone on LCL 21-23, Band DCA, send to MON2" \
    --save-change-set horns.json
# read the review, then:
atoo patch --show touringband --console 192.0.2.16 \
    --change-set horns.json --confirm
```

The saved file carries the change's text as well, so the journal records
it. A `--review-json` file works as a `--change-set` too. The Patch screen
does this for you: its write is always the change set its preview showed.

## How long a change takes

Every run ends with a `Timing:` line: the desk read, which took about
1.4 seconds on a WING Compact when reads went one request at a time, and the model call, which varies with the
provider and the model and has not yet been timed against a real one.

While it runs, each read and write of the desk says what it is doing on
stderr: `occupancy read`, `reading the untouched strips, before writing`,
`checking each setting, writing what differs`, then the same proof read after. The lines
are the ones [`apply` prints](applying.md#while-it-runs);
`--no-progress` turns them off.

## See also

- [Applying a plan](applying.md) — `apply`, flags and exit codes; [the journal](journals.md)
- [Undoing a write](undo.md) — `atoo undo`
- [Patching from a rebuilt plan](amend.md) — `atoo amend`
- [One plan, two desks](two-desks.md)
- [Command reference](cli-reference.md) — every flag, generated from the code
