# Using Atoo

Atoo is said "A-two": your A2, the second engineer at the desk.

Atoo turns an input list and your own written conventions into a
complete show setup for a Behringer WING, writes it to the desk,
validates every value, and watches the desk for mistakes. A full browser
UI is included or use it on the command line.

## Start here

In this order, the first time:

| Page | For |
|---|---|
| [Why Atoo?](why.md) | whether it is worth your time, against what you already do |
| [Installing Atoo](install.md) | on a Mac, step by step: Homebrew, pipx, Python, Atoo, then `atoo init` and `atoo ui` |
| [Installing without Homebrew](install-without-homebrew.md) | Python and pipx another way, on a Mac, Linux or Windows |
| [Try the Demo show](demo.md) | Build, Apply and Watch on a simulated desk, in five minutes |
| [Testing on your desk](testing-on-your-desk.md) | your own WING: its address, a saved show, `a2 ping`, then read-only checks, a write and its undo |
| [Configuring Atoo](configuration.md) | your house conventions, presets and desk, set once |
| [Setting up an AI provider](ai-provider.md) | the model that writes your plans, and its API key |
| [Change the Demo show](change-the-demo.md) | your first build, on a copy of the Demo, then a patch onto the desk |

## In the browser

| Page | For |
|---|---|
| [Build a show](build-a-show.md) | a new show: the input list, tonight's instructions, **Build plan**, and reading the findings |
| [Apply a plan to the desk](apply-to-desk.md) | **Ping**, the four steps: the pre-flight, **Preview** (the desk as scribble strips), writing, reading the result, undo |
| [Patch a show that is already on the desk](patch-a-show.md) | the horns at 6pm: a change typed in plain English, nothing else moved |
| [Watch the desk during a show](watch-a-show.md) | live findings, and your own watch conditions |

## The files you write

| Page | For |
|---|---|
| [Writing an input list](input-lists.md) | what is plugged in: columns, sockets, stereo pairs |
| [Writing conventions](conventions.md) | how you set up a desk, in your own words, and how it is read |
| [Channels that are not on the input list](extra-strips.md) | talkback, playback and the strips you want at every show, asked for in a sentence |
| [Conventions reference](conventions-reference.md) | the levels vocabulary, the desk's eighteen colours, and the resolved file Atoo writes beside yours |
| [Using channel presets](presets.md) | your own `.chn` presets, and what they are called |
| [Bus presets: mix and FX busses](bus-presets.md) | a mix bus's compressor, or an FX bus's reverb or delay, from your own `.bus` export |
| [Show bundles](show-bundles.md) | one show's folder, and what each file in it is |
| [Watch conditions](watch-conditions.md) | your own alerts for **Watch**: the Kick stays on LCL 5, the PA never mutes |

## When something goes wrong

| Page | For |
|---|---|
| [Reading findings](reading-findings.md) | what ERROR, WARNING and INFO mean, the verdicts, and the codes |
| [Troubleshooting](troubleshooting.md) | can't reach the desk, a build that fails, a refused plan, the UI not starting |
| [Where Atoo needs work](limitations.md) | what is not built or not yet proven on a desk, before you rely on it |
| [Words Atoo uses](glossary.md) | one name for each thing: Choices, Arm, History, the journal, a show bundle |
| [Questions](faq.md) | is it AI slop, will it touch my desk mid-show, what if it goes wrong |

## From the command line

| Page | For |
|---|---|
| [Command-line quickstart](quickstart.md) | input list to plan to desk to proof, end to end, with `atoo` commands |
| [How a show gets built](pipeline.md) | the stages, which one gates, and `resolve` |
| [Learning from a batch of builds](lessons.md) | `lessons`: the questions your builds keep asking, as candidate lines for your conventions |
| [Applying a plan](applying.md) | `apply`: preview, reading the result, flags, exit codes |
| [What a full apply changes on the desk](what-apply-changes.md) | the reset to initialized, unpatching unbuilt strips, Main routes, talkback, alternate inputs, expansion bays |
| [The journal](journals.md) | what every write leaves behind, and how far back undo reaches |
| [Undoing a write](undo.md) | `undo`: step back one write, keeping everything changed since |
| [Patching a running show](patch.md) | `patch`: a typed change onto a desk already in use |
| [Patching from a rebuilt plan](amend.md) | `amend`, from the command line: the difference between two plans, onto a desk already in use |
| [One plan, two desks](two-desks.md) | a primary and a backup, or a plan for a different WING |
| [Checking a desk](audit.md) | `audit`: one read, signal tracing, and checking a desk against its plan |
| [Watching from the command line](watch.md) | `watch`: the same rules on a loop, reporting what changed |
| [Command reference](cli-reference.md) | every command and flag (generated from the code) |
| [Installing from a checkout](install-from-checkout.md) | running Atoo from a clone of its repository, in a virtualenv |

