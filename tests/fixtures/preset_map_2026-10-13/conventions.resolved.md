<!-- atoo resolved conventions
conventions: conventions.md
conventions_sha256: ce3897b9df9bc0a1dfb9ab9f3573afae554b712769961e21c6d07714973ecfe8
domain_sha256: f4b9ce2dd1d2738e1375b29d5c2c86d39c335b2c49eaecae7f34ba98dbfb4e29
prompt_sha256: ce73ef7020fbe61bfc7c1fd84322cfc08bcbc4875a7f3d73de32093f0dbc8903
model: claude-sonnet-5-5
effort: medium
made: 2026-10-13T15:29:41Z
atoo: 0.1.0 (cb6ac17)
Made by atoo from the conventions and the domain knowledge; made again when either changes. Edit the conventions, not this file.
-->

# Resolved conventions (conventions.md)

## Categories

### Drums
- Covers kick, snare, hi hat, toms and overheads. Also covers percussion (see the Percussion decision below). [conventions: "Drum kit order: kick, snare, hi hat, toms from high to low, then overheads."]
- Strip kind: regular channel. [conventions: "Everything on the input list gets a regular channel."]
- Colour: Red. [conventions: "Color coding: Drums-Red"]
- Presets: Kick "Kick In"; Snare "Snare"; Hi-hat "HiHat"; high (or only) rack tom "H Tom"; second rack tom "M Tom"; floor tom "Fl Tom"; Overheads "OH"; Percussion "Perc". A preset named on the input list replaces these. [conventions: "If the input list names a preset, use that one instead of the defaults above."]
- HPF: comes from the channel's preset (value not stated in the texts). A drums channel with no preset gets 40 Hz. [conventions: "The high-pass filter comes from the channel's preset."] [conventions: "drums 40Hz"]
- DCA: "Drums". Mute group: "Band". [conventions: "Drums: every drums-category channel."] [conventions: "Band: every drums, bass, guitars, keys and horns channel."]
- Monitor sends: none unless the show's instructions list them (then PRE, -18 dB). [conventions: "Only the sends the show's instructions list are switched on, starting at -18dB"]
- Mix bus: "Drums" (POST, 0 dB). FX sends: none. [conventions: "\"Drums\": every drums-category channel."]
- Main routing: only through the "Drums" bus, not direct. [conventions: "a channel in a mix bus does not also go to Main directly"]
- Head-amp gain 20 dB, trim 0 dB. Phantom from the input list. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."] [conventions: "Phantom power comes from the input list's phantom column, never from here."]
- Decided: Percussion is part of Drums (Red, Drums bus, Drums DCA, Band mute group, ordered after the overheads). The conventions give percussion a preset ("Perc") but no category, and the drums fallback is the nearest fit. [conventions: "Percussion: \"Perc\""]
- Decided: a stereo overhead pair (OH L/OH R) is one stereo channel named "OH", per the conventions. [conventions: "Overheads included."]

### Bass
- Regular channel, Blue, preset "Bass". HPF from preset, else 50 Hz. [conventions: "Bass-Blue"] [conventions: "Bass: \"Bass\""] [conventions: "bass 50Hz"]
- DCA "Band". Mute group "Band". [conventions: "Band: bass, guitars, keys and horns."]
- Monitor sends: none unless the instructions list them. No mix bus, no FX sends.
- Main routing: direct, since it is in no mix bus. [conventions: "Every channel that is in no mix bus goes to Main directly."]
- Gain 20 dB, trim 0 dB, phantom from the input list. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]

### Guitars
- Regular channel, Pink. Presets: electric "E Gtr", acoustic "Ac Gtr". HPF from preset, else 80 Hz. [conventions: "Guitars-Pink"] [conventions: "Electric guitar: \"E Gtr\""] [conventions: "Acoustic guitar: \"Ac Gtr\""] [conventions: "guitars 80Hz"]
- DCA "Band". Mute group "Band". [conventions: "Band: bass, guitars, keys and horns."]
- Monitor sends: instructions only. No mix bus, no FX. Main: direct. [conventions: "Every channel that is in no mix bus goes to Main directly."]
- Gain 20 dB, trim 0 dB, phantom from the input list. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]

