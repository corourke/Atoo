# What a full apply changes on the desk

A full `atoo apply` makes the desk the plan, so nothing from last
night's show is left behind to surprise you. That means it writes more
than the values your plan lists: it resets the rest of the desk, unpatches
the strips it does not build, and sets a few switches the plan implies.
This page lists each of them, so none is a surprise either.

Only a full apply (or the browser's **Apply**, which runs it) does any of
this. `patch`, `amend` and `undo` touch only what their change owns.
Every write below is read back and journalled with the value the desk
held, so `atoo undo` reverses it with the rest of the apply.

## First, the desk is reset to its initialized state

You do not have to press Initialize on the desk; Atoo does the
equivalent itself. It reads the whole desk, compares every setting with
an **initialized capture** of that model (a show file saved from a
freshly initialized desk, shipped with Atoo), and writes back the
initialized value wherever the desk differs. Then it writes the plan.

A setting the plan writes itself is not reset first: it is written once,
as the plan's value. Some settings are never reset, because they are not
part of a show:

| Left alone | Why |
|---|---|
| The desk's system nodes (`$syscfg`, `$globals`, `$ctl`, and every read-only `$` status value) | IP address, network settings, clock, console name. A write here could cut Atoo's own connection or the desk's audio clock. |
| Expansion cards (`/cards`) | Which card is fitted and how it is clocked. |
| Meter and RTA display (`/cfg/mtr`, `/cfg/rta`) | What the screen shows, not what the desk does. |
| Monitor and solo listening (`/cfg/mon`, `/cfg/solo`) | Your headphones and monitor speakers, set for you and the room. |

One INFO line counts what was reset, by area. This is a preview of a
23-channel plan on a WING Compact that had had another show on it:

```
INFO reset to initialized (WING Compact capture) before the plan's writes: 128 setting(s) would change -- 97 channel, 24 I/O, 6 bus, 1 DCA; 18,048 already initialized; left alone: 2,762 the plan sets itself, 84 on the skip-list (monitor/solo listening), 56 under a selector the plan sets to another model, 26 on the skip-list (meter/RTA display), 12 on the skip-list (expansion cards), 4 a mono bus's width (the desk holds it at 0), 2 not settable (no address the desk takes); reading the desk took 0.1s (1,990 requests); writing would take about 5.2s at the rate measured on a WING Compact
```

On a real Compact the read took about half a minute, one request at a
time; reads now keep several requests in flight, which should make it
shorter. A desk far from
initialized can need a few thousand writes, at about 40 ms each.

- **`--no-init`** skips the reset, for a desk you have initialized by
  hand. The run says so at INFO.
- **The WING Rack has no capture yet.** A full apply to a Rack, or to a
  desk whose model Atoo cannot tell, says so at WARNING and writes
  the plan without the reset. Initialize a Rack by hand first.

## Strips the plan does not build: unpatched from their sources

A WING ships every channel and aux patched to its own local socket. A
full apply **unpatches every channel and aux strip the plan does not
build**: their source goes to `OFF`, across the whole desk (ch 1-40,
aux 1-8). Only the source; the strip's name, fader, mute and everything
else are left as they are.

Without this, a plan that puts the playback on LCL 23-24 would leave
ch 24 on its factory patch, LCL 24, listening to the playback. One INFO
line says which strips:

```
INFO ch 24-40, aux 3-7: not in this plan, unpatched from their sources so none listens to a socket the plan uses
```

## Output sockets the plan does not patch: disconnected

A WING ships with its local outputs already patched (on a Compact, outputs
3-8 carry busses and the Mains), and an earlier show leaves its own patches
behind. A full apply **disconnects every output socket on the desk's own
panel that no bus, Main or Matrix of the plan is patched to**: the
socket's group goes to `OFF`, and nothing else about it is touched. A
socket the plan does patch keeps what the plan wrote, and one that already
reads `OFF` is left as it is. One INFO line says which sockets:

```
INFO output LCL 3-8: no bus or output in this plan is patched there, so each is disconnected rather than left on what the desk came with or an earlier show put there
```

Without it, the audit would call those patches leftovers, and a stereo bus
the plan only feeds into a Main would show as patched on its left side
only. This step covers the desk's own panel. The outputs beyond it (an
AES50 stage box, StageCONNECT, a card, USB) are already disconnected by the
[reset to initialized](#first-the-desk-is-reset-to-its-initialized-state)
above, which sets every output group to its initialized state, so nothing
needs to be told how many sockets each has. With `--no-init`, or on a Rack
(no capture), [`--clean-output-sockets`](applying.md#flags-worth-knowing)
reaches them. [Undo](undo.md) puts each socket back as it was.

## Direct Main routes: every Main is written, OFF included

A WING ships every channel and aux routed straight to **Main 1**, and
bus 9-16 too. So for every strip and bus the plan builds, apply writes
all four direct Main routes: **on** for each Main the plan lists, **off**
for the rest. A drum that should reach the PA only through the Drums
bus, or a monitor bus on bus 9-16, is taken off Main 1 rather than
reaching it directly as well.

A route that is on is written at unity, post-fader, as is a Matrix's
feed: the conventions have no words for a route's own level or tap, and
the report says so once.

## Talkback: the assign follows the plan

Setup -> Audio's talkback assign says which strip the desk's TALK
buttons use, and the desk offers only **ch 40** or **aux 8**. When the
plan builds a talkback strip on one of those (one named or reading as
"Talkback", "Talk", "Talk Mic", "TB" or "T/B"), apply sets the assign to
it:

```
INFO talkback assign (Setup -> Audio) set to AUX8 (was 'OFF'): aux 8 'TALKBACK' is the plan's talkback strip
```

A plan with no talkback strip there sets the assign to `OFF`. A
talkback strip anywhere else cannot be assigned; `verify` warns about it
(`talkback.unassignable`) and apply leaves the strip where the plan put
it.

## Alternate inputs: every strip back on its main input

A channel whose plan states an **alternate input** (see [Writing
conventions](conventions.md#alternate-inputs-virtual-soundcheck)) gets
it written. A channel with no stated alternate keeps whatever the desk
has.

**Every strip apply builds is also switched back to its main input**,
alternate or not. A strip left on its alternate after yesterday's
virtual soundcheck hears the recorder, not the stage. The report counts
them once:

```
  - INFO 19 strip(s) set to their main input (not their alternate) -- a show apply means stage inputs live
```

Apply never writes the desk's global alternate switch, which moves every
strip set to follow it: that is your call at the desk. `atoo audit`
reports it if it is engaged.

## Expansion bays: `CRD` and `MOD`

A WING has two slots for extra inputs and outputs: the rear-panel
**card** (`CRD`: WING-LIVE, Dante, MADI) and an internal AoIP **module**
(`MOD`: Dante or WSG). Either can be empty, and a desk leaves the
factory with nothing in the module slot.

The desk does not tell you. It accepts a patch into an empty bay and
reads it back unchanged, so the journal says `match` and the channel is
silent. So apply asks the desk what is fitted before it writes anything,
and stops if the plan uses an empty bay:

```
192.0.2.16 reports NOTHING in the MOD bay (AoIP module: Dante/WSG), and this plan uses it 1 time(s):
  - channel 'Kick' from MOD 1

The console would accept these patches and read them back unchanged -- it does not refuse a patch to an empty bay -- so nothing after this point would tell you the channels are silent. Fit the card or module, or repatch these to a group this desk has.
```

It exits `2` and nothing is written. `--skip-verify` does not turn this
off. Only the desk answering `NONE` stops the run: a bay that does not
answer, or names a card Atoo does not know, counts as fitted. An
empty bay the plan does not use is not a problem.

Offline, `atoo verify` cannot know what is in a slot, so it warns
instead (`patch.expansion-bay-not-checked`).

## Stage boxes: a socket past the end of the box

An AES50 port (`A`, `B`, `C`) lists 48 sockets whatever is plugged into
it, so `A 17` on an S16 (16 inputs, 8 outputs) is accepted, written and
read back by the desk — and the mic on it is heard by nobody. Apply asks
the desk what is on each port the plan uses (`/$stat/A/dev` reads `S16`)
and stops if the plan patches a socket past the end of that box:

```
This plan patches 1 socket(s) that do not exist on the stage box 192.0.2.16 reports:
  - A 17 (input) -- channel 'Mic 2'; the S16 on AES50-A has 16 inputs, so A 17 does not exist
```

It exits `2` and nothing is written; `--skip-verify` does not turn it
off. A box Atoo has no size recorded for (only the S16's is) is reported
with a WARNING and its sockets are not checked. A plan that patches no
AES50 socket never asks. [Patch](patch.md) holds a change to the same
rule.

## Names go on the source socket

The desk's **Link Customization to Source** switch is on by default, and
while it is on a strip shows the name, colour and icon of the socket it
is patched to, not its own. So apply writes the name, colour and icon to
the **source socket**, which is where your input list put them. Where
one socket feeds more than one strip, those strips are unlinked and
carry their own names.

## A selector is written before the values it governs

Some settings change what other settings mean. A delay is in metres or
feet depending on the strip's delay mode; a compressor's threshold means
something different under each model. So on each strip apply writes the
**selectors first**, then the **values**, then the **on-switches**.

When the run changes a selector, every value it governs is written and
read back after it, even if the desk already held the plan's number:
under the old selector that number meant something else. The report says
how many at INFO, and the preview counts them the same way.

| selector | governs, on the same strip |
|---|---|
| `in/set/dlymode` | `in/set/dly` only |
| `dyn/mdl` | every `dyn/*` value |
| `gate/mdl` | every `gate/*` value |
| `eq/mdl`, `eq/leq`, `eq/heq` | every `eq/*` value |
| `flt/mdl` | every `flt/*` value |
| `gatesc/type`, `dynxo/type`, `dynsc/type` | every value in that node |

## See also

- [Applying a plan](applying.md): the command, reading the result, flags
- [Using channel presets](presets.md#what-apply-does-with-them): how a
  preset's values are written
- [Undoing a write](undo.md)
