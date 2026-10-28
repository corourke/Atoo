# Audio domain knowledge

Things that are true across engineers, bands and venues — as distinct from
**console facts** (fixed by the hardware) and from **one engineer's
conventions** (their own file, which is policy, not knowledge).

---

## Every input needs an output

All channels need a path to at least one final output, either to the Main L/R bus or included in one of the mix busses. Note that DCAs, do NOT create a signal path, they are a remote control on the assigned channel faders only. Also, assignments to a monitor bus typically do not satisfy the need for a channel to be routed to the final output (the one exception being a click track.)

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

An aux strip has no high-pass filter (no `flt` node at all on WING), which
is usually fine for a line-level feed and would not be fine for a source
you intended to process.

The word "misc" on an input list often covers both kinds. Do not treat
"misc" as automatically meaning aux — look at what the source actually is.

## Every input is mono

There is no such thing as a stereo input socket. A socket is one jack
carrying one signal. **Stereo exists on channels and busses, never on an
input.**

A "stereo source" is therefore two mono inputs that someone has decided
belong together. On a WING that decision is recorded at the source: both
sockets get `mode: "ST"`, and the stereo channel's patch points at the
*first* of the two.

```
LCL 15: mode='ST'  name='Keys 1'     two mono sockets, flagged as a pair
LCL 16: mode='ST'  name='Keys 1'
ch 'Keys 1': in.conn = LCL/15        the channel references only the first
```

Two consequences worth holding onto:

**Pairing is a decision, not something you can read off the names.** In
the same show as the Keys pair above, `OH L` and `OH R` are two
independent **mono** channels — overheads deliberately kept separate so
they can be panned and processed individually. An engineer who wanted one
stereo overhead channel would have said so. Merging rows because their
names end in L and R will be wrong often enough to matter.

**An input list that lists L and R separately is correct, not sloppy.**
That is what the physical world looks like and what bands send you. Two
rows, two XLRs, two sockets.

### The two halves have to be next door to each other

A WING forms a stereo pair only from two **consecutive** sockets starting
on an **odd** one: 1+2, 15+16, 23+24. Never 2+3, never 1+5. This is the
routing hardware and not a preference — asked for an even-first pair the
desk refuses and snaps it back — so "patch the keys to LCL 7 and LCL 12"
is not a thing that can be asked for, however sensible it looks written
down.

When the cabling genuinely cannot give you that — the two halves land on
different stage boxes, or on two playback tracks set apart — the desk has
its own way round it, called a **USER SIGNAL** or a **USER PATCH**. These
are virtual sources. You tell the desk "slot 25 is card input 1, slot 26
is card input 33", and then patch the channel to slots 25+26, which *are*
adjacent and odd-first. The pair the hardware sees is legal; the two
things feeding it can be anywhere.

What separates the two is where the audio comes from. A **user signal**
takes an existing strip — a channel, an aux, a bus, a Main, a Matrix —
which is how you feed something already mixed back in somewhere else. A
**user patch** takes a physical jack directly, with no strip in between,
and that is the one that matters for an input list.

This type of configuration will need to be stated on the input list or in `instructions.md`
when a show needs it, because nothing about two socket numbers on a page
tells anybody that the pair is to be one stereo channel.


## One input can feed more than one channel strip

The usual case is one physical input to one channel strip, and that is
what most input lists describe. But a second strip on the **same socket**
is a normal, deliberate thing to ask for, and there are two common
reasons:

**A separate strip for monitors.** The same microphone, processed
differently for the wedges or in-ears than for the house. The FOH strip
and the monitor strip want different EQ, different compression and
different sends, and the only way to have both is two strips off one
input.

**A socket reused between acts.** At a festival one XLR might be a trumpet
for one band and a saxophone for the next. Two strips, each named and
processed for its own act, and whichever one is in use that set.

This is not the same as two strips accidentally patched to one socket,
which is a mistake. The difference is that a deliberate share **will be
called out** -- either the input list says so, or the show's
`instructions.md` does. If nothing says so, treat it as the mistake.

Two things follow whenever a socket is shared:

**The strips cannot inherit their name from the source.** A WING strip
displays the name, colour and icon of the socket it is patched to unless
"Link Customization to Source" is turned off (`clink`). One socket cannot
carry two names, so sharing means **unlinking both strips and naming each
one directly**. The socket itself gets a composite or generic name --
something that makes sense for the jack rather than for either strip.

**They share everything physical.** One socket has one head-amp gain and
one phantom setting, because there is one preamp. Two strips off it can
differ in everything *after* the preamp -- EQ, dynamics, sends, fader --
and in nothing before it. An input list asking for 48V on one of them and
not the other is asking for something the hardware cannot do.


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

## "In use" is not the same as "has a setting on it"

A channel, aux or bus is **in use** when it is named, when something is
patched into it, or when it is sending somewhere. A bus is also in use when
something is sending *to* it. That is the whole of it, and the reason it is
worth writing down is the other half: a console out of its box already has
settings on everything.

A WING Compact ships with all forty channels routed to Main 1, the first
twenty-four patched from their own local socket, eight of the sixteen
busses routed to Main 1 with their faders at unity, and aux 1 and 2 patched
from the USB player and the media player. None of that is a decision
anybody made about a particular show. So a **factory default is not evidence of
use**: channel 3 sitting on local input 3 says nothing, the media player on
aux 2 says nothing, and neither does anything routed to Main 1 — that is
where a WING routes everything before it is told otherwise. Move a channel
to a different socket, give it a name, send it to a bus, or route it to
Main 2, and it is in use, because each of those took a deliberate act.

Which patches a desk arrives with is a fact about the **model**, not about
WINGs in general — a full-size WING has eight local inputs where the
Compact has twenty-four, so its channels cannot all arrive on their own
local socket. The list we have measured is the Compact's, read off an
initialized board and
written down in `console_facts.FACTORY_INPUT_PATCHES`, which is the
console-facts file rather than this one because it is fixed by the
hardware. On a model nobody has measured, the only default assumed is
channel n on local input n; anything else that desk came with will read as
in use until somebody captures one and writes down what it really ships
with.

This matters to anyone reading a desk rather than writing one: "how much of
this console is actually in the show" is a question you answer by looking
for what somebody *did*, not by counting what is switched on.

## Physical outputs

Engineers name output destinations by what they are plugged into. "XLR outputs" or "the XLRs" normally means the console's local outputs. "FOH" means the main mix. Stage boxes get called by their protocol ("AES50-A") or their position ("the stage box", "upstage left").
