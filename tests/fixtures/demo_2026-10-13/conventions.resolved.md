<!-- atoo resolved conventions
conventions: conventions.md
conventions_sha256: ce3897b9df9bc0a1dfb9ab9f3573afae554b712769961e21c6d07714973ecfe8
domain_sha256: f4b9ce2dd1d2738e1375b29d5c2c86d39c335b2c49eaecae7f34ba98dbfb4e29
prompt_sha256: ce73ef7020fbe61bfc7c1fd84322cfc08bcbc4875a7f3d73de32093f0dbc8903
model: claude-sonnet-5-5
effort: medium
made: 2026-10-13T03:11:09Z
atoo: 0.1.0 (71fbc0d)
Made by Atoo from the conventions and the domain knowledge; made again when either changes. Edit the conventions, not this file.
-->

# Resolved conventions (conventions.md)

## Categories

Common to every strip: head-amp gain 20 dB and trim 0 dB on a physical socket, and fader fully down (-144 dB), unmuted. Details are in `## Head amps` and `## Faders`.

### Drums (includes percussion)
- Decided: percussion rows ("perc", "percussion") belong to Drums. The conventions give percussion a preset but no colour, DCA or position, and the drum kit is the nearest family. [conventions: "- Percussion: "Perc""]
- Strip kind: channel. [conventions: "Everything on the input list gets a regular channel."]
- Colour: Red. [conventions: "Drums-Red"]
- Preset: kick "Kick In"; snare "Snare"; hi-hat "HiHat"; percussion "Perc"; overheads "OH". [conventions: "- Kick: "Kick In""] [conventions: "- Snare: "Snare""] [conventions: "- Hi-hat: "HiHat""] [conventions: "- Overheads: "OH""] [conventions: "- Percussion: "Perc""]
- Preset: toms are "H Tom" for the high (or only) rack tom, "M Tom" for a second rack tom, "Fl Tom" for the floor tom. [conventions: "- Toms: "H Tom" for the high (or only) rack tom, "M Tom" for a second rack tom, "Fl Tom" for the floor tom."]
- A preset the input list names replaces the default. [conventions: "If the input list names a preset, use that one instead of the defaults above."]
- HPF: comes from the preset, so it is not set here. A drums channel with no preset gets 40 Hz. [conventions: "The high-pass filter comes from the channel's preset."] [conventions: "drums 40Hz"]
- DCA: "Drums". [conventions: "- Drums: every drums-category channel."]
- Mute group: "Band". [conventions: "- Band: every drums, bass, guitars, keys and horns channel."]
- Monitor sends: none unless the show's instructions list them (pre fader, -18 dB). [conventions: "Only the sends the show's instructions list are switched on, starting at -18dB"]
- Mix bus: "Drums". [conventions: "- "Drums": every drums-category channel."]
- FX sends: none.
- Main routing: only through the Drums bus, not direct. [conventions: "a channel in a mix bus does not also go to Main directly"]
- Gain 20 dB, trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Phantom: from the input list's phantom column. [conventions: "Phantom power comes from the input list's phantom column, never from here."]

### Bass
- Strip kind: channel. [conventions: "Everything on the input list gets a regular channel."]
- Colour: Blue. [conventions: "Bass-Blue"]
- Preset: "Bass". [conventions: "- Bass: "Bass""]
- HPF: from the preset; 50 Hz if the channel has no preset. [conventions: "bass 50Hz"]
- DCA: "Band". [conventions: "- Band: bass, guitars, keys and horns."]
- Mute group: "Band". [conventions: "- Band: every drums, bass, guitars, keys and horns channel."]
- Monitor sends: none unless instructed.
- Mix bus: none.
- FX sends: none.
- Main routing: direct. [conventions: "Every channel that is in no mix bus goes to Main directly."]
- Gain 20 dB, trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Phantom: from the input list. [conventions: "Phantom power comes from the input list's phantom column, never from here."]

### Guitars
- Strip kind: channel. [conventions: "Everything on the input list gets a regular channel."]
- Colour: Pink. [conventions: "Guitars-Pink"]
- Preset: electric "E Gtr"; acoustic "Ac Gtr". [conventions: "- Electric guitar: "E Gtr""] [conventions: "- Acoustic guitar: "Ac Gtr""]
- HPF: from the preset; 80 Hz if the channel has no preset. [conventions: "guitars 80Hz"]
- DCA: "Band". [conventions: "- Band: bass, guitars, keys and horns."]
- Mute group: "Band". [conventions: "- Band: every drums, bass, guitars, keys and horns channel."]
- Monitor sends: none unless instructed.
- Mix bus: none.
- FX sends: none.
- Main routing: direct. [conventions: "Every channel that is in no mix bus goes to Main directly."]
- Gain 20 dB, trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Phantom: from the input list. [conventions: "Phantom power comes from the input list's phantom column, never from here."]

