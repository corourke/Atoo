# Installing Atoo

Seven steps on a Mac, in order. Each one starts with how to tell it is
already done, so skip any you have. No Homebrew, or a Linux or Windows
laptop: [Installing without Homebrew](install-without-homebrew.md) gets
you to step 5.

## 1. Homebrew

Homebrew installs command-line programs on a Mac. Atoo strongly
recommends it: the steps below assume it.

```bash
brew --version
```

A version number means you have it: go to step 2. `command not found`
means you do not:

1. Install it with the one command on [brew.sh](https://brew.sh). It
   asks for your Mac password, and installs Apple's Command Line Tools
   (which include `git`) if you do not have them.
2. Put it on your `PATH`, so the terminal can find it. On an Apple
   Silicon Mac (M1 and later):

   ```bash
   echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zshrc && exec zsh
   ```

   On an Intel Mac it is in `/usr/local/bin`, which is already on your
   `PATH`.
3. Check: `brew --version` now prints a version.

## 2. pipx

pipx installs a Python program the way an app is installed: one
command, its own private folder, and one command to remove it.

```bash
pipx --version
```

If that says `command not found`:

```bash
brew install pipx
```

## 3. Python 3.11 or newer

Atoo needs Python 3.11 or newer, and runs on the Python pipx itself
uses. `python3` on a stock Mac is 3.9, which is too old, but Homebrew's
pipx brings its own current Python. Check which one pipx uses:

```bash
"$(pipx environment --value PIPX_DEFAULT_PYTHON)" --version
```

`Python 3.11` or later: go to step 4. Older, or an error:

```bash
brew install python@3.12
python3.12 --version
```

and in step 5, add `--python python3.12` after `pipx install`.

Leave the 3.9 at `/usr/bin/python3` alone: it belongs to Apple's
Command Line Tools, and parts of the system use it. The two live side by
side under their own names.

## 4. Put pipx's programs on your `PATH`

pipx puts the programs it installs in `~/.local/bin`. Make sure your
terminal looks there:

```bash
pipx ensurepath && exec zsh
```

`exec zsh` starts a fresh shell in the same window, which is what picks
up the change. A terminal already open in another window does not see
it until you open a new one.

## 5. Install Atoo

```bash
pipx install "atoo[ui] @ git+https://github.com/corourke/Atoo.git"
```

This installs Atoo and its browser UI into a private folder of their
own, and changes nothing else on the laptop. It gives you two commands
that are the same command: `atoo`, and `a2`, its short spelling
(`a2 ui` is `atoo ui`). Check:

```bash
atoo --version
```

Its first line names the copy you just installed:

```text
atoo 0.2.1 (installed copy at ~/.local/pipx/venvs/atoo/lib/python3.12/site-packages/atoo)
```

## 6. First run: `atoo init`, then `atoo ui`

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
atoo 0.2.1 (installed copy at ~/.local/pipx/venvs/atoo/lib/python3.12/site-packages/atoo)
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

**`atoo: command not found` after a successful install.** The terminal
has not seen step 4: run `exec zsh`, or open a new terminal.
`pipx list` says where the command went.

**pipx refuses Atoo for its Python version.** pipx is using a Python
older than 3.11: do step 3, and install with `--python python3.12`.

**`the web UI needs the 'ui' extra` from `atoo ui`.** It was installed
without `[ui]`. Install it again with the extra:

```bash
pipx install --force "atoo[ui] @ git+https://github.com/corourke/Atoo.git"
```

**`python3.12: command not found` right after `brew install`.**
Homebrew is not on your `PATH`: step 1, part 2.

**The starter set is missing.** If an install has lost it, `init`
writes nothing, exits 1, and says where it looked. Reinstall:
`pipx reinstall atoo`.

[Troubleshooting](troubleshooting.md) covers the desk, builds and the
browser.

## Updating and removing

```bash
pipx reinstall atoo     # fetches the latest and installs it again
pipx uninstall atoo     # removes the program
```

Neither touches your shows, `~/Documents/Atoo` or `~/.atoo.config`.

To run Atoo from a clone of its repository instead, see [Installing from
a checkout](install-from-checkout.md).
