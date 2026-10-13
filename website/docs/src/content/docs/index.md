---
title: "Using Atoo"
description: "Atoo turns an input list and your own house conventions into a complete setup for a Behringer WING, writes it to the desk, reads every value back, and watches the desk during the show. Start with the…"
---

<!-- Generated from docs/user/README.md by tools/port_user_docs.py. Edit it there, then re-run the port. -->
Atoo turns an input list and your own house conventions into a
complete setup for a Behringer WING, writes it to the desk, reads every
value back, and watches the desk during the show. Start with the
browser; everything it does can also be done from the command line.

## Start here

| Page | For |
|---|---|
| [Why Atoo](/getting-started/why/) | whether it is worth your time, against what you already do |
| [Installing Atoo](/getting-started/install/) | getting it onto a laptop, and `atoo init` for a folder of your own |
| [Installing from a checkout](/getting-started/install-from-checkout/) | changing the code or running the tests: a virtualenv, the extras |
| [Setting up Atoo](/getting-started/configuration/) | your model and API key, house conventions, presets and desk, set once |
| [Try the Demo show](/getting-started/demo/) | Build, Apply and Watch on a simulated desk, in five minutes |
| [Testing on your desk](/getting-started/testing-on-your-desk/) | trying it on your own WING: the Demo, read-only, then a write and its undo, and how to report |

## In the browser

| Page | For |
|---|---|
| [Build a show](/build/build-a-show/) | a new show: the input list, tonight's instructions, **Build plan**, and reading the findings |
| [Apply a plan to the desk](/apply/apply-to-desk/) | **Ping**, the four steps: the pre-flight, **Preview** (the desk as scribble strips), writing, reading the result, undo |
| [Patch a show that is already on the desk](/patch/patch-a-show/) | the horns at 6pm: a change typed in plain English, nothing else moved |
| [Watch the desk during a show](/watch/watch-a-show/) | live findings, and your own watch conditions |

## The files you write

| Page | For |
|---|---|
| [Writing an input list](/build/input-lists/) | what is plugged in: columns, sockets, stereo pairs |
| [Writing conventions](/build/conventions/) | how you set up a desk, in your own words, and how it is read |
| [Channels that are not on the input list](/build/extra-strips/) | talkback, playback and the strips you want at every show, asked for in a sentence |
| [Conventions reference](/build/conventions-reference/) | the levels vocabulary, the desk's eighteen colours, and the resolved file Atoo writes beside yours |
| [Using channel presets](/build/presets/) | your own `.chn` presets, and what they are called |
| [Bus presets: mix and FX busses](/build/bus-presets/) | a mix bus's compressor, or an FX bus's reverb or delay, from your own `.bus` export |
| [Show bundles](/build/show-bundles/) | one show's folder, and what each file in it is |
| [Watch conditions](/watch/watch-conditions/) | your own alerts for **Watch**: the Kick stays on LCL 5, the PA never mutes |

## When something goes wrong

| Page | For |
|---|---|
| [Reading findings](/build/reading-findings/) | what ERROR, WARNING and INFO mean, the verdicts, and the codes |
| [Troubleshooting](/troubleshooting/troubleshooting/) | can't reach the desk, a build that fails, a refused plan, the UI not starting |
| [Where Atoo needs work](/reference/limitations/) | what is not built or not yet proven on a desk, before you rely on it |
| [Words Atoo uses](/reference/glossary/) | one name for each thing: Choices, Arm, History, the journal, a show bundle |
| [Questions](/reference/faq/) | is it AI slop, will it touch my desk mid-show, what if it goes wrong |

## From the command line

| Page | For |
|---|---|
| [Command-line quickstart](/getting-started/quickstart/) | input list to plan to desk to proof, end to end, with `atoo` commands |
| [How a show gets built](/build/pipeline/) | the stages, which one gates, and `resolve` |
| [Learning from a batch of builds](/build/lessons/) | `lessons`: the questions your builds keep asking, as candidate lines for your conventions |
| [Applying a plan](/apply/applying/) | `apply`: preview, reading the result, flags, exit codes |
| [What a full apply changes on the desk](/apply/what-apply-changes/) | the reset to initialized, unpatching unbuilt strips, Main routes, talkback, alternate inputs, expansion bays |
| [The journal](/apply/journals/) | what every write leaves behind, and how far back undo reaches |
| [Undoing a write](/apply/undo/) | `undo`: step back one write, keeping everything changed since |
| [Patching a running show](/patch/patch/) | `patch`: a typed change onto a desk already in use |
| [Patching from a rebuilt plan](/patch/amend/) | `amend`: the difference between two plans, onto a desk already in use |
| [One plan, two desks](/apply/two-desks/) | a primary and a backup, or a plan for a different WING |
| [Checking a desk](/watch/audit/) | `audit`: one read, signal tracing, and checking a desk against its plan |
| [Watching from the command line](/watch/watch/) | `watch`: the same rules on a loop, reporting what changed |
| [Command reference](/reference/cli-reference/) | every command and flag (generated from the code) |
| The web UI's HTTP API | scripting against `atoo ui` (a developer reference, in `docs/developer/`) |
