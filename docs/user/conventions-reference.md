# Conventions reference

The words and the details behind [Writing conventions](conventions.md):
the levels vocabulary the build understands, the desk's colours, and
the resolved file Atoo writes beside your conventions. Come here to
look something up; to write a conventions file, start with the how-to.

## Levels, in the words you would say them

- `unity` means `0.0` dB.
- **All the way down** has five recognised spellings — `all the way
  down`, `fully down`, `minus infinity`, `-inf`/`-infinity` and `off` —
  and they all mean the desk's own fader floor.
- Anything else is the number as written: `-6`, `-10dB`, `+3`.

"Leave all faders all the way down" is a convention like any other, not a
special case. So is a bus parked at −6 dB for headroom.

Starting levels can be stated in three places, each in its own natural
phrasing: in your processing section (*"Vocals start at unity."*,
*"Start everything muted."*), inside a bus's own bullet (*"… starts at
−6dB"*), or as one line covering every bus that does not state its own
(*"Busses start at −6dB."*). A bus's own bullet always wins over the
file-wide line.

## Bus colours

A bus is coloured when your conventions say so, and stays uncoloured
when they do not -- a bus colour is never picked for you. State it the
way you state a channel's, by one of the desk's eighteen names, for one
bus or for a whole kind of bus. Any of these works as a line under
`## Busses`:

```markdown
- Monitor busses are White. Mix busses take their category's colour. FX busses are Purple.
```

"Take their category's colour" means the colour your `Color coding:`
line gives that category's channels -- a "Drums" bus is Red when drums
are Red. A single bus can be named too (`"Drums Comp" is Rust`). The
build writes the name into the bus's `color` in `plan.json`, `apply`
writes the desk's matching colour to the bus, and step 04 paints the
bus's number chip in it. A bus with no stated colour keeps whatever the
desk already had.

## The desk's eighteen colours

Say a colour in the desk's own word. The WING's palette is eighteen
colours, and these are the names the desk itself shows for them, in its
own order (index 1 to 18):

> Navy, Blue, Violet, Turquoise, Green, Lime, Yellow, Rust, Red,
> Salmon, Pink, Purple, Amber, Cyan, Orange, Mint, Grey, White

Case and spacing do not matter (`red`, `Red` and `RED` are the same).

**`Crimson` and `Magenta` are accepted too**, as other names for the
desk's Red (9) and Pink (11). The strip gets that colour, and verify
says which desk colour it became, as a note. The touring-band plan (here,
its frozen copy) was built from conventions that say `Guitars-Magenta`:

```
atoo verify --show docs/user/demo/touringband
```

```
0 error(s), 0 warning(s), 15 note(s)

  [info] plan: 'Magenta' is the desk's Pink (11): EG 1. The desk has no colour called 'Magenta'; Atoo used that name for 11 until the desk was asked, so it still resolves. Say 'Pink' to use the desk's own word  (strip.colour-alias)
  ...
```

Change the word to `Pink` in the conventions, rebuild, and the note goes.
A bus named with an old word gets the same note, as `bus.colour-alias`.

## Colours the desk does not have

A conventions file that asks for a colour outside the eighteen gets a
warning naming the strip and the eighteen it could have had. On the
Demo show (from an Atoo checkout) with Gtr 1 set to `Gold`:

```bash
python3 -c "import json; p = json.load(open('starter/demo-show/plan.json')); \
p['channels'][6]['color'] = 'Gold'; json.dump(p, open('/tmp/gold.plan.json', 'w'))"
atoo verify --plan /tmp/gold.plan.json --input starter/demo-show/input.csv
```

prints, among its other findings:

```
0 error(s), 1 warning(s), 4 note(s)

  [warning] plan: 1 strip(s) state a colour the console does not have: 'Gold' (Gtr 1). The desk's eighteen are Navy, Blue, Violet, Turquoise, Green, Lime, Yellow, Rust, Red, Salmon, Pink, Purple, Amber, Cyan, Orange, Mint, Grey, White. Those strips keep whatever colour they already had -- pick one of the eighteen, or set 'col' directly to the index you want  (strip.colour-not-writable)
  ...
APPLICABLE: warnings only.
```

It is a warning and not an error, and that strip keeps whatever colour it
had. Nobody's show is blocked over a colour — but nothing picks Amber or
Yellow on your behalf either, because that would put a colour on a desk
you did not choose.

A bus colour the desk does not have is reported the same way, once for
the plan, as `bus.colour-not-writable`, naming the busses; they too keep
the colour they had.

## The resolved conventions

