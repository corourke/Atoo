# Questions

The questions a careful engineer asks before letting a new tool near a
desk, with short answers and a link to the page that says more.

## Is this AI slop?

Here is exactly where AI is used, and what holds it in check:

- A model **drafts** the plan from your input list and conventions, on
  your laptop, before the show.
- Code with no model in it **checks** every value in the draft against
  the desk's real limits: sockets this model has, stereo pairs it can
  form, values in range. A setting the desk cannot hold is an error, and
  nothing is written.
- **Every write is read back** from the desk, and anything that did not
  land is named.
- **Every choice the tool made** that your files did not state is
  announced as an INFO finding, with what it was decided from
  ([Reading findings](reading-findings.md)).

Most of the code was written with AI coding agents, to the design and
under the review of a working live-sound engineer, and tested against a
real WING Compact. There are about 4,500 automated tests. Read the plan
it produces, on the [Demo show](demo.md), and judge that.

## Will AI touch my desk during a show?

No. The model is never connected to the desk: it writes a file, before
the show, and ordinary code applies it after you have read it. Watch,
the part meant for a show, only reads, and uses no model.

## What if the model makes up a setting?

A setting the desk cannot physically have is refused before anything is
written. A choice that is possible but that you did not state, such as a
bus being mono or stereo, is made and printed as a note, so you see it
in the plan rather than at soundcheck. The model is told to set an EQ
band, a gain or a trim only where your conventions state one; your sound
otherwise comes from your own [channel presets](presets.md). The
optional critic pass flags a value that appears nowhere in your files.

## Why does it need a model at all?

Because your rules stay in your own English, not in a format you have
to learn. Reading *"drums go to DCA 1 unless it is a festival
changeover"* is what the model is for. Verify, apply, undo, audit, watch
and the Demo show run with no model.

## Does my show go to the cloud?

Your input list and conventions go to the model you set up, with your
own key: Claude, which Atoo is built and tested on. A local model
through Ollama keeps them on your own machine, but local models have not
worked well so far
([Setting up an AI provider](ai-provider.md)). There is no
Atoo account, and nothing is sent anywhere else.

## What does a build cost?

Your AI provider bills each build to your key. Each call to the model
shows what it cost on Build step 04 while the build runs, and the build
record in the show's `builds/` folder keeps it. Two recorded builds of a
38-channel festival show cost about $0.35 and $0.60 on Claude, with the
critic pass on, using an earlier default model and effort. A smaller
show costs less. Verify, apply, undo, audit, watch and the Demo show
cost nothing: they use no model.

## What does it do to my desk?

A **full apply takes the whole desk**: it first puts the desk back to
its initialized state, leaving the network, clock, cards and monitor
listening alone, then writes the plan and reads it back. Save your show
first ([Apply a plan](apply-to-desk.md)). A **patch** adds or changes
only what you typed and proves nothing else moved
([Patch a show](patch-a-show.md)). Nothing is written until you tick
**Arm** on the Apply screen and press its write button.

## What if it goes wrong?

Every write is recorded with the values it replaced. Undo puts back the
newest one, address by address, and leaves alone anything changed since
([Undoing a write](undo.md)). A saved show on the desk is always a
reload away.

## What are you selling?

Nothing to engineers. It is free and open source, to use on any show,
paid gigs included, with no account to open with us (a
build uses your own AI provider's key). A company that wants to build it
into a closed or commercial product can get a commercial licence by
agreement. It was written by a working live-sound engineer and
consultant for real shows.

## Who maintains it in six months?

Its author uses it on real shows, which is why it exists. It is open
source: the code, its tests and these pages are in its repository, so
someone else can pick it up.

## Which consoles?

Behringer WING only: the Compact, the full-size WING and the Rack. Full
applies are proven on a Compact; the others less so
([Where Atoo needs work](limitations.md#consoles)).

## Will it mix for me?

No. Nothing moves a fader during a show. It sets the desk's starting
state and gets out of the way.

## How is it different from what I use now?

[Why Atoo?](why.md) compares it with building by hand or in WING
Edit, copying last month's show, the desk's presets, and a spreadsheet
input list.