### Keys
- Strip kind: channel. [conventions: "Everything on the input list gets a regular channel."]
- Colour: Cyan. [conventions: "Keys-Cyan"]
- Preset: keyboards "Keys"; piano "Piano". [conventions: "- Keyboardss: "Keys""] [conventions: "- Piano: "Piano""]
- HPF: from the preset; 60 Hz if the channel has no preset. [conventions: "keys 60Hz"]
- DCA: "Band". [conventions: "- Band: bass, guitars, keys and horns."]
- Mute group: "Band". [conventions: "- Band: every drums, bass, guitars, keys and horns channel."]
- Monitor sends: none unless instructed.
- Mix bus: none.
- FX sends: none.
- Main routing: direct. [conventions: "Every channel that is in no mix bus goes to Main directly."]
- Gain 20 dB, trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Phantom: from the input list. [conventions: "Phantom power comes from the input list's phantom column, never from here."]

### Horns (also called brass)
- Decided: "brass" is the same category as horns. [domain: ""Horns" and "Brass" generally mean the same thing."]
- Strip kind: channel. [conventions: "Everything on the input list gets a regular channel."]
- Colour: Amber. [conventions: "Horns-Amber"]
- Preset: trumpet "Trumpet"; trombone "T Bone"; alto sax "A Sax"; baritone sax "B Sax"; tenor sax "B Sax"; generic sax "B Sax". [conventions: "- Trumpet: "Trumpet""] [conventions: "- Trombone: "T Bone""] [conventions: "- Alto sax: "A Sax""] [conventions: "- Baritone sax: "B Sax""] [conventions: "- Tenor sax: "B Sax""] [conventions: "- Generic sax "B Sax""]
- HPF: from the preset; 100 Hz if the channel has no preset. [conventions: "horns 100Hz"]
- DCA: "Band". [conventions: "- Band: bass, guitars, keys and horns."]
- Mute group: "Band". [conventions: "- Band: every drums, bass, guitars, keys and horns channel."]
- Monitor sends: none unless instructed.
- Mix bus: "Horns". [conventions: "- "Horns": every horns-category channel."]
- FX sends: none.
- Main routing: only through the Horns bus, not direct. [conventions: "a channel in a mix bus does not also go to Main directly"]
- Gain 20 dB, trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Phantom: from the input list. [conventions: "Phantom power comes from the input list's phantom column, never from here."]

### Vocals (lead and backing; "vox" is shorthand)
- Strip kind: channel. [conventions: "Everything on the input list gets a regular channel."]
- Colour: Green. [conventions: "Vocals-Green"]
- Preset: "Vocal". [conventions: "- Lead and backing vocals: "Vocal""]
- HPF: from the preset; 120 Hz if the channel has no preset. [conventions: "vocals 120Hz"]
- DCA: "Vocals". [conventions: "- Vocals: every vocals-category channel."]
- Mute group: "Vocals". [conventions: "- Vocals: every vocals-category channel."]
- Monitor sends: none unless instructed.
- Mix bus: "Vocals". [conventions: "- "Vocals": every vocals-category channel."]
- FX sends: "Vox Verb", post fader at -6 dB. [conventions: ""Vox Verb" bus: include every vocals-category channel, POST fader at -6dB."]
- Main routing: only through the Vocals bus, not direct. [conventions: "a channel in a mix bus does not also go to Main directly"]
- Gain 20 dB, trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Phantom: from the input list. [conventions: "Phantom power comes from the input list's phantom column, never from here."]

### Speech (host, MC, podium, pastor, speaker)
- Decided: these words all mean Speech, and speech is not part of the band. [domain: ""Host" or "MC" or "Podium" or "Pastor" or "Speaker" are all spoken word or speech inputs."]
- Strip kind: channel. [conventions: "Everything on the input list gets a regular channel."]
- Colour: none (the conventions give none).
- Preset: "Speech". [conventions: "- Speech (an MC, host, a podium): "Speech""]
- HPF: from the preset; there is no source fallback, so not set otherwise.
- DCA: none. Decided: no DCA rule covers speech, and it is not band. [domain: "They are almost never a part of the band."]
- Mute group: none. Decided: for the same reason.
- Monitor sends: none unless instructed.
- Mix bus: none.
- FX sends: none.
- Main routing: direct. [conventions: "Every channel that is in no mix bus goes to Main directly."]
- Gain 20 dB, trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Phantom: from the input list. [conventions: "Phantom power comes from the input list's phantom column, never from here."]

