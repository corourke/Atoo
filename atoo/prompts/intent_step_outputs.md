<!-- Step 3 of `atoo build --intent --intent-steps`: DCAs, mute groups and outputs.
     THIS FILE IS PROSE, NOT CODE. Code puts it AFTER the shared prefix (see `intent_steps.md`),
     followed by what steps 1 and 2 built: the channels, the categories and the buses. -->

# Step 3 of 3: DCAs, mute groups and outputs

Write every DCA, mute group and output the conventions and the instructions ask for. Read every
section of the conventions for them. Buses are already written (listed below); do not write them
again.

- **Outputs first, Main first**: `{"op": "add_output", "object": "main", "name": "Main",
  "patch": {"group": "LCL", "first": 1, "count": 2}}` with the sockets the conventions state, then
  each matrix (`"object": "matrix"`) with its sockets.
- **DCAs and mute groups**: one `add_group` each, `object` `dca` or `mute_group`, named as the
  conventions name it, with `members` by category (`{"categories": ["strings"]}`), by channel name
  or `{"all": true}`. Use the names listed below. A DCA or mute group the conventions do not ask
  for is not made.

Example (another show): "Main L/R on LCL 1-2. A delay matrix on LCL 9. DCAs: Strings (fiddle and
banjo), Vox. Mute group FX." is

    {"name": "Groups and outputs", "ops": [
      {"op": "add_output", "object": "main", "name": "Main", "patch": {"group": "LCL", "first": 1, "count": 2}},
      {"op": "add_output", "object": "matrix", "name": "Delay", "patch": {"group": "LCL", "first": 9}},
      {"op": "add_group", "object": "dca", "name": "Strings", "members": {"categories": ["strings"]}},
      {"op": "add_group", "object": "dca", "name": "Vox", "members": {"categories": ["vocals"]}},
      {"op": "add_group", "object": "mute_group", "name": "FX", "members": {"categories": ["fx"]}}],
     "notes": []}

Ops this step may write: `add_output`, `add_group`. Reply with
`{"name": ..., "ops": [...], "notes": [...]}` and nothing else.
