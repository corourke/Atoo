---
title: "Applying a plan to a console"
description: "atoo apply writes a plan to the desk and then reads every value back. The readback is the product: a remote write can fail silently, so the only thing that makes \"the console is set up the way you…"
sidebar: 
  order: 2
---

<!-- Generated from docs/user/applying.md by tools/docs_to_starlight.py in the development repository. Edit it there. -->
`atoo apply` writes a plan to the desk and then reads every value
back. The readback is the product: a remote write can fail silently, so
the only thing that makes "the console is set up the way you wrote it
down" a fact rather than a hope is asking the console afterwards.

If you have not applied a plan before, [Command-line quickstart](/getting-started/quickstart/) walks
one through end to end. This page is what it means and how to steer it.

## Preview first, then `--confirm`

```bash
atoo apply --show touringband --console 192.0.2.16            # preview
atoo apply --show touringband --console 192.0.2.16 --confirm  # writes
```

Without `--confirm`, `apply` **changes nothing**. It does everything
except the writes: verifies the plan, contacts the desk, reads the
current value of every address the plan would touch, and tells you what
would change. Writing takes explicit arming, and there is no flag that
arms it implicitly.

`--show DIR` takes the plan, the input list and the journal's destination
from a [show bundle](/build/show-bundles/). Without it, name the plan with
`--plan` and, ideally, the input list with `--input`: several checks —
that every input became a channel, that no channel was invented, that
phantom power is safe for the mics in use — are skipped when `apply`
cannot see the list the plan was built from, and it says so rather than
passing silently.

The console address can come from `--console`, from `$ATOO_CONSOLE`,
or from a `[console]` section in `~/.atoo.config`, in that order. A
run that connects somewhere the command line never named says so on
stderr.

## What happens, in order