### Playback (the band's tracks, and external feeds on the input list)
- Decided: "tracks", "trax" and "playback" are this category. A "misc" row goes here unless its source is crowd, ambient or room (see Crowd). External feeds that are on the input list still get regular channels, because aux strips are only for sources the show's instructions add. [domain: "Tracks" or "trax" means the band's own backing tracks"] [conventions: "Everything on the input list gets a regular channel. Aux channels are for sources the show's instructions add."]
- Strip kind: channel (an aux only if the instructions add one).
- Colour: Yellow. [conventions: "Playback-Yellow"]
- Preset: none. [conventions: "- Playback: no preset."]
- HPF: none. [conventions: "Playback gets none."]
- DCA: "Playback". [conventions: "- Playback: playback channels, and any aux channel the show adds for music."]
- Mute group: none.
- Monitor sends: none unless instructed.
- Mix bus: none.
- FX sends: none.
- Main routing: direct. [conventions: "Every channel that is in no mix bus goes to Main directly."]
- Gain 20 dB on a physical mic/line socket only; a digital source (USB, card, player) has none. Trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."] [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]
- Phantom: from the input list; none on a digital source.

### Click / guide
- Decided: rows named click or guide are their own category. They are the band's tracks and are treated like Playback, except they never reach Main. [domain: "these tracks must never be routed to the main mix, only to monitor busses."]
- Strip kind: channel. [domain: "belong on **regular channels** where possible."]
- Colour: Yellow (Playback colour). Decided: it is playback material. [conventions: "Playback-Yellow"]
- Preset: none; HPF: none. [conventions: "Playback gets none."]
- DCA: "Playback". Decided: it is a playback channel. [conventions: "- Playback: playback channels, and any aux channel the show adds for music."]
- Mute group: none.
- Monitor sends: only the instructed ones. Click and guide go only to monitor busses. [domain: "Click and Guide are for the musicians on stage only."]
- Mix bus: none.
- FX sends: none.
- Main routing: none, not direct. Decided: this overrides the direct-to-Main line, because the domain rule is a safety rule. [domain: "must never be routed to the main mix"]
- Gain 20 dB on a physical socket, trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Phantom: from the input list.

### Crowd / ambient / room
- Decided: the conventions are silent, so the domain rule is used. These mics are never routed to Main. [domain: "It is always routed to monitor or recording busses, never to the mains."]
- Strip kind: channel, mono or stereo as the input list gives it. [conventions: "Everything on the input list gets a regular channel."]
- Colour: none. Preset: none. HPF: none.
- DCA: none. Mute group: none.
- Monitor sends: none unless instructed.
- Mix bus: none. FX sends: none.
- Main routing: none, not direct.
- Gain 20 dB, trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Phantom: from the input list.

### Misc (a word, not a strip)
- Decided: "misc" is not automatically aux. It is placed by what the source is: crowd, ambient or room goes to Crowd; anything else goes to Playback. [domain: "Do not treat "misc" as automatically meaning aux"]

### Band (a grouping word)
- The DCA "Band" is bass, guitars, keys and horns. The mute group "Band" is drums, bass, guitars, keys and horns. Vocals, speech and playback are never in either. [conventions: "- Band: bass, guitars, keys and horns."] [conventions: "- Band: every drums, bass, guitars, keys and horns channel."]
- Decided: the conventions' definitions override the broader domain meaning of "band". [domain: ""Band" usually means all instruments"]

### Instruments (a grouping word)
- Drums, bass, guitars, keys and horns. It excludes vocals and tracks. [domain: ""Instruments" normally does not include the vocals or backing tracks."]

## Busses

Order: monitor busses, then mix busses, then FX busses. [conventions: "Bus order: monitor busses first, then mix busses, then FX busses."]

1. **Monitor busses**: one per mix on stage, named for who it is for. The show's instructions list them. [conventions: "Monitor busses: one per mix on stage, named for who it is for."]
   - Width: a wedge mix is MONO; an in-ear (IEM) mix is STEREO. [conventions: "A wedge mix is a MONO bus. An in-ear (IEM) mix is a STEREO bus."]
   - Colour: White. [conventions: "Monitor busses are White."]
   - Destination: the output the instructions give it. Never to Main. [conventions: "Never routed to Main. Each one is patched to the output the show's instructions give it."]
   - Fader: -12 dB. [conventions: "Monitor bus faders at -12dB."]
   - Senders: only channels the instructions list. [conventions: "every other channel stays out of the mix until soundcheck."]
   - Mode and level: PRE fader, -18 dB. [conventions: "Sends to monitor busses are PRE fader."]
