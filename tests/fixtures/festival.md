# atoo-rules-festival.md

A fourth worked example, added 2026-09-10: a composite conventions file
hand-derived from `Festival_STANDALONE.snap`, the third of the three real
WING show files behind `wing-console-model.md`'s calibration section.
Companion to `tests/fixtures/festival.csv`, a **deliberately partly
filled** input list -- the real show itself is a template with 14 of its
38 named channels still unpatched (`grp: "OFF"` in the source data,
`socket` left blank here so the compiler auto-assigns and flags them),
not something invented for this fixture. Levels, fader positions, and
other per-show tuning are intentionally left out per the brief this file
was built from ("don't worry about things that will vary a lot") -- the
point of this file is to get close to expressing the real *routing*.

This show file is structurally richer than `touringband.*` and surfaced
real routing shapes our schema cannot yet fully express. Rather than
force-fitting them into the grammar or silently dropping them, they're
named here so the gap is visible:

  - **A channel can route straight to Main with no bus and no DCA at
    all.** HOST (an emcee mic) has neither -- it's on Main 1 directly,
    no subgroup. Un-deferred 2026-09-10: `## Processing` now
    has a "routes directly to main" statement for exactly this case (see
    below), so HOST is no longer just an input row with nothing else --
    an even starker case than `touringband.md`'s Horns (which at least
    had a bus and mute group) is now actually expressible.
  - **A bus can feed Main and a dedicated physical output at the same
    time.** The real VOCALS bus does both (Main 1, and duplicated out to
    AES50-A 44 / StageConnect 4 -- likely a vocals-only reference feed).
    `GroupDef.destination` is one value ("main" xor "dedicated_output"),
    so `Vocals` below states only the Main routing, the one that matters
    for the mix; the duplicate physical feed is dropped rather than
    guessed at.
  - **A mute group can contain busses, not just channel categories.**
    The real file's "MONITORS" mute group holds the six monitor busses
    themselves; "ALL BAND" holds every channel category *and* the
    VOCALS/DRUMS/FX busses. `CATEGORY_CHANNELS_RE` only recognizes
    "X channels" -- there's no grammar for "X busses" as mute-group
    members, so only the channel-category half of "ALL BAND" is stated
    below.
  - **Not every monitor bus in a template is actually wired up.** MON2,
    MON4, and MON6 exist (tagged into that same MONITORS mute group,
    fed pre-fader from every channel, identically to MON1/3/5) but have
    no physical output patched at all in this standalone show -- the bus
    equivalent of an unpatched channel. Left out of `## Busses` below
    rather than inventing a socket for them.
  - **Eight matrices exist in the real show** (MAIN OUT, DELAY, SUBS,
    REF, MON 1-4) feeding broadcast, delay towers, sub alignment, and a
    reference wedge. Only one representative `Matrix` entry is modeled
    below -- the rest would just repeat the same "fed from Main" shape
    for different physical destinations, which is exactly the kind of
    per-show variation the brief this file follows says to skip.
  - **Overheads aren't always a linked stereo pair.** OH L and OH R are
    two independent mono channels in the source data (their own `io.in`
    sources are both `mode: "M"`), unlike `smallband.md`/`fullband.md`'s
    "overheads (stereo)" assumption -- so they're two ordinary drums-
    category rows here, not one stereo row.

## Inputs
Patch order: drums, then bass, then guitars, then keys, then horns, then strings, then vocals, then host, then tracks.
Within drums: kick, snare, hi-hat, tom 1, tom 2, tom 3, tom 4, overhead L, overhead R, pads, perc 1, perc 2.

## Channels
Match inputs in patch order. Stereo-paired inputs become one stereo channel.

## Processing
Drums get a high-pass at 65Hz.
Bass channels get a high-pass at 70Hz.
Keys channels get a high-pass at 80Hz.
Host routes directly to Main.

## DCAs
- Drums: all drums-category channels
- Bass: all bass-category channels
- Guitars: all guitars-category channels
- Keys: all keys-category channels
- Horns: all horns-category channels, all strings-category channels
- Vocals: all vocals-category channels
- Tracks: all tracks-category channels
- FX: all effects busses

## Mute Groups
- Drums: same membership as the Drums DCA
- Inst: bass channels, guitars channels, keys channels, horns channels, and strings channels
- Vocals: same membership as the Vocals DCA
- Tracks: same membership as the Tracks DCA
- All Band: drums channels, bass channels, guitars channels, keys channels, horns channels, strings channels, vocals channels, and tracks channels

## Busses
- Drums: drums channels route to bus post-fader at -10dB, bus routes to main
- Vocals: vocals channels route to bus post-fader at -6dB, bus routes to main
- Monitor 1: drums channels, bass channels, guitars channels, keys channels, horns channels, strings channels, vocals channels, and tracks channels route to bus pre-fader, bus routes to a dedicated output, named "MON1", routed to AES50-A outputs 41
- Monitor 3: same as Monitor 1, bus routes to a dedicated output, named "MON3", routed to AES50-A outputs 42
- Monitor 5: same as Monitor 1, bus routes to a dedicated output, named "MON5", routed to AES50-A outputs 43
- FX: effects busses route to main

## Output
- Main: full mix, routed to USB outputs 47-48
- Matrix: MAIN OUT feed, fed from Main, routed to Local outputs 7

## Watch
Alert if any vocals-category channel is muted.
Alert if the Main fader moves below -10dB.