1. **The plan is read and checked** against the plan schema, then
   verified against the console's limits and the input list. **Errors
   stop the run here, before the desk is contacted**, so an impossible
   plan never reaches hardware:

   ```
   Refusing to apply 'touringband/plan.json'. Fix the plan, or pass --skip-verify if you have a reason to write it anyway.
   ```

   See [`verify` says `BLOCKED: do not apply.`](/troubleshooting/troubleshooting-verify/#verify-says-blocked-do-not-apply).
   Warnings print and the run continues.
2. **The desk states its model.** A plan built for a different WING is
   checked against this desk's sockets: all there, and it is applied
   with an INFO; a socket the desk does not have stops the run, named.
   See [A plan built for a different
   model](/apply/two-desks/#a-plan-built-for-a-different-model).
3. **The desk is asked what is in its expansion bays**, and a plan that
   patches from or to an empty one stops here. See
   [Expansion bays](/apply/what-apply-changes/#expansion-bays-crd-and-mod).
4. **The desk is reset to its initialized state**, so nothing from the
   last show carries over (`--no-init` skips it). See [What a full apply
   changes on the desk](/apply/what-apply-changes/).
5. **Every address is read** for its current value, the baseline the
   journal keeps.
6. **Values that already agree are not written.** Many of the desk's
   values are stepped, so a low-cut asked for at 100Hz that reads back
   as 100.237Hz already agrees. The exception is a value whose
   [selector](/apply/what-apply-changes/#a-selector-is-written-before-the-values-it-governs)
   this run changes.
7. **Everything else is written and read back.** On each strip, the
   selectors go first, then the values, then the on-switches.
8. **The journal is written**, and the summary printed.

### While it runs

Steps 4 to 7 talk to the desk and can take a minute. Each one says what
it is doing on stderr while it does it, naming the address in flight,
and ends with a count and a time. This is a confirmed apply, cut short,
run against a test desk (so the times are tiny):

```
  reading the desk for the reset 99/1988 (4%) 0s -- /io/in/B/19 (node)
  reading the desk for the reset 198/1988 (9%) 0s -- /io/in/SC/22 (node)
  ...
  reading the desk for the reset: 1988 of 1988 addresses in 0.1s
  every address answered.
  resetting to initialized, reading each back 1/1 (100%) 0s -- /ch/30/name
  resetting to initialized, reading each back: 1 of 1 settings in 0.0s
  writing, reading each back 139/2787 (4%) 0s -- /ch/14/in/conn/grp
  ...
```

A preview shows `reading the desk for the preview` in place of the
writes. If some readbacks disagree, `reading back again what disagreed`
follows the writes. In a terminal the line is rewritten in place; in a
log it is a plain line about twenty times per step. `--no-progress`
turns it off. stdout and the journal are the same either way.

Steps 1 and 2 need no console: point `apply` at an address where nothing
is listening and the verdict still prints first. Here it is on the Demo
show, from an Atoo checkout:

```
atoo apply --plan starter/demo-show/plan.json --input starter/demo-show/input.csv --console 127.0.0.1 --timeout 0.2
```

```
0 error(s), 0 warning(s), 4 note(s)

  [info] plan: 12 channel(s) carry a preset's values, written at the processing stage and read back like every other write: ch 1 Kick In (83), ch 2 Snare (83), ch 3 H Tom (83), ch 4 Fl Tom (83), ch 5 OH (83), ch 6 Bass (83), ch 7 E Gtr (83), ch 8 E Gtr (83), ch 9 Keys (83), ch 10 Vocal (80), ch 11 Vocal (80), ch 12 Vocal (80)  (preset.expanded)
  [info] plan: 3 bus(ses) carry a bus preset's processing, written at the processing stage and read back like every other write: Drums: 'Mix Bus' (55), Vocals: 'Mix Bus' (55), Vox Verb: 'Vox Verb' (55)  (preset.bus-expanded)
  [info] plan: 1 FX insert(s) are loaded and switched on, each read back: Vox Verb: V-REV on FX5 (saved bypassed, switched on)  (fx.inserts)
  [info] channels[Music]: aux 1 'Music' is not on the input list; built because instructions.md says 'Walk-in music ("Music") on Aux 1, stereo, source LCL 3-4. Fader at -20dB', on LCL 3-4 as it states  (reconcile.from-instructions)

APPLICABLE: notes only -- choices made where the conventions were silent.
no reply from 127.0.0.1:2223 -- is the console reachable, and is its OSC remote enabled?
```

A plan with no findings prints nothing before the `no reply` line. With
`--show`, the gate also warns when the plan is older than the bundle's
inputs (`plan.older-than-inputs`), for instance when the conventions
were edited after the last build.

A full apply also unpatches the strips the plan does not build, sets
every direct Main route, the talkback assign and each strip's main
input. [What a full apply changes on the desk](/apply/what-apply-changes/)
lists each one.

## Reading the result

```
APPLIED: 631 address(es) evaluated, 337 written, 2 mismatch(es).
  MISMATCH /bus/10/name: expected 'VOX Delay', read back ''
  MISMATCH /ch/10/tags: expected '#D6,#M1', read back ''
  note: 31 stale reply/replies from the console were discarded (duplicated or unsolicited datagrams). Readbacks above are matched by address, so this did not affect them.
```

Every address ends in one of five states:

| status | what happened |
|---|---|
| `match` | written, read back, and the desk agrees |
| `skipped_no_change` | the desk already held this value; nothing written |
| `mismatch` | written, read back, and the desk reports something else |
| `unreadable_skipped` | no baseline could be read, so nothing was written |
| `dry_run` | a preview: evaluated, never written |

- **`skipped_no_change` is proof, not a gap.** The plan states it and
  the desk already satisfies it. It is why "written" is smaller than
  "evaluated": above, 294 of 631 were already correct.
- **An `UNREADABLE` line is not a pass.** Nothing was written there, and
  the run cannot vouch for it.
- **Mismatches exit `2`** and are repeated on stderr by address. A
  mismatch you can see is the point: a write that failed silently is
  what this tool exists to catch. See [`apply` says a value did not land, but the desk shows
  it](/troubleshooting/troubleshooting-desk/#apply-says-a-value-did-not-land-but-the-desk-shows-it).
- **A stage box's gain is read back on the box's own steps.** A preamp
  on an AES50 stage box holds the nearest gain it has (20.0 asked, 20.5
  held). Within half a dB that is a `match`, and one INFO line says so.

[The journal](/apply/journals/) records every one of these, with the value
the desk held before, and explains how a late answer from the desk is
settled.

## The journal stack

Every confirmed write in a bundle is filed in its `journals/` directory,
and the newest 5 are kept, so `atoo undo` reaches back at most 5
writes. See [The journal](/apply/journals/).

## Flags worth knowing

| flag | what it is for |
|---|---|
| `--confirm` | actually write. Without it, nothing is written. |
| `--journal PATH` | put the journal somewhere other than the default |
| `--raw-log PATH` | append every raw OSC request and reply, with hex bytes. What you want when a mismatch needs diagnosing rather than describing — and worth passing on any apply you may have questions about later. |
| `--clean-output-sockets LCL=24,A=48` | opt-in, off by default: disconnect physical output sockets in those groups that the plan routes nothing to. Without it, whatever was patched there by an earlier show stays. |
| `--presets DIR` | Atoo's own `.chn` library. `apply` does not need it to write a preset -- `build` already put the preset's values into the plan -- and uses it only to say whether a preset changed since, or to name one the plan names and does not carry. A plan naming a preset it cannot find is a warning, never a block. |
| `--skip-verify` | write a plan verification refused. See below. |
| `--console-model` | check the plan for this model instead of the one recorded in it |
| `--port`, `--timeout` | OSC port (default 2223) and per-request timeout (default 1.0s) |

**`--skip-verify` is the one to be careful with.** It does not make a
plan safe; it removes the check that runs before hardware is touched, and
verification is the only step that can refuse a plan for free. Use it
when you know precisely which finding you are overriding and why.

What it never skips is the hardware: a socket the plan patches that this
desk does not have is still refused by name, on the same model as well
as across models — exactly as `amend` refuses it.

## Exit codes

| code | meaning |
|---|---|
| `0` | applied, and everything read back as intended — or a preview that found no reason to stop |
| `1` | an unreadable file, no `--plan` or `--show` given, the console could not be reached, or the connection dropped mid-run |
| `2` | the run ran and found problems: **something did not land**, or it refused to proceed — because verification found errors, the plan patches a socket this desk's model does not have, or an expansion bay this plan uses is empty. Also a command line argparse rejected, or no console address at all |

A preview exits `0` on a plan it would apply cleanly, so
`atoo apply … && echo ok` is a usable pre-flight check in a script.

Tell `1` and `2` apart in a script. `1` means Atoo never got far
enough to have an opinion: a bad path or an unreachable desk. `2` means
the run happened and the desk is not what the plan asked for. `0` is the
only code that means every value landed.

```bash
atoo apply --show touringband --console 192.0.2.16 --confirm
case $? in
  0) echo "every value landed" ;;
  1) echo "could not run -- check the address and the plan path" ;;
  2) echo "ran, and something is wrong -- read what it printed" ;;
esac
```

**This table is `apply`'s, not the whole tool's.** `build`, `verify` and
`compare` use `2` the same way, but `audit` and `watch` report their
findings with `1`, because they hold no plan — so the
`case` above does not transfer to them unchanged. The
[canonical exit-code table](/reference/cli-reference/#exit-codes) covers every
command in one place.

## What `apply` will not do

- **It does not mix.** It writes a fader or mute value only for a strip
  this plan builds, and only a value the plan itself states — or its
  documented default of unity and unmuted when the conventions said
  nothing at all. It never chooses a level.
- **It touches a strip the plan does not mention only to unpatch it.** A
  channel from last week's show that this plan says nothing about keeps
  its name, fader, mute and processing; its source is set to `OFF`, so
  it listens to nothing (see [Strips the plan does not
  build](/apply/what-apply-changes/#strips-the-plan-does-not-build-unpatched-from-their-sources)).
- **It is not the mid-show tool.** A full build writes every address in
  the plan, including every fader of every strip already in use. Use
  [`atoo patch`](/patch/patch/) for that.
- **It cannot recall the desk's own scenes or presets.** Those cannot be
  reached over the network. Your channel presets are written as ordinary
  values instead, read back and journalled like the rest. See [Using
  channel presets](/build/presets/).

## See also

- [Undoing a write](/apply/undo/) — `atoo undo`
- [Patching a running show](/patch/patch/) — `atoo patch`
- [Patching from a rebuilt plan](/patch/amend/) — `atoo amend`
- [One plan, two desks](/apply/two-desks/)
- [What a full apply changes on the desk](/apply/what-apply-changes/) — the reset, unpatching, Main routes, talkback
- [The journal](/apply/journals/) — what every write leaves behind, and how far undo reaches
- [Command reference](/reference/cli-reference/) — every flag, generated from the code

- [Apply a plan to the desk](/apply/apply-to-desk/) — the same, in the browser
- [Command-line quickstart](/getting-started/quickstart/) — the whole path, once, on the shipped example
- [Checking a desk](/watch/audit/) — checking a desk nobody just applied to
- [Troubleshooting](/troubleshooting/troubleshooting/) — when it will not connect, or something did not land
