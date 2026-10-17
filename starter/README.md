# Your Atoo folder

`atoo init` made this folder and put a starter set in it. Everything
here is yours to edit, rename or delete: running `atoo init` again
never writes over a file you have changed.

| What | What it is |
|---|---|
| `conventions.md` | Your **house conventions**: how you set up a desk, the same for every show. Plain English under fixed headings. `~/.atoo.config` names it as your default, so every build reads it. It starts as a working band/club house style that states the usual choices (stereo pairs, monitor widths, colours, presets by source), so a first build has little to guess. Start by making it describe your own house style. It names channel presets by source ("Kick In", "Vocal"...), the starter presets in `presets/`: when you replace a preset with your own, use its name here, or a build says it is not there and builds the strip without it. |
| `presets/` | Your **preset library**: WING channel presets (`.chn`). Name one in an input list's `preset` column, or in your conventions, and a build puts its processing on that channel. `~/.atoo.config` names this folder as your preset library. It starts with the starter set: twenty channel presets, one per common source, that the starter conventions name, plus three bus presets (`.bus`): "Mix Bus", a compressor for every mix bus, and two that put a reverb on the FX bus the conventions give them to. Export your own from the desk into it, under the names your conventions use; `atoo presets` lists what each is called. |
| `audit-demo/` | Three small, hand-built console captures for trying `atoo audit` and `atoo watch` with no console attached: `audit_demo_state.json` (a small rig with faults seeded on purpose), `audit_demo_state_before.json` (the same rig with every fault fixed) and `audit_demo_plan.json` (a plan to audit against). `atoo audit --help` and `atoo watch --help` name them. |

There is no show here yet: which show you start with is yours to choose.
To see a finished one first, `atoo ui`'s **Try the demo show** opens
the Demo, a five-piece band built from this same `conventions.md`. It
opens read-only; `atoo init --demo` copies it here as `demo-show/`,
a show of your own to change, rebuild and apply to a desk.
A **show bundle** is one show's files in one folder -- `input.csv`, the
input list (one row per input on stage), and `instructions.md`, how this
show differs from the house conventions. A build writes its plan into the
same folder, as `plan.json`.

## Next

```bash
atoo ui
```

opens Atoo in your browser, starting in this folder. Start your
first show with the bundle bar's **New show…**, and work through
Build's four steps.

A build calls an AI model, which you choose with environment variables
before starting `atoo ui`. See the user documentation's "Setting up
Atoo" page (https://docs.atoo.app/getting-started/configuration/) for how.
