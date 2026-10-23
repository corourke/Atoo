# `tests/fixtures/`

Everything the test suite reads from disk lives here: input lists and
conventions, plans, model replies, build logs, console captures and
journals, and channel presets. Tests build small cases in the test itself
where they can; these are the ones that are too large or too real to build.

A fixture is **frozen**. If the file it was taken from changes, the fixture
stays as it is, and the tests go on asserting against the bytes they were
written for. To refresh one on purpose, copy the new bytes, fix whichever
assertions change, and update its entry below.

## Scrubbed

The plans, captures and journals come from real shows and real desks, and
every one was put through a scrub before it was committed:

- **Names.** The band, its members and the one named person in the church
  capture have neutral names. The band is `sixpiece`, in file names and
  text alike. The source show file of the touring-band lists is
  `TOURING_260821_MIX.snap`. Channel names (Kick, Vocal 1, Bass DI) are
  unchanged: they are what the tests are about.
- **Home paths** are `/home/user/show/...`.
- **Desk addresses** are documentation addresses (RFC 5737): the Compact is
  `192.0.2.16`, the full-size `192.0.2.148`.
- **Serials.** The Compact states `SERIAL00000001` and is named
  `WING-PP-SERIAL01`; the full-size states `SERIAL00000002`. Each is the
  same in every file of a capture (the identity string, the journals' `desk`
  blocks and journal ids, and the hex of the raw log's `/?` reply, where
  every replacement is the same length so the OSC padding is unchanged).
  `atoo/initialized/wing-compact.snap` carries the same `creator_name`, so it
  is byte for byte `console-runs/Initialized-Compact.snap`.

A fixture added or refreshed is scrubbed the same way.

## Sample shows: input lists and conventions

The hand-written sample shows the suite builds from, each an input list
(`.csv`) with the conventions that go with it (`.md`).

| Files | What | Read by |
|---|---|---|
| `smallband.csv`, `smallband.md`, `smallband.plan.json` | a small band; the plan is a build of it | `test_cli.py`, `test_conventions_ref.py`, `test_amend.py`, `test_channel_misses_main.py`, `test_channel_reaches_nothing.py`, `test_render.py` |
| `smallband_natlang.md` | the same band's conventions written as plain prose | a sample for trying a build |
| `fullband.csv`, `fullband.md` | a larger band with monitor sends that do not route to Main, a bus routed to an outboard effect, and a per-channel override beside a category default | `test_cli.py` |
| `touringband.csv`, `touringband.md` | a touring band converted by hand from a real show file | `test_cli.py`, `test_bundle.py`, `test_webui.py`, `test_preset_library.py` and more |
| `touringband.plan.json`, `touringband.generated.plan.json` | plans for it: one from the compiler that preceded model builds, one a real model reply from before the `socket` rename | `test_verify_plan.py`, `test_bus_colours.py`, `test_plan_schema.py`, `test_generate_and_verify_cli.py` |
| `touringband.watch.json` | its watch conditions, with a channel written as bare `Main` | `test_watch_scoped_names.py` |
| `festival.csv`, `festival.md` | a festival template, deliberately partly filled (14 of 38 channels unpatched) | `test_webui_filebrowser.py` |
| `real_plans.json`, `compiled_plans.json` | plans for four real shows of 9 to 38 channels, written by the compiler that preceded model builds | `test_plan_schema.py`, `test_preset_expand.py`, `test_apply.py`, `test_render.py`, and `conftest.py`'s `stub_build` |
| `setup_viewer.plan.json` | a plan for the Setup page's plan viewer | `test_webui.py`, `test_conventions_ref.py` |
| `applied-show.plan.json` | the touring-band plan as it stood when it was applied: the "applied show" of the amend tests | `test_amend.py`, `test_patch.py`, `test_webui_amend.py` |
| `sample.snap`, `sample.watch.json` | a console snapshot and a watch list | `test_snapshot.py`, `test_cli.py`, `test_webui.py` |
| `bus_width.csv`, `bus_width.md` | a deliberately small show whose conventions state a bus width in the middle of a bullet that says three other things | `test_prompt_fidelity.py` |
| `engineer-conventions.md` | an engineer's own conventions, kept only to check that the prompt does not quote them | `test_prompts.py` |

