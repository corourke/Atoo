# Configuring Atoo

Your house conventions, your presets and your desk are the same from
show to show, so you should not have to type them every time. Set them
once here. Which AI model writes your plans is the other half:
[Setting up an AI provider](ai-provider.md).

Atoo takes its settings from two places:

| Where | What goes there | Why there |
|---|---|---|
| `~/.atoo.config` | your house conventions file, your preset library, your watch conditions, your usual desk, your working folder | These are **your** files and your desk, the same from show to show. |
| environment variables | a desk for this session only ([below](#the-console)), and the AI model and its key ([Setting up an AI provider](ai-provider.md)) | A key is a secret, so it does not belong in a file you might copy or share, and a venue's desk is for one session. |

Neither is required. Without the config file, every command takes its
paths and console as flags. Every flag beats both, so `--conventions`,
`--presets` or `--console` always wins for that one run.

---

## The config file

`~/.atoo.config` is a small TOML file in your home directory.
**`atoo init` writes its `[conventions]`, `[presets]` and `[workspace]`
sections for you** ([First run](install.md#3-first-run-atoo-init-then-atoo-ui)).
Here it is with every section filled in:

```toml
[conventions]
default = "~/atoo/house.md"

[presets]
default = "~/atoo/channel_presets"

[watch_conditions]
default = "~/atoo/house.watch.json"

[console]
default = "192.0.2.16"
port = 2223
timeout = 1.0

[workspace]
default = "~/Documents/Atoo"
```

Every section is optional; leave out what you do not use. `~` means
your home directory. A path that does not exist is reported on one line
and then ignored, as if it were not there. It does not stop the command.

| Section | What it names | What reads it |
|---|---|---|
| `[conventions]` | your house [conventions file](conventions.md) | `build`, `resolve`, `patch`, and step 01 of `atoo ui` |
| `[presets]` | a folder of `.chn` [channel presets](presets.md) | `build`, `verify`, `apply`, `patch` (when the plan on the desk records no library it can find), `presets`, and `atoo ui` |
| `[watch_conditions]` | a house watch-conditions file | `watch` and `atoo ui` |
| `[console]` | the desk you normally use: address, and `port`/`timeout` if not the defaults | `ping`, `apply`, `patch`, `amend`, `undo`, `audit`, `watch`, and `atoo ui` (its bundle bar) |
| `[workspace]` | your working folder: where your shows live | `atoo ui` with no `--show`: its file browser, **Open…** and **New show…** start there |

**A house conventions file is the one to set first.** It is house style,
the same for every show, which is why it lives outside any show's own
folder. With `[conventions] default` set, you can drop `--conventions`
from `build`. A show's own `instructions.md` still layers on top of it
([show bundles](show-bundles.md)).

The `[workspace]` folder, by default, holds your shows, presets,
conventions and house watch-conditions. Running `atoo init` creates a
workspace folder at `~/Documents/Atoo` and sets up your config file. When
you start `atoo ui` it will report its working folder:

```
Working folder: ~/Documents/Atoo -- Open… and New show… start here.
```

**`atoo init` never replaces a value you have set.** It reports the
value it found and the one it would have set; `atoo init --force`
replaces it. Like every write to this file, it changes only that line.

`atoo ui` can write the `[conventions]` line for you. On Build step 01,
**New file** has a checkbox that makes the new file the default, and
**Replace the default** swaps it for another. Both change that one line
and leave the rest of the file alone.

### Check it took

Commands report any settings used from your config file. These were run in a folder holding a
copy of the Demo show's `input.csv`, with the file above pointing at a
copy of the starter conventions (`starter/conventions.md`) at
`~/atoo/house.md` and of the starter presets (`starter/presets/`)
at `~/atoo/channel_presets` (paths shortened to `/home/you`):

```bash
atoo presets
```

```
No --presets given -- using the [presets] default in /home/you/.atoo.config: /home/you/atoo/channel_presets

19 preset(s) in /home/you/atoo/channel_presets
...
```

```bash
atoo ping
```

```
Using console 192.0.2.16 from /home/you/.atoo.config [console]
```

A build lists every conventions layer it read and where each one came
from, before it calls the model:

```bash
atoo build --console-model wing-compact --input input.csv --out plan.json
```

```
Conventions, in order -- each layer overrides the one above it:
  1. /home/you/atoo/house.md  (/home/you/.atoo.config)
```

If you do not see one of these lines, the setting was not used. Look
for a one-line complaint about the config file just above it.

---

## The console

Every command that talks to a desk (`ping`, `apply`, `patch`, `amend`,
`undo`, `audit`, `watch`) takes `--console <ip>`. There are three ways
to give it, and the first one found wins:

1. `--console 192.0.2.16` on the command line, for that one run;
2. `export ATOO_CONSOLE=192.0.2.16`, for this terminal: a venue's desk,
   for one session;
3. `[console]` in `~/.atoo.config`, for the desk you always use.

A command that was not given `--console` says which address it used, and
where it came from ([Connect to your desk and try the CLI](testing-on-your-desk.md#1-before-you-start)).
Read that line before a write.

---

## Next

[Setting up an AI provider](ai-provider.md): the model that writes your
plans.
