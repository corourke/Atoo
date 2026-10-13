---
title: "Installing from a checkout"
description: "To change the code or run the tests, install from a clone of the repository into a virtualenv. To use Atoo, the pipx install is all you need. A virtualenv is a private directory of packages with its…"
sidebar: 
  order: 7
---

<!-- Generated from docs/user/install-from-checkout.md by tools/docs_to_starlight.py in the development repository. Edit it there. -->
To change the code or run the tests, install from a clone of the
repository into a virtualenv. To use Atoo, the
[pipx install](/getting-started/install/) is all you need. A virtualenv is a private
directory of packages with its own `python3` and `atoo` commands.
Installing into it cannot disturb the system Python, and a bad install
is `rm -rf .venv` away from gone.

`venv` is in the standard library. Only Debian and Ubuntu split it out,
as `apt install python3-venv`.

```bash
git clone https://github.com/corourke/Atoo.git
cd Atoo
python3.12 -m venv .venv           # name the interpreter explicitly
source .venv/bin/activate
python3 -m pip install --upgrade pip    # editable installs need pip >= 21.3
python3 -m pip install -e '.[ui]'
```

Your prompt gains a `(.venv)` prefix. **Activation is per terminal** — a
new window, tab, or reboot starts outside it, and the `source` line is
what puts you back. `deactivate` leaves it. `.venv/` is not committed.

`-e` is an *editable* install: the package is a link to this source tree
rather than a copy, so **a change under `atoo/` takes effect on the
next `atoo` command, with no reinstall.** Re-run it only when
`pyproject.toml` itself changes.

Use `python3 -m pip`, not a bare `pip`: stock macOS has no `pip` command
at all, while `python3 -m pip` always reaches the pip belonging to
whichever `python3` you just ran.

pipx installs straight from a checkout too, if you want the command
everywhere without activating anything: `pipx install --editable
'.[ui]'` from the repository root.

An editable install reads the starter set -- what `atoo init`
copies, and the Demo show the UI opens -- from this checkout's own
`starter/`. A checkout from before that folder moved there may still
have a `atoo/starter/` folder, kept by files git does not track
(a `.DS_Store`, say). Atoo passes it over, and it is safe to delete.

## The extras

Two optional extras, neither needed to build or apply a plan:

| Extra | Install | What it is for |
|---|---|---|
| `ui` | `python3 -m pip install -e '.[ui]'` | `atoo ui`, the browser UI — FastAPI, uvicorn, websockets |
| `test` | `python3 -m pip install -e '.[test]'` | running the test suite — pytest, jsonschema |

Both together, which is what a contributor wants:

```bash
python3 -m pip install -e '.[test,ui]'
python3 -m pytest -q
```

Expect a fully green run with nothing skipped.

> **If a handful of web-UI tests skip, install `httpx2`.** FastAPI's
> `TestClient` is built on Starlette's, which needs an HTTP client, and
> current Starlette asks for `httpx2` by name — but it is in neither
> extra, so `[test,ui]` alone does not bring it. `python3 -m pip install
> httpx2` and they run. An older Starlette that wants plain `httpx` says
> so — install whichever it names.

The engine itself never uses `httpx2`, `httpx`, or anything else on that
list. `atoo build`, `verify`, `compare`, `apply`, `audit` and
`watch` run on the standard library alone.

## Upgrading Python on macOS

The 3.9 at `/usr/bin/python3` belongs to Apple's Command Line Tools.
**Leave it alone** — parts of the system use it. Install a newer Python
alongside it; they coexist by version-suffixed name (`python3.12` vs
`python3.9`).

*With Homebrew* (`brew --version` to check; if missing, get it from
[brew.sh](https://brew.sh)):

```bash
brew install python@3.12
python3.12 --version         # confirm it is on PATH
```

If `python3.12: command not found` right after a successful install, the
Homebrew prefix is not on your `PATH`. On Apple Silicon that is
`/opt/homebrew/bin`, on Intel `/usr/local/bin`:

```bash
echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zshrc && exec zsh
```

*Without Homebrew*: the installer from
[python.org/downloads](https://www.python.org/downloads/) puts
`python3.12` in `/usr/local/bin` and needs no package manager.

## When the install fails

**"editable mode currently requires a setuptools-based build" / "File
setup.py or setup.cfg not found"**, from a checkout. A pip *version* problem, not a real
error. Installing straight from `pyproject.toml` with no `setup.py`
(PEP 660) needs pip >= 21.3; anything older — the pip shipped with
macOS's Command Line Tools Python is commonly 21.2.x — falls back to
legacy editable installs, which do require a `setup.py`, and this project
deliberately has none. Fix it once:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

**`atoo: command not found` after a successful install.** It
installed into whichever Python `python3 -m pip` resolved to, and the
`atoo` command lands in *that* environment's script directory. A
different terminal or a deactivated venv misses it even though the
install succeeded.

```bash
python3 -m pip show atoo      # says exactly which Python has it
python3 -m atoo.cli --help    # always works: no entry point, no PATH
```

If `which atoo` resolves anywhere outside `.venv`, the virtualenv is
not active.

On Python 3.9 or 3.10, the TOML backport gives you `~/.atoo.config`
without upgrading: `python3 -m pip install tomli`.

## See also

- [Installing Atoo](/getting-started/install/)
- `CONTRIBUTING.md`
