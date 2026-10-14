# Frozen copies for the user docs

These are copies of shipped example bundles, taken so that a transcript
in `docs/user/` stays true when the show under `examples/` is rebuilt.
The bundles under `examples/` are living show files and change with every
rebuild; nothing here does.

**The Demo show (`starter/demo-show/`) is the sample show for these
pages**. A transcript runs on it wherever it can; each copy
below stays only for something the Demo cannot show:

- `touringband/` -- a capture taken off a real desk after a real apply
  (the `compare` transcripts), a `watch.json` whose conditions fire
  against the hand-built audit states, a plan built from conventions that
  say `Magenta` (the colour-alias note), and the Build and Apply
  screenshots. The Demo has a simulated rig, not a `.snap`, and uses the
  desk's own colour words.
- `festival/` -- the `lessons` transcript reads a show's build logs. The
  Demo is built with no model, so it keeps none.
- `undo-demo/` -- the `undo` transcripts need a journal from a real
  apply. The Demo console never takes a write.
- `amend-demo/` -- the offline `amend` transcript needs an applied
  plan, a rebuild of it and a capture of a desk running it with somebody
  else's strip on it. The Demo has neither.
- `demo-show/` -- not a copy: the change set for the Demo's own 6pm
  change, for the offline `patch` transcript. A change set comes from a
  model, and the Demo is built with none, so this one is written by hand.
  The `patch` transcript runs on the Demo show itself, against the Demo
  console's rig (`atoo/web/demo_states/before.json`).
- The `audit`, `watch` and `watch-conditions` transcripts read a
  hand-built console state with faults seeded on purpose, and its fixed
  twin, because the Demo console's rig is clean and has nothing for those
  pages to find. They are not here: they ship with the package as
  `starter/audit-demo/`, which `atoo init` copies to
  `~/Documents/Atoo/audit-demo/`, so `audit --help` and
  `watch --help` can name them on a pipx install, which has no
  `docs/`.

`smallband/` was archived on 2026-10-11
(`archive/docs/user/demo/smallband/`): every transcript that ran on it
now runs on the Demo.

| Copy | Taken from | Used by |
|---|---|---|
| `touringband/plan.json`, `input.csv`, `instructions.md`, `watch.json` | `examples/touringband/` at 3b75d6b | `tools/doc_screenshots.py`, the Build and Apply screenshots in `img/`; `show-bundles.md`, the `verify`, `compare` and `watch` transcripts (`verify` is test-run); `conventions.md`, the unstated-width note; `conventions-reference.md`, the `Magenta` `verify` (test-run) |
| `touringband/console-after-apply.snap` | `examples/console-runs/session-2026-09-24-1045/touringband/` at ee189c9, with `creator_name` (the desk's network name) replaced by `WING` | `show-bundles.md` and `quickstart.md`, the `compare` transcripts |
| `conventions.md` | `tests/fixtures/sixpiece_conventions_2026-09-29.md` (the house conventions `touringband/plan.json` was built from; same sha256 the plan records) | `tools/doc_screenshots.py`, so the touringband shots read **PLAN CURRENT** |
| `undo-demo/apply-journal.json`, `undo-demo/after-apply.json` | `examples/undo-demo/` as it stood before 6367020 removed it from `examples/` | `undo.md`, the two `undo` transcripts (both test-run); `examples/README.md` stage 7 |
| `amend-demo/applied.plan.json`, `rebuilt.plan.json`, `occupancy.json` | `tests/fixtures/smallband.plan.json` and `tests/fixtures/amend-demo/` at 66e1461 (frozen copies of `examples/smallband/plan.json` and `examples/amend-demo/`) | `amend.md`, the offline `amend` transcript (test-run) |
| `demo-show/horns.change-set.json` | written by hand (2026-10-13) for *"trumpet, sax and trombone on LCL 21-23, Band DCA"* under the starter conventions: three horns with their starter presets, on a new Horns mix bus with the "Mix Bus" bus preset; the same file as `tests/fixtures/demo-horns.change-set.json` (a test keeps them equal) | `patch.md`, the offline `patch --change-set` transcript (test-run) |
| `festival/plan.json`, `festival/builds/` (the two newest) | `examples/festival/` at f906e3d | `lessons.md`, the `lessons` transcript (test-run) |

`tests/test_user_docs.py` runs every transcript whose command names a
file here and compares its output with the page, so a code change that
alters the output fails the suite. When that happens, re-run the command
and update the page. Refresh a copy from `examples/` only when the page
needs to show something the old copy cannot, and update this table.
