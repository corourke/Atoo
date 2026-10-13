# Why Atoo

You already have ways to get a show onto a WING. This page says what each
one is good at, what it cannot do, and where Atoo is different. It
is not always the better choice.

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

## What Atoo does differently

- **Rules, not a template.** Your conventions are a file you write once,
  in plain English. A model drafts tonight's plan from them and the input
  list, whatever the size or shape of the band.
- **Checked before it is written.** Code checks the draft against the
  desk's real limits and your conventions. A stereo pair that starts on an
  even socket, or a patch to a socket the desk does not have, is caught
  at your laptop, not at soundcheck. Anything the model chose that you
  did not state is announced, with what it was inferred from, so you can
  state it next time.
- **Read back after it is written.** Every value is read back from the
  desk, and anything that did not land is named.
- **A late change moves nothing else.** Type *"trumpet, sax and trombone
  on LCL 21-23, Band DCA"*, and those three channels go into free strips.
  Nothing already in use moves, and the change can be undone on its own.
- **It watches the show against your rules.** The DI that got repatched,
  the Band DCA pulled to the floor, the playback fader left down.

## What it costs you

- **Writing your conventions down is work.** A starter file is included,
  but the plan is only as good as what you state. If you always copy
  last week's show and that works, keep doing it.
- **A build needs your own AI API key**, which you pay for. Atoo is
  built and tested on Claude; local models have not worked well so far.
  A build takes minutes, not seconds.
- **WING only.** The Compact, the full-size WING and the Rack.
- **Other tools exist.** [Wing Tools](https://wingtools.theta-tontechnik.de/)
  already reads values back after writing, and checks a snapshot against
  its own rules. Atoo differs in building from your rules, changing a
  running desk, and being free and local, not in reading back.

Next: [try the Demo show](../../README.md#try-it-in-two-minutes-with-no-desk),
or [install it](install.md).
