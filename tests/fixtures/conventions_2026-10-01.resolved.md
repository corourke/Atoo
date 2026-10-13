<!-- atoo resolved conventions
conventions: conventions.md
conventions_sha256: 35d016b9f72b71f7900cd426c694afee7fc64e0d8e7c95f1199800d8553c9bad
domain_sha256: a9739e66ce1dd8503e359366740aa99ec27da3a49f1b44e850c4ef32c578ad67
prompt_sha256: a3384c019caa59de86f4dcce90ef93f935090fa3b73b5c5b17a88f8036c451ce
model: claude-sonnet-5-5
effort: medium
made: 2026-10-01T05:34:58Z
Made by Atoo from the conventions and the domain knowledge; made again when either changes. Edit the conventions, not this file.
-->

# Resolved conventions (conventions.md)

## Categories

### Drums
- Covers kick, snare, hi hat, rack toms, floor tom, overheads and other percussion. Decided: other percussion is in Drums, so it gets the drum rules, because the kit order places it at the end of the kit. [conventions: "Drum kit order: kick, snare, hi hat, rack toms, floor toms, overheads and then any other percussion."]
- Strip: channel. [conventions: "Patch drums first"]
- Colour: Red. [conventions: "Drums-Red"]
- HPF: 40 Hz. [conventions: "I always want a highpass at 40 Hz on anything in the drums category."]
- DCA: Drums. [conventions: "Drums DCA should include every channel in the drums category."]
- Mute group: Band. Decided: Drums are band instruments. [conventions: "Band: All band instruments"]
- Monitor sends: to MON1-MON4, level all the way down (-144 dB), PRE fader, mute off. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix busses: Drums and Drums Comp, sent at unity (0 dB), POST fader. [conventions: "Sends from channels to these busses should be at unity, POST fader."]
- FX sends: Snare channels only go to Snare Verb (-10 dB, PRE fader). No other drum goes to an FX bus. Drums are excluded from INST Reverb. [conventions: "\"Snare Verb\" -- Snare channels."] [conventions: "All instrument channels (but not drums)"]
- Main routing: only through the Drums and Drums Comp busses, not direct. [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Head-amp gain 20 dB on a mic or DI socket, trim 0 dB, phantom not set. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Overheads: if named OH L / OH R, keep them as two separate mono channels. [conventions: "do NOT patch as a stereo pair, keep as separate mono channels"]

### Bass
- Strip: channel. Colour: Blue. [conventions: "Bass-Blue"]
- HPF: 80 Hz. Decided: bass is a band instrument. [conventions: "Same idea for band instruments, but higher -- 80 Hz is fine."]
- DCA: Band. Bass has no DCA of its own, so it falls under "all other instruments". [conventions: "Band: Include all other instruments not included in one of the DCAs above."]
- Mute group: Band. [conventions: "Band: All band instruments"]
- Monitor sends: to MON1-MON4, down, PRE, mute off. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: none. [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- FX sends: INST Reverb only, level all the way down (-144 dB), POST fader. [conventions: "Set send levels to this buss all the way down, POST fader."]
- Main routing: direct. [conventions: "Send all Channels to the Main L/R bus"]
- Gain 20 dB, trim 0 dB, phantom not set. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]

### Guitars
- Strip: channel. Colour: Magenta. [conventions: "Guitars-Magenta"]
- HPF: 80 Hz. [conventions: "Guitars channels get a high-pass at 80Hz."]
- DCA: Guitars. [conventions: "Guitars: all guitars-category channels"]
- Mute group: Band. [conventions: "Band: All band instruments"]
- Monitor sends: to MON1-MON4, down, PRE, mute off. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: none. FX sends: INST Reverb only, down, POST. [conventions: "Set send levels to this buss all the way down, POST fader."]
- Main routing: direct. [conventions: "Send all Channels to the Main L/R bus"]
- Gain 20 dB, trim 0 dB, phantom not set. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]