### Keys
- Regular channel, Cyan. Presets: keyboards "Keys", piano "Piano". HPF from preset, else 60 Hz. [conventions: "Keys-Cyan"] [conventions: "Keyboardss: \"Keys\""] [conventions: "Piano: \"Piano\""] [conventions: "keys 60Hz"]
- DCA "Band". Mute group "Band". [conventions: "Band: bass, guitars, keys and horns."]
- Monitor sends: instructions only. No mix bus, no FX. Main: direct. A "Keys L"/"Keys R" pair becomes one stereo channel "Keys". [conventions: "Two inputs named as a Left/Right pair"]
- Gain 20 dB, trim 0 dB, phantom from the input list. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]

### Horns
- Regular channel, Amber. "Horns" and "Brass" mean the same. Presets: Trumpet "Trumpet"; Trombone "T Bone"; Alto sax "A Sax"; Baritone sax "B Sax"; Tenor sax "B Sax"; generic sax "B Sax". HPF from preset, else 100 Hz. [conventions: "Horns-Amber"] [domain: "\"Horns\" and \"Brass\" generally mean the same thing."] [conventions: "Generic sax \"B Sax\""] [conventions: "horns 100Hz"]
- DCA "Band". Mute group "Band". [conventions: "Band: bass, guitars, keys and horns."]
- Monitor sends: instructions only. FX: none.
- Mix bus: "Horns" (POST, 0 dB). Main: only through the "Horns" bus. [conventions: "\"Horns\": every horns-category channel."]
- Gain 20 dB, trim 0 dB, phantom from the input list. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]

### Vocals
- Regular channel, Green. "VOX" is shorthand for vocals. Preset "Vocal" (lead and backing). HPF from preset, else 120 Hz. [conventions: "Vocals-Green"] [domain: "\"VOX\" is shorthand for vocal."] [conventions: "Lead and backing vocals: \"Vocal\""] [conventions: "vocals 120Hz"]
- DCA "Vocals". Mute group "Vocals". [conventions: "Vocals: every vocals-category channel."]
- Monitor sends: instructions only.
- Mix bus: "Vocals" (POST, 0 dB). FX: "Vox Verb" POST at -6 dB. Main: only through the "Vocals" bus. [conventions: "\"Vocals\": every vocals-category channel."] [conventions: "include every vocals-category channel, POST fader at -6dB."]
- Gain 20 dB, trim 0 dB, phantom from the input list. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]

### Playback (tracks)
- Covers the band's own backing tracks ("tracks", "trax"), mono or stereo, one or many. Regular channels, Yellow, no preset, no HPF. A "Playback L"/"Playback R" pair becomes one stereo channel "Playback". [conventions: "Playback-Yellow"] [conventions: "Playback: no preset."] [conventions: "Playback gets none."] [domain: "These are *part of the band's sound*"]
- DCA "Playback". Mute group: none. [conventions: "Playback: playback channels, and any aux channel the show adds for music."]
- Monitor sends: instructions only. No mix bus, no FX. Main: direct. [conventions: "Every channel that is in no mix bus goes to Main directly."]
- Gain 20 dB for a channel on a physical mic/line socket; none on a digital source (USB, card, player). Trim 0 dB. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."] [domain: "A digital source (USB audio, an expansion card, a player)"]
- Decided: a "misc" input-list row is a Playback channel (Yellow, Playback DCA, Main direct), and it is a regular channel, not an aux. The conventions give every input-list row a regular channel, and Playback is the only category for music feeds. [conventions: "Everything on the input list gets a regular channel."]

