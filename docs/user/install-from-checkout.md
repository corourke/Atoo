# Installing from a checkout

The [pipx install](install.md) is all most people need. This page is for
running Atoo from a clone of its repository instead: into a virtualenv,
a private directory of packages with its own `python3` and `atoo`
commands. Installing into it cannot disturb the system Python, and a bad
install is `rm -rf .venv` away from gone.

`venv` is in the standard library. Only Debian and Ubuntu split it out,
as `apt install python3-venv`.

This needs Python 3.11 or newer: [step 3 of Installing
Atoo](install.md#3-python-311-or-newer) gets one with Homebrew, and
[Installing without Homebrew](install-without-homebrew.md) without.

```bash
git clone https://github.com/corourke/Atoo.git
cd Atoo
python3.12 -m venv .venv           # name the interpreter explicitly
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install '.[ui]'
```

`[ui]` brings the browser UI, `atoo ui`. Without it, the commands that
build, apply and watch a show still work; `atoo ui` says the extra is
missing.

Your prompt gains a `(.venv)` prefix. **Activation is per terminal**: a
new window, tab, or reboot starts outside it, and the `source` line is
what puts you back. `deactivate` leaves it.

Use `python3 -m pip`, not a bare `pip`: stock macOS has no `pip` command
at all, while `python3 -m pip` always reaches the pip belonging to
whichever `python3` you just ran.

To update, pull and install again, with the virtualenv active:

```bash
git pull
python3 -m pip install '.[ui]'
```

Then carry on from [First run](install.md#6-first-run-atoo-init-then-atoo-ui).

## When the install fails

**`atoo: command not found` after a successful install.** It
installed into whichever Python `python3 -m pip` resolved to, and the
`atoo` command lands in *that* environment's script directory. A
different terminal or a deactivated virtualenv misses it even though the
install succeeded.

```bash
python3 -m pip show atoo      # says exactly which Python has it
python3 -m atoo.cli --help    # always works: no entry point, no PATH
```

If `which atoo` resolves anywhere outside `.venv`, the virtualenv is
not active.

**`the web UI needs the 'ui' extra` from `atoo ui`.** It was installed
without `[ui]`. With the virtualenv active, run
`python3 -m pip install '.[ui]'` again from the repository root.

## See also

- [Installing Atoo](install.md)
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
