# atoo-rules-smallband.md

## Inputs
Patch order: drums, then band, then vocals, then misc.
Within drums: kick, snare, overheads (stereo), other percussion.

## Channels
Match inputs in patch order. Stereo-paired inputs become one stereo channel.

## Processing
Drums get a high-pass at 80Hz.
Band channels get a high-pass at 40Hz.
Vocals get a high-pass at 100Hz.
Lead Vox uses the "Lead Vocal" preset.
All other vocals-category channels use the "BGV" preset.

## DCAs
- Drums: all drums-category channels
- Band: all band-category channels
- Vocals: all vocals-category channels
- FX: all effects busses

## Mute Groups
- Vocals: same membership as the Vocals DCA

## Busses
- Drums: drums channels route to bus post-fader at unity, bus routes to main
- Drums Compressed: same as Drums, plus a compressor on the bus, -6dB
- Vocals: vocals channels route to bus post-fader, bus routes to main
- Monitor 1: drums channels route to bus pre-fader at unity, bus routes to a dedicated output, named "Drum wedge", routed to Local outputs 3-4
- FX: effects busses route to main

## Output
- Main: full mix, routed to Local outputs 1-2, EQ set for a recordable sound
- Matrix: fed from Main, EQ corrects the room

## Watch
Alert if any vocals-category channel is muted.
Alert if the Main fader moves below -10dB.
