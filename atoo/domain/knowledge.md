# Audio domain knowledge

Things that are true across engineers, bands and venues — as distinct from
**console facts** (fixed by the hardware) and from **one engineer's
conventions** (their own file, which is policy, not knowledge).

---

## Every input needs an output

All channels need a path to at least one final output, either to the Main L/R bus or included in one of the mix busses. Note that DCAs, do NOT create a signal path, they are a remote control on the assigned channel faders only. Also, assignments to a monitor bus typically do not satisfy the need for a channel to be routed to the final output (the exceptions being a click or guide track, and a crowd or ambient mic.)

## Busses
There are three different classes of busses: mix busses (these consolidate parts of the band, like drums, vocals or a horn section), monitor busses (independent mixes for the musicians), and FX busses (used to share an FX processor with multiple channels). These are not dedicated like on some consoles, they are assigned from a pool of busses according to function. On the WING, there are also dedicated Main busses (or "Mains") and Matrix busses. Either a Main bus or a Matrix bus can be the final step before the physical outputs.

### A bus is itself mono or stereo

A bus has its own width, independent of the channels feeding it. A mono bus carries one signal and lands on one output socket; a stereo bus carries a left and a right and outputs to two sockets. This is not the same question as whether a *channel* is a linked stereo pair — that is a property of the physical sources on the input side, and a stereo bus is routinely fed by mono channels. Stage wedges are always mono; an in-ear mix is often stereo. A mix bus summed into the stereo Main is stereo, so its sources keep their panning. An FX bus (a reverb or delay return) is stereo as many effects work in stereo.

### Mix Busses
Channels sent to a mix bus are generally sent POST fader. The mix bus is then usually sent to the Main bus, POST fader, with the starting level at unity.

### Monitor Busses

A stage monitor mix (or just "monitor mix" or "IEM mix") is an ordinary bus routed to physical outputs instead of the main mix. There is no separate "monitor bus" object on a WING at all. "Wedge", "IEM", "cans" and "foldback" all describe what the mix is *for*, never a distinct kind of object.

Monitor sends from the channels are normally pre-fader, so that a front-of-house move doesn't change what a musician hears.

Send levels into monitors are a performance decision made at sound check and during the show. A conventions file can reasonably state the routing — which channels feed which monitor — and should generally not state the levels, because they are not a property of the show's structure.

### FX Busses

This type of bus consolidates different channels usually for the purpose of applying one or more audio effects to those channels as a group. Generally the channel send mode is GRP and the send level is fixed by the GRP setting. Channels are typically routed 'Dry' or direct to either a Mix or Main bus AND are routed to the FX bus, which adds the effect, and then routes to Main. For example, the un-affected dry sound of a vocal mic is routed to main and is sent to the Vocal Reverb bus, which adds just the ambient reverb signal (typically no dry signal as that is already handled by the direct routing from the channel to main--and its inclusion would cause comb filtering) and then is routed to main. The bus fader controls the amount of effect added. Sometimes, engineers prefer to send channels POST fader so that they can control the send level for each channel independently. (When a channel bus send is set to POST fader, both the channel fader position and the send level control the signal level sent to the bus.)

## Playback and tracks

These are two different things that both get called "playback", and the
distinction decides where they belong.

**The band's own tracks** — sometimes
labelled "tracks" or "trax". These are *part of the band's sound*: they sit in the
mix, get mixed during the show, and belong on **regular channels** where
possible. They may be mono or stereo, and there may be one or many. Do
not assume a single stereo pair. 

If there are multiple track channels, there may be a channel called click, or guide, 
or a combination of the two -- these
tracks must never be routed to the main mix, only to monitor busses. Click and Guide
are for the musicians on stage only. 

**External feeds** — background music between sets, audio from video
playback, a laptop or computer input, a phone. These are not part of the
band's performance and generally belong on **aux input strips**.

## Every input is mono

There is no such thing as a stereo input socket. A socket is one jack
carrying one signal. **Stereo exists on channels and busses, never on an
input.**  A "stereo source" is therefore two mono inputs that someone has decided
belong together.

Pairing is a decision, not something you can read off the names. `OH L` and
`OH R` are often two independent mono channels. Pair two inputs only when the
conventions or the input list say so.


## One input can feed more than one channel strip

