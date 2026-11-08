# Patching a running show: `atoo patch`

*From the command line. In the browser, see [Patch a show](patch-a-show.md).*

The horn section has turned up during the setup window. The show is already applied, there is a mix on the desk, and you cannot re-run `apply`: it resets the desk to its initialized state and sets the whole plan, every fader included, so the mix on the desk is lost. You type what changed, and `atoo patch` writes only that:

```bash
atoo patch --show touringband --console 192.0.2.16 \
    "trumpet, sax and trombone on LCL 21-23, Band DCA, send to MON2"
```

**Use it before doors, not during the show.** Save a snapshot on the desk once the board is patched, and the worst a change can cost you is a reload.

## Why "patch", and what a "change" is

On a WING, "patch" already means routing a socket to a channel, and Atoo's findings and plan fields use it only that way. So **what you type is a *change***, and it is called that in messages, in the journal and on the page: `change 3: Add horns on A 21-23`.

## What it is for

- A **permanent** change to the show is in its files: the input list and the other sheets, the conventions or `instructions.md`. A change typed here becomes one when you **keep it in the show** (`--promote`, below), which writes it into `plan.json` and the sheets.
- `patch` is for **ad-hoc** changes to what is on the board right now, typically at short notice: a horn section turning up, a vocalist leaving. It also works for **building a show up one change at a time** from an initialized board, dictating one piece at a time.

## How it works

1. **The plan on the desk.** The desk's own newest journal entry records the plan it left there (each desk keeps its own — [One plan, two desks](two-desks.md#one-plan-two-desks)). A desk this bundle has never written falls back to `plan.json`, with a NOTE; a desk with neither starts from an **empty board**, with a NOTE. The review says which, in its first line.
2. **One model call.** The model sees only your change, that plan (as read-only context), and your house conventions with the bundle's `instructions.md` layered on top. It answers with a **change set**: what to add, drop or edit, and a short name for the change, never a whole plan, because a model asked to restate the show re-decides things nobody asked about.
3. **The merge**, in code. New channels, and any bus, DCA, mute group or output the change needs, are added to a copy of the plan on the desk, with console indices the plan leaves free. Dropped channels are taken out. **A reference to anything that does not exist is refused**, and the whole change with it: a send to a bus that is neither on the desk nor added by the change cannot be set, so nothing is written half-connected. **Sockets the change names are honored**; one it did not name is checked against every socket in use and chosen afresh if it is taken — and either way a NOTE says what was chosen.
4. **Everything after that is amend's**, unchanged: placement on genuinely free strips (skipping occupied ones, never renumbering a running one), [the pre-flight](amend.md#the-pre-flight-the-same-checks-as-apply), the review, the one `--confirm`, the write, the proof that nothing else moved, the journal and undo.

## Try it with no console, and no model

`--state FILE` reads an offline capture instead of a desk, and `--change-set FILE` uses a change set compiled earlier instead of calling the model. The Demo show has both: `atoo/web/demo_states/before.json` is the Demo console's rig (the desk as the Demo show leaves it), and `docs/user/demo/demo-show/horns.change-set.json`, in an Atoo checkout, is the change set for the Demo's 6pm change, *"trumpet, sax and trombone on LCL 21-23, Band DCA"*, written by hand as a model would answer under the starter conventions. Run it from the top of an Atoo checkout:

```
atoo patch --show starter/demo-show --change-set docs/user/demo/demo-show/horns.change-set.json --state atoo/web/demo_states/before.json
```

```
  NOTE no desk was contacted (--state), so the applied plan is plan.json -- the bundle's last build. A run against the desk compares against the plan that desk's own newest write left on it, which may differ.

Change: Add Trumpet, Sax and Trombone on LCL 21-23
  NOTE preset library: starter/presets -- the library the plan on the desk was built with (its strips' preset values record it)

What this change does on the desk:
  added channel 'Trumpet' -> ch:14
  added channel 'Sax' -> ch:15
  added channel 'Trombone' -> ch:16
  added bus 'Horns' -> bus:8

379 address(es) will be written.

Details:
48 strip(s) read over 206 address(es): 14 ours, 0 theirs, 34 free, 0 unknown
  this read asked each strip for its name, its link-to-source flag and its input patch, and asked every patched socket for ITS name -- which on a WING is where a name somebody typed actually lives. It did not ask what anything is routed to, so a strip that is routed somewhere but neither named nor patched reads as free here. `atoo audit` asks the rest.

4 added, 14 unchanged
  ADDED            channel 'Trumpet' -> ch:14: new channel, placed on a free strip
  ADDED            channel 'Sax' -> ch:15: new channel, placed on a free strip
  ADDED            channel 'Trombone' -> ch:16: new channel, placed on a free strip
  ADDED            bus 'Horns' -> bus:8: new bus
  writes to: ch:14, ch:15, ch:16
  NOTE bus 'Horns' is new, given index 8 -- the lowest the plan on the desk leaves free
  NOTE channel 'Trumpet': patched to LCL 21, the socket the change named
  NOTE channel 'Sax': patched to LCL 22, the socket the change named
  NOTE channel 'Trombone': patched to LCL 23, the socket the change named
  NOTE channel 'Trumpet': the preset 'Trumpet' (Trumpet.chn) puts 83 processing values into the change, written with it and read back like every other write
  NOTE channel 'Sax': the preset 'A Sax' (A Sax.chn) puts 83 processing values into the change, written with it and read back like every other write
  NOTE channel 'Trombone': the preset 'T Bone' (T Bone.chn) puts 83 processing values into the change, written with it and read back like every other write
  NOTE 1 bus(ses) carry a bus preset's values, resolved from starter/presets: Horns: 'Mix Bus'
  NOTE the model said: 'sax' read as an alto sax, so it takes the A Sax preset; say 'baritone sax' for B Sax.
  NOTE the model said: The Horns mix bus is new: the Demo show has no horns until now.
  NOTE bus 'Horns' (index 8) was judged free from the applied plan alone -- the occupancy read covers strips, not busses

379 address(es) will be written; 1625 belonging to objects this amend does not own will NOT be.
  NOTE input.csv: 16 of its 16 row(s) are used by the changed plan and were checked as a full build checks them (stated sockets and presets, phantom power against the microphone); 4 channel(s) of the changed plan are not on it (Music, Trumpet, Sax, Trombone) -- added by this change, an earlier one or the conventions -- and are taken as they stand, not called invented. A row the plan does not use is not called dropped: a change does not rebuild the show

Pre-flight verify of the changed plan against the WING Compact the plan is for (reviewed offline: no desk was asked): no findings.
  ...
```

