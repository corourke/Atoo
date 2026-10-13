<!-- This is an example conventions file that applies across all shows. -->

## Inputs
- Patch input sockets according to the supplied input list.
- If the input list gives no socket for a row, patch in channel order to local inputs 1-24, then overflow to AES50-A from 1.
- Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple

## Channels
- Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else. 
- Drum kit order: kick, snare, hi hat, rack toms, floor toms, overheads and then any other percussion.
- The lower-numbered toms are rack toms. There is almost always only one floor tom (the highest number); if there were more, the input list would say so.
- If you see Left/Right designations in the overhead (OH) names, do NOT patch as a stereo pair, keep as separate mono channels -- the reason is they get separate processing.
- For instruments other than overheads, if two sequential inputs are marked as stereo pair (L/R, Left/Right), patch as one stereo channel.
- Any inputs that are for background music, or any audio source that is not a part of the band should be placed on an Aux channel. One exception is speech, those inputs should get a regular channel.
- Use same color coding for channels as the sources.

## Processing
- I always want a highpass at 40 Hz on anything in the drums category.
- Same idea for band instruments, but higher -- 80 Hz is fine.
- Guitars channels get a high-pass at 80Hz.
- Horns channels get a high-pass at 100Hz.
- Vocals need more low end removed, so put their high-pass up at 120Hz.
- Speech channels get a high-pass at 120Hz, like vocals.
- Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send.
- Send all Channels to the Main L/R bus unless they are included in one of the mix busses below.
- Unless overridden by the show instructions, set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB.
- Leave all faders all the way down. 

## Busses
- Setup the bus ordering with monitor busses first, then mix busses then FX busses.
- Monitor Busses. Leave bus faders all the way down. Do not patch to main.
  - Create four monitor busses, named 'MON1' thru 'MON4', these will all be MONO busses. 
  - Patch output to local XLR outputs 1 through 4 if not specified otherwise.
  - Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader. <!-- Monitors will be mixed during a soundcheck. -->
- Mix Busses. These are stereo busses. Patch all to Main mix, POST fader at unity. Bus faders at unity. Sends from channels to these busses should be at unity, POST fader. 
  - Drums: include all drum channels, and it feeds the main mix.
  - "Drums Comp": Compressed drums. A duplicate of the Drums bus, but with heavy compression added. (Start with the 'No Stressor' compressor at -20dB threshold, attack 20ms, release 50ms). Leave the fader pulled down 6dB.
  - "Vocals": include all vocal channels. 
  - If there are multiple keyboards, create a "Keys" bus.
  - If there are multiple horns, create a "Horns" bus. 
  - If there are multiple strings, create a "Strings" bus. 
- FX Busses. These are stereo busses. Create the following FX busses and send them to Main at unity, post fader. Fader at unity. Sends to these busses are generally at unity, POST fader, unless noted below. 
  - "VOX Reverb" -- All vocal channels
  - "VOX Delay" -- All vocal channels
  - "Snare Verb" -- Snare channels. Sends from channels at -10db, PRE fader.
  - "INST Reverb" -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader.

## DCAs
Create a DCA for the following instrument grouping if there is at least one member:
- Drums DCA should include every channel in the drums category.
- Guitars: all guitars-category channels
- Keys: all keys-category channels
- Vocals: all vocals-category channels
- Tracks: all tracks- or trax- category channels
- Strings: all strings-category channels
- Horns: all horns-category channels
- Band: Include all other instruments not included in one of the DCAs above.
- Speech: Hosts, MCs, Podium Mics, Presenters, Pastors, etc.
- FX should include all the effects return busses.

## Mute Groups
- Band: All band instruments
- Vocals: All (singing) vocal channels
- Speech: All speech channels
- FX: All FX busses


## Outputs
- Main should be the full mix. Send to Matrix 1. Main has no physical output of its own; it only feeds Matrix 1. <!-- We will EQ this so it sounds good for a recording. -->
- Matrix 1 takes its feed from Main. Patch output to internal XLRs 7 and 8. <!-- We will EQ to correct for the room. -->