## Build replies, plans and logs from real models

One regression each: what a model wrote, kept so the code that repairs,
checks or expands it is tested on the real thing.

| Files | What | Read by |
|---|---|---|
| `haiku45_smallband.csv`, `haiku45_smallband.reply.json`, `haiku45_smallband_2026-09-29.reply.json` | a smaller hosted model's failed builds of the small band | `test_haiku_plan_fixes.py`, `test_send_levels_and_reply_repair.py` |
| `haiku45_smallband_nulls.reply.json` | a reply that writes `null` for what it has nothing to say about | `test_reply_expand.py` |
| `haiku45_sixpiece_2026-09-29.reply.json`, `haiku45_sixpiece_2026-09-29_fixup.reply.json` | a build of the six-piece band that gave a category no colour and put a marker where a Matrix cannot carry one, and the reply to the fix-up round | `test_instructed_channels.py`, `test_sixpiece_round2.py`, `test_stereo_pair_reconcile.py` |
| `haiku45_festival_2026-09-29.csv` | the input list a festival build read, with 14 "not patched for this event" rows its reply left out | `test_every_row_built.py` |
| `haiku45_festival_dangling_dca.csv`, `haiku45_festival_dangling_dca.reply.json` | three channels of that build, rewritten as a compact reply: one joins a DCA the plan never declares | `test_fixup_round.py`, `test_conventions_resolve.py` |
| `festival_2026-09-29.plan.json` | a festival plan from a larger model, every unity send to a mix or FX bus written `level_db: null` | `test_send_levels_and_reply_repair.py`, `test_channel_misses_main.py` |
| `sixpiece_2026-09-29.csv`, `sixpiece_conventions_2026-09-29.md`, `sixpiece_instructions_2026-09-29.md` | the texts those six-piece builds read: the input list, the conventions and the show's instructions | `test_instructed_channels.py`, `test_category_table.py` |
| `sixpiece_2026-10-01.csv`, `sixpiece_instructions_2026-10-01.md`, `conventions_2026-10-01.md`, `conventions_2026-10-01.resolved.md` | the inputs of a six-piece rebuild whose generator dropped the conventions' Aux 1, Aux 2 and Aux 8 | `test_instructed_strips.py` |
| `conventions_2026-10-01_strips.resolved.md` | that resolved file with an `## Instructed strips` block added, restating its three aux strips | `test_instructed_strips.py` |
| `sixpiece_2026-10-01.reply.json` | that build's reply, reconstructed from its plan (the raw reply was not kept) | `test_instructed_strips.py` |
| `conventions_2026-09-30.resolved-body.md` | a resolved conventions body with a `## Category table` written after it | `test_category_table.py` |
| `sixpiece_2026-10-01.plan.json` | a real findings load: 36 build notes, 10 verify findings, 10 critic findings | `test_findings_dock.py`, `test_findings_dock_layout.py`, `test_build_details.py` |
| `sixpiece_2026-10-02.plan.json` | a six-piece build whose channel 24 reads MUSIC | `test_full_apply.py`, `test_apply_progress.py`, `test_initialize.py` |
| `sixpiece_2026-10-11.plan.json` | the plan a Compact was watched with: monitor busses on AES50, a phones Matrix, a Kick out of its busses, a muted Vocals bus | `test_watch_desk_drift.py` |
| `lessons_thinking.build-log.json` | a build log with the model's kept thinking-summary notes | `test_lessons.py` |
| `preset-test.plan.json` | the touring-band plan with a preset named on six channels, each a matching case, and two names that are deliberately not in the library (`Snare Top`, `Kick (In)`) | `test_bus_presets.py`, `test_mix_bus_presets.py` |
| `watchlist_draft_extra_key.json` | a watch-list draft whose first condition carries an `index` key no condition has, and whose third names a field outside the vocabulary | `test_watchlist_draft.py` |