The usual case is one physical input to one channel strip, and that is
what most input lists describe. But a second strip on the **same socket**
is a normal, deliberate thing to ask for, and there are two common
reasons: 1) a separate strip for monitors only, 2) a socket reused for different 
purposes between acts. 

A deliberate share will be called out, either on the input list or in the
show's `instructions.md`. If nothing says so, two strips on one socket is a
mistake.


## Category words engineers use

"Band" usually means all instruments (drums, bass, guitars, keyboards, and any strings or brass) plus the vocals and any backing tracks -- everything that makes up the music. 
"Instruments" normally does not include the vocals or backing tracks.
"Vocals", unsurprisingly, is all the vocal channels; "VOX" is shorthand for vocal.
"Horns" and "Brass" generally mean the same thing.
"Host" or "MC" or "Podium" or "Pastor" or "Speaker" are all spoken word or speech inputs. They are almost never a part of the band.
"Tracks" or "trax" means the band's own backing tracks (see "Playback and tracks" above).
"Crowd" or "Ambient" or "Room" generally refers to a mic that picks up the audience or the ambient sound in the room. It is always routed to monitor or recording busses, never to the mains. The channel can be either mono or stereo.

These are conventions, not laws. An input list defines its own categories, and the conventions file has to be read against *that* list rather than against an assumed vocabulary. When a term in the prose doesn't match any category the input list supplies, that is worth surfacing — the two documents disagree, and only a human knows which one is right.

## Fader, trim, gain and makeup are four different things

Confusing these is the single most likely way to write a plausible-looking
wrong value.

- **Fader** — the strip's own level. `ch.{n}.fdr`, `bus.{n}.fdr`. When an
  engineer says "the fader", this is always what they mean.
- **Trim** — digital input source level, `ch.{n}.in.set.trim`. Applied
  after the patch, independent of the head amp.
- **Gain** — the head amp on the physical socket, `io.in.{group}.{n}.g`.
  Shared by every channel patched to that socket. Only a physical mic/line
  input has one. A digital source (USB audio, an expansion card, a player)
  arrives already levelled and has no head amp and no phantom, so a "set
  the gain on each channel" means the channels that have a preamp, and a
  digital one's gain is rightly left unset. Trim applies to every channel.
- **Makeup gain** — a compressor's own output gain, `dyn.gain`. A
  compressor has no fader and no trim; its parameters are threshold,
  ratio, attack, hold, release, knee, detection, envelope, mix and makeup.

"Pull the fader down 6dB" is a statement about the strip, even when it
appears in the same sentence as compressor settings.


## Starting levels

A starting fader position is not a mixing decision; it is where sound check begins. Common choices: unity, fully down (−∞), or a few dB back to leave headroom. Busses are often started around -6dB for that reason.

Fully down has many names — "all the way down", "fully down", "-inf", "off". On the wire, WING's floor is exactly -144.

## Physical outputs

Engineers name output destinations by what they are plugged into. "XLR outputs" or "the XLRs" normally means the console's local outputs. "FOH" means the main mix. Stage boxes get called by their protocol ("AES50-A") or their position ("upstage left").

## Splits and recording feeds

A split is an engineering word, not something on the desk. On the desk an output socket is patched to a source, and a split is simply an output socket fed straight from an input socket rather than from a bus, a Main or a Matrix: the Dante module or a card sending every input to a recorder, USB recording, or an AES50 port carrying the inputs to a monitor desk. The desk offers an output 18 source groups: every input group (local, aux, AES50 A/B/C, StageConnect, USB, card, module, the USB player, AES/EBU), user signals and patches (USR), the oscillator, a bus, a Main, a Matrix, a send and the monitor.

A split carries the input before the channel strip: the preamp's gain, which lives on the socket, but no trim, filter, EQ, dynamics or fader. That is what a multitrack recording and a virtual soundcheck want. There is no "channel pre/post" source: a processed or post-fader feed goes through a user signal (USR), which takes a channel at a tap point, and the output is patched to that USR slot. Recording "every input one to one" means the inputs in channel order, one output socket each.

A processed feed is stated by the strip and its tap, not by the slot: "the lead vocal post-fader to USB 13" names the channel, says post, and names the socket. The desk has 24 user signals (USR 1-24); which one carries the feed is bookkeeping, chosen by code, the next one free. A stereo strip needs two, its left and its right, on two sockets. Pre-fader is after the channel's processing but before its fader, so the feed follows EQ and dynamics but not the mix; post-fader follows the fader as well.
