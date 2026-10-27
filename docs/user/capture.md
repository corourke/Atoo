# Capturing a desk

Some desks are already set up, and nobody is going to rebuild them from an input list: a church's weekly patch, a venue's house desk, a show somebody else built. `atoo capture` reads that desk as it is and makes it a show you can watch and edit, with **no model** and **nothing written to the desk**.

```bash
atoo capture --console 192.0.2.148
```

or, from a show file saved on the desk:

```bash
atoo capture --snap CCC-20261024.snap --console-model wing-full
```

A `.snap` does not say which WING saved it, and the three have different sockets, so a `.snap` needs `--console-model` (`wing-full`, `wing-compact` or `wing-rack`). A live desk states its own model.

In the browser, press **New show…** in the bundle bar and choose **From a desk**: **The console** reads the console in the bar, and **A .snap file** asks for the file and which WING saved it. **Folder** is where the show goes, named as below; change it if you like. The dialog says what it does: *Captures the desk to input.csv and busses.csv which you can edit.* Press **Capture this desk**, and the new show opens on Build's step 04, where you edit it ([below](#editing-the-sheets)). On the Watch page with no show open, **Make a show from this desk** opens the same dialog on the console Watch is reading, and Watch keeps running ([Watch the desk](watch-a-show.md#with-no-show-make-a-show-from-this-desk)).

## What it makes

A show folder in your Atoo folder (`~/Documents/Atoo/`, or `--dir`), named after the `.snap`, or after the desk's model and the date for a live desk (`wing-full-2026-10-25`). A name already taken gets `-2`, `-3`; `--name` chooses your own. Rename the folder freely afterwards.

