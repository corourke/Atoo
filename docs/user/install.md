# Installing Atoo

On a Mac or Linux, two commands and one new terminal window. Each step
starts with how to tell it is already done, so skip any you have.
Windows: [below](#windows).

## 1. `uv`

`uv` installs a Python program as an app that you can call on the 
command line, and also fetches the correct version of Python (3.11 or newer).

```bash
uv --version
```

A version number means you have it: go to step 2. `command not found`
means you do not. Install it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If you are a Homebrew user, `brew install uv` does the same.

Then **open a new terminal window**. The installer puts uv in
`~/.local/bin` and updates your `PATH` in your shell's
startup file. In the new window, check:

```bash
uv --version
```

If you are still seeing `command not found`: run `~/.local/bin/uv tool update-shell`, then
open another new window.

## 2. Install Atoo

```bash
uv tool install --python 3.12 "atoo[ui]"
```

`--python 3.12` is needed to prevent use of the built-in
Python 3.9 that is installed by default on MacOS.

This installs Atoo and its browser UI into a private folder along with Python. It should end with `Installed 2 executables: a2, atoo`.  (You can use `a2` in place of `atoo` if you prefer that spelling.)

Then add `atoo` to your `PATH`:

```bash
uv tool update-shell; exec zsh
```

`update-shell` adds `~/.local/bin` to your shell's startup file. `exec zsh` restarts the shell in this window so it
reads the change; `zsh` is the default on a Mac. If you are using `bash` or any other
shell, open a new terminal window instead. Check:

```bash
atoo --version
```

Its first line names the copy you just installed:

```text
atoo 0.2.5 (installed copy at ~/.local/share/uv/tools/atoo/lib/python3.12/site-packages/atoo)
```

## 3. Open Atoo: `atoo ui`

```bash
atoo ui
```

```text
atoo 0.2.5 (installed copy at ~/.local/share/uv/tools/atoo/lib/python3.12/site-packages/atoo)
Console: none configured -- set one in the bundle bar (Change…) before Ping, Apply or a live Watch.
No show open and no working folder set -- `atoo init` makes ~/Documents/Atoo with house conventions and a preset library.
```

Atoo opens in your default browser. `Ctrl-C` in the terminal stops it.
You don't need to set anything up yet: the Demo show works as it is, and
[Set up Atoo](configuration.md) comes after it.

Next: [Try the Demo show](demo.md).

## Troubleshooting

**`uv: command not found`, or `atoo: command not found`, after a
successful install.** The terminal has not seen the `PATH` change: run
`uv tool update-shell; exec zsh` (or `~/.local/bin/uv tool update-shell`
if `uv` itself is not found), or open a new window. If using bash, open a new window.

**`uv tool install` says Atoo needs Python 3.11 or newer.** uv picked
the Python 3.9 that came with the laptop. Run step 2's command with
`--python 3.12` after `install`, as written above.

**`the web UI needs the 'ui' extra` from `atoo ui`.** It was installed
without `[ui]`. Install Atoo again: run step 2's command again with `--force` after `install`.

**The starter set is missing.** Install Atoo again: run step 2's command again with `--force` after `install`.

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
you have. See: ([Which atoo am I
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

Please [tell us](faq.md#found-something-wrong) how it went, good or bad.

To run Atoo from a clone of its repository instead, see [Installing from
a checkout](install-from-checkout.md).
