# Atoo

Set up a Behringer WING for tonight's show from your own house rules, write
it to the desk, and prove every value landed.

## The problem

Forty inputs to patch, name, colour, gain, high-pass, send to monitors and
put in DCAs, by hand, at 4pm with doors at 7. You do it the same way every
show, from memory. Then the horn section turns up at 6pm, and four channels
have to go onto a desk that already has a mix on it. And when something is
wrong, the desk does not say so: forty screens each look fine, and the
vocal still is not in the PA.

## What it does

1. **You write two files.** An input list (what is plugged in tonight) and
   your conventions (how you always set up a desk, in plain English).
2. **A model drafts the whole setup** as a plan you can read: every
   channel, patch, colour, bus, send and DCA, each with its reason.
3. **Code checks the draft** against the desk's real limits and your
   conventions before anything can be written. A stereo pair that starts on an
   even socket, or a patch to a socket the desk does not have, stops it.
   Anything the model chose that you did not state is announced.
4. **It writes the plan to the desk and reads every value back**, so what
   did not land is named, not discovered at soundcheck. First, a preview
   reads the desk and draws it as the plan will leave it, strip by strip,
   with every change outlined; nothing is written until you arm it. Every
   write is journalled and can be undone.
5. **During the show, it watches the desk** against your own rules: the
   DI that got repatched, the DCA pulled to the floor.

A late change is one line, *"trumpet, sax and trombone on LCL 21-23, Band
DCA"*, and moves nothing that is already in use.

It runs on your laptop, in your browser or from the command line. **A
build needs your own AI API key**: Atoo is built and tested on
Claude, and local models have not worked well so far. The model builds
the show plan, before the show; local code applies it to the desk, with
every write logged and undoable.

## Why not what you already use?

| You do it now by... | What that cannot do |
|---|---|
| building it by hand, on the desk or in WING Edit | check itself, or be reused for a different band |
| copying last month's show file | adapt to a band with a different shape; it carries the old layout |
| the desk's channel presets and libraries | set up the show around the strips: patch, busses, sends, DCAs |
| typing a spreadsheet input list into the desk | confirm that the desk now matches the spreadsheet |

[Why Atoo](docs/user/why.md) makes the comparison in full, including
where the existing ways are better.

## Try it in two minutes, with no desk

You need Python 3.11 or newer ([installing](docs/user/install.md) covers
older ones).

```bash
git clone https://github.com/corourke/Atoo.git
cd Atoo
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -e '.[ui]'
atoo ui
```

`a2` is the same command as `atoo`, shorter to type (`a2 ui`).

Your browser opens on an empty show. Press **Try the Demo show**. A
five-piece band with backing tracks opens on a simulated WING Compact: look through
**Build**, **Apply** and **Watch**. On **Apply**, press **Preview** to see
the simulated desk drawn as the plan would leave it; on **Watch**, press
**Start watching** to see faults come and go. Nothing is written
anywhere.

Then patch the horn section in, still with no desk and no key:

```bash
atoo patch --show starter/demo-show --change-set docs/user/demo/demo-show/horns.change-set.json --state atoo/web/demo_states/before.json
```

Three horns land on free strips with their presets, on a new Horns bus
with a compressor, and nothing else on the desk is touched
([The 6pm change](docs/user/demo.md#the-6pm-change)).

## Consoles

The Behringer **WING Compact**, the full-size **WING** and the **WING
Rack**. No other console is supported.

## Read next

- [The user guide](docs/user/README.md): installing, writing an input list
  and conventions, building, applying and watching, in the browser or
  from the command line.
- [Questions a careful engineer asks](docs/user/faq.md): is it AI slop,
  will it touch my desk mid-show, what it costs, what if it goes wrong.
- [Where Atoo needs work](docs/user/limitations.md): what is not
  built, or not yet proven on a real desk.

## Licence

[AGPL-3.0](LICENSE) (`AGPL-3.0-or-later`). For use in a closed or
commercial product, a commercial licence is available by agreement:
contact [Act4Audio](https://www.act4audio.com/).
