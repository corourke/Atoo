# Questions

Please open an issue on https://github.com/corourke/Atoo/issues if any question is not resolved here.

## Was AI used to build Atoo? 

Yes. This is an AI-assisted project. Most of the code was written with AI coding agents, to the design and under the review of a working live-sound engineer, with close to 40 years in tech. The human effort has included dozens of hours spent in refinement and testing edge cases, against all three sizes of WING. The code base has over 6,000 automated tests.

## Where is AI used in the tool?

There are strong safeties built in to the workflow, and you are always free to reject any action. 

- An AI model drafts the show plan from your input list and conventions.
- Oppositional code (no AI) checks every value in the draft against the desk's real limits, and the input list intent. The AI is given a chance to correct errors and if the plan still does not pass validation, it is marked invalid.
- After this, there is no AI involved. The plan preview, apply and watch are code only. 

## Will AI touch my desk during a show?

No. The model is never connected to the desk: it writes a plan file, and ordinary code applies it after you have run a preview. Watch only reads, and uses no model.

## What if the model makes up a setting?

A setting the desk cannot physically have is refused before anything is written. A choice that is possible but that you did not state, such as a bus being mono or stereo, is made and printed as a note, so you see it in the plan preview before it is applied to the board. The model is told to set an EQ band, a gain or a trim only where your conventions state one; your sound otherwise comes from your own [channel presets](presets.md). The optional critic pass flags settings that you didn't spell out.

## Why does it need a model at all?

The main idea behind one of the two workflows is for domain knowledge, including an engineer's preferences around how a desk should be set up, can be expressed in natural language, and then applied to many shows. So the repetitive work would be eliminated while allowing setups to be perfectly tailored to each band, and also to allow for quick changes that are guaranteed to be correct.

## Does my show go to the cloud?

Your input list and conventions are sent to the model you specify. Atoo was built and tested on Claude Sonnet 5.5, and you supply your own API key. Various local models through Ollama are being tested, but none have been sufficient so far. (See: [Setting up an AI provider](ai-provider.md)). There is no Atoo account, and nothing is sent anywhere else.

## What does a build cost?

Your AI provider bills each build to your key. Each call to the model shows what it cost on Build step 04 while the build runs, and the build record in the show's `builds/` folder keeps it. Two recorded builds of a 38-channel festival show cost about $0.35 and $0.60 on Claude, with the critic pass on, using an earlier default model and effort. A smaller show costs less. Verify, apply, undo, audit, watch and the Demo show cost nothing: they use no model.

## What does it do to my desk?

A full apply updates the whole desk: it first puts the desk back to its initialized state, leaving the network, clock, cards and monitor listening alone, then writes the plan and reads it back. Save your show first ([Apply a plan](apply-to-desk.md)). A **patch** adds or changes only what you typed ([Patch a show](patch-a-show.md)). Nothing is written until you tick **Arm** on the Apply screen and press the write button.

## What if it goes wrong?

Every write is recorded with the values it replaced. Undo restores the prior settings, address by address, and leaves alone anything changed since the last apply. ([Undoing a write](undo.md)). And you can always restore from a saved snap.

## What are you selling?

Atoo is free and open source, to use on any show, paid gigs included, with no account to open with us (a build uses your own AI provider's key). A company that wants to build it into a closed or commercial product can get a commercial license by agreement.

## Who maintains it in six months?

Its author uses it on real shows, which is why it exists. It is open source: the code, its tests and these pages are in its repository, so someone else can pick it up if the author should meet an early demise.

## Which consoles?

Behringer WING only: the Compact, the full-size WING and the Rack. No other console, the X32 and M32 included.

## Will it mix for me?

No. Nothing moves a fader during a show. It sets the desk's starting state and gets out of the way.

## How is it different from what I use now?

[Why Atoo?](why.md) compares it with building by hand or in WING Edit, copying last month's show, the desk's presets, and a spreadsheet input list.

## Found something wrong?

Open an issue on the repository with what you ran, what you expected, and what you saw. [Reporting a problem](reporting.md) says what to send, and which files will help us make a speedy repair.
