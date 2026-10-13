---
title: "Writing conventions"
description: "Your habits, in plain English, written down once and reused for every show. This is the file that makes the tool worth using."
sidebar: 
  order: 3
---

<!-- Generated from docs/user/conventions.md by tools/docs_to_starlight.py in the development repository. Edit it there. -->
Your habits, in plain English, written down once and reused for every
show. This is the file that makes the tool worth using.

The [input list](/build/input-lists/) says what is plugged in tonight. The
conventions file says what you always do with it: what order you patch
in, what goes in a DCA, where the monitor busses go, how loud a send
starts. Two files, and everything else Atoo produces comes from
them.

## Start from the starter

`atoo init` puts a starter conventions file in your Atoo
folder (`~/Documents/Atoo/conventions.md`; in a checkout,
`starter/conventions.md`). It is one engineer's band/club house style, a
page long, with a comment on the lines worth explaining, and it states
the choices a build would otherwise have to make for you: which inputs
pair into stereo, wedge mixes mono and in-ears stereo, a colour per
category, a channel preset per source, which DCA and mute group each
kind of source joins. The [Demo show](/getting-started/demo/) is built from it, so open
the Demo to see what it produces. Make it yours: keep the lines you
share, change the rest, and rename its presets to the ones in your own
library.

## It is prose, not a format

There is no grammar to learn. A model reads the file with the input
list in front of it, and deterministic code then checks what it
produced. Write the way you would brief a competent
engineer who has never worked with you:

> - Channel order: drums, then bass, guitars, keys, horns, vocals, and
>   playback last.
> - Drum kit order: kick, snare, hi hat, toms from high to low, then overheads.
> - Start every channel's head-amp gain at 20dB and its trim at 0dB.

Those are three lines from the starter.