2. **Drums**: stereo; Main at unity; fader 0 dB; colour Red; preset "Mix Bus". Senders: every drums-category channel, POST fader at 0 dB. [conventions: "Mix busses are STEREO, routed to Main at unity, faders at unity."] [conventions: "Channel sends to them are POST fader at unity"] [conventions: "Every mix bus takes the bus preset "Mix Bus", which carries its compressor."] [conventions: "Mix busses take their category's colour."]
3. **Horns**: same as Drums, colour Amber. Senders: every horns-category channel. [conventions: "- "Horns": every horns-category channel."]
4. **Vocals**: same as Drums, colour Green. Senders: every vocals-category channel. [conventions: "- "Vocals": every vocals-category channel."]
   - Condition: a mix bus with no channel feeds is not created. [conventions: "A mix bus with no channel feeds is left out of the plan."]
5. **Vox Verb** (FX): stereo; Purple; Main at unity; fader 0 dB; preset "Vox Verb". Senders: every vocals-category channel, POST fader at -6 dB. [conventions: "FX busses are STEREO, routed to Main at unity, faders at unity."] [conventions: "FX busses are Purple."] [conventions: "Each FX bus takes the bus preset of the same name ("Vox Verb", "Snare Verb")"] [conventions: ""Vox Verb" bus: include every vocals-category channel, POST fader at -6dB."]
   - Condition: created only if there is at least one vocals channel. Decided: an FX bus with no feeds is left out, like a mix bus.
   - Decided: no "Snare Verb" bus is created, because no sender rule exists for it. The name is only an example of the preset naming. [conventions: "Each FX bus takes the bus preset of the same name ("Vox Verb", "Snare Verb")"]
   - Decided: the send mode is POST at -6 dB as the conventions say, not the domain's usual GRP. [domain: "Sometimes, engineers prefer to send channels POST fader"]

## Outputs

- Main 1 is named "PA", patched to local XLR outputs 1 and 2 (LCL 1 and 2), fader at unity (0 dB). [conventions: "Main 1 is the PA. Name it "PA", patch it to local XLR outputs 1 and 2, fader at unity."]
- Mix and FX busses feed Main 1 at unity. Monitor busses never feed Main; each is patched to the output the instructions give. [conventions: "Never routed to Main. Each one is patched to the output the show's instructions give it."]
- Matrix: none. Decided: the conventions create none, and Main 1 goes straight to the physical outputs. [domain: "Either a Main bus or a Matrix bus can be the final step before the physical outputs."]
- Every channel must reach Main directly or through a mix bus, except click/guide and crowd. [domain: "All channels need a path to the final output"]

## DCAs

- "Drums": every drums-category channel. [conventions: "- Drums: every drums-category channel."]
- "Band": bass, guitars, keys and horns channels. [conventions: "- Band: bass, guitars, keys and horns."]
- "Vocals": every vocals-category channel. [conventions: "- Vocals: every vocals-category channel."]
- "Playback": playback and click/guide channels, and any aux the show adds for music. [conventions: "- Playback: playback channels, and any aux channel the show adds for music."]
- "FX": every FX bus. [conventions: "- FX: every FX bus."]
- Decided: a DCA with no members is not created, for the same reason an empty mix bus is left out. [conventions: "A mix bus with no channel feeds is left out of the plan."]
- DCAs control faders only; they create no signal path. [domain: "DCAs, while assigned to channels in a similar manner to a bus, do NOT create a signal path"]

## Mute groups

- "Band": every drums, bass, guitars, keys and horns channel. [conventions: "- Band: every drums, bass, guitars, keys and horns channel."]
- "Vocals": every vocals-category channel. [conventions: "- Vocals: every vocals-category channel."]
- "FX": every FX bus. [conventions: "- FX: every FX bus."]
- Decided: a mute group with no members is not created, by the same reasoning as DCAs. [conventions: "A mix bus with no channel feeds is left out of the plan."]

## Head amps

