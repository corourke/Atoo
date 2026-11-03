<!-- The Build addition to the intent front end's system prompt (`atoo build --intent`).
     THIS FILE IS PROSE, NOT CODE. It follows `intent.md`, which describes the ops and the
     console's limits, and says what is different when the whole show is being written.
     No example here is taken from a show the build is scored on. -->

# This request builds a whole show

There is no desk yet; everything is free. The request is the input list below, read with
the conventions. **Code writes one channel for every input-list row**, in the list's order,
filling in what the list says (the source type, model, phantom power, category, preset and
any socket it states). You do not write those channels. You write what the list cannot say.

The reply for a whole show has one more field than a change: `categories`, the Category table.

- **`categories`**: one entry for each category the conventions give settings to, as a small
  JSON list: `{"name": "Drums", "aliases": ["drums"], "color": "Yellow", "hpf_hz": 80}`.
  `aliases` are the input list's category words; add only the fields the conventions state
  (`color`, `hpf_hz`, `gain_db`, `trim_db`, `fader_db`, `main_direct`, `dca`, `mute_group`).
  `dca` and `mute_group` are LISTS of names, even for one: `"dca": ["Drums"]`.
  Code applies the entry to every channel of the category. `[]` if the conventions give none.
- **Order**: if the conventions put the strips in an order by category ("drums, then bass,
  then vocals"), write one `order` op listing the categories in that order. If they also
  order channels within a category ("within drums: kick, snare, overheads"), list those channels,
  in that order, in the op's `channels`. Otherwise the list's order stands within a category.
- **A channel the list does not say enough about** gets an `add_channel` naming its row: a
  stereo pair is ONE `add_channel` with `rows` naming both rows and `stereo` true; a strip
  the conventions give a different name or a preset gets `name` and `preset`; an aux strip
  has `bank` `aux`. Write nothing for a row that needs nothing.
- **A strip the conventions ask for that is not an input-list row** (a click, a talkback)
  is an `add_channel` named exactly as the conventions name it, with the socket they give in
  `patch`. Code builds it only when a line of the conventions names it and says where it is
  plugged in.
- **A row left out**: only if the conventions, the instructions or the row's notes say so in
  words you can quote. Write a `drop` of that channel with `quote` set to those words. A
  `drop` without a quote that is really there leaves the row built.
- **DCAs, mute groups and buses** the conventions ask for are `add_group` and `add_bus` ops,
  named as the conventions name them, with `members`: `{"categories": ["drums"]}` for every
  channel of a category, `{"channels": ["Kick", "Snare"]}` for named ones, `{"all": true}`
  for all. A bus takes `mode` (`pre` or `post`) and `level_db` for its members' sends, and
  `to` for the output it feeds. A DCA or mute group the conventions do not ask for is not
  made. Never list every channel of a category by name: say the category.
- **Outputs** (Main, matrix) are `add_output` ops with the sockets the conventions state; `object` is `main` or `matrix`: `{"op":"add_output","object":"main","name":"Main","patch":{"group":"LCL","first":1,"count":2}}`.
- Your assumptions, and anything you could not tell, go in `notes`, one sentence each.

## Before you reply: every section of the conventions

Go through the conventions section by section. The buses, groups and outputs come from the
CONVENTIONS, not the input list: an input list never lists them. Your reply is not complete
until each item below has its op, or one sentence in `notes` saying why it is not made:

0. **Every pair of rows the conventions make one stereo channel** (an L/R or Left/Right pair,
   when they say such pairs are stereo) is ONE `add_channel` with `rows` naming both rows and
   `stereo` true. Without it, code builds the two rows as two mono channels.
1. **Every bus** the conventions list (mix buses, monitor buses, wedges, in-ears, effects
   sends) is an `add_bus`, with `members`, `mode`, `level_db` and `to` (`{"main": true}`, or
   `{"output": {...}}` with the sockets they give).
2. **Every DCA and every mute group** is an `add_group`, or the `dca` / `mute_group` of a
   Category table entry when it holds exactly one category: one or the other, never both.
3. **Every output**, Main first, is an `add_output` with the sockets the conventions state.
   "AES50-A outputs 41" is the group `A`, socket 41 (`AES` is a different group, of two
   sockets); "Local outputs 1-2" is `LCL` 1, count 2.
4. **Every strip the conventions ask for on an Aux channel** that is not an input-list row (a
   talkback, a music playback, a host mic: "Setup TALKBACK on Aux 8, source LCL 22") is an
   `add_channel` with `bank` `aux`, `place` at the Aux number and `patch` at the socket they
   give. A row the conventions put on Aux strips gets `bank` `aux`.

Code checks this: an item of the conventions' bus, DCA, mute group or output sections that
your reply neither makes nor names in `notes` sends the reply back to you.

## A worked example (a made-up show, not one you will be asked to build)

Conventions, in part (the input list has rows `Harp L` and `Harp R`):

    ## Channels
    - Any L/R pair of inputs becomes one stereo channel, named without the L/R.
    ## DCAs
    - Strings: all strings-category channels
    ## Mute Groups
    - Voices: all voice-category channels
    ## Busses
    - Room Verb: strings channels route to bus post-fader at -10dB, bus routes to main
    - Wedge A: voice channels route to bus pre-fader at unity, mono, bus routes to a dedicated output, routed to Local outputs 6
    - FX: effects busses route to main
    ## Output
    - Main: full mix, routed to Local outputs 1-2
    - Matrix: fed from Main, routed to Local outputs 7

The pair, the groups, the buses and the outputs of the reply (its Category table left out):

    {"op":"add_channel","name":"Harp","rows":["Harp L","Harp R"],"stereo":true}
    {"op":"add_group","object":"dca","name":"Strings","members":{"categories":["strings"]}}
    {"op":"add_group","object":"mute_group","name":"Voices","members":{"categories":["voice"]}}
    {"op":"add_bus","name":"Room Verb","stereo":true,"members":{"categories":["strings"]},"mode":"post","level_db":-10,"to":{"main":true}}
    {"op":"add_bus","name":"Wedge A","stereo":false,"members":{"categories":["voice"]},"mode":"pre","level_db":0,"to":{"output":{"group":"LCL","first":6}}}
    {"op":"add_output","object":"main","name":"Main","patch":{"group":"LCL","first":1,"count":2}}
    {"op":"add_output","object":"matrix","name":"Matrix","patch":{"group":"LCL","first":7}}

and in `notes`: "FX: the conventions make no effects busses, so there is no FX bus."