**It is yours, not the show's.** You carry it from gig to gig, so it
lives **outside** any show bundle
([why](/build/show-bundles/#two-files-that-do-not-go-in-the-bundle)). What is
specific to tonight goes in that show's `instructions.md`
([below](#instructionsmd-layers-over-it)).

**Name it something you can find.** `atoo-rules-<description>.md` is
the suggested shape (`atoo-rules-house.md`,
`atoo-rules-festival.md`). Never a leading dot: a hidden file is one
nobody reviews.

## A shape that works

Headings are for you and for whoever reads the file next, not for the
parser. This order matches how a show gets built, which is why the
shipped example uses it:

| Section | What you put in it |
|---|---|
| Sources / Inputs | patch order, colour coding, what counts as a category |
| Channel assignments | which strip things land on, what becomes a stereo pair, what goes on an aux |
| Channel processing | high-pass by category, presets by name, starting fader and mute |
| Busses | monitors, mixes, FX — membership, send mode, send level, width, where each one goes |
| DCAs | one bullet per DCA, by category |
| Mute groups | the same, for mute groups |
| Outputs | Main, and any matrix fed from it, with their physical sockets |
| Watch | what should alert you during the show, if you use `atoo watch` |

The starter calls them "Inputs", "Channels", "Processing", "Busses",
"DCAs", "Mute Groups", "Outputs" and "Watch", and builds correctly. Use
the words you think in. Headings are optional on the browser page too:
Build's step 01 edits the file as one text, and offers an **Example**
with the usual headings to copy from ([Build a
show](/build/build-a-show/#2-check-your-house-rules-01-conventions)).

## Notes the build ignores

A note to yourself — a reminder, a reason, a rule switched off for
now — goes in an HTML comment, `<!-- ... -->`, on one line or across
several:

```markdown
## Outputs
- Main should be the full mix. Send to Matrix 1. <!-- We will EQ this so it sounds good for a recording. -->
- Matrix 1 takes its feed from Main. Patch output to internal XLRs 7 and 8.

<!--
## DCAs
- Horns: all horns-category channels   (no horns this season)
-->
```

The build strips every comment from your conventions file and from a
show's `instructions.md` before a model sees either, so nothing inside
one is ever built. A `## ` heading inside a comment is commented out, too:
the `## DCAs` above is not a heading. The browser page's editors show
comments as you wrote them, and **View house file** shows them dimmed.

A `<!--` inside a code block or a `` `code span` `` is ordinary text,
not a comment.

**An unfinished comment does not swallow the rest of the file.** If a
`<!--` never closes, the build does not throw away every rule after it.
It reads the rest of the file as written and warns you, naming the file
and line:

```
Comments in the conventions -- 1 note(s):

WARNING  house.md line 3: A comment opened here with <!-- never closes with
         -->. Rather than drop everything after it, the build reads the rest
         of the file as written, the unfinished comment included -- so a note
         there will be read as if it were a rule.
         Your line: - Matrix 1 takes its feed from Main. <!-- We will EQ to
         correct for the room.
         Fix: close the comment with -->, or delete the <!--
         (conventions.unclosed-comment)
```

The same warning appears in the browser's Findings panel. A stray `-->`
with no `<!--` is read as written (it might be an arrow) and noted at
INFO.

**Why not parentheses?** They often carry real rules: *"(but not
drums)"* leaves channels out of a reverb. The model acts on a
parenthesis that states a setting and treats one that gives a reason as
background, but if a line must never be read at all, a comment is the
only sure way.

## The one rule worth internalising: state it, or it is decided and said

A value your conventions never mention goes one of two ways, and which
way depends on whether the desk can work without it.

- **Most values are left alone.** A high-pass, an EQ band, a fader, a
  colour, a preset: unstated means the plan leaves the field empty and
  the desk keeps whatever it had. A board with last week's filter still
  passes audio, so nothing is filled in with something plausible.
- **Four values are decided, and every decision is announced.** A bus's
  mono/stereo width, a send's pre/post, a mix or FX bus's route to the
  Main, and whether two sources become a stereo pair all decide how the
  show is *patched*, and a patch left to whatever the desk had may not
  work. So the build makes the reasonable choice — from your conventions
  first, then from what the bus is for and what things are called — and
  says so in an [INFO note](/build/reading-findings/#info-a-choice-made-and-said)
  naming what it chose and why.

A **physical socket** is never decided that way: a socket is where a
cable is, not a preference, so it is never guessed. An output whose patch
nobody stated is still set up -- its feed, level and processing -- but
routed to no socket, at WARNING (`output.no-patch`). That is right for a
Matrix used inside the desk, as the phones or monitor source; if the
output should reach a jack, state its patch.

For example, a conventions file that names six monitor busses but never
says how wide they are still gives an applicable plan. `verify` adds a
note for each width it decided:

```
  [info] busses[MON1]: width set to mono -- the conventions did not state it; decided by Atoo's fallback rule: it feeds a dedicated output on a single socket (A 21), and one jack carries one signal  (inferred.bus-width)
```

A wedge on one socket is mono; an in-ear or a mix bus is stereo. If that
is wrong for your show you will hear it at soundcheck, and one sentence
settles it for every show after: *"these will all be MONO busses."* The
plan, the Findings panel, `verify`, `apply` and `amend` all agree on the
value that was chosen.

The same principle, in the places it usually bites:

- **Send mode is decided, and said.** `pre-fader` or `post-fader` is
  yours to state, and should be. Where it is not, a send into a bus that
  only feeds a physical output (a monitor mix) is made pre-fader, and
  anything else post-fader — with an `inferred.send-mode` note naming the
  bus and the channels.
- **Send level defaults to unity, and says so.** A send your conventions
  list with no level is set to unity (0 dB), with an
  `inferred.send-level` note naming the bus and the channels. It is never
  left empty, because the desk would then keep its own send level, and
  a fresh desk's is -144: the send would be on and silent. Want a send
  to start lower? Say so ("sends to INST Reverb all the way down",
  "Snare Verb at -10dB").
- **A rule that matches nothing is reported.** Name a channel in a DCA
  that no input list row supplies and you get a warning, not silence —
  that is how a hallucinated channel is caught.

The words Atoo understands for a level ("all the way down",
"unity", "-10dB") are listed in the
[conventions reference](/build/conventions-reference/#levels-in-the-words-you-would-say-them).

## Specific beats general

A category rule is a **default**, not a claim about every channel in it:

```
- I always want a highpass at 40 Hz on anything in the drums category.
- Kick gets a high-pass at 60Hz.
```

The named channel wins over its category, and a category wins over a
statement about everything. This is the normal shape of a real drum kit's
conventions rather than an edge case — one real WING show's "Drums" DCA
spanned high-passes from 32 Hz to 1500 Hz.

## Stereo pairs are a conventions decision

The input list cannot say whether two sources are a pair — see
[why](/build/input-lists/#two-columns-you-may-not-have). Your conventions
decide it, and the exception usually matters more than the rule:

```
- If you see Left/Right designations in the overhead (OH) names, do NOT
  patch as a stereo pair, keep as separate mono channels -- the reason is
  they get separate processing.
- For instruments other than overheads, if two sequential inputs are
  marked as stereo pair (L/R, Left/Right), patch as one stereo channel.
```

The exception wins over the naming rule. What a pair can be *patched to*
is the desk's business, not yours — two adjacent sockets, odd first — and
that constraint lives on the [input list page](/build/input-lists/#a-stereo-pair-needs-two-adjacent-sockets-odd-first),
because the cabling is where it can still be fixed.

## Alternate inputs: virtual soundcheck

Every WING strip has **two** input patches, a main one and an alternate,
and a switch between them. The alternate is how virtual soundcheck
works: WING LIVE records the show to the card, and the next day each
channel's alternate plays its own track back with the stage silent. A
card track is addressed like any socket, `CRD 1` to `CRD 64`.

A plan carries an alternate **only when you state one**. Say it in the
conventions, or in `instructions.md` for one show, in the words you
would use:

```
- Virtual soundcheck: every channel's alternate input is its own WING
  LIVE track, CRD 1 upward in channel order.
```

If you name the card and not the track numbers, they are counted for
you: the next free `CRD` socket, in channel order, a stereo channel
taking an odd/even pair, with an INFO note listing every one. Name the
numbers ("Kick plays back from CRD 17") and they are used as written. A
channel with no alternate stated keeps the one already on the desk, which
breaks nothing: the strip works on its main input.

`verify` refuses an alternate the desk cannot take, such as a socket that
does not exist or a stereo channel's alternate that is not an odd/even
pair:

```
  [error] channels[Kick].alt_patch: CRD 65 does not exist -- CRD inputs are 1..64 on a WING Compact  (alt-patch.socket-out-of-range)
```

It warns when an alternate is someone else's main socket, because when
the strip is switched over it hears their source.

What `apply` writes, and why it also puts every strip back on its main
input, is on [What a full apply changes](/apply/what-apply-changes/#alternate-inputs-every-strip-back-on-its-main-input).

## Presets by name, never by value

```
- Lead Vox uses the "Lead Vocal" preset.
```

Name the preset. Never write an EQ curve or a compressor ratio into the
conventions file — that is what the preset is for, and duplicating it
into prose is how the two drift apart. Matching forgives case and
`-`/`_`/spaces ([how forgiving](/build/presets/#naming-one-and-how-forgiving-the-match-is)).
`build` puts the preset's values into the plan, so you can read exactly
what will be written before anything touches the desk. A value your
conventions state for the same parameter (the channel's own high-pass)
replaces the preset's for that one parameter, with a note
([Your plan wins over the preset](/build/presets/#your-plan-wins-over-the-preset)).
A preset named in the input list's
[`preset` column](/build/input-lists/#the-preset-column) wins over one named
here, for that channel.

When your conventions name presets by kind -- one for alto sax, one for
baritone -- and the input list just says `Sax`, the build takes the
most common kind (an alto, so A Sax) rather than leaving the strip with
no preset, and says so in its notes, naming the other: call the row
`Baritone sax` for B Sax. A tom with no qualifier is read as a rack
tom, a guitar as electric. `patch` makes the same choice
([patch.md](/patch/patch/)). It is the model's choice from your wording, so
read the note; a wrong guess costs a moment at soundcheck.

### Mix and FX busses: name a bus preset

```
- Mix busses are STEREO, routed to Main at unity, faders at unity. Channel sends to them are POST fader at unity, and a channel in a mix bus does not also go to Main directly. Every mix bus takes the bus preset "Mix Bus", which carries its compressor. A mix bus with no channel feeds is left out of the plan.
  - "Drums": every drums-category channel.
  - "Horns": every horns-category channel.
  - "Vocals": every vocals-category channel.
- FX busses are STEREO, routed to Main at unity, faders at unity. Each FX bus takes the bus preset of the same name ("Vox Verb", "Snare Verb"), which carries its reverb or delay.
```

Those are the starter's own lines. Naming the bus preset is all the
conventions do; saving one, and what the build and `apply` do with it,
is on [Bus presets: mix and FX busses](/build/bus-presets/). Say "the bus
preset" (or "bus preset Vox Verb"), so it is not read as a channel
preset; the two may share a name. Do not describe the reverb in words:
Atoo cannot set an effect from a description.

For colours, including the names the desk does not have, see the
[conventions reference](/build/conventions-reference/#the-desks-eighteen-colours).

## A channel that is not on the input list

A talkback mic, an ambient pair, a click from your own laptop: channels
that are yours, not the band's. Ask for one in a sentence that names its
socket ("Talkback on channel 40, source LCL 12"), in the show's
`instructions.md` or, for every show, here. See [Channels that are not
on the input list](/build/extra-strips/).

## `instructions.md` layers over it

A show bundle can carry an `instructions.md`: how *this* show differs.
The house conventions are always brought in, and the show's instructions
layer over them, winning where the two disagree; where it is silent, the
conventions apply in full ([Show bundles](/build/show-bundles/#two-files-that-do-not-go-in-the-bundle)).

```bash
atoo build --show clubdate --conventions house.md
```

```
Conventions, in order -- each layer overrides the one above it:
  1. house.md  (--conventions)
  2. clubdate/instructions.md  (show bundle clubdate)
```

`build` prints that stack every time, so a plan can always be
explained afterwards. (The run above then stops with `no console model
stated`, a separate flag — see [Command-line quickstart](/getting-started/quickstart/).)

## A default conventions file across every show

Naming the house file by hand every time — or, worse, copying it into
every show's folder — is how three slightly different house files come
to exist. Name it once in `~/.atoo.config`:

```toml
[conventions]
default = "~/conventions/house.md"
```

Then, in a directory holding nothing but tonight's input list:

```bash
cd ~/shows/2026-10-03-club-date
ls
atoo build
```

```
input.csv
(input list: input.csv)

Conventions, in order -- each layer overrides the one above it:
  1. /home/you/conventions/house.md  (/home/you/.atoo.config)
```

The default is consulted **last**: an explicit `--conventions`, or a
conventions file `build` finds in the current directory, always wins
without the config file even being read. A missing `~/.atoo.config`
is normal and silent; one that is wrong prints one line saying what is
wrong with it and is then ignored. The browser page can write the
`[conventions]` line for you: see [Setting up Atoo](/getting-started/configuration/#the-config-file).

## See also

- [Conventions reference](/build/conventions-reference/) — the levels vocabulary, the desk's colours, and the resolved file
- [Writing an input list](/build/input-lists/) — the other half
- [Channels that are not on the input list](/build/extra-strips/) — talkback, playback and the strips you add at every show
- [Command-line quickstart](/getting-started/quickstart/) — both files through to a proven desk
- [Show bundles](/build/show-bundles/) — where `instructions.md` lives
- `starter/conventions.md` — the complete starter, which builds the Demo show
- [Conventions reference](/build/conventions-reference/) — the levels
  vocabulary, the desk's colours, and the rules Atoo writes beside yours