### Keyboards
- Strip: channel. Colour: Cyan. [conventions: "Keyboards-Cyan"]
- HPF: 80 Hz. Decided: keyboards are band instruments. [conventions: "Same idea for band instruments, but higher -- 80 Hz is fine."]
- DCA: Keys. [conventions: "Keys: all keys-category channels"]
- Mute group: Band. [conventions: "Band: All band instruments"]
- Monitor sends: to MON1-MON4, down, PRE, mute off. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: "Keys" only if there are two or more keyboard channels. Decided: count channels, so a stereo pair counts as one. [conventions: "If there are multiple keyboards, create a \"Keys\" bus."]
- FX sends: INST Reverb only, down, POST. [conventions: "Set send levels to this buss all the way down, POST fader."]
- Main routing: through the Keys bus if it exists. Otherwise direct. [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Gain 20 dB, trim 0 dB, phantom not set. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]

### Strings
- Strip: channel. Colour: Orange. [conventions: "Strings/Brass-Orange"]
- HPF: 80 Hz. Decided: strings are band instruments, and only horns have their own value. [conventions: "Same idea for band instruments, but higher -- 80 Hz is fine."]
- DCA: Strings. [conventions: "Strings: all strings-category channels"]
- Mute group: Band. [conventions: "Band: All band instruments"]
- Monitor sends: to MON1-MON4, down, PRE, mute off. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: "Strings" only if there are two or more string channels. [conventions: "If there are multiple strings, create a \"Strings\" bus."]
- FX sends: INST Reverb only, down, POST. [conventions: "Set send levels to this buss all the way down, POST fader."]
- Main routing: through the Strings bus if it exists. Otherwise direct. [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Gain 20 dB, trim 0 dB, phantom not set. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]

### Horns
- Brass is the same category as horns. [domain: "\"Horns\" and \"Brass\" generally mean the same thing."]
- Strip: channel. Colour: Orange. [conventions: "Strings/Brass-Orange"]
- HPF: 100 Hz. [conventions: "Horns channels get a high-pass at 100Hz."]
- DCA: Horns. [conventions: "Horns: all horns-category channels"]
- Mute group: Band. [conventions: "Band: All band instruments"]
- Monitor sends: to MON1-MON4, down, PRE, mute off. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: "Horns" only if there are two or more horn channels. [conventions: "If there are multiple horns, create a \"Horns\" bus."]
- FX sends: INST Reverb only, down, POST. [conventions: "Set send levels to this buss all the way down, POST fader."]
- Main routing: through the Horns bus if it exists. Otherwise direct. [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Gain 20 dB, trim 0 dB, phantom not set. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]

### Vocals
- VOX means vocals. Covers singing vocal channels. [domain: "\"VOX\" is shorthand for vocal."]
- Strip: channel. Colour: Green. [conventions: "Vocals-Green"]
- HPF: 120 Hz. [conventions: "Vocals need more low end removed, so put their high-pass up at 120Hz."]
- DCA: Vocals. [conventions: "Vocals: all vocals-category channels"]
- Mute group: Vocals. [conventions: "Vocals: All (singing) vocal channels"]
- Monitor sends: to MON1-MON4, down, PRE, mute off. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: Vocals, at unity, POST. [conventions: "\"Vocals\": include all vocal channels."]
- FX sends: VOX Reverb and VOX Delay at unity (0 dB), POST. No INST Reverb. [conventions: "\"VOX Reverb\" -- All vocal channels"] [conventions: "\"VOX Delay\" -- All vocal channels"]
- Main routing: only through the Vocals bus, not direct. [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Gain 20 dB, trim 0 dB, phantom not set. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]

