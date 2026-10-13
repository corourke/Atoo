---
title: "Troubleshooting: when verify refuses a plan"
description: "The plan was built, but verify (or the pre-flight before apply) refuses it, or a preset it names cannot be found."
sidebar: 
  order: 3
---

<!-- Generated from docs/user/troubleshooting-verify.md by tools/docs_to_starlight.py in the development repository. Edit it there. -->
The plan was built, but `verify` (or the pre-flight before `apply`)
refuses it, or a preset it names cannot be found.

## `verify` says `BLOCKED: do not apply.`

```
$ atoo verify --show demo-show
2 error(s), 0 warning(s), 4 note(s)

  [error] outputs[Matrix 1]: LCL output 9 does not exist -- LCL outputs are 1..8 on a WING Compact (note LCL has 24 INPUTS but only 8 outputs)  (output.socket-out-of-range)
  [error] outputs[Matrix 1]: LCL output 10 does not exist -- LCL outputs are 1..8 on a WING Compact (note LCL has 24 INPUTS but only 8 outputs)  (output.socket-out-of-range)

  [info] plan: 'Magenta' is the desk's Pink (11): Elec Gtr. The desk has no colour called 'Magenta'; Atoo used that name for 11 until the desk was asked, so it still resolves. Say 'Pink' to use the desk's own word  (strip.colour-alias)
  [info] plan.mute_groups[Speech]: mute group 'Speech' is declared but no channel or bus joins it -- it does nothing  (group.empty)
  [info] outputs[Main, Matrix 1] (2 outputs): index set to 1 -- the plan left it out; decided by Atoo's fallback rule: the plan has one Main, so it is Main 1 / its name, 'Matrix 1', states slot 1  (inferred.output-index)

BLOCKED: do not apply.
```

*(Made from a copy of the small band example, with
`outputs["Matrix 1"].patch` set to LCL 9-10 -- the state a build leaves
when the conventions name a jack the desk does not have: a WING Compact
has eight local outputs.)*

**`BLOCKED` is one sentence about the whole plan, and it is decided by
severity alone**: one or more `[error]` findings. Warnings and notes
never block, however many there are — the run above would have said
`APPLICABLE: notes only -- choices made where the conventions were
silent.` without the two errors.

**An error is a setting the desk cannot be left in**: a socket that does
not exist, a pair that cannot be formed, a value out of range. Anything
the desk can work with -- even if it may not be what you meant -- is a
warning or a note, and is applied.

**An output with no patch at all is not blocked.** Set the same Matrix's
`patch` to `null` instead -- the state a build leaves when the
conventions never say where the Matrix physically lands, or a Matrix
used only inside the desk, as the phones or monitor source -- and verify
says so at WARNING:

```
$ atoo verify --show unpatched-show
0 error(s), 2 warning(s), 4 note(s)

  [warning] outputs[Main]: nothing is patched from this output to a physical socket -- apply sets it up (its feed, level and processing) but routes it to no output socket  (output.no-patch)
  [warning] outputs[Matrix 1]: nothing is patched from this output to a physical socket -- apply sets it up (its feed, level and processing) but routes it to no output socket -- right when the Matrix is used inside the desk, for example as the phones or monitor source  (output.no-patch)

  [info] plan: 'Magenta' is the desk's Pink (11): Elec Gtr. The desk has no colour called 'Magenta'; Atoo used that name for 11 until the desk was asked, so it still resolves. Say 'Pink' to use the desk's own word  (strip.colour-alias)
  [info] plan.mute_groups[Speech]: mute group 'Speech' is declared but no channel or bus joins it -- it does nothing  (group.empty)
  [info] outputs[Main, Matrix 1] (2 outputs): index set to 1 -- the plan left it out; decided by Atoo's fallback rule: the plan has one Main, so it is Main 1 / its name, 'Matrix 1', states slot 1  (inferred.output-index)

APPLICABLE: warnings only.
```

Apply sets each of them up -- the Matrix's feed from Main 1, both
faders and any processing -- and routes neither to an output socket. The
socket is never guessed. Main has a warning too, because Matrix 1 was its
only way out. If the Matrix should reach a jack, state a `patch` for it
in the conventions.

