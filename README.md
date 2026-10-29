# Atoo

[![tests](https://github.com/corourke/Atoo/actions/workflows/tests.yml/badge.svg)](https://github.com/corourke/Atoo/actions/workflows/tests.yml)

_Atoo is said "A-two": your A2, the second engineer at the desk._

Takes an input list and a set of written conventions (instructions) that state your personal preferences, along with general audio engineering knowledge, and plans out a complete show on a Behringer WING, audits it for correctness, and applies it to your console incorporating your own saved channel and bus presets. It allows you to make last minute patch updates, again using plain English, validating the changes and allowing full undo at any point. It also watches your desk pre-show or during the show for routing problems and other errors.

## The problem

When building show files, I noticed myself doing much the same thing for every new act, either patching from scratch or copying an existing showfile, following my same patterns, and it was both tedious and error prone. Festival patches were always a compromise, and when things got exciting close to doors, it was all too easy to making a routing mistake or forget something simple.

I found some prior work in this area, in terms of generating and auditing show files, but I wanted to take a different approach and start with written audio engineering knowledge, along with my own preferences and conventions that could be applied to any show. I also wanted to be able to verify the board against the input list, and logically trace the signal path for every channel from input to final output.

Lastly, I wanted to be able to type in a change (my favorite example is when an unannounced horn section showed up 30 minutes before doors) and have the program just figure it out, including busses, DCAs, presets, all of it and verify the correctness of the new layout. And if I managed to do something dumb, like mute the drum bus, or double patch the last minute backup vocalist to both the main and vocal busses, I wanted something that would alert me before the show started.

## How Atoo works

1. **You write three files.** Your conventions (how you always set up a desk, in plain English), an input list, and any show-specific instructions (again, in English).
2. **A model drafts the whole setup** as a plan you can read: every channel, patch, color, bus, send and DCA, each with its reason.
3. **Code checks the plan** against the desk's real limits and various rules before anything can be written. A stereo pair that starts on an even socket, or a patch to a socket the desk does not have, stops it. Anything the model chose that you did not state is announced.
4. **It writes the plan to the desk and validates every value**, anything that did not land is named, not discovered at soundcheck. First, a preview reads the desk and draws it as the plan will leave it, strip by strip, with every change outlined. Every write is journalled and can be undone.
5. **During the show, it watches the desk** against the input list, the built-in rules, and your own rules. It doesn't mix and never touches the desk unless you specifically arm a write step.
6. **Capture.** (Alternative workflow.) It reads your desk as it is now and turns it into a show bundle, with your inputs, busses and outputs as sheets you can read, edit and watch against.

It runs in a browser or from the command line on your laptop. **A build needs an AI provider and your own AI API key**. Atoo is built and tested on Claude, and we are investigating local models and other providers.

[Why Atoo?](https://github.com/corourke/Atoo/blob/main/docs/user/why.md) goes into the reasons for creating Atoo, why use it instead of alternatives, and how it is different.

## Try it in two minutes, with no desk

On Mac or Linux, install using `uv` (a Python package installer).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then, in a new terminal window:

```bash
uv tool install --python 3.12 "atoo[ui]"
uv tool update-shell; exec zsh   # in bash, open a new terminal window instead
```

Then:

```bash
atoo ui
```

> [!NOTE] [Installing Atoo](https://github.com/corourke/Atoo/blob/main/docs/user/install.md) has each step, along with alternative instructions for Homebrew and pipx users. To run it from a GitHub clone instead, see [Installing from a checkout](https://github.com/corourke/Atoo/blob/main/docs/user/install-from-checkout.md). A real build also needs your own AI API key ([Setting up an AI provider](https://github.com/corourke/Atoo/blob/main/docs/user/ai-provider.md)).

`a2` is the same command as `atoo`, shorter to type (`a2 ui`).

Press **Try the Demo show**. A five-piece band with backing tracks opens on a simulated WING Compact: look through **Build**, **Apply** and **Watch**. On **Apply**, press **Preview** to see the simulated desk drawn as the plan would leave it; on **Watch**, press **Start watching** to see faults come and go. Nothing is written anywhere.

## Consoles

The Behringer **WING Compact**, the full-size **WING** and the **WING Rack**. No other console is supported.

## For Beta testers

### Who I'm looking for

Because Atoo can (optionally) write to your desk, I'd like to start with a few people who:

- can save a snapshot of their desk before testing and load it again after;
- are comfortable typing a few setup commands into a terminal;
- are on a Mac. Linux should work. Windows folks are welcome, but I haven't tested it, so tell me what breaks;
- can zip up a show folder (Compress, on a Mac) and upload it with a short form;
- don't mind giving short, honest feedback.

### How to get started

1. Check the preliminary website: https://atoo.app/ 
2. Check the preliminary docs: https://docs.atoo.app/
3. Go through the 'Getting Started' section in the docs, which includes the install. 
4. Log any issues at https://github.com/corourke/Atoo/issues
5. Include your show folder: Zip it up with a reading of the desk inside ([how](https://docs.atoo.app/reference/reporting/)). 

## Read next

- [The user guide](https://github.com/corourke/Atoo/blob/main/docs/user/README.md): installing, writing an input list and conventions, building, applying and watching, in the browser or from the command line.
- [Questions a careful engineer asks](https://github.com/corourke/Atoo/blob/main/docs/user/faq.md): is it AI slop, will it touch my desk mid-show, what it costs, what if it goes wrong.

## License

[AGPL-3.0](https://github.com/corourke/Atoo/blob/main/LICENSE) (`AGPL-3.0-or-later`). For use in a closed or commercial product, a commercial license is available by agreement: contact [Act4Audio](https://www.act4audio.com/).