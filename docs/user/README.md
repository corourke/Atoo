# Using Atoo

Atoo is said "A-two": your A2, the second engineer at the desk.

Atoo turns an input list and your own written conventions into a complete show setup for a Behringer WING, writes it to the desk, validates every value, and watches the desk for mistakes. A full browser UI is included or use it on the command line.

## Start here

In this order, the first time:

| Page | For |
|---|---|
| [Why Atoo?](why.md) | Whether Atoo is worth your time against what you already do |
| [Installing Atoo](install.md) | Install on a Mac or Linux with `uv`, step by step, then open `atoo ui`; Homebrew and pipx, and Windows, too |
| [Try the Demo show](demo.md) | Build, Apply and Watch on a simulated desk, in five minutes |
| [How Atoo works](how-atoo-works.md) | The three files you write, the plan, and build, verify, apply and watch |
| [Set up Atoo](configuration.md) | Your Atoo folder with `atoo init`, your desk with `a2 ping`, your presets, and the config file |
| [Setting up an AI provider](ai-provider.md) | The model that writes your plans, and its API key |
| [Build your first show](change-the-demo.md) | Your copy of the Demo show: change it with or without a model, apply it, watch it and undo |
| [Patch a show](patch-a-show.md) | A change typed in plain English, onto a show already on the desk |
| [Capture a desk you didn't build](capture-a-desk.md) | A desk that is already set up, as a show you can watch and edit |
| [The command line](quickstart.md) | One show from files to desk with `atoo` commands, then useful things to try |

## Using Atoo in the browser

| Page | For |
|---|---|
| [Build a show](build-a-show.md) | Show bundle files: the input list, your show-specific instructions, the **Build plan**, and the watch list |
| [Apply a plan to the desk](apply-to-desk.md) | The four steps: the pre-flight, **Preview** (the desk as tiles, each tile's changes in Detail), writing, undo |
| [Watch the desk during a show](watch-a-show.md) | Live findings, and setting watch conditions |

## The files you write

| Page | For |
|---|---|
| [Writing an input list](input-lists.md) | what is plugged in: columns, sockets, stereo pairs |
| [Writing conventions](conventions.md) | how you set up a desk, in your own words, and how it is read |
| [Channels that are not on the input list](extra-strips.md) | talkback, playback and the strips you want at every show, asked for in a sentence |
| [Conventions reference](conventions-reference.md) | the levels vocabulary, the desk's eighteen colors, and the resolved file Atoo writes beside yours |
| [Using channel presets](presets.md) | your own `.chn` presets, and what they are called |
| [Bus presets: mix and FX busses](bus-presets.md) | a mix bus's compressor, or an FX bus's reverb or delay, from your own `.bus` export |
| [Show bundles](show-bundles.md) | one show's folder, and what each file in it is |
| [Watch conditions](watch-conditions.md) | your own alerts for **Watch**: the Kick stays on LCL 5, the PA never mutes |

## When something goes wrong

| Page | For |
|---|---|
| [Reading findings](reading-findings.md) | what ERROR, WARNING and INFO mean, the verdicts, and the codes |
| [Troubleshooting](troubleshooting.md) | can't reach the desk, a build that fails, a refused plan, the UI not starting |
| [Words Atoo uses](glossary.md) | one name for each thing: Choices, Arm, History, the journal, a show bundle |
| [Questions](faq.md) | is it AI slop, will it touch my desk mid-show, what if it goes wrong |

## From the command line

| Page | For |
|---|---|
| [How a show gets built](pipeline.md) | the stages, which one gates, and `resolve` |
| [Capturing a desk](capture.md) | `capture`: a desk or a `.snap` as a show you can watch, with no model and nothing written |
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
| [Rules reference](rules-reference.md) | every rule `audit` and Watch can report (generated from the code) |
| [AI provider reference](ai-provider-reference.md) | Prompt caching on Claude, and what an OpenAI-compatible host is sent |
| [Reporting a problem](reporting.md) | what to send when something is wrong, and which files help |
| [Installing from a checkout](install-from-checkout.md) | running Atoo from a clone of its repository, in a virtualenv |

