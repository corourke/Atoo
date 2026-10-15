# Try the Demo show

Five minutes, no desk, no API key: see a whole show built, checked and
watched before you write a file of your own.

The Demo show is a five-piece band with backing tracks on a simulated
WING Compact: drums (kick, snare, two toms, stereo overheads), a bass
DI, two guitar amps, a stereo keyboard, a lead and two backing vocals on
a stage box over AES50, and a stereo playback laptop on the desk's own
inputs. Three mono wedges and a stereo in-ear mix, five DCAs, three mute
groups. It is read-only: nothing you click can save, build or write
anything. `atoo init --demo` makes a copy of your own
([below](#see-the-gate-refuse-a-plan)).

It is built from the **starter conventions**, the house style
`atoo init` gives you, so what you see here is what your own first
build looks like.

## Open it

1. Start the browser UI ([installing](install.md) if you have not):

   ```bash
   atoo ui
   ```

2. With no show open, the line under the bar reads **No show open.**
   Press **Try the Demo show**.

   Or, at any time: next to **Console** in the bar, press **Change…**,
   choose **Demo**, then press **Use this console**.

A box opens, once, saying what the Demo is: what works in it, what is
switched off, and how to leave it. Press **Got it**. The bar now reads
**Demo show**, **READ-ONLY**, **Demo · what's this?** and **Demo**;
**Demo · what's this?** opens the box again.

![The Demo show's box: what works, what is switched off, and Got it](img/demo-popup.png)

![The bar with the Demo show open](img/demo-bar.png)

## Build: the files and the plan

**Build** is four steps across the top. Click each tile to open it.
Each tile reads a green **LOADED**, with no **Change file** or **New
file**: nothing in the Demo can be saved, and the bar's **READ-ONLY**
says so. The steps show their files as plain text: 01 and 03 as the
text of the file (their **Example** has no Insert button), and 02 as a
table with nothing to type in,
no row handles or buttons, and **Save** and **Discard changes** locked
with *Locked: the Demo show is read-only* beside them. To edit, make a
copy of your own with `atoo init --demo`
([below](#see-the-gate-refuse-a-plan)).

- **01 Conventions**: the house rules, in plain English: stereo pairs,
  monitor widths, colours, a channel preset per source, which DCA and
  mute group each kind of source joins. It is the same file as the
  starter conventions.
- **02 Input list**: **16 input rows · 1 skipped**, one row per thing
  plugged in. The `order` column is the band's own numbering; the guest
  vocal's row has `-` there, so it stays in the file and the build leaves
  it out.
- **03 Instructions**: this show's exceptions to the house rules: who is
  in which wedge, where each monitor output goes, and a **Music** strip
  for walk-in music on Aux 1 that is not on the input list at all. **2 layers** means
  the house file, then these instructions on top.
- **04 Plan**: what the desk will be given. One row per channel with its
  number, socket, phantom power, DCAs and mute groups. Press **▸** on a
  row for its preset, sends, colour and where each value came from.
  **PLAN CURRENT** on the tile means the plan was built from the files as
  they are now.

The **Findings** panel down the right holds everything the checks said
about the plan. It starts with the verdict: **Ready to apply**, with 0
to check, 0 advice from the critic and 6 notes on choices the build
made.

Twelve channels carry a preset from the starter library: Kick takes
**Kick In**, the toms **H Tom** and **Fl Tom**, the three singers
**Vocal**, and so on, and the plan holds each preset's values (▸ on a
row in **04 Plan** shows `Kick In (83 values)`). Playback has no preset:
the conventions say so, because a mixed line from a laptop wants none.

Open **▸ Choices**: **AUX 1 Music is not on the input list** (a strip
built from the instructions is always reported, so you see the one
strip your list does not have; asked for word for word with its socket,
it is a note, not a warning), the skipped guest vocal, the two choices
made for the Vox Verb bus's reverb (which FX engine it goes into, and
switching on an insert its preset was saved bypassed), and what a full
apply does beyond the plan's own strips (it unpatches the strips the
plan does not use, and sets the talkback assign). **▸ Build details**
holds nine more, on how the build read the draft and what it carried
into the plan: the preset values the channels and busses carry, the
reverb loaded and read back, the Music strip, channel numbers, colours,
sends, and what a full apply's reset does.

## Apply: a preview on the simulated desk

Click **Apply**. On a real desk this is the one screen that writes. Its
first step, **What will be written**, names the plan and its **Pre-flight
verify**: **0 errors · 0 warnings**, so the plan could be written as it
stands. Beside it, **7 notes (3 among Choices, 4 among Build details)**
are the pre-flight's own; the Findings panel's counts are the whole
show's, so they hold the build's notes as well.

Press **Preview**. It reads the Demo's simulated WING, a WING Compact
with the show already on it, exactly as it would read a real desk, and
draws the desk as the plan will leave it: **1667 addresses read**, **444
will change**, **1223 already match**, **0 didn't answer**. The 444 are
mostly the channel and bus processing, which the simulated desk does not
hold.

![Apply on the Demo show: the desk drawn as scribble strips after a preview](img/apply-demo-preview.png)

**Write to console** and **Undo newest write** stay locked, drawn
without colour, and each says why beside it, after **Locked:**: writing
is switched off in the Demo show.
**Patch** previews a typed change too, when a model is set up, as for a
build; without one, its box says so and the Demo previews a Full build
only.

## Watch: the show, live

Click **Watch**, then **Start watching**. The simulated desk has faults
that come and go at random, so within a few seconds the table fills:

![Watch on the Demo rig: the Vocals bus clipped, Lead Vox muted and the Band DCA pulled down, three of the show's own conditions firing](img/watch-table.png)

The word over the table says it from across the room: a red **TROUBLE**
while an error stands, a yellow **WARNING** with warnings only, a green
**ALL OK** when the faults have gone. Error rows fill red and warning
rows amber. Rules starting `WATCH:` are the
show's own watch conditions, listed as text under **Watch conditions**
below the table, with **Save** locked since the show is read-only; rules
named by a code such as `R005` are built-in checks. The **This watch**
block, also below the table, reads *Resolved at Start: DCA Band → DCA 2,
BUS Drum IEM → BUS 4, BUS Drums → BUS 5, MAIN PA → MAIN 1, ...*: which
bus, DCA and Main each condition's name was matched to when the watch
started. The show watches Lead Vox muted; the PA (Main 1) muted or below
-40 dB; the Drums, Vocals and Vox Verb busses and the Drum IEM and Vox
Wedge mixes muted, and the three mix and FX busses below -40 dB; and any
DCA muted or below -30 dB, with the Band DCA held above -20 dB. When the
Band DCA goes to the floor, the show's conditions and the built-in
CH002 all catch it: the conditions' rows, with CH002 named under
the first. The house conventions start every channel fader at the floor,
and the plan puts them there, so L002 *Active Strip Fader At Floor*
says nothing about them: Watch checks that rule against the show's plan,
and names only a fader at the floor that the plan put somewhere else,
like the Drums bus when it drops. A row disappears by itself when the fault clears. Now and then a
strip also **clips**: a red **Clipped** row for a channel, bus or Main,
which stays about a minute and counts up if the same strip clips again
([what it says](watch-a-show.md#a-clip)). The Demo simulates those; on a
real desk they come from the console's meters. Press
**Stop** when you have seen enough.

## See the gate refuse a plan

The Demo show is read-only, but a copy is not. `atoo init --demo`
writes one into your Atoo folder, as `demo-show`. Copy that, and
move the stereo keyboard onto an even socket, a patch the desk cannot
make:

```bash
atoo init --demo
cp -r ~/Documents/Atoo/demo-show /tmp/demo-copy
python3 -c "import json; p = json.load(open('/tmp/demo-copy/plan.json')); \
p['channels'][8]['patch']['sockets'] = [10, 11]; json.dump(p, open('/tmp/demo-copy/plan.json', 'w'))"
atoo verify --show /tmp/demo-copy
```

```
1 error(s), 0 warning(s), 4 note(s)

  [error] channels[Keys].patch: A 10+11 cannot be a stereo pair -- the pair starts on 10, an even socket (a pair always starts on an odd one). The console's routing hardware forms a stereo pair only from consecutive [odd, even] sockets, so this patch cannot be made as written  (patch.stereo-pair-not-odd-even)
  ...
BLOCKED: do not apply.
```

`apply` refuses a plan in that state before it contacts a desk.

## The 6pm change

The horn section turns up at six. On a desk with the Demo show on it,
this is the change to type in **Apply → Patch** (or `atoo patch`):

> trumpet, sax and trombone on LCL 21-23, Band DCA

The three horns go onto the next free strips, ch 14 to 16, patched to
the sockets you named, in the Band DCA, each with its starter preset
(Trumpet, A Sax, T Bone). The conventions give the horns a mix bus of
their own, so the change adds a **Horns** bus, compressed by the **Mix
Bus** bus preset, and nothing already on the desk moves.

As [above](#apply-a-preview-on-the-simulated-desk), the Demo's **Patch**
needs a model to compile a typed change. From an Atoo checkout you
can see the review with no model at all: the change is compiled already,
in `docs/user/demo/demo-show/horns.change-set.json`, and the Demo
console's rig stands in for the desk. See [Patching a running
show](patch.md#try-it-with-no-console-and-no-model):

```bash
atoo patch --show starter/demo-show --change-set docs/user/demo/demo-show/horns.change-set.json --state atoo/web/demo_states/before.json
```

For the whole flow on a real desk, see
[Patch a show that is already on the desk](patch-a-show.md).

## Leave the demo

Press **Change…** next to **Console** and choose **Address** to use a
real desk, or open or create a show with **Open…** or **New show…**
next to **Show bundle**.

## Next

- [Testing on your desk](testing-on-your-desk.md): the same, on your own
  WING.
- [Why Atoo?](why.md), if you are still deciding.
