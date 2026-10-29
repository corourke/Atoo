# Set up Atoo

Your house conventions, your presets and your desk are the same from show to show, so you set them up once. This page creates your Atoo folder, connects to your desk and checks your presets. The other half of setting up is the AI model that builds your plans: [Setting up an AI provider](ai-provider.md).

## 1. Create your Atoo folder: `atoo init`

```bash
atoo init
```

```
Working folder: ~/Documents/Atoo (created)
  README.md                    created
  conventions.md               created
  presets/README.md            created
  presets/                     23 presets: 23 created
  audit-demo/                  3 files: 3 created

~/.atoo.config:
  [conventions] default    set to ~/Documents/Atoo/conventions.md
  [presets] default        set to ~/Documents/Atoo/presets
  [workspace] default      set to ~/Documents/Atoo

Next: `atoo ui` opens Atoo in your browser, starting in ~/Documents/Atoo. ~/Documents/Atoo/README.md says what each file is.
```

It creates `~/Documents/Atoo` and sets up your config file, `~/.atoo.config`, to point at it:

| File | What it is |
|---|---|
| `conventions.md` | Example house conventions, to rewrite as your own house style |
| `presets/` | Twenty starter channel presets (`.chn`), one per common source, and three bus presets (`.bus`). Add your own, exported from the desk or WING Edit. |
| `audit-demo/` | Three small saved readings of a desk, for trying [`atoo audit`](audit.md) and [`atoo watch`](watch.md) with no desk |
| `README.md` | What each file is, and what to do next |

To get an editable copy of the Demo show as well, run `atoo init --demo` ([Build your first show](change-the-demo.md)).

`atoo init` never overwrites anything. To reset a file, delete it and run `atoo init` again, or run `atoo init --force`.

## 2. Connect to your desk

1. **Find the desk's address.** On the desk, it is in **Setup**, under the network settings. If you are not at the desk, WING Edit on a laptop on the same network shows the address of each desk it finds.
2. **Ping it.** This sends one message and writes nothing:

   ```bash
   a2 ping --console 192.0.2.16
   ```

   ```
   Console: WING,192.0.2.16,FOH,wing-compact,SN12345,3.1-0
   Detected model: WING Compact (wing-compact)
   ```

   If nothing answers, you'll see:

   ```
   no reply from 192.0.2.16:2223 -- is the console reachable, and is its OSC remote enabled?
   ```

   [Troubleshooting: the desk](troubleshooting-desk.md) covers what to check.

3. **Save the address**, so you don't type it every time. Add these two lines to `~/.atoo.config`:

   ```toml
   [console]
   default = "192.0.2.16"
   ```

   For a venue's desk you'll only use once, `export ATOO_CONSOLE=192.0.2.16` sets it for this terminal instead ([The console](#the-console)).

Already have a show on the desk that you didn't build with Atoo? You can [capture it](capture.md) to watch and edit it.

## 3. Look at your presets: `atoo presets`

`atoo presets` lists your preset library, by the names your conventions use:

```bash
atoo presets
```

```
No --presets given -- using the [presets] default in /home/you/.atoo.config: /home/you/Documents/Atoo/presets

20 preset(s) in /home/you/Documents/Atoo/presets

name     params  file
-------  ------  -----------
A Sax        83  A Sax.chn
Ac Gtr       83  Ac Gtr.chn
...
```

A preset's name is the one it was saved under on the desk, not its file name ([Using channel presets](presets.md)).

## 4. Confirm your settings

Commands report any settings used from your config file, so you can see where each value came from. These were run with a config file pointing at a copy of the starter conventions at `~/atoo/house.md` and of the starter presets at `~/atoo/channel_presets` (paths shortened to `/home/you`), in a folder holding a copy of the Demo show's `input.csv`:

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

A build lists every conventions layer it read and where each one came from, before it calls the model:

```bash
atoo build --console-model wing-compact --input input.csv --out plan.json
```

```
Conventions, in order -- each layer overrides the one above it:
  1. /home/you/atoo/house.md  (/home/you/.atoo.config)
```

If you do not see one of these lines, the setting was not used. Look for a one-line complaint about the config file just above it.

---

---

## The config file

Atoo takes its settings from two places, and neither is required:

| Where | What goes there |
|---|---|
| `~/.atoo.config` | Your house conventions file, your preset library, your watch conditions, your usual desk and your working folder: the same from show to show. |
| Environment variables | A desk for this session only ([below](#the-console)), and the AI model and its key ([Setting up an AI provider](ai-provider.md)). A key is a secret, so it does not belong in a file you might copy or share. |

A flag always wins for that one run: `--conventions`, `--presets` or `--console`.

`~/.atoo.config` is a small TOML file in your home directory. **`atoo init` writes its `[conventions]`, `[presets]` and `[workspace]` sections for you** ([step 1](#1-create-your-atoo-folder-atoo-init)). Here it is with every section filled in:

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

Every section is optional; leave out what you do not use. `~` means your home directory. A path that does not exist is reported on one line and then ignored, as if it were not there. It does not stop the command.

| Section | What it names | What reads it |
|---|---|---|
| `[conventions]` | your house [conventions file](conventions.md) | `build`, `resolve`, `patch`, and step 01 of `atoo ui` |
| `[presets]` | a folder of `.chn` [channel presets](presets.md) | `build`, `verify`, `apply`, `patch` (when the plan on the desk records no library it can find), `presets`, and `atoo ui` |
| `[watch_conditions]` | a house watch-conditions file | `watch` and `atoo ui` |
| `[console]` | the desk you normally use: address, and `port`/`timeout` if not the defaults | `ping`, `apply`, `patch`, `amend`, `undo`, `audit`, `watch`, and `atoo ui` (its bundle bar) |
| `[workspace]` | your working folder: where your shows live | `atoo ui` with no `--show`: its file browser, **Open…** and **New show…** start there |

**A house conventions file is the one to set first.** It is house style, the same for every show, which is why it lives outside any show's own folder. With `[conventions] default` set, you can drop `--conventions` from `build`. A show's own `instructions.md` still layers on top of it ([show bundles](show-bundles.md)).

The `[workspace]` folder, by default, holds your shows, presets, conventions and house watch-conditions. Running `atoo init` creates a workspace folder at `~/Documents/Atoo` and sets up your config file. When you start `atoo ui` it will report its working folder:

```
Working folder: ~/Documents/Atoo
```

**`atoo init` never replaces a value you have set.** It reports the value it found and the one it would have set; `atoo init --force` replaces it. Like every write to this file, it changes only that line.

`atoo ui` can write the `[conventions]` line for you. On Build step 01, **New file** has a checkbox that makes the new file the default, and **Replace the default** swaps it for another. Both change that one line and leave the rest of the file alone.

---

## The console

Every command that talks to a desk (`ping`, `apply`, `patch`, `amend`, `undo`, `audit`, `watch`) takes `--console <ip>`. There are three ways to give it, and the first one found wins:

1. `--console 192.0.2.16` on the command line, for that one run;
2. `export ATOO_CONSOLE=192.0.2.16`, for this terminal: a venue's desk, for one session;
3. `[console]` in `~/.atoo.config`, for the desk you always use.

A command that was not given `--console` prints which address it used, and where it came from. Read that line before a write.

---

## Next

[Setting up an AI provider](ai-provider.md): the model that writes your plans.
