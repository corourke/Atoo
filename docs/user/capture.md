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

## What it makes

A show folder in your Atoo folder (`~/Documents/Atoo/`, or `--dir`), named
after the `.snap`, or after the desk's model and the date for a live desk
(`wing-full-2026-10-25`). A name already taken gets `-2`, `-3`; `--name`
chooses your own. Rename the folder freely afterwards.

| File | What's in it |
|---|---|
| `input.csv` | One row per input in use, in the [input list](input-lists.md)'s format, with three more columns: `channel`, `dca` and `mute_group`. A stereo source is two rows on one channel |
| `busses.csv` | One row per bus, Main and Matrix in use: its `name`, `width`, what feeds it (`sources`, and whether `pre` or `post` in `tap`), the sockets it feeds (`outputs`), the effects inserted on it (`fx`), and its DCAs and mute groups |
| `plan.json` | The desk as it is: patch, routing, membership and widths. Not faders, mutes, send levels or EQ: they are the mix |
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
  plan.json    the desk as it is: patch, routing, membership, widths
  watch.json   empty, ready for watch conditions
  captures/church-full-2026-10-24.snap

What the desk does not state, decided or left out (15):
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

## What it cannot hold yet

Nothing is dropped silently. Each of these is one INFO line, naming what
it is about, and the snapshot in `captures/` keeps the whole desk:

- **A channel sent straight to a Matrix, a bus sent to a bus, and a Matrix
  fed by more than one source** are rows in `busses.csv`, but not yet in
  `plan.json`, which cannot hold them.
- **Sockets fed straight from an input**, such as a recording or Dante
  split, are not in the sheets. The plan records them, so Watch says only
  if one changes, and `atoo apply` does not write them.
- **Effects inserted on a channel** are listed in that row's `notes`.
- **A send in the desk's GRP mode** has its tap left undecided.
- **A channel on the oscillator** is left out.

## Watching it

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

## The `channel`, `dca` and `mute_group` columns

They are the [input list](input-lists.md#the-channel-dca-and-mute_group-columns)'s
own optional columns, so you can also write them by hand. **A build does
not place channels by them yet**: where a filled cell and the plan
disagree, `atoo verify` says so (`input-list.column-not-built`), so a
cell that had no effect never looks honoured. A captured show's plan
agrees with its sheets.