The review leads with **What this change does on the desk**: one line for each object the change adds, drops, moves or edits, in words, each object once. An output's or a bus's sockets are said whole, before and after, with what goes off named (*"output 'Matrix 1': out on LCL 7-8, AES50-A 1-2 -> LCL 7-8 (AES50-A 1-2 off)"*). Then how many addresses will be written, and, when the change moves audio on something already running, one `!!` line that says so. Everything else follows under **Details:**: what was read off the desk, each object's verdict, the fields old -> new, the notes, the addresses, and the pre-flight.

The pre-flight reads the show's `input.csv`, so the check that every input became a channel, that phantom power is safe for the microphones and that the list's stated sockets and presets match runs on the changed plan, and the NOTE line says what it was checked against. A change is not a rebuild, so it is held to the list differently from a full build: the channels it adds (and any that an earlier change added) are not on the list and are not called invented, a row the plan has no channel for is not called dropped, and a socket the change states for a channel stands over the one the list states. A show with no `input.csv` still gets the `reconcile.not-checked` warning.

The run ends by saying how long the review took, and that no console was contacted.

Each horn lands on the next free strip, on the socket you named, and takes its starter preset (Trumpet, A Sax, T Bone). The conventions put every horns channel on a **Horns** mix bus, which the Demo does not have yet, so the change adds it, with the **Mix Bus** bus preset: its compressor is among the writes, read back like the rest ([Bus presets](bus-presets.md)).

The presets come from the library the show was built with, found without a flag, and the first NOTE line says which one and why:

