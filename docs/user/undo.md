# Undoing a write: `atoo undo`

*From the command line. In the browser, see [Apply a plan to the desk](apply-to-desk.md#undo-the-last-write).*

```bash
atoo undo --show touringband --console 192.0.2.16
atoo undo --show touringband --console 192.0.2.16 --confirm
```

The first form changes nothing. It reads the console's current value for
every address the run wrote and shows you, per address, what it would put
back and what it would refuse. `--confirm` arms it, exactly as on `apply`,
and there is no second switch.

You can also name a journal: an entry in `journals/`, or any other
journal file (`<plan-stem>.apply-journal.json`
from an apply without a bundle, or one `--journal` wrote):

```bash
atoo undo touringband/journals/20260924T054016.101288Z-apply-S2203A1.json --console 192.0.2.16
```

A bundle with no `journals/` has recorded no writes, and `undo --show`
says so without contacting the desk (exit `1`). A show that has never
been applied has none:

```
nothing to undo: touringband has recorded no writes (nothing in journals/).
```

## One step back in time

With `--show` and no journal named, undo reverses the **top of the
bundle's stack** — the newest write still standing on the desk, whatever
kind it was. It says which one before it does anything:

```
Console: WING,198.51.100.9,FOH-A,wing-compact,S2203A1,3.1-0-g9f314617:release
Reversing the newest entry in touringband/journals on this desk:
  2026-09-24T21:25:43.965565+00:00  amend  APPLIED: 66 address(es) evaluated, 39 written, 0 mismatch(es).  (scope: ch:21, ch:22, ch:23)  [on FOH-A (wing-compact) serial S2203A1, at 198.51.100.9:2223]
Undo of touringband/journals/20260924T212543.971020Z-amend-S2203A1.json
  selection: /ch/21, /io/in/A/21, /ch/22, /io/in/A/22, /ch/23, /io/in/A/23 (this journal's own scope)
  RESTORE   ...

DRY RUN: 39 would be reversed.
  (27 journal record(s) were never written)
```

("On this desk", because each desk keeps its own history — see
[One plan, two desks](two-desks.md#one-plan-two-desks).) Each press steps back one
more, as far as the five entries `journals/` keeps allow: see
[How far back undo reaches](journals.md#how-far-back-undo-reaches-the-newest-5).

It **pops**: having reversed the amend, the next undo reverses the apply
underneath it. A second press steps back two — it does not redo the
first. (The redo is still there, and is still a command rather than a
button: see [Redo](#redo).)

## Undoing a change or an amend leaves `plan.json` alone

A change or an amend never writes `plan.json`, so undoing one has nothing
to put back: it reverses the desk and says `plan.json left as it is:
only a build writes it, and that patch did not.`

## Undoing an apply an amend was built on top of

This is refused, and it is the reason the stack exists. The guard below
is per address, and it cannot see a later run: an apply that wrote
ch 1-19 still holds every one of those values after an amend added
ch 21-23, so every address would pass and the show would come off the
desk with the horn section left standing on nothing.

```bash
atoo undo touringband/journals/20260928T210720.074082Z-apply.json --state touringband/after-apply.json
```

```
touringband/journals/20260928T210720.074082Z-apply.json is not the newest entry in touringband/journals.
1 later write(s) are still on the desk:
  2026-09-28T21:07:20.091602+00:00  amend  APPLIED: 1 address(es) evaluated, 1 written, 0 mismatch(es).  (scope: ch:21)

Reversing this one would put the console back to before them while they stay on it -- undo's own guard is per address and cannot see a later run, so every address here would pass it.
Undo them first (`atoo undo --show DIR` reverses the newest, one step at a time), or pass --out-of-order if you have a reason to reach underneath them.
```

Exit `1`, and nothing was read from the console — the refusal is made
from the files, before the desk is contacted. `--out-of-order` overrides
it and names what is still on top while it runs.

**A journal that is not on the stack is held to the same rule.** A
journal file in the bundle that `journals/` does not hold — copied in
from elsewhere, or written before the bundle had a stack — undoes like
any journal while nothing is recorded on the stack. Once something is,
whatever stands on it is newer than that journal, and `undo` on it is
refused the same way — it says the journal is not on the stack and names
what is above it — until those have been undone.

## Why this is not the same as reloading a snapshot

Save a show or a snapshot on the desk before you patch — every good
engineer does, and you should keep doing it. A snapshot is still a
different tool from this one:

| | a console snapshot | `atoo undo` |
|---|---|---|
| what it puts back | **the whole desk**, to the moment it was saved | **only the addresses this run wrote** |
| what happens to changes made since | all of them are lost | all of them are kept |
| needs to have been saved in advance | yes | no — the journal is written whether or not anyone thought about it |
| can put back half a run | no | yes, with `--only` |

If you patched at four, made three changes at
five, and want ours gone at six, the snapshot takes the other two with
it.

## The guard: only where we are still the last writer

Before restoring an address, undo **reads it**. If it no longer holds the
value we wrote, somebody has changed it since — another apply, WING-Edit,
a hand on the surface — and putting our `prior_value` there would clobber
their change. That address is **refused and reported, never written**.

The comparison is the same stepped-parameter-aware one `apply` uses, not
exact equality: a
high-pass asked to sit at 40Hz reads back at 39.905Hz because those are
the steps the desk has, and calling that "somebody changed it" would make
undo useless on exactly the addresses it most needs to handle.

Two more outcomes are counted apart from that refusal:

- **no prior value.** If `apply` could not read the address before
  writing it, `prior_value` is `null` and there is nothing to restore.
  Reported; no default is invented.
- **already back.** The address already holds its prior value — a
  previous undo, or a write that never landed. Nothing to do, and not a
  refusal: it is what makes `undo` safe to re-run after a partial one.

## Try it on a real journal, with no console attached

`docs/user/demo/undo-demo/` holds a nine-address slice of a real apply
journal from a WING Compact and `after-apply.json`, the
desk as that run left it — except that somebody has since renamed DCA 2
from `Guitars` to `Horns`. Run this from the top of an Atoo checkout:

```
atoo undo docs/user/demo/undo-demo/apply-journal.json --state docs/user/demo/undo-demo/after-apply.json
```

```
Undo of docs/user/demo/undo-demo/apply-journal.json
  REFUSE    /dca/2/name: we wrote 'Guitars', the console now reads 'Horns' -- changed since, not ours to reverse
  RESTORE   /dca/1/name: 'Drums' -> ''   (DCA 1: name)
  RESTORE   /bus/1/name: 'MON1' -> ''   (bus 1 (MON1): name)
  RESTORE   /ch/2/flt/lcf: 40.0 -> 100.23745727539062   (ch 2 (Snare): high-pass frequency)
  RESTORE   /ch/2/name: 'Snare' -> ''   (ch 2 (Snare): name)
  RESTORE   /ch/1/flt/lcf: 40.0 -> 100.23745727539062   (ch 1 (Kick): high-pass frequency)
  RESTORE   /ch/1/in/conn/grp: 'A' -> 'LCL'   (ch 1 (Kick): patch group)
  RESTORE   /ch/1/name: 'Kick' -> ''   (ch 1 (Kick): name)

DRY RUN: 7 would be reversed, 1 refused (changed since).
  (1 journal record(s) were never written)

Reviewed offline from --state; no console was contacted. Re-run with --console to preview against the desk, and --confirm to reverse.
```

Four things to read in that. The DCA 2 rename is **refused**, and it is
refused in the preview, before anything is armed. The two `flt/lcf`
addresses are **not** refused, although the desk reads 39.905 where the
journal says 40.0. The addresses come back in **reverse order** — DCA
first, channel 1's name last — because `apply` writes in an order some
addresses depend on, and unwinding has to respect it. And one journal
record was **never written** (`/ch/1/in/conn/in` was already right, so
`apply` skipped it); it has nothing to reverse.

**A strip's processing is the exception to reverse order.** Its rows are
put back **selectors first, then the values they govern, then switches**,
the same order `apply` writes them in: putting a delay mode back makes
the desk re-read the delay, so the delay has to follow it. A value a
restored selector governs is checked against the guard **before** the
selector goes back, and written after it.

`--state` is a preview against a saved capture and can never be combined
with `--confirm`: a file says nothing about what the desk holds now,
which is the whole question the guard asks.

## The same preview, as data

The browser's **Preview undo** draws this same list, in the Preview box
(step 2 of Apply). `--result-json FILE`
writes it as data, for a preview and for a confirmed run alike: one row
per address, with the strip it belongs to, the value the journalled run
wrote, the value on the desk now, the value an undo puts back, and
whether it **goes back**, is **already back**, has **changed since** (it is
left as it is) or has **no earlier value**.

```
atoo undo docs/user/demo/undo-demo/apply-journal.json --state docs/user/demo/undo-demo/after-apply.json --result-json undo-preview.json
python3 -c "import json; d = json.load(open('undo-preview.json')); print(d['outcome'], d['counts']['goes-back'], d['counts']['changed-since']); print(d['rows'][0])"
```

```
differs 7 1
{'address': '/dca/2/name', 'strip': 'dca:2', 'strip_name': '', 'control': 'name', 'written': 'Guitars', 'now': 'Horns', 'goes_back_to': '', 'verdict': 'changed-since', 'detail': None}
```

`differs` is the word for a preview that would leave something where it is;
`safe` is one where every address goes back or is already back.

## Unwinding half a run

```
atoo undo docs/user/demo/undo-demo/apply-journal.json --state docs/user/demo/undo-demo/after-apply.json --only ch:1
```

```
Undo of docs/user/demo/undo-demo/apply-journal.json
  selection: /ch/1 (--only)
  RESTORE   /ch/1/flt/lcf: 40.0 -> 100.23745727539062   (ch 1 (Kick): high-pass frequency)
  RESTORE   /ch/1/in/conn/grp: 'A' -> 'LCL'   (ch 1 (Kick): patch group)
  RESTORE   /ch/1/name: 'Kick' -> ''   (ch 1 (Kick): name)

DRY RUN: 3 would be reversed.
  (1 journal record(s) were never written; 5 not selected)

Reviewed offline from --state; no console was contacted. Re-run with --console to preview against the desk, and --confirm to reverse.
```

`--only` takes a comma-separated list of strip labels (`ch:21`, `aux:3`,
`bus:4`, `main:1`, `mtx:2`, `dca:7` — the same spelling `amend
--allow-strip` uses) or bare address prefixes (`/io/in/A/5`). An **amend**
journal needs it less often: it carries the scope the amend was held to,
and undo defaults to exactly that.

## Redo

Every confirmed undo writes its own journal — a new entry in
`journals/` when it reversed an entry there, and `<journal stem>.undo.json`
beside the journal otherwise (a journal outside any bundle's stack),
never over it — and that file is an ordinary
apply journal. It names itself on the way out (`Journal of this undo:
…`), and undoing it is the redo:

```bash
atoo undo --show touringband --console 192.0.2.16 --confirm
atoo undo touringband/journals/20260924T062011.930451Z-undo-S2203A1.json --console 192.0.2.16 --confirm   # redo
```

There is no `redo` command because there does not need to be one, and
there is no redo button either: the browser keeps one arming control and
one undo.

An undo's journal is kept but is **not a step forward**. It is the mirror
of the entry it reversed (its `prior_value` and `intended_value` are that
entry's, swapped), so on the stack it pops that entry rather than
becoming a new position — which is why a second undo steps back two. It
is kept because it is the only file that records the addresses the undo
**refused** to touch.

## What it counts, and what it exits

```
UNDONE: 41 reversed, 2 refused (changed since), 1 unreversible (no prior value).
```

| code | meaning |
|---|---|
| `0` | everything selected came back |
| `1` | the command could not run: an unreadable or dry-run journal, a journal that is no longer the top of the stack (pass `--out-of-order` if you mean it), no console address, the connection dropped mid-run |
| `2` | it ran and the desk is not fully back — something was refused, something had no prior value, or a reversal did not read back |

A reversal is a write like any other: it goes out on the same path,
is **read back and proved**, and a reversal that did not land is reported
as one.

While it runs, undo says what it is doing on stderr, the way
[`apply` does](applying.md#while-it-runs): `reading the values a
selector governs, before undoing` when the journal puts back a selector,
then `reading the desk for the undo preview`, or with `--confirm`
`putting back, reading each back`.
`--no-progress` turns it off.

## See also

- [Applying a plan](applying.md) — `apply`, flags and exit codes
- [The journal](journals.md) — what undo reads, and how far back it reaches
- [Patching a running show](patch.md) — `atoo patch`
- [Patching from a rebuilt plan](amend.md) — `atoo amend`
- [One plan, two desks](two-desks.md)
- [Command reference](cli-reference.md) — every flag, generated from the code