| File | What's in it |
|---|---|
| `input.csv` | One row per input in use, in the [input list](input-lists.md)'s format, with three more columns: `channel`, `dca` and `mute_group`. A stereo source is two rows on one channel |
| `busses.csv` | One row per bus, Main and Matrix in use: its `name`, its `role` (what it is for), `width`, what feeds it (`sources`, and whether `pre` or `post` in `tap`), the sockets it feeds (`outputs`), the effects inserted on it (`fx`), its DCAs and mute groups, a `label` and `notes` |
| `outputs.csv` | One row per output socket the desk patches: the `output` socket, its `source` in the desk's own words (an input socket for a split or a recording feed, `Bus 9 L` for a bus's left side), and `notes`. See [Every output socket](#every-output-socket-outputscsv) |
| `user.csv` | Only when the desk uses one: one row per USR slot a channel or an output reads, saying what the slot takes. See [User signals and patches](#user-signals-and-patches-usercsv) |
| `plan.json` | The desk as it is: patch, routing, membership, widths and effects. Not faders, mutes, send levels or EQ: they are the mix |
| `watch.json` | Empty, ready for [watch conditions](watch-conditions.md) |
| `captures/` | The `.snap` it was made from, or a live desk's reading |

Every example on this page runs from the top of an Atoo checkout, on a church's full-size WING frozen there as a test fixture:

```bash
atoo capture --snap tests/fixtures/church-full-2026-10-24.snap --console-model wing-full --dir /tmp/shows
```

```
Captured the snapshot tests/fixtures/church-full-2026-10-24.snap to /tmp/shows/church-full-2026-10-24/
  input.csv    46 inputs on 40 channels
  busses.csv   15 buses, 1 Mains, 5 Matrices
  outputs.csv  147 output sockets: 123 fed straight from a source, 24 by a bus, a Main or a Matrix
  plan.json    the desk as it is: patch, routing, membership, widths, effects
  watch.json   empty, ready for watch conditions
  captures/church-full-2026-10-24.snap

What the desk does not state, decided or left out (12):
  [INFO] 30 channel(s) have no name of their own, so the name of their source is written in: CH 2 takes 'Piano2' from AES50-A 2; ...
  [INFO] category from each channel's first DCA, or 'other' with none: 'other' for CH 1, CH 2, CH 16, CH 26, CH 28, CH 37, CH 38 and CH 40; ...
  [INFO] type 'Line' for a source on a module, USB, a card, the player or AES/EBU, 'Mic' for every other: Line on CH 26, CH 29, ...
  [INFO] role 'fx' for BUS 11 'Reverb': BPLATE and VSS3 inserted, 100% wet, so it is read as an effect return.
  ...

Nothing was written to the desk. Watch it with this show:
  atoo watch --show /tmp/shows/church-full-2026-10-24 --console <address>
```

The two sheets open in any spreadsheet:

```bash
head -4 /tmp/shows/church-full-2026-10-24/input.csv
grep "^Matrix 6" /tmp/shows/church-full-2026-10-24/busses.csv
```

```
channel,patch,name,category,type,model,phantom,dca,mute_group,notes
1,AES50-A 1,Piano1,other,Mic,,TRUE,,ALL,
2,AES50-A 2,Piano2,other,Mic,,TRUE,,ALL,
3,AES50-A 3,Bass,Bass/Keys/AG,Mic,,FALSE,Bass/Keys/AG,BAND;ALL,
Matrix 6,DRUMS IEM,,stereo,DR PAD;Kick;Snare;Snare Btm;Tom;Floor;OH A;OH B;High Hat,pre,MOD 36-37,,,,,,
```

## What it decides, and says

The desk does not state everything a sheet has a column for. What it leaves open, `capture` decides and says, at INFO, so you can correct it:

- **Every name is written in.** A channel with no name of its own takes its source's ("CH 20 takes 'MIC2' from LCL 4"). An input list's names must be unique, so a name the desk uses twice is written as `Acoustic (CH 7)` on the second row; the plan keeps the desk's name.
- **`category`** is the channel's first DCA's name, or `other`.
- **`type`** is `Line` for a source on a Dante or SoundGrid module, USB, a card, the USB player or AES/EBU, and `Mic` for everything else.
- **`role`** is left for you, except `fx`: a bus whose effects are all reverbs, delays, modulation or pitch effects, set fully wet, is an effect return. A bus with a doubler or a compressor on it (a vocal bus) carries the dry signal too, so it stays blank.
- **`tap`** is the pre or post most of a row's sources use; a source that differs is marked in `sources` (`Crowd (pre)`).

### The desk's colours

The capture keeps each colour as the desk shows it, so Build's step 04 draws it: a channel's, a bus's, a Main's and a Matrix's number, a channel's patch, and each Outputs row's source. A strip linked to its source (the WING's factory setting) shows its socket's colour, not its own, so that is the one drawn, and the plan states none of its own for it. Applied back, the plan writes each strip's own colour where the desk showed it, and leaves every socket's as it was. Navy, the desk's default, is drawn as Navy.

## Effects

Every effect switched on in an insert, on a channel, bus, Main or Matrix, goes into `plan.json` on that strip: the effect, the engine it is in and all of that engine's settings. A bus's, Main's or Matrix's are in its `fx` cell too, and a channel's in its row's `notes` (the input list has no effects column):

```bash
grep "^Bus 11" /tmp/shows/church-full-2026-10-24/busses.csv
grep "^17," /tmp/shows/church-full-2026-10-24/input.csv
```

```
Bus 11,Reverb,fx,stereo,MIC1 Lead;MIC2;MIC3;MIC4;MIC5,post,,BPLATE; VSS3,,AllBand;FX Vocals,BAND;VOCAL;ALL,,
17,LCL 1,Pastor,Speaker,Mic,,FALSE,Speaker,SPEAKING;ALL,"Inserts: GEQ (FX9, preins)"
```

`atoo apply` loads each effect back into its engine with those settings and switches its insert on. Applied to the desk it came from, that changes nothing; applied to another desk, or after someone changed the effects, it puts them back. Watch checks them too: an insert switched off, pointing at another engine, or an engine holding another effect is a warning, `CV015 Effect Insert Contradicts Plan`.

From a live desk, the effects' settings are one more short read after the desk's: one request for each engine a strip inserts, counted in the capture's summary (*plan.json the desk as it is: ..., effects; 16 effect(s), their parameters read in 16 more request(s) after the desk's read*). An engine that does not answer keeps its effect only, at INFO: `atoo apply` loads the effect and leaves its settings as the desk has them.

