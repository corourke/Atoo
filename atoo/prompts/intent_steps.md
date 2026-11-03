<!-- The system prompt's Build addition for `atoo build --intent --intent-steps`.
     THIS FILE IS PROSE, NOT CODE. It follows `intent.md` and is the SAME for all three calls of
     one build: the system prompt and the first part of the user message are one byte-identical
     prefix that a host reads once (Ollama's prompt cache, Claude's `cache_control`). Everything
     that differs between the steps is in `intent_step_*.md`, which code puts AFTER the prefix.
     Nothing here may name one step's ops as the only ones allowed.
     No example here or in the step files is taken from a show the build is scored on. -->

# This request builds a whole show, in three steps

There is no desk yet; everything is free. **Code writes one channel for every input-list row**,
in the list's order, filling in what the list says (the source type, model, phantom power,
category, preset and any socket it states). You do not write those channels.

The show is built in three short steps. Each message ends with the step to do now, the ops that
step may write, and what the earlier steps have built. **Write only that step's part**, and only
the ops it names; the other steps are asked for separately, so nothing is lost by leaving them
out of this reply. Everything in the conventions that belongs to the step you are asked for must
be in your reply: read every section of the conventions for it.

1. **Categories and exceptions**: the Category table, stereo pairs, strips that are not rows,
   renamed rows, rows left out, the strip order.
2. **Buses and their sends**: monitor mixes, effects and group buses, with their members.
3. **DCAs, mute groups and outputs**: Main first, then the matrices, with their sockets.

The reply of every step is one JSON object and nothing else:

    {"name": "<a few words>", "ops": [ ... ], "notes": [ ... ]}

Step 1 also has `categories`. A step with nothing to write replies with `"ops": []` and says why
in `notes`. Members are named **by category** (`{"categories": ["drums"]}`), by channel name
(`{"channels": ["Kick", "Snare"]}`) or `{"all": true}`; use a category or channel name the
earlier steps built, exactly as the step's message lists it. Never list every channel of a
category by name: say the category. Your assumptions, and anything you could not tell, go in
`notes`, one sentence each.
