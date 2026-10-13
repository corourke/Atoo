# A natural-language conventions file example.

## Inputs
I like to patch drums first, then bass, guitars, keyboards, any strings or brass, 
then vocals, and misc stuff last. 
For the drum kit specifically: kick goes in before snare, then hi hat, then the 
rack toms then floor toms. Follow this with the
overheads (they're a stereo pair), and then whatever other percussion shows up.

## Channels
Just follow the patch order above. If two inputs are marked as a stereo
pair, they should end up sharing one linked stereo channel instead of two
separate ones.
Any inputs that are for background music, playback or any audio source that
is not a part of the band should be placed on an Aux channel. 

## Processing
I always want a highpass around 40 Hz on anything in the drums category.
Same idea for band instruments, but higher -- 80 Hz is fine.
Vocals need more low end removed, so put their high-pass up at 120Hz.

## DCAs
Drums DCA should grab every channel in the drums category.
Band DCA: same idea but for the band category.
Vocals DCA covers the vocals category, obviously.
And FX should pick up all the effects return busses.

## Mute Groups
Whatever's assigned to the Vocals DCA should also be in a Vocals mute group.

## Busses
Drums bus: every drums channel feeds it, and it feeds the main mix.
There's also a compressed "Drums Comp" version -- basically the same feed as the
regular Drums bus, but with a compressor inserted (-20dB threshold, attack 20ms, release 50ms) with the fader pulled down 6dB.
Vocals bus works the same way as drums, including the compressed version, just for vocals channels.
Create the following FX busses and send them to Main:
- VOX Reverb -- All vocal channels sent here at unity
- VOX Delay -- All vocal channels sent here at zero dB
- Snare Verb -- Snare channels sent here at unity
- INST Reverb -- All instrument channels (not drums) sent here at zero dB

## Output
Main should be the full mix, EQed so it sounds good for a recording.
Matrix takes its feed from Main and gets EQed to correct for the room.
Matrix output goes to output XLRs 1 and 2

## Watch
Let me know if any of the vocal channels get muted.
Also flag it if the Main fader ever drops below -10dB.