*An experiment.* The first time you build with a
conventions file, Atoo asks a model to restate it — together with
the audio domain knowledge it relies on — as one set of explicit rules,
and writes them beside your file: `house.md` gives `house.resolved.md`.
From then on the model that lays out each show reads that file instead
of your conventions and the domain knowledge, so it does not work out
the same things from scratch every show. It is made again only when your
conventions (or the domain knowledge, or the prompt that makes it)
change. [How a show gets built](pipeline.md#0-resolve-your-conventions-restated-once-as-rules)
has the build's side of it.

**Read it.** It is written for you as much as for the model: if a rule
in it is not what you meant, your conventions did not say what you meant
clearly enough, and every show was going to be built on that reading. A
file made from this `house.md` (the reply here was written by hand for
the example, standing in for the model; the transcripts below were run
with it):

```
# House conventions

## Inputs
- Patch in channel order to local inputs 1-24.

## Processing
- Drums get a high-pass at 40 Hz; vocals and speech at 120 Hz.
- Drums are red, vocals green, speech purple.
- Set the head-amp gain on each channel to 20dB, and the Trim to 0dB.

## Busses
- Create "Drums", a stereo mix bus with every drum channel, feeding Main.
- Send all channels to the Main L/R bus unless they are in a mix bus.

## Other
- We usually have a good time. <!-- keep it that way -->
```

reads, in part:

````
### Drums
- Colour: Red. [conventions: "Drums are red, vocals green, speech purple."]
- HPF: 40 Hz. [conventions: "Drums get a high-pass at 40 Hz"]
- Main routing: none direct -- through the Drums bus only. [conventions: "Send all channels to the Main L/R bus unless they are in a mix bus."]

## Head amps
- Digital source (USB, card, player): no head amp, so no gain; trim 0 dB. Decided: "each channel" means each channel with a preamp. [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

## Lines with no effect
- [conventions: "We usually have a good time."] a remark, not a setting.

## Category table

```json
[
  {"name": "Drums", "aliases": ["drums", "drum"], "color": "Red", "hpf_hz": 40, "gain_db": 20, "trim_db": 0, "main_direct": false},
  ...
]
```

## Instructed strips

```json
[]
```
````

Five things to know when reading it:

- **The brackets are the source.** Every rule ends with the words it
  came from, copied exactly: `[conventions: "..."]` is a line of your
  file, `[domain: "..."]` a sentence of Atoo's domain knowledge.
  Code checks every one is really there. They are for that check and
  for you: the build strips them before the generator reads the file,
  since they are over half of it and the generator needs only the
  rules.
- **`Decided:` is a judgement made on your behalf**, in the spirit of
  the build's INFO notes: your conventions were silent or unclear, so a
  choice was made once, with its reason, and every show will follow it.
  If you disagree, say what you want in your conventions; the file is
  then out of date and the next build makes it again.
- **"Lines with no effect"** lists the lines of your file that produce
  no setting, with why. A line you meant as a rule showing up here is
  worth rewording.
- **The Category table** at the end is the Categories section again,
  as data for code: per category, the input-list category words it
  covers (`aliases`) and its colour, high-pass, DCA, mute group, gain,
  trim, starting fader and Main routing (`main_direct`: true is straight
  to Main, false only through its busses). A field it leaves out is one
  the rules do not settle for the whole category. [Below](#the-category-table).
- **Instructed strips**, last, lists the strips your conventions ask
  for that are not on any input list (a talkback mic on Aux 8, say), as
  data code builds. `house.md` asks for none, so it is `[]`.
  [Strips your conventions ask for](extra-strips.md#strips-your-conventions-ask-for).

**What is checked, with no model call:**

```bash
atoo resolve --conventions house.md --check
```

```
house.resolved.md: fresh (the conventions, the domain knowledge and the resolve prompt are unchanged)
house.resolved.md: 11 of 11 citation(s) found; 7 of 7 conventions line(s) covered
house.resolved.md: Category table valid, 3 categories
house.resolved.md: Instructed strips valid, 0 built by code
```

After adding a line to `house.md`, before any build:

```
house.resolved.md: stale (the conventions changed)
house.resolved.md: 11 of 11 citation(s) found; 7 of 8 conventions line(s) covered
house.resolved.md: Category table valid, 3 categories
house.resolved.md: Instructed strips valid, 0 built by code

Resolved conventions -- 1 note(s):

NOTE     house.md: the conventions line "- Leave all faders all the way down."
         is cited by no rule in house.resolved.md and not listed under "Lines
         with no effect" -- the generator is given it verbatim instead
         Your line: - Leave all faders all the way down.
         Fix: resolve again (`atoo resolve`), or make the line clearer; a
         quote of fewer than four words covers a line only when it is the
         whole line
         (resolve.line-not-covered)
```

(It exits 0 when the file is fresh and clean, 2 when it is usable with
warnings or stale, and 1 when there is no usable file.) A line no rule
cites is a note, not a warning: the generator reads that line as you
wrote it, so nothing is lost. A quote that is not in your file or the
domain knowledge is a WARNING, `resolve.quote-not-found`: the rule
citing it may be the resolver's own, not yours. Neither stops the file
being used; a file that is empty or quotes nothing that can be found is
not used at all, and the build reports it. A build prints these as one line
each (how many, and this command to list them); every one is kept in the
plan's `meta.build_findings`.

A quote counts as found however a model retypes it: double quotes as
single ones (`'INST Reverb'` for your `"INST Reverb"`), several lines
cited together as `"a" / "b"`, a middle left out as `...` (each part
must be there, in order), a trailing full stop of its own, or a
sentence quoted across the place your file wraps it -- including a wrap
the model wrote out as the two characters `\n`.

A line counts as covered when a quote of four words or more is found in
it, or a shorter quote is the whole line. A list item's bullet is not a
word: `- Snare: "Snare"` quoted with or without its `- ` covers that
line. A line ending in a colon that introduces indented items under it
(`- Default channel presets by source:`) is covered when any of its
items is. A list line, such as
`- Color coding: Drums-Red, Bass-Blue, ...`, also counts when at least
half its items, and at least two, are each quoted whole: the resolved
file cites a colour list one category at a time.

Your preset map is the exception: an item indented under a line that
names presets (`- Default channel presets by source, from my preset
library:`) that quotes a preset (`- Kick: "Kick In"`) or says `no
preset` counts as covered whenever your preset library has every preset
it names, whether the resolved file cites it or not. The build's preset
choice reads that line, not a rule, and the generator still reads it
as you wrote it. The library is the one the build uses (`--presets`, or
`[presets] default` in `~/.atoo.config`; `resolve --check` reads the
default; it says which library it used, as an `INFO preset library:`
line, before anything else). An item naming a preset the library has not
got is still a note, and says which. Here `house.md`'s map has
`- Kick: "Kick In"`, which the starter library (here `[presets] default =
"presets"`) has, and `- Snare: "Snare Top"`, which it has not;
`resolve --check` lists only the second:

```
NOTE     house.md: the preset map line "- Snare: "Snare Top"" names "Snare
         Top", which is not in the preset library (presets) -- a channel given
         it is built without its processing
         Your line: - Snare: "Snare Top"
         Fix: export a preset saved under that name into the library, or
         change the line to a name `atoo presets` lists
         (resolve.line-not-covered)
```

A few more things about the preset map:

- **Bus presets count.** Which presets a map item is looked up among
  depends on the line it sits under. Under a line that says *bus*
  (`- Default bus presets:`), it is your bus presets (`.bus` files);
  under one that says *channel*, your channel presets (`.chn` files);
  under one that says both, or neither, either kind. So
  `- Drums: "Mix Bus"` is covered when `Mix Bus.bus` is in the library.
- **A heading line is covered with its items.** The line that
  introduces the map (`- Default channel presets by source, ...:`)
  counts as covered as soon as any item under it does, so the notes do
  not depend on which lines the resolved file happened to cite.
- **An item that states a rule is not covered by the library.** The
  preset choice reads only the preset's name, so
  `- Vocals go to the "Vox Verb" bus and get 3 dB more at 3k` is a note
  that quotes the part it does not carry out ("bus and get 3 dB more at
  3k"): put the rule on a line of its own. A number, a processing word
  (a level, a filter, a compressor, `must`, `always`) or more than ten
  words of prose around a name is read as a rule; a few words saying
  which channel a name is for (`"H Tom" for the high (or only) rack
  tom`) are not. Names may be in double or single quotes.
- **A library that cannot be read is said, not skipped.** If the
  library's files cannot be opened (the folder is gone, a preset file
  is damaged), no name can be checked, so every map item counts as
  covered, and one note, `resolve.preset-library-unreadable`, gives
  the reason.

For the Vocals line above, `resolve --check` says:

```
NOTE     house.md: the preset map line "- Vocals go to the "Vox Verb" bus and
         get 3 dB more at 3k" says more than a preset name ("bus and get 3 dB
         more at 3k"), and no rule in house.resolved.md cites it -- the preset
         choice reads only the name, so the rest reaches the generator
         verbatim instead
         Your line: - Vocals go to the "Vox Verb" bus and get 3 dB more at 3k
         Fix: put that rule on a line of its own, outside the preset map, or
         resolve again (`atoo resolve`)
         (resolve.line-not-covered)
```

**Making it again.** It is made again by itself when it goes stale. To
make it again anyway — you have read it and disagree with a decision,
say, and have reworded your conventions, or you want a second opinion —
run `atoo resolve`, which always makes a new one (one model call):

```bash
atoo resolve --conventions house.md
```

```
INFO resolved conventions: house.resolved.md is missing (there is no resolved file yet) -- resolving now: one model call, role resolve
  claude-sonnet-5-5 (resolve, effort medium): ... in, ... out -- $...
resolve: wrote house.resolved.md
resolve: checked house.resolved.md: 11 of 11 citation(s) found; 7 of 7 conventions line(s) covered
resolve: Category table valid, 3 categories
resolve: Instructed strips valid, 0 built by code
```

The second line is the model call's usage: tokens in and out, and what
it cost.

Deleting the file does the same at the next build. Editing it by hand
works, and the edit lasts until the next time it goes stale, when it is
overwritten — so an edit worth keeping belongs in your conventions.
`atoo build --no-resolve` (or `ATOO_RESOLVE=0`) builds from
your conventions and the domain knowledge as they are, without it.

Commit it beside your conventions: it is the reading every show was
built from. Its header records the three checksums it is fresh against
and which Atoo made it (`atoo: 0.2.5 (8779a67)`, the version
and git commit). The checksums ignore line endings and Unicode spelling,
so the same files read fresh on any machine. If a machine finds the file
stale when you expected it fresh, the message names the Atoo that
made it and the one reading it -- usually a checkout that has not been
pulled yet.

### The Category table

Most of what your conventions say about a channel
depends only on its category: every drum gets the same high-pass, DCA,
mute group, gain and trim. So the build does not ask the model to write
those thirty times. Code reads the table and, on every channel whose
input-list row has one of a category's words in its `category` column,
writes each of those settings **the model left out**. What the model
writes itself wins: that is how a channel that differs from its category
(one host who needs a lower cut) stays different. The model is told,
for the categories on your input list, exactly what code will write.

A few things code decides while doing it, each said in the note below:
an aux strip gets no high-pass (it has none), a USB or card source gets
no gain (it has no head amp), and a strip named as a click, guide or
talkback never goes straight to Main from the table, since a "tracks"
row might be the click. A channel the show's instructions ask for (a
Talkback on channel 40) is not a row of your input list, so the table
does not touch it. A strip your conventions ask for takes the values of
the category its entry in the Instructed strips names: a HOST mic
whose entry names Speech gets Speech's colour, DCA and mute group. An
entry that names no category takes the one its name is a word of
(MUSIC is a Misc word), else the one for its kind of strip (`aux`), and
the build's INFO line for the strip says which and why.

Each setting code wrote is marked in the plan: the channel's provenance
reads `category table: Drums`, and the build keeps one note per
category in `meta.build_findings`. From the three-row show the
transcripts here were built on (Kick, Lead Vox, Host), where the
stand-in model wrote only the Host's high-pass:

```
Drums (input-list category 'drums'): 1 channel(s), Kick. Written by code where the reply left the field out: colour Red (all); HPF 40 Hz (all); gain 20 dB (all); trim 0 dB (all); Main only through its busses (all)
Speech (input-list category 'speech'): 1 channel(s), Host. Written by code where the reply left the field out: colour Purple (all); gain 20 dB (all); trim 0 dB (all); straight to Main 1 (all). The reply's own, different value kept: HPF (Host)
```

**When a value is wrong, correct your conventions**, not the table: it
restates your rules, so a wrong value there is a rule your conventions
did not state the way you meant, and the next resolve makes it again.
The table must agree with the prose above it; `atoo resolve
--check` says whether it is valid. One that is not (bad JSON, a value
the desk cannot take, one category word in two entries) is a WARNING,
`category-table.invalid`, and is not used: the model then writes every
setting itself, as before. A file made before the table existed has
none, and is made again at the next build anyway.

`atoo build --no-category-rules` (or `ATOO_CATEGORY_RULES=0`)
ignores the table, for comparing builds with and without it.

## See also

- [Writing conventions](conventions.md) — the how-to this page backs up
- [How a show gets built](pipeline.md) — where the resolved file is made and read
- [Reading findings](reading-findings.md) — what an INFO note means
