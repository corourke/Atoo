# Installing Atoo

On a Mac or Linux, two commands and one new terminal window. Each step
starts with how to tell it is already done, so skip any you have.
Windows: [below](#windows).

## 1. uv

uv installs a Python program the way an app is installed: one command,
its own private folder, and one command to remove it. It also fetches
the Python that Atoo needs (3.11 or newer), so you never install one
yourself, and leaves the Python your laptop came with alone.

```bash
uv --version
```

A version number means you have it: go to step 2. `command not found`
means you do not. Install it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

With Homebrew, `brew install uv` does the same.

Then **open a new terminal window**. The installer puts uv in
`~/.local/bin` and adds that folder to your `PATH` in your shell's
startup file, and a window that was already open does not read the
change. In the new window, check:

```bash
uv --version
```

Still `command not found`: run `~/.local/bin/uv tool update-shell`, then
open another new window.

## 2. Install Atoo

```bash
uv tool install --python 3.12 "atoo[ui]"
```

`--python 3.12` is not optional on a Mac: without it uv may pick the
Python 3.9 that Apple's Command Line Tools put on the laptop, and stop
with an error that Atoo needs Python 3.11 or newer. With it, uv uses a
3.12 it already has or downloads one of its own.

This installs Atoo and its browser UI into a private folder of their
own, with a Python of their own, and changes nothing else on the
laptop. It ends with `Installed 2 executables: a2, atoo`: two commands
that are the same command, `atoo`, and `a2`, its short spelling
(`a2 ui` is `atoo ui`).

Make sure `atoo` is on your `PATH`, whatever the installer did on this
laptop (on a new Mac account it often is not yet):

```bash
uv tool update-shell; exec zsh
```

`update-shell` adds `~/.local/bin` to your shell's startup file, or says
it is already there. `exec zsh` restarts the shell in this window so it
reads the change; zsh is the default on a Mac. In bash or any other
shell, open a new terminal window instead. Check:

```bash
atoo --version
```

Its first line names the copy you just installed:

```text
atoo 0.2.4 (installed copy at ~/.local/share/uv/tools/atoo/lib/python3.12/site-packages/atoo)
```

`atoo: command not found`: the command above, then `atoo --version`
again.

## 3. First run: `atoo init`, then `atoo ui`

`atoo init` gives you a folder of your own to work in, so nothing you
do touches the files Atoo ships. It makes `~/Documents/Atoo` (or
wherever `--dir` says), copies a starter set into it, and points
`~/.atoo.config` at it:

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

| File | What it is |
|---|---|
| `README.md` | what each file is, and what to do next |
| `conventions.md` | example house conventions, to rewrite as your own house style |
| `presets/` | nineteen starter channel presets (`.chn`), one per common source, that `conventions.md` names, and three bus presets (`.bus`): a compressor for the mix busses and a reverb for each of two FX busses. Export your own from the desk into it |
| `audit-demo/` | three small, hand-built console captures for trying [`atoo audit`](audit.md) and [`atoo watch`](watch.md) with no desk |

**It never overwrites anything.** A file already there is left alone and
reported, and so is a config value that already names something else
(`--force` replaces that, never a file you have edited). Run it twice
and the second run says `Nothing to do`.

It makes no show: your first one is made in the browser with **New
show…**. To edit the Demo show, `atoo init --demo` adds a copy of it
([Change the Demo show](change-the-demo.md)).

Then open Atoo in your browser:

```bash
atoo ui
```

```text
atoo 0.2.4 (installed copy at ~/.local/share/uv/tools/atoo/lib/python3.12/site-packages/atoo)
Atoo: http://127.0.0.1:8420 -- Build, Apply and Watch (Ctrl-C to stop)
Session-based: closing this stops whatever it was watching, and nothing is kept between runs.
Watch and Build never write to a console. The shell's Apply mode is the one screen that does, and only with Arm ticked.
Console: none configured -- set one in the bundle bar (Change…) before Ping, Apply or a live Watch.
Working folder: ~/Documents/Atoo -- Open… and New show… start here.
```

The page opens in your default browser. Over SSH, with no display, it
opens nothing and says so; the address is printed for that.
`--no-browser` turns the opening off, and a second `atoo ui` opens the
one already running. `Ctrl-C` in the terminal stops it.

Next: [Try the Demo show](demo.md).

## When it does not work

**`uv: command not found`, or `atoo: command not found`, after a
successful install.** The terminal has not seen the `PATH` change: run
`uv tool update-shell; exec zsh` (or `~/.local/bin/uv tool update-shell`
if `uv` itself is not found), or open a new window. In bash, open a new
window rather than `exec zsh`.

**`uv tool install` says Atoo needs Python 3.11 or newer.** uv picked
the Python 3.9 that came with the laptop. Run step 2's command with
`--python 3.12` after `install`, as written above.

**`the web UI needs the 'ui' extra` from `atoo ui`.** It was installed
without `[ui]`. Run step 2's command again with `--force` after
`install`.

**The starter set is missing.** If an install has lost it, `init`
writes nothing, exits 1, and says where it looked. Install it again:
step 2's command with `--force` after `install`.

[Troubleshooting](troubleshooting.md) covers the desk, builds and the
browser.

## Updating and removing

```bash
uv tool upgrade atoo     # fetches the latest and installs it again
uv tool uninstall atoo   # removes the program
```

Neither touches your shows, `~/Documents/Atoo` or `~/.atoo.config`.

## If you already use Homebrew and pipx

pipx does the same job as uv, on a Python you provide. If you already
keep your command-line programs with it:

1. `pipx --version`; if it is not found, `brew install pipx`.
2. Check the Python pipx uses: `"$(pipx environment --value
   PIPX_DEFAULT_PYTHON)" --version`. Atoo needs 3.11 or newer. If it is
   older, `brew install python@3.12`, and add `--python python3.12`
   after `pipx install` below. Leave the 3.9 at `/usr/bin/python3`
   alone: it belongs to Apple's Command Line Tools.
3. `pipx ensurepath`, then open a new terminal window.
4. Install Atoo:

   ```bash
   pipx install "atoo[ui]"
   ```

Its `atoo --version` names a copy in pipx's own folder, ending
`pipx/venvs/atoo/...`. To update or remove it: `pipx upgrade atoo`,
`pipx uninstall atoo`. Keep one of the two installs, not both: each
puts its `atoo` in `~/.local/bin`, and `atoo --version` says which one
you have ([Which atoo am I
running?](install-from-checkout.md#4-which-atoo-am-i-running)).

## Windows

Windows installation has not been tested yet, however, it should work
with Python 3.11 and later. Please report your findings if you are able
to install and run Atoo on Windows.

1. Install Python from
   [python.org/downloads](https://www.python.org/downloads/), ticking
   *Add python.exe to PATH*.
2. In a new Command Prompt:

   ```
   py -m pip install --user pipx
   py -m pipx ensurepath
   ```

3. Open a new Command Prompt, and install Atoo:

   ```
   pipx install "atoo[ui]"
   ```

The configuration file is `C:\Users\<you>\.atoo.config`, and `init`
makes `C:\Users\<you>\Documents\Atoo`, even when your Documents folder
is kept in OneDrive; `atoo init --dir` puts it where you want it.
Atoo reads and writes every file as UTF-8, so save your input list,
conventions and instructions as UTF-8: Excel's *CSV UTF-8* and
Notepad's default both do.

Please [tell us](limitations.md#telling-us) how it went, good or bad.

To run Atoo from a clone of its repository instead, see [Installing from
a checkout](install-from-checkout.md).
