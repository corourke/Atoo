<!-- Step 1 of `atoo build --intent --intent-steps`: the categories and the exceptions.
     THIS FILE IS PROSE, NOT CODE. Code puts it AFTER the shared prefix (see `intent_steps.md`),
     followed by what the earlier steps built (nothing, for this step). -->

# Step 1 of 3: categories and exceptions

Write the Category table and the channels the input list does not say enough about. Do not write
buses, DCAs, mute groups or outputs: steps 2 and 3 do those.

- **`categories`**: one entry for each category the conventions give settings to:
  `{"name": "Strings", "aliases": ["strings", "fiddle"], "color": "Green", "hpf_hz": 100}`.
  `aliases` are the input list's category words. Add only the fields the conventions state
  (`color`, `hpf_hz`, `gain_db`, `trim_db`, `fader_db`, `main_direct`); DCAs and mute groups are
  step 3's. `[]` if the conventions give none.
- **`add_channel`** naming its row, only where the row needs more than the list says:
  - a stereo pair is ONE `add_channel` with `rows` naming both rows and `stereo` true:
    `{"op": "add_channel", "name": "Banjo", "rows": ["Banjo L", "Banjo R"], "stereo": true}`;
  - a strip the conventions give another name or a preset gets `name`, `rows` and `preset`;
  - an aux strip has `bank` `aux`;
  - a strip the conventions ask for that is not a row (a click, a talkback) is an `add_channel`
    named as the conventions name it, with the socket they give in `patch`.
  Write nothing for a row that needs nothing.
- **`drop`** of a row's channel, only if the conventions, the instructions or the row's notes say
  so in words you can quote, with `quote` set to those words.
- **`order`**: if the conventions put the strips in an order by category, one `order` op listing
  the categories in that order, and in `channels` any channels they order within a category.

Ops this step may write: `add_channel`, `drop`, `order`. Reply with
`{"name": ..., "categories": [...], "ops": [...], "notes": [...]}` and nothing else.
