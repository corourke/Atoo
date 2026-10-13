# Using channel presets

Your own `.chn` exports, applied as ordinary parameter writes -- and your `.bus` exports, which also load an FX bus's effect.

Run everything on this page from the top of an Atoo checkout.

## These are Atoo's presets, not the console's

A WING has no remote "recall this preset" command at all. Presets are
recallable only as Scenes inside an open Show, and Scene tags can only be
assigned by hand on the console screen — so nothing here touches your
desk's scenes, tags or its own preset library.

Instead Atoo keeps its **own** directory of `.chn` files, copies a
preset's processing values **into the plan** when it builds it, and
writes them like every other value, each one read back. Nothing is
uploaded and nothing is left behind on the desk (confirmed on a WING
Compact).

## The library

A directory of `.chn` files. It is the reusable piece, like your
[conventions](conventions.md), so it lives **outside** any
[show bundle](show-bundles.md) — one library, every show.

Name it with `--presets DIR` on `build`, `verify`, `apply` or
`presets`, or once as `[presets] default` in `~/.atoo.config`
([The config file](configuration.md#the-config-file)):

```bash
atoo build  --presets ~/atoo-presets ...
atoo verify --presets ~/atoo-presets ...
atoo apply  --presets ~/atoo-presets ...
```

`--presets` wins over the config file. `atoo patch` needs neither
as a rule: a change takes its new strips' presets from the library the
plan on the desk records (the one the show was built with, or the
packaged starter presets when its files match them), and only then from
`[presets] default`; an INFO line names the library and why
([Patching a running show](patch.md#try-it-with-no-console-and-no-model)).

With no library named at all, a plan that names a preset gets one
warning for the whole plan rather than one per strip:

```bash
atoo verify --plan tests/fixtures/preset-test.plan.json
```

```
  [warning] plan: 6 channel(s) name a preset (KEYS, Kick (In), Perc, Snare Top, kick-in, vocal) but no preset library is configured and the plan carries none of their values, so those strips will be built without the processing those presets carry  (preset.no-library)
```

## The starter set

Atoo ships a starter library in `starter/presets/`: twenty channel
presets made on a real WING, one per common source, and
three bus presets: one for a mix bus, two for FX busses. `atoo init` copies it into your Atoo
folder as your library, the [starter conventions](conventions.md) name
them by source, and the Demo show is built with them. This page uses it.

| File | Preset name | For |
|---|---|---|
| `Kick.chn` | **Kick In** | kick, inside or boundary mic |
| `Snare.chn` | Snare | snare |
| `HiHat.chn` | HiHat | hi-hat |
| `H Tom.chn`, `M Tom.chn`, `Fl Tom.chn` | H Tom, M Tom, Fl Tom | high, mid and floor toms |
| `OH.chn` | OH | overheads |
| `Perc.chn` | Perc | percussion |
| `Bass.chn` | Bass | bass |
| `E Gtr.chn`, `Ac Gtr.chn` | E Gtr, Ac Gtr | electric and acoustic guitar |
| `Keys.chn`, `Piano.chn` | Keys, Piano | keyboards, piano |
| `Trumpet.chn`, `T Bone.chn`, `A Sax.chn`, `T Sax.chn`, `B Sax.chn` | Trumpet, T Bone, A Sax, T Sax, B Sax | horns |
| `Vocal.chn` | Vocal | lead and backing vocals |
| `Speech.chn` | Speech | a talker: MC, podium |
| `Mix Bus.bus` | Mix Bus | mix busses (Drums, Horns, Vocals): a compressor and a flat EQ, no effect |
| `FX Vox Verb.bus`, `FX Snare Verb.bus` | Vox Verb, Snare Verb | FX busses: a V-REV and a gated reverb, each with its bus's EQ and compressor |

They are starting points, and they are meant to be replaced: export your
own over them, keep the ones you like, delete the rest. To add one, save
the channel preset on the desk (or in WING-EDIT) under the name your
conventions use, copy the `.chn` file into your library folder, and run
`atoo presets` to check it answers to that name.

The `.bus` files are covered on [Bus presets: mix and FX
busses](bus-presets.md): on a mix bus a bus preset sets only EQ and
compressor; on an FX bus it also loads the effect into an FX engine and
inserts it.

## A preset's name is inside the file, not on it

This catches everybody once. The name Atoo matches on is the
preset's own label, saved when it was exported. The filename is only a
fallback for a file that has none. In the starter set every file is
named for its preset except one: `Kick.chn` holds the preset **Kick In**,
so a plan asks for `Kick In`, and asking for "Kick" would not find it.

**The preset's name and the channel's name are separate, too.** A channel
called `Snare` can use a preset called `Drums Snare`; the strip keeps
the plan's name. A preset never sets a channel's name, colour or icon
(see [What a preset may carry](#what-a-preset-may-carry)). Name your
presets however you like on the desk, and the same way in your
conventions.

### Ask the library what it is called

`atoo presets` opens every file and tells you:

```
$ atoo presets --presets starter/presets
20 preset(s) in starter/presets

name     params  file
-------  ------  -----------
A Sax        83  A Sax.chn
Ac Gtr       83  Ac Gtr.chn
B Sax        83  B Sax.chn
Bass         83  Bass.chn
E Gtr        83  E Gtr.chn
Fl Tom       83  Fl Tom.chn
H Tom        83  H Tom.chn
HiHat        83  HiHat.chn
Keys         83  Keys.chn
Kick In      83  Kick.chn
M Tom        83  M Tom.chn
OH           83  OH.chn
Perc         83  Perc.chn
Piano        83  Piano.chn
Snare        83  Snare.chn
Speech       80  Speech.chn
T Bone       83  T Bone.chn
T Sax        83  T Sax.chn
Trumpet      83  Trumpet.chn
Vocal        80  Vocal.chn

3 bus preset(s)

bus preset  effect                                            file
----------  ------------------------------------------------  -----------------
Mix Bus     no effect                                         Mix Bus.bus
Snare Verb  GATED (pre-insert, saved on FX8)                  FX Snare Verb.bus
Vox Verb    V-REV (pre-insert, saved on FX5, saved bypassed)  FX Vox Verb.bus
```

`params` is how many parameter leaves that preset carries: most of a
strip's processing, which is why they all read 80 or 83. The bus presets
follow, each with the effect it inserts, the engine it was saved from,
and whether it was saved bypassed. With `[presets] default` configured,
plain `atoo presets` is enough.

**It also reports two things nothing else tells you until a show
does.** A preset carrying a field this tool does not recognise, or a
sidechain keyed off another channel, otherwise warns only when a plan
names it, on the day you use it. (This block comes from a deliberately
broken library; the starter set has none.)

```
warning: Keyed Kick (keyed.chn) --
  gatesc.src references channel 'CH.12' instead of SELF -- not portable across channels/shows, dropped rather than silently rewiring a sidechain
```

And two files claiming one name never warns during a build, because the
newest simply wins. Here, a library with the starter's `Keys.chn` saved
twice:

```bash
mkdir /tmp/dup-presets
cp starter/presets/Keys.chn /tmp/dup-presets/Keys.chn
sleep 1   # the newer copy is the one used
cp starter/presets/Keys.chn /tmp/dup-presets/keys-2025.chn
```

```
$ atoo presets --presets /tmp/dup-presets
2 preset(s) in /tmp/dup-presets

name  params  file
----  ------  -------------
Keys      83  Keys.chn
Keys      83  keys-2025.chn

warning: 2 files share the name 'Keys': Keys.chn, keys-2025.chn. The newest wins when a plan asks for it.
```

A plan asking for `Keys` gets whichever was exported last, and the other
cannot be asked for by name until it is re-saved under a name of its own.

Neither stops anything, so `atoo presets` exits `0` either way. It
reads no console and writes nothing.

## Naming one, and how forgiving the match is

Name the preset in your conventions, in the sentence you would say out
loud:

```
- Kick uses the "Kick In" preset.
- Lead Vox uses the "Vocal" preset.
```

Matching is **case-insensitive**, and `-`, `_` and runs of whitespace all
count as the same thing: `Kick In`, `kick_in` and `KICK-IN` are one name.

Or name it in the input list's optional `preset` column, matched the
same way; **the input list wins** over the conventions and instructions
([The `preset` column](input-lists.md#the-preset-column)). The build
says so at INFO (`reply.preset-from-input-list`) when it replaces a
different preset. In the browser, Build step 02's Preset column offers
this library's names.

Matching stops there on purpose. Other punctuation is **not** stripped, because
guessing further starts merging presets you meant to keep apart.
`tests/fixtures/preset-test.plan.json` names six presets, each a deliberate
case. It is a hand-made plan that has never been through `build`, so it
names its presets without carrying their values yet -- which verify says,
strip by strip:

```bash
atoo verify --plan tests/fixtures/preset-test.plan.json --presets starter/presets
```

```
0 error(s), 7 warning(s), 8 note(s)

  [warning] channels[Kick]: names the preset 'kick-in', which the library has (Kick.chn), but the plan carries none of its values -- it was built before presets were expanded into the plan, or without a library -- so nothing from it will be written  (preset.not-expanded)
  [warning] channels[Snare]: names the preset 'Snare Top', which is not in the library at starter/presets (20 presets) -- that strip will be built without it. Closest in the library: Snare, M Tom, H Tom, Fl Tom  (preset.unknown)
  [warning] channels[HH]: names the preset 'Kick (In)', which is not in the library at starter/presets (20 presets) -- that strip will be built without it. Closest in the library: Kick In  (preset.unknown)
  [warning] channels[Keys]: names the preset 'KEYS', which the library has (Keys.chn), but the plan carries none of its values -- it was built before presets were expanded into the plan, or without a library -- so nothing from it will be written  (preset.not-expanded)
  [warning] channels[T.Sax SM57]: names the preset 'Perc', which the library has (Perc.chn), but the plan carries none of its values -- it was built before presets were expanded into the plan, or without a library -- so nothing from it will be written  (preset.not-expanded)
  [warning] channels[MLD VOX]: names the preset 'vocal', which the library has (Vocal.chn), but the plan carries none of its values -- it was built before presets were expanded into the plan, or without a library -- so nothing from it will be written  (preset.not-expanded)
  [warning] plan: no input list was supplied, so nothing checked that every input became a channel, that no channel was invented, or that phantom power is safe for the microphones in use -- pass the input list to check those  (reconcile.not-checked)

  [info] busses[Drums, Drums Comp, Vocals, Horns, VOX Reverb, VOX Delay, Snare Verb, INST Reverb] (8 busses): width set to stereo -- the conventions did not state it; decided by Atoo's fallback rule: no physical output socket depends on its width, so it keeps the WING's factory width, stereo  (inferred.bus-width)

APPLICABLE: warnings only.
```

(Each `preset.unknown` line names up to five closest names in the
library: `Kick (In)` finds `Kick In`. The `[info]` note is not about
presets: this fixture plan leaves its bus widths unstated, so verify
reports the width it will write, one line for all eight. See
[Writing conventions](conventions.md#the-one-rule-worth-internalising-state-it-or-it-is-decided-and-said).)

Read the six presets as a table:

| Named in the plan | Result |
|---|---|
| `kick-in` | matches **Kick In** -- case, and `-` for a space. Not expanded yet |
| `KEYS` | matches **Keys** -- case only. Not expanded yet |
| `vocal` | matches **Vocal**. Not expanded yet |
| `Perc` | matches **Perc** (on a saxophone channel -- nothing checks that a preset *suits* a strip; that is your call). Not expanded yet |
| `Snare Top` | **not in the library** -- that strip is built without it |
| `Kick (In)` | **not in the library** -- the parentheses are not punctuation to be ignored |

## How a preset gets into the plan

**`build` puts it there.** When a plan names a preset, `build` opens the
`.chn`, takes its processing values (the allow-list below), compressor
and gate included, and writes them into the plan under that channel's
`processing.preset_values`. The plan then says exactly what `apply`
will write; `apply` never opens a `.chn`.

A plan that was built before this, or built with no library, names a
preset and carries none of its values. `atoo presets --expand` does
what `build` does to it, without a model call:

```bash
atoo presets --presets starter/presets --expand tests/fixtures/preset-test.plan.json --out /tmp/preset-test.expanded.json
```

```
Presets -- 5 note(s):

NOTE     plan: 4 channel(s) carry a preset's values, resolved from
         starter/presets and written at the processing stage: ch 1 Kick In
         (81), ch 9 Keys (81), ch 10 Perc (81), ch 14 Vocal (78)
         (preset.expanded)

NOTE     ch 1, 9-10, 14 (4 channels): the plan's own processing wins at 1
         address(es) the preset … also sets -- flt/lcf preset
         35.05742264..121.7320709 -> plan 40.0..120.0
         (preset.overridden)
Wrote /tmp/preset-test.expanded.json: 4 channel(s) carry preset values (321 in all), resolved from starter/presets. Nothing has been written to any console -- `atoo apply` does that.
```

Without `--out` it rewrites the plan in place, and only when something
in it changed; run it again and it says `already up to date`. It reads no
console and writes nothing to one.

Verify, on the expanded plan, has one line for all four strips instead
of four warnings:

```bash
atoo verify --plan /tmp/preset-test.expanded.json --presets starter/presets
```

```
0 error(s), 3 warning(s), 9 note(s)

  [warning] channels[Snare]: names the preset 'Snare Top', which is not in the library at starter/presets (20 presets) -- that strip will be built without it. Closest in the library: Snare, M Tom, H Tom, Fl Tom  (preset.unknown)
  [warning] channels[HH]: names the preset 'Kick (In)', which is not in the library at starter/presets (20 presets) -- that strip will be built without it. Closest in the library: Kick In  (preset.unknown)
  [warning] plan: no input list was supplied, so nothing checked that every input became a channel, that no channel was invented, or that phantom power is safe for the microphones in use -- pass the input list to check those  (reconcile.not-checked)

  [info] busses[Drums, Drums Comp, Vocals, Horns, VOX Reverb, VOX Delay, Snare Verb, INST Reverb] (8 busses): width set to stereo -- the conventions did not state it; decided by Atoo's fallback rule: no physical output socket depends on its width, so it keeps the WING's factory width, stereo  (inferred.bus-width)
  [info] plan: 4 channel(s) carry a preset's values, written at the processing stage and read back like every other write: ch 1 Kick In (81), ch 9 Keys (81), ch 10 Perc (81), ch 14 Vocal (78)  (preset.expanded)

APPLICABLE: warnings only.
```

## Your plan wins over the preset

If a channel names a preset **and** states a value of its own at the same
address -- its own high-pass, an EQ band -- the plan's value is the one
written, and **only** that one: the preset's value for that address is
moved to `overridden` and never sent. Each override is a note
(`preset.overridden`, above) naming the address and both values.

A preset saved with its sends or main routing switched on cannot reroute
your show either: routing is not on the allow-list at all (next
section).

## What a preset may carry

A `.chn` file holds far more than a sound: the physical patch, fader,
mute, pan, bus routing, DCA and mute-group membership, and the channel's
own name, colour and icon are all in there. Applying all of it would
repatch inputs, wreck routing and rename channels from a file that was
only ever meant to carry a drum sound.

So Atoo applies **processing only**, from an explicit allow-list:

| Applied | Never applied |
|---|---|
| filter / high-pass | the input patch and preamp gain |
| gate, and its sidechain settings | fader, mute, pan |
| dynamics, and its sidechain settings | bus sends and main routing |
| channel EQ and PreSend EQ | DCA and mute-group membership |
| input delay (delay, mode, on/off) | name, colour, icon |

The allow-list is checked three times -- when `build` expands a preset,
when `verify` reads the plan, and when `apply` writes it -- so a plan
edited by hand cannot slip a send or a fader into `preset_values`: `apply`
refuses it by name and `verify` warns first (`preset.leaf-not-written`).

Worth knowing:

- **A sidechain pointed at another channel is dropped, with a warning.** A
  preset captured with its gate keyed off "CH.12" would silently key off
  whatever occupies channel 12 in *your* show. `SELF` is applied; a
  channel reference is not.
- **Anything in the file that is on neither list becomes a named warning**
  on that preset, rather than being quietly applied or quietly skipped.
- **An aux strip gets only what an aux strip has.** It has no filter,
  gate or PreSend EQ node, so those values are left out of the plan for
  an aux channel, with a note saying how many and which.
- **An aux strip gets only the choices an aux strip offers.** A `.chn` is
  a channel's file, and some of a channel's list choices are not on an
  aux's list. Every preset in the starter library sets its dynamics
  sidechain tap to `IN`, a channel's tap; an aux's taps are `BUS`, `DYN`,
  `PFL`, `AFL`, `EQ` and `INS2`, and the desk turns an `IN` written to an
  aux into `BUS`. So `build` carries `IN` -- and a channel's `FILT`,
  since an aux has no filter -- onto an aux as `BUS`, the same point in
  the aux's signal, and says so at INFO (`preset.value-not-on-strip`).
  A choice with no equivalent on an aux (a dynamics model only a channel
  has, say) is left out, with the values set for it, and the note names
  each.

## What verify says about presets

| Finding | Severity | When |
|---|---|---|
| `preset.expanded` | info | the plan carries preset values -- one line for the whole plan, listing each strip and how many values |
| `preset.overridden` | info | the plan's own processing wins at an address the preset also set |
| `preset.library-changed` | info | the library's copy of a preset changed since the plan was built. The plan's values are still what is written; rebuild or `--expand` to take the new ones |
| `preset.not-expanded` | warning | a named preset the library has, but the plan carries none of its values -- nothing from it is written |
| `preset.no-library` | warning | the plan names presets it does not carry, and no library is configured -- one finding for the whole plan |
| `preset.unknown` | warning | a named preset is not in the library; the message names up to five presets the library has whose names are closest |
| `preset.ambiguous` | warning | two files in the library carry the same name |
| `preset.unreadable-library` | warning | the library path cannot be read as a directory of presets |
| `preset.stale-expansion` | warning | the values in the plan came from a different preset than the one it now names (a hand edit) |
| `preset.leaf-not-written` | warning | a value in `preset_values` that `apply` will refuse: off the allow-list, no known type, a node the strip does not have, or a list choice the strip does not offer |
| `preset.contradicts-input-list` | warning | with `--input`: a channel's preset is not the one its input-list row states ([The `preset` column](input-lists.md#the-preset-column)) |
| `preset.input-list-pair-disagrees` | warning | with `--input`: a stereo pair's two rows name different presets; the first row's is the channel's |

None of them is an error, and none blocks an apply or a build: a strip
whose preset cannot be resolved is built without that preset's
processing, and you are told which strip and why. A plan that carries
its values is self-contained, so `preset.no-library` never fires for it.

Two files sharing a name is decided rather than refused: the newest
wins, and the message names the one it ignored. On the two-file library
from [Ask the library what it is called](#ask-the-library-what-it-is-called):

```bash
atoo verify --plan tests/fixtures/preset-test.plan.json --presets /tmp/dup-presets
```

The two lines about `KEYS` (the warnings for the five presets this
library does not have are left out):

```
  [warning] channels[Keys]: 2 presets in /tmp/dup-presets are named 'KEYS' -- using the newest, /tmp/dup-presets/keys-2025.chn, ignoring /tmp/dup-presets/Keys.chn  (preset.ambiguous)
  [warning] channels[Keys]: names the preset 'KEYS', which the library has (keys-2025.chn), but the plan carries none of its values -- it was built before presets were expanded into the plan, or without a library -- so nothing from it will be written  (preset.not-expanded)
```

## What apply does with them

`apply` writes every value in `preset_values` at the processing stage --
after the patch, alongside the high-pass and EQ -- reads each one back,
and journals it with the value it replaced, exactly like every other
write. So a preset write is in the preview, is proved or reported as a
mismatch, and comes off the desk with `atoo undo`.

On each strip the compressor and gate models and the delay mode go
before the values they govern ([A selector is written before the values
it governs](what-apply-changes.md#a-selector-is-written-before-the-values-it-governs)).
A strip returned to free by `patch` or `amend` has its gate and
compressor put back to the factory reading too.

## See also

- [Writing conventions](conventions.md#presets-by-name-never-by-value) --
  naming a preset from the file that decides who gets one
- [Bus presets: mix and FX busses](bus-presets.md)
- [Applying a plan](applying.md) -- what `apply` does write