### Click/Guide
- Rows named click or guide (or both). Regular channel, Yellow, no preset, no HPF, like Playback. [domain: "there may be a channel called click, or guide"]
- Main routing: never to Main, not in any mix bus. Reaches only monitor busses. [domain: "these tracks must never be routed to the main mix, only to monitor busses."]
- DCA "Playback". Mute group: none. FX: none. Monitor sends only as the instructions list them.
- Gain 20 dB on a physical socket, none on a digital source. Trim 0 dB.
- Decided: Click/Guide sorts after the other playback channels, as the last channels. It is in Playback, which is last in the order. [conventions: "and playback last."]

### Speech
- Host, MC, podium, pastor and speaker rows. Regular channel, preset "Speech". [domain: "\"Host\" or \"MC\" or \"Podium\" or \"Pastor\" or \"Speaker\" are all spoken word or speech inputs."] [conventions: "Speech (an MC, host, a podium): \"Speech\""]
- HPF from the preset. Colour: not set.
- DCA: none. Mute group: none. No mix bus, no FX. Monitor sends: instructions only. Main: direct.
- Gain 20 dB, trim 0 dB, phantom from the input list. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Decided: Speech is not "band" and gets no DCA or mute group, because the conventions list none for it and the domain says it is almost never part of the band. [domain: "They are almost never a part of the band."]

### Crowd / ambient
- Crowd, ambient and room mics. Regular channel; mono or stereo as the input list says. Colour not set, no preset, no HPF.
- Main routing: never to Main. No mix bus, no DCA, no mute group, no FX. Monitor sends: instructions only. [domain: "It is always routed to monitor or recording busses, never to the mains."]
- Gain 20 dB, trim 0 dB, phantom from the input list. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."]
- Decided: Crowd gets no colour, DCA or mute group because no rule exists for it. Its Main exclusion overrides the "Every channel that is in no mix bus goes to Main directly." line. [domain: "never to the mains"]

### Band, Instruments (grouping words)
- Decided: "Band" in the DCA sense means bass, guitars, keys and horns only; drums and vocals have their own DCAs. In the mute-group sense it means drums, bass, guitars, keys and horns. [conventions: "Band: bass, guitars, keys and horns."] [conventions: "Band: every drums, bass, guitars, keys and horns channel."]
- "Instruments" means drums (including percussion), bass, guitars, keys and horns. It excludes vocals and tracks. [domain: "\"Instruments\" normally does not include the vocals or backing tracks."]

### Aux strips
- Only for sources the show's instructions add (external feeds). Never created for an input-list row. [conventions: "Aux channels are for sources the show's instructions add."]
- No HPF. [domain: "An aux strip has no high-pass filter"]
- A music aux joins DCA "Playback". [conventions: "any aux channel the show adds for music."]
- Decided: an aux on a physical socket gets gain 20 dB and trim 0 dB; an aux on a digital source gets trim 0 dB and no gain. Decided: aux fader starts at -144 dB. Both follow the channel rules. [conventions: "Start every channel fader all the way down, unmuted."]

## Busses
Order: monitor busses, then mix busses, then FX busses. [conventions: "Bus order: monitor busses first, then mix busses, then FX busses."]

1. Monitor busses, one per stage mix in the show's instructions (named for who it is for). [conventions: "Monitor busses: one per mix on stage, named for who it is for."]
   - Wedge mix: MONO. IEM mix: STEREO. [conventions: "A wedge mix is a MONO bus. An in-ear (IEM) mix is a STEREO bus."]
   - Colour White. Fader -12 dB. Never to Main. Destination: the output the instructions give it. [conventions: "Monitor busses are White."] [conventions: "Monitor bus faders at -12dB. Never routed to Main."]
   - Senders: only channels the instructions list, PRE fader at -18 dB. All others are off. [conventions: "Sends to monitor busses are PRE fader."]
