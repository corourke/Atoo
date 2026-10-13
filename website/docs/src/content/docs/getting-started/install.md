---
title: "Installing Atoo"
description: "One command puts Atoo on a Mac or a Linux laptop, and two more set it up and open it in your browser."
sidebar: 
  order: 2
---

<!-- Generated from docs/user/install.md by tools/docs_to_starlight.py in the development repository. Edit it there. -->
One command puts Atoo on a Mac or a Linux laptop, and two more set
it up and open it in your browser.

## Short version

With [pipx](#getting-pipx) installed:

```bash
pipx install "atoo[ui] @ git+https://github.com/corourke/ShowProof.git"
atoo init     # makes ~/Documents/Atoo: house conventions, presets
atoo ui       # opens Atoo in your browser, starting there
```

The first line installs Atoo and its browser UI into a private
folder of their own and puts the `atoo` command on your `PATH`, with
`a2` beside it as a short spelling of the same command (`a2 ui` is
`atoo ui`). It changes nothing else on the laptop. [First run](#first-run-atoo-init)
says what the other two lines do.

Windows has not been tried yet: see [Windows](#windows).

## Getting pipx

pipx installs a Python program the way an app is installed: one command,
its own private folder, and one command to remove it.

*macOS*, with [Homebrew](https://brew.sh):

```bash
brew install pipx
pipx ensurepath
```

*Linux*: `sudo apt install pipx` on Debian 12, Ubuntu 23.04 or later;
otherwise `python3 -m pip install --user pipx`. Then `pipx ensurepath`.

**Then open a new terminal.** `pipx ensurepath` adds pipx's command
folder (`~/.local/bin`) to your `PATH`, and only a new terminal sees it.

The `git+https://` address needs `git`. On a Mac, the first use of `git`
offers to install Apple's Command Line Tools: say yes. Homebrew has
already installed them if you used it.

## Updating and removing

```bash
pipx reinstall atoo     # fetches the latest and installs it again
pipx uninstall atoo     # removes the program
```

Neither touches your shows, `~/Documents/Atoo` or
`~/.atoo.config`.

## Python 3.11 or newer

pipx runs Atoo on the Python pipx itself was installed with.
Homebrew's pipx brings a current one. To check:

```bash
pipx environment --value PIPX_DEFAULT_PYTHON    # a path; run it with --version
```

`python3` on a stock macOS is 3.9. Everything works there except
reading `~/.atoo.config`, which says so when it fails.

To run Atoo on a newer Python than pipx's own, name it:

```bash
pipx install --python python3.12 "atoo[ui] @ git+https://github.com/corourke/ShowProof.git"
```

To install a newer Python on a Mac, see [Installing from a
checkout](/getting-started/install-from-checkout/#upgrading-python-on-macos).

## Windows

**Not supported yet: nobody has run Atoo on Windows.** Reading the
code says it should work. The configuration file is
`C:\Users\<you>\.atoo.config`, `init` makes
`C:\Users\<you>\Documents\Atoo`, and `atoo ui` opens your
browser. Atoo reads and writes every file as UTF-8 on Windows too,
so a name with an accent or a dash in it stays as you typed it. Save
your input list, conventions and instructions as UTF-8; Excel's *CSV
UTF-8* and Notepad's default both do.

If you try it: install Python from
[python.org/downloads](https://www.python.org/downloads/) (tick *Add
python.exe to PATH*), and [Git for Windows](https://git-scm.com/download/win)
for the `git+https://` address; then, in a new Command Prompt:

```
py -m pip install --user pipx
py -m pipx ensurepath
```

Open a new Command Prompt and run the [short version](#short-version).
If your Documents folder is kept in OneDrive, `init` still makes its
folder under `C:\Users\<you>\Documents`; `atoo init --dir` puts it
where you want it. Please [tell us](/reference/limitations/#telling-us) how it
went, good or bad.

## First run: `atoo init`

`atoo init` gives you a folder of your own to work in, so nothing
you do touches the files Atoo ships. It makes
`~/Documents/Atoo` (or wherever `--dir` says) and copies a small
starter set into it:

| File | What it is |
|---|---|
| `README.md` | what each file is, and what to do next |
| `conventions.md` | example house conventions, to rewrite as your own house style |
| `presets/` | your library of WING channel presets (`.chn`): nineteen starter presets, one per common source, that `conventions.md` names, and three bus presets (`.bus`): a compressor for the mix busses and a reverb for each of two FX busses. Export your own from the desk into it |

Then it points `~/.atoo.config` at them: `[conventions]` at
`conventions.md`, `[presets]` at `presets/`, and `[workspace]`
at the folder itself, which is where `atoo ui` starts.

It makes no show. Which show you start with is yours to choose, so the
first one is made in the UI with the bundle bar's **New show…**, which
starts in this folder. The one exception is asked for:
[`init --demo`](#a-copy-of-the-demo-show-init---demo) copies the Demo
show in as well.

```bash
atoo init
```

```
Working folder: ~/Documents/Atoo (created)
  README.md                    created
  conventions.md               created
  presets/README.md            created
  presets/                     22 presets: 22 created

~/.atoo.config:
  [conventions] default    set to ~/Documents/Atoo/conventions.md
  [presets] default        set to ~/Documents/Atoo/presets
  [workspace] default      set to ~/Documents/Atoo

Next: `atoo ui` opens Atoo in your browser, starting in ~/Documents/Atoo. ~/Documents/Atoo/README.md says what each file is.
```

**It never overwrites anything.** A file already in the folder is left
alone and reported. A config value that already names something else is
left alone, and the line says what `init` would have set:

```
  [conventions] default    left as ~/house.md -- init would have set ~/Documents/Atoo/conventions.md; --force replaces it
```

Run it twice and the second run changes nothing, and says
`Nothing to do: everything init sets up is already here, and it changes
nothing that is.` `--force` replaces those config values, and any
starter file that is an *unchanged* copy of an older starter set. It never
replaces a file you have edited. (`init` records what it copied in a
hidden `.atoo-starter.json` in the folder, which is how it can tell.)

### A copy of the Demo show: `init --demo`

The Demo show the UI opens is read-only. To change it, rebuild it, or
[apply it to a desk of your own](/getting-started/testing-on-your-desk/), make a copy
with `--demo`. It does everything `init` does, and also writes the Demo
show into the folder as `demo-show/`, beside the starter conventions and
presets it was built from, so it opens with its plan current. Run after
`init`, it adds only the copy:

```bash
atoo init --demo
```

```
Working folder: ~/Documents/Atoo (already there)
  README.md                    already there
  conventions.md               already there
  presets/README.md            already there
  presets/                     22 presets: 22 already there
  demo-show/input.csv          created
  demo-show/instructions.md    created
  demo-show/plan.json          created
  demo-show/watch.json         created

~/.atoo.config:
  [conventions] default    already ~/Documents/Atoo/conventions.md
  [presets] default        already ~/Documents/Atoo/presets
  [workspace] default      already ~/Documents/Atoo

Next: `atoo ui` opens Atoo in your browser, starting in ~/Documents/Atoo. ~/Documents/Atoo/README.md says what each file is.
The Demo show's copy is ~/Documents/Atoo/demo-show: yours to edit, build and apply.
```

The copy is yours from then on. A `demo-show` folder already there is
never written over, with or without `--force`:

```
  demo-show/                   left alone: a demo-show folder is already here -- rename it, and run init --demo again, for a fresh copy
```

### When the starter set is missing

The starter set comes from the installed Atoo itself. If an install
has lost it, `init` writes nothing, exits 1, and says where it looked and
how to reinstall (the two paths shortened here):

```
this Atoo install has no starter set (looked in .../atoo/starter or .../starter) -- nothing was written. Reinstall Atoo (`pipx reinstall atoo`, or from a checkout `pipx install --force --editable .`).
```

### Then `atoo ui`

```bash
atoo ui
```

```
Atoo: http://127.0.0.1:8420 -- Build, Apply and Watch (Ctrl-C to stop)
Session-based: closing this stops whatever it was watching, and nothing is kept between runs.
Watch and Build never write to a console. The shell's Apply mode is the one screen that does, and only with Arm ticked.
Console: none configured -- set one in the bundle bar (Change…) before Ping, Apply or a live Watch.
Working folder: ~/Documents/Atoo -- Open… and New show… start here.
```

The page opens in your default browser as soon as the server answers.
The address is printed as well, for when no browser can be opened: over
SSH, with no display, `ui` opens nothing and says so. `--no-browser`
turns the opening off. If Atoo is already running on that port, a
second `atoo ui` opens the running one and exits rather than
failing.

With no `--show`, the bundle bar's **Open…** and **New show…** open
on the working folder, so a new show lands beside the starter ones.

To look round before you have a show or a console, press **Try the Demo
show** on the empty page (or, at any time, **Change…** beside
*Console:* and choose **Demo**). It opens a small, read-only show on a
built-in rig, so Build, Apply's pre-flight and Watch all have something
to show ([Try the Demo show](/getting-started/demo/)). Choosing an address, or opening
or creating a show, leaves it.

Before your first build, choose the model that writes plans:
[Setting up Atoo](/getting-started/configuration/#choosing-the-model).

## When it does not work

Three failures account for nearly all of them.

**`atoo: command not found` after a successful install.** With
pipx, the terminal was opened before `pipx ensurepath`: open a new one.
`pipx list` says where the command went.

From a checkout, see [Installing from a checkout](/getting-started/install-from-checkout/).

**`the web UI needs the 'ui' extra` from `atoo ui`.** It was
installed without `[ui]`. With pipx, install it again with the extra:

```bash
pipx install --force "atoo[ui] @ git+https://github.com/corourke/ShowProof.git"
```

The UI is the one part of Atoo that is not dependency-free, so
this is a normal thing to hit rather than a broken install.

## Pointing it at your console

Four commands talk to a desk — `ping`, `apply`, `audit` and `watch` —
and each takes `--console <ip>`. Check it works:

```bash
atoo ping --console 192.0.2.16
```

```
Console: WING,192.0.2.16,FOH,wing-compact,SN12345,3.1-0
Detected model: WING Compact (wing-compact)
```

If nothing answers, see
[Troubleshooting](/troubleshooting/troubleshooting/#atoo-cannot-reach-the-console).

**You do not have to retype that address.** Set it once for the
session with `export ATOO_CONSOLE=192.0.2.16`, or for good in
`~/.atoo.config` ([Setting up Atoo](/getting-started/configuration/)). A
command that was not told its console on the command line says where it
got one:

```
Using console 192.0.2.16 from ATOO_CONSOLE
```

Read that line. It is there so that an `export` left over from last
week's desk cannot quietly aim an `apply --confirm` at the wrong box.

## Next

If you have not yet, run [`atoo init`](#first-run-atoo-init).

[Setting up Atoo](/getting-started/configuration/): which model writes your plans,
and where your house conventions, presets and desk live, set once.

Then, in the browser, [try the Demo show](/getting-started/demo/) and
[build a show](/build/build-a-show/) of your own. Or, from a terminal, the
[Command-line quickstart](/getting-started/quickstart/): an input list to a plan on a
console, once, end to end.
