# Installing from a checkout

The [pipx install](install.md) is all most people need. This page is for
running Atoo from a clone of its repository instead, to try a branch:
installed into a virtualenv, a private directory of packages with its
own `python3` and `atoo` commands, inside the clone.

**On a Mac, the virtualenv is not optional.** Homebrew's Python refuses
a `pip install` outside one, with `error: externally-managed-environment`.
The virtualenv is the fix: it cannot disturb the system Python, and a bad
install is `rm -rf .venv` away from gone.

This needs Python 3.11 or newer: [step 3 of Installing
Atoo](install.md#3-python-311-or-newer) gets one with Homebrew, and
[Installing without Homebrew](install-without-homebrew.md) without.
`venv` is in the standard library; only Debian and Ubuntu split it out,
as `apt install python3-venv`.

## 1. Make the virtualenv, in the clone

```bash
git clone https://github.com/corourke/Atoo.git
cd Atoo
python3 -m venv .venv          # python3.12 if python3 is older than 3.11
source .venv/bin/activate
```

Your prompt gains a `(.venv)` prefix. **Activation is per terminal**: a
new window, tab, or reboot starts outside it, and the `source` line,
run in the clone, is what puts you back. `deactivate` leaves it.

## 2. Install the clone into it

```bash
python3 -m pip install -e ".[ui]"
hash -r
```

`-e` installs a link to the clone rather than a copy, so `git checkout`
of another branch changes what runs with no reinstall. `[ui]` brings the
browser UI, `atoo ui`. `hash -r` makes the terminal forget where it last
found `atoo`.

## 3. Which atoo am I running?

**Check this before you test anything.** If you also have the pipx
install, there are two `atoo` commands on your laptop, and the terminal
runs whichever it finds first. Ask the one you are about to use:

```bash
atoo --version
```

```text
atoo 0.2.0 (running from ~/Atoo/atoo; branch my-branch, a1b2c3d, clean)
Python 3.13.16 at ~/Atoo/.venv/bin/python3
```

The first line is the answer: the version, the folder the code runs from,
and, for a clone, the **branch**, the short **commit**, and `clean` or
`uncommitted changes` (to files git tracks). `atoo ui` prints the same
line before anything else, and the page shows it at the bottom. The
version number alone never tells branches apart. What you want to see is
your clone's folder and the branch you checked out.

The pipx copy's first line is different, and names no branch:

```text
atoo 0.2.0 (installed copy at ~/.local/pipx/venvs/atoo/lib/python3.12/site-packages/atoo)
```

That is a private copy of a release, which never follows `git checkout`.
If you see it while testing a branch, the virtualenv is not active in
this terminal: run the `source` line from step 1 in the clone. Without
`git` on the machine, a clone says `a git checkout, but git is not
installed` in place of the branch.

There are three ways to run a branch, and `atoo --version` tells you which
one you are in:

| How you run it | What runs |
|---|---|
| `atoo`, with the clone's virtualenv active (`which atoo` ends in `.venv/bin/atoo`) | the clone's current branch, from the editable install in step 2 |
| `python3 -m atoo.cli`, from the clone's top folder | the clone's code, with no install at all; the packages it needs must be in that Python (`atoo ui` needs the `ui` extra, so on a Mac use the virtualenv) |
| `atoo` with no virtualenv active | whichever `atoo` is first on your `PATH`: usually `~/.local/bin/atoo`, the pipx copy, which ignores the clone |

`which -a atoo` lists every `atoo` on your `PATH`; the first one wins.
The same check from outside Atoo:

```bash
which atoo
python3 -c "import atoo; print(atoo.__file__)"
```

Both must be inside the clone: `which atoo` ending in `.venv/bin/atoo`,
and the second a path under the clone's `atoo/` folder.

To see where the pipx copy was installed from:

```bash
ls -l ~/.local/bin/atoo
cat "$(pipx environment --value PIPX_LOCAL_VENVS)"/atoo/lib/python3*/site-packages/atoo-*.dist-info/direct_url.json
```

The first shows the launcher pointing into pipx's own folder, not your
clone. The second names the source pipx installed from; for an install
from GitHub it carries the commit as well.

To run the clone whatever your `PATH` says, name it:
`./.venv/bin/atoo ui`, from the clone's top folder.

## 4. Switching branches

```bash
git checkout <branch>
```

With the editable install, the next `atoo` command runs that branch.
Install again only if the branch adds a dependency:
`python3 -m pip install -e ".[ui]"`.

## 5. Going back to the pipx install

Open a new terminal, or type `deactivate`. `which atoo` is
`~/.local/bin/atoo` again.

Then carry on from [First run](install.md#6-first-run-atoo-init-then-atoo-ui),
if you have not run `atoo init` before.

## When the install fails

**`error: externally-managed-environment`.** You ran `pip install`
outside the virtualenv. Activate it (step 1) and install again. Do not
use `--break-system-packages`.

**`atoo: command not found`, or the wrong `atoo` runs.** The virtualenv
is not active in this terminal: [step 3](#3-which-atoo-am-i-running) says
how to tell, and the fix.

**`the web UI needs the 'ui' extra` from `atoo ui`.** Either the clone was
installed without `[ui]`, or the `atoo` that ran is not the clone's. Check
[step 3](#3-which-atoo-am-i-running) first, then, with the virtualenv
active, run `python3 -m pip install -e ".[ui]"` again in the clone. The
message itself says which of these you need: outside a virtualenv it gives
the steps to make one (the `pip install` alone would fail there), and
inside one, just the `pip install`.

## See also

- [Installing Atoo](install.md)
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
