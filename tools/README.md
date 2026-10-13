# Tools

Build tooling for the actual product: scripts a developer runs by hand.

## `build_parameter_map.py`

Turns a walk of a console's parameter tree into the parameter map -- a
schema keyed by address template (`ch.{n}.fdr`, not forty separate
`ch.1.fdr`...`ch.40.fdr` entries) with type, range, enum, and unit parsed
out of the `?`-mode description text.

```
python3 tools/build_parameter_map.py wing_params_20260908.json \
    --out docs/reference/wing-compact-parameter-map
```

Writes `<out>.json` (machine-readable schema) and `<out>.md` (counts,
categories, and every template where different instances of the same
collection disagreed on structure). See the script's own docstring for
what it does and doesn't do — in particular, category tags (`show` vs.
`surface-ui` vs. ...) are a first-pass guess, not a reviewed scoping
decision, and nothing is dropped from the output regardless of category.


## `build_demo_show.py`

Rebuilds the demo show's `plan.json` (`starter/demo-show/`) with no model. The generator's reply is hand-written in
[`demo_show.reply.json`](demo_show.reply.json); the script plays it back
through `atoo build --show` in a scratch copy of `starter/`
(reading `starter/conventions.md`, `--no-resolve`, and
`--presets starter/presets` once that folder holds a `.chn`), runs
`atoo verify`, and copies back only `plan.json` -- and only when the
build succeeds and verify finds no error. It then writes the Demo
console's rig, `atoo/web/demo_states/before.json`, from that plan.
The hand-written `watch.json` is never touched.

```
python3 tools/build_demo_show.py
```

Run it after editing the demo's conventions (the starter's: one file,
`starter/conventions.md`), input
list, instructions, reply or presets, then run the suite: `tests/test_demo_show.py` checks the plan
verifies, is current against its inputs, and lines up with the Demo rig
(`atoo/web/demo_states/before.json`).

## `freeze_initialized_capture.py`

Freezes a model's initialized capture into package data for the reset a
full apply does first (`atoo/initialize.py`). `add`
copies the `.snap` an initialized desk exported to
`atoo/initialized/<model>.snap`; `types` rebuilds
`atoo/initialized/leaf_types.json` (every leaf template's OSC type
and list tokens) from the parameter map above.

```
python3 tools/freeze_initialized_capture.py add wing-rack path/to/A8-initialized.snap
python3 tools/freeze_initialized_capture.py types
```

After `add` for a new model, add the line it prints to
`initialize.CAPTURES`. To get the `.snap`: initialize the desk, then save
its show file from the desk or WING Edit.

## `doc_screenshots.py`

Retakes the user guide's screenshots in `docs/user/img/` from the
manifest `doc_screenshots.json`, so a UI change is followed by one
command rather than by hand-cropping:

```
python3 tools/doc_screenshots.py            # every shot
python3 tools/doc_screenshots.py demo-bar   # just the named ones
python3 tools/doc_screenshots.py --list
```

Headless Chromium from `/opt/pw-browsers/chromium`, dark scheme,
1440x900, the page clock fixed, and a throwaway `HOME` per show. The
shows are the packaged Demo show and the frozen
`docs/user/demo/touringband/`. Nothing reaches a console: Ping, preview,
apply, patch, undo and build requests are aborted in the browser, and
only the Demo rig may be watched. Each run rewrites
`docs/user/img/SHOTS.md` with the commit each shot was taken at.

The Watch table shot is skipped until the Demo rig can be seeded:
`webui.py`'s `demo_provider_factory` uses an unseeded `random.Random()`.
The script already passes `ATOO_DEMO_SEED=1` to the server, and
takes the shot once `webui.py` reads that variable.

## `scrub_check.py`

The public repository's scrub check, run on any tree before it is
carried over:

```
python3 tools/scrub_check.py                    # the whole repository
python3 tools/scrub_check.py tests/fixtures     # one directory or file
python3 tools/scrub_check.py --category serial  # one category (repeatable)
```

Each hit prints as `path:line: category: matched text`, followed by a count
per top-level directory, and the exit status is 1 when anything was found.
The categories:

| Category | What it finds |
|---|---|
| `home-path` | `/Users/<name>`, `C:\Users\<name>`, or a `/home/<name>` other than a placeholder (`user`, `you`, `me`, `username`) |
| `name` | the maintainer's first name, except on a copyright or credit line (`Copyright`, `©`, `authors =`, a credit, the Act4Audio footer) |
| `private-ip` | 10/8, 172.16/12 and 192.168/16 addresses. Documentation addresses (192.0.2.x) are the replacement and pass |
| `serial` | a desk serial (four digits, three letters or digits, four digits, three letters), a hardware-derived desk name (`WING-PP-<digits>`), a `creator_sn` that is not a placeholder |
| `deny-name` | a band, venue, client or person's name from `scrub_denylist.txt`: one per line, `#` comments, matched as whole words without regard to case |
| `chn` | every `.chn` channel preset, once per file: only the replacement set goes public |

Binary files are searched byte for byte. `scrub_denylist.txt` lists the
names that were scrubbed, so the check never reports on it, and it stays in
the private repository; without it the `deny-name` category is skipped with
a warning. `tests/test_scrub_check.py` plants one hit of each kind.

