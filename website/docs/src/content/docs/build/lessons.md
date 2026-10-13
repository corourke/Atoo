---
title: "Learning from a batch of builds"
description: "If the build keeps asking the same question show after show, your conventions have a gap. atoo lessons finds those questions. It reads a bundle's recent builds and groups everything they noted by…"
sidebar: 
  order: 11
---

<!-- Generated from docs/user/lessons.md by tools/docs_to_starlight.py in the development repository. Edit it there. -->
If the build keeps asking the same question show after show, your
conventions have a gap. `atoo lessons` finds those questions. It
reads a bundle's recent builds and groups everything they noted by
topic, putting the topics that come up again and again first. Each one is
a candidate for a line in `conventions.md` or a show's `instructions.md`.

It only reads files and makes no model call.

## Run it

```
atoo lessons --show docs/user/demo/festival
```

```
Sources: current, 2026-09-30T01-45-34Z, 2026-09-29T23-06-37Z (3 builds).

## Where the thinking went (share of the time each role's notes cover)
  2026-09-30T01-45-34Z
    generator    75.2s over  29 note(s): mechanical 23%, conventions 0%, prompt 10%, writing 7%, judgement 60%
    critic       64.4s over  25 note(s): mechanical 2%, conventions 3%, prompt 21%, writing 3%, judgement 70%
  2026-09-29T23-06-37Z
    generator    86.5s over  37 note(s): mechanical 18%, conventions 4%, prompt 5%, writing 6%, judgement 67%
    fixup        19.3s over   4 note(s): mechanical 35%, conventions 38%, prompt 0%, writing 27%, judgement 0%
    critic       42.2s over  14 note(s): mechanical 8%, conventions 22%, prompt 43%, writing 0%, judgement 27%

## Guitars (28 item(s), across 3 builds)
  - (current, critic [critic]) Conventions specify patch order as drums, bass, guitars, keyboards, strings/brass, vocals, tracks, then speakers — the plan patches HOST (speech) at channel 30, ahead of the tracks block (31-38), reversing the required tracks-before-speakers order.
  - (2026-09-30T01-45-34Z, build_log [generator]) I'm deciding to treat all 38 rows as active channels, ignoring the "not patched" comments as instructed. Then I'm organizing categories in order: drums, bass, guitars, keyboards, strings/brass, vocals, tracks, speakers, and other remaining items.
  ...
```

(`docs/user/demo/festival` is a frozen copy of a festival show's plan and
its two newest build logs.)

## What it reads

- The bundle's current `plan.json`: its build findings, critic findings,
  inferred choices, notes and `verify` warnings.
- Every build log in the bundle's `builds/` folder, newest first. Each
  build writes one, including a build that failed or was stopped, and
  the folder keeps the newest 5. `--last N` reads fewer.
- With `--git N`, up to N older versions of `plan.json` from the
  bundle's git history, if the bundle is a git repository.

Items are grouped by the channel, bus, DCA or output they name, or else
by the plan field involved.

## Where the thinking went

The report opens with one line per role per build. Each line shows how
the time covered by that role's thinking notes splits across five rough
buckets, sorted by keyword:

| Bucket | What it catches |
|---|---|
| mechanical | counting, numbering, the next free socket |
| conventions | conflicts and ambiguity in what you wrote |
| prompt | the reply's format and fields |
| writing | assembling the reply |
| judgement | everything else |

The buckets are keyword guesses. Use them to compare one build with
another, not as a verdict on any one note. A lot of time in
**conventions** is the useful signal: the model was working out what
your text meant.

`--json` gives the same report as data, with the time split under
`thinking_time`. Nothing is written anywhere.

## See also

- [How a show gets built](/build/pipeline/)
- [Writing conventions](/build/conventions/)
- [Command reference](/reference/cli-reference/#atoo-lessons)
