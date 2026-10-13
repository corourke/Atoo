# The `atoo` package

The code itself, for someone who wants to change it. To use the tool,
start with the [user guide](../docs/user/README.md).

## Set up a working copy

```bash
python3 -m pip install -e '.[test,ui]'
python3 -m pytest -q
```

[Installing Atoo](../docs/user/install.md) covers Python versions,
the virtualenv, the two extras, and the failures that actually happen.
Two things it does not say, because they are about working on the code:

- `-e` installs a link to this source tree, so **an edit under
  `atoo/` takes effect on the next `atoo` command**, with no
  reinstall. Re-run the install only when `pyproject.toml` changes.
- **The engine has no dependencies.** Every model provider is plain HTTP
  through `urllib`, and only `atoo ui` needs third-party packages,
  behind the `ui` extra. Keep it that way: a venue laptop installs this
  and nothing else.

## Where things are

| Path | What it holds |
|---|---|
| `atoo/cli.py` | every `atoo` command and its flags; [`cli-reference.md`](../docs/user/cli-reference.md) is generated from it |
| `atoo/generate.py`, `prompts/`, `domain/knowledge.md` | the build: the model call that drafts a plan, its prompts, and the audio domain knowledge it reads |
| `atoo/verify_plan.py`, `plan_schema.py`, `console_facts.py` | the checks a plan must pass, and what each WING model has |
| `atoo/apply.py`, `undo.py`, `patch.py`, `amend.py` | writing to a desk, reading it back, and the journal |
| `atoo/audit.py`, `watch.py`, `watch_conditions.py` | reading a desk and checking it, once or on a loop |
| `atoo/webui.py`, `web/static/` | `atoo ui`: the server and the browser pages |
| `starter/` (packaged as `atoo.starter`), `atoo/initialized/` | the starter set -- the conventions and preset library `atoo init` copies, and the Demo show (`starter/demo-show/`) -- and each model's initialized-desk capture |
| `tests/` | the suite; `tests/fixtures/README.md` lists every frozen fixture and where it came from |
| `tools/` | scripts for maintainers: the CLI reference generator, the screenshot harness, capture tools |

## Tests

```bash
python3 -m pytest -q
```

Two groups stand aside from an ordinary run:

- **`example_guard`** tests have a file under `examples/` as their
  subject. Nothing else may read `examples/`: those are working show
  files, rebuilt between shows, and `tests/conftest.py` refuses the read.
  A test that needs a show uses a frozen copy under `tests/fixtures/`.
  `-m "not example_guard"` skips them while you edit `examples/`.
- **`live_model`** tests call a real model and cost real money, so both
  switches are needed:

  ```bash
  ATOO_LIVE_MODEL_TESTS=1 ATOO_AI_PROVIDER=claude \
      ATOO_AI_API_KEY=... python3 -m pytest -m live_model
  ```

  Point them at the cheapest, weakest model you have. They ask whether a
  prompt says what it means, and a strong model papers over ambiguity.

**The suite cannot see the browser.** A renamed field that a page in
`web/static/` still reads shows as a blank element, not a failure. Open
the page (`atoo ui`), and add an assertion over the served asset in
`tests/test_webui.py`.

Two working rules come before any change. A setting the desk cannot
take (a socket that does not exist, a value out of range) is an error;
a judgement call (mono or stereo, a colour, an abbreviation) is made
and announced as an INFO finding, never left unset. And backwards
compatibility is not a goal: when a change makes an old file stop
working, change the file, not the code.
