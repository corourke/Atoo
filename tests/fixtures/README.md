# `tests/fixtures/`

Everything the test suite reads lives here. Nothing under `examples/` is a
fixture: the show bundles there are rebuilt between shows, and the desk
captures, presets and demo files are the maintainer's working material.
`tests/conftest.py` refuses any read of `examples/` from a test that is not
marked `example_guard` (CLAUDE.md, "A bundle under `examples/` is a living
example, not a test fixture").

A test that needs a file which also lives in `examples/` reads a **frozen
copy** here. A copy is not kept in step with its original. If the original
changes, the copy stays as it is, and the tests go on asserting against the
bytes they were written for. To refresh a copy on purpose, copy the new
bytes, fix whichever assertions change, and update the entry below.

## Scrubbed for the public repository (2026-10-11)

Every fixture here was put through the manifest's scrub check
(`docs/product/public-repo-manifest.md`), and `python3 tools/scrub_check.py
tests/fixtures` is clean (the `.chn` files here are the maintainer's own
set, which the check allows). A copy refreshed from `examples/` is scrubbed the same way before
it is committed. What changed, so a test still means what it meant:

- **Names.** The band, its members and the one named person in the
  church capture have neutral names. The band is `sixpiece` (files and
  text alike, so `examples/sixpiece/...` below names that band's bundle by
  its neutral name), and `touringband.md`'s source show file is
  `TOURING_260821_MIX.snap`. Channel names (Kick, Vocal 1, Bass DI) are
  unchanged: they are what the tests are about.
- **Home paths** are `/home/user/show/...`.
- **Desk addresses** are documentation addresses (RFC 5737): the Compact
  is `192.0.2.16`, the full-size `192.0.2.148`.
- **Serials.** The Compact states `SERIAL00000001` and is named
  `WING-PP-SERIAL01`; the full-size states `SERIAL00000002`. Each is the
  same in every file of a capture -- the identity string, the journals'
  `desk` blocks and journal ids, and the hex of the raw log's `/?` reply,
  where every replacement is the same length so the OSC padding is
  unchanged. `atoo/initialized/wing-compact.snap` took the same
  `creator_name`, so it is still byte for byte `Initialized-Compact.snap`.
- **Presets.** The commercial `.chn` presets that were here are gone
  (see "The maintainer's own presets" below). His own carry
  `creator_name` `WING-PP-SERIAL01` too.

## The maintainer's own presets (2026-10-12)

Frozen copies of `starter/presets/` at the commit that adopted
it (517ff1e, with `creator_name` scrubbed to `WING-PP-SERIAL01`), so a
later re-export of the starter set does not move the tests. All are
`chpreset.11` exports from WING-EDIT 3.3.1.

| Copy | What | Read by |
|---|---|---|
| `channel_presets/` | all 19 `.chn`, the two FX bus presets (`FX Vox Verb.bus`, `FX Snare Verb.bus`) and the mix bus preset (`Mix Bus.bus`, copied from `starter/presets/` 2026-10-13) | `test_cli.py` (`atoo presets`, the bus-preset note), `test_presets.py` (a `.bus` is not read as a channel preset), `test_preset_expand.py` (Speech on an aux; every fixture preset's leaves have a type), `test_mix_bus_presets.py` (a bus preset with no effect, on a mix bus) |
| `presets/` | five of them: `Kick.chn` (saved as **Kick In**), `Snare.chn`, `H Tom.chn`, `Fl Tom.chn`, `Piano.chn` | `test_presets.py`, `test_preset_expand.py`, `test_preset_resolution.py`, `test_input_list_preset.py`, `test_cli.py` |

They replace the commercial exports that were here (`presets/` five
`chpreset.8` files, `presets_v11/kick_wing_edit_v11.chn`, and twelve in
`channel_presets/`). Tests that named those presets now name these;
the `chpreset.8` shape is built in `test_presets.py` from the Kick.
`preset-test.plan.json` names presets from this set too (`kick-in`,
`KEYS`, `vocal`, `Perc`, and two that are deliberately not in it,
`Snare Top` and `Kick (In)`).

## Frozen copies of `examples/` (2026-09-29)

These are byte-for-byte copies (until the scrub above) of `examples/` at `origin/main` 1ff4317,
taken when the guard was extended from `examples/touringband/` to all of
`examples/` (`examples/smallband/` is a living example too, and
the tests still assert on its contents). Each keeps its path relative to
`examples/`, except where noted.

| Copy | Original | Read by |
|---|---|---|
| `smallband.plan.json` | `examples/smallband/plan.json` | `test_amend.py` (the offline `amend` CLI walkthrough, stage 4) |
| `amend-demo/rebuilt.plan.json`, `rebuilt-minus-bgvox.plan.json`, `occupancy.json`, `occupancy-bgvox-taken-over.json` | `examples/amend-demo/` | `test_amend.py` |
| `examples-conventions.md` | `examples/conventions.md` | `test_prompts.py` (the prompt must not quote it) |
| `touringband.generated.plan.json` | `experiments/generator/touringband.generated.plan.json`, copied 2026-10-13 (the public tree carries no `experiments/`) | `test_plan_schema.py`, `test_generate_and_verify_cli.py`, `test_role_effort.py`, `test_patch_rename.py` (a real model reply, from before the `socket` rename) |
| `Initialized-Full.snap` | `examples/Initialized-Full.snap` | `test_audit_in_use.py` |
| `console-runs/Initialized-Compact.snap` | `examples/console-runs/` | `test_alternate_input_plan.py`, `test_apply.py`, `test_audit_alternate_input.py`, `test_audit_effects.py`, `test_audit_in_use.py`, `test_audit_talkback.py` |
| `console-runs/Church-Full.snap` | `examples/console-runs/` | `test_alternate_input_plan.py` |
| `console-runs/2026-09-21/A1-raw.log`, `A7-with-AES-alt.txt` | `archive/examples/console-runs/2026-09-21/` | `test_readback_index_base.py` |
| `console-runs/2026-09-21/A7-ch1-with-WLIVE-alt.snap` | `archive/examples/console-runs/2026-09-21/` | `test_alternate_input_plan.py`, `test_audit_alternate_input.py`, `test_readback_index_base.py` |
| `console-runs/2026-09-21/A7-no-alts.txt`, `A7-with-WLIVE-alt.txt` | `archive/examples/console-runs/2026-09-21/` | `test_audit_alternate_input.py` |
| `console-runs/2026-09-21-2100/A1-apply-journal.json` | `archive/examples/console-runs/2026-09-21-2100/` | `test_undo.py` |
| `console-runs/2026-09-22-2008/A11-read-speed.json` | `archive/examples/console-runs/2026-09-22-2008/` | `test_watch_scope.py` |
| `console-runs/2026-09-22-2136/A1-apply-journal.json` | `archive/examples/console-runs/2026-09-22-2136/` | `test_undo.py` |
| `console-runs/2026-09-22-2139/A13-board-with-podium.snap` | `archive/examples/console-runs/2026-09-22-2139/` | `test_amend.py`, `test_audit_in_use.py` |
| `console-runs/2026-09-22-2139/A13-occupancy.json` | `archive/examples/console-runs/2026-09-22-2139/` | `test_amend.py` |
| `console-runs/2026-09-23-1921/A17-wing-full.json` | `archive/examples/console-runs/2026-09-23-1921/` | `test_console_model.py` |
| `console-runs/2026-09-23-1921/A17-wing-full.snap` | `archive/examples/console-runs/2026-09-23-1921/` | `test_alternate_input_plan.py`, `test_audit_effects.py`, `test_audit_stale_strip_name.py`, `test_audit_talkback.py` |
| `console-runs/2026-10-02-sixpiece-apply-excerpt.json` | an EXCERPT of `examples/sixpiece/journals/20261002T234240.710613Z-apply-SERIAL00000001.json` (the maintainer's first full apply on the Compact, 4,583 writes), copied 2026-10-05 at `origin/main` bef79bd: every mismatch row, every `/bus/{n}/busmono` and `/bus/{n}/wid` row, and aux 2's `dyn/mdl` and `dynsc` rows, unchanged, each with its `index` in the journal | `test_initialize.py` and `test_preset_expand.py` (a mono bus's width reads back 0; an aux's tap written `IN` reads back `BUS`) |
| `console-runs/session-2026-09-23-0928/A15-rebuilt-minus-ch18.plan.json` | `archive/examples/console-runs/session-2026-09-23-0928/` | `test_amend.py` |
| `touringband.watch.json` | `examples/touringband/watch.json`, copied 2026-10-01 at `origin/main` c984173 | `test_watch_scoped_names.py` (its `"channel": "Main"`, refused from an earlier change until bare `Main` was read as `MAIN 1`) |
| `sixpiece_2026-10-11.plan.json` | `examples/sixpiece/plan.json` (the 2026-10-02 build), copied 2026-10-12, home paths replaced (the plan the maintainer watched his Compact with on 2026-10-12) | `test_watch_desk_drift.py` (monitor busses on AES50, a phones Matrix, a Kick out of its busses, a muted Vocals bus) |
| `sixpiece_2026-10-02.plan.json` | `examples/sixpiece/plan.json`, copied 2026-10-02 at `origin/main` 89f2baa (the maintainer's sixpiece build whose ch 24 read MUSIC) | `test_full_apply.py` (a full apply unpatches ch 24-40 and the unused auxes, and sets talkback's assign to AUX8 for aux 8 TALKBACK) |
| `sixpiece_2026-10-01.plan.json` | `examples/sixpiece/plan.json`, copied 2026-10-02 at `origin/main` 028ae10 (the maintainer's rebuild of 2026-10-01) | `test_findings_dock.py` (a real findings load -- 36 build INFOs, 10 verify findings, 10 critic findings -- for the dock's one-place, no-duplicates and INFO-grouping checks) |
| `console-runs/2026-09-28-1904/A22-apply-journal.json` | `examples/console-runs/2026-09-28-1904/`, copied 2026-09-29 at `origin/main` 59d0a66 | `test_selector_dependent.py` (a journal from before the fix, whose `in/set/dly` was skipped under a changed `dlymode`) |
| `preset-test.plan.json` | `examples/preset-test.plan.json`, copied 2026-10-11 at `origin/main` c82d729, when the original was archived at `archive/examples/preset-test.plan.json` | no test: the worked examples in `docs/user/presets.md` and `docs/reference/console-session-checklist.md` section B run on it (touringband with a preset named on six channels, each a matching case) |

The originals stay in `examples/`, because the docs' worked examples, the
desk scripts under `examples/console-runs/` or the code's own comments use
them. No file in `examples/` was used by the tests alone, so none was moved.
The exception is the early desk runs, `console-runs/2026-09-21*` to
`2026-09-23*` and the two `session-2026-09-23-*` sessions, whose
originals were archived on 2026-10-11 under
`archive/examples/console-runs/`; the copies here are
unchanged.

The `example_guard` tests (`python3 -m pytest -m example_guard`) are the only
ones that still read `examples/`. They check that the shipped examples are
valid, for example that the bundles verify and the amend walkthrough runs.
They never check what the examples contain.

## Fixtures that were always here

These fixtures were never copies of a living file. Each test that reads one
says in its own docstring what the fixture is for.

- `smallband.*`, `fullband.*`, `festival.*`, `touringband.csv`,
  `touringband.md`: input lists and conventions for four real shows (see
  `docs/developer/modules.md`, "Test fixtures").
- `real_plans.json`, `compiled_plans.json`, `touringband.plan.json`: plans
  from the deterministic compiler, generated just before an earlier change deleted
  it.
- `applied-show.plan.json`: the touring-band plan as
  `examples/touringband/plan.json` held it on 2026-09-23, just before that
  bundle was rebuilt. It is the applied show in `test_amend.py`.
- `touringband-2026-09-18.apply-journal.json`: the journal from the
  2026-09-18 touringband apply on a real desk.
- `audit_demo_*.json`, `sample.snap`, `sample.watch.json`: console states,
  a snapshot and a watchlist used by the audit, watch and snapshot tests.
- `presets/`, `channel_presets/`: the maintainer's own presets (next
  section).
- `festival_2026-09-29.plan.json`: `examples/festival/plan.json` as
  the maintainer's Sonnet 5 build of 2026-09-29 wrote it, every unity send to a
  mix or FX bus `level_db: null` (`test_send_levels_and_reply_repair.py`).
- `haiku45_smallband_2026-09-29.reply.json`: that day's failed Haiku 4.5
  smallband reply, from `examples/smallband/plan.partial.json`; its input
  list is `haiku45_smallband.csv`.
- `haiku45_sixpiece_2026-09-29.reply.json`: that day's failed Haiku 4.5
  sixpiece reply, from `examples/sixpiece/plan.partial.json`: a category
  given no colour, and a marker for a field a Matrix cannot carry.
- `haiku45_sixpiece_2026-09-29_fixup.reply.json`: the fix-up reply of
  Haiku 4.5's second sixpiece build that day (commit 4492816), from
  `examples/sixpiece/plan.partial.json` -- which was written part-expanded,
  so its name-keyed `busses`/`outputs`/`dcas`/`mute_groups` maps are turned
  back into the arrays the model wrote. Its Talkback quote carries an
  "Instructions:" label and drops "Setup"; the first reply is rebuilt from
  it in the test with its two format slips put back
  (`test_sixpiece_round2.py`).
- `haiku45_festival_dangling_dca.reply.json` and `.csv`: three channels
  (Kick, BassDI, VOX 1) of Haiku 4.5's festival build of 2026-09-29
  (`git show 2897232:examples/festival/plan.json`), rewritten as a
  compact reply with sends left out. BassDI joins DCA 'Band', which the
  plan never declares -- verify's `reference.dangling`, as in the real
  build (`test_fixup_round.py`).
- `sixpiece_2026-09-29.csv`, `sixpiece_instructions_2026-09-29.md`,
  `sixpiece_conventions_2026-09-29.md`: `examples/sixpiece/input.csv`,
  its `instructions.md` and `examples/conventions.md` as that day's
  Haiku sixpiece build read them (the conventions' sha256 matches the
  build log) -- the texts the Talkback quote is checked against
  (`test_instructed_channels.py`).
- `haiku45_festival_2026-09-29.csv`: `examples/festival/input.csv` as
  Haiku's festival build of 2026-09-29 read it (commit 2897232), whose 14
  "not patched for this event" rows the reply left out
  (`test_every_row_built.py`).
- `conventions_2026-09-30.resolved-body.md`: the body of
  `examples/conventions.resolved.md` as the maintainer's Sonnet-high resolve
  wrote it on 2026-09-30 (header and title line removed), with a
  `## Category table` written by hand after it, restating its
  Categories section (Keys, Strings, Horns and Tracks leave
  `main_direct` out, as the prose makes it depend on the show)
  (`test_category_table.py`).
- `conventions_2026-10-01.md`, `conventions_2026-10-01.resolved.md`,
  `sixpiece_2026-10-01.csv`, `sixpiece_instructions_2026-10-01.md`:
  byte-for-byte copies (until the scrub above) of `examples/conventions.md`,
  `examples/conventions.resolved.md`, `examples/sixpiece/input.csv` and
  its `instructions.md` at commit c04dd25 -- the maintainer's sixpiece build of
  2026-10-01, whose generator dropped the conventions' Aux 1 MUSIC, Aux 2
  HOST and Aux 8 TALKBACK (`test_instructed_strips.py`).
- `conventions_2026-10-01_strips.resolved.md`: that resolved file with a
  `## Instructed strips` block written by hand after it -- the block the
  resolve prompt asks for since 2026-10-01, restating its Misc section's
  three aux strips (MUSIC's `stereo` left null, so code decides it from
  "23-24") (`test_instructed_strips.py`).
- `sixpiece_2026-10-01.reply.json`: sixpiece's reply at c04dd25,
  RECONSTRUCTED from `examples/sixpiece/plan.json` (the raw reply was
  not kept): each channel as its input-list row with the socket group,
  processing (no preset values), fader, DCA, mute group and Main routes
  the plan has; busses with their senders grouped by mode and level; the
  model's own notes. It expands back to that plan's 23 channels, with no
  aux strip (`test_instructed_strips.py`).
- `haiku45_*`, `lessons_thinking.build-log.json`, `setup_viewer.plan.json`,
  `bus_width.*`, `a18-full-size-unanswered.json`, and the rest: model
  replies, build logs and plans captured for a single regression each.

## The Demo show

`starter/demo-show/` is shipped, not a fixture (an earlier change replaced the
7-channel show with the sample show), so a test that needs the OLD
Demo's contents reads a frozen copy, and a test whose subject is the
shipped Demo (`test_demo_show.py`) asserts only what it promises.

- `old-demo-rig/before.json`: the 7-channel Demo rig
  (`atoo/web/demo_states/before.json` at `origin/main`), for `test_webui_watch.py`'s scoped-name resolution, which
  needs a bus named Drums at BUS 1.
- `demo-horns.change-set.json`: the change set for the Demo's 6pm
  change, *"trumpet, sax and trombone on LCL 21-23, Band DCA"*, written
  by hand in the shape `patch --save-change-set` writes, so
  `test_demo_show.py` can review it against the Demo rig with no model.
  Since 2026-10-13 the horns take their starter presets and land on a
  new Horns mix bus with the "Mix Bus" bus preset (the maintainer's desk test 13).
  `docs/user/demo/demo-show/horns.change-set.json` is the same file, for
  `patch.md`'s transcript; a test keeps the two equal.
- `demo_2026-10-13/`: the maintainer's real-model rebuild of the Demo
  (commit d89acf7), frozen for `test_quiet_build.py`: the
  `conventions.md`, `demo-show/input.csv` and `demo-show/instructions.md`
  he built from, the `conventions.resolved.md` his resolve call wrote
  (169 citations), and `generator.reply.json`, the generator's reply
  recovered from his plan by `tools/demo_reply_from_plan.py`. The test
  replays that build with no model and asserts the Findings dock reads 0
  to check and 4 choices.
- `preset_map_2026-10-13/`: the maintainer's real-model build of a copy
  of `starter/` on 2026-10-13 (Resolve: preset-map lines in
  the conventions come back as resolve.line-not-covered notes): the
  `conventions.md` he built from (before the starter's Keyboards, T Sax
  and Generic sax edits and the rename) and the `conventions.resolved.md`
  his resolve call wrote, which cites ten of the preset map's lines by
  no rule. Unchanged but for the product's old name, which became Atoo
  in the resolved file's header and one conventions comment (so a release carries no old name). Read by
  `test_preset_map_coverage.py`, with `channel_presets/` as the library
  (byte for byte the `presets/` of his bundle).
- `watchlist_draft_extra_key.json`: a watchlist draft whose first
  condition carries an `index` key no condition has, as the Demo's real
  draft did, and whose third names a field outside the vocabulary, for
  `test_watchlist_draft.py`.
- `rebuild_diff/previous.plan.json` and `rebuild_diff/current.plan.json`:
  the packaged Demo show built from `tools/demo_show.reply.json` with no
  model, then rebuilt after one edit -- the `Guest Vox` row un-skipped in
  `input.csv` and named in instructions.md's Vox Wedge line -- with that
  reply edited to add Guest Vox and, unasked, to raise the Bass DI's gain
  from 20 to 26 dB. Both carry `meta.change_basis`; the
  second carries `meta.changes_since_previous`. Scratch paths are spelled
  `starter/...`, and `meta.build_log_file` is dropped. For
  `test_plan_diff.py`: an asked-for change, one nobody asked for, and a
  renumbered strip (Playback, CH 13 -> CH 14).
- `rebuild_diff/demo/`: the Demo inputs that run was built from, frozen
  from `starter/` and `tools/demo_show.reply.json` on 2026-10-13
  (`conventions.md`, `input.csv`, `instructions.md`, `reply.json`), and
  the edit as files (`input.after.csv`, `instructions.after.md`,
  `reply.after.json`), so `test_plan_diff.py`'s end-to-end build does not
  depend on the shipped Demo's text.
