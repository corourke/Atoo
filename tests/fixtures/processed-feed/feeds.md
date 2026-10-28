# atoo-rules-processed-feeds.md

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

## Output
- Main: full mix, routed to Local outputs 1-2

## Feeds
- Stream recorder: the lead vocal, post-fader, on USB 13, so the stream follows the vocal's level in the mix.
- Keys to the video desk: the keys pre-fader, on USB 14-15, processed but not following the keys fader.