### Tracks
- The band's own backing tracks and "trax". They go on regular channels, mono or stereo, one or many. [domain: "belong on **regular channels** where"]
- Strip: channel. Colour: Yellow. [conventions: "Tracks/Plaback-Yellow"]
- HPF: none. [conventions: "Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send."]
- DCA: Tracks. [conventions: "Tracks: all tracks- or trax- category channels"]
- Mute group: none. [conventions: "no Band mute group"]
- Monitor sends: to MON1-MON4, down, PRE, mute off. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: none. FX sends: none, including no INST Reverb. [conventions: "no INST Reverb send"]
- Main routing: direct. [conventions: "Send all Channels to the Main L/R bus"]
- Gain 20 dB on a mic or line socket. A digital source has no gain set. Trim 0 dB, phantom not set. [domain: "arrives already levelled and has no head amp and no phantom"] [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]

### Click/guide
- Decided: a row whose category or name is click or guide is its own category. It takes the Tracks values except for Main routing, because click and guide are for the musicians only. [domain: "must never be routed to the main mix, only to monitor busses"]
- Strip: channel. Colour: Yellow. HPF: none. DCA: Tracks. Mute group: none. [conventions: "Tracks/Plaback-Yellow"] [conventions: "Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send."]
- Monitor sends: to MON1-MON4, down, PRE, mute off. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: none. FX sends: none. [conventions: "no INST Reverb send"]
- Main routing: NOT sent to Main, and in no mix bus, so it reaches only the monitor busses. Decided: this exception overrides the send-to-Main line. [domain: "must never be routed to the main mix, only to monitor busses"]
- Gain 20 dB on a mic or line socket, none on a digital source. Trim 0 dB, phantom not set. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]

### Speech
- Hosts, MCs, podium mics, presenters, pastors and speakers. Not part of the band. [domain: "\"Host\" or \"MC\" or \"Podium\" or \"Pastor\" or \"Speaker\" are all spoken word or speech inputs."]
- Strip: regular channel. [conventions: "One exception is speech, those inputs should get a regular channel."]
- Exception: the HOST mic is on aux strip Aux 2 (see Misc). Decided: the specific Aux 2 line beats the general regular-channel line, and every other speech row gets a regular channel. [conventions: "Setup HOST mic on Aux 2, Preset \"Host CO2\", Source LCL 20."]
- Colour: Purple. [conventions: "Speech-Purple"]
- HPF: 120 Hz on speech channels. The HOST aux strip has none. [conventions: "Speech channels get a high-pass at 120Hz, like vocals."] [domain: "An aux strip has no high-pass filter"]
- DCA: Speech. Decided: the HOST aux is a member too. [conventions: "Speech: Hosts, MCs, Podium Mics, Presenters, Pastors, etc."]
- Mute group: Speech. [conventions: "Speech: All speech channels"]
- Monitor sends: none. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: none. FX sends: none. Decided: no rule gives speech an FX send. [conventions: "\"VOX Reverb\" -- All vocal channels"]
- Main routing: direct. [conventions: "Send all Channels to the Main L/R bus"]
- Gain 20 dB, trim 0 dB, phantom not set. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]

