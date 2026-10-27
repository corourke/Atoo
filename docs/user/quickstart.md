# The command line

Everything you did in the browser is also a command. The command line adds a few things the browser doesn't: you can check a saved reading of a desk with no desk attached, replay one in Watch, keep a record of a desk before and after a change, and script any of it.

This page runs one show from files to desk on your own WING, then shows some useful things to try. It uses your copy of the Demo show, and your desk's address saved in [Set up Atoo](configuration.md); the examples use `192.0.2.16`, so type your own if you didn't save it.

## Part 1: one show, from files to desk

### 1. Make a copy of the Demo show

If you haven't already:

```bash
atoo init --demo
cd ~/Documents/Atoo
```

### 2. Check the plan

```bash
atoo verify --show demo-show
```

```
0 error(s), 0 warning(s), 4 note(s)

  [info] plan: 12 channel(s) carry a preset's values, written at the processing stage and read back like every other write: ...  (preset.expanded)
  [info] plan: 3 bus(ses) carry a bus preset's processing, written at the processing stage and read back like every other write: ...  (preset.bus-expanded)
  [info] plan: 1 FX insert(s) are loaded and switched on, each read back: Vox Verb: V-REV on FX5 (saved bypassed, switched on)  (fx.inserts)
  [info] channels[Music]: aux 1 'Music' is not on the input list; built because instructions.md says 'Walk-in music ("Music") on Aux 1, stereo, source LCL 3-4. Fader at -20dB', on LCL 3-4 as it states  (reconcile.from-instructions)

APPLICABLE: notes only -- choices made where the conventions were silent.
```

The last line is the verdict. Only `BLOCKED: do not apply.` stops an apply ([Reading findings](reading-findings.md)).

### 3. Build it again (needs a model)

```bash
atoo build --show demo-show
```

A build takes a few minutes and shows its progress as it goes. It takes the desk model from the show's own plan; add `--console-model wing-full` or `wing-rack` to build for a different WING.

### 4. Read your desk

These two write nothing, so they are safe on a desk that is running a show.

```bash
a2 ping
atoo audit --dump-state my-desk.state.json
```

`ping` confirms the desk answers. `audit` reads the whole desk, checks it against the built-in rules, and saves what it read to `my-desk.state.json`. Check each finding against the desk.

### 5. Preview, then write

**Only on a desk that is not running a show**, with its own show saved first. A full apply resets the desk, then writes the plan ([What a full apply changes](what-apply-changes.md)).

```bash
atoo apply --show demo-show
```

This writes nothing: it reads the desk, shows what would change, and ends with `Nothing was written -- this was a preview. Re-run with --confirm to apply.` Then:

```bash
atoo apply --show demo-show --confirm
```

Every value is read back afterwards. The line that starts `APPLIED:` counts what was written, and a `MISMATCH` line names anything that didn't land ([Applying a plan](applying.md)).

### 6. Watch it

```bash
atoo watch --show demo-show --count 3
```

Three readings, two seconds apart. Leave out `--count` to watch until you press `Ctrl-C`.

### 7. Undo, and put the desk back

```bash
atoo undo --show demo-show
atoo undo --show demo-show --confirm
```

The first previews the undo; the second does it. Then load the show you saved on the desk.

## Part 2: useful things

**Check a desk with no desk attached.** `audit` reads a saved reading as well as a live desk. `atoo init` gives you one to try:

```bash
atoo audit --state audit-demo/audit_demo_state.json
```

```
Audit findings: 7 warning, 3 info.

[WARNING] C001 Phantom Power On Unpatched Socket
  48V is on for LCL 9 but nothing is patched to it -- no channel, no aux and no user patch.

[WARNING] CH002 DCA Fader Low With Active Members
  DCA 1 "Drums" is at the floor (-20dB or lower) but controls 2 active member(s): CH 1 "Kick", CH 2 "Snare".
  ...
```

**Replay a change in Watch.** Give Watch two saved readings, and it reports what changed between them, as it would live:

```bash
atoo watch --state-sequence audit-demo/audit_demo_state_before.json,audit-demo/audit_demo_state.json
```

```
[...] change detected:
  NEW     [WARNING] C001 Phantom Power On Unpatched Socket: 48V is on for LCL 9 but nothing is patched to it -- no channel, no aux and no user patch.
  NEW     [WARNING] CH002 DCA Fader Low With Active Members: DCA 1 "Drums" is at the floor (-20dB or lower) but controls 2 active member(s): CH 1 "Kick", CH 2 "Snare".
  ...
```

**Keep a record of a change.** Save a reading before and after you write to a desk, and you can see exactly what changed, or send both with a [report](reporting.md):

```bash
atoo audit --dump-state before.state.json
atoo audit --dump-state after.state.json
```

**Preview a typed change.** `atoo patch` does what Patch does in the browser. Without `--confirm` it only previews:

```bash
atoo patch --show demo-show "trumpet, sax and trombone on LCL 21-23, Band DCA"
```

**Capture a desk you didn't build:**

```bash
atoo capture --console 192.0.2.16
```

**See what your builds keep asking.** `atoo lessons` reads a show's builds and lists what the model kept having to guess, so you can add it to your conventions:

```bash
atoo lessons --show demo-show
```

**Every command explains itself.** `atoo <command> --help` lists its options. The [Command reference](cli-reference.md) has every command and flag, and the [Rules reference](rules-reference.md) every rule `audit` and `watch` can report.

**Exit codes.** `0` is clean, `1` means it couldn't run, and `2` means it ran and found problems; `audit` and `watch` report findings with `1` ([Exit codes](cli-reference.md#exit-codes)).

## Where next

| I want to... | Page |
|---|---|
| write the input list for my own show | [Writing an input list](input-lists.md) |
| write down how I set up a desk | [Writing conventions](conventions.md) |
| understand what `apply` guarantees | [Applying a plan](applying.md) |
| keep one show's files together | [Show bundles](show-bundles.md) |
| check a desk that is already set up | [Checking a desk](audit.md) |
| report something that went wrong | [Reporting a problem](reporting.md) |
| work out why something failed | [Troubleshooting](troubleshooting.md) |
