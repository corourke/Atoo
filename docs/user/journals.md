# The journal: what every write leaves behind

Every confirmed write to a desk (`apply`, `patch`, `amend`, `undo`) leaves a journal: each address it touched, what the desk held before, what was asked for, and what the desk said afterwards. It is the proof that the desk is set up the way you wrote it down, and it is what `atoo undo` reads to put the desk back.

## Where it goes

In a [show bundle](show-bundles.md), every run is filed in the bundle's `journals/` directory, one timestamped entry per run:

```
touringband/
  journals/
    20260924T054016.101288Z-apply-S2203A1.json     the stack, oldest first
    20260924T061502.774310Z-amend-S2203A1.json
    20260924T062011.930451Z-undo-S2203A1.json
    index.json                                     so a listing need not open them
```

Each name is the UTC time the run was filed, its kind, and the serial number of the desk it wrote to (or, for a desk that states no serial, its address). Sorting the names sorts the runs. See [One plan, two desks](two-desks.md#one-plan-two-desks) for why the desk is in the name.

Without a bundle, `apply` writes `<plan-stem>.apply-journal.json`, or wherever `--journal` says.

## What is in one

One row per address:

```json
{
  "address": "/dca/1/name",
  "description": "DCA 1: name",
  "value_type": "s",
  "method": "node",
  "ack": "OK",
  "prior_value": "",
  "intended_value": "Drums",
  "readback_value": "Drums",
  "status": "match",
  "timestamp": "2026-09-22T00:38:13.677058+00:00",
  "readback_source": null
}
```

- **`prior_value`** is what the desk held before the write. It is what lets `undo` reverse the run without reading the desk again.
- **`status`** is one of the five outcomes in [Reading the result](applying.md#reading-the-result).
- **`readback_source`** is `null` when the readback straight after the write settled it, and says otherwise (below).

Beside the rows, the journal says how the run ended: **`aborted`** is `true` for a run that stopped partway, **`abort_reason`** says why, and **`stopped`** is `true` when you stopped it (Ctrl-C, or **Stop** on the Apply page) rather than the desk. See [A run that stopped partway](#a-run-that-stopped-partway).

## Why every value is read back

The desk does not acknowledge every write. A text value containing a space, comma or equals sign goes by a path that gets no answer at all, and an answer on the other path proves the message arrived, not that the desk kept the value. So every write is read back.

The desk sometimes answers a readback late, with the value it held before the write, and the new one a moment later. Atoo does not believe a disagreement straight away: it looks at what the desk sent afterwards about **that address**, and if that does not settle it, re-reads the address once after the run's last write. Only then is it a mismatch. A late answer counts only if it names the same address, arrived after the write, and carries the value asked for, so a write the desk never accepted stays a mismatch.

A verdict reached that way is marked: `readback_source` is `"late_reply"` (the desk's own reply, late) or `"recheck"` (the re-read), and the summary's note counts them:

```
  note: 1 stale reply/replies from the console were discarded (duplicated or unsolicited datagrams). Readbacks above are matched by address, so this did not affect them. 1 of them named an address whose readback had raced the write, and confirmed it.
```

## The stack

Nothing overwrites anything. A second amend keeps the first amend's journal, and a run that **aborted** partway is filed too: it is the one most worth being able to reverse (below).

That includes an undo that aborted. It is filed, but it does not pop the run it was reversing, because some of that run's writes are back and some still stand. Run `atoo undo --show DIR` again and it finishes the job.

Each apply, patch and amend entry also carries the plan it left on the desk. That is what the next `patch` or `amend` of that desk compares against.

## A run that stopped partway

A run stops partway when the desk stops answering, when you press Ctrl-C, or when you press **Stop writing** on the Apply page (see [If the desk stops answering, or you stop it](applying.md#if-the-desk-stops-answering-or-you-stop-it)). Its journal holds every write that was sent before the stop, and nothing after it:

- a write the desk took is `match` (or `mismatch`), as in any run;
- a write that was sent and never answered is `unreadable`: whether it landed is unknown, and Undo looks before it touches it.

The journal is **saved as the run goes**, about once a second, so it is on disk even if Atoo itself is killed outright (the laptop's power, a forced quit). A journal saved that way says `"aborted": true` with the reason *the run did not finish*, and it is on the stack like any other: `atoo undo --show DIR` finds it.

To take a stopped run back off the desk, undo it like any other. This is the undo of the apply in [Applying a plan](applying.md#if-the-desk-stops-answering-or-you-stop-it), once the desk answered again; the 60 `RESTORE` lines of the preview are left out:

```
Reversing the newest entry in demo-show/journals on this desk:
  2026-11-07T16:31:05.535370+00:00  apply  ABORTED: lost the connection to the console (the desk answered none of the last 3 requests, nor a check of /io/in/A/14/g after them).  [on Demo (wing-compact) serial DEMO-SIMULATED, at 127.0.0.1:40814]
Undo of demo-show/journals/20261107T163059.663971Z-apply-DEMO_SIMULATED.json
  NO CHANGE /io/in/LCL/2/g: already back at 0.0
  NO CHANGE /io/in/LCL/1/g: already back at 0.0
  NO CHANGE /io/in/A/15/g: already back at 0.0

DRY RUN: 60 would be reversed, 3 already back.
  (175 journal record(s) were never written)
```

The three **already back** are the writes the desk never took. Or run the apply again instead: it finishes the job, skipping everything that landed.

## How far back undo reaches: the newest 5

`journals/` keeps the newest **5** entries, pruned after each run. The limit is fixed. Pruning removes the oldest first, but takes runs an undo already reversed, and the undos themselves, before a write that is still on a desk. It never removes a desk's newest standing write: with two desks, the backup's one old apply keeps its place however many writes the primary takes.

So **undo reaches back at most 5 writes.** When a write still on the desk has been pruned, `undo` stops at the entry above it, writes nothing and exits `1`:

```
nothing more to undo on this desk: my-show/journals keeps only the newest 5 entries. This desk's last write still journalled is
  2026-09-23T00:00:00+00:00  apply  APPLIED: 1 address(es) evaluated, 1 written, 0 mismatch(es).  [on no serial, at 198.51.100.7]
and the write beneath it was pruned (20261002T162704.453182Z-apply-198.51.100.7.json, apply). Undoing it would leave the desk holding a write no journal records, so amend and patch would compare against the wrong plan. Nothing was written. To change the desk from here, apply a plan (a full apply replaces everything) or patch it.
```

The run that pruned it said so at the time, in a NOTE. A pruned patch can no longer be kept in the show with `patch --promote`; the refusal quotes its text so you can put it into the sheets in Build's step 04 yourself.

Copy an entry somewhere else if a particular run must outlive the five. `index.json` is a cache for listing the stack; delete it and it is rebuilt from the journals, all but its list of pruned runs.

## See also

- [Undoing a write](undo.md): `atoo undo`
- [Applying a plan](applying.md): reading the result
- [Show bundles](show-bundles.md): the bundle's other files