To change a bus's, Main's or Matrix's effects, edit its `fx` cell in Build's step 04 (or the file), with the effects' names as the desk shows them, `;`-separated:

- an effect still named keeps its engine and settings;
- an effect you delete comes off its insert (the engine keeps it, inserted nowhere); emptying the cell takes them all off;
- an effect you add goes on a free insert, in a free engine that can hold it, with its settings as the desk has them, and a note in the plan says which engine;
- a name the desk has no effect for, more than two effects, or no engine left that can hold it is refused, naming the cell, and nothing changes.

On the church show, open **B13** (Delay Long) with **▸**: its FX cell reads `TAP-DL`. Type `NOPE` and the row turns red with *fx "NOPE": no FX engine on the desk offers this effect; write the model as the desk names it (V-REV, ST-DL)*. Type `ST-DL` and press **Save busses.csv**: *Saved church-full-2026-10-24/busses.csv: 1 row(s) changed. The plan is updated: Bus 13 fx ST-DL.* The plan's notes say *Bus 13: TAP-DL comes off its pre-insert.* and *Bus 13: ST-DL goes on its pre-insert, in FX2, a free engine that can hold it; its parameters are left as the desk has them.* Type `V-PLATE` in **M1**'s FX cell instead and it is refused: *every engine that can hold V-PLATE (FX1-8) is already in use*.

## Every output socket: outputs.csv

`outputs.csv` says what each output socket carries: one row for every socket the desk patches, whatever feeds it. The file has one row per socket, never a range, in the order the desk lists its outputs:

```bash
head -4 /tmp/shows/church-full-2026-10-24/outputs.csv
grep "^USB 5," /tmp/shows/church-full-2026-10-24/outputs.csv
```

```
output,source,notes
LCL 1,Bus 9 L,
LCL 2,Bus 9 R,
LCL 3,Bus 8 L,
USB 5,AES50-A 5,
```

A bus, a Main or a Matrix is written by its side, so its two sockets are two rows. `busses.csv`'s `outputs` cell says the same sockets for each bus, worked out from the plan (`LCL 1-2` for Bus 9).

A socket that carries an object's R without its L on the socket before it (Bus 3's R alone on a USB socket, say) is recorded as that socket's own source, as the desk has it, and the capture says so at INFO; `busses.csv`'s cell leaves it out, since a cell's sockets go L then R.

### Splits and recording feeds

An output socket the desk feeds straight from a source, not from a bus, a Main or a Matrix, is a split: the Dante module's outputs to a recording machine, the WING-LIVE card one to one, a USB recording feed, an AES50 split to a monitor desk. The plan records them (`direct_outputs`), and the capture says which, at INFO:

```
  [INFO] 123 output socket(s) carry an input or a monitor feed directly, not a bus, Main or Matrix (recording and Dante splits): AES50-A 33-40; AUX 3; AUX 7-8; AES50-B 25-32; CRD 1-14; CRD 17-24; CRD 29-30; MOD 3-35; MOD 40-42; MOD 46-48; USB 1-28; USB 30-40; USB 45-46. They are in outputs.csv, one row each, with every other patched socket; Apply writes them and Watch says only if one changes.
```

A `source` is written as the desk lists it:
- an input socket, as the input list spells it: `AES50-A 5`, `LCL 3`, `MOD 12`;
- a user signal or patch: `USR 3`;
- the oscillator: `OSC 1`;
- a bus, a Main or a Matrix by its side: `Bus 9 L`, `Main 1 R`, `Matrix 6 L`;
- a send or the monitor by the desk's own number: `SEND 19`, `MON 1`;
- `OFF` for nothing.

There is no "channel, pre-fader" source, because the desk has none. A split carries the input before the channel strip. A processed or post-fader feed goes through a user signal, and its row says `USR n`. What the slot takes (a channel at its pre or post tap, say) is the plan's: a capture records every USR slot a channel or an output reads, in [`user.csv`](#user-signals-and-patches-usercsv) and the plan, and Apply writes it back; a slot assigned on the desk that nothing reads is left as it is, said at INFO.

