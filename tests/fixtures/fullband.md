# atoo-rules-fullband.md

A richer worked example than `smallband.md`, built 2026-09-10 directly
from patterns found in three real WING show files the maintainer supplied (see
`docs/reference/wing-console-model.md`'s calibration section) rather
than invented: multiple monitor sends that don't route to Main, a bus
routed to a dedicated output for a non-monitor reason (an outboard
effects unit), and a channel-specific processing override sitting
alongside its category's default -- all three confirmed as normal, not
edge-case, in real production shows.

## Inputs
Patch order: drums, then band, then vocals, then misc.
Within drums: kick, snare, hi-hat, tom 1, tom 2, overheads (stereo).

## Channels
Match inputs in patch order. Stereo-paired inputs become one stereo channel.

## Processing
Drums get a high-pass at 80Hz.
Kick gets a high-pass at 50Hz.
Hi-Hat gets a high-pass at 300Hz.
Band channels get a high-pass at 40Hz.
Vocals get a high-pass at 120Hz.
Lead Vox uses the "Lead Vocal" preset.
All other vocals-category channels use the "BGV" preset.

## DCAs
- Drums: all drums-category channels
- Band: all band-category channels
- Vocals: all vocals-category channels
- FX: all effects busses

## Mute Groups
- Vocals: same membership as the Vocals DCA
- Band: same membership as the Band DCA

## Busses
- Drums: drums channels route to bus post-fader at unity, bus routes to main
- Vocals: vocals channels route to bus post-fader at unity, bus routes to main
- Drum Wedge: drums channels route to bus pre-fader at unity, bus routes to a dedicated output, named "Drummer IEM", routed to Local outputs 3-4
- Vocal Wedge: vocals channels route to bus pre-fader at unity, bus routes to a dedicated output, named "Vocal monitor", routed to Local outputs 5-6
- Reverb Send: vocals channels route to bus post-fader at -6dB, bus routes to a dedicated output, named "Outboard reverb send", routed to AES50-A outputs 3
- FX: effects busses route to main

## Output
- Main: full mix, routed to Local outputs 1-2, EQ set for a recordable sound
- Matrix: fed from Main, EQ corrects the room

## Watch
Alert if any vocals-category channel is muted.
Alert if the Main fader moves below -10dB.
