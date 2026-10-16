# Troubleshooting: the browser UI

`atoo ui` will not start, or its page is blank, stale or read-only.

A healthy start prints where to point a browser and then sits there:

```text
$ atoo ui --plan touringband/plan.json
atoo 0.2.0 (installed copy at ~/.local/pipx/venvs/atoo/lib/python3.12/site-packages/atoo)
Atoo: http://127.0.0.1:8420 -- Build, Apply and Watch (Ctrl-C to stop)
Session-based: closing this stops whatever it was watching, and nothing is kept between runs.
Watch and Build never write to a console. The shell's Apply mode is the one screen that does, and only with Arm ticked.
Plan: touringband/plan.json -- on Build step 04
Console: none configured -- set one in the bundle bar (Change…) before Ping, Apply or a live Watch.
Working folder: ~/Documents/Atoo -- Open… and New show… start here.
```

The first line says which copy of Atoo this is ([`atoo --version`](install-from-checkout.md#3-which-atoo-am-i-running)
prints the same), and the page repeats it at the bottom. One URL, and it is the whole UI: Build, Apply and Watch are three modes
of the one page at `/`. The `Plan:` line appears only with `--plan` (or
`--show` on a bundle that has a `plan.json`); the plan is on Build step
04, which can also open one from a path. The `Console:` line is always
there: with a console configured it names the address and where it came
from (`--console`, `ATOO_CONSOLE` or `~/.atoo.config`), and the
bundle bar's **Change…** sets another without a restart. The
`Working folder:` line is the folder [`atoo init`](install.md#6-first-run-atoo-init-then-atoo-ui)
made; before `init` it says there is none, and how to make one.

### It exits immediately

Three causes, and each names itself:

**`the web UI needs the 'ui' extra`** — the server is an optional
dependency, so the engine installs without FastAPI and uvicorn. Exits
`1`. The message names the fix for where Atoo is running:

- **A clone, outside a virtualenv** (Homebrew's Python, on a Mac): it
  gives the four steps, `cd` into the clone, `python3 -m venv .venv`,
  `source .venv/bin/activate`, `python3 -m pip install -e ".[ui]"`. Run
  them in that order. A `pip install` on its own is refused there with
  `error: externally-managed-environment`; never work round it with
  `--break-system-packages`.
- **A clone, inside its virtualenv**: just `python3 -m pip install -e
  ".[ui]"`.
- **The pipx install**: `pipx install --force "atoo[ui] @
  git+https://github.com/corourke/Atoo.git"`
  ([Installing Atoo](install.md#when-it-does-not-work)).

From a clone, check first that the `atoo` that ran is the clone's
(`atoo --version`, [Which atoo am I
running?](install-from-checkout.md#3-which-atoo-am-i-running)); the
steps are in [Installing from a
checkout](install-from-checkout.md#1-make-the-virtualenv-in-the-clone).

**`couldn't read plan file 'x.json': No such file or directory`**, and
the same for `--watch-conditions` — both files are loaded before the
server binds anything, on purpose, so a typo fails in a tenth of a second
instead of after you have opened a browser. Exits `1`.

**`couldn't serve on 127.0.0.1:8420 -- Address already in use.`** —
another program has the port. The message tells you the way out, and
exits `1`:

```
$ atoo ui --port 8420
couldn't serve on 127.0.0.1:8420 -- Address already in use.
Something else is already using that port; try `atoo ui --port 8421`.
```

An earlier `atoo ui` still running on the port is not this
failure: a second one says `Atoo is already running at
http://127.0.0.1:8420/ -- open that page.`, opens it, and exits `0`. To
stop the first, press Ctrl-C in its terminal.

**No URL is printed when the server cannot start.** Atoo binds the
port before it announces anything, so an address on your screen is an
address that answers.

A bad `--host` fails in the same place and names itself the same way —
`couldn't serve on 203.0.113.254:8420 -- Cannot assign requested address.`
— without the "try another port" advice, because the port is not what is
wrong.

### The page loads but shows nothing

**Watch mode is empty until you start a watch.** It holds no state of
its own between runs — the session is the run — so a freshly opened page
with no console address typed in is doing exactly what it should.

**A few 404s in the browser's network tab are normal**, and none is a
fault: `/favicon.ico`, which the browser asks for unprompted;
`/api/watch-conditions`, which answers "nothing loaded" that way when no
watch-conditions file was given; and `/api/apply/preflight`, which
answers "no plan loaded" that way when no show is open.

**If a field or a panel is blank where you expected a value**, that is
worth reporting rather than working around. The page renders a missing
field as an empty string rather than complaining, so a blank element is the exact symptom of a plan field the page is
reading under a name the rest of the tool no longer uses. Say which
element, and which plan you opened.

### Build step 04 says Failed

Step 04's **Build plan** runs `atoo build --show` on the open bundle,
exactly as the command would from a terminal, and a build that writes no
plan ends **Failed** with a `build.failed` error in the Findings panel. The message
is the build's own last word on why, and the whole of what it said is in
the log on step 04. By far the commonest cause is that **a build needs a
model and cannot reach one**. With nothing configured, the Findings panel says:

```
The build did not produce a plan (exit 1): generation failed: a build needs a model: the default is Claude, which needs an API key in ANTHROPIC_API_KEY (or ATOO_AI_API_KEY) -- or set ATOO_AI_PROVIDER=ollama to use a local Ollama model instead
```

Set the key, or point `ATOO_AI_PROVIDER` at another backend (see
[`build` says "generation failed"](troubleshooting-build.md#build-says-generation-failed)) **in the shell
you start `atoo ui` from** — the page runs the build inside that
server process, with its environment. Restart the server after changing
it.

**Done, but the Findings panel is full of errors** is a different thing: the plan
was written (exit `2`), and verify found errors in it, which is what those
findings are. `atoo apply` will refuse it until they are fixed. Each
finding carries a jump link to the plan table's row it is about -- the
jump opens the row -- and one about your conventions text links to the
conventions or instructions editor, with the line it quotes selected.

**Build plan is refused outright** before anything runs when no console
model is chosen (a build will not guess which WING it is for), when no
bundle is open, when step 03 was pointed at an instructions file outside
the bundle — `atoo build` reads the bundle's own `instructions.md`
and nothing else, so the page will not build from a text it is not
showing — or when there is no house conventions file or no input list.
Those last two are only a to-do on their tiles until you press Build
plan; the refusal is what puts the ERROR (`build.no-conventions`,
`build.conventions-missing` or `build.input-list-missing`) in the Findings panel,
with a jump to the tile.

### The page says it is out of date

A red **This page is out of date** banner across every mode means the
`atoo ui` behind the tab was restarted, or another tab opened a
different show. Until you press **Reload page**, every button that writes
or runs is off, Watch's **Start watching** and **Save** included, so a
tab left open on one show cannot write another show's plan. It does not
reload by itself, so you can copy anything you had typed first.

### Write to console or Undo newest write stays locked

A locked button has no colour and a dashed edge. **Locked:** beside it
says why, and it is one of these:

- **Writing is switched off in the Demo show.** The Demo is read-only,
  on a simulated desk: Preview works, writing and Undo never do.
  Choosing a console address in the bar (**Change…**, then **Address**)
  leaves the Demo; then open or create a show of your own.
- **No console address**, or **No show bundle open**: set the one it
  names in the bar.
- **Nothing to undo on this desk**: History has no write standing on the
  console in the bar.
- **Preview first**, or **Step 1 or the console changed since the
  preview**: press **Preview** in step 2 again.
- **The pre-flight verify has N error(s)**: fix the plan on
  **Build** and rebuild, or, if you know why, tick **Skip the pre-flight
  verify** under **Options** in step 1.
- **Tick Arm first**: the **Arm** checkbox in step 3. It clears
  itself after each write, and Undo needs it too.
- **Preview the undo first**, or **Preview the undo again**: Undo is
  only offered for an undo you have just previewed. Press **Preview undo**
  on the newest row of History; do it again if a write, an undo, the
  console or the newest row has changed since.

### Another computer can open the page, but only to watch

`atoo ui --host <address>` lets a second machine on the venue
network open the page. That machine can watch, but it cannot build,
apply, patch, undo, save or browse this laptop's files: those answer
only the laptop the server runs on.

## See also

- [Troubleshooting](troubleshooting.md) — every symptom, and the page it is on
- [Build a show](build-a-show.md) — the browser's own task pages start here