`atoo apply` writes each one's source, as it writes a bus's output patch, so the show puts its splits back on any desk; applied to the desk it came from, they are already there and nothing changes. In Apply's Preview they are on their output group's tile. Watch counts them as part of the show, so it says only if one changes. `atoo verify` refuses a split on a socket a bus, a Main or a Matrix also patches, naming both, and one fed from a source the desk does not have.

**`outputs.csv` is where each socket's source is kept, and `busses.csv`'s Outputs column follows it.** A build lays `outputs.csv` onto the plan:
- a row with a filled `source` wins over the conventions, whatever fed the socket before: `LCL 1,Bus 10 L` moves LCL 1 from Bus 9 to Bus 10;
- a bus, a Main or a Matrix the file names feeds the sockets its rows give it and no others, so moving a bus's rows to new sockets moves the bus; it is not also left on its old ones;
- `OFF` disconnects that socket;
- a socket the file doesn't list is left to the conventions.

Each change is an INFO (`build.outputs-sheet`), for example *outputs.csv wins over the conventions: LCL 1 from AES50-A 1 (was Main 1 L).* Where the file takes sockets off a bus, a Main or a Matrix that a line of your instructions or conventions asks for in so many words, the build says so as a WARNING, quoting the line, for example *outputs.csv decides Main 1's sockets (LCL 1-2), so the instructions' 'Video Feed: Send the main mix to USB 18-19' is not carried out: USB 18-19 are not patched from Main 1. Add USB 18-19 to outputs.csv, or edit them in Build 04's Outputs table, to carry it out.*