**Notes (`[info]`) are choices, not problems.** Where the conventions
were silent about something the desk cannot be left without — a bus's
width, a send's pre/post — the plan decides it and says what it decided
and why. The last line above is that: the plan never said which Main
or which Matrix slot its outputs take, so each is decided from the name
and said -- once, naming both, because it is the same note twice. The
other two are things worth knowing rather than choices: a colour the
desk calls by another word, and a mute group nothing joins. A note that
says the same thing about several busses (or channels, or outputs) is
printed once, naming them all; a built `plan.json` still holds one
finding per object in its `meta`. If a choice is wrong for your show,
say so in your conventions and rebuild.
See [Writing conventions](/build/conventions/#the-one-rule-worth-internalising-state-it-or-it-is-decided-and-said).

**Read the findings, not the verdict.** Each one has four parts and they
are worth telling apart (the example is the second run above):

| part | example above | what to do with it |
|---|---|---|
| severity | `[warning]` | errors block; warnings and notes do not |
| where | `outputs[Matrix 1]` | the object in the plan, addressable by hand |
| message | `nothing is patched from this output ...` | usually names the fix |
| code | `(output.no-patch)` | **stable across rewordings** — quote this in a bug report, and the browser UI filters on it. |

**`apply` obeys the verdict without re-deciding it**, and refuses before
it opens a socket, so a blocked plan never reaches hardware:

```
$ atoo apply --show demo-show --console 192.0.2.16 --confirm
...
BLOCKED: do not apply.

Refusing to apply 'demo-show/plan.json'. Fix the plan, or pass --skip-verify if you have a reason to write it anyway.
```

Both exit `2`.

**The fix is almost always in the plan, and sometimes in the
conventions.** A plan is a file you can read and edit, so a one-line
correction is legitimate. But a finding like the one above is the plan
faithfully recording what your conventions said -- a jack the desk does
not have -- so editing the plan fixes this show, and editing the
conventions fixes every show you build after it. See [Writing conventions](/build/conventions/).

**`--skip-verify` is not the answer to a `BLOCKED`.** It does not make
the plan correct; it removes the only check that can refuse a plan for
free, before a console is touched. Use it when you know precisely which
finding you are overriding and why — and note that it does not turn off
`apply`'s expansion-bay check, which is the desk's own report rather than
a judgement about the plan.

## `verify` says two objects are on the same physical output

```
$ atoo verify --show demo-show
1 error(s), 0 warning(s), 4 note(s)

  [error] busses[MON6]: LCL outputs 7 and 8 are claimed by 2 sources at once -- busses[MON6] and outputs[Matrix 1] -- and one physical socket carries one signal. Whichever of them apply writes last wins; the other is silently dead at the jack. LCL has 8 outputs on a WING Compact and all 8 are claimed, so there is no free LCL socket to move one of them to -- the AES50 groups (A, B, C) have 48 outputs each, which is where IEM and monitor sends usually live  (output.socket-collision)

  [info] plan: 'Magenta' is the desk's Pink (11): Elec Gtr. The desk has no colour called 'Magenta'; Atoo used that name for 11 until the desk was asked, so it still resolves. Say 'Pink' to use the desk's own word  (strip.colour-alias)
  [info] plan.mute_groups[Speech]: mute group 'Speech' is declared but no channel or bus joins it -- it does nothing  (group.empty)
  [info] outputs[Main, Matrix 1] (2 outputs): index set to 1 -- the plan left it out; decided by Atoo's fallback rule: the plan has one Main, so it is Main 1 / its name, 'Matrix 1', states slot 1  (inferred.output-index)

BLOCKED: do not apply.
```

*(Made from a copy of the small band example — MON1-4 on
LCL 1-4, Matrix 1 on LCL 7-8 — and adding two stereo IEM busses fed
pre-fader from Lead Vox, MON5 on LCL 5-6 and MON6 on LCL 7-8. Four
sockets wanted, two free. The four notes are smallband's own,
[explained above](#verify-says-blocked-do-not-apply).)*

**One XLR carries one signal.** This is not a shared feed: `apply` writes
each claimant's routing to the same `/io/out/LCL/7` and `/io/out/LCL/8`
in turn, so whichever is written last owns the jack and the other sends
its signal nowhere. You find that at soundcheck, when an in-ear pack is
silent or the truck has no feed — which is why it is an **error** and not
a warning. There is no second jack to prefer, so it is not a matter of
taste.

**The message names both claimants on purpose.** `busses[MON6]` and
`outputs[Matrix 1]` are the two objects, addressable by hand in the plan;
`LCL outputs 7 and 8` are the sockets they are fighting over. A stereo
collision is reported once, naming both sockets, rather than twice.

**Then read the last clause, because it says whether there is room.**
Two shapes:

- *"LCL has 8 outputs on a WING Compact and all 8 are claimed"* — the
  group is full. Do not shuffle within it; there is no ninth LCL. Move
  one of the two to another group. IEM and monitor sends usually live on
  AES50 (`A`, `B`, `C`), where there are 48 outputs each and a stage box
  or IEM rack is normally already sitting.
- *"LCL has 8 outputs on a WING Compact and 2 of them are still free
  (LCL 5, LCL 6)"* — the group has room, and the free sockets are listed.
  Move one claimant onto one of those.

Fixing the run above by putting MON6 on AES50 A 1-2 instead (the four
notes are unchanged, and left out here):

```
$ atoo verify --show demo-show
0 error(s), 0 warning(s), 4 note(s)

  ...

APPLICABLE: notes only -- choices made where the conventions were silent.
```

**The real fix is usually in the conventions**, as with any `BLOCKED`
above: the plan is faithfully recording that your `## Busses` section
asked for more dedicated outputs than the group it named has. Saying
which group the IEM sends patch to — see [Writing
conventions](/build/conventions/) — fixes every show you build after this one.

**Inputs are not covered by this rule, deliberately.** Two channels on
one physical *input* is legitimate — a split to a broadcast truck, one
socket reused between acts at a festival — so it stays advice
(`reconcile.duplicated-input` here, `C002` from `audit`), never a
refusal.

## A plan names a preset that cannot be found

```
  [warning] channels[Snare]: names the preset 'Snare Top', which is not in the library at starter/presets (20 presets) -- that strip will be built without it. Closest in the library: Snare, M Tom, H Tom, Fl Tom  (preset.unknown)
```

It names up to five presets whose names are closest, so a near miss
(`Kick (In)` for `Kick In`) is easy to spot.

**This is a warning and never blocks.** The strip is built with
everything else the plan states and without the preset's values, which is
a working channel rather than a missing one.

**The name it is looking for is inside the `.chn` file, not the
filename.** The starter's `Kick.chn` answers to `Kick In`,
because that is the label the preset carries. A plan naming the filename
will not match.

The warning above names the closest names in the library, which half answers the
question — but you should not have to provoke a warning to ask it.
**`atoo presets --presets starter/presets` lists the library
directly**, name beside filename, and reports anything wrong with a
preset while it is there. See
[Ask the library what it is called](/build/presets/#ask-the-library-what-it-is-called).

Five other things to check:

1. **Is there a library configured at all?** No `--presets` and no
   `[presets] default` in `~/.atoo.config` is a different warning,
   and it is one per plan rather than one per strip:

   ```
     [warning] plan: 6 channel(s) name a preset (KEYS, Kick (In), Perc, Snare Top, kick-in, vocal) but no preset library is configured and the plan carries none of their values, so those strips will be built without the processing those presets carry  (preset.no-library)
   ```

   `preset.unknown` means the library was read and this name was not in
   it. `preset.no-library` means nothing was read.
2. **Is it a near-miss?** Matching forgives case and punctuation, so
   `kick-in` resolves to `Kick In` with no warning at all. It does
   not guess: `Kick (In)` is a different name, and is reported rather
   than resolved to the thing it obviously means.
3. **Are two files claiming the same name?** That is `preset.ambiguous`:
   it uses the newest, names the ones it ignored, and says so out loud —
   picking silently is how the wrong one gets applied for a month.
4. **Is the directory readable?** A library it cannot read is
   `preset.unreadable-library` rather than a silent empty one.
5. **Found, but "nothing from it will be written"?** That is
   `preset.not-expanded`: the library has the preset, but the plan was
   built before `build` started putting a preset's values into the plan,
   or without a library. Rebuild with `--presets`, or run
   `atoo presets --presets DIR --expand plan.json`, which does the
   same thing offline. See
   [How a preset gets into the plan](/build/presets/#how-a-preset-gets-into-the-plan).

See [Using channel presets](/build/presets/) — in particular
[A preset's name is inside the file, not on it](/build/presets/#a-presets-name-is-inside-the-file-not-on-it)
and [What verify says about presets](/build/presets/#what-verify-says-about-presets).

## See also

- [Troubleshooting](/troubleshooting/troubleshooting/) — every symptom, and the page it is on
- [Reading findings](/build/reading-findings/) — the verdicts, severities and codes
- [Writing conventions](/build/conventions/) — where most fixes go
