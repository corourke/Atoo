# One plan, two desks

*From the command line.*

One plan can go to more than one console — a primary and a backup, say, both with similar I/O. Build it once, apply it to the first desk, point at the second, and apply it again:

```bash
atoo apply --show touringband --console 198.51.100.9 --confirm
atoo apply --show touringband --console 198.51.100.7 --confirm
```

In the browser the second step is the bundle bar's **Change…**: the one console address on the page, used by Ping, Apply, Patch, Undo and Watch alike. It cannot change while a write is running, and changing it unticks **Arm** — a tick given for the primary is not consent to write to the backup.

## Each desk keeps its own undo history

Every entry on the journal stack records **the desk it wrote to**: the name, model, serial number and firmware the desk states on `/?`, and the address it was reached at — in the entry, in `index.json`, and (the serial) in the entry's file name.

Undo is held strictly to the desk a journal was written on. Apply and amend are more permissive, so that a second desk, or the same desk on a new IP address (the home network, then the gig's), still works. So:

- **The serial is the desk.** The same serial at a new address is the same desk; a different serial is a different desk, even at the same address. A desk that states no serial is known by its address.
- **Undo is strict.** It pops, and accepts, only entries written to the desk on the line. There is no override.
- **Apply and amend are permissive.** Apply writes to any desk, and amend finds the desk's own plan by its serial, wherever it is now ([below](#amending-both-desks)).

So "the newest write" means **the newest write on the desk this command reaches**. `undo --show` asks the desk who it is first, pops that desk's newest, and leaves the other desk's history where it is. Run against two fake desks in the test harness, after applying to FOH-A and then FOH-B:

```bash
atoo undo --show touringband --console 198.51.100.9 --confirm
```

```
Console: WING,198.51.100.9,FOH-A,wing-compact,S2203A1,3.1-0-g9f314617:release
Reversing the newest entry in touringband/journals on this desk:
  2026-09-29T00:18:25.753176+00:00  apply  APPLIED: 1082 address(es) evaluated, 759 written, 0 mismatch(es).  [on FOH-A (wing-compact) serial S2203A1, at 198.51.100.9:2223]
  INFO 1 newer write(s) on this stack were recorded on a different desk, and are left alone:
    2026-09-29T00:18:25.822738+00:00  apply  APPLIED: 1082 address(es) evaluated, 759 written, 0 mismatch(es).  [on FOH-B (wing-compact) serial S2207B4, at 198.51.100.7:2223]
UNDONE: 759 reversed.
  (323 journal record(s) were never written)
Journal of this undo: touringband/journals/20260929T001825.912121Z-undo-S2203A1.json
  (undoing THAT file is the redo)
```

Without this, the top of the stack would have been FOH-B's apply, and undo's per-address guard would have passed on every address — FOH-A holds exactly the values that journal says were written — so FOH-A would have been reversed.

**A journal written to the other desk is refused**, naming both. Name FOH-B's apply entry while FOH-A is on the line (fake desks in the test harness):

```bash
atoo undo touringband/journals/20260928T211010.269845Z-apply-S2207B4.json --console 198.51.100.9
```

```
Console: WING,198.51.100.9,FOH-A,wing-compact,S2203A1,3.1-0-g9f314617:release
touringband/journals/20260928T211010.269845Z-apply-S2207B4.json was written to FOH-B (wing-compact) serial S2207B4, at 198.51.100.7:2223, but the console on the line is FOH-A (wing-compact) serial S2203A1, at 198.51.100.9:2223.
Undo only reverses a journal on the desk it was written to (matched by the serial the desk states; by its address only when it states none). Its guard is per address, and a plan applied to both desks holds the same value at every address on both -- so every address would pass it and THIS desk would be reversed. Connect to the desk it was written to: `atoo undo --show DIR` reverses the newest write on whichever desk it reaches.
```

Exit `1`, nothing written. There is no flag that gets past it, because there is no good reason to reverse one desk's journal onto another. The same holds for a journal copied out of the bundle: it carries the desk it was written to, and is held to it. The backup brought up on the primary's address is refused too, by its serial. The staleness check follows the same rule: a named journal is refused as *not the newest* only when a later write **on this desk** still stands on it (`--out-of-order` is still the way past that, and only that).

**A desk that has moved networks is the same desk.** FOH-A applied at home on 198.51.100.9, then brought up at the gig on 203.0.113.40:

```bash
atoo undo --show touringband --console 203.0.113.40
```

```
Console: WING,203.0.113.40,FOH-A,wing-compact,S2203A1,3.1-0-g9f314617:release
Reversing the newest entry in touringband/journals on this desk:
  2026-09-29T00:18:32.185944+00:00  apply  APPLIED: 1082 address(es) evaluated, 759 written, 0 mismatch(es).  [on FOH-A (wing-compact) serial S2203A1, at 198.51.100.9:2223]
  INFO 1 newer write(s) on this stack were recorded on a different desk, and are left alone:
    2026-09-29T00:18:32.246678+00:00  apply  APPLIED: 1082 address(es) evaluated, 759 written, 0 mismatch(es).  [on FOH-B (wing-compact) serial S2207B4, at 198.51.100.7:2223]
  INFO this journal was written to serial S2203A1 at 198.51.100.9; the desk on the line states the same serial at 203.0.113.40. The serial is the desk, so it is the same one -- its address has changed since.
Undo of touringband/journals/20260929T001832.164202Z-apply-S2203A1.json
  RESTORE   /mtx/1/fdr: 0.0 -> -144.0   (output Matrix 1 (matrix 1): starting fader -> unity (0dB))
  RESTORE   /main/1/fdr: 0.0 -> -144.0   (output Main 1 (main 1): starting fader -> unity (0dB))
  ...
```

**Entries recorded before desks were recorded** name no desk. They are taken to be the connected desk's — the single-desk assumption was true when they were written, there is nothing recorded to hold them to, and refusing them would strand the only undo those runs have — and undo notes this at INFO. Its per-address guard still applies. An offline `--state` preview contacts no desk, so it previews the newest entry on the whole stack and says a confirmed run may pick a different one.

The Apply screen's **History** step (the journal stack) has a **Desk** column. A row written to another desk is drawn dimmed and tagged **Other desk**, and the newest row on the desk in the bundle bar is the one with **Preview undo** — the write **Undo newest write** reverses. Rows are matched to that desk by address until you **Ping** it; the ping reads its serial. (The Undo button itself always asks the desk, so it never depends on that.)

## A plan built for a different model

The two desks need not be the same model: a WING Compact at front of house and a WING Rack as the backup, say, with similar I/O, and the plan built once, for the Compact.

`apply` compares the model the desk states on `/?` with the plan's `meta.console_model` before anything is written, and what it does about a difference depends on whether the plan **can be patched** on this desk. That is the line between a judgment call and a physical impossibility: a different model is not in itself a reason to stop, but a patch to a jack that is not there is.

**Every socket the plan uses exists on this desk: it is applied.** The Compact and the Rack have the same local and aux I/O — 24 LCL in, 8 out, no AUX — so every socket a Compact plan can name is on a Rack. The run notes this and carries on:

```bash
atoo apply --show touringband --console 198.51.100.6
```

```
Console: WING,198.51.100.6,MON-RACK,wing-rack,S2301R7,3.1-0-g9f314617:release

INFO: This plan is for a WING Compact, but 198.51.100.6 is a WING Rack (19", 4U). Every socket the plan patches exists on this desk, so it is applied as it stands, with the pre-flight verify re-run against wing-rack -- the desk being written to.
DRY RUN: 1089 address(es) evaluated, 493 would change, nothing written.
  - INFO reset to initialized (WING Rack (19", 4U) capture) before the plan's writes: nothing would change; 19,905 already initialized; left alone: 1,089 the plan sets itself, 84 on the skip-list (monitor/solo listening), 26 on the skip-list (meter/RTA display), 12 on the skip-list (expansion cards), 4 a mono bus's width (the desk holds it at 0), 2 not settable (no address the desk takes); reading the desk took 0.5s (2,100 requests; the plan's own settings: 997 from the node dumps, 92 read one by one); writing: no measured request rate for the WING Rack (19", 4U)
  - INFO 19 strip(s) set to their main input (not their alternate) -- a show apply means stage inputs live
  - INFO 3 direct Main route(s) and 1 Matrix feed(s) set to unity (0 dB), post-fader -- apply's documented default; the conventions have no phrasing for a route's own level or tap
  - INFO output LCL 1-6: no bus or output in this plan is patched there, so each is disconnected rather than left on what the desk came with or an earlier show put there
  ...

Nothing was written -- this was a preview. Re-run with --confirm to apply.
```

The verify that runs before the console is contacted checks the plan for the model it was built for; once the desk has said what it is, the verify **runs again against the desk's model**, and still refuses on anything that is really wrong for that desk. "Every socket" means every place a plan names one: each channel's input patch, a USR user patch's source, and every physical output a bus, Main or Matrix routes to. The expansion bays are the same two on every model, so they are not part of this comparison — what is *in* them is checked separately, below.

**A socket the plan uses does not exist on this desk: it is refused.** A full-size WING has 8 local inputs, not 24. A Compact plan with the kick on LCL 20, pointed at one:

```bash
atoo apply --show touringband --console 198.51.100.10 --confirm
```

```
Console: WING,198.51.100.10,FOH-FULL,wing-fullsize,SERIAL00000002,3.1-0-g9f314617:release

ERROR: This plan is for a WING Compact, but 198.51.100.10 is a WING (full-size console), and 1 socket(s) the plan patches do not exist on the WING (full-size console):
  - LCL 20 (input) -- channel 'Kick'; LCL inputs are 1..8 on a WING (full-size console)
Refusing to apply: LCL 20 does not exist on the WING (full-size console) at 198.51.100.10. Rebuild for this desk (--console-model wing-full), or repatch to sockets it has.
```

Exit `2`, nothing written. Every missing socket is listed, inputs and outputs both. `--skip-verify` does not get past it: that flag is about the plan's findings, and this is about the hardware.

**A desk whose model Atoo has never seen: it is applied, with a warning.** A desk names its model on `/?` in its own spelling — a full-size WING says `wing-fullsize` — and only spellings read off a real desk are recognized. Nobody has captured a WING Rack's yet. If yours says something Atoo does not know:

```
Console: WING,198.51.100.8,MON-RACK,wing-racksize,S2301R7,3.1-0-g9f314617:release

WARNING: 198.51.100.8 calls itself 'wing-racksize', a model name Atoo has never measured on a real desk, so it cannot tell which WING this is. Sockets were checked against the plan's own model only, the WING Compact; a confirmed apply still reads every write back from the desk and proves it landed. The desk's own token is recorded in the journal (desk.model_token) -- once the model is known it is one line in console_facts.IDENTITY_MODEL_ALIASES.
```

Please send that token in — `atoo ping` shows it too, and the journal keeps it under `desk.model_token` — and it becomes one line in `console_facts.IDENTITY_MODEL_ALIASES`.

**`--console-model`** is the explicit way to say which model the plan is to be checked for. `--console-model wing-rack` against a Rack verifies the plan against the Rack before the desk is even contacted, and the desk then agrees with it, so there is nothing more to say.

**On the Apply screen** all of this is the same command, so it behaves the same: a Compact plan applies to a Rack from the browser, and the INFO — or the WARNING — lands in the Findings panel beside the journal. A refusal is in the run log, word for word.

**`amend` asks the same questions** of the sockets it writes, in its preview as well as before a write — see [The pre-flight](amend.md#the-pre-flight-the-same-checks-as-apply).

## Amending both desks

`plan.json` is the last build, and nothing but a build writes it — so it says nothing about which changes are on which desk. `patch --show` and `amend --show` compare against **the plan the connected desk's own newest write left on it**: every apply, change and amend entry keeps a copy (`desk_plan` — the applied plan for an apply, the effective plan for a change or an amend), found by the desk's serial, so it is found after the desk has changed address too. Amend the primary, then the backup from the same rebuild, and the backup gets the channels (fake desks in the test harness; the occupancy lines are shortened):

```bash
atoo amend --show touringband --amended-plan touringband/rebuilt.plan.json --console 198.51.100.9 --confirm
atoo amend --show touringband --amended-plan touringband/rebuilt.plan.json --console 198.51.100.7 --confirm
```

```
Console: WING,198.51.100.7,FOH-B,wing-compact,S2207B4,3.1-0-g9f314617:release
  INFO applied plan: the one this desk's newest write left on it -- journals/20260928T211010.269845Z-apply-S2207B4.json (apply); plan.json says the same.
48 strip(s) read over 212 address(es): 19 ours, 1 theirs, 20 free, 8 unknown
  ...

3 added, 19 unchanged
  ADDED            channel 'Trumpet' -> ch:21 (the rebuild asked for ch:20): new channel, placed on a free strip
  ADDED            channel 'Trombone' -> ch:22 (the rebuild asked for ch:21): new channel, placed on a free strip
  ADDED            channel 'T.Sax' -> ch:23 (the rebuild asked for ch:22): new channel, placed on a free strip
  ...
APPLIED: 66 address(es) evaluated, 39 written, 0 mismatch(es).
plan.json is unchanged -- only a build writes it. What is on this desk now is recorded in its journal entry, which the next patch or amend of this desk reads; a full `atoo apply --show touringband` would replace it, and warns before it does.
Untouched-strip proof: 867 unrelated address(es) read before and after, 0 changed.
Journal: touringband/journals/20260928T211010.406626Z-amend-S2207B4.json (scope: ch:21, ch:22, ch:23)
```

Before per-desk plans the second run said *Nothing to add and nothing to return to free* and the backup never got the horns.

Because the plan is kept per entry, **undo keeps it in step**: undoing the backup's amend pops it, and the backup's applied plan is the one beneath it again — its apply's — while the primary's is still its amend's. `plan.json` is not touched by either (see [Undoing a change or an amend](undo.md#undoing-a-change-or-an-amend-leaves-planjson-alone)).

**A desk this bundle has not written to yet** — a new spare, or a desk the show was put on by hand — is amended against `plan.json`, and amend prints:

```
Console: WING,198.51.100.11,SPARE,wing-compact,S2210C9,3.1-0-g9f314617:release
  INFO no write to this desk (SPARE (wing-compact) serial S2210C9, at 198.51.100.11:2223) is standing in journals/, so the applied plan is plan.json -- the bundle's last build. If this desk was set up from a different plan, name it with --plan FILE.
```

The same fallback, said the same way, happens when the desk's newest entry predates per-desk plans, and when `--state` means no desk was contacted. `--plan FILE` always reads the file you named.

**And a warning when the plan does not look like this desk.** If the plan amend is comparing against claims strips as running that read empty on the desk — no name, nothing on the socket, factory patch — it warns. Here the spare above has never had the show at all:

```
WARNING: the applied plan claims 19 strip(s) as this show's that read EMPTY on this desk -- no name, nothing on the socket, factory patch: ch:1, ch:2, ch:3, ch:4, ch:5, ch:6, ch:7, ch:8 and 11 more. The plan may describe a different desk. They are still treated as ours, so nothing is placed on them; check that this is the desk the plan was applied to, or that it has not been reloaded since. A desk that never had the show is a full apply (`atoo apply --show DIR`), not an amend.
```

It is a warning, not a refusal: the strips stay *ours*, so nothing is placed on them, and a strip cleared by hand is a legitimate reason for one. In the browser, the INFO lines and this warning are in the Patch screen's review with the rest.

## See also

- [Applying a plan](applying.md) — `apply`, flags and exit codes; [the journal](journals.md)
- [Undoing a write](undo.md) — `atoo undo`
- [Patching a running show](patch.md) — `atoo patch`
- [Patching from a rebuilt plan](amend.md) — `atoo amend`
- [Command reference](cli-reference.md) — every flag, generated from the code
