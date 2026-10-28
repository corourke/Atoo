# Build your first show

Your own copy of the Demo show, changed and put on your desk, in the browser. There are two ways to change a show before it goes on the desk: edit the plan's tables directly, which needs no AI model, or change the show's files and build the plan again, which does.

**You need:** your desk ([Set up Atoo](configuration.md)), **not running a show**, with its own show saved. Step 4 also needs a model ([Setting up an AI provider](ai-provider.md)); skip it if you don't have one yet.

## 1. Make a copy of the Demo show

The Demo show is read-only. `atoo init --demo` writes a copy of your own into your Atoo folder, as `demo-show`, beside the starter conventions and presets it was built from. Run after `init`, it adds only the copy:

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

A `demo-show` folder already there is never written over. To start again from a fresh copy, rename it and run `atoo init --demo` again.

## 2. Open the copy

1. Run `atoo ui`.
2. Next to **Show bundle**, press **Open…**.
3. Click **demo-show/** (tagged **SHOW BUNDLE**), then press **Open demo-show/**.

The bar reads **demo-show/**, and the four tiles read **LOADED**, with **PLAN CURRENT** on **04 Plan**. Unlike the Demo show, this one can be edited.

## 3. Change the plan directly (no model needed)

The stage-right guitar amp has been moved to the next socket on the stage box.

1. Click the **04 Plan** tile. The **Channels** table is the input list, one row per input.
2. In the **Gtr 2** row, change **Patch** from `AES50-A 9` to `AES50-A 10`.
3. Press **Save input.csv**.

The message reads *Saved demo-show/input.csv: 1 row(s) changed. The plan is updated: CH 8 patched from AES50-A 10.* The tile still reads **PLAN CURRENT**: the plan changed with the file, without a build.

You can change a channel's patch, name, DCA and mute groups this way, and a bus's sources, width and outputs in the **Busses** table. A cell that can't work on the desk, such as a socket it doesn't have, turns red with the reason, and **Save** waits until it is fixed. Adding a new input is different: it needs a build (step 4).

## 4. Bring the guest singer in (needs a model)

A build is a call to an AI model, so this step needs one set up before `atoo ui` starts ([Setting up an AI provider](ai-provider.md)). Without one, **Rebuild plan** is locked, with the reason beside **Build plan**, and the plan stays exactly as it is: skip this step, leave Guest Vox skipped, and go on to step 5 with the plan from step 3.

The input list already has the guest's microphone, switched off: its row is skipped, so the build leaves it out.

1. Click the **02 Input list** tile. It reads **16 input rows · 1 skipped**.
2. In the **Guest Vox** row, untick **Skip**, then press **Save**.

The tile now reads **17 input rows**, and **04 Plan** reads **STALE**: the plan no longer matches its files.

3. Click the **04 Plan** tile. Under **Options**, choose your desk's model under **Console model**.
4. Press **Rebuild plan**.

A build takes a few minutes. When it is done, the tile reads **PLAN CURRENT**. The starter conventions put playback last, so Guest Vox takes channel 13 and Playback moves along to 14. **Changed since the last build** lists the two strips, and in the **Channels** table they are marked **ADDED** and **MOVED**. Read the **Findings** panel ([Build a show](build-a-show.md#6-read-the-findings)).

## 5. Apply it to the desk

1. **Save the show that is on the desk**: on the desk, press **Library**, then **Snap**, then **Save**; set **Scope** to **All** and press **Save**. This is your way back.
2. In the bar at the top, next to **Console**, press **Change…** and enter your desk's **Address**.
3. Click **Apply**, then **Preview**. Atoo reads the desk and shows how many settings **will change** and how many already match. Nothing is written yet.
4. Tick **Arm**, then press **Write to console**.

Every value written is read back, and anything that didn't land is named. Look at the desk: the channels are named, colored and patched as the plan says. [Apply a plan to the desk](apply-to-desk.md) has each step in full.

## 6. Watch it

1. Click **Watch**, then **Start watching**.
2. Pull a DCA that has channels in it down to the floor. A row appears in the table, and clears when you push the fader back up.
3. Press **Stop**.

[Watch the desk during a show](watch-a-show.md) explains what Watch checks, and how to add your own watch conditions.

## 7. Undo, and put the desk back

On **Apply**, press **Preview undo**, then tick **Arm** and press **Undo newest write**: the desk goes back to how it was before your write ([Undoing a write](undo.md)). Then load the show you saved on the desk.

## Next

[Patch a show](patch-a-show.md): make a change to a show that is already on the desk, typed in plain English.
