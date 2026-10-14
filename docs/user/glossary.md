# Words Atoo uses

One name for each thing, as the browser and the command line say it.
A label in **bold** is what you see on screen; `code` is what you type.

## Your files

| Word | What it is | Where you meet it |
|---|---|---|
| Show bundle | one show's folder: its input list, instructions, plan, watch conditions and journals | **Show bundle** in the bar; `--show` ([Show bundles](show-bundles.md)) |
| Conventions | how you set up a desk, in your own words, for every show | **01 Conventions**; `--conventions` ([Writing conventions](conventions.md)) |
| Input list | what is plugged in, and where | **02 Input list**; `input.csv` ([Writing an input list](input-lists.md)) |
| Instructions | what is different about tonight | **03 Instructions**; `instructions.md` |
| Plan | every value the desk will be given, built from the three above | **04 Plan**; `plan.json` |
| Socket, patch | a socket is the connector on the desk (`LCL 3`); a channel's patch is the socket it is fed from | the input list's `patch` column |
| Preset | a `.chn` or `.bus` file of processing from your own library | `--presets` ([Using channel presets](presets.md)) |
| Watch condition | an alert of your own: the Kick stays on LCL 5 | **Watch conditions**; `watch.json` ([Watch conditions](watch-conditions.md)) |

## Building and checking

| Word | What it is | Where you meet it |
|---|---|---|
| Build | a model drafts the plan, and code checks every value | **Build plan**, **Rebuild plan**; `atoo build` ([Build a show](build-a-show.md)) |
| Stale | the plan is older than a file it was built from | the **Stale** badge on step 04 |
| Critic | a second model's opinion of the plan; it never blocks | **Run the critic pass**, **Advice**; `--critic` |
| Finding | one line a check reports, at ERROR, WARNING or INFO | **Findings**; `verify` ([Reading findings](reading-findings.md)) |
| Verdict | whether the plan can be written | **Ready to apply** or **Blocked** (**No plan yet** before a build); `VERIFIED:`, `APPLICABLE:` or `BLOCKED:` |
| To check | the errors and warnings, read before writing | **To check** under **Findings** |
| Choices | what the build decided where your files were silent, said at INFO | **Choices** under **Findings** |
| Build details | how the model's reply was read, at INFO | **Build details** under **Findings** |

## Writing to the desk

| Word | What it is | Where you meet it |
|---|---|---|
| Console | the one desk address the page uses | **Console** and **Change…** in the bar; `--console` |
| Ping | one round trip to the desk, for its name and model; changes nothing | **Ping**; `atoo ping` |
| Pre-flight verify | the plan checked again against this desk's model, just before a write | **Pre-flight verify** in Apply step 1 |
| Full build | the whole plan written to a desk you are setting up | **Full build**, **Write to console**; `atoo apply` ([Apply a plan to the desk](apply-to-desk.md)) |
| Patch | a change to a show already on the desk, nothing else moved | **Patch**, **Write changes to console**; `atoo patch` ([Patch a show](patch-a-show.md)) |
| Preview | reads the desk and shows what a write would change; writes nothing | **Preview**, **Preview undo**; `apply`, `patch` or `undo` without `--confirm` |
| Arm | the one control that lets a write happen; it clears after each write | **Arm** in Apply step 3; `--confirm` |
| Journal | the record of one write, with each value it replaced | **The journal**; the show's `journals/` folder ([The journal](journals.md)) |
| History | every write from this show, newest first | **History**, Apply step 4 |
| Undo | puts back what the newest write still on the desk changed | **Preview undo**, **Undo newest write**; `atoo undo` ([Undo](undo.md)) |
| Demo | a packaged, read-only show on a simulated WING Compact | **Try the Demo show** ([Try the Demo show](demo.md)); `atoo init --demo` copies it into your folder as an editable `demo-show/` |

## See also

- [Reading findings](reading-findings.md): the verdicts and codes in full
- [Command reference](cli-reference.md): every command and flag