1. `--presets DIR`, when you give it;
2. else the library the plan on the desk records (every strip a build gave a preset's values names the library it came from), so the new strips match the ones already running. A plan built from the starter presets somewhere else (the Demo show, or a copy of it in `/tmp`) finds the packaged starter presets by their contents;
3. else `[presets] default` in `~/.atoo.config`. One that is not a folder, or holds no presets, is passed over, with a NOTE naming it.

With none of them, a change that names presets gives a warning first, before the review, as a `WARNING: no preset library was found ...` line naming them: the strips are still written and pass audio, without their presets' processing. Pass `--presets DIR` and preview again.

**A sax, with no kind named.** Where your conventions give presets by kind of instrument (alto and baritone sax) and the change does not say which, the most common kind is chosen and the notes say so, naming the other: *"'sax' read as an alto sax, so it takes the A Sax preset; say 'baritone sax' for B Sax."* The model is told never to leave a strip without its preset for want of a word.

Nothing already on the desk is written: the 1625 addresses that belong to the Demo's own strips are left alone, and on a real desk they are read before and after the write, as the proof that nothing else moved. A change can also edit what is running; see [Editing what is already running](#editing-what-is-already-running).

## Let the model say less: `--intent`

By default the model answers with a **change set**: the new channels written out in full, with their sockets and sends. A small or local model often gets that wrong. With `--intent` it answers with an **intent** instead: a short list of what you asked for, in a small vocabulary, and Atoo's own code works out the rest.

```bash
atoo patch --show touringband --console 192.0.2.16 --intent \
    "trumpet, sax and trombone on LCL 21-23, Band DCA"
```

The result is reviewed, and written with `--confirm`, exactly like any other change. What differs is who decides what:

| The model says | Atoo works out |
|---|---|
| which things to add, drop, move, rename or set, and the sockets you typed | the strip each new channel goes on, the socket for a channel you gave none, the bus, DCA and mute-group numbers, the stereo pair (the first socket odd, the second the next), every setting's range |
| a name only when you gave one | the name of a new bus, DCA, mute group or output you did not name, from your own words ("a stereo IEM bus" is called `IEM`), in a NOTE, `IEM 2` if `IEM` is taken |

**What it refuses.** A change the console cannot be left in is refused, with the reason, and nothing is written: a socket the desk or the stage box does not have, a strip past the desk's range, a stereo pair that starts on an even socket, a value out of range, a channel that is not on the desk. So is anything the model made up: a channel name with words nobody said, a microphone model nobody named, a preset that is not in the library, a color the console does not have. A socket **you** typed that does not exist is final: the model is not asked to put it somewhere else. Anything the model made up is sent back to it once, with the reason.

**What it chooses**, it says, in a NOTE: the strip, the socket (once, as *"the first free A socket"*, not as the model's pick), the width of a bus you did not state, the name of a new bus.

**Naming a group.** "HPF 100 on the vocals" names the Vocals DCA, not a channel; the setting is made on the DCA's channels and a NOTE lists them.

### Try it with no console, and no model

`--intent-file FILE` compiles an intent you already have, as `--change-set` uses a change set. In an Atoo checkout, the Demo show has one for its 6pm change, and an `--state` capture for the desk:

```
atoo patch --show starter/demo-show --conventions starter/conventions.md --intent-file docs/user/demo/demo-show/horns.intent.json --state atoo/web/demo_states/before.json "trumpet, sax and trombone on LCL 21-23, Band DCA"
```

```
  NOTE no desk was contacted (--state), so the applied plan is plan.json -- the bundle's last build. A run against the desk compares against the plan that desk's own newest write left on it, which may differ.
  NOTE conventions: starter/conventions.md (--conventions)
  NOTE instructions: starter/demo-show/instructions.md (layered on top, as for a build)

Compiling the change: trumpet, sax and trombone on LCL 21-23, Band DCA
  NOTE channel 'Trumpet': no strip was named, so it goes on ch 14, the next strip past the last one in use (ch 13)
  NOTE channel 'Sax': no strip was named, so it goes on ch 15, the next strip past the last one in use (ch 14)
  NOTE channel 'Trombone': no strip was named, so it goes on ch 16, the next strip past the last one in use (ch 15)

Change: Add Trumpet, Sax and Trombone on LCL 21-23
  NOTE preset library: starter/presets -- the library the plan on the desk was built with (its strips' preset values record it)
...
```

An intent that asks for something the desk does not have is refused, and says which:

```
atoo patch --show starter/demo-show --conventions starter/conventions.md --intent-file docs/user/demo/demo-show/tamb-a49.intent.json --state atoo/web/demo_states/before.json "add a tambourine mic Tamb on A 49"
```

```
  NOTE no desk was contacted (--state), so the applied plan is plan.json -- the bundle's last build. A run against the desk compares against the plan that desk's own newest write left on it, which may differ.
  NOTE conventions: starter/conventions.md (--conventions)
  NOTE instructions: starter/demo-show/instructions.md (layered on top, as for a build)

Compiling the change: add a tambourine mic Tamb on A 49
  REFUSED          op 1 (add_channel 'Tamb'): this console has A inputs 1 to 48, so A 49 does not exist
Refusing to patch: nothing was written. The change asks for something the console cannot do, or the model made up something the desk does not have (each reason above says which).
  ...
```

(The terminal also prints a warning that this saved state names no stage boxes, so a socket past a box's size cannot be checked here; the limit shown is the console's own.)

**Which models.** Three local models made all fifteen of our test changes with `--intent`: [Which model](ai-provider.md#which-model) names them. The change-set form stays the default until `--intent` does as well on a hosted model. A local model should be run with `ATOO_AI_NUM_PREDICT` set (for example `800`) so a reply that never stops is cut off.

## The rules

- **Writing a change never touches `plan.json`.** What a change put on a desk is recorded in that desk's journal entry, which the next change (or amend) of the same desk reads as its starting point — so typing the same change twice finds the horns already there and writes nothing. Keeping the change in the show (below) is what puts it into `plan.json`, and the write's last lines say so: ``plan.json is unchanged: Keep this in the show (`atoo patch --show touringband --promote 1`) puts the change into it and the sheets.``
- **Add, remove, and edit only what is named.** A change adds channels, busses, DCAs, mute groups and outputs, drops channels, busses, DCAs, mute groups and outputs, and sets the fields it names on anything already running — nothing else about a running strip moves. **An object you drop is cleared** (see [Clearing a bus](#clearing-a-bus) and [Clearing a DCA, a mute group or an output](#clearing-a-dca-a-mute-group-or-an-output)).
- **A channel can move.** *"Move Playback to Aux 8"* builds the channel on its new strip and returns the old strip to free, leaving the input sockets alone. The review lists it twice, `ADDED` on the new strip and `RELEASED` on the old one, with a NOTE saying it was moved. If the strip you name is not free, the channel goes on a free one instead, and the review says which.
- **A channel you drop is dropped, even if the desk has changed.** *"Lose the MD vocal"* returns the strip to free whatever somebody has done to it since the build — renamed or repatched. The review gives a `WARNING`: what the strip holds now, and that it is not what the plan built. Undo puts it back. (A rebuild with `amend` that merely leaves a channel out never named it, so it still leaves a changed strip alone.)
- **A change never moves what you did not name.** If setting a field would also change addresses on other objects — patching a strip onto a socket another strip uses turns that strip's link off too — the change is **refused, and the refusal is the question**: it names the other objects and the addresses it would move, and says how to go ahead. Name those objects in the change as well (say what you want done to each) and it is carried out, like any instruction you state. Nothing is written with a warning instead.
- **A channel can be made stereo, or mono again.** *"Make ch 5 stereo"* puts a mono channel that is on an odd socket on that socket and the next one, if nothing uses it, with a `NOTE`; name the pair in the change to choose it yourself. What cannot be done is refused with the reason: a cable on an even socket cannot be one half of a pair where it is (a stereo pair on a WING starts on an odd socket), and a second socket another channel uses is not taken. Made mono again, the channel keeps its first socket and the second is left as the desk has it; the second input-list row of the pair stays on the list, unused, and the change is not stopped for it.
- **A running channel can be moved to another strip.** *"Move the Kick to ch 30"* returns ch 1 to free, as a dropped channel's strip is, and writes the Kick whole on ch 30: its name, patch, processing, sends, DCA and mute group go with it. *"Swap the Kick and the Snare"* moves both; each strip is written once, by the channel that lands on it. A move to an aux strip works the same way. The move is refused only for a strip that cannot take the channel: one past the desk's range, one a running channel holds that the change does not also move or drop (named, so you can say what to do with it), or one the desk reads as somebody else's or did not answer for. Undo puts both strips back.
- **Which input-list row a strip takes can be set.** *"Ch 1 is now the Kick Sub"* sets the strip's `source.input` (or `source.pair_input`, the second row of a stereo pair). The patch stays where it is unless the change names a socket, and a NOTE says so: the cable is taken to be where it was.
- **A bus, DCA, mute group or output can be renumbered.** *"Make the Drums bus bus 14"* writes the bus whole on bus 14 and returns bus 5 to an initialized desk's reading. Everything that pointed at it moves with it: every channel's send into it, a DCA's or mute group's tags on its members, the routes into a Main or Matrix and a Matrix's feed. Each object that moves is named in a NOTE. *"Make the matrix a Main"* takes the lowest free Main unless the change names one; routes to its old number stay there, and a NOTE names them. Two objects can swap numbers in one change: each is written whole on the other's number, with its own sends, tags and routes, and each address is written once. Refused only for a number past the desk's range, or one another object holds that the change does not also renumber or drop (named). The new number is judged free from the plan on the desk, because the desk read covers strips, not busses, DCAs, mute groups or outputs; a NOTE says so.
- **A channel's preset can be switched.** *"Use the Snare preset on the Kick"* expands the new preset over the running channel as a build would: the values that differ are written, a value the old preset set and the new one does not goes back to what an initialized strip reads, and a field the plan states itself (a high-pass you typed, say) stays as stated. A preset the library does not have is refused, with that reason. A channel built with no preset can be given one the same way.
- **A bus's preset can be switched, effect and all.** *"Use the Snare Verb preset on the Vox Verb bus"* expands the bus preset over the running bus in the same way, and loads its effect into an FX engine nothing else on the plan inserts: the one the preset was saved from when that one is free, else the next free engine that can hold it. The engine's model, its parameters and the bus's insert are written; an engine the bus no longer inserts keeps its old effect, inserted nowhere, as the desk has it. The engine is judged free from the plan on the desk, since the desk read covers strips, not FX engines. When every engine that can hold the effect is in use, the change is refused, naming them. See [A bus preset on a running bus](#a-bus-preset-on-a-running-bus).
- **A channel can be inserted, and then the strips after it move.** *"Add HiHat after Snare"* puts HiHat on the next free strip and moves nothing; *"insert HiHat after Snare and renumber the channels after it"* puts it beside Snare and moves every strip after it down. The words decide, and [the section below](#inserting-a-channel-and-renumbering-the-strips-after-it) says which ones.
- **A line source takes a line gain only when no gain is stated.** A channel whose type is Line, patched to a head amp (a stage box's or a local input), takes 0 dB where the plan gave it more than 10 dB and **nothing states a gain**: not your conventions, not `instructions.md`, not the Category table, not the change. A NOTE explains: *a Line source on A 16, a head amp, so its gain is 0 dB, not the 20 dB the plan had -- that is a mic's gain, and a line-level feed with it would clip the preamp.* Where your conventions do state a gain, even a line about every channel ("set the input gain on each channel to 20dB"), that gain applies to a line source too and stands, and nothing is announced. A build does the same; a change reads the conventions and `instructions.md` as well as its own words.
- **A socket past the end of a stage box does not exist.** The desk lists 48 sockets on every AES50 port whatever is plugged in, so `A 17` on an S16 is accepted by the console and heard by nobody. Atoo asks the desk what is on each port; the S16 has 16 inputs and 8 outputs. Whether you named a socket is read from your words, not from the model's say-so: a socket your change writes ("on A 17") is yours, and past the box it is refused by the pre-flight, naming the box and its size; a socket the change leaves to Atoo ("add two choir mics") is chosen within the box, and if the model picked one the box lacks, the next free socket is used instead, with a NOTE. A stereo channel needs two adjacent sockets; if the box has no free pair left, the next free `LCL` pair is used and the NOTE says why (see [the pre-flight](amend.md#the-pre-flight-the-same-checks-as-apply)). A box Atoo has no size for is reported, and its sockets are not checked.
- **What the change leaves out is not a reason to refuse it.** A change that adds one channel and says nothing of busses, DCAs or outputs goes on, with a NOTE: *the change set left out add.busses, ...; each is read as empty*. The same holds for a file given to `--change-set`.
- **A name that runs long is cut, not refused.** A change's short name is a label in the journal, at most 48 characters, and a new channel's name is what the console shows, at most 16. A longer one is cut and said in a NOTE, and the rest of the change stands, even when your change quotes the long name (*Add a vocal mic called "Featured Guest Vocalist From The Opening Act"* adds `Featured Guest V`): *the change's name 'Add HiHat and F Lead2, move Playback to ch 16 on A 16 as mono' is 61 characters, longer than the 48 it is shown at; it is cut to 'Add HiHat and F Lead2, move Playback to ch 16 on'*. A paid answer is never lost to a label. A rename of a strip already on the desk is cut the same way (*the new name for channel 'Snare' ... is 30 characters, longer than the 16 it is shown at*). A change that fails to compile prints which Atoo ran (version and where it is installed) under the error, and the Patch page's failure finding carries it too. An answer Atoo cannot use at all is kept as `change.partial.json` in the show bundle, and the error says why.
- **Something the plan or the desk cannot take refuses the change** (`REFUSED`, exit `2`): a reference to something that is not there (*"it names bus 'MON9', which is neither on the desk nor added by this change"*), a field a running object does not carry, or a value out of range. Say it again naming what is there, or add the missing object in the same change. The browser heads the review "Refused: cannot be written as asked", and each line says which it is. A change that compiles to nothing at all, because the model judged it impossible and only said so, is refused the same way (exit `2`), with the model's note printed above the refusal: *Refusing to patch: the change, as compiled, adds, drops and edits nothing, so it was not carried out -- the reason is the note above.*
- **Each change's text and short name are recorded** in the desk's journal entry, numbered in the order they are written, so the journal stack reads as a list of changes. `atoo undo --show DIR` pops a change exactly as it pops an amend, and names it:

  ```
  Reversing the newest entry in touringband/journals on this desk:
    2026-09-26T00:45:16.925926+00:00  patch  change 1: Add Trumpet, Trombone and T.Sax on A 21-23  APPLIED: 51 address(es) evaluated, 39 written, 0 mismatch(es).  (scope: ch:21, ch:22, ch:23)  [on FOH-A (wing-compact) serial S2203A1, at 198.51.100.9:2223]
  ```
- **A full apply warns before it replaces changes** that are not in `plan.json` — in `atoo apply`'s output and in the Apply screen's pre-flight, as a WARNING, not an error:

  ```
  WARNING  plan.json: a full apply replaces 1 change(s) on this desk (FOH-A
           (wing-compact) serial S2203A1, at 198.51.100.9:2223) that are not in
           plan.json: change 1: Add Trumpet, Trombone and T.Sax on A 21-23. The
           apply writes the plan as built: a channel a change dropped comes
           back, and a channel a change added stays on its strip but is no
           longer tracked -- the next patch treats that strip as somebody
           else's.
           Fix: to keep a change for good, `atoo patch --promote <change>` (Keep
           this in the show, on the page) puts it into plan.json and the sheets;
           to take an added channel off the desk, undo that change before the
           apply; to drop a channel again after the apply, patch the drop again.
           (apply.replaces-changes)
  ```

  Do not "patch it back on" after an apply: the added channel is still on its strip, and a second patch would place a second copy of it. A change you have kept in the show is not listed: it is in `plan.json`, so the apply writes it.
- **A bus, DCA, mute group, Main or Matrix the plan does not know is read off the desk.** On a desk Atoo did not set up, or one set up by hand since, a change that names one — *"clear bus Drums"*, *"put the sax in the Horns DCA"* — reads just that object's name from the desk (never a sweep of it), and for a drop also which strips send into the bus or belong to the group. It is then carried out against what the desk holds, and a `NOTE` says it was found there (*"bus 'Drums' is not in the plan on the desk, but the desk holds it as bus 5"*). A strip that sends into it or belongs to it but is not in the plan has that taken away too, from what the desk read: its send switched off, or the group's tag taken out of its tags (its other tags stay). A `NOTE` names those strips, and Undo puts them back. A name the desk does not hold either is still refused.

  A Main or Matrix the plan does not know is read the same way, by the name the desk gives it or by its number (*"drop Matrix 1"*). Dropping a Matrix switches off every send into it the desk reads as on, from a strip, a bus or a Main, whether or not the plan holds it. Dropping a Main leaves the strips routed to it as they are. Either way the output sockets it feeds were not read, so they stay patched as the desk has them, and a `NOTE` says so. Undo puts it all back.

  Such an object can be edited as well as dropped. An edit of a bus writes only what it names (*"tilt +2 on the Drums bus"*); sending the bus to a socket reads which Mains it is routed to first, so the route it leaves is switched off. Renumbering a Main or Matrix (*"make Room EQ Matrix 3"*) reads all of it off the desk, with every send or route into it, and writes them on the new number; the old number is cleared. The output sockets it feeds are not read, so they still take the old number: name them in the change to move them too. A number the desk already holds under another name is refused.

  A change that **adds** a Main or Matrix by a name the desk already holds is about that one, not a second: it is carried out as moving it to the number the change gives, or, when it is already there, as nothing. A `NOTE` says so (*"the change adds output 'Delay', which the desk already holds as Matrix 2: carried out as moving it to Matrix 4, as the change asks, not as a second one"*). The name is matched, never the number.

## Clearing a bus

*"Clear bus 5 and 6, we are not using them. Add a stereo IEM bus (reuse bus 5) and output to LCL 3-4."* is one change, and it is carried out as said: a bus you drop is **returned to free**, and the new bus can take its place.

- **What a freed bus is** is the same on every WING (Compact, Full and Rack): every setting on it reads as an initialized desk has it — name, color, icon, mono/stereo and width, fader and mute, EQ, dynamics, inserts, DCA and mute-group tags, and its routes to the Mains and matrices. The output socket it fed is unpatched. Its fader goes to −∞ first, so it is silent while the rest is cleared.
- **Every send into it is switched off**, on every channel that had one, and the send's level and mode go back to what an initialized desk reads. The channels are otherwise left exactly as they are.
- **A bus keeps its number for the new bus if you say so.** *"Reuse bus 5"* puts the new bus on bus 5, the bus the same change returns to free; a new bus with no number named takes the lowest free one. Either way a NOTE says which and why. A bus is mono or stereo on its own on a WING, so a stereo IEM on bus 5 takes bus 5 alone — bus 6 is simply free — and its output on `LCL 3-4` carries its left on socket 3 and its right on 4.
- **A refusal is for a setting the desk cannot hold**: a bus number past the desk's last bus, or a new channel whose send names a bus the same change drops (a send to nothing). Each says which.
- **Undo puts every address back**, as for a channel.

The change set for those words, written by hand as a model would answer (`docs/user/demo/demo-show/clear-bus.change-set.json`; the Demo's buses 5 and 6 are Drums and Vocals), run offline from the top of an Atoo checkout:

```
atoo patch --show starter/demo-show --change-set docs/user/demo/demo-show/clear-bus.change-set.json --state atoo/web/demo_states/before.json
```

```
  NOTE no desk was contacted (--state), so the applied plan is plan.json -- the bundle's last build. A run against the desk compares against the plan that desk's own newest write left on it, which may differ.

Change: Clear 5 and 6, add stereo IEM
  NOTE preset library: starter/presets -- the library the plan on the desk was built with (its strips' preset values record it)

What this change does on the desk:
  returned to free bus 'Drums' -> bus:5
  returned to free bus 'Vocals' -> bus:6
  added bus 'IEM' -> bus:5
  channel 'Kick': bus_sends: Drums removed
  channel 'Snare': bus_sends: Drums removed
  channel 'Rack Tom': bus_sends: Drums removed
  channel 'Floor Tom': bus_sends: Drums removed
  channel 'OH': bus_sends: Drums removed
  channel 'Lead Vox': bus_sends: Vocals removed
  channel 'BV Gtr': bus_sends: Vocals removed
  channel 'BV Keys': bus_sends: Vocals removed

342 address(es) will be written.

Details:
48 strip(s) read over 206 address(es): 14 ours, 0 theirs, 34 free, 0 unknown
  this read asked each strip for its name, its link-to-source flag and its input patch, and asked every patched socket for ITS name -- which on a WING is where a name somebody typed actually lives. It did not ask what anything is routed to, so a strip that is routed somewhere but neither named nor patched reads as free here. `atoo audit` asks the rest.
  ...
```

The review's lines for the buses (the summary's first lines, then the NOTEs that say what was chosen):

```
  RETURNED TO FREE bus 'Drums' -> bus:5: dropped by the change: bus 5 is returned to free -- every setting on it reads as an initialized bus (name, color, icon, width, fader, mute, EQ, dynamics, inserts, tags, routes to the Mains and matrices), the output it fed is unpatched, and the channels' sends into it are switched off
  RETURNED TO FREE bus 'Vocals' -> bus:6: dropped by the change: bus 6 is returned to free -- every setting on it reads as an initialized bus (name, color, icon, width, fader, mute, EQ, dynamics, inserts, tags, routes to the Mains and matrices), the output it fed is unpatched, and the channels' sends into it are switched off
  ADDED            bus 'IEM' -> bus:5: new bus
  ...
  NOTE the change drops bus 'Drums' (bus 5): carried out -- the bus is returned to free, and every channel's send into it is switched off
  NOTE the change drops bus 'Vocals' (bus 6): carried out -- the bus is returned to free, and every channel's send into it is switched off
  NOTE bus 'IEM' is new, put on bus 5 as the change said -- the bus this change returns to free
```

The summary at the top names the eight channels whose send into bus 5 or 6 is taken away (`bus_sends: Drums removed`). Nothing here asks the model; whether a given model words *"clear bus 5"* as a drop is the model's part, and the review above is what it is checked against before anything is written.

## Clearing a DCA, a mute group or an output

*"Get rid of the FX DCA and the FX mute group. Make a Horns DCA on DCA 5."* Dropping any of these is carried out the way dropping a bus is: the object is **returned to free**, the same on every WING (Compact, Full and Rack), from the initialized capture of your console model.

- **A DCA or a mute group** reads as an initialized one — name, color, icon, fader and mute — and **every strip that was a member is taken off it** (channels and buses alike; a strip's other DCAs and mute groups are kept, and its tag is rebuilt without the dropped one). A DCA's fader goes to −∞ first.
- **An output** (a Main or a Matrix, and the socket it fed) reads as an initialized Main or Matrix, and its socket reads as an initialized desk's; a Matrix is also taken off the Main or bus that fed it. Channels and buses that still route to a dropped Main are left as they are, and the review lists them: that is a routing you did not ask to change.
- **The number is free for a new one in the same change.** *"Make a Horns DCA on DCA 5"* puts it on DCA 5, the DCA the same change returns to free; a new DCA or mute group with no number named takes the lowest free one, and a new output takes the Main or Matrix the change names (*"add a Matrix 'Delay' on Matrix 4"*), or the lowest free one when it names none or names one that is taken, and may take the socket the dropped one fed. A NOTE says which and why. A number past the desk's range is refused (*"this console has Matrices 1 to 8 -- there is no matrix 9"*).
- **A refusal is for a setting the desk cannot hold**: a number past the desk's last DCA or mute group, or a drop naming something not on the desk.
- **Undo puts every address back.**

The change set for those words (`docs/user/demo/demo-show/clear-groups.change-set.json`; the Demo's DCA 5 and mute group 3 are both FX), run offline from the top of an Atoo checkout:

```
atoo patch --show starter/demo-show --change-set docs/user/demo/demo-show/clear-groups.change-set.json --state atoo/web/demo_states/before.json
```

```
  NOTE no desk was contacted (--state), so the applied plan is plan.json -- the bundle's last build. A run against the desk compares against the plan that desk's own newest write left on it, which may differ.

Change: Drop FX groups, add Horns DCA
  NOTE preset library: starter/presets -- the library the plan on the desk was built with (its strips' preset values record it)

What this change does on the desk:
  returned to free dca 'FX' -> dca:5
  returned to free mute group 'FX' -> mgrp:3
  added dca 'Horns' -> dca:5
  bus 'Vox Verb': dca FX -> none; mute_group FX -> none

10 address(es) will be written.

Details:
48 strip(s) read over 206 address(es): 14 ours, 0 theirs, 34 free, 0 unknown
  this read asked each strip for its name, its link-to-source flag and its input patch, and asked every patched socket for ITS name -- which on a WING is where a name somebody typed actually lives. It did not ask what anything is routed to, so a strip that is routed somewhere but neither named nor patched reads as free here. `atoo audit` asks the rest.

1 added, 2 returned to free, 14 unchanged, 1 edited
  RETURNED TO FREE dca 'FX' -> dca:5: dropped by the change: returned to free -- its fader, mute, name, color and icon read as an initialized DCA's and its members are taken off it
  RETURNED TO FREE mute group 'FX' -> mgrp:3: dropped by the change: returned to free -- its name and mute read as an initialized mute group's and its members are taken off it
  ADDED            dca 'Horns' -> dca:5: new dca
  EDITED           bus 'Vox Verb': only the field(s) the change names are written (dca, mute_group); nothing else on this bus is touched, and the rest of it is in the untouched proof
  fields changed on objects already on the desk (only these; nothing else on them is written):
    bus 'Vox Verb': dca FX -> none
    bus 'Vox Verb': mute_group FX -> none
  ...
```

The summary's last line, and the `EDITED` line under Details, name the Vox Verb bus, the one member of both FX groups, so it is the one strip edited: its tags go to none.

## Inserting a channel, and renumbering the strips after it

Something was missed on the input list, and the desk has to line up with the real one on site: the hi-hat is a channel of its own, and it belongs after the snare. **What you type decides whether the strips after it move.**

- **To renumber, say so**: *insert*, *renumber*, or *move the rest down*. *"Insert HiHat after Snare and renumber the channels after it"* puts HiHat on the strip below Snare's, and every strip from there to the first free one moves down by one. Each of them is rewritten whole on its new number (its patch, name, color, processing, bus sends, DCA and mute-group membership go with it), and **the review lists every strip that moves**.
- **Otherwise, nothing moves.** *"Add HiHat after Snare"* is the ambiguous case: the channel goes on the next free strip, and a NOTE says that it was not renumbered and gives the words that would.

The Demo show has the snare on ch 2 and the rack tom on ch 3. The same change set, compiled once, run both ways. This is the insert:

```bash
atoo patch --show starter/demo-show --change-set docs/user/demo/demo-show/hihat.change-set.json --state atoo/web/demo_states/before.json "insert HiHat after Snare and renumber the channels after it"
```

```
1 added, 3 unchanged, 11 shifted
  SHIFTED          channel 'Rack Tom' -> ch:4: moves from ch:3 to ch:4 to make room for the insert, and is rewritten whole on its new strip
  SHIFTED          channel 'Floor Tom' -> ch:5: moves from ch:4 to ch:5 to make room for the insert, and is rewritten whole on its new strip
  ...
  SHIFTED          channel 'Playback' -> ch:14: moves from ch:13 to ch:14 to make room for the insert, and is rewritten whole on its new strip
  ADDED            channel 'HiHat' -> ch:3: new channel, inserted here: the channels after it move down one strip
  writes to: ch:3

!! 11 RUNNING STRIP(S) RENUMBERED -- each is rewritten whole on its new number the moment it is written:
!!   'Rack Tom': ch:3 -> ch:4
!!   'Floor Tom': ch:4 -> ch:5
...
!!   'Playback': ch:13 -> ch:14
```

And this is the same change typed as *"add HiHat after Snare"*:

```
1 added, 14 unchanged
  ADDED            channel 'HiHat' -> ch:14 (the change asked for ch:3): new channel, placed on a free strip
  ...
  NOTE channel 'HiHat': the change puts it at ch 3, which is in use, and does not ask for the strips after it to be renumbered, so it went on ch:14, the next free strip, and nothing already on the desk moved. To put it there and move the others down, say: "insert HiHat after Snare and renumber the channels after it".
```

What an insert does and does not do:

- **It is a rewrite of many strips**, so the preview lists each one and marks it on the desk drawing; the write is read back like any other, and the journal records which strip went where. **`atoo undo` puts every address back.**
- **Where the move stops.** The run of channels from the insertion point moves down until the first free strip; strips after that gap stay where they are. If the strip the last channel would land on is not free (somebody else's, or past the end of the desk), nothing moves and the change is blocked, naming it.
- **Faders and mutes the plan does not state are not carried.** A moved strip's fader goes to -inf and it is unmuted, as an untouched strip reads: raise it again. One that the plan states is written as stated.
- **An insert, an edit and a drop can share a change.** An edit of a strip the insert moves is written with the move (the strip is rewritten whole on its new number, with a NOTE); an edit of the channel the change inserts (*"insert HiHat after Snare, HPF 200 on it"*) is set on it and written with it; a drop beside an insert is carried out, and a strip the dropped channel leaves that a moved channel lands on is written once, by the channel that lands. A move or a renumber can share the change too. Each address is written once, and Undo puts every one back.
- **The input list is not edited** until you keep the change in the show (`--promote`, below). Keeping it adds the new input's row at the end of `input.csv` and writes each moved row's `channel` cell, so a rebuild puts every input on the strip the desk has it on.

## Editing what is already running

A change may also change something **already on the desk** — *"move the sax to MON3 at -10"*, *"rename ch 5 Kick In"*, *"HPF 100 on the vocals"*, *"put the horns in the Band DCA"*, *"mute group Speech on the host"* — but **only in the fields it names**. That is enforced in code, not left to the model:

- **Code sets those fields and no others**, and refuses a field the object cannot carry or a change may not set (the build's own record of where a strip came from, say), the whole change with it. Only the addresses whose value moves are written; the rest of the strip is in the before/after read that proves nothing unrelated moved.
- **A show built with presets edits like any other.** A channel or bus that carries a preset's values (see [Presets](presets.md)) is renamed, moved, muted or given a new fader like any other, and the preset's values on it are left exactly as they were: they are not among the fields the change names, so none of them is written. A change cannot set those values themselves; asking a running channel or bus for a *different* preset switches it, as above, and writes only the values that move.
- **A running strip's 48V, mic model and input can be set.** *"48V on the snare"* and *"the vocal mic is an SM58"* are edits of the strip's `source.phantom` and `source.model` (and `source.type`); *"ch 1 is now the Kick Sub"* is an edit of its `source.input`, and its patch stays unless the change names a socket. Whether it is stereo is set as above.
- **A stereo channel's 48V switches on both sockets or neither.** The desk does not take one side of a stereo channel on its own, so *"48V on the keys"* sets `source.phantom` and the review marks both sockets under `SWITCHES 48V LIVE`. When the plan states a different value for the second socket, the second follows, with a NOTE line. A change that would switch only the second socket (`source.pair_phantom` alone), or leave the two different, is refused, and the refusal names `source.phantom`; nothing is written. A pair the change does not touch the 48V of stays as it was built.
- **Switching 48V on a running strip is live**, so it is said first and on its own, beside a repatch (from Atoo's test desk and a stubbed model):

  ```
  !! 1 PHANTOM POWER CHANGE(S) ON SOMETHING ALREADY RUNNING -- 48V is switched the moment it is written:
  !!   SWITCHES 48V LIVE -- channel 'Snare' on ch:2: source.phantom false -> true
  ```

  It is written to the socket's own phantom address the moment you confirm. No console address carries a mic model or type, so nothing is written to the desk for them: it is kept (in the plan the desk's journal entry holds) only when the same change writes something else, and a change that is only a model writes nothing and leaves no entry; set it in the input list and rebuild. A change that leaves a passive ribbon microphone with 48V on is refused, because that destroys the microphone; switch the 48V off in the same change:

  ```
  REFUSED          channel 'Snare' -> ch:2: the change edits it, and 'Royer R-121' is a passive ribbon microphone and the change leaves it with phantom power on -- 48V destroys a ribbon element and switching it off again does not undo the damage; set source.phantom false in the same change -- refused rather than half-written
  ```
- **The review says each edited object once, in words**, at the top (`channel 'T.Sax SM57': bus_sends: MON3 level -144 -> -10.0`), and under Details each field old -> new, as an `EDITED` line and in the "fields changed" block.
- **A fader moves only when the change says "fader"** (and a mute only when it says "mute" — "mute group" is a membership, not the mute). A fader the model set anyway is shown as `MODIFIED`, not written.
- **A repatch of a running strip moves audio the moment it is written**, so it is said at the top, once, under the line that says what changes (from Atoo's test desk and a stubbed model):

  ```
  What this change does on the desk:
    channel 'BassDI': patch A 6 -> A 30

  5 address(es) will be written.
  !! It moves audio on channel 'BassDI', already running, the moment it is written: check what is plugged in where before you arm it.
  ```

  The new socket's own name, color, phantom and gain are written with it — unless another strip on the desk uses that socket, when they are that strip's and are left alone, with a note. The old socket keeps its name.
- **Taking something away is written as off**: a send the change removes is switched off, a high-pass it removes is switched off, and a strip that leaves every DCA and mute group has those tags cleared (other tags kept). An output socket taken off a bus, a Main or a Matrix (*"remove all the AES50-A outputs"*) is switched off on the desk, its source set to OFF (never back to a local output's factory feed from the Main); the object's other sockets stay as they are, and an object left with none stays, with no output.
- **A change that only removes adds nothing.** Typed as a removal (*"remove"*, *"delete"*, *"clear"*, *"unpatch"*, *"disconnect"*, *"take off"*), with no word that puts something somewhere, it keeps no socket the object did not already have: one the model added is left off, and a NOTE says which. An object that went out on two places keeps the other one: that is not a new socket.
- **An edit that would rewrite another object is refused.** Patching a running strip onto a socket another running strip uses turns that other strip's source link off too — and that strip is not named, so the change is refused.
- **Undo puts every edited field back**: the journal records each address's value before the write, as it does for every write.

## A bus preset on a running bus

The Demo's **Vox Verb** bus carries the *Vox Verb* bus preset: a V-REV in FX5 on its pre-insert. `docs/user/demo/demo-show/snare-verb.change-set.json` is the change *"use the Snare Verb preset on the Vox Verb bus"*, as a model compiles it: one field, the bus's `preset`. Run it from the top of an Atoo checkout, with no desk and no model:

```
atoo patch --show starter/demo-show --change-set docs/user/demo/demo-show/snare-verb.change-set.json --state atoo/web/demo_states/before.json
```

```
  NOTE no desk was contacted (--state), so the applied plan is plan.json -- the bundle's last build. A run against the desk compares against the plan that desk's own newest write left on it, which may differ.

Change: Snare Verb on the Vox Verb bus
  NOTE preset library: starter/presets -- the library the plan on the desk was built with (its strips' preset values record it)

What this change does on the desk:
  bus 'Vox Verb': preset Vox Verb -> Snare Verb

12 address(es) will be written.

Details:
48 strip(s) read over 206 address(es): 14 ours, 0 theirs, 34 free, 0 unknown
  this read asked each strip for its name, its link-to-source flag and its input patch, and asked every patched socket for ITS name -- which on a WING is where a name somebody typed actually lives. It did not ask what anything is routed to, so a strip that is routed somewhere but neither named nor patched reads as free here. `atoo audit` asks the rest.

14 unchanged, 1 edited
  EDITED           bus 'Vox Verb': only the field(s) the change names are written (preset, preset_values); nothing else on this bus is touched, and the rest of it is in the untouched proof
  fields changed on objects already on the desk (only these; nothing else on them is written):
    bus 'Vox Verb': preset "Vox Verb" -> "Snare Verb"
    bus 'Vox Verb': preset_values {"preset": "Vox Verb", "file": "FX Vox Verb.bus", "library": "starter/presets", "sha256": "2e283e8906b0bd3a7723e450f4... -> {"preset": "Snare Verb", "file": "FX Snare Verb.bus", "library": "starter/presets", "sha256": "bf3c8a07f670470940c6ac...
  NOTE bus 7 ('Vox Verb')'s pre-insert: GATED goes into FX8 -- the engine the preset was saved from
  NOTE bus 'Vox Verb': the bus preset 'Snare Verb' (FX Snare Verb.bus) replaces the old one's processing values and effects; its GATED goes into FX8; what the old preset set and this one does not goes back to what an initialized strip reads; no preset leaf changes value
  NOTE bus 'Vox Verb': FX8 was judged free from the plan on the desk alone -- the occupancy read covers strips, not FX engines
  NOTE bus 'Vox Verb': preset "Vox Verb" -> "Snare Verb" -- no console address carries it, so nothing is written to the desk for it; it is kept (in the plan the journal entry holds) only when the same change writes something else
  NOTE bus 'Vox Verb': FX5 is no longer inserted on it; it keeps the old preset's effect and its values, inserted nowhere, as the desk has it

12 address(es) will be written; 1613 belonging to objects this amend does not own will NOT be.
  12 of them CHANGE A RUNNING OBJECT -- only the fields the change names:
    /fx/8/mdl: bus 7 (Vox Verb): FX8 effect GATED
    /fx/8/fxmix: bus 7 (Vox Verb): FX8 GATED fxmix
    /fx/8/pdel: bus 7 (Vox Verb): FX8 GATED pdel
    /fx/8/att: bus 7 (Vox Verb): FX8 GATED att
    /fx/8/dcy: bus 7 (Vox Verb): FX8 GATED dcy
    /fx/8/dens: bus 7 (Vox Verb): FX8 GATED dens
    /fx/8/diff: bus 7 (Vox Verb): FX8 GATED diff
    /fx/8/sprd: bus 7 (Vox Verb): FX8 GATED sprd
    /fx/8/lc: bus 7 (Vox Verb): FX8 GATED lc
    /fx/8/hsf: bus 7 (Vox Verb): FX8 GATED hsf
    /fx/8/hsg: bus 7 (Vox Verb): FX8 GATED hsg
    /bus/7/preins/ins: bus 7 (Vox Verb): pre-insert -> FX8 (GATED)
  NOTE input.csv: 16 of its 16 row(s) are used by the changed plan and were checked as a full build checks them (stated sockets and presets, phantom power against the microphone); 1 channel(s) of the changed plan are not on it (Music) -- added by this change, an earlier one or the conventions -- and are taken as they stand, not called invented. A row the plan does not use is not called dropped: a change does not rebuild the show

Pre-flight verify of the changed plan against the WING Compact the plan is for (reviewed offline: no desk was asked): no findings.
  ...
```

The *Snare Verb* preset was saved with its GATED in FX8, which nothing on the plan inserts, so it goes there; FX5 keeps the V-REV, inserted nowhere. The two presets set the same bus processing, so no bus value moves; between two presets that differ, the NOTE lists the leaves that move. Only FX8 and the bus's insert are written, and Undo puts back what the desk held before: the model FX8 had, and that model's own parameters, which the desk drops when the model changes.

When every engine that can hold the effect is already inserted somewhere, the change is refused, naming them: *"the bus preset 'Snare Verb' inserts GATED on its pre-insert, and every FX engine that can hold it (FX1-8) is already in use on the desk"*. Take an effect off another bus first, to free one.

## Keeping a change in the show: `--promote`

A change is ad hoc: `plan.json` does not have it, and a full apply replaces it. When the horns turn out to be permanent, **keep** the change in the show instead of retyping it into your files. `plan.json` and each sheet the change touches come to say what it did:

```bash
atoo patch --show touringband --promote 1
```

`1` is the change's number (`change 1` works too), or give its short name or its journal entry. The run below is Atoo's own test desk and a stubbed model standing in for the WING and the change compile. The change was *"congas on A 21 and 22, in the Drums DCA and the Drums bus"*, written to that desk first:

```
Keep change 1: Add Conga Hi and Conga Lo on A 21-22 in the show:

  input.csv:
    row 'Conga Hi' added, on channel 21 from AES50-A 21
    row 'Conga Lo' added, on channel 22 from AES50-A 22

  plan.json:
    CH 21 'Conga Hi' added
    CH 22 'Conga Lo' added

  instructions.md is not touched.
  NOTE 'Conga Hi': category 'drums' -- the category of 'Kick', which shares its DCA 'Drums'
  NOTE 'Conga Lo': category 'drums' -- the category of 'Kick', which shares its DCA 'Drums'

Nothing was written -- this was a preview. Re-run with --confirm to keep change 1: Add Conga Hi and Conga Lo on A 21-22 in the show.
```

`--confirm` writes the files it listed:

```
Written: input.csv, plan.json. change 1: Add Conga Hi and Conga Lo on A 21-22 is in the show now: plan.json says it, and so do the sheets, so a rebuild keeps it.
```

What it writes, file by file:

- **`input.csv`**: a row for each input the change added, on the strip it went to (its `channel` cell) and from the socket it is on, after the rows already there. Its category and type are inferred and said in a NOTE; a stereo channel is two rows. An input the change dropped loses its row. A running input the change renamed, repatched (`OFF` when it unpatched it), moved, or put in another DCA or mute group has those cells changed. A column the list does not have yet (`channel`, `dca`) is added, blank on the other rows. Every row the change did not touch keeps its exact text.
- **`busses.csv`, `outputs.csv` and `user.csv`**, where the show has them: a bus, Main or Matrix the change touched has its filled cells say what it is now (a blank cell means "the plan's" and stays blank), one it added gains a row, and one it took out reads `OFF`. A socket the change took off loses its `outputs.csv` row. As in `input.csv`, every row the change did not touch keeps its exact text, and so do the file's encoding mark, its line endings and any column of your own.
- **`plan.json`**: the sheets laid on by the same code a Save in Build's step 04 uses, and checked the same way. What cannot physically work is refused, naming the cell, and nothing is written. **A field no sheet says** is written into `plan.json` and marked *(in plan.json only)*, with a NOTE: a rebuild works it out again from the input list and conventions. That is a field no sheet holds, such as a high-pass or a fader, and one the sheets leave to the plan: a strip renamed while its input keeps its name (*channel 'KICK IN' (ch:1): name (in plan.json only)*), or a send taken off a bus whose `sources` cell is blank.
- **`instructions.md` is never written.** The change is kept as what it did, not as the words you typed.
- **Refused**: a change that was **undone** (it is not on the desk, so there is nothing to keep), one that aborted partway, and an amend from a rebuilt plan. Keeping the same change twice writes nothing the second time: *already in the show*.

In the browser, **Keep this in the show** does the same: under a standing Patch preview (before anything is written to the desk), in step 3 after the change is written, and on each change in **History** ([Patch a show](patch-a-show.md)).

## Write exactly the change you reviewed

A model asked the same thing twice can answer differently, so a `--confirm` writes the change set your preview compiled, not a second answer. A preview keeps what it compiled in the show, in `previews/patch.json`, and says so. Run the same command again with `--confirm`:

```bash
atoo patch --show touringband --console 192.0.2.16 \
    "trumpet, sax and trombone on LCL 21-23, Band DCA, send to MON2"
# read the review, then the same words with --confirm:
atoo patch --show touringband --console 192.0.2.16 \
    "trumpet, sax and trombone on LCL 21-23, Band DCA, send to MON2" --confirm
```

The confirm says *NOTE writing the change set your preview compiled (2026-11-07 21:40), not asking the model again*, and its `Timing:` line reads *model call: none (the preview of ...)*. It does that only when nothing the preview depended on has changed: the same words, the same `plan.json`, no write to the desk since, and the same console, `--allow-strip`, console model and `--intent`/`--no-constrain`. Otherwise the confirm compiles the change itself and says why in a NOTE (*the last preview in this show was of another change*, or *was made on another plan, desk or flags*); what it writes is then the review it prints.

To keep a change for later, or write it from another show or machine, save it and write that file. The saved file carries the change's text as well, so the journal records it:

```bash
atoo patch --show touringband --console 192.0.2.16 \
    "trumpet, sax and trombone on LCL 21-23, Band DCA, send to MON2" \
    --save-change-set horns.json
atoo patch --show touringband --console 192.0.2.16 \
    --change-set horns.json --confirm
```

A `--review-json` file works as a `--change-set` too. The Patch screen does the same for you: its write is always the change set its preview showed.

## How long a change takes

Every run ends with a `Timing:` line: the desk read, a second or two, and the model call, which varies with the provider and the model.

While it runs, each read and write of the desk says what it is doing on stderr: `occupancy read`, `reading the untouched strips, before writing`, `checking each setting, writing what differs`, then the same proof read after. The lines are the ones [`apply` prints](applying.md#while-it-runs); `--no-progress` turns them off.

## See also

- [Applying a plan](applying.md) — `apply`, flags and exit codes; [the journal](journals.md)
- [Undoing a write](undo.md) — `atoo undo`
- [Patching from a rebuilt plan](amend.md) — `atoo amend`
- [One plan, two desks](two-desks.md)
- [Command reference](cli-reference.md) — every flag, generated from the code
