# How a show gets built

Five stages between the two files you write by hand and a desk you can trust, plus a stage 0 that runs once per conventions file. Each one checks something the one before it could not, and only one of them writes to the console.

```
  input list                  input.csv       what is plugged in
+ conventions                 conventions.md  how you set a desk up
        |
        |  0. RESOLVE    (once per conventions file)   inside build, or atoo resolve
        |     conventions.resolved.md         your conventions + the domain knowledge, as rules
        |
        |  1. BUILD                           atoo build
        v
      plan.json                               every value, with its reason
        |
        |  2. CRITIC PASS      (advisory)     build --critic
        |  3. VERIFY           (gate)         atoo verify
        v
        |  4. APPLY                           atoo apply --confirm
        v
      the desk                                written, read back, journalled
        |
        |  5. AUDIT                           atoo audit
        v
      findings                                what the desk actually says
```

Stage 0 runs inside `build` whenever its file is missing or out of date, and costs nothing when it is not. Stage 3 runs inside `build` as well, so one `atoo build` gives you the plan and its verification. Stage 2 is opt-in (`--critic`). `verify` exists as its own command anyway, because a plan file can be edited after it is built — and because `apply` runs it again itself rather than trusting that it was ever run.

## 0. Resolve: your conventions, restated once as rules

*An experiment.* Many questions about your conventions have the same answer in every show: which high-pass the drums get, which DCA the bass joins, whether "gain on each channel" includes a USB track. So before the first build, one model call restates your conventions, together with Atoo's audio domain knowledge, as explicit rules, and writes them beside your file: `house.md` gives `house.resolved.md`. Every later build reads that file in place of the two. Your show's `instructions.md` is still read as written, on top, and still wins.

From the rules, code writes each category's settings (color, high-pass, DCA, gain and so on) on every channel the model left them off, and builds the strips your conventions ask for that are on no input list, such as "Setup TALKBACK on Aux 8". Code also checks that every quote in the file really is in your text, and that every line of your conventions is used or listed as having no effect. A quote that is not in your text is a WARNING; a line no rule cites is a note, and the generator is given that line as you wrote it.

