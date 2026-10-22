# Why Atoo?

When building show files, I noticed myself doing much the same thing for every new act, 
either patching from scratch or copying an existing showfile, following my same patterns, 
and it was both tedious and error prone. Festival patches were always a compromise, and 
when things got exciting close to doors, it was all too easy to making a routing mistake or
forget something simple. 

I found some prior work in this area, in terms of generating and auditing show files,
but I wanted to take a different approach and start with written audio engineering knowledge, 
along with my own preferences and conventions that could be applied to any show. I also wanted
to be able to verify the board against the input list, and logically trace the signal path
for every channel from input to final output. 

Lastly, I wanted to be able to type in a change (my favorite example is when an unannounced 
horn section showed up 30 minutes before doors) and have the program just figure it out, 
including busses, DCAs, presets, all of it and verify the correctness of the new layout. 
And if I managed to do something dumb, like mute the drum bus, or double patch the last minute
backup vocalist to both the main and vocal busses, I wanted something that would alert me 
before the show started.

## What every show has in common

- **Your conventions live in your head.** Kick on 1, drums in DCA 1, every
  vocal gets your vocal preset and a send to the in-ears. You do it the
  same way every show, by hand, from memory.
- **The input list changes after the work is done.** An extra singer at
  5pm, the horns confirmed at 6pm, and part of the job is redone in a
  hurry on a desk that already has a mix on it.
- **The mistakes are silent, and they are about signal path.** A source
  muted three steps upstream, a bus with no output. Every screen looks
  fine on its own.
- **Remote writes fail silently.** A value sent over the network to the
  wrong address, or with the wrong type, reports success and changes
  nothing.


## Why not stick with what you already use?

| How you do it now... | How Atoo helps |
|---|---|
| Building the show file by hand, on the desk or in WING Edit | Atoo saves time, allows quick reconfiguration, and checks the configuration for errors |
| Copying last month's show file | Atoo lets your show file perfectly match your act without compromises. |
| Using the desk's channel presets and libraries | Atoo also sets up all your routing: mix/FX/monitor busses, DCAs, mains and matricies. |
| Hoping you got everything right | Atoo verifies proper routing, makes dozens of common checks, and checks your setup against your input list. |

## The ways you already do it

### By hand, on the desk or in WING Edit

**Good at:** total control, and no new tool to learn.
**Cannot:** check itself, or carry over to a different band. Every show
costs the same hours, and nothing tells you that channel 14 never got
its high-pass.

### Copying last month's show file

**Good at:** a band that comes back with the same line-up. If nothing
changed, a saved show is faster than anything else, Atoo included.
**Cannot:** adapt to a different band. Twelve inputs where there were
thirty, or a second keyboard, and the old layout fights you: you are
editing someone else's show rather than building yours.

### The desk's channel presets and libraries

**Good at:** a strip's sound. Your vocal chain, your kick EQ.
**Cannot:** lay out the show around the strips: which socket feeds which
channel, the stereo pairs, the busses, the sends and the DCAs. Atoo
uses your presets for the sound, and does the layout itself
([Using channel presets](presets.md)).

### A spreadsheet input list, typed into the desk

**Good at:** agreeing the list with the band and the stage crew.
**Cannot:** confirm the desk matches it. The list is typed twice, once in
the spreadsheet and once on the desk, and nothing compares the two.

## Other tools for the job

Other tools take on parts of this job. Most do one of the jobs below.

### Show-file generators

**Good at:** turning a channel list into a show file, quickly.
**What Atoo adds:** a generator starts from a template or a
questionnaire, so each show starts from scratch again. Atoo starts from
your written conventions, which grow from show to show. Atoo also writes
to the desk itself rather than handing you a file to load over the
show. It reads every value back, and it can change the show later
without rebuilding it.

### Show-file checkers

**Good at:** a list of common mistakes, found before the show.
**What Atoo adds:** its checks read the desk itself, not a saved file,
and never guess what a channel is from its name. It also checks the
desk against your input list and your conventions, follows a signal
from the microphone to the loudspeaker, and keeps checking while the
show runs.

### Plain-language remotes

**Good at:** quick edits by typing, such as names, colours and routes.
**What Atoo adds:** a typed change goes through the same checks as a
full build. It is previewed, written, read back, and can be undone on
its own, and nothing else on the desk moves.

## What Atoo does differently

- **Your conventions build up, show after show.** They are one file of
  house rules in plain English, not a template show to copy. Write
  *"every vocal gets the vocal preset and a pre-fader send to that
  singer's in-ear"* once, and every show with vocals gets it, whether a
  four-piece tonight or a twelve-piece next week. A model drafts
  tonight's plan from those rules and the input list.
- **Checked before it is written.** Code checks the draft against the
  desk's real limits and your conventions. A stereo pair that starts on
  an even socket, or a patch to a socket the desk does not have, is
  caught at your laptop, not at soundcheck. Anything the model chose
  that you did not state is announced, with what it was inferred from,
  so you can state it next time.
- **Checked against the input list.** Every input on the list becomes a
  channel, and no channel appears that nobody will plug in. Phantom
  power is checked against each microphone on the list, and a ribbon
  mic is never left with 48V on. The list is typed once, and the desk is
  compared with it.
- **Written to the desk, then read back.** There is no show file to load
  over the top of your show. Each setting is written over the network
  and read back, and anything that did not land is named. Every write
  is journalled and can be undone.
- **A late change moves nothing else.** Type *"trumpet, sax and
  trombone on LCL 21-23, Band DCA"* at 6pm, and those three channels go
  into free strips with their presets, sends and DCA. The strips around
  them are read before and after the write to prove nothing else moved.
  The change can be undone on its own, and *"clear bus 5 and 6, add a
  stereo IEM bus on 5"* works the same way.
- **It reads the desk, not the names.** No check guesses what a channel
  is from its name. A strip called *Spare* that still feeds the mains is
  checked as what it is: its routing, patch, mute and fader.
- **It answers "why can I not hear this?"** Name a microphone and a
  loudspeaker, and it follows the signal between them across the desk.
  When the signal stops, it says how far it got and what stopped it,
  for example *"First break: ch 7's fader is at the floor"*, or that no
  route was ever built.
- **It watches the show against your rules.** It re-reads the desk
  every couple of seconds and tells you only what changed: the DI that
  got repatched, the Band DCA pulled to the floor, the playback fader
  left down.
- **It runs on your laptop.** There is no Atoo account and no
  subscription. Your show files stay with you, and the code is open
  source.

## What it costs you

- **Writing your conventions down is work.** A starter file is included,
  but the plan is only as good as what you state. If you always copy
  last week's show and that works, keep doing it.
- **A build needs your own AI API key**, which you pay for. Atoo is
  built and tested on Claude; local models have not worked well so far.
  A build takes minutes, not seconds.
- **WING only.** The Compact, the full-size WING and the Rack.

Next: [try the Demo show](../../README.md#try-it-in-two-minutes-with-no-desk),
or [install it](install.md).
