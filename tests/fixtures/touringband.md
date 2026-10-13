# atoo-rules-touringband.md

A third worked example, added 2026-09-10 as a one-time hand conversion of a
real WING show file (`TOURING_260821_MIX.snap`, one of the three files
behind `wing-console-model.md`'s calibration section) into a conventions
file -- not the output of a tool (the general-purpose show-file decompiler
that idea points at is still deferred), a human reading of the real data.

Two honest gaps from that conversion, left visible rather than papered
over:
  - WING's saved show data has no microphone-type or model field at all --
    only channel name/tags/color/icon are stored. `touringband.csv`'s
    `type`/`model` columns are therefore best-effort, populated only where
    a model was literally embedded in the channel name (the three horn
    mics, e.g. "T.Sax SM57"); everything else is a guess from the channel
    name and left blank rather than invented.
  - The real show's Main bus fans out to three physical destinations at
    once (USB, a card slot, and a recorder) -- a real, confirmed pattern
    (see wing-console-model.md), not an edge case. The schema only
    supports one socket per bus/output entry (`project-brief.md` §10 logs
    this as a known gap), so `## Output` below states one representative
    destination rather than all three.

Also real, and deliberately reproduced here rather than smoothed away:
Horns channels (the three horn mics) had no DCA at all in the source show
-- only a mute group and a bus. Category rules don't need a DCA to exist
to be useful.

## Inputs
Patch order: drums, then bass, then guitars, then keys, then horns, then vocals, then tracks.
Within drums: kick, snare, tom 1, hi-hat, floor, overhead.

## Channels
Match inputs in patch order. Stereo-paired inputs become one stereo channel.

## Processing
Drums get a high-pass at 80Hz.
Bass channels get a high-pass at 40Hz.
Guitars channels get a high-pass at 80Hz.
Horns channels get a high-pass at 100Hz.
Vocals get a high-pass at 120Hz.

## DCAs
- Drums: all drums-category channels
- Bass: all bass-category channels
- Guitars: all guitars-category channels
- Keys: all keys-category channels
- Vocals: all vocals-category channels
- Tracks: all tracks-category channels

## Mute Groups
- Drums: same membership as the Drums DCA
- Vocals: same membership as the Vocals DCA
- Inst: bass channels, guitars channels, keys channels, and horns channels
- Tracks: all tracks-category channels
- All Band: drums channels, bass channels, guitars channels, keys channels, horns channels, and vocals channels

## Busses
- Drums: drums channels route to bus post-fader at unity, bus routes to main
- Vocals: vocals channels route to bus post-fader at unity, bus routes to main
- Horns: horns channels route to bus post-fader at unity, bus routes to main
- Monitor 1: drums channels, bass channels, guitars channels, keys channels, horns channels, vocals channels, and tracks channels route to bus pre-fader at unity, set width to mono, bus routes to a dedicated output, named "Monitor 1", routed to AES50-A outputs 41
- Monitor 3: same as Monitor 1, set width to mono, bus routes to a dedicated output, named "Monitor 3", routed to AES50-A outputs 43
- Monitor 5: same as Monitor 1, set width to mono, bus routes to a dedicated output, named "Monitor 5", routed to AES50-A outputs 45
- Reverb Send: vocals channels route to bus post-fader, set width to mono, bus routes to a dedicated output, named "Outboard reverb send", routed to AES50-A outputs 25

## Output
- Main: full mix, routed to USB outputs 47-48, EQ set for a recordable sound
- Matrix: fed from Main, EQ corrects the room

## Watch
Alert if any vocals-category channel is muted.
Alert if the Main fader moves below -10dB.
