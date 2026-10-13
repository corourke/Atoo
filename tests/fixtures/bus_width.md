# Conventions -- bus width

Deliberately small, and deliberately shaped like the file that broke: the width is stated in the MIDDLE of a bullet that also
says three other things, which is how `examples/conventions.md` states
it and how a real engineer writes. Every width this file states out
loud has to reach the plan, whichever width it is.

## Sources
- Patch input sockets according to the supplied input list.

## Channel Assignments
- Patch drums first, then bass, then vocals.
- Send all channels to the Main L/R bus unless they are included in one
  of the mix busses below.
- Leave all faders all the way down.

## Busses
- Setup the bus ordering with monitor busses first, then mix busses, then
  FX busses.
- Monitor Busses. Leave bus faders all the way down. Do not patch to main.
  - Create two monitor busses, named 'MON1' and 'MON2', these will all be
    MONO busses.
  - Patch output to local XLR outputs 1 and 2 if not specified otherwise.
  - Leave all sends from channels to monitor busses all the way down, mute
    off, mode is PRE fader.
- Mix Busses. These are stereo busses. Patch all to Main mix, POST fader at
  unity. Bus faders at unity. Sends from channels to these busses should be
  at unity, POST fader.
  - "Band": include every channel.
- FX Busses. These are stereo busses. Create the following FX busses and
  send them to Main at unity, post fader. Fader at unity.
  - "VOX Reverb" -- all vocal channels.