### Misc (aux strips)
- Background music and any source that is not part of the band go on aux strips. Misc is judged by what the source is, not treated as automatically aux. [conventions: "Any inputs that are for background music, or any audio source that is not a part of the band should be placed on an Aux channel."] [domain: "Do not treat\n\"misc\" as automatically meaning aux"]
- Decided: a misc row that is a band element (backing track, click) is Tracks or Click/guide. A misc row that is an external feed goes on an aux strip, because that is what the domain separates. [domain: "belong on **aux input strips**"]
- Strip: aux. HPF: none. [domain: "An aux strip has no high-pass filter"]
- Colour: not set. Decided: no rule gives it one. HOST is Purple because it is speech. [conventions: "Use same color coding for channels as the sources."]
- DCA: none, except HOST, which is in Speech. Mute group: none, except HOST, which is in Speech. [conventions: "Speech: Hosts, MCs, Podium Mics, Presenters, Pastors, etc."]
- Monitor sends: only TALKBACK sends to MON1-MON4 (down, PRE, mute off). Decided: aux strips are not "channels", but talkback is for the stage, so only it gets sends. [conventions: "Every channel except speech sends to every monitor bus."]
- Mix bus: none. FX sends: none.
- Main routing: MUSIC and HOST direct. TALKBACK not to Main. Decided: talkback is for the stage, and the others are for the house. [domain: "All channels need a path to the final output"]
- Gain 20 dB and trim 0 dB on aux strips patched to a physical socket, phantom not set. Decided: the default is applied literally. [conventions: "Unless overridden by the show instructions, set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Aux 1 "MUSIC": source LCL 23-24, stereo (LCL 23+24 is a legal odd-first pair). Decided: stereo link. [conventions: "Setup a MUSIC playback on Aux 1, source LCL 23-24."] [domain: "1+2, 15+16, 23+24. Never 2+3, never 1+5."]
- Aux 2 "HOST": preset "Host CO2", source LCL 20, mono. [conventions: "Setup HOST mic on Aux 2, Preset \"Host CO2\", Source LCL 20."]
- Aux 8 "TALKBACK": source LCL 22 if available. Decided: "available" means no input-list row is patched to LCL 22. If one is, still create Aux 8 and leave its source unpatched. [conventions: "Setup TALKBACK on Aux 8, source LCL 22 if available."]

### Band (grouping word)
- Decided: for the Band DCA and the Band mute group, "band" means instruments only: drums, bass, guitars, keyboards, strings, horns and any other band instrument. It excludes vocals and tracks, which have their own groups. [domain: "\"Band\" usually means all instruments"] [conventions: "Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send."]
- Decided: a band-instrument row in a category not named here goes in the Band DCA and Band mute group, gets HPF 80 Hz, and goes direct to Main. Its colour is not set. [conventions: "Band: Include all other instruments not included in one of the DCAs above."]

### Instruments (grouping word)
- Excludes vocals and tracks. For INST Reverb, "instrument channels" are bass, guitars, keyboards, strings, horns and other band instruments, but not drums. [domain: "\"Instruments\" normally does not include the vocals or backing tracks."] [conventions: "\"INST Reverb\" -- All instrument channels (but not drums)."]

## Busses

Order on the console: monitor busses, then mix busses, then FX busses. [conventions: "Setup the bus ordering with monitor busses first, then mix busses then FX busses."]

Decided: a mix or FX bus is created only if it has at least one sending channel, like the DCA rule, because an empty bus does nothing. [conventions: "Create a DCA for the following instrument groupings if there is at least one member."]

**Monitor busses**
- MON1, MON2, MON3, MON4: mono. [conventions: "Create four monitor busses, named 'MON1' thru 'MON4', these will all be MONO busses."]
- Destination: local XLR outputs 1, 2, 3, 4 respectively, unless the show says otherwise. Not patched to Main. [conventions: "Patch output to local XLR outputs 1 through 4 if not specified otherwise."] [conventions: "Do not patch to main."]
- Fader: all the way down (-144 dB). [conventions: "Leave bus faders all the way down."]
- Senders: every channel except speech, plus the TALKBACK aux. Level all the way down (-144 dB), mute off, mode PRE. [conventions: "Leave those sends all the way down, mute off, mode is PRE fader."]

**Mix busses**: stereo, patched to Main mix POST fader at unity, bus fader at unity (0 dB), sends at unity POST fader. [conventions: "Mix Busses. These are stereo busses. Patch all to Main mix, POST fader at unity. Bus faders at unity. Sends from channels to these busses should be at unity, POST fader."]
- Drums: stereo. Senders: all channels in the Drums category. [conventions: "Drums: include all drum channels, and it feeds the main mix."]
- Drums Comp: stereo. Senders: the same channels as Drums. Fader -6 dB. Compressor "No Stressor", threshold -20 dB, attack 20 ms, release 50 ms. Ratio and other compressor settings are not set. [conventions: "\"Drums Comp\": Compressed drums. A duplicate of the Drums bus, but with heavy compression added."] [conventions: "Leave the fader pulled down 6dB."]
- Vocals: stereo. Senders: all Vocals channels. [conventions: "\"Vocals\": include all vocal channels."]
- Keys: stereo. Created only if there are 2 or more keyboard channels. Senders: the Keyboards channels. [conventions: "If there are multiple keyboards, create a \"Keys\" bus."]
- Horns: stereo. Created only if there are 2 or more horn channels. Senders: the Horns channels. [conventions: "If there are multiple horns, create a \"Horns\" bus."]
- Strings: stereo. Created only if there are 2 or more string channels. Senders: the Strings channels. [conventions: "If there are multiple strings, create a \"Strings\" bus."]

**FX busses**: stereo, sent to Main at unity POST fader, bus fader at unity (0 dB). Sends are unity POST fader unless noted. [conventions: "FX Busses. These are stereo busses. Create the following FX busses and send them to Main at unity, post fader. Fader at unity. Sends to these busses are generally at unity, POST fader, unless noted below."]
- VOX Reverb: senders are all Vocals channels, at 0 dB, POST. [conventions: "\"VOX Reverb\" -- All vocal channels"]
- VOX Delay: senders are all Vocals channels, at 0 dB, POST. [conventions: "\"VOX Delay\" -- All vocal channels"]
- Snare Verb: senders are the snare channels, at -10 dB, PRE fader. [conventions: "\"Snare Verb\" -- Snare channels. Sends from channels at -10db, PRE fader."]
- INST Reverb: senders are all instrument channels (not drums, vocals or tracks), at -144 dB, POST. [conventions: "\"INST Reverb\" -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader."]
- Decided: the send mode is POST as the conventions say, not the GRP mode the domain describes as typical. [domain: "Generally the channel send mode is GRP"]

## Outputs

- Main: the full mix. It has no physical output of its own and feeds only Matrix 1. [conventions: "Main should be the full mix. Send to Matrix 1. Main has no physical output of its own; it only feeds Matrix 1."]
- Matrix 1: fed from Main. Patched to internal XLR outputs 7 and 8. Decided: "internal XLRs" means the local XLR outputs, so Matrix 1 L is on 7 and R on 8. [conventions: "Matrix 1 takes its feed from Main. Patch output to internal XLRs 7 and 8."] [domain: "\"XLR outputs\" or \"the XLRs\" normally means the console's local outputs."]
- Matrix 1 is stereo, because it feeds a pair of sockets. [domain: "a bus patched to a socket pair is stereo"]
- Monitor busses go to local XLR outputs 1-4 and never to Main or the Matrix. [conventions: "Patch output to local XLR outputs 1 through 4 if not specified otherwise."]
- Every channel except click/guide reaches Main directly or through a mix bus. Click/guide reaches only the monitor busses. [domain: "All channels need a path to the final output, either to the Main L/R bus or included in one of the mix busses."]

## DCAs

All created DCAs start with the fader at unity (0 dB). A DCA with no members is not created. DCAs are remote controls only and make no signal path. [conventions: "Create a DCA for the following instrument groupings if there is at least one member. All created DCAs should start with fader at unity."]
- Drums: every channel in the Drums category. [conventions: "Drums DCA should include every channel in the drums category."]
- Guitars: all Guitars channels. [conventions: "Guitars: all guitars-category channels"]
- Keys: all Keyboards channels. [conventions: "Keys: all keys-category channels"]
- Vocals: all Vocals channels. [conventions: "Vocals: all vocals-category channels"]
- Tracks: all Tracks and click/guide channels. [conventions: "Tracks: all tracks- or trax- category channels"]
- Strings: all Strings channels. [conventions: "Strings: all strings-category channels"]
- Horns: all Horns channels. [conventions: "Horns: all horns-category channels"]
- Band: bass and every other instrument not in a DCA above. [conventions: "Band: Include all other instruments not included in one of the DCAs above."]
- Speech: the speech channels and the HOST aux. [conventions: "Speech: Hosts, MCs, Podium Mics, Presenters, Pastors, etc."]
- FX: all created FX busses (VOX Reverb, VOX Delay, Snare Verb, INST Reverb). [conventions: "FX should include all the effects return busses."]
- DCAs do not satisfy the need for a signal path. [domain: "DCAs, while assigned to channels in a similar manner to a bus, do NOT create a signal path"]

## Mute groups

Decided: a mute group with no members is not created, matching the DCA rule. [conventions: "Create a DCA for the following instrument groupings if there is at least one member."]
- Band: all band instruments, meaning drums, bass, guitars, keyboards, strings, horns and other instruments. It excludes vocals, speech and tracks. [conventions: "Band: All band instruments"] [conventions: "no Band mute group"]
- Vocals: all singing vocal channels. [conventions: "Vocals: All (singing) vocal channels"]
- Speech: all speech channels, including the HOST aux. [conventions: "Speech: All speech channels"]
- FX: all created FX busses. [conventions: "FX: All FX busses"]

## Head amps

- Mic or DI on a physical socket: gain 20 dB, trim 0 dB, phantom not set. Decided: the conventions never mention 48V, so phantom comes only from the input list or show instructions. [conventions: "Unless overridden by the show instructions, set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Digital source (USB, card, player): gain and phantom not set, trim 0 dB. [domain: "arrives already levelled and has no head amp and no phantom"] [domain: "Trim applies to every channel."]
- Aux strip on a physical socket (MUSIC, HOST, TALKBACK): gain 20 dB, trim 0 dB, phantom not set. Decided: see Misc. [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- A value in the show instructions or input list overrides these defaults. [conventions: "Unless overridden by the show instructions"]

## Patching and channel order

- A row with a socket in the input list is patched there. [conventions: "Patch input sockets according to the supplied input list."]
- A row with no socket takes the next free local input in channel order, up to local 24. After that it goes to AES50-A starting at 1, then 2, and so on. [conventions: "If the input list gives no socket for a row, patch in channel order to local inputs 1-24, then overflow to AES50-A from 1."]
- Decided: "next free" skips sockets the input list uses and local 20, 22, 23 and 24, which the aux strips use. This stops two sources sharing a socket. [conventions: "Setup a MUSIC playback on Aux 1, source LCL 23-24."] [domain: "treat it as the mistake"]
- Stereo pairing: two sequential non-overhead rows marked as a stereo pair (L/R, Left/Right) become one stereo channel, patched at the first socket. This covers vocals and tracks too. [conventions: "For instruments other than overheads, if two sequential inputs are marked as stereo pair (L/R, Left/Right), patch as one stereo channel."]
- Overheads named L/R are never paired: two mono channels. [conventions: "do NOT patch as a stereo pair, keep as separate mono channels"]
- A pair needs consecutive sockets starting on an odd one. Decided: for an unpatched pair, skip to the next free odd socket with the next one free (a skipped socket stays empty). If that would pass local 24, start the pair at an odd AES50-A socket. [domain: "1+2, 15+16, 23+24. Never 2+3, never 1+5."]
- Decided: if the input list puts a pair on non-adjacent or even-first sockets, use a user patch to make it legal. The input list's sockets stay as given. [domain: "A **user patch** takes a physical jack directly"]
- Channel order:
  1. Drums, in the kit order below. [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."]
  2. Bass.
  3. Guitars.
  4. Keyboards.
  5. Strings, then horns. Decided: strings before horns, following "strings or brass".
  6. Vocals.
  7. Tracks, with click and guide last among them. Decided: backing tracks first.
  8. Speech channels (speakers).
  9. Anything else.
- Kit order: kick, snare, hi hat, rack toms, floor tom, overheads, then other percussion. [conventions: "Drum kit order: kick, snare, hi hat, rack toms, floor toms, overheads and then any other percussion."]
- Toms: the lower-numbered ones are rack toms. The highest-numbered is the floor tom. There is only one floor tom unless the input list says more. [conventions: "The lower-numbered toms are rack toms. There is almost always only one floor tom (the highest number); if there were more, the input list would say so."]
- Colour follows the category. [conventions: "Use same color coding for channels as the sources."]
- Colour table: Drums Red, Bass Blue, Guitars Magenta, Keyboards Cyan, Strings and Brass Orange, Vocals Green, Tracks Yellow, Speech Purple. [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]

## Faders

- Every channel and aux strip: all the way down (-144 dB). [conventions: "Leave all faders all the way down."] [domain: "WING's floor is exactly -144"]
- Monitor busses MON1-MON4: -144 dB. [conventions: "Leave bus faders all the way down."]
- Mix busses: 0 dB, except Drums Comp at -6 dB. [conventions: "Bus faders at unity."] [conventions: "Leave the fader pulled down 6dB."]
- FX busses: 0 dB. [conventions: "Fader at unity."]
- DCAs: 0 dB. [conventions: "All created DCAs should start with fader at unity."]
- Main and Matrix 1: 0 dB. Decided: the blanket "all faders down" is for channels, since an output at -144 dB would silence the show. [conventions: "Main should be the full mix."]
- Sends: monitor sends -144 dB PRE. Mix-bus sends 0 dB POST. VOX Reverb and VOX Delay sends 0 dB POST. Snare Verb sends -10 dB PRE. INST Reverb sends -144 dB POST. [conventions: "Leave those sends all the way down, mute off, mode is PRE fader."] [conventions: "Sends from channels at -10db, PRE fader."]

## Lines with no effect

- None. Every non-heading line of the conventions yields a rule above.

## Category table

```json
[
  {"name": "Drums", "aliases": ["drums", "drum", "percussion", "perc"], "color": "Red", "hpf_hz": 40, "dca": ["Drums"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Bass", "aliases": ["bass"], "color": "Blue", "hpf_hz": 80, "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Guitars", "aliases": ["guitars", "guitar", "gtr", "gtrs"], "color": "Magenta", "hpf_hz": 80, "dca": ["Guitars"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Keyboards", "aliases": ["keyboards", "keyboard", "keys", "key"], "color": "Cyan", "hpf_hz": 80, "dca": ["Keys"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144},
  {"name": "Strings", "aliases": ["strings", "string"], "color": "Orange", "hpf_hz": 80, "dca": ["Strings"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144},
  {"name": "Horns", "aliases": ["horns", "horn", "brass"], "color": "Orange", "hpf_hz": 100, "dca": ["Horns"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144},
  {"name": "Vocals", "aliases": ["vocals", "vocal", "vox", "vocalist", "vocalists"], "color": "Green", "hpf_hz": 120, "dca": ["Vocals"], "mute_group": ["Vocals"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Tracks", "aliases": ["tracks", "track", "trax", "playback", "backing"], "color": "Yellow", "hpf_hz": null, "dca": ["Tracks"], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Click/guide", "aliases": ["click", "guide", "click/guide", "click track", "guide track"], "color": "Yellow", "hpf_hz": null, "dca": ["Tracks"], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Speech", "aliases": ["speech", "host", "mc", "podium", "pastor", "speaker", "speakers", "presenter"], "color": "Purple", "dca": ["Speech"], "mute_group": ["Speech"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Misc", "aliases": ["misc", "aux", "background music", "music", "external"], "color": null, "hpf_hz": null, "gain_db": 20, "trim_db": 0, "fader_db": -144}
]
```
