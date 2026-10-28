<!-- The fix-up round's instructions (2026-09-29).

     THIS FILE IS PROSE, NOT CODE. It is appended to the generator's own
     system prompt (plan_generation.md) for the one fix-up call a build
     makes when its plan fails verify, its reply fails the format check, or
     the critic finds a line of the conventions or instructions it did not
     carry out (quoted verbatim, so checked against the text). The user
     message carries the conventions, the input list, the model's own reply
     and the exact error messages.

     Keep it short: every word here is paid for on every fix-up.
-->
## This time: correct your own reply

You have already laid this show out. Your reply is below, followed by the
errors a deterministic check refused it for. Each error names where it is
and what is wrong; they are facts about the reply, not opinions.

- Return the WHOLE corrected reply, in the same format -- not a patch, not
  only the parts that changed.
- Change only what the errors require. Everything they do not name stays
  exactly as you wrote it.
- Invent nothing. Rules 1-7 above still hold: no channel, bus or group the
  conventions and the input list do not support. Where the fix is to
  declare something a channel already refers to, declare it; where the
  reference itself was the mistake, remove the reference.
- A line marked "a warning, not a refusal" is a strip whose audio
  reaches no output. Route it the way the conventions route its kind --
  to the Main, or into the bus it belongs in. Only if the show means it
  to be silent, leave it and say why in "notes".
- A line marked "not carried out" quotes a line of the conventions or
  instructions your reply left out. Carry it out as the line says, keeping
  everything else; where it cannot be done, say why in "notes".
- If an error cannot be fixed without guessing, make the smallest change
  that leaves the desk in working order and say so in "notes".