- Mic or DI on a physical socket: gain 20 dB, trim 0 dB, phantom from the input list's phantom column. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."] [conventions: "Phantom power comes from the input list's phantom column, never from here."]
- Digital source (USB, card, player): no gain and no phantom; trim 0 dB. [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"] [domain: "Trim applies to every channel."]
- Aux strip the instructions add: on a physical socket, gain 20 dB, trim 0 dB, phantom from the input list or instructions. Decided: the conventions call these "aux channels", so the every-channel start values apply. An aux has no HPF. [conventions: "Aux channels are for sources the show's instructions add."] [domain: "An aux strip has no high-pass filter"]
- Gain belongs to the socket, so strips sharing a socket share gain and phantom. [domain: "One socket has one head-amp gain and one phantom setting"]

## Patching and channel order

- Patch each socket as the input list says. [conventions: "Patch input sockets according to the supplied input list."]
- Overflow: not covered. Decided: never renumber or move a row away from its listed socket.
- Channel order: drums, bass, guitars, keys, horns, vocals, speech, playback (tracks and click/guide) last. Decided: speech sits between vocals and playback, because the conventions place playback last but say nothing about speech. [conventions: "Channel order: drums, then bass, guitars, keys, horns, vocals, and playback last."]
- Drum order: kick, snare, hi hat, toms high to low, overheads. Decided: percussion follows the overheads. [conventions: "Drum kit order: kick, snare, hi hat, toms from high to low, then overheads."]
- Stereo pairing: two inputs named as a Left/Right pair become one stereo channel named without the L/R: "OH", "Keys", "Playback". Overheads are included. Decided: the conventions' explicit rule overrides the domain's caution about merging L/R names. [conventions: "Two inputs named as a Left/Right pair ("OH L"/"OH R", "Keys L"/"Keys R", "Playback L"/"Playback R") become one stereo channel, named without the L/R ("OH", "Keys", "Playback"). Overheads included."]
- A stereo channel patches to the first of its two sockets. The pair must be consecutive sockets starting on an odd one. [domain: "A WING forms a stereo pair only from two **consecutive** sockets starting on an **odd** one"]
- Decided: if the listed sockets are not an odd-first consecutive pair, build the pair with a user patch and do not move the sockets. [domain: "the desk has its own way round it, called a **USER SIGNAL** or a **USER PATCH**"]
- Two strips on one socket are allowed only if the input list or instructions say so. Both are then unlinked from the source name and named directly. [domain: "a deliberate share **will be called out**"]

## Faders

- Every channel and aux strip: fully down, -144 dB, unmuted. [conventions: "Start every channel fader all the way down, unmuted."]
- Mix busses: 0 dB. [conventions: "Mix busses are STEREO, routed to Main at unity, faders at unity."]
- FX busses: 0 dB. [conventions: "FX busses are STEREO, routed to Main at unity, faders at unity."]
- Monitor busses: -12 dB. [conventions: "Monitor bus faders at -12dB."]
- DCAs: 0 dB. [conventions: "DCA faders start at unity."]
- Main 1: 0 dB. [conventions: "fader at unity"]
- Channel sends: to mix busses POST at 0 dB; to Vox Verb POST at -6 dB; to monitors PRE at -18 dB (instructed only).

## Lines with no effect

- [conventions: "Alert if any mix bus or FX buss is muted, or fader is < -40dB (Low fader)"] This is a runtime alert, not a layout value.
- [conventions: "Alert if any active main or matrix bus is muted or fader is < -40dB"] This is a runtime alert, not a layout value.
- [conventions: "Alert if any active DCA fader < -30dB or muted"] This is a runtime alert, not a layout value.

## Category table

```json
[
  {"name": "Drums", "aliases": ["drums", "drum", "percussion", "perc"], "color": "Red", "dca": ["Drums"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Bass", "aliases": ["bass"], "color": "Blue", "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Guitars", "aliases": ["guitars", "guitar", "gtr", "gtrs"], "color": "Pink", "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Keys", "aliases": ["keys", "keyboard", "keyboards", "piano"], "color": "Cyan", "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Horns", "aliases": ["horns", "horn", "brass"], "color": "Amber", "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Vocals", "aliases": ["vocals", "vocal", "vox"], "color": "Green", "dca": ["Vocals"], "mute_group": ["Vocals"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Speech", "aliases": ["speech", "host", "mc", "podium", "pastor", "speaker"], "dca": [], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Playback", "aliases": ["playback", "tracks", "track", "trax", "misc"], "color": "Yellow", "hpf_hz": null, "dca": ["Playback"], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Click", "aliases": ["click", "guide"], "color": "Yellow", "hpf_hz": null, "dca": ["Playback"], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Crowd", "aliases": ["crowd", "ambient", "room"], "hpf_hz": null, "dca": [], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false}
]
```

## Instructed strips

```json
[]
```
