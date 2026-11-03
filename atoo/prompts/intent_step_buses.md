<!-- Step 2 of `atoo build --intent --intent-steps`: the buses and their sends.
     THIS FILE IS PROSE, NOT CODE. Code puts it AFTER the shared prefix (see `intent_steps.md`),
     followed by what step 1 built: the channels and the categories a member may name. -->

# Step 2 of 3: buses and their sends

Write every bus the conventions and the instructions ask for: monitor mixes (wedges, in-ears),
effects returns' sends (reverb, delay), group buses (drums, vocals), and any other. Read every
section of the conventions for them. Do not write DCAs, mute groups or outputs: step 3 does those.

One `add_bus` op per bus, named as the conventions name it:

- `members`: which channels send to it, by category (`{"categories": ["horns"]}`), by channel
  name (`{"channels": ["Lead Vox", "Banjo"]}`) or `{"all": true}`. Use the names listed below.
- `mode`: `pre` or `post` (a monitor mix is usually `pre`, an effect or a group `post`), when the
  conventions say or it is the usual choice; `level_db` for the members' sends, if stated.
- `stereo`: true or false when the conventions say (an in-ear mix is usually stereo).
- `to`: `{"main": true}` for a group bus that feeds Main, or `{"output": {"group": "LCL",
  "first": 5, "count": 2}}` for the physical output the conventions give a monitor mix.

Example (another show): "The horn wedge gets the horns and the lead vocal, pre-fader, on LCL 7.
Horns go to a Horns group bus." is

    {"name": "Buses", "ops": [
      {"op": "add_bus", "name": "Horn Wedge", "stereo": false,
       "members": {"categories": ["horns"], "channels": ["Lead Vox"]}, "mode": "pre",
       "to": {"output": {"group": "LCL", "first": 7, "count": 1}}},
      {"op": "add_bus", "name": "Horns", "members": {"categories": ["horns"]}, "mode": "post",
       "to": {"main": true}}], "notes": []}

Write the fields in that order -- `name`, `stereo`, `members`, `mode`, `level_db`, `to` -- since
the reply's format may allow a field only before the ones after it.

Ops this step may write: `add_bus`. Reply with `{"name": ..., "ops": [...], "notes": [...]}` and
nothing else.
