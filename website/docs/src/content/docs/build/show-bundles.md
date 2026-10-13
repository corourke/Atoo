---
title: "Show bundles"
description: "One directory per show. Every command then takes --show DIR instead of four or five file flags you have to remember to pass together and keep in sync by hand."
sidebar: 
  order: 8
---

<!-- Generated from docs/user/show-bundles.md by tools/port_user_docs.py. Edit it there, then re-run the port. -->
One directory per show. Every command then takes `--show DIR` instead of
four or five file flags you have to remember to pass together and keep in
sync by hand.

A bundle is a directory with **fixed filenames inside it and no manifest**
— nothing to author, nothing to keep current. The names are the
convention.

## The four slots

The [Demo show](/getting-started/demo/) is one, and it ships with Atoo. From the
top of an Atoo checkout:

```bash
ls starter/demo-show/
```

```
input.csv
instructions.md
plan.json
watch.json
```

A show you build also grows the folders in the second half of the table
below (`journals/`, `builds/` and so on) as you use it.

| filename | what it is | who writes it |
|---|---|---|
| `input.csv` | the input list — one row per physical input | you |
| `instructions.md` | how *this* show works: a layer over your conventions | you |
| `plan.json` | the plan the last build made | `atoo build`, and nothing else |
| `plan.partial.json` | the part of the reply a FAILED build received, kept as evidence of why; removed by the next build that succeeds | `atoo build` |
| `plan.previous.json` | the plan a rebuild replaced, moved aside the moment the rebuild starts, so a build that fails or is stopped leaves no out-of-date `plan.json` for Apply to offer. A rebuild ends by comparing the new plan with it, strip by strip ([What a rebuild changed](/build/pipeline/#what-a-rebuild-changed)). One generation only; not tracked by git (`.gitignore`) | `atoo build` |
| `watch.json` | your [watch conditions](/watch/watch-conditions/) | `atoo build` drafts it, you edit it (in the browser: Watch's **Watch conditions**) |
| `journals/` | a **directory**: every journalled write in time order, one file each, named for the desk it wrote to — which `atoo undo` walks back one step at a time, per desk. The newest 5 are kept | `apply`, `patch`, `amend` and `undo`, on `--confirm` |
| `builds/` | a **directory**: one file per build — done, failed or stopped — holding what each model call noted and what it cost. The newest 5 are kept | `atoo build` (and the UI's Build) |
| `logs/` | a **directory**: text transcripts of a build and its verify, `<UTC time>-build.txt` and `<UTC time>-verify.txt`, one pair per run. The newest 5 runs are kept | a rebuild script of your own, if you keep one |
| `backups/` | a **directory**: the file a **Change file** copy replaced, as `<name>.bak` — one per file, the newest replacing the last | the UI's file picker |

**Only plan files and the files you write sit at the top level**:
`input.csv`, `instructions.md`, `plan.json`,
`watch.json`, and `plan.previous.json` / `plan.partial.json` while they
exist. Everything else Atoo writes goes in one of the four folders,
and the three that grow with every run — `journals/`, `builds/` and
`logs/` — are pruned to their newest **5** entries straight after each
write. For `logs/` an entry is one run, so the build and verify
transcripts of a run are kept or removed together.

The listing above is not a one-to-one match for that table, and neither
is wrong: the Demo show has never been built, applied or had a file
replaced from this copy, so it has no `builds/`, `journals/` or
`backups/`.

The folders are not slots in the strict sense. `builds/` is
covered in [the pipeline](/build/pipeline/); `plan.json` keeps only a pointer
to its own build's file, at `meta.build_log_file`, and that file is never
pruned while a plan points to it. See
[the journal](/apply/journals/) for what is inside
`journals/`, and why undo reaches back at most 5 writes.

Each entry in `journals/` is named `<UTC time>-<kind>-<desk>.json`, for
example `20260924T190104.102728Z-amend-S2203A1.json`: the time first, so
the files sort in the order the desks received them; the kind (`apply`,
`patch`, `amend` or `undo`); and the **serial number** of the desk it wrote to, as
the desk states it. A desk that states no serial is named by the address
it was reached at instead (`...-apply-198.51.100.7.json`, with `_port<N>` on
the end only for a port other than 2223). Anything that is not a letter,
digit or dot becomes `_`. The serial rather than the IP, because the IP
changes when the desk moves from the home network to the gig network and
the desk does not. See [One plan, two desks](/apply/two-desks/).

`plan.json` has one writer: `build`, because it is made from the input
list, the conventions and the instructions. A confirmed change or amend
records what it put on a desk in that desk's entry under `journals/`, and
the next change or amend of that desk reads it from there rather than
from `plan.json` — which is also how a backup desk still gets channels
the primary was changed with (see [Amending both desks](/apply/two-desks/#amending-both-desks)).
See [After a confirmed amend or change](/patch/amend/#after-a-confirmed-amend-or-change-planjson-is-unchanged).
For the rebuilt-plan route, build the
rebuild to a different file (`--out my-show/rebuilt.plan.json`) rather
than over `plan.json`: the amend needs both. On the command line
that path is relative to where you run it, not to the bundle.

**A missing slot is an ordinary state, not an error.** There is no
`plan.json` until the first build and no `journals/` until the first
confirmed write, and a bundle in that state is a perfectly good
bundle. Each command asks only for the slots it actually needs.

A snapshot is **not** a bundle slot: it is a capture of one moment
rather than one of the show's standing artifacts, so `compare` always
wants it named explicitly.

## What `--show` saves you

`verify` is the clearest case, because both of its file arguments are
bundle slots — the plan and the input list both come from the directory:

```
atoo verify --show docs/user/demo/touringband
```

```
0 error(s), 0 warning(s), 15 note(s)

  [info] plan: 'Magenta' is the desk's Pink (11): EG 1. The desk has no colour called 'Magenta'; Atoo used that name for 11 until the desk was asked, so it still resolves. Say 'Pink' to use the desk's own word  (strip.colour-alias)
  [info] plan.mute_groups[Speech]: mute group 'Speech' is declared but no channel or bus joins it -- it does nothing  (group.empty)
  [info] busses[MON5, MON6, Drums, Drums Comp, Vocals, Keys, Horns, VOX Reverb, VOX Delay, Snare Verb, INST Reverb] (11 busses): width set to stereo -- the conventions did not state it; decided by the generator: Instructions add MON5 and MON6 as stereo IEM mixes, patched to AES50-A socket pairs / Mix busses conventionally stereo / FX busses conventionally stereo  (inferred.bus-width)
  [info] outputs[Matrix 1]: Matrix index set to 1 -- the plan left it out; decided by Atoo's fallback rule: its name, 'Matrix 1', states slot 1  (inferred.output-index)
  [info] channels[Keys L]: linked as a stereo pair -- no convention states it; decided by the generator: Input list designates Keys L/R as left/right pair on consecutive AES50-A sockets 15+16; stereo pairing conventional for DI sources  (inferred.channel-stereo)

APPLICABLE: notes only -- choices made where the conventions were silent.
```

The transcripts on this page run from the top of an Atoo checkout,
on `docs/user/demo/touringband`, a touring band's show frozen so that
what is printed here stays true. On your own show it is `--show my-show`.

**Every command that reads a show's files takes `--show`:** `build`,
`verify`, `compare`, `apply`, `patch`, `amend`, `undo`, `audit`, `watch`,
`ui` and `lessons`. (`ping` needs only an address, and `presets` reads
your preset library, not a show.)

`compare` takes the plan from the bundle and the snapshot from you:

```bash
atoo compare --show docs/user/demo/touringband \
                  --snapshot docs/user/demo/touringband/console-after-apply.snap
```

```
110 difference(s), 0 not compared

  [error] ch 1 (Kick): plan sends to 'MON5' at -144dB; the desk saved 0dB  (snapshot.send-level)
  [error] ch 1 (Kick): plan sends to 'MON5' pre-fader; the desk saved POST  (snapshot.send-mode)
  ...
  [error] ch 4 (Tom1): plan patches to A 3; the desk is on A 4  (snapshot.patch)
  ...
  [error] ch 9 (Keys L): plan names this 'Keys L'; the desk has 'Keys'  (snapshot.name)
  ...

Only fields the plan actually states are compared -- a null fader is not an assertion about where the fader should be.
```

Exit `2`. Those differences are real. The capture was saved from a
desk running an earlier build of this show, and `plan.json` has since
been rebuilt from an edited input list and `instructions.md`, so the two
now disagree about sends, DCA membership, mutes, high-passes and one
name. Three of the differences — Tom1, BassDI and EG 1 patched one socket off — go back to
the capture itself. That is what makes it a usable example rather than a
green screenshot.

`watch` picks up `watch.json`, which nothing on the command line named.
Against the demo capture that ships beside the bundle:

```bash
atoo watch --show docs/user/demo/touringband --state-sequence docs/user/demo/audit-demo/audit_demo_state.json
```

```
Watching 1 state file(s) in sequence every 2s (Ctrl-C to stop) -- read-only, nothing here writes to a console.

[2026-10-03T07:22:45+00:00] baseline -- 16 finding(s) already present:
Audit findings: 8 warning, 8 info.

... the 16 findings
```

Drop `--show` and the same command reports **15**. The bundle adds two
from its own `watch.json`, which nothing on the command line named: its
`Kick` condition fires (`CH 1 "Kick" is not muted`), and its
`main-fader-floor` condition adds a note that it read `Main` as
`MAIN 1`. It also takes one away: with the bundle's plan, L002 is
quiet about CH 7's fader at the floor, because the plan puts that fader
there. See [Watch conditions](/watch/watch-conditions/) for what those findings
mean.

## An explicit flag always beats the bundle

`--show DIR --plan elsewhere.json` reads `elsewhere.json`. This is the
same precedence a flag already has over a default in
`~/.atoo.config`, and it is how you check one show's plan against
another show's input list — usually by accident, and usually
informatively:

```
atoo verify --show docs/user/demo/touringband --plan starter/demo-show/plan.json
```

```
30 error(s), 0 warning(s), 3 note(s)

  [error] channels[Rack Tom]: source 'Rack Tom' is not on the input list -- the plan invented an input that nobody is going to plug in  (reconcile.invented-source)
  ...
```

## Two files that do not go in the bundle

**Your conventions file stays outside it.** Conventions are your standing
house style — how *you* set up a board, re-run against every show you
ever do. A copy in every show directory would defeat the point, so the
bundle has no slot for one and you name it each time with `--conventions`,
or once in `~/.atoo.config`. See [Writing
conventions](/build/conventions/).

**`instructions.md` is the opposite, and it does go in the bundle.** It
is how *this one* show works — `touringband/instructions.md` adds two
stereo IEM mixes, MON5 and MON6, and high-passes the vocals at 100Hz
tonight rather than the house 120Hz. Both layers reach the model on a build, and the
build says which wins — your house style is the default, anything the
show restates replaces it **for this show only**, and where
`instructions.md` is silent the conventions apply in full. Whenever there
is more than one layer the build prints them in order, and records the
same list in the plan itself at `meta.conventions_stack` — because a plan
you cannot explain afterwards is worse than one you have to think about.

Neither file has to be made by hand first. In `atoo ui`, Build step
01's **New file** makes an empty house conventions file (and can name it
in `~/.atoo.config` for you), and step 03's **New file** makes an
empty `instructions.md` in the open bundle when it has none. Both
refuse to overwrite anything. Each step edits its file as one text, and
offers an **Example** beside the editor — a starting layout of headings
and comments, with no rules — that reaches the file only if you insert
it and Save. See
[Build's first three steps](/build/build-a-show/).

**A file you already have is copied in, not pointed at.** In the UI,
choosing an input list or an instructions file from outside the open
bundle with a Build tile's **Change file** copies it into the bundle as
its `input.csv` or `instructions.md`, and says so — *"Copied
~/lists/band.csv into festival/input.csv -- the bundle now owns its copy;
edits to the original won't reach it."* A bundle that already has one is
asked first (replace it, keeping the old one as `backups/input.csv.bak`; keep the
bundle's; or cancel), never overwritten silently. So **New show…** and
then an input list from your downloads folder gives you a complete,
self-contained bundle. The house conventions file is the exception, for
the reason above: it is used where it is, never copied. See
[the file browser](/build/build-a-show/#1-make-the-show).

**`watch.json` goes with the bundle the same way.** Watch's
**Watch conditions** names the bundle's `watch.json`, and its **Change file**
copies a watch-conditions file from outside into the bundle as
`watch.json` — the same question before replacing one, the same
`backups/watch.json.bak`, the same note in the Findings panel. **New file** makes an
empty `watch.json` in the bundle when it has none, and **Save** writes the
bundle's. With no bundle open, a file is used where it is. See
[Watch conditions](/watch/watch-a-show/#3-say-what-matters-tonight-watch-conditions).

That record says where each file is **relative to the bundle** — usually
`../house-rules.md` — along with its absolute path and a fingerprint
(sha256) of what it held. So when you open the bundle in the UI, step 01
shows the conventions file this show was built from, not whatever your
config names today, and tells you if that file has been edited since, has
moved, or is gone. Move the bundle and its house file together and it
still finds it.

A build records the same fingerprint of `input.csv`, at `meta.input_list`.
With all three recorded, the UI can say a plan is
**stale** — `input.csv`, `instructions.md` or the house file has changed
since it was built — and offer **Rebuild plan**; `atoo apply --show`
and the Apply screen's pre-flight say so as a WARNING. All three files
can be edited in the UI — see
[Editing the three files](/build/build-a-show/).

## A build writes back into the bundle

Point `build` at the directory and the plan lands *in* it, rather than
beside whatever `--out` happened to name:

```bash
atoo build --console-model wing-compact --show my-show --conventions conventions.md
```

After that the directory is one draggable thing holding the whole show.
The build also leaves its own log in `builds/` — one file per build,
kept even when the build fails or is stopped, the newest 5 at a time; see
[the pipeline](/build/pipeline/).

A bundle build drafts `watch.json` too — a short list of things worth an
alert if they move mid-show, written by a pass that reads the finished
plan. Each drafted entry is marked `"source": "drafted"`, and **the file
is yours**: edit it, delete from it, raise a severity. A later build
**merges** rather than overwrites. It keeps a description you rewrote, and
it does not restore a condition you deleted — a top-level `drafted` list
records everything that has ever been proposed, which is what makes a
deletion stick. Without it, a rule you removed on purpose would look
exactly like one that was never drafted.

Two things a watch-conditions draft will not do: fail your build (a plan
that built and a draft that did not is a warning, not an error), and write
anything it cannot validate. Each drafted condition is checked on its
own: a key a condition does not have is dropped, a condition naming a
field outside the vocabulary is left out, each with an `INFO
watch-conditions draft:` line saying which, and the rest are kept. A draft with nothing
usable in it writes nothing, and leaves any existing `watch.json` as it
was.

`apply --confirm` writes back too — a new, timestamped entry in
`journals/`, which it never overwrites. The newest 5 entries are kept,
so undo reaches back at most 5 writes ([the journal stack](/apply/journals/#the-stack));
copy one aside if a particular run must outlive that.

## When a directory is not a bundle

Each command names the slot it could not find:

```
demo-show is not a usable show bundle: no 'plan.json' in it. A bundle is a directory with fixed filenames inside (input.csv, instructions.md, plan.json, watch.json) -- see docs/user/show-bundles.md.
```

The mistake this guards against is laying a bundle out by hand and naming
the input list after the show. The filenames are not suggestions.

`--input`, `--plan` and the rest work without a bundle too. A bundle is
an extra way to invoke, not a replacement.

## See also

- [Command-line quickstart](/getting-started/quickstart/) — the whole path, once, on `touringband`
- [Writing an input list](/build/input-lists/) — what goes in `input.csv`
- [Writing conventions](/build/conventions/) — the file that stays outside the bundle
- [The journal](/apply/journals/) — what `apply --confirm` writes into `journals/`
- [Watch conditions](/watch/watch-conditions/) — what `watch.json` is for
- [Command reference](/reference/cli-reference/) — every flag, generated from the code
