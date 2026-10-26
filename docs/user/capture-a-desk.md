# Capture a desk you didn't build

Some desks are already set up, and nobody is going to rebuild them from an
input list: a church's weekly patch, a venue's house desk, a show somebody
else built. Capturing reads the desk as it is and turns it into a show you
can watch and edit. It needs no AI model and writes nothing to the desk.

**You need:** the desk's address saved, or typed in the bar ([Set up
Atoo](configuration.md#2-connect-to-your-desk)).

## 1. Capture the desk

1. Run `atoo ui`.
2. In the bar at the top, press **New show…** and choose **From a desk**.
3. Choose **The console** to read the desk in the bar, or **A .snap
   file** to read a show file saved on the desk. A `.snap` doesn't say
   which WING saved it, so you choose the model too.
4. Check **Folder**: it is where the new show goes, in your Atoo folder.
5. Press **Capture this desk**.

The new show opens on Build's step 04, with its two sheets:

- **Channels** is the show's `input.csv`: one row per input in use, with
  its channel, patch, name, DCA and mute groups.
- **Busses** and **Mains and Matrix** are its `busses.csv`: one row per
  bus, Main and Matrix, with what feeds it and where it goes.

Where the desk doesn't state something a sheet has a column for, such as
a channel's category, Atoo makes a choice and tells you in a note in the
**Findings** panel, so you can correct it.

## 2. Watch it

Click **Watch**, then **Start watching**. With the captured show open,
Watch knows what the desk is meant to be: a deliberate split, such as a
reverb bus, is a note rather than a warning, and a channel muted during a
service is not a finding. A bus that reaches nothing or a stage box link
that drops is still reported.

Already watching a desk with no show open? Press **Make a show from this
desk** on the Watch page: the same capture, without stopping Watch.

## 3. Edit the sheets and apply them

Change a cell in step 04 and press **Save**: the sheet and the plan are
updated together, with no model. A cell that can't work on the desk turns
red with the reason, and **Save** waits until it is fixed.

Nothing reaches the desk until you apply the plan. Applying a captured
show writes only its patch, routing, names, DCAs, mute groups and widths.
It leaves the mix alone: faders, mutes, send levels and EQ stay as the
desk has them, and the desk is not reset. A send you took out of a sheet
is switched off on the desk; its level is left as it was.

## From the command line

```bash
atoo capture --console 192.0.2.148
atoo capture --snap CCC-20261024.snap --console-model wing-full
```

[Capturing a desk](capture.md) has the full detail: every file a capture
makes, what it decides and why, effects, splits and recording feeds, and
the sheets' columns.

## Next

[The command line](quickstart.md): the same work, typed, and what the
command line adds.