The file is made again when your conventions, the domain knowledge or the prompt change, and `atoo resolve --conventions house.md` makes it again on purpose. `atoo build --no-resolve` builds without it. **Read it**: [The resolved conventions](conventions-reference.md#the-resolved-conventions) says how, and what to do when a rule in it is not what you meant.

## 1. Build — compile the two files into a plan

`atoo build` reads the input list and the conventions, and writes `plan.json`: every value it intends to set, each carrying the sentence of your conventions that asked for it. Nothing is sent to a console.

It needs to know which desk the plan is for (`--console-model wing-compact`; a rebuild of a show that has a plan takes it from that plan), and a model provider ([Setting up an AI provider](ai-provider.md)). This is the one stage that uses a language model. Everything after it is ordinary code and runs with no model at all.

The model writes a short reply, saying what it decided, and code expands it into the plan: it numbers the channels, copies each row's details off the input list, picks the next free socket where a row states none, and applies your colors. Each thing code chose is recorded in the plan as an INFO note (in the browser, under **Build details**), so it is never mistaken for what the model or your conventions did.

**Every input-list row becomes a channel, unless your own words say to leave it out.** The model may leave a row off only by quoting a line from your conventions, your instructions or that row's own notes (*"not patched for this event"*), and code checks the quote is really there, word for word. A row left out without one is built anyway, by code, and said at INFO (`reply.row-built`). A channel that is not built is a dead microphone at soundcheck; one built that nobody wanted is a strip you mute.

**Where your conventions are silent** about something the desk cannot be left without (a bus's mono or stereo, a send's pre or post, a stereo pairing), the build decides it and `verify` reports each decision as an `inferred.*` note. Where your conventions and instructions **contradict each other**, or declare something this show never uses, the build adds a note that quotes the lines (`conventions.conflict`, `conventions.unused`).

**One fix-up round.** When the plan fails `verify` with errors, or a strip's audio reaches no output, the build sends the model its reply and the exact messages once, and asks for a corrected reply. If that passes, it is the plan, and the build says what was fixed (`build.fixup`). If not, the plan is still written but apply will refuse it: the build shows both rounds' errors and exits 2 (`build.fixup-unresolved`). There is one round, never a loop.

With the critic on (below), it reads the first plan before this round. When it finds a line of your instructions or conventions the plan did not carry out, and quotes that line exactly, the line goes back in the same round, alongside verify's errors, or on its own. The corrected plan is kept only if `verify` finds it no worse: no more errors, and, with as many, no more strips that reach no output. Otherwise the first plan stands, and the build says what is still open (`build.fixup-rejected`). Each line sent back is a note quoting it (`build.critic-repair`): carried out, where code can see the sockets it names, or else to be confirmed in the plan. The critic's other findings were about the first plan, so once it is replaced each starts *On the first plan:*.

**It is the slow stage**: minutes on a hosted model. Each model call shows where it is while it runs (waiting, thinking or writing, and for how long), and a build can be stopped at any time with Ctrl-C or Build's **Stop**, writing nothing. See [A build seems stuck](troubleshooting-build.md#a-build-seems-stuck).

Each build, including one that failed or was stopped, leaves a log in the bundle's `builds/` folder: what each model call noted while it thought, and what it cost. The newest 5 are kept. `atoo lessons` reads them ([Learning from a batch of builds](lessons.md)).

### What a rebuild changed

A model drafts the plan, so building the same files twice is not promised to give the same plan. So a rebuild into a show bundle ends by saying what changed against the plan it replaced (`plan.previous.json`), strip by strip, in the desk's terms. A first build says nothing about changes.

Each change is graded by what the strip is made from:

- **INFO** -- you asked for it. An input-list row the strip is made from changed, a changed line of your conventions or instructions names it (its name, its source, its desk label such as `CH 14`, its category, or a bus, DCA or mute group it is on), or its preset file changed. A strip that only moved number is INFO when rows were added, removed or reordered.
- **WARNING** -- nobody asked for it. Nothing in the input list or the conventions about that strip changed, so the model rewrote something your edit was not about. The plan may still be right; check it. It is never an error.

A rebuild that changed something also offers **Apply the difference** in Build output. It opens Apply with Full build chosen and the preview run. A full build writes only the addresses where the desk differs from the plan, so the preview's "will change" is the difference.

Which lines are "about" a strip is read from their words, so a line that calls a strip by another name is not seen, and the section notes it at INFO. A changed line that names no strip at all ("monitor sends are pre-fader") could be about anything, so every change is then taken as asked for, and said at INFO. A heading, or a line you only re-wrapped or re-indented (the same words, in the same order), changes no rule, so it asks for nothing; counted as a line naming no strip, it would make every change look asked for and hide the one that was not. The section counts those lines at INFO.

**When a change is a WARNING**, nothing has stopped: the plan is written and verified as usual, and Apply will take it. Read the value before you do. If the new one is right, there is nothing to do. If it is not, say what you want in your conventions or the show's instructions and build again: the line you add asks for that strip, so the next comparison grades its change as INFO. A rebuild that changed nothing says *Changed since the last build: nothing*.

Here the Demo show (from a checkout's `starter/`) was built, then the `Guest Vox` row was un-skipped in `input.csv` and named in the Vox Wedge line of `instructions.md` (*"Lead Vox and Guest Vox send to it."*), and it was built again. The model's reply was a recorded one that also, without being asked, raised the Bass DI's gain. The end of the rebuild:

```text
$ atoo build --show starter/demo-show --conventions starter/conventions.md --console-model wing-compact --no-resolve --no-category-rules --presets starter/presets
...
Changed since the last build -- 3 strips against plan.previous.json: 1 added, 1 changed, 1 moved; 1 not asked for
  WARNING  CH 6 Bass DI: gain 20 -> 26 dB -- nothing in the input list or the conventions about it
           changed
  INFO     CH 13 Guest Vox: added
  INFO     CH 14 Playback: moved from CH 13
  INFO     graded by what each strip is made from: a change is asked for when an input-list row it
           is made from changed, or a conventions line naming it, its category, or a bus, DCA or
           mute group it is on -- read from the words, so a line that calls a strip something else
           is not seen
```

`Playback` moved because a row was added before it: matched by its input row, it shows as moved rather than as removed and added.

**Every changed value.** A strip with more than two changed values gets one line ending *"and 3 more values"*. The plan keeps the whole comparison at `meta.changes_since_previous`: each strip with its grade, its reason, and every value old and new. `--all-changes` on a build prints all of it instead of the short lines, with why each change is graded as it is. It is a `build` flag, so it shows the next rebuild in full, not the last one.

In the browser, Build step 04's Plan box has the same list as its **Changed since the last build** part, worst first. Each strip is a link to its row, and the part is open when a change was not asked for. In the tables, each changed strip carries **ADDED**, **CHANGED** or **MOVED** by its number, yellow and with a yellow edge when it was not asked for, gray when it was. Each change nobody asked for is also a WARNING in the **Findings** panel, under **To check** (`rebuild.unasked-change`), so the verdict reads **Ready to apply · 1 to check**. It does not block Apply.

Worked example: [The command line](quickstart.md).

## 2. Critic pass — a second read of the plan

`atoo build --critic` has a second model read the plan as a reviewer, looking for omissions first (a channel with no DCA, a monitor bus with nothing in it, a name that does not match the input list) and at the conventions themselves. Like the build's own notes, every finding must quote your lines, and one whose quote is not in your files is marked untrusted. It reads each strip's starting fader and mute as the desk will hold them: where the plan states none, unity and unmuted, which is what Apply writes. So it does not point at an unset mute when your conventions say "unmuted", and it still does when they say "muted".

**It is advisory, and it gates nothing.** It reads the first plan, before the fix-up round. One kind of finding goes back to the model: an omission that quotes a line of your instructions or conventions exactly, such as *Video Feed: Send the main mix to USB 18-19*. It joins the fix-up round (above), so the line is carried out in this build. A quote that is not word for word in your files, or an opinion about how a rule was carried out, is only printed. Its findings are kept in the plan, and no later stage reads them. Routing is not its job: code checks that in `verify`. It is off by default on the command line (Build's step 04 ticks it for you), and the plan records whether it ran. Which model it runs on is set in [Setting up Atoo](configuration.md).

## 3. Verify — the gate

`atoo verify` checks the plan against the console's own limits and, when you pass `--input`, against the input list it claims to cover: a socket that does not exist on this model, a stereo pair that cannot be formed, a DCA index out of range, an input from your list that never became a channel.

```
atoo verify --plan starter/demo-show/plan.json --input starter/demo-show/input.csv
```

```
0 error(s), 0 warning(s), 4 note(s)

  [info] plan: 12 channel(s) carry a preset's values, written at the processing stage and read back like every other write: ch 1 Kick In (83), ch 2 Snare (83), ch 3 H Tom (83), ch 4 Fl Tom (83), ch 5 OH (83), ch 6 Bass (83), ch 7 E Gtr (83), ch 8 E Gtr (83), ch 9 Keys (83), ch 10 Vocal (80), ch 11 Vocal (80), ch 12 Vocal (80)  (preset.expanded)
  [info] plan: 3 bus(ses) carry a bus preset's processing, written at the processing stage and read back like every other write: Drums: 'Mix Bus' (55), Vocals: 'Mix Bus' (55), Vox Verb: 'Vox Verb' (55)  (preset.bus-expanded)
  [info] plan: 1 FX insert(s) are loaded and switched on, each read back: Vox Verb: V-REV on FX5 (saved bypassed, switched on)  (fx.inserts)
  [info] channels[Music]: aux 1 'Music' is not on the input list; built because instructions.md says 'Walk-in music ("Music") on Aux 1, stereo, source LCL 3-4. Fader at -20dB', on LCL 3-4 as it states  (reconcile.from-instructions)

APPLICABLE: notes only -- choices made where the conventions were silent.
```

(`starter/demo-show/` is the Demo show, in an Atoo checkout. The test suite re-runs this transcript, so it stays what the command prints.)

The `[info]` lines are **notes, not problems**: what the plan carries, a choice made where the conventions were silent, or something built because `instructions.md` asked for it. Notes never block. The same thing said about many objects is printed once, naming them all (`ch 1-22 (22 channels): ...`).

**Routing is checked here, by code.** A channel whose audio reaches no output (`routing.channel-reaches-nothing`), or reaches no Main, directly or through a bus (`routing.channel-misses-main`), is a warning. A click, guide or talkback strip is meant to stay off Main and is not reported. Both are warnings, not errors: the desk works, and a strip kept off the PA can be deliberate.

**This is the stage that stops an apply.** `apply` runs the same checks itself before it contacts the desk, and on any **error** it prints the report and stops, exiting `2`:

```
Refusing to apply 'plan.json'. Fix the plan, or pass --skip-verify if you
have a reason to write it anyway.
```

Pass `--input` whenever you can. Without it the checks that need the input list are skipped, and `verify` reports that rather than returning a clean result nobody earned. Did every input on your list become a channel? That is the most important check there is.

## 4. Apply — write it, then prove it

`atoo apply --console <ip> --plan plan.json --confirm` writes every value, reads every one back, and journals the pair. Without `--confirm` it is a preview that writes nothing. Reading back is not politeness: a remote write that did not land looks exactly like one that did until somebody asks the desk again.

`atoo undo --show DIR` takes the newest write back off the desk, one step per run ([Undoing a write](undo.md)).

Full detail: [Applying a plan](applying.md).

## 5. Audit — ask the desk

`atoo audit` reads the live console and checks it against the structural rules: a bus in use with nothing feeding it, 48V on a socket nobody patched, a DCA pulled low over active members. Give it `--plan` as well and it also compares the desk with what the plan asked for.

It works offline too, against a saved state (`atoo init` puts a demo one in your Atoo folder):

```
atoo audit --state ~/Documents/Atoo/audit-demo/audit_demo_state.json --plan ~/Documents/Atoo/audit-demo/audit_demo_plan.json
```

```
Audit findings: 5 warning, 3 info.

[WARNING] C001 Phantom Power On Unpatched Socket
  48V is on for LCL 9 but nothing is patched to it -- no channel, no aux and no user patch.

[WARNING] CH002 DCA Fader Low With Active Members
  DCA 1 "Drums" is at the floor (-20dB or lower) but controls 2 active member(s): CH 1 "Kick", CH 2 "Snare".
  ...
```

**Audit findings do not gate anything, and cannot.** By the time there is a desk to read, the apply has happened. That is why the gate is at stage 3, on the plan, where refusing still costs nothing.

`atoo watch` is this same stage on a loop, reporting only what changed. See [Checking a desk](audit.md) and [Watching from the command line](watch.md).

## Severity, across all five stages

Every stage produces the same kind of finding, with the same three severities:

| | what it means | consequence |
|---|---|---|
| `ERROR` | this cannot work | `verify` and `apply` refuse (exit 2); `audit`/`watch` exit 1 |
| `WARNING` | this probably is not what you meant | reported, never blocking |
| `INFO` | a choice was made for you, and here it is | reported, never blocking |

**`INFO` is load-bearing.** Where your conventions and the input list imply an answer but do not state one — whether a monitor bus is mono or stereo, how a long name is abbreviated — Atoo makes the reasonable choice and tells you at `INFO` what it chose and what it read that from. It does not refuse, and it does not leave the field empty, because the desk has to end up in working order. If the choice does not suit the show, the conventions did not say so clearly enough, and that is a one-line fix for next time.

There is no `CRITICAL`: `ERROR` already refuses everything.

## Where each stage's rules are written down

| stage | the rules it applies | where |
|---|---|---|
| 1 Build | the conventions grammar | [Writing conventions](conventions.md) |
| 3 Verify | the plan checks against the console model | `atoo/verify_plan.py` |
| 5 Audit / watch | the structural rules (`C001`, `R005`, …), the plan-diff checks (`CV001`, …), and your own watch conditions | each finding names its rule; [Reading findings](reading-findings.md#codes) |

Both catalogs grow as rules are added, so this page does not count them; the linked source is the list.

## See also

- [The command line](quickstart.md) — the whole path, once, with output
- [Applying a plan](applying.md) — stages 3 and 4 in detail
- [Learning from a batch of builds](lessons.md) — `atoo lessons`
- [Checking a desk](audit.md) and [Watching from the command line](watch.md) — stage 5 in detail
- [Command reference](cli-reference.md#exit-codes) — every exit code, which are not uniform across commands
