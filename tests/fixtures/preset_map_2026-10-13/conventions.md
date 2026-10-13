<!--
Starter house conventions: a band or club show on a Behringer WING.

This is one working engineer's house style, written down so a build has
little to guess. Every line is a choice you would otherwise make at the
desk. Keep the ones you like, change the ones you don't, and delete the
rest. Anything inside these comment marks is a note to you: the build
never reads it. Atoo's Demo show is built from this same file.

What goes in this file is how you always set up a desk. What is true of one show
only (tonight's wedge mixes, a guest, a stage box on a different network)
goes in that show's instructions.md.
-->

## Inputs
- Patch input sockets according to the supplied input list. <!-- The list's socket column is usually what a stage box is cabled to. -->
- Phantom power comes from the input list's phantom column, never from here. 
- Color coding: Drums-Red, Bass-Blue, Guitars-Pink, Keys-Cyan, Horns-Amber, Vocals-Green, Playback-Yellow.
- Start every channel's head-amp gain at 20dB and its trim at 0dB. <!-- A safe start; gain is set properly at line check. -->

## Channels
- Channel order: drums, then bass, guitars, keys, horns, vocals, and playback last.
- Drum kit order: kick, snare, hi hat, toms from high to low, then overheads.
- Two inputs named as a Left/Right pair ("OH L"/"OH R", "Keys L"/"Keys R", "Playback L"/"Playback R") become one stereo channel, named without the L/R ("OH", "Keys", "Playback"). Overheads included. <!-- One fader and one preset for the pair. -->
- Everything on the input list gets a regular channel. Aux channels are for sources the show's instructions add.
- Start every channel fader all the way down, unmuted. 

## Processing
- Default channel presets by source, from my preset library: <!-- The name in quotes is the name saved inside the preset; Atoo CLI lists them with `atoo presets`. A preset's name need not match the channel's: the Kick channel uses "Kick In" and is still called Kick. -->
  - Kick: "Kick In"
  - Snare: "Snare"
  - Hi-hat: "HiHat"
  - Toms: "H Tom" for the high (or only) rack tom, "M Tom" for a second rack tom, "Fl Tom" for the floor tom.
  - Overheads: "OH"
  - Percussion: "Perc"
  - Bass: "Bass"
  - Electric guitar: "E Gtr"
  - Acoustic guitar: "Ac Gtr"
  - Keyboardss: "Keys"
  - Piano: "Piano"
  - Trumpet: "Trumpet"
  - Trombone: "T Bone"
  - Alto sax: "A Sax"
  - Baritone sax: "B Sax"
  - Tenor sax: "B Sax"
  - Generic sax "B Sax"
  - Lead and backing vocals: "Vocal"
  - Speech (an MC, host, a podium): "Speech"
  - Playback: no preset. <!-- A line source from a laptop: flat, no gate, no compressor. -->
- The high-pass filter comes from the channel's preset. A channel with no preset gets one by source: horns 100Hz, vocals 120Hz, guitars 80Hz, keys 60Hz, drums 40Hz, bass 50Hz. Playback gets none.
- If the input list names a preset, use that one instead of the defaults above.

## Busses
- Bus order: monitor busses first, then mix busses, then FX busses.
- Monitor busses are White. Mix busses take their category's colour. FX busses are Purple.
- Monitor busses: one per mix on stage, named for who it is for.
  - A wedge mix is a MONO bus. An in-ear (IEM) mix is a STEREO bus.
  - Sends to monitor busses are PRE fader. Only the sends the show's instructions list are switched on, starting at -18dB; every other channel stays out of the mix until soundcheck.
  - Monitor bus faders at -12dB. Never routed to Main. Each one is patched to the output the show's instructions give it.
- Mix busses are STEREO, routed to Main at unity, faders at unity. Channel sends to them are POST fader at unity, and a channel in a mix bus does not also go to Main directly. Every mix bus takes the bus preset "Mix Bus", which carries its compressor. A mix bus with no channel feeds is left out of the plan. <!-- One bus compressor to glue each group; the preset never sets the bus's routing, fader or name. -->
  - "Drums": every drums-category channel.
  - "Horns": every horns-category channel.
  - "Vocals": every vocals-category channel.
- FX busses are STEREO, routed to Main at unity, faders at unity. Each FX bus takes the bus preset of the same name ("Vox Verb", "Snare Verb"), which carries its reverb or delay.
  - "Vox Verb" bus: include every vocals-category channel, POST fader at -6dB.
- Every channel that is in no mix bus goes to Main directly.

## DCAs
- Drums: every drums-category channel.
- Band: bass, guitars, keys and horns.
- Vocals: every vocals-category channel.
- Playback: playback channels, and any aux channel the show adds for music.
- FX: every FX bus.
- DCA faders start at unity.

## Mute Groups
- Band: every drums, bass, guitars, keys and horns channel. <!-- One button between songs. -->
- Vocals: every vocals-category channel.
- FX: every FX bus. <!-- Kill the reverb for talking. -->

## Outputs
- Main 1 is the PA. Name it "PA", patch it to local XLR outputs 1 and 2, fader at unity.

## Watch
- Alert if any mix bus or FX buss is muted, or fader is < -40dB (Low fader) 
- Alert if any active main or matrix bus is muted or fader is < -40dB
- Alert if any active DCA fader < -30dB or muted