2. "Drums": STEREO, Red, to Main at unity, fader 0 dB. Senders: every Drums channel, POST at 0 dB. Preset "Mix Bus". Created only if it has channel feeds. [conventions: "Mix busses are STEREO, routed to Main at unity, faders at unity."] [conventions: "Every mix bus takes the bus preset \"Mix Bus\""] [conventions: "A mix bus with no channel feeds is left out of the plan."]
3. "Horns": STEREO, Amber, to Main at unity, fader 0 dB. Senders: every Horns channel, POST at 0 dB. Preset "Mix Bus". Created only if it has channel feeds. [conventions: "Mix busses take their category's colour."]
4. "Vocals": STEREO, Green, to Main at unity, fader 0 dB. Senders: every Vocals channel, POST at 0 dB. Preset "Mix Bus". Created only if it has channel feeds. [conventions: "Channel sends to them are POST fader at unity"]
5. "Vox Verb" (FX): STEREO, Purple, to Main at unity, fader 0 dB. Preset "Vox Verb". Senders: every Vocals channel, POST at -6 dB. [conventions: "FX busses are STEREO, routed to Main at unity, faders at unity."] [conventions: "FX busses are Purple."]
   - Decided: created only if the show has Vocals channels. A bus with no feeds is not created, the same rule as for mix busses. [conventions: "A mix bus with no channel feeds is left out of the plan."]
   - Decided: "Snare Verb" is not created. The conventions name it only as an example preset and list no channels for it. [conventions: "(\"Vox Verb\", \"Snare Verb\")"]

## Outputs
- Main 1: name "PA", patched to local XLR outputs 1 and 2, fader at unity (0 dB). [conventions: "Main 1 is the PA. Name it \"PA\", patch it to local XLR outputs 1 and 2, fader at unity."]
- Matrix: none. Decided: no matrix is created because the conventions give no matrix rule. [domain: "Either a Main bus or a Matrix bus can be the final step before the physical outputs."]
- Mix and FX busses reach Main 1 at unity. Monitor busses never go to Main; each is patched to the output the instructions give it. [conventions: "Each one is patched to the output the show's instructions give it."]

## DCAs
- "Drums": every Drums channel. [conventions: "Drums: every drums-category channel."]
- "Band": Bass, Guitars, Keys, Horns channels. [conventions: "Band: bass, guitars, keys and horns."]
- "Vocals": every Vocals channel. [conventions: "Vocals: every vocals-category channel."]
- "Playback": Playback and Click/Guide channels, plus any aux the show adds for music. [conventions: "Playback: playback channels, and any aux channel the show adds for music."]
- "FX": every FX bus. [conventions: "FX: every FX bus."]
- All DCA faders start at unity (0 dB). [conventions: "DCA faders start at unity."]
- Decided: a DCA with no members is not created, because an empty DCA controls nothing. DCAs are remote controls only and carry no signal. [domain: "DCAs, while assigned to channels in a similar manner to a bus, do NOT create a signal path"]

## Mute groups
- "Band": every Drums, Bass, Guitars, Keys and Horns channel. [conventions: "Band: every drums, bass, guitars, keys and horns channel."]
- "Vocals": every Vocals channel. [conventions: "Vocals: every vocals-category channel."]
- "FX": every FX bus. [conventions: "FX: every FX bus."]
- Decided: a mute group with no members is not created, for the same reason as DCAs.

## Head amps
- Mic or DI on a physical socket: gain 20 dB, trim 0 dB. Phantom comes only from the input list's phantom column. [conventions: "Start every channel's head-amp gain at 20dB and its trim at 0dB."] [conventions: "Phantom power comes from the input list's phantom column, never from here."]
- Digital source (USB, card, player): no gain, no phantom; trim 0 dB. [domain: "A digital source (USB audio, an expansion card, a player) arrives already levelled and has no head amp and no phantom"]
- Aux strip: physical socket gets gain 20 dB and trim 0 dB; digital source gets trim 0 dB only. See the Aux strips decision above.
- A shared socket has one gain and one phantom setting for all strips on it. [domain: "One socket has one head-amp gain and one phantom setting, because there is one preamp."]