## Console captures and journals

From real desks. `console-runs/` keeps its original sub-folder names.

| Files | What | Read by |
|---|---|---|
| `console-runs/Initialized-Compact.snap`, `Initialized-Full.snap`, `Initialized-Rack.snap` | the factory state of a Compact, of a full-size WING and of a Rack (the Rack's from WING Edit 3.3.1, firmware 3.1-0-g9f314617, exported 2026-10-21; byte for byte `atoo/initialized/wing-rack.snap`; its `creator_name` is scrubbed to `WING-PP-SERIAL01` like the Compact's, nothing else in the file differs from the desk's export) | `test_audit_in_use.py`, `test_initialize.py`, `test_apply.py`, `test_alternate_input_plan.py` |
| `console-runs/Church-Full.snap` | a full-size WING with a house mix on it | `test_alternate_input_plan.py` |
| `console-runs/2026-09-21/` | raw log and OSC captures of channel 1 with and without alternate inputs | `test_readback_index_base.py`, `test_alternate_input_plan.py`, `test_audit_alternate_input.py` |
| `console-runs/2026-09-21-2100/`, `2026-09-22-2136/` | apply journals of two real runs | `test_undo.py` |
| `console-runs/2026-09-22-2008/` | a read-speed measurement | `test_watch_scope.py` |
| `console-runs/2026-09-22-2139/` | a board with a podium channel on it, and its occupancy | `test_amend.py`, `test_audit_in_use.py` |
| `console-runs/2026-09-23-1921/` | a full-size WING: its model description and its capture | `test_console_model.py`, `test_audit_stale_strip_name.py`, `test_audit_effects.py`, `test_audit_talkback.py` |
| `console-runs/2026-09-28-1904/` | a journal from before a fix: its `in/set/dly` was skipped under a changed `dlymode` | `test_selector_dependent.py` |
| `console-runs/2026-10-02-sixpiece-apply-excerpt.json` | an excerpt of the first full apply on a Compact (4,583 writes): every mismatch row, every `/bus/{n}/busmono` and `/bus/{n}/wid` row, and aux 2's `dyn/mdl` and `dynsc` rows, unchanged, each with its `index` in the journal | `test_initialize.py`, `test_preset_expand.py` |
| `console-runs/session-2026-09-23-0928/` | a rebuilt plan with channel 18 removed | `test_amend.py` |
| `touringband-2026-09-18.apply-journal.json` | the journal of a touring-band apply on a real desk | `test_apply.py`, `test_readback_index_base.py`, `test_webui_apply.py` |
| `a18-full-size-unanswered.json` | what a full-size WING left unanswered in a read | `test_read_unanswered_family.py` |
| `amend-demo/` | the amend walkthrough's files: a rebuilt plan, the same without one channel, and the desk's occupancy before and after a strip is taken over | `test_amend.py`, `test_amend_plan_json.py`, `test_webui_amend.py` |
| `audit_demo_plan.json`, `audit_demo_state.json`, `audit_demo_state_before.json` | a hand-built console state and plan for trying `audit` with no console attached; the packaged copies are `starter/audit-demo/` | `test_audit_dump_state.py`, `test_help_examples.py`, `test_packaging.py` |

## Presets

Frozen copies of the starter preset library (`starter/presets/`), with
`creator_name` scrubbed to `WING-PP-SERIAL01`. All are `chpreset.11`
exports from WING-EDIT 3.3.1.

| Folder | What | Read by |
|---|---|---|
| `channel_presets/` | all 19 channel presets (`.chn`), the two FX bus presets (`FX Vox Verb.bus`, `FX Snare Verb.bus`) and the mix bus preset (`Mix Bus.bus`) | `test_cli.py`, `test_presets.py`, `test_preset_expand.py`, `test_mix_bus_presets.py`, `test_preset_map_coverage.py` |
| `presets/` | five of them: `Kick.chn` (saved as **Kick In**), `Snare.chn`, `H Tom.chn`, `Fl Tom.chn`, `Piano.chn` | `test_presets.py`, `test_preset_resolution.py`, `test_input_list_preset.py` |

The older `chpreset.8` shape is built in `test_presets.py` from the Kick.

## The Demo show

`starter/demo-show/` is shipped, not a fixture, so a test that needs an
older Demo reads a frozen copy, and a test whose subject is the shipped Demo
(`test_demo_show.py`) asserts only what it promises.

- `old-demo-rig/before.json`: the earlier 7-channel Demo rig, for
  `test_webui_watch.py`'s scoped-name resolution, which needs a bus named
  Drums at BUS 1.
- `demo-horns.change-set.json`: the change set for the Demo's 6pm change,
  *"trumpet, sax and trombone on LCL 21-23, Band DCA"*, written by hand in
  the shape `patch --save-change-set` writes, so `test_demo_show.py` can
  review it against the Demo rig with no model. The horns take their starter
  presets and land on a new Horns mix bus with the "Mix Bus" preset.
  `docs/user/demo/demo-show/horns.change-set.json` is the same file; a test
  keeps the two equal.
- `watch-build-duplicates.watch.json` and `watch-build.plan.json`: the
  `watch.json` a full-size WING run of the Demo ended with (a `MAIN PA` and a
  `MAIN 1` mute condition side by side, one `BUS` condition per bus, a `DCA`
  range beside a `DCA Vocals`), and the plan it was drafted for, cut down to
  two channels. Read by `test_watch_build_duplicates.py`.
- `patch-aux8.change-reply.json` and `patch-aux8.plan.json`: a real-model
  reply to the change *"Add another vocal channel, move Playback to Aux 8."*
  (the 3,544 characters `atoo patch` kept when it refused the reply for
  leaving out `add.busses`, `add.dcas`, `add.mute_groups` and `add.outputs`),
  and the plan it was compiled onto, cut down to the four strips (Kick, Lead
  Vox, Playback, Music) and the busses, DCAs, mute groups and output the
  reply names. Read by `test_patch_omitted_sections.py`.
- `patch-change-name-61.change-reply.json`: a real-model reply to the change
  *"Add HiHat channel after Snare channel. Add another vocal mic "F Lead2",
  Move "Playback" to channel 16 and input A16 (make it mono)."*, as `atoo
  patch` kept it when it refused it for a 61-character short name (limit
  48). Whole JSON, otherwise valid. Read by `test_patch_cosmetic_names.py`.
- `demo_2026-10-13/`: a real-model rebuild of the Demo: its `conventions.md`,
  `demo-show/input.csv` and `instructions.md`, the `conventions.resolved.md`
  its resolve call wrote (169 citations), and `generator.reply.json`, the
  generator's reply. `test_quiet_build.py` replays that build with no model
  and asserts the Findings dock reads 0 to check and 4 choices.
- `preset_map_2026-10-13/`: a real-model build of a copy of `starter/`: its
  `conventions.md` and the `conventions.resolved.md` its resolve call wrote,
  which cites ten of the preset map's lines by no rule. Read by
  `test_preset_map_coverage.py`, with `channel_presets/` as the library.
- `rebuild_diff/previous.plan.json` and `current.plan.json`: the packaged Demo
  built from its hand-written reply with no model, then rebuilt after one
  edit (the `Guest Vox` row un-skipped and named in the instructions), with
  that reply edited to add Guest Vox and, unasked, to raise the Bass DI's gain
  from 20 to 26 dB. Both carry `meta.change_basis`; the second carries
  `meta.changes_since_previous`. For `test_plan_diff.py`: an asked-for
  change, one nobody asked for, and a renumbered strip.
- `rebuild_diff/demo/`: the inputs of that run (`conventions.md`,
  `input.csv`, `instructions.md`, `reply.json`) and the edit as files
  (`input.after.csv`, `instructions.after.md`, `reply.after.json`), so
  `test_plan_diff.py`'s end-to-end build does not depend on the shipped
  Demo's text.