When the show has `outputs.csv`, a build does not read `busses.csv`'s Outputs column. In Build's step 04 that column is read-only: you move a bus in the [Outputs table](#the-outputs-table), and its Save rewrites the bus's `busses.csv` cell to match. A cell edited in another program that disagrees with `outputs.csv` is not used, and the build says so, for example *busses.csv says Bus 9 goes to AUX 1-2, outputs.csv says LCL 1-2: outputs.csv is where each socket's source is kept, so it wins, and busses.csv's Outputs column follows it.* A row that cannot work stops the build, naming it: a socket the desk does not have, a socket listed twice, a source past its group's end.

**A show built from conventions has no `outputs.csv` at first.** Build's step 04 shows the plan's own outputs in its Outputs table, and says so: *This show has no outputs.csv yet -- these are the plan's outputs. Save writes outputs.csv, which will then take priority over conventions and instructions during a build.* Its first Save writes `outputs.csv` with every socket the plan patches, and from then on the file decides: a rebuild lays it on, so a change to your conventions no longer moves a socket the file lists. Edit the row instead, or delete `outputs.csv` to hand every socket back to the conventions.

## User signals and patches: user.csv

A WING's `USR` slots are how a channel or an output gets a signal the patch alone cannot give it: a **user signal** (USR 1-24) takes a channel, an aux, a bus, a Main or a Matrix before or after its fader, and a **user patch** (USR 25-56) takes an input socket as it is. A post-fader recording feed, or a stereo channel on two sockets that are not side by side, goes through one.

When the desk uses any, the capture writes `user.csv`: one row for every slot a channel or an output reads, in the desk's own words, and the summary says how many. A desk with USR 3 taking CH 10 after its fader, read by USB 29, gets:

```
slot,source,tap,leg,name
USR 3,CH 10,POST,L+R,Lead post
```

and the summary line

```
  user.csv     1 USR slot: 1 user signal
```

| Column | What it says |
|---|---|
| `slot` | `USR 1` to `USR 56` |
| `source` | for a user signal, a strip: `CH 10`, `AUX 2`, `BUS 8`, `MAIN 1`, `MTX 3`; for a user patch, an input socket as the input list spells it: `LCL 5`, `AES50-A 12`; `OFF` to take the slot out |
| `tap` | a user signal's `PRE` or `POST`; empty for a user patch |
| `leg` | a user signal's `L+R`, `L` or `R`; empty for a user patch |
| `name` | the slot's name on the desk |

A slot assigned on the desk that nothing reads gets no row; the capture says so at INFO. A desk that uses no slot gets no `user.csv`.

**A build lays it on** after `busses.csv` and `outputs.csv`: a row wins for its slot over what the conventions made, a blank `tap`, `leg` or `name` keeps the plan's, `OFF` takes the slot out, and a slot the file doesn't name is left to the conventions. Each change is an INFO (`build.user-sheet`), for example *user.csv wins over the conventions: USR 3 takes CH 11 PRE L+R (Lead post) (was CH 10 POST L+R (Lead post)).* A row that cannot work stops the build, naming it: a slot past USR 56, a user patch given a strip or a tap, a user signal given a socket, a strip the desk does not have, a slot listed twice. A slot nothing reads yet is kept, so you can define a feed before you patch it; verify says so at INFO, in case the slot number was mistyped. The plan records the file's fingerprint, so editing it in another program makes the plan **Stale** until you rebuild or save it in Build.

**Build's step 04 shows it** as its **User signals and patches** table, under Mains and Matrix: a row per slot, with what reads it (the outputs and channels fed from it) in **Read by**. **Add a slot** takes the lowest user signal the table does not have, at POST on both legs. A slot typed as a user patch drops its tap and leg. **Save** writes `user.csv` in the desk's words and updates the plan, with no model; a cell that cannot work locks it, with the reason under the row. What reads a slot is set in Outputs or Channels, not here.

## What stays out of the sheets

Nothing is dropped silently. Each of these is one INFO line, naming what it is about, and the snapshot in `captures/` keeps the whole desk:

- **A send in the desk's GRP mode** has its tap left undecided.
- **A channel on the oscillator** is left out.
- **A bus nothing feeds that reaches only a Main** is left out, and no `sources` cell names it. A desk initialized at the factory routes its unused buses to Main 1, so capturing one says, for example, *Left out of the sheets: Bus 9, Bus 10, Bus 11, Bus 12, Bus 13, Bus 14, Bus 15 and Bus 16, which nothing feeds and which reach only a Main, so no row has them and no sources cell names them.*

## Watching it

Every send goes into `plan.json` as well as `busses.csv`: a channel sent straight to a Matrix (the drummer's in-ears), a bus sent to another bus (a broadcast mix built from the band's buses), and a Matrix fed by several sources, each with its pre or post. So Watch follows those routes too, and a send the show has that is switched off is reported.

Give Watch the show, from the command line or with the show open in the browser:

```bash
atoo watch --show /tmp/shows/church-full-2026-10-24 --console 192.0.2.148
```

A captured plan's routing counts as asked for, so a deliberate split such as a reverb bus or a parallel-compression bus is a note (`R013`), not a warning. The plan states no mix, so a channel muted during a service is not a finding. Anything a rule finds about the desk itself, such as a bus that reaches nothing or a dead link, is still reported.

## Editing the sheets

Build's step 04 shows the sheets as its tables, every cell editable:

- **Channels** is `input.csv`: channel, patch, name, category, type, 48V, DCA and mute group. Press **▸** on a row for its model, preset and notes.
- **Busses** and **Mains and Matrix** are `busses.csv`: name, role and width, with the sockets it feeds as read-only badges (`LCL 3-4`), which you change in Outputs. **▸** opens its sources and their tap, its effects, preset, DCAs, mute groups, label and notes, and **Feeds**: where the row goes, worked out from the other rows' sources.
- **Outputs** is `outputs.csv`: every output socket the desk patches and what feeds it ([The Outputs table](#the-outputs-table)).
- **User signals and patches** is `user.csv`: slot, source, tap, leg and name. With no slot in use it says so, and **Add a slot** starts one ([User signals and patches](#user-signals-and-patches-usercsv)).

A cell left empty shows, in grey, what the plan has there. Type in a cell and the table marks it; **Save** writes the file and updates the plan, with no model. Under the Channels table it says *Save writes the input.csv file and updates the build plan.*, and under Busses and Mains and Matrix *Save writes the busses.csv file and updates the build plan.* Renaming an input or a bus renames it in every row's sources too.

`sources` is the list of what feeds a row, separated by `;`: channel names, bus names, an input-list category, `*` for every channel, and on a Matrix, Main names. `Kick (pre)` sets that one source's tap. Take a name out and its send comes out of the plan; add one and it goes in, post-fader if nothing says pre, and the Save's message tells you which.

A cell that cannot work on the desk turns red, with the reason under its row, before you press Save: a socket the desk does not have (`LCL output 9 does not exist -- LCL outputs are 1..8 on a WING (full-size console)`), a Main feeding a bus, a source nothing is called, two inputs on one channel. **Save** stays locked until it is fixed.

Nothing goes to the desk until you apply the plan. A role, a label or a note changes nothing on the desk.

### The Outputs table

One row per output socket: the socket, what feeds it in the desk's words (`Bus 9 L`, `AES50-A 5`, `USR 3`, `SEND 19`), and notes. Sockets that go up together, fed by sources that go up together, fold into one line of read-only badges: `USB 1-8 ← AES50-A 1-8`, or `LCL 1-2 ← Bus 9 L-R` for a bus's two sides. Press **▸** to open the run and edit its rows. A run holding an edited or refused row stays open.

The row's left edge says what feeds it: solid blue for an input socket (a split or a recording feed), double grey for a bus, a Main or a Matrix, dashed brass for a user signal or patch, dotted grey for a send, the monitor or the oscillator. The square beside the source is the desk's own colour for it, as [the desk shows it](#the-desks-colours).

To move a socket, change its output or its source; to disconnect one, type `OFF` as its source; **Add a socket** adds a row. Each cell is checked as you type, and one that cannot work turns red with the reason under its row. **Save outputs.csv** writes the file and updates the plan, with no model: the file is written in the desk's output order and words, with your notes, and a socket you took `OFF` has no row. Moving a bus, a Main or a Matrix rewrites its `busses.csv` Outputs cell too, and the Save says so: *busses.csv's Outputs column follows: Bus 9 AUX 1-2.*

### While Watch runs

**Edit sheets** on the Watch page brings you to this step, and Watch keeps running; **Back to Watch** returns to it. It reads the plan on its next pass after a Save, with no restart. A role changes what it says (a split through a `parallel` bus is *Parallel bus asked for*, quoting the cell); anything the desk would change for is a WARNING, **Sheet differs from desk**, until you apply it, with **Open in Apply** beside it ([Edit the sheets while it runs](watch-a-show.md#edit-the-sheets-while-it-runs)).

## Applying it back

A captured plan is the desk as it is, so applying it back to the same desk changes nothing: a preview of it lists nothing that would change. It states no faders, mutes or send levels, and `atoo apply` leaves those as the desk has them, rather than setting unity and unmuted as it does for a built show. It also does not [reset the desk to initialized or unpatch the strips it does not hold](what-apply-changes.md), as a full apply of a built show does: it writes its own patch, routing, names, membership and widths, and nothing else. `atoo verify` reports this (`capture.mix-left-to-desk`).

Its sends and its DCAs and mute groups are the whole list of them: a full apply switches off every send between the strips the plan holds that the plan does not list, and takes a strip out of a DCA it is no longer in. So a send you took out of a sheet comes off the desk, and only its switch is written: its level is left as it was.

## The `channel`, `dca` and `mute_group` columns

They are the [input list](input-lists.md#the-channel-dca-and-mute_group-columns)'s own optional columns, so you can also write them by hand. A Save in step 04 carries them into the plan, and a build places channels by them, so a filled cell wins over the conventions. Where a filled cell and the plan disagree (the sheet changed in a spreadsheet since), `atoo verify` warns (`input-list.column-not-followed`), so a cell that had no effect never looks honoured. A captured show's plan agrees with its sheets.

A build reads `busses.csv` too. On a captured show, **Build plan** asks first: *This plan was read from the desk. Build plan replaces it with a new plan from your conventions, using a model; your sheet edits still win.* **Continue** builds; **Cancel** (or Esc) leaves the plan as it is. Rebuild a captured show from your conventions and the bus sheet still wins wherever it has a filled cell: the names, roles, widths, sources, outputs and effects it gives are laid onto the new plan, each change a note in the build's report (in **Findings**, under **Choices**), with the engine each added effect was given. A cell that cannot work on the desk stops the build, naming the cell, as Save does in step 04: *busses.csv cannot be laid onto this plan, so nothing was written: busses.csv, Bus 4, outputs: LCL output 99 does not exist …*
