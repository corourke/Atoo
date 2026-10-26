# Capturing a desk you didn't build

Some desks are already set up, and nobody is going to rebuild them from an
input list: a church's weekly patch, a venue's house desk, a show somebody
else built. `atoo capture` reads that desk as it is and makes it a show you
can watch and edit, with **no model** and **nothing written to the desk**.

```bash
atoo capture --console 192.0.2.148
```

or, from a show file saved on the desk:

```bash
atoo capture --snap CCC-20261024.snap --console-model wing-full
```

A `.snap` does not say which WING saved it, and the three have different
sockets, so a `.snap` needs `--console-model` (`wing-full`, `wing-compact`
or `wing-rack`). A live desk states its own model.

In the browser, press **New show…** in the bundle bar and choose **From a
desk**: **The console** reads the console in the bar, and **A .snap file**
asks for the file and which WING saved it. **Folder** is where the show
goes, named as below; change it if you like. The dialog says what it
does: *Captures the desk to input.csv and busses.csv which you can
edit.* Press **Capture this desk**, and the new show opens on Build's
step 04, where you edit it ([below](#editing-the-sheets)). On the Watch
page with no show open, **Make a show from this desk** opens the same
dialog on the console Watch is reading, and Watch keeps running
([Watch the desk](watch-a-show.md#with-no-show-make-a-show-from-this-desk)).

## What it makes

A show folder in your Atoo folder (`~/Documents/Atoo/`, or `--dir`), named
after the `.snap`, or after the desk's model and the date for a live desk
(`wing-full-2026-10-25`). A name already taken gets `-2`, `-3`; `--name`
chooses your own. Rename the folder freely afterwards.

| File | What's in it |
|---|---|
| `input.csv` | One row per input in use, in the [input list](input-lists.md)'s format, with three more columns: `channel`, `dca` and `mute_group`. A stereo source is two rows on one channel |
| `busses.csv` | One row per bus, Main and Matrix in use: its `name`, its `role` (what it is for), `width`, what feeds it (`sources`, and whether `pre` or `post` in `tap`), the sockets it feeds (`outputs`), the effects inserted on it (`fx`), its DCAs and mute groups, a `label` and `notes` |
| `outputs.csv` | One row per output socket fed straight from a source rather than from a bus, Main or Matrix: a split or a recording feed. The `output` socket, its `source` in the desk's own words, and `notes`. See [Splits and recording feeds](#splits-and-recording-feeds) |
| `plan.json` | The desk as it is: patch, routing, membership, widths and effects. Not faders, mutes, send levels or EQ: they are the mix |
| `watch.json` | Empty, ready for [watch conditions](watch-conditions.md) |
| `captures/` | The `.snap` it was made from, or a live desk's reading |

Every example on this page runs from the top of an Atoo checkout, on a
church's full-size WING frozen there as a test fixture:

```bash
atoo capture --snap tests/fixtures/church-full-2026-10-24.snap --console-model wing-full --dir /tmp/shows
```

```
Captured the snapshot tests/fixtures/church-full-2026-10-24.snap to /tmp/shows/church-full-2026-10-24/
  input.csv    46 inputs on 40 channels
  busses.csv   15 buses, 1 Mains, 5 Matrices
  outputs.csv  123 output sockets fed straight from a source
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

The desk does not state everything a sheet has a column for. What it
leaves open, `capture` decides and says, at INFO, so you can correct it:

- **Every name is written in.** A channel with no name of its own takes its
  source's ("CH 20 takes 'MIC2' from LCL 4"). An input list's names must
  be unique, so a name the desk uses twice is written as
  `Acoustic (CH 7)` on the second row; the plan keeps the desk's name.
- **`category`** is the channel's first DCA's name, or `other`.
- **`type`** is `Line` for a source on a Dante or SoundGrid module, USB, a
  card, the USB player or AES/EBU, and `Mic` for everything else.
- **`role`** is left for you, except `fx`: a bus whose effects are all
  reverbs, delays, modulation or pitch effects, set fully wet, is an
  effect return. A bus with a doubler or a compressor on it (a vocal bus)
  carries the dry signal too, so it stays blank.
- **`tap`** is the pre or post most of a row's sources use; a source that
  differs says so in `sources` (`Crowd (pre)`).

## Effects

Every effect switched on in an insert, on a channel, bus, Main or Matrix,
goes into `plan.json` on that strip: the effect, the engine it is in and
all of that engine's settings. A bus's, Main's or Matrix's are in its `fx`
cell too, and a channel's in its row's `notes` (the input list has no
effects column):

```bash
grep "^Bus 11" /tmp/shows/church-full-2026-10-24/busses.csv
grep "^17," /tmp/shows/church-full-2026-10-24/input.csv
```

```
Bus 11,Reverb,fx,stereo,MIC1 Lead;MIC2;MIC3;MIC4;MIC5,post,,BPLATE; VSS3,,AllBand;FX Vocals,BAND;VOCAL;ALL,,
17,LCL 1,Pastor,Speaker,Mic,,FALSE,Speaker,SPEAKING;ALL,"Inserts: GEQ (FX9, preins)"
```

`atoo apply` loads each effect back into its engine with those settings
and switches its insert on. Applied to the desk it came from, that changes
nothing; applied to another desk, or after someone changed the effects,
it puts them back. Watch checks them too: an insert switched off, pointing
at another engine, or an engine holding another effect is a warning,
`CV015 Effect Insert Contradicts Plan`.

From a live desk, the effects' settings are one more short read after the
desk's: one request for each engine a strip inserts, counted in the
capture's summary (*plan.json the desk as it is: ..., effects; 16
effect(s), their parameters read in 16 more request(s) after the desk's
read*). An engine that does not answer keeps its effect only, at INFO:
`atoo apply` loads the effect and leaves its settings as the desk has them.

To change a bus's, Main's or Matrix's effects, edit its `fx` cell in Build's
step 04 (or the file), with the effects' names as the desk shows them,
`;`-separated:

- an effect still named keeps its engine and settings;
- an effect you delete comes off its insert (the engine keeps it, inserted
  nowhere); emptying the cell takes them all off;
- an effect you add goes on a free insert, in a free engine that can hold
  it, with its settings as the desk has them, and a note in the plan says
  which engine;
- a name the desk has no effect for, more than two effects, or no engine
  left that can hold it is refused, naming the cell, and nothing changes.

On the church show, open **B13** (Delay Long) with **▸**: its FX cell
reads `TAP-DL`. Type `NOPE` and the row turns red with *fx "NOPE": no FX
engine on the desk offers this effect; write the model as the desk names
it (V-REV, ST-DL)*. Type `ST-DL` and press **Save busses.csv**: *Saved
church-full-2026-10-24/busses.csv: 1 row(s) changed. The plan is updated:
Bus 13 fx ST-DL.* The plan's notes say *Bus 13: TAP-DL comes off its
pre-insert.* and *Bus 13: ST-DL goes on its pre-insert, in FX2, a free
engine that can hold it; its parameters are left as the desk has them.*
Type `V-PLATE` in **M1**'s FX cell instead and it is refused: *every
engine that can hold V-PLATE (FX1-8) is already in use*.

## Splits and recording feeds

An output socket the desk feeds straight from a source, not from a bus, a
Main or a Matrix, is a split: the Dante module's outputs to a recording
machine, the WING-LIVE card one to one, a USB recording feed, an AES50
split to a monitor desk. The capture writes each one to `outputs.csv`, one
row per socket, and the plan records them (`direct_outputs`). The capture
says which, at INFO:

```
  [INFO] 123 output socket(s) carry an input or a monitor feed directly, not a bus, Main or Matrix (recording and Dante splits): AES50-A 33-40; AUX 3; AUX 7-8; AES50-B 25-32; CRD 1-14; CRD 17-24; CRD 29-30; MOD 3-35; MOD 40-42; MOD 46-48; USB 1-28; USB 30-40; USB 45-46. They are in outputs.csv, one row each; Apply writes them and Watch says only if one changes.
```

The file has one row per socket, never a range, in the order the desk lists
its outputs:

```bash
head -4 /tmp/shows/church-full-2026-10-24/outputs.csv
grep "^USB 5," /tmp/shows/church-full-2026-10-24/outputs.csv
```

```
output,source,notes
AUX 3,SEND 19,
AUX 7,MON 1,
AUX 8,MON 2,
USB 5,AES50-A 5,
```

A `source` is written as the desk lists it:
- an input socket, as the input list spells it: `AES50-A 5`, `LCL 3`,
  `MOD 12`;
- a user signal or patch: `USR 3`;
- the oscillator: `OSC 1`;
- a bus, a Main or a Matrix by its side: `Bus 9 L`, `Main 1 R`, `Matrix 6 L`;
- a send or the monitor by the desk's own number: `SEND 19`, `MON 1`;
- `OFF` for nothing.

There is no "channel, pre-fader" source, because the desk has none. A split
carries the input before the channel strip. A processed or post-fader feed
goes through a user signal, and its row says `USR n`.

`atoo apply` writes each one's source, as it writes a bus's output patch,
so the show puts its splits back on any desk; applied to the desk it came
from, they are already there and nothing changes. In Apply's Preview they
are on their output group's tile. Watch counts them as part of the show,
so it says only if one changes. `atoo verify` refuses a split on a socket
a bus, a Main or a Matrix also patches, naming both, and one fed from a
source the desk does not have.

A build lays `outputs.csv` onto the plan the way it lays `busses.csv`:
- a row with a filled `source` wins over the conventions;
- `OFF` disconnects that socket;
- a socket the file doesn't list is left to the conventions.

Each change is an INFO (`build.outputs-sheet`). A row that cannot work stops
the build, naming it: a socket the desk does not have, one a bus or a Main
also patches, a source past its group's end. Build's step 04 does not show
the file yet; its table is waiting on a design review.

## What stays out of the sheets

Nothing is dropped silently. Each of these is one INFO line, naming what
it is about, and the snapshot in `captures/` keeps the whole desk:

- **A send in the desk's GRP mode** has its tap left undecided.
- **A channel on the oscillator** is left out.
- **A bus nothing feeds that reaches only a Main** is left out, and no
  `sources` cell names it. A desk initialized at the factory routes its
  unused buses to Main 1, so capturing one says, for example, *Left out of
  the sheets: Bus 9, Bus 10, Bus 11, Bus 12, Bus 13, Bus 14, Bus 15 and Bus
  16, which nothing feeds and which reach only a Main, so no row has them and
  no sources cell names them.*

## Watching it

Every send goes into `plan.json` as well as `busses.csv`: a channel sent
straight to a Matrix (the drummer's in-ears), a bus sent to another bus (a
broadcast mix built from the band's buses), and a Matrix fed by several
sources, each with its pre or post. So Watch follows those routes too, and a
send the show has that is switched off is reported.

Give Watch the show, from the command line or with the show open in the
browser:

```bash
atoo watch --show /tmp/shows/church-full-2026-10-24 --console 192.0.2.148
```

A captured plan's routing counts as asked for, so a deliberate split such
as a reverb bus or a parallel-compression bus is a note (`R013`), not a
warning. The plan states no mix, so a channel muted during a service is
not a finding. Anything a rule finds about the desk itself, such as a bus
that reaches nothing or a dead link, is still reported.

## Editing the sheets

Build's step 04 shows the two sheets as its three tables, every cell
editable:

- **Channels** is `input.csv`: channel, patch, name, category, type, 48V,
  DCA and mute group. Press **▸** on a row for its model, preset and notes.
- **Busses** and **Mains and Matrix** are `busses.csv`: name, role, width, sources,
  tap and outputs. **▸** opens its effects, preset, DCAs, mute groups,
  label and notes, and **Feeds**: where the row goes, worked out from the
  other rows' sources.

A cell left empty shows, in grey, what the plan has there. Type in a cell
and the table marks it; **Save** writes the file and updates the plan, with
no model. Under the Channels table it says *Save writes the input.csv file
and updates the build plan.*, and under Busses and Mains and Matrix *Save writes
the busses.csv file and updates the build plan.* Renaming an input or a bus
renames it in every row's sources too.

`sources` is the list of what feeds a row, separated by `;`: channel names,
bus names, an input-list category, `*` for every channel, and on a Matrix,
Main names. `Kick (pre)` sets that one source's tap. Take a name out and
its send comes out of the plan; add one and it goes in, post-fader if
nothing says pre, and the Save's message says so.

A cell that cannot work on the desk turns red, with the reason under its
row, before you press Save: a socket the desk does not have
(`LCL output 9 does not exist -- LCL outputs are 1..8 on a WING
(full-size console)`), a Main feeding a bus, a source nothing is called,
two inputs on one channel. **Save** stays locked until it is fixed.

Nothing goes to the desk until you apply the plan. A role, a label or a
note changes nothing on the desk.

### While Watch runs

**Edit sheets** on the Watch page brings you to this step, and Watch keeps
running; **Back to Watch** returns to it. It reads the plan on its next pass after a Save, with no
restart. A role changes what it says (a split through a `parallel` bus is
*Parallel bus asked for*, quoting the cell); anything the desk would change
for is a WARNING, **Sheet differs from desk**, until you apply it, with
**Open in Apply** beside it ([Edit the sheets while it
runs](watch-a-show.md#edit-the-sheets-while-it-runs)).

## Applying it back

A captured plan is the desk as it is, so applying it back to the same desk
changes nothing: a preview of it lists nothing that would change. It
states no faders, mutes or send levels, and `atoo apply` leaves those as
the desk has them, rather than setting unity and unmuted as it does for a
built show. It also does not [reset the desk to initialized or unpatch
the strips it does not hold](what-apply-changes.md), as a full apply of a
built show does: it writes its own patch, routing, names, membership and
widths, and nothing else. `atoo verify` says so
(`capture.mix-left-to-desk`).

Its sends and its DCAs and mute groups are the whole list of them: a full
apply switches off every send between the strips the plan holds that the
plan does not list, and takes a strip out of a DCA it is no longer in. So a
send you took out of a sheet comes off the desk, and only its switch is
written: its level is left as it was.

## The `channel`, `dca` and `mute_group` columns

They are the [input list](input-lists.md#the-channel-dca-and-mute_group-columns)'s
own optional columns, so you can also write them by hand. A Save in step
04 carries them into the plan, and a build places channels by them, so a
filled cell wins over the conventions. Where a filled cell and the plan
disagree (the sheet changed in a spreadsheet since), `atoo verify` says so
(`input-list.column-not-followed`), so a cell that had no effect never looks
honoured. A captured show's plan agrees with its sheets.

A build reads `busses.csv` too. On a captured show, **Build plan** asks
first: *This plan was read from the desk. Build plan replaces it with a new
plan from your conventions, using a model; your sheet edits still win.*
**Continue** builds; **Cancel** (or Esc) leaves the plan as it is. Rebuild a
captured show from your
conventions and the bus sheet still wins wherever it has a filled cell: the
names, roles, widths, sources, outputs and effects it gives are laid onto
the new plan, each change a note in the build's report (in **Findings**,
under **Choices**), with the engine each added effect was given. A
cell that cannot work on the desk stops the build, naming the cell, as Save
does in step 04: *busses.csv cannot be laid onto this plan, so nothing was
written: busses.csv, Bus 4, outputs: LCL output 99 does not exist …*
