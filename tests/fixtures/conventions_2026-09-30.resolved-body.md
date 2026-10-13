## Categories

### Drums
- Strip kind: regular channel (part of the band, patched among channels, not aux) [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."] [conventions: "Any inputs that are for background music, or any audio source that is not a part of the band should be placed on an Aux channel."]
- Colour: Red [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"] [conventions: "Use same color coding for channels as the sources."]
- HPF: 40 Hz [conventions: "I always want a highpass at 40 Hz on anything in the drums category."]
- DCA: Drums DCA [conventions: "Drums DCA should include every channel in the drums category."]
- Mute group: Band [conventions: "Band: All band instruments"] [domain: "\"Instruments\" normally does not include the vocals or backing tracks."]
- Monitor sends: all four MON busses, level all the way down, mute off, PRE fader [conventions: "Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader."]
- Mix-bus membership: Drums bus and Drums Comp bus [conventions: "Drums: include all drum channels, and it feeds the main mix."] [conventions: "\"Drums Comp\": Compressed drums. A duplicate of the Drums bus, but with heavy compression added."]
- FX sends: Snare channels only go to Snare Verb, at -10dB, PRE fader; no drum channel gets INST Reverb [conventions: "'Snare Verb' -- Snare channels. Sends from channels at -10db, PRE fader."] [conventions: "'INST Reverb' -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader."]
- Main routing: not sent directly to Main; reaches Main only through the Drums / Drums Comp busses [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Head-amp gain: 20dB [conventions: "Unless overridden by the show instructions, set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Trim: 0dB [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."] [domain: "Trim applies to every channel."]
- Phantom: Decided - off by default, engaged only where the input list specifies a mic/DI needing 48V; neither document sets a default [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Bass
- Strip kind: regular channel [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."]
- Colour: Blue [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]
- HPF: 80 Hz (band instrument, no bass-specific override) [conventions: "Same idea for band instruments, but higher -- 80 Hz is fine."]
- DCA: none dedicated; falls into the Band DCA catch-all, since no "Bass" DCA is listed [conventions: "Band: Include all other instruments not included in one of the DCAs above."]
- Mute group: Band [conventions: "Band: All band instruments"] [domain: "\"Instruments\" normally does not include the vocals or backing tracks."]
- Monitor sends: all four MON busses, all the way down, mute off, PRE fader [conventions: "Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader."]
- Mix-bus membership: none (no Bass mix bus is defined) - routes straight to Main [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- FX sends: INST Reverb (it is an instrument channel, not drums), send fully down, POST fader [conventions: "'INST Reverb' -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader."]
- Main routing: direct to Main L/R [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Head-amp gain: 20dB / Trim: 0dB [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Phantom: Decided - off by default, engaged per input list where needed [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Guitars
- Strip kind: regular channel [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."]
- Colour: Magenta [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]
- HPF: 80 Hz [conventions: "Guitars channels get a high-pass at 80Hz."]
- DCA: Guitars DCA [conventions: "Guitars: all guitars-category channels"]
- Mute group: Band [conventions: "Band: All band instruments"]
- Monitor sends: all four MON busses, all the way down, mute off, PRE fader [conventions: "Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader."]
- Mix-bus membership: none (no Guitars mix bus is defined) [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- FX sends: INST Reverb, send fully down, POST fader [conventions: "'INST Reverb' -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader."]
- Main routing: direct to Main L/R [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Head-amp gain: 20dB / Trim: 0dB [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Phantom: Decided - off by default, per-input-list otherwise [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Keyboards
- Strip kind: regular channel [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."]
- Colour: Cyan [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]
- HPF: 80 Hz (band instrument, no keyboard-specific override) [conventions: "Same idea for band instruments, but higher -- 80 Hz is fine."]
- DCA: Keys DCA [conventions: "Keys: all keys-category channels"]
- Mute group: Band [conventions: "Band: All band instruments"]
- Monitor sends: all four MON busses, all the way down, mute off, PRE fader [conventions: "Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader."]
- Mix-bus membership: "Keys" bus, only if the input list shows more than one keyboard channel; otherwise none [conventions: "If there are multiple keyboards, create a 'Keys' bus."]
- FX sends: INST Reverb, send fully down, POST fader [conventions: "'INST Reverb' -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader."]
- Main routing: direct to Main if no Keys bus exists; through the Keys bus (POST fader, unity, to Main) if it does [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."] [conventions: "Patch all to Main mix, POST fader at unity."]
- Head-amp gain: 20dB / Trim: 0dB [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Phantom: Decided - off by default, per-input-list otherwise [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Strings
- Strip kind: regular channel [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."]
- Colour: Orange (shared with Horns/Brass) [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]
- HPF: 80 Hz (band instrument; strings get no HPF override, unlike Horns) [conventions: "Same idea for band instruments, but higher -- 80 Hz is fine."]
- DCA: Strings DCA [conventions: "Strings: all strings-category channels"]
- Mute group: Band [conventions: "Band: All band instruments"]
- Monitor sends: all four MON busses, all the way down, mute off, PRE fader [conventions: "Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader."]
- Mix-bus membership: "Strings" bus, only if the input list shows more than one strings channel; otherwise none [conventions: "If there are multiple strings, create a 'Strings' bus."]
- FX sends: INST Reverb, send fully down, POST fader [conventions: "'INST Reverb' -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader."]
- Main routing: direct to Main if no Strings bus; via the Strings bus otherwise [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Head-amp gain: 20dB / Trim: 0dB [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Phantom: Decided - off by default, per-input-list otherwise [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Horns/Brass
- Strip kind: regular channel [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."]
- Colour: Orange (shared with Strings) [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"] [domain: "\"Horns\" and \"Brass\" generally mean the same thing."]
- HPF: 100 Hz (specific override, higher than the generic band-instrument 80Hz) [conventions: "Horns channels get a high-pass at 100Hz."]
- DCA: Horns DCA [conventions: "Horns: all horns-category channels"]
- Mute group: Band [conventions: "Band: All band instruments"]
- Monitor sends: all four MON busses, all the way down, mute off, PRE fader [conventions: "Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader."]
- Mix-bus membership: "Horns" bus, only if the input list shows more than one horn channel; otherwise none [conventions: "If there are multiple horns, create a 'Horns' bus."]
- FX sends: INST Reverb, send fully down, POST fader [conventions: "'INST Reverb' -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader."]
- Main routing: direct to Main if no Horns bus; via the Horns bus otherwise [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Head-amp gain: 20dB / Trim: 0dB [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Phantom: Decided - off by default, per-input-list otherwise [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Vocals
- Strip kind: regular channel [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."]
- Colour: Green [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]
- HPF: 120 Hz [conventions: "Vocals need more low end removed, so put their high-pass up at 120Hz."]
- DCA: Vocals DCA [conventions: "Vocals: all vocals-category channels"]
- Mute group: Vocals [conventions: "Vocals: All (singing) vocal channels"]
- Monitor sends: all four MON busses, all the way down, mute off, PRE fader [conventions: "Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader."]
- Mix-bus membership: Vocals bus (always created, unconditional) [conventions: "'Vocals': include all vocal channels."]
- FX sends: VOX Reverb and VOX Delay (unity, POST fader, since not noted otherwise); not sent to INST Reverb (vocals are not "instrument channels") [conventions: "'VOX Reverb' -- All vocal channels"] [conventions: "'VOX Delay' -- All vocal channels"] [domain: "\"Instruments\" normally does not include the vocals or backing tracks."]
- Main routing: via the Vocals bus (POST fader, unity, to Main) [conventions: "Patch all to Main mix, POST fader at unity."]
- Head-amp gain: 20dB / Trim: 0dB [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Phantom: Decided - off by default, per-input-list otherwise [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Tracks/Playback (the band's own tracks, excluding Click/Guide)
- Strip kind: regular channel; may be mono or stereo, one or many [conventions: "Any inputs that are for background music, or any audio source that is not a part of the band should be placed on an Aux channel."] [domain: "belong on **regular channels** where possible. They may be mono or stereo, and there may be one or many. Do not assume a single stereo pair."]
- Colour: Yellow [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]
- HPF: none [conventions: "Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send."]
- DCA: Tracks DCA [conventions: "Tracks: all tracks- or trax- category channels"] [domain: "\"Tracks\" or \"trax\" means the band's own backing tracks (see \"Playback and tracks\" above)."]
- Mute group: Decided - none; explicitly excluded from Band, and matches no other listed mute group [conventions: "Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send."]
- Monitor sends: all four MON busses, all the way down, mute off, PRE fader (tracks are channels, and only speech is excluded) [conventions: "Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader."]
- Mix-bus membership: none defined for tracks [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- FX sends: none - explicitly no INST Reverb, and not a vocal or snare channel [conventions: "Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send."]
- Main routing: direct to Main L/R [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Head-amp gain: Decided - 20dB only if the source is a physical mic/line/DI input; if the source is a digital player/USB/card feed, gain does not apply (no head amp) [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."] [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]
- Trim: 0dB regardless of source [domain: "Trim applies to every channel."]
- Phantom: none if digital; Decided off-by-default if physical [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Click/Guide
- Strip kind: regular channel (a sub-type of the band's own tracks) [domain: "If there are multiple track channels, there may be a channel called click, or guide, or a combination of the two -- these tracks must never be routed to the main mix, only to monitor busses. Click and Guide are for the musicians on stage only."]
- Colour: Yellow (same as Tracks/Playback) [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]
- HPF: none (tracks rule applies) [conventions: "Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send."]
- DCA: Tracks DCA [conventions: "Tracks: all tracks- or trax- category channels"]
- Mute group: none (same reasoning as Tracks/Playback) [conventions: "Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send."]
- Monitor sends: all four MON busses, all the way down, mute off, PRE fader [conventions: "Every channel except speech sends to every monitor bus. Leave those sends all the way down, mute off, mode is PRE fader."] [domain: "these tracks must never be routed to the main mix, only to monitor busses. Click and Guide are for the musicians on stage only."]
- Mix-bus membership: none [domain: "these tracks must never be routed to the main mix"]
- FX sends: none [conventions: "no INST Reverb send"]
- Main routing: none - explicitly excluded from Main, overriding the general "send all channels to Main" default [domain: "these tracks must never be routed to the main mix, only to monitor busses."]
- Head-amp gain: Decided - as Tracks/Playback, 20dB if physical, not applicable if digital [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."] [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]
- Trim: 0dB [domain: "Trim applies to every channel."]
- Phantom: none if digital; Decided off-by-default if physical [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Speech
- Strip kind: regular channel (explicit exception to the Aux rule) [conventions: "One exception is speech, those inputs should get a regular channel."]
- Colour: Purple [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]
- HPF: 120 Hz [conventions: "Speech channels get a high-pass at 120Hz, like vocals."]
- DCA: Speech DCA [conventions: "Speech: Hosts, MCs, Podium Mics, Presenters, Pastors, etc."] [domain: "\"Host\" or \"MC\" or \"Podium\" or \"Pastor\" or \"Speaker\" are all spoken word or speech inputs. They are almost never a part of the band."]
- Mute group: Speech [conventions: "Speech: All speech channels"]
- Monitor sends: none - speech is the one explicit exception [conventions: "Every channel except speech sends to every monitor bus."]
- Mix-bus membership: none defined for speech [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- FX sends: Decided - none; speech is neither a vocal, snare, nor instrument channel, so it qualifies for none of the FX busses [domain: "\"Host\" or \"MC\" or \"Podium\" or \"Pastor\" or \"Speaker\" are all spoken word or speech inputs. They are almost never a part of the band."] [domain: "\"Instruments\" normally does not include the vocals or backing tracks."]
- Main routing: direct to Main L/R [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Head-amp gain: 20dB / Trim: 0dB [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Phantom: Decided - off by default, per-input-list otherwise [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Misc / External Feeds (background music, video/laptop/phone audio, anything not part of the band or speech)
- Strip kind: Aux [conventions: "Any inputs that are for background music, or any audio source that is not a part of the band should be placed on an Aux channel."]
- Colour: Decided - none assigned; the colour list covers only band and speech categories, and "misc" must be judged by source, not assumed [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"] [domain: "The word \"misc\" on an input list often covers both kinds. Do not treat \"misc\" as automatically meaning aux -- look at what the source actually is."]
- HPF: none - aux strips have no filter node at all [domain: "An aux strip has no high-pass filter (no `flt` node at all on WING), which is usually fine for a line-level feed and would not be fine for a source you intended to process."]
- DCA: Decided - none; no listed DCA grouping covers non-band, non-speech sources [conventions: "Create a DCA for the following instrument grouping if there is at least one member:"]
- Mute group: Decided - none; no listed mute group covers non-band, non-speech sources [conventions: "Band: All band instruments"] [conventions: "Speech: All speech channels"]
- Monitor sends: Decided - none; the monitor-send rule names "channel", and an aux strip is a distinct strip kind from a channel [conventions: "Every channel except speech sends to every monitor bus."] [domain: "generally belong on **aux input strips**."]
- Mix-bus membership: none (no mix bus admits non-band sources) [conventions: "Drums: include all drum channels, and it feeds the main mix."]
- FX sends: none (no FX bus admits non-band, non-speech sources) [conventions: "'INST Reverb' -- All instrument channels (but not drums)."]
- Main routing: Decided - direct to Main L/R, since every input needs a path to the final output and no mix bus applies [domain: "All channels need a path to the final output, either to the Main L/R bus or included in one of the mix busses."]
- Head-amp gain: Decided - 20dB if fed from a physical line input; not applicable if fed from a digital source (USB/media player/card) [conventions: "set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."] [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]
- Trim: 0dB regardless of source [domain: "Trim applies to every channel."]
- Phantom: none if digital; Decided off-by-default if physical [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]

### Band
- Covers all instruments (drums, bass, guitars, keyboards, any strings or brass) plus the vocals and any backing tracks - the whole of the music [domain: "\"Band\" usually means all instruments (drums, bass, guitars, keyboards, and any strings or brass) plus the vocals and any backing tracks -- everything that makes up the music."]
- Governs the Aux-vs-regular-channel split: anything in the band gets a regular channel; speech is the one non-band exception that still gets a regular channel; everything else non-band goes to Aux [conventions: "Any inputs that are for background music, or any audio source that is not a part of the band should be placed on an Aux channel. One exception is speech, those inputs should get a regular channel."]
- The "Band" DCA and "Band" mute group are named for this term but in practice hold only the *instrument* subset (drums, bass, guitars, keys, strings, horns) - vocals and tracks are pulled out into their own DCA/mute groups instead [conventions: "Band: Include all other instruments not included in one of the DCAs above."] [conventions: "Band: All band instruments"] [domain: "\"Instruments\" normally does not include the vocals or backing tracks."]
- Strip kind / colour / HPF / DCA / mute group / monitor sends / mix-bus membership / FX sends / Main routing / gain / trim / phantom: not applicable - "Band" is a grouping term, not a strip; see each member category above [domain: "These are conventions, not laws. An input list defines its own categories, and the conventions file has to be read against *that* list rather than against an assumed vocabulary."]

### Instruments
- Covers drums, bass, guitars, keyboards, strings, and horns/brass; excludes vocals and backing tracks [domain: "\"Instruments\" normally does not include the vocals or backing tracks."]
- Governs the Band mute group ("All band instruments") and the Band DCA catch-all ("Include all other instruments not included in one of the DCAs above") - both mean this instruments set, minus whichever already has its own dedicated DCA [conventions: "Band: All band instruments"] [conventions: "Band: Include all other instruments not included in one of the DCAs above."]
- Governs INST Reverb membership: "All instrument channels (but not drums)" [conventions: "'INST Reverb' -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader."]
- Decided - any band instrument that does not match one of the eight named colours (e.g. an extra percussion or other instrument the input list doesn't name a colour for): patched last, per the stated channel order; gets no colour (none of the eight defined colours apply); joins the Band DCA and Band mute group as an "other instrument"; sends to all four monitor busses; receives the INST Reverb send; routes to Main directly; takes the default 20dB gain / 0dB trim like any physical channel [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."] [conventions: "Band: Include all other instruments not included in one of the DCAs above."] [domain: "These are conventions, not laws. An input list defines its own categories, and the conventions file has to be read against *that* list rather than against an assumed vocabulary."]
- Strip kind / colour / etc. otherwise not applicable at this grouping level; see each member category above [domain: "These are conventions, not laws."]

## Busses

Creation order: monitor busses, then mix busses, then FX busses [conventions: "Setup the bus ordering with monitor busses first, then mix busses then FX busses."]

**Monitor busses (MON1-MON4)**
- Names: MON1, MON2, MON3, MON4 [conventions: "Create four monitor busses, named 'MON1' thru 'MON4', these will all be MONO busses."]
- Width: mono, each [conventions: "these will all be MONO busses."]
- Destination: local XLR outputs 1-4, unless a specific show overrides it [conventions: "Patch output to local XLR outputs 1 through 4 if not specified otherwise."]
- Not patched to Main [conventions: "Do not patch to main."]
- Bus fader: fully down [conventions: "Leave bus faders all the way down."]
- Senders: every channel except speech [conventions: "Every channel except speech sends to every monitor bus."]
- Send level: fully down, mute off, mode PRE fader [conventions: "Leave those sends all the way down, mute off, mode is PRE fader."]
- These are ordinary busses re-purposed as monitor mixes, not a distinct object type [domain: "There is no separate \"monitor bus\" object on a WING at all."]

**Mix busses**
- Width: stereo, all of them [conventions: "These are stereo busses."]
- Destination: Main mix, POST fader, unity [conventions: "Patch all to Main mix, POST fader at unity."]
- Bus fader: unity [conventions: "Bus faders at unity."]
- Sends from channels: unity, POST fader [conventions: "Sends from channels to these busses should be at unity, POST fader."]
- Drums: all drum channels; feeds Main [conventions: "Drums: include all drum channels, and it feeds the main mix."]
- Drums Comp: a duplicate of the Drums bus with heavy compression - "No Stressor" compressor at -20dB threshold, 20ms attack, 50ms release; bus fader pulled down 6dB from its unity start [conventions: "'Drums Comp': Compressed drums. A duplicate of the Drums bus, but with heavy compression added. (Start with the 'No Stressor' compressor at -20dB threshold, attack 20ms, release 50ms). Leave the fader pulled down 6dB."] [domain: "\"Pull the fader down 6dB\" is a statement about the strip, even when it appears in the same sentence as compressor settings."]
- Vocals: all vocal channels; always created [conventions: "'Vocals': include all vocal channels."]
- Keys: created only if the input list shows multiple keyboard channels [conventions: "If there are multiple keyboards, create a 'Keys' bus."]
- Horns: created only if the input list shows multiple horn channels [conventions: "If there are multiple horns, create a 'Horns' bus."]
- Strings: created only if the input list shows multiple strings channels [conventions: "If there are multiple strings, create a 'Strings' bus."]

**FX busses**
- Width: stereo, all of them [conventions: "These are stereo busses."]
- Destination: Main, unity, POST fader [conventions: "Create the following FX busses and send them to Main at unity, post fader."]
- Bus fader: unity [conventions: "Fader at unity."]
- Sends: generally unity, POST fader, unless noted [conventions: "Sends to these busses are generally at unity, POST fader, unless noted below."] - this overrides the domain default of GRP-mode sends [domain: "Generally the channel send mode is GRP and the send level is fixed by the GRP setting."] [domain: "Sometimes, engineers prefer to send channels POST fader so that they can control the send level for each channel independently."]
- VOX Reverb: all vocal channels [conventions: "'VOX Reverb' -- All vocal channels"]
- VOX Delay: all vocal channels [conventions: "'VOX Delay' -- All vocal channels"]
- Snare Verb: snare channels; send level -10dB, PRE fader [conventions: "'Snare Verb' -- Snare channels. Sends from channels at -10db, PRE fader."]
- INST Reverb: all instrument channels except drums; send level fully down, POST fader (a starting point, not a permanent mute) [conventions: "'INST Reverb' -- All instrument channels (but not drums). Set send levels to this buss all the way down, POST fader."] [domain: "Send levels into monitors are a performance decision made at sound check and during the show." - same reasoning extends to FX starting levels]

## Outputs

- Main: the full mix; has no physical output of its own; feeds only Matrix 1 [conventions: "Main should be the full mix. Send to Matrix 1. Main has no physical output of its own; it only feeds Matrix 1."]
- Main width: stereo (it is referred to elsewhere as the "Main L/R bus") [conventions: "Send all Channels to the Main L/R bus unless they are included in one of the mix busses below."]
- Main = the house/FOH mix [domain: "\"FOH\" means the main mix."]
- Matrix 1: takes its feed from Main; patched to internal XLR outputs 7 and 8 [conventions: "Matrix 1 takes its feed from Main. Patch output to internal XLRs 7 and 8."]
- Matrix 1 width: Decided - stereo, because it is patched to a pair of adjacent sockets (7 and 8) [domain: "a bus patched to a socket pair is stereo, because a pair carries a left and a right."]
- "XLRs"/"internal XLRs" mean the console's own local output sockets [domain: "\"XLR outputs\" or \"the XLRs\" normally means the console's local outputs."]
- Monitor busses MON1-4 patch to local XLR outputs 1-4 unless overridden (see Busses) [conventions: "Patch output to local XLR outputs 1 through 4 if not specified otherwise."]
- No other physical output is defined; mix and FX busses feed Main internally rather than a physical jack [conventions: "Patch all to Main mix, POST fader at unity."] [conventions: "Create the following FX busses and send them to Main at unity, post fader."]

## DCAs

DCAs are created only where the show actually has at least one qualifying member; an empty grouping is not created [conventions: "Create a DCA for the following instrument grouping if there is at least one member:"]

- Drums DCA: every channel in the drums category [conventions: "Drums DCA should include every channel in the drums category."]
- Guitars DCA: all guitars-category channels [conventions: "Guitars: all guitars-category channels"]
- Keys DCA: all keys-category channels [conventions: "Keys: all keys-category channels"]
- Vocals DCA: all vocals-category channels [conventions: "Vocals: all vocals-category channels"]
- Tracks DCA: all tracks- or trax- category channels, including Click/Guide (Click/Guide are a type of track channel) [conventions: "Tracks: all tracks- or trax- category channels"] [domain: "If there are multiple track channels, there may be a channel called click, or guide, or a combination of the two"]
- Strings DCA: all strings-category channels [conventions: "Strings: all strings-category channels"]
- Horns DCA: all horns-category channels [conventions: "Horns: all horns-category channels"]
- Band DCA: all other instruments not included in one of the DCAs above (catches Bass, and any uncategorised band instrument) [conventions: "Band: Include all other instruments not included in one of the DCAs above."]
- Speech DCA: Hosts, MCs, Podium Mics, Presenters, Pastors, etc. [conventions: "Speech: Hosts, MCs, Podium Mics, Presenters, Pastors, etc."]
- FX DCA: Decided - all four FX busses (VOX Reverb, VOX Delay, Snare Verb, INST Reverb) only; the Drums/Vocals/Keys/Horns/Strings mix busses are not "effects return busses" and are excluded [conventions: "FX should include all the effects return busses."] [domain: "There are three different classes of busses to create: mix busses (these consolidate parts of the band, like drums, vocals or a horn section), monitor busses (independent mixes for the musicians), and FX busses (used to share an FX processor with multiple channels)."]

## Mute groups

- Band: all band instruments (drums, bass, guitars, keyboards, strings, horns) - vocals and tracks are excluded [conventions: "Band: All band instruments"] [domain: "\"Instruments\" normally does not include the vocals or backing tracks."]
- Vocals: all (singing) vocal channels [conventions: "Vocals: All (singing) vocal channels"]
- Speech: all speech channels [conventions: "Speech: All speech channels"]
- FX: all FX busses [conventions: "FX: All FX busses"]
- No mute group exists for Tracks, Click/Guide, or Misc/Aux channels - Tracks are explicitly excluded from Band, and no other group names them [conventions: "Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send."]
- Decided - unlike DCAs, mute groups have no "at least one member" condition stated, so all four listed mute groups (Band, Vocals, Speech, FX) are always created, even if a particular show leaves one with zero members [conventions: "Create a DCA for the following instrument grouping if there is at least one member:"] (this qualifier appears only in the DCA section, not the Mute Groups section)

## Head amps

- Mic or DI on a physical socket: head-amp gain 20dB, Trim 0dB, unless the show instructions override [conventions: "Unless overridden by the show instructions, set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB."]
- Mic or DI phantom power: Decided - off by default, enabled only where the input list specifies a source (e.g. a condenser mic) that needs 48V; neither conventions nor domain state a blanket default [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]
- Digital source (USB, expansion card, player): no head-amp gain - not applicable, since there is no preamp [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom, so a \"set the gain on each channel\" means the channels that have a preamp, and a digital one's gain is rightly left unset."]
- Digital source Trim: 0dB, same as any channel [conventions: "and the Trim to 0dB."] [domain: "Trim applies to every channel."]
- Digital source phantom: none, not applicable [domain: "arrives already levelled and has no head amp and no phantom"]
- Aux strip: Decided - gain, trim and phantom follow whichever source feeds the strip (physical or digital), by the same two rules above; strip kind (channel vs aux) does not change how the underlying socket's preamp works [domain: "Gain — the head amp on the physical socket, `io.in.{group}.{n}.g`. Shared by every channel patched to that socket. Only a physical mic/line input has one."] [domain: "Trim applies to every channel."]
- A shared socket (two strips off one input) has one gain and one phantom setting for both strips, since there is one preamp; only settings after the preamp may differ [domain: "One socket has one head-amp gain and one phantom setting, because there is one preamp."]

## Patching and channel order

- Patch sockets exactly as the input list specifies [conventions: "Patch input sockets according to the supplied input list."]
- If a row has no socket given: patch in channel order to local inputs 1-24, then overflow to AES50-A starting at 1 [conventions: "If the input list gives no socket for a row, patch in channel order to local inputs 1-24, then overflow to AES50-A from 1."]
- "AES50-A" names a stage-box connection by protocol [domain: "Stage boxes get called by their protocol (\"AES50-A\") or their position (\"the stage box\", \"upstage left\")."]
- Channel order: drums, then bass, then guitars, then keyboards, then any strings or brass, then vocals, then tracks, then speech, then anything else [conventions: "Patch drums first, then bass, guitars, keyboards, any strings or brass, then vocals, then tracks, then speakers, and then anything else."]
- Decided - "speakers" in the channel-order line is read as "speech" (a typo): the colour list and every other section name the category "Speech", never "speakers", and there is no other category by that name [conventions: "Color coding: Drums-Red, Bass-Blue, Guitars-Magenta, Keyboards-Cyan, Strings/Brass-Orange, Vocals-Green, Tracks/Plaback-Yellow, Speech-Purple"]
- Drum sub-order: kick, snare, hi-hat, rack toms, floor tom(s), overheads, then any other percussion [conventions: "Drum kit order: kick, snare, hi hat, rack toms, floor toms, overheads and then any other percussion."]
- Toms: lower-numbered inputs are rack toms; the single highest-numbered tom is the floor tom, unless the input list itself shows more than one floor tom [conventions: "The lower-numbered toms are rack toms. There is almost always only one floor tom (the highest number); if there were more, the input list would say so."]
- Overheads named with Left/Right: keep as separate mono channels, never a stereo pair, because they need separate processing [conventions: "If you see Left/Right designations in the overhead (OH) names, do NOT patch as a stereo pair, keep as separate mono channels -- the reason is they get separate processing."]
- Any other instrument (not overheads) with two sequential inputs marked as a stereo pair (L/R, Left/Right): patch as one stereo channel [conventions: "For instruments other than overheads, if two sequential inputs are marked as stereo pair (L/R, Left/Right), patch as one stereo channel."]
- Every socket carries one mono signal; a "stereo source" is two mono sockets both flagged `mode: "ST"`, and the stereo channel's patch points at the first of the two [domain: "There is no such thing as a stereo input socket. A socket is one jack carrying one signal."] [domain: "A \"stereo source\" is therefore two mono inputs that someone has decided belong together."]
- A stereo pair must sit on two consecutive sockets starting on an odd number (1+2, 15+16, 23+24, etc.); this is a hardware limit, not a preference [domain: "A WING forms a stereo pair only from two **consecutive** sockets starting on an **odd** one: 1+2, 15+16, 23+24. Never 2+3, never 1+5."] [domain: "This is the routing hardware and not a preference — asked for an even-first pair the desk refuses and snaps it back"]
- If the two physical halves of a stereo source cannot be adjacent (different stage boxes, or a card feed 32 apart), build a USER SIGNAL (from an existing strip) or USER PATCH (from a physical jack) so the pair the hardware sees is legal [domain: "called a **USER SIGNAL** or a **USER PATCH**. These are virtual sources."] [domain: "A **user signal** takes an existing strip — a channel, an aux, a bus, a Main, a Matrix — which is how you feed something already mixed back in somewhere else. A **user patch** takes a physical jack directly, with no strip in between, and that is the one that matters for an input list."]
- A deliberate second strip off one socket (e.g. a separate monitor-mix strip, or a socket reused between acts) is legal only if the input list or instructions.md calls it out; otherwise treat two strips on one socket as a mistake [domain: "But a second strip on the **same socket** is a normal, deliberate thing to ask for, and there are two common reasons"] [domain: "This is not the same as two strips accidentally patched to one socket, which is a mistake."]
- Shared-socket strips must be unlinked from the source name and each named individually, since a socket can't carry two names [domain: "The strips cannot inherit their name from the source."]

## Faders

- Channel faders: fully down (-inf) at the start [conventions: "Leave all faders all the way down."]
- Monitor bus (MON1-4) faders: fully down [conventions: "Leave bus faders all the way down."]
- "Fully down"/"-inf" is exactly -144 on the wire [domain: "Fully down has many names — \"all the way down\", \"fully down\", \"-inf\", \"off\". On the wire, WING's floor is exactly -144."]
- Mix bus faders (Drums, Vocals, Keys, Horns, Strings): unity [conventions: "Bus faders at unity."]
- Drums Comp bus fader: unity, then pulled down 6dB [conventions: "Leave the fader pulled down 6dB."]
- FX bus faders (VOX Reverb, VOX Delay, Snare Verb, INST Reverb): unity [conventions: "Fader at unity."]
- Channel sends to monitor busses: fully down, mute off [conventions: "Leave those sends all the way down, mute off, mode is PRE fader."]
- Channel sends to mix busses: unity [conventions: "Sends from channels to these busses should be at unity, POST fader."]
- Channel sends to FX busses: unity generally [conventions: "Sends to these busses are generally at unity, POST fader, unless noted below."]; Snare Verb sends at -10dB [conventions: "Sends from channels at -10db, PRE fader."]; INST Reverb sends fully down [conventions: "Set send levels to this buss all the way down, POST fader."]

## Lines with no effect

None. Every non-heading line in conventions.md produces at least one rule captured above.

## Category table

```json
[
  {"name": "Drums", "aliases": ["drums", "drum"], "color": "Red", "hpf_hz": 40, "dca": ["Drums"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Bass", "aliases": ["bass"], "color": "Blue", "hpf_hz": 80, "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Guitars", "aliases": ["guitars", "guitar"], "color": "Magenta", "hpf_hz": 80, "dca": ["Guitars"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Keyboards", "aliases": ["keys", "keyboards", "keyboard"], "color": "Cyan", "hpf_hz": 80, "dca": ["Keys"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144},
  {"name": "Strings", "aliases": ["strings"], "color": "Orange", "hpf_hz": 80, "dca": ["Strings"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144},
  {"name": "Horns/Brass", "aliases": ["horns", "brass"], "color": "Orange", "hpf_hz": 100, "dca": ["Horns"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144},
  {"name": "Vocals", "aliases": ["vocals", "vocal"], "color": "Green", "hpf_hz": 120, "dca": ["Vocals"], "mute_group": ["Vocals"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Tracks/Playback", "aliases": ["tracks", "trax", "playback"], "color": "Yellow", "hpf_hz": null, "dca": ["Tracks"], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144},
  {"name": "Click/Guide", "aliases": ["click", "guide"], "color": "Yellow", "hpf_hz": null, "dca": ["Tracks"], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Speech", "aliases": ["speech"], "color": "Purple", "hpf_hz": 120, "dca": ["Speech"], "mute_group": ["Speech"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Misc / External Feeds", "aliases": ["misc"], "color": null, "hpf_hz": null, "dca": [], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true}
]
```
