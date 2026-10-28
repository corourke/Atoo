# atoo-rules-splits.md

## Inputs
Inputs are on stage box AES50-A in the socket order given.
Overheads and keys are stereo pairs.

## Channels
Match inputs in socket order. Stereo-paired inputs become one stereo channel.

## Processing
Drums get a high-pass at 80Hz. Band channels 40Hz. Vocals 100Hz.

## DCAs
- Drums: all drums-category channels
- Band: all band-category channels
- Vocals: all vocals-category channels

## Busses
- Wedge 1: vocals channels pre-fader, bus routes to Local outputs 3

## Output
- Main: full mix, routed to Local outputs 1-2

## Splits
- Monitor split: every input socket goes out, unprocessed, on AES50-B in the same order (AES50-A 1 to AES50-B 1, AES50-A 2 to AES50-B 2, and so on for all 12 inputs). The monitor desk is on AES50-B.
- Recording split: every input socket also goes out on sequential USB channels in input order (AES50-A 1 to USB 1 through AES50-A 12 to USB 12), for multitrack recording.
- Nothing else uses AES50-B outputs 1-12 or USB outputs 1-12.
