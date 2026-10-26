# Command-line quickstart

One show, end to end: two files in, a plan out, the plan on the desk, and
a readback proving every value landed.

This uses a 19-channel touring band on a WING Compact, which ships with
Atoo under `docs/user/demo/`. Copy it into a folder of your own
first, from the top of an Atoo checkout, so nothing you build
overwrites the shipped copy:

```bash
mkdir ~/quickstart
cp -r docs/user/demo/touringband docs/user/demo/conventions.md ~/quickstart/
cd ~/quickstart
```

Run everything below from that folder.

**Installed with uv or pipx, and no checkout?** `docs/user/demo/` is not in
the install. [`atoo init
--demo`](change-the-demo.md#1-make-a-copy-of-the-demo-show) writes the
smaller Demo show to `~/Documents/Atoo/demo-show/`. Run the steps
from `~/Documents/Atoo` with `demo-show` wherever this page says
`touringband`, and step 2 as `atoo build --show demo-show` (the copy's
own plan names its model, so there is no `--console-model` to pass). The outputs below are the touring band's,
not the Demo's.

**Only step 2 calls a model, and only steps 4 to 6 want a desk.** The
copy already holds the plan step 2 would build, so you can follow
everything up to the console with no model set up. Skip step 2 until one
is: a build with `--show` moves `plan.json` aside to
`plan.previous.json` as it starts, so one that cannot reach a model
leaves the copy with no plan.

If Atoo is not installed yet, start at
[Installing Atoo](install.md).

---

## 0. Set up once

Two things carry over from show to show, so you set them once:

- **Which model writes the plan**, in your shell environment. Claude is
  the default, and with no API key `build` stops and tells you. See
  [Setting up an AI provider](ai-provider.md); you can
  leave it until step 2.
- **Your house conventions, your presets and your desk**, in
  `~/.atoo.config`. Once one is set, the matching `--conventions`,
  `--presets` or `--console` flag becomes optional; a flag you pass
  still wins. See [The config file](configuration.md#the-config-file).

This walkthrough passes every flag explicitly, so it works with no
config file at all.

---

## 1. The two files you write

**An input list** — one row per physical input, in
`touringband/input.csv`:

```csv
socket,name,category,type,model,phantom,notes
AES50-A 1,Kick,drums,Mic,Beta91A,TRUE,
AES50-A 2,Snare,drums,Mic,,FALSE,
AES50-A 3,Tom1,drums,Mic,,FALSE,
AES50-A 4,HH,drums,Mic,,FALSE,
```

It says what is plugged in and where, not what to do about it. The
first column, headed `socket` here, reads the same headed `patch`. See
[Writing an input list](input-lists.md).

**A conventions file** — how *you* set up a board, in plain English.
`conventions.md` is house style, not one show's, so it lives outside the
show's directory:

```markdown
## Processing
- I always want a highpass at 40 Hz on anything in the drums category.
- Same idea for band instruments, but higher -- 80 Hz is fine.
- Guitars channels get a high-pass at 80Hz.
- Horns channels get a high-pass at 100Hz.
- Vocals need more low end removed, so put their high-pass up at 120Hz.
- Speech channels get a high-pass at 120Hz, like vocals.
- Tracks are not band instruments: no high-pass, no Band mute group, and no INST Reverb send.
- Send all Channels to the Main L/R bus unless they are included in one of the mix busses below.
- Unless overridden by the show instructions, set the input (head-amp) gain on each channel to 20dB, and the Trim to 0dB.
- Leave all faders all the way down.
```

Written once, re-run against every show; make it your
`[conventions] default` (step 0) and every build reads it. See
[Writing conventions](conventions.md).

---

## 2. Build the plan

```bash
atoo build --console-model wing-compact \
                --input touringband/input.csv \
                --conventions conventions.md \
                --out touringband/plan.json
```

**`--console-model` is required and has no default.** The three WING
models do not have the same sockets — a Compact has 24 local inputs and
no aux jacks, a full-size WING has 8 and does. You pass it once: `build`
records it in the plan, and `verify` and `apply` read it back out. So does
a rebuild: `atoo build --show DIR` on a show that has been built before
takes the model from that show's `plan.json`, notes it at `INFO`, and
accepts `--console-model` to build for a different WING. A show with no
plan yet is refused, and the refusal names the flag.

A build calls a model and takes minutes. It streams its progress, so
silence means a stalled connection, and everything it says is also kept
in the plan under `meta`. The shipped plan's record (abridged):

```json
"meta": {
  "generated_at": "2026-09-30T23:49:59+00:00",
  "console_model": "wing-compact",
  "conventions_stack": [ ... ],
  "verify_at_generation": {"skipped": false, "ok": true,
                           "error_count": 0, "warning_count": 0,
                           "note_count": 15, "summary": "OK"},
  "critic_findings": [ ... ]
}
```

`conventions_stack` names every conventions and instructions file the
build read, in layering order; `critic_findings` keeps a `--critic`
pass's findings. A build on Claude also records the `model` and `effort`
of each call (`medium` by default), so two builds can be compared.

**The first build on a conventions file makes one extra model call**,
writing `conventions.resolved.md` beside `conventions.md`; later builds
reuse it, and say so on an `INFO resolved conventions:` line. The copy's
`meta` records it under `resolved_conventions`. See
[The resolved conventions](conventions-reference.md#the-resolved-conventions).

**A model writes the plan; deterministic code checks it.** Nothing the
model says is enforced — even `--critic`'s second-pass findings are only
printed. Only the verification in step 3 gates anything. The plan is a
file you can read and edit, and the last point at which a mistake is
cheap.

---

## 3. Read the verdict

```bash
atoo verify --show touringband
```

`--show` names a [show bundle](show-bundles.md): one directory holding
the show's files under fixed names, so the plan and input list need no
flags.

```
0 error(s), 0 warning(s), 15 note(s)

  [info] plan: 'Magenta' is the desk's Pink (11): EG 1. The desk has no colour called 'Magenta'; Atoo used that name for 11 until the desk was asked, so it still resolves. Say 'Pink' to use the desk's own word  (strip.colour-alias)
  [info] plan.mute_groups[Speech]: mute group 'Speech' is declared but no channel or bus joins it -- it does nothing  (group.empty)
  [info] busses[MON5, MON6, Drums, Drums Comp, Vocals, Keys, Horns, VOX Reverb, VOX Delay, Snare Verb, INST Reverb] (11 busses): width set to stereo -- the conventions did not state it; decided by the generator: Instructions add MON5 and MON6 as stereo IEM mixes, patched to AES50-A socket pairs / Mix busses conventionally stereo / FX busses conventionally stereo  (inferred.bus-width)
  [info] outputs[Matrix 1]: Matrix index set to 1 -- the plan left it out; decided by Atoo's fallback rule: its name, 'Matrix 1', states slot 1  (inferred.output-index)
  [info] channels[Keys L]: linked as a stereo pair -- no convention states it; decided by the generator: Input list designates Keys L/R as left/right pair on consecutive AES50-A sockets 15+16; stereo pairing conventional for DI sources  (inferred.channel-stereo)

APPLICABLE: notes only -- choices made where the conventions were silent.
```

Exit `0`. Fifteen notes on five lines: a note that says the same thing
about several strips is printed once, naming them all. The notes depend
on the show, and change when it is rebuilt.

- **The last line is the verdict**, one of four, and it is what `apply`
  obeys: only `BLOCKED: do not apply.` stops it. See
  [The verdict](reading-findings.md#the-verdict).
- **The code in parentheses is stable** across rewordings: quote it in a
  bug report. See [Codes](reading-findings.md#codes).
- The warning you are most likely to meet first is
  `strip.colour-not-writable`: a colour outside the desk's eighteen,
  which leaves that strip's colour as it was. See
  [Colours the desk does not have](conventions-reference.md#colours-the-desk-does-not-have).

**Exit codes:** `0` clean, `1` it could not run, `2` it ran and found
problems — except that `audit` and `watch` report findings with `1`. The
whole rule is in the [command reference](cli-reference.md#exit-codes).

---

## 4. Check you can reach the desk

```bash
atoo ping --console 192.0.2.16
```

One round trip that reads and writes nothing, so it is safe during a
show. Two lines come back: the console's identity string, and the model
read out of it, which the next step checks your plan against.

If it does not answer, the usual cause is OSC remote control switched
off on the desk; see
[Troubleshooting](troubleshooting.md#atoo-cannot-reach-the-console).
To stop typing the address, see
[The console](configuration.md#the-console).

---

## 5. Preview, then apply

```bash
atoo apply --show touringband --console 192.0.2.16
```

**This writes nothing.** It verifies the plan, checks the desk's model,
reads every address the plan would touch, shows what would change, and
ends:

```
Nothing was written -- this was a preview. Re-run with --confirm to apply.
```

Verification runs *before* the console is contacted, so a blocked plan
never reaches hardware. Then:

```bash
atoo apply --show touringband --console 192.0.2.16 --confirm
```

```
APPLICABLE: warnings only.
Console: WING,192.0.2.16,<desk name>,wing-compact,<serial>,3.1-0-g9f314617:release
APPLIED: 631 address(es) evaluated, 337 written, 2 mismatch(es).
  MISMATCH /bus/10/name: expected 'VOX Delay', read back ''
  MISMATCH /ch/10/tags: expected '#D6,#M1', read back ''
  note: 31 stale reply/replies from the console were discarded (duplicated or unsolicited datagrams). Readbacks above are matched by address, so this did not affect them.
Journal: <path>/A1-apply-journal.json

2 parameter(s) did NOT land:
  - /bus/10/name: wanted 'VOX Delay', console reports ''
  - /ch/10/tags: wanted '#D6,#M1', console reports ''
```

*A real run against a WING Compact, verbatim except that the desk's
name, serial number and journal folder are replaced and the verification
lines are left out. That run was given `--journal`; a plain `--show
touringband` writes a timestamped entry in `touringband/journals/`.*

**Every address is read back afterwards**, because a remote write can
fail silently. Anything that did not land is named by address and the
command exits `2`, which is the whole point of the tool.

Those two mismatches were themselves false: the desk answered late, and
`apply` now settles a late answer by its address — see
[Why every value is read back](journals.md#why-every-value-is-read-back).
[Applying a plan](applying.md) covers the flags and what each result
word means.

---

## 6. Prove it later

Two things outlive the apply.

**The journal.** Every write with the value it replaced, filed in
`touringband/journals/`, so `atoo undo --show touringband` walks
the show back one step at a time ([the journal stack](journals.md#the-stack)).

**A show file the console wrote itself.** Save a snapshot on the desk,
copy it off (there is no remote save-and-download), and compare:

```bash
atoo compare --show touringband \
                  --snapshot touringband/console-after-apply.snap
```

```
110 difference(s), 0 not compared

  [error] ch 1 (Kick): plan sends to 'MON5' at -144dB; the desk saved 0dB  (snapshot.send-level)
  ...
  [error] ch 1 (Kick): plan sends this to 'Drums' (bus 7); the desk has that send off  (snapshot.send-off)
  ...
  [error] ch 4 (Tom1): plan patches to A 3; the desk is on A 4  (snapshot.patch)
  ...
  [error] ch 9 (Keys L): plan names this 'Keys L'; the desk has 'Keys'  (snapshot.name)
  ...

Only fields the plan actually states are compared -- a null fader is not an assertion about where the fader should be.
```

Exit `2`. That `.snap` is an old capture from a desk running an
earlier build of this show, so it disagrees with today's plan about
sends, mutes, high-passes and one name; three patches one socket off go
back to the capture itself. It is kept because a comparison that finds
something teaches more than one that finds nothing.

---

## Where next

| I want to... | Page |
|---|---|
| write the input list for my own show | [Writing an input list](input-lists.md) |
| write down how I set up a desk | [Writing conventions](conventions.md) |
| set my house files, my desk or my model once | [Set up Atoo](configuration.md), [Setting up an AI provider](ai-provider.md) |
| understand what `apply` guarantees | [Applying a plan](applying.md) |
| keep one show's files together | [Show bundles](show-bundles.md) |
| check a desk that is already set up | [Checking a desk](audit.md) |
| look up a flag | [Command reference](cli-reference.md) |
| work out why something failed | [Troubleshooting](troubleshooting.md) |
