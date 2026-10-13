# Setting up Atoo

Do this once, before your first show. Atoo takes its settings from
two places, and each one holds different things:

| Where | What goes there | Why there |
|---|---|---|
| `~/.atoo.config` | your house conventions file, your preset library, your watch conditions, your usual desk, your working folder | These are **your** files and your desk. They stay the same from show to show, so you should not have to retype them. |
| environment variables | which AI model writes the plan, and its API key | A key is a secret, so it does not belong in a file you might copy or share. Switching models is a per-session choice. |

Neither is required. Without the config file, every command takes its
paths and console as flags. Without the environment variables, `build`
uses Claude, which needs an API key, and stops with a one-line message
if it has none (see [Choosing the model](#choosing-the-model)).

Every command-line flag beats both, so `--conventions`, `--presets` or
`--console` always wins for that one run.

---

## The config file

`~/.atoo.config` is a small TOML file in your home directory.
**`atoo init` writes its `[conventions]`, `[presets]` and `[workspace]` sections for you** -- see
[First run](install.md#first-run-atoo-init). Here it is with every
section filled in:

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
folder. With
`[conventions] default` set, you can drop `--conventions` from `build`.
A show's own `instructions.md` still layers on top of it
([show bundles](show-bundles.md)).

**`[workspace]` is the folder you keep your shows in.** `atoo init`
makes `~/Documents/Atoo` and sets it. `atoo ui` started with no
`--show` opens its file browser there, so **New show…** puts a new show
beside the others, and says so when it starts:

```
Working folder: ~/Documents/Atoo -- Open… and New show… start here.
```

Nothing else reads it: every other command takes its files from flags or
from `--show`.

**`atoo init` never replaces a value you have set.** It reports the
value it found and the one it would have set; `atoo init --force`
replaces it. Like every write to this file, it changes only that line.

`atoo ui` can write the `[conventions]` line for you. On Build step 01,
**New file** has a checkbox that makes the new file the default, and
**Replace the default** swaps it for another. Both change that one line
and leave the rest of the file alone.

### Check it took

Every command that uses a setting from this file **says so**, so you
can see where a value came from. These were run in a folder holding a
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

## Choosing the model

Only `atoo build` calls a model (and `atoo resolve`, the step
a build runs for you when your conventions change), and so does a build
started from Build in `atoo ui`. `patch` uses one too when you type the change in words.
`verify`, `apply`, `audit` and `watch` never do.

The model is chosen by environment variables. Put the `export` lines in
your shell's startup file (`~/.zshrc` on a Mac, `~/.bashrc` on most
Linux) so every new terminal has them. Start `atoo ui` from a
terminal that has them too: the browser's builds run on the settings of
the terminal that started the UI.

### Claude (what Atoo is tuned against)

```bash
export ATOO_AI_PROVIDER=claude
export ANTHROPIC_API_KEY=sk-ant-...     # or ATOO_AI_API_KEY
```

That is all a Claude build needs. By default every call runs on
`claude-sonnet-5-5`: the plan, the `--critic` review, the
watch-conditions draft and the resolve step. `ATOO_AI_MODEL` changes the first;
`ATOO_AI_CRITIC_MODEL`, `ATOO_AI_WATCHLIST_MODEL` and
`ATOO_AI_RESOLVE_MODEL` change the other three.

**Never put the key in a file in a repository.** A shell startup file in
your home directory is fine. `~/.atoo.config` is the wrong place:
it has no key setting, on purpose.

### A local model with Ollama

Claude is the default. With `ATOO_AI_PROVIDER=ollama`, `build` asks
an Ollama server on this machine (`http://localhost:11434`) for
`llama3.1` instead. This is the only setup that works with no network at
all. Plans from small local models have not
been shown to be good enough for a real show, so check them hard. To
choose the model:

```bash
export ATOO_AI_PROVIDER=ollama
export ATOO_AI_MODEL=qwen2.5-coder:7b
```

### Any OpenAI-compatible host

```bash
export ATOO_AI_PROVIDER=api
export ATOO_AI_API_KEY=...
export ATOO_AI_MODEL=gpt-4o-mini
export ATOO_AI_BASE_URL=https://api.openai.com   # the host, without /v1
```

### Check it took

A build names the model before it sends anything. On a Claude build the
plan's call looks like this:

```
claude-sonnet-5-5 (generator, effort medium): sending, waiting for the first reply...
```

and with `ATOO_AI_PROVIDER=ollama` like this:

```
llama3.1 (generator): sending, waiting for the first reply...
```

The first build after your conventions change makes one call before
that, to resolve them. It is named the same way, as
`(resolve, effort medium)` on Claude, and the line above it says why.

With no key, a build stops before it sends anything, and says both ways
forward:

```
generation failed: a build needs a model: the default is Claude, which needs an API key in ANTHROPIC_API_KEY (or ATOO_AI_API_KEY) -- or set ATOO_AI_PROVIDER=ollama to use a local Ollama model instead
```

The effort levels, token limits, thinking budget and timeouts are in the
full table in the
[CLI reference](cli-reference.md#choosing-and-tuning-the-model). You do
not need any of them to get started.

---

## The console, per session

`[console]` above is for the desk you always use. For one session, such
as a venue's desk, use the environment instead:

```bash
export ATOO_CONSOLE=198.51.100.9
```

That beats the config file, and `--console` beats both. See
[Pointing it at your console](install.md#pointing-it-at-your-console) for
the line each command prints about which address it used, and why you
should read it before an `apply --confirm`.

---

## Next

[Command-line quickstart](quickstart.md): an input list to a plan on a console, end
to end.
