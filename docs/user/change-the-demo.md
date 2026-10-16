# Change the Demo show

The guest singer is sitting in tonight, and the horn section turns up at
six. Those are the two ways a show changes: before the desk is set,
change a file and rebuild the plan; once it is set, patch the change on
and move nothing else. This page does both, on a copy of the Demo show.

**You need:** a model set up ([Setting up an AI provider](ai-provider.md))
for steps 4 and 6, and for steps 5 to 7 the desk you tried in [Testing
on your desk](testing-on-your-desk.md), **not doing a show**, with its
own show saved.

## 1. Make a copy of the Demo show

The Demo show is read-only. `atoo init --demo` writes a copy of your
own into your Atoo folder, as `demo-show`, beside the starter
conventions and presets it was built from. Run after `init`, it adds
only the copy:

```bash
atoo init --demo
```

```
Working folder: ~/Documents/Atoo (already there)
  README.md                    already there
  conventions.md               already there
  presets/README.md            already there
  presets/                     23 presets: 23 already there
  audit-demo/                  3 files: 3 already there
  demo-show/input.csv          created
  demo-show/instructions.md    created
  demo-show/plan.json          created
  demo-show/watch.json         created

~/.atoo.config:
  [conventions] default    already ~/Documents/Atoo/conventions.md
  [presets] default        already ~/Documents/Atoo/presets
  [workspace] default      already ~/Documents/Atoo

Next: `atoo ui` opens Atoo in your browser, starting in ~/Documents/Atoo. ~/Documents/Atoo/README.md says what each file is.
The Demo show's copy is ~/Documents/Atoo/demo-show: yours to edit, build and apply.
```

A `demo-show` folder already there is never written over. To start
again from a fresh copy, rename it and run `atoo init --demo` again.

## 2. Open the copy

1. Run `atoo ui`.
2. Next to **Show bundle**, press **Open…**.
3. Click **demo-show/** (tagged **SHOW BUNDLE**), then press **Open
   demo-show/**.

The bar reads **demo-show/**, and the four tiles read **LOADED**, with
**PLAN CURRENT** on **04 Plan**. Unlike the Demo show, this one can be
edited.

## 3. Bring the guest singer in

The input list already has the guest's microphone, switched off: its row
is skipped, so the build leaves it out.

1. Click the **02 Input list** tile. It reads **16 input rows · 1
   skipped**.
2. In the **Guest Vox** row, untick **Skip**. A yellow **UNSAVED
   CHANGES** tag comes up.
3. Press **Save**.

The **Order** cell of the Guest Vox row is empty now, where it read
`-`. The build will note that it built the guest's channel from a row
with no order number; if the band gives the guest a number, type it
there.

The tile now reads **17 input rows**, and **04 Plan** reads **STALE**:
the plan no longer matches its files. The verdict under **Findings**
reads **STALE** too, where it said **READY TO APPLY**, with a **Rebuild**
button.

## 4. Rebuild the plan

1. Click the **04 Plan** tile. Under **Options**, choose your desk's
   model under **Console model**.
2. Press **Rebuild plan** (on the tile, or in the **STALE** banner). Under
   **Options** the same button reads **Build plan**.

A build takes a few minutes. When it lands, the tile reads **PLAN
CURRENT**. The starter conventions put playback last, so Guest Vox takes
channel 13 and Playback moves along to 14. **Changed since the last
build** is folded, and reads *2 strips: 1 added, 1 moved*; open it for
the two strips by name. In the **Channels** table they carry **ADDED**
and **MOVED** by their numbers. Check what Guest Vox sends to, and read
the **Findings** panel ([Build a show](build-a-show.md#6-read-the-findings)
says how).

## 5. Apply it to the desk

1. Choose your desk next to **Console**: **Change…**, **Address**.
2. On **Build**, press **Apply the difference**, under **Build output**.
   It opens **Apply** with **Full build** chosen and runs the preview.
   (Or click **Apply** and press **Preview** yourself.)
3. Read the counts: the addresses read, how many **will change**, and
   how many already match. Then follow [Apply a plan to the
   desk](apply-to-desk.md): tick **Arm** and write.

A full build writes only the addresses that differ, so after one new
channel it writes that channel and what it touches, not the whole desk.
Every value written is read back. Look at the desk: the guest's channel
is there, named, coloured and patched.

## 6. The 6pm change: a patch

Now the desk is set. A full build would put the desk back to its
initialized state before it wrote the plan, which takes the mix off it.
A patch writes only what changed, and moves nothing else.

1. In **Apply**, choose **Patch** in the **Full build | Patch** control at the top.
2. In step 1, under **CHANGE**, type in the box:

   > trumpet, sax and trombone on LCL 21-23, Band DCA

3. Press **Preview**, and read what it will write: three new channels
   on free strips and a new **Horns** bus, with nothing already on the
   desk moving. The pre-flight shows one warning,
   `reconcile.not-checked`: a patch is not checked against the input
   list. It does not block the write.
4. Tick **Arm**, and press **Write changes to console**.

[Patch a show that is already on the desk](patch-a-show.md) explains
each step, and how to keep the change or take it off.

## 7. Put the desk back

Load the show you saved on the desk. To step back one write at a time
instead, see [Undoing a write](undo.md).

## From the command line

The same, with the copy's path and your desk's model and address:

```bash
atoo build --show ~/Documents/Atoo/demo-show --console-model wing-compact
atoo apply --show ~/Documents/Atoo/demo-show --console 192.0.2.16
atoo apply --show ~/Documents/Atoo/demo-show --console 192.0.2.16 --confirm
atoo patch --show ~/Documents/Atoo/demo-show --console 192.0.2.16 "trumpet, sax and trombone on LCL 21-23, Band DCA"
```

In a text editor, step 3 is clearing the `-` from the Guest Vox row's
`order` cell in `input.csv` ([Writing an input
list](input-lists.md#the-order-column-band-numbers-and-skipping-a-row)).
`apply` and `patch` without `--confirm` preview and write nothing.

## Next

[Build a show](build-a-show.md) of your own, from a new input list.