## Patching and channel order
- Patch each input to the socket the input list gives. [conventions: "Patch input sockets according to the supplied input list."]
- Overflow: none. Every input-list row gets a regular channel; nothing is moved to an aux. [conventions: "Everything on the input list gets a regular channel."]
- Stereo pairing: two inputs named as a Left/Right pair (OH L/OH R, Keys L/Keys R, Playback L/Playback R) become one stereo channel named without the L/R. The channel's patch points at the first socket. [conventions: "become one stereo channel, named without the L/R"] [domain: "the stereo channel's patch points at the *first* of the two."]
- Decided: if a pair's two sockets are not consecutive and odd-first, build a user patch over them (slots that are adjacent and odd-first) and patch the channel to that. The hardware only pairs consecutive sockets starting on an odd one. [domain: "A WING forms a stereo pair only from two **consecutive** sockets starting on an **odd** one"]
- Pairs not named as Left/Right pairs stay separate mono channels. [domain: "Merging rows because their names end in L and R will be wrong often enough to matter."]
- Channel order: drums, bass, guitars, keys, horns, vocals, playback last. [conventions: "Channel order: drums, then bass, guitars, keys, horns, vocals, and playback last."]
- Drum order: kick, snare, hi hat, toms high to low, overheads, then percussion. [conventions: "Drum kit order: kick, snare, hi hat, toms from high to low, then overheads."]
- Decided: Speech, then Crowd/ambient, go after vocals and before playback, because the order line lists neither. Within a category, keep input-list order. Playback order: tracks, then click/guide.

## Faders
- Every channel (and any aux): -144 dB (fully down), unmuted. [conventions: "Start every channel fader all the way down, unmuted."] [domain: "On the wire, WING's floor is exactly -144."]
- Monitor busses: -12 dB. [conventions: "Monitor bus faders at -12dB."]
- Mix busses and FX busses: 0 dB. [conventions: "Mix busses are STEREO, routed to Main at unity, faders at unity."]
- Main 1 "PA": 0 dB. DCAs: 0 dB.
- Sends: monitor sends -18 dB (PRE, only those listed); mix bus sends 0 dB (POST); Vox Verb sends -6 dB (POST).

## Lines with no effect
- [conventions: "Alert if any mix bus or FX buss is muted, or fader is < -40dB (Low fader)"] Monitoring alerts only; they set nothing in the layout.
- [conventions: "Alert if any active main or matrix bus is muted or fader is < -40dB"] Monitoring alert only.
- [conventions: "Alert if any active DCA fader < -30dB or muted"] Monitoring alert only.

## Category table
```json
[
  {"name": "Drums", "aliases": ["drums", "drum", "drum kit", "kit", "percussion", "perc"], "color": "Red", "dca": ["Drums"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Bass", "aliases": ["bass"], "color": "Blue", "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Guitars", "aliases": ["guitars", "guitar", "gtr", "gtrs"], "color": "Pink", "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Keys", "aliases": ["keys", "keyboards", "keyboard", "piano"], "color": "Cyan", "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Horns", "aliases": ["horns", "horn", "brass"], "color": "Amber", "dca": ["Band"], "mute_group": ["Band"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Vocals", "aliases": ["vocals", "vocal", "vox", "backing vocals", "bgv"], "color": "Green", "dca": ["Vocals"], "mute_group": ["Vocals"], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Playback", "aliases": ["playback", "tracks", "track", "trax", "misc"], "color": "Yellow", "hpf_hz": null, "dca": ["Playback"], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Click/Guide", "aliases": ["click", "guide", "click/guide"], "color": "Yellow", "hpf_hz": null, "dca": ["Playback"], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false},
  {"name": "Speech", "aliases": ["speech", "host", "mc", "podium", "pastor", "speaker"], "color": null, "dca": [], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": true},
  {"name": "Crowd", "aliases": ["crowd", "ambient", "room"], "color": null, "hpf_hz": null, "dca": [], "mute_group": [], "gain_db": 20, "trim_db": 0, "fader_db": -144, "main_direct": false}
]
```

## Instructed strips
```json
[]
```
