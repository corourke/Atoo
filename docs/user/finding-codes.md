<!-- GENERATED FILE -- edit the preamble block only.

     Every code below comes from the table of finding codes in the code, by
     a script in the development repository. Editing a code here by hand
     will be overwritten there.

     Text inside the `<!-- preamble:start/end -->` block IS hand-written
     and is preserved across regeneration.
-->

# Finding codes

<!-- preamble:start -->
Every finding Atoo prints ends with a code in brackets, such as `(patch.socket-out-of-range)`. Search this page for the code to see what the finding is about, or quote it in a bug report: a code stays the same from version to version even when its message is reworded. [Reading findings](reading-findings.md) explains the four severities and where findings appear.

A code ending in `*` is a family: the last part is filled in when the finding is made, such as `critic.omission` from `critic.*`. The checks `audit` and Watch run on the desk itself have codes like `R005` and `CV016`; the [Rules reference](rules-reference.md) lists those. A code starting `WATCH:` is one of your own [watch conditions](watch-conditions.md).
<!-- preamble:end -->

## The build

What the build chose where your conventions were silent, how it filled in the model's draft from the input list and your conventions, and what stopped it.

| Code | What it means |
|---|---|
| `build.bus-sheet` | A filled cell in busses.csv overrides the conventions for a bus, and the build carries it out. |
| `build.conventions-from-plan` | The Build page shows the conventions file this plan was built from rather than the house default named in the settings file; a build from the page uses the file shown. |
| `build.conventions-missing` | The house conventions file named in the settings file is not at that path. |
| `build.conventions-not-plan` | The conventions file typed into the Build page is not the one this plan was built from, and a build from the page uses the typed file. |
| `build.critic-repair` | A line the critic review found not carried out was sent to the fix-up round; the plan written carries it out, or, where that cannot be checked, the round was asked to. |
| `build.failed` | The build did not produce a plan; the message gives the reason from the run's own output. |
| `build.fixup` | Verify errors or missed instructions in the first plan went back for one fix-up round, and the corrected plan passes. |
| `build.fixup-failed` | The fix-up round did not produce a usable plan, so the first plan stands with the problems it was sent to fix. |
| `build.fixup-rejected` | The fix-up round's corrected plan verified worse than the first, so it was discarded and the first plan stands. |
| `build.fixup-unresolved` | After the fix-up round, the corrected plan still has some of the problems it was sent to fix; they are listed with it. |
| `build.input-list-missing` | The open show bundle has no input.csv, and a build cannot run without the input list. |
| `build.monitor-source` | Two outputs both claim to be the source for the phones or the monitor speakers; the first claim is kept and the second is not carried out. |
| `build.no-conventions` | No house conventions file is set, and a build cannot run without one. |
| `build.outputs-sheet` | busses.csv and outputs.csv disagree on which sockets a bus feeds; outputs.csv wins, and the Outputs column of busses.csv follows it. |
| `build.outputs-sheet-overrides` | A line in the conventions or instructions.md asks for output sockets that outputs.csv does not give that bus; outputs.csv decides, so those sockets are not patched. |
| `build.recorded-conventions-edited` | The conventions file this plan was built from has been edited since, so the next build reads different text from the one that made the plan. |
| `build.recorded-conventions-missing` | The conventions file this plan was built from is no longer where the plan records it, so the plan cannot be rebuilt exactly as it was. |
| `build.recorded-conventions-moved` | The plan's conventions file is not at its recorded place beside the bundle but was found at its recorded full path; the bundle has probably moved. |
| `build.resolved-conventions` | Reports whether the resolved conventions, which a build reads in place of the raw file, are up to date or will be resolved again before the next build. |
| `build.user-sheet` | A filled cell in user.csv overrides the conventions for a user signal, and the build carries it out. |
| `build.watchlist-drafted` | The build drafted watch conditions into the show's watch file, merged beside any existing ones and marked as drafted; nothing is watched until a watch session starts. |
| `build.*-unreadable` | The conventions file, input list or instructions.md exists but cannot be read, so the build cannot use it. |
| `bundle.copied-in` | A file was copied into the show bundle from elsewhere and is now the bundle's own copy. |
| `category-table.invalid` | The Category table in the resolved conventions cannot be read, so code applies no per-category setting and the model writes every channel's settings. |
| `category-table.missing` | The resolved conventions have no Category table, so code applies no per-category setting; resolving the conventions again adds the table. |
| `inferred.bus-destination` | A bus has no destination stated in the conventions; the build routes it to one and names what that choice was based on. |
| `inferred.bus-main-index` | A bus routed to a Main does not say which Main; the build picks the Main number and names what it was based on. |
| `inferred.bus-width` | The conventions do not state whether a bus is mono or stereo; the build sets its width and names what it inferred it from. |
| `inferred.channel-stereo` | No convention states whether a channel is stereo; the build links it as a pair or keeps it mono and names what it was based on. |
| `inferred.output-index` | A Main or Matrix in the plan has no number; the build assigns one and names what that choice was based on. |
| `inferred.output-run` | A run of output sockets is fed from a range of sources, as a line of the instructions asks; lists the sockets and what feeds each. |
| `inferred.pair-phantom` | Stereo channels state one 48V value for the pair, so the second socket takes the first socket's phantom setting. |
| `inferred.processed-feed` | An output socket carries a strip's signal pre- or post-fader, as the instructions ask, routed through the next free user signal. |
| `inferred.send-level` | Channel sends into a bus have no stated level; the build sets one and lists the channels and what the level was based on. |
| `inferred.send-mode` | The conventions do not say whether sends into a bus are pre- or post-fader; the build chooses one and lists the channels it applies to. |
| `input-list.column-not-followed` | A filled channel, DCA or mute-group cell in input.csv disagrees with the plan, because one changed after the other, so the cell has had no effect. |
| `input-list.invalid` | The input list cannot be read; the message names the row and column at fault, and nothing from the file is used until it is corrected. |
| `input-list.patch-shorthand` | Patch cells in input.csv written as A, B or C plus a number are read as sockets on the desk's AES50 stage-box ports. |
| `input-list.skipped` | Rows marked '-' in input.csv's order column are left out of this build; the finding lists them. |
| `instructed-strips.entry-invalid` | One strip in the resolved conventions' list of instructed strips cannot be built from it, for the reason the message gives, so the model builds it instead. |
| `instructed-strips.invalid` | The list of instructed strips in the resolved conventions is not valid JSON or not the expected shape, so none is built from it and the model builds them instead. |
| `instructed-strips.missing` | The resolved conventions predate the list of instructed strips, so strips the conventions ask for are left to the model to build; resolving again adds the list. |
| `output-runs.not-a-socket` | An output run the instructions ask for is not built, because what it names as its destination is not an output socket. |
| `output-runs.not-a-source` | An output run the instructions ask for is not built, because what it says to feed from is not a source the desk's output routing offers. |
| `processed-feed.no-free-user-signal` | An output asked to carry a strip's processed signal is not fed, because every user signal is already in use. |
| `processed-feed.no-such-strip` | An output asked to carry a strip's processed signal is not fed, because the plan has no channel, bus, Main or Matrix by that name. |
| `processed-feed.not-a-socket` | A processed feed the instructions ask for is not built, because what it names as its destination is not an output socket. |
| `rebuild.unasked-change` | A rebuild changed a strip although nothing it is made from changed; the plan may still be right, so check it. |
| `reply.alt-sockets-chosen` | Alternate inputs go on the next sockets of the group the conventions name, ones no main patch uses and input.csv does not state, in channel order. |
| `reply.category-group-declared` | A DCA or mute group that the category table puts channels in is declared by the build, because the generated plan left it out. |
| `reply.category-rule` | Fields the generated plan left out for an input-list category are filled from the conventions' category table; the finding lists what was set and for which channels. |
| `reply.channel-from-input-list` | The input list's channel column puts a row on a different strip than the build chose; the list wins, and any channel already there swaps places. |
| `reply.channels-numbered` | Lists the strip numbers given to channels, in the order the model's draft listed them. |
| `reply.colours-applied` | Lists the colors written to channels from the category color map, by each input-list row's category. |
| `reply.dca-from-input-list` | The input list's DCA column puts a channel in different DCAs than the model's draft did; the list wins. |
| `reply.from-instructions` | A strip not on the input list is built because instructions.md or the conventions ask for it; type, 48V and color are chosen where the text is silent. |
| `reply.instructed-strip` | A strip the conventions ask for, not on the input list, is added on the socket they name, or left unpatched when that socket is taken; a clash is a warning. |
| `reply.instructed-strip-no-room` | The conventions ask for a strip, but every strip in its bank is already taken, so it is not built. |
| `reply.instructed-strip-row` | The conventions put a strip on one socket, but the matching input-list row states another; the input list's socket is used. |
| `reply.instructed-strip-sends` | The bus sends the conventions state for a strip they ask for are written; a send to a bus this plan does not have is left out and named. |
| `reply.line-gain` | A Line source on a head amp gets a line-level gain chosen from its type, not the mic gain copied from other channels. |
| `reply.mute-group-from-input-list` | The input list's mute group column puts a channel in different mute groups than the model's draft did; the list wins. |
| `reply.name-cut` | A channel name is longer than the 16 characters the desk shows, so the strip is named with its first 16. |
| `reply.note-carried-out` | A note in the model's draft about an input-list column is dropped, because the build carries out every filled cell of that column itself. |
| `reply.pair-by-names` | Two mono rows named as an L/R pair become one stereo channel, patched through user patch slots because their sockets cannot pair directly. |
| `reply.pair-phantom` | The two input-list rows of a stereo channel disagree about 48V; the desk switches a pair's 48V together, so both sockets get it. |
| `reply.pair-split` | A stereo pair's two sockets cannot pair on the desk as cabled and no user patch slots can bridge them, so it is built as two mono channels. |
| `reply.pair-through-user-patch` | A stereo pair's two sockets cannot pair on the desk as cabled, so the channel is patched through two user patch slots that take one socket each. |
| `reply.preset-from-input-list` | The input list's preset column names a different preset for a channel than the model's draft chose; the list wins. |
| `reply.row-built` | An input-list row is built as a channel, with its strip and socket, because nothing in the conventions, instructions or its notes leaves it out. |
| `reply.sends-expanded` | Each channel's bus sends are written out from the busses' sender lists; the note counts the senders per bus. |
| `reply.socket-group-assumed` | Neither the model's draft nor the input list names a socket group for a row, so it is patched from LCL, the group a small rig cables into. |
| `reply.socket-skipped` | A socket is left empty so a stereo pair starts on an odd socket, since the desk forms a pair only from an odd socket and the next even one. |
| `reply.sockets-chosen` | Lists, per socket group, the next free sockets given to channels whose group the model's draft chose but whose socket nothing stated. |
| `reply.unassigned-quote-not-found` | The model's draft left an input-list row out, quoting a reason that is not in the conventions, instructions or the row's notes, so the row is built anyway. |
| `reply.unpatched-by-list` | The input list's patch column says OFF for a row, so its channel is patched from nothing and apply sets its input to OFF. |
| `reply.*-from-input-list` | A filled input-list column (channel, DCA, mute group or preset) differs from what the model's draft chose for a channel; the list's value is used. |
| `resolve.failed` | Rewriting the conventions into the resolved conventions file failed, so this build reads the raw conventions and the domain knowledge instead. |
| `resolve.line-not-covered` | A conventions line is cited by no rule in the resolved conventions, so the model reads it word for word; also a preset-map line naming a preset the library lacks. |
| `resolve.not-written` | The resolved conventions could not be saved beside the conventions file; this build uses them, but the next build resolves again. |
| `resolve.preset-library-unreadable` | The preset library cannot be read, so the preset-map lines in the conventions are not checked against it and count as covered. |
| `resolve.quote-not-found` | A rule in the resolved conventions cites text that is not in the conventions file or the domain knowledge, so the rule may not be the engineer's. |
| `resolve.refused` | The resolved conventions file is empty or cites nothing found in the conventions, so it is not used and the build reads the raw conventions. |

## Your conventions and the critic

Notes on the text of your conventions and instructions.md, and the critic: a second model call that reads the built plan against them. The critic never blocks an apply.

| Code | What it means |
|---|---|
| `conventions.conflict` | Two lines in the conventions or instructions.md set the same thing differently with nothing to settle it; the message names the one the plan followed. |
| `conventions.stray-comment-close` | A comment end (-->) in the conventions has no opening <!-- before it, so it is read as written, perhaps as an arrow. |
| `conventions.unclosed-comment` | A comment opened with <!-- in the conventions never closes, so the rest of the file, the comment included, is read as rules. |
| `conventions.unused` | Something declared in the conventions, such as a DCA, mute group or bus, is not used by anything in this show. |
| `conventions.unverified-quote` | A conventions conflict or unused item was reported quoting text that is not in the conventions or instructions.md, so it is shown but not trusted. |
| `conventions.*` | A note on the conventions or instructions text itself, such as two lines that conflict or a declared DCA, mute group or bus this show leaves empty; the last part names which. |
| `critic-expect.missed` | In a scoring run of the critic review, a gap the expectations file lists was not flagged at all. |
| `critic-expect.not-run` | The critic review did not run, so nothing was scored against the expectations file; this is not the same as a review that found nothing. |
| `critic-expect.under-severity` | The critic review flagged an expected gap, but at a lower severity than the expectations file asks for. |
| `critic.conventions` | The critic review found a problem in the conventions text itself: two lines that disagree, or something declared that nothing in the show uses. |
| `critic.intent` | The critic review found a line of the conventions or instructions.md that the plan carried out wrongly, or a stated fact the plan left unset. |
| `critic.omission` | The critic review found an input-list row missing from the plan, or a conventions line not carried out at all; a quoted line goes to the fix-up round, and is a warning if the plan written still does not carry it out. |
| `critic.*` | A second model call, the critic, reviews the built plan and reports a concern, such as a row left out, an intent misread, something invented or a contradiction; it is an INFO, listed under Advice, and never blocks an apply. |

## The plan against the desk and the input list

What verify finds when it checks plan.json against the desk's limits, your input list and the physical sockets: things that cannot work are errors, the rest are for you to check.

| Code | What it means |
|---|---|
| `alt-patch.malformed` | A channel's alternate patch in plan.json is not a group-and-sockets entry, so it cannot be read. |
| `alt-patch.mono-socket-count` | A mono channel's alternate patch does not name exactly one socket; the alternate feeds the same strip, so it takes one. |
| `alt-patch.no-sockets` | A channel's alternate patch names no sockets, or its sockets are not a list. |
| `alt-patch.same-as-main` | A channel's alternate patch is the same socket as its main patch, so switching the strip to its alternate changes nothing. |
| `alt-patch.socket-out-of-range` | A channel's alternate patch names a socket that is not a positive number, or one its input group does not have on this desk. |
| `alt-patch.socket-shared` | A channel's alternate socket is also used by another source, so the strip hears that source when switched to its alternate. |
| `alt-patch.socket-width-conflict` | An alternate socket is used elsewhere at the other width, mono in one place and stereo in the other; width belongs to the socket, so it cannot be both. |
| `alt-patch.stereo-pair-not-odd-even` | A stereo channel's alternate patch names two sockets the desk cannot pair; a stereo pair is always an odd socket and the even one after it. |
| `alt-patch.stereo-socket-count` | A stereo channel's alternate patch does not name exactly two sockets. |
| `alt-patch.unknown-group` | A channel's alternate patch names an input group the desk does not have. |
| `bus.colour-alias` | A bus uses an older color name, such as Crimson or Magenta, that still resolves to one of the desk's colors; the desk's own name is given to use instead. |
| `bus.colour-not-writable` | A bus names a color that is not among the desk's eighteen, so the bus keeps whatever color it already had. |
| `bus.empty` | A bus is declared but no channel sends to it, so it carries silence. |
| `bus.index-duplicated` | Two or more busses state the same bus number; the desk has one bus there, so only one of them would exist after an apply. |
| `bus.matrix-destination-unsupported` | A bus names a Matrix as its destination, which is not how a Matrix is fed; the feed belongs on the Matrix's own list of sources in plan.json. |
| `bus.no-destination` | A bus feeds nothing, neither a Main nor an output, so every channel sent to it is inaudible. |
| `bus.not-an-object` | An entry in the busses section of plan.json is not an object (a null or a list, for example), so it cannot be checked or applied. |
| `bus.unresolved-destination` | A bus is routed to an output, but no physical socket was resolved for that output. |
| `capacity.exceeded` | The plan declares more of something, such as busses, DCAs or mute groups, than the desk has. |
| `capture.mix-left-to-desk` | This plan was captured from a desk and states no faders, mutes or send levels; applying it leaves those, and the strips it does not hold, as the desk has them. |
| `channel.missing-field` | A channel in plan.json lacks a field every channel must have. |
| `channel.not-an-object` | An entry in the channel list of plan.json is not a channel record. |
| `console.unknown-model` | The plan names no console model Atoo knows, so the sockets it patches cannot be checked against the desk's panel. |
| `console.window` | Watch reads the desk with a non-default number of requests in flight, set by ATOO_CONSOLE_WINDOW, or that variable's value was not accepted. |
| `direct-output.source-out-of-range` | An output socket is fed from an input socket number that does not exist on this desk. |
| `direct-output.unknown-source` | An output socket is fed from a source group that the desk's output routing does not offer. |
| `group.empty` | A DCA or mute group is declared but no channel or bus joins it, so it does nothing. |
| `group.index-duplicated` | Two or more DCAs, or two or more mute groups, state the same number; the desk has one there, so only one of them would exist after an apply. |
| `output.index-duplicated` | Two or more outputs state the same Main or Matrix number, so all would be patched from that one mix and the others never reach a jack. |
| `output.monitor-source` | A bus, Main or Matrix is the source for the desk's phones or monitor speakers, so it needs no output socket of its own. |
| `output.no-patch` | A Main or Matrix is patched to no physical socket and reaches none by another path, so what it carries is heard nowhere; apply still sets its level and processing. |
| `output.not-an-object` | An entry in the outputs section of plan.json is not an object (a null or a list, for example), so it cannot be checked or applied. |
| `output.socket-collision` | One physical output socket is claimed by two or more sources, so only the last one written would carry signal; the message lists free sockets to move one to. |
| `output.socket-out-of-range` | An output is patched to a socket number its group does not have on this desk model. |
| `output.too-many-sockets-for-one-source` | An output states more than two physical sockets for one source; a source has only an L and an R, so a third would land on another output's routing. |
| `output.unknown-group` | An output is patched to a socket group the desk does not have; the message lists the groups that exist. |
| `patch.aborted` | A live change stopped part way, because the desk stopped answering or Stop was pressed; the journal records every write that reached the desk, and undo takes them back. |
| `patch.blocked` | A live change to the desk is refused whole, with nothing written, because part of it cannot be written: a missing object, a missing field or an out-of-range value. |
| `patch.collision` | A live change reaches addresses the applied plan also writes, so its scope is wrong and it is refused rather than written. |
| `patch.contradicts-input-list` | A channel is patched to a different socket from the one input.csv says its cable is plugged into. |
| `patch.contradicts-instructions` | A strip built from the conventions or instructions is patched to a socket other than the one they state for it. |
| `patch.expansion-bay-empty` | The plan uses an expansion bay that the captured desk read as empty, so the channels and outputs on it would be silent. |
| `patch.expansion-bay-not-checked` | The plan uses an expansion bay and no reading of the desk says what is fitted there; the apply preview checks it and refuses an empty bay. |
| `patch.failed` | A live change did not run at all; the message carries its last words, and the run log on the Apply screen has the rest. |
| `patch.info` | A choice a live change made where the request left it open, reported for the engineer to review. |
| `patch.missing` | A channel in plan.json has no patch at all, so it is connected to nothing. |
| `patch.mono-socket-count` | A mono channel is patched to more than one socket, or to none. |
| `patch.moved` | After a live change was written, settings belonging to strips it does not touch changed on the desk; the run log names each with its before and after values. |
| `patch.no-sockets` | A channel's patch names no sockets, or its socket entry is not a list. |
| `patch.not-checked` | No console model is known, so nothing checks that the sockets the plan patches exist on this desk; the WING, Rack and Compact differ. |
| `patch.note` | Something in a live change's review that deserves a look before the show; the change is not refused for it. |
| `patch.off` | A channel's patch is OFF in the input list, so apply sets its input to nothing and the strip is left unpatched. |
| `patch.past-stage-box` | A channel or output is patched to a socket past the end of the stage box on that AES50 port, so it hears nothing or sends nothing. |
| `patch.preflight` | A live change is refused by the check run before writing, and nothing is written; the message gives the reason. |
| `patch.socket-out-of-range` | A channel is patched to a socket number that is not a positive whole number, or that its group does not have on this desk model. |
| `patch.socket-shared` | One input socket feeds more than one channel; normal for a separate monitor strip, but worth confirming it was asked for, since the strips share gain and phantom. |
| `patch.stereo-pair-not-odd-even` | A stereo channel's two sockets are not a consecutive odd-then-even pair, which is the only pairing the desk can link as stereo. |
| `patch.stereo-socket-count` | A stereo channel is patched to some number of sockets other than two. |
| `patch.unknown-group` | A channel is patched from an input socket group that does not exist; the message lists the groups that do. |
| `patch.unparsable-stated-socket` | A patch cell in input.csv cannot be read as a group and a number, so the plan's patch for that row is not checked against it. |
| `patch.user-source-undefined` | A channel or output uses a user signal (USR slot) that nothing in the plan defines, so it carries whatever that slot holds on the desk now, or nothing. |
| `phantom.pair-differs` | The plan gives the two sockets of a stereo channel different 48V settings; the desk switches them together, so apply turns 48V on for both if either is on. |
| `plan.busses-not-an-object` | The busses section of plan.json is not a set of entries keyed by name, so it cannot be checked. |
| `plan.channels-not-a-list` | The channels section of plan.json is not a list, so the plan cannot be checked any further. |
| `plan.made-from-disagrees` | plan.json says it was built, or captured from a desk or snapshot, but its send levels look like the other kind; it is treated as what it says it is. |
| `plan.missing-section` | plan.json lacks one of its required top-level sections. |
| `plan.no-channels` | plan.json assigns no channels at all, so there is nothing to check or apply. |
| `plan.not-an-object` | plan.json is not a JSON object, so nothing in it can be checked. |
| `plan.old-patch-key` | plan.json holds a patch under a field name that is no longer read, so that patch is ignored; rebuild, or rename the field. |
| `plan.older-than-inputs` | plan.json is older than edits to the files it is built from, so applying it writes the plan without those edits. |
| `plan.outputs-not-an-object` | The outputs section of plan.json is not a set of entries keyed by name, so it cannot be checked. |
| `reconcile.deliberately-unassigned` | An input on the input list has no channel, and the plan declares it deliberately unassigned; confirm that is intended before the show. |
| `reconcile.dropped-input` | An input on the input list has no channel in the plan, and the plan does not declare it deliberately unassigned. |
| `reconcile.duplicated-input` | One input from the input list feeds more than one channel; right when it was asked for, and the strips share one head amp's gain and phantom. |
| `reconcile.from-instructions` | A strip not on the input list is built because the conventions or instructions ask for it; a warning when it could not be checked or is left unpatched. |
| `reconcile.instructed-conflict` | A strip built from the instructions is patched to a socket another source already uses, and one socket cannot carry two sources. |
| `reconcile.invented-source` | A channel not on the input list claims the instructions asked for it, but quotes nothing, or quotes words they do not contain, so nobody will plug it in. |
| `reconcile.not-checked` | No input list was supplied, so nothing checks that every input became a channel, that none was invented, or that phantom power is safe. |
| `reconcile.skipped-source` | The plan builds a channel for an input.csv row now marked skipped; the plan was built before the row was skipped. |
| `reconcile.unknown-unassigned` | The plan declares an input deliberately unassigned, but that input is not on the input list. |
| `reference.dangling` | A channel, bus or Matrix refers to a bus, DCA or mute group that the plan never declares. |
| `routing.broadcast-only` | A channel stays out of the front-of-house mix but goes to a broadcast, stream, recording or video bus that reaches an output socket. |
| `routing.channel-misses-main` | A channel reaches no Main, directly or through a bus or Matrix, so it is not in the front-of-house mix. |
| `routing.channel-reaches-nothing` | A channel has no Main route, no monitor send and no audible bus send, so nothing on it is heard. |
| `safety.phantom-on-passive-ribbon` | The plan sends 48V phantom power to a passive ribbon microphone, which destroys the ribbon element; switching it off afterwards does not undo the damage. |
| `schema` | plan.json has a field the plan format does not have, lacks one it needs, or holds a value of the wrong kind; the message names the field. |
| `strip.colour-alias` | A color name in the plan is an old name for one of the desk's colors; it is written as that desk color, which the note names. |
| `strip.colour-not-writable` | Strips state a color the desk does not have, so apply cannot write it and they keep whatever color they already had. |
| `strip.double-booked` | Two sources are assigned to the same channel or aux strip, and a strip holds only one. |
| `strip.index-not-an-int` | A strip number in the plan is not a whole number. |
| `strip.index-out-of-range` | A strip number is past the number of channel or aux strips this desk has. |
| `strip.name-too-long` | A strip name is longer than the 16 characters the desk shows, so it would appear cut short. |
| `strip.unknown-bank` | A strip names an input bank other than ch or aux, the only two the desk has. |
| `talkback.unassignable` | A strip reads as talkback but is not on ch 40 or aux 8, the only strips the desk's talkback assign can use; apply leaves the assign as it is. |
| `user-source.duplicate-slot` | A USR slot is defined twice in the plan; one slot holds one source, so the second would overwrite the first. |
| `user-source.field-not-on-user-patch` | A user patch slot states a tap point or stereo leg, which only a user signal slot has. |
| `user-source.group-not-allowed` | A USR slot takes its source from a group that kind of slot (user signal or user patch) does not accept. |
| `user-source.index-out-of-range` | A USR slot takes a source number past the range its group has on this desk. |
| `user-source.slot-out-of-range` | A user source names a USR slot number the desk does not have. |
| `user-source.unused` | A USR slot is defined but no channel patches it and no output takes it; it is still written to the desk, and a mistyped slot number looks like this. |
| `value.eq-band-duplicate` | An EQ band is stated twice on one strip, so which setting is meant cannot be told. |
| `value.eq-band-empty` | An EQ band is listed with no frequency, gain, Q or filter type, so nothing is written for it. |
| `value.eq-band-unavailable` | An EQ names a band that this kind of strip does not have. |
| `value.eq-model-unavailable` | An EQ names a model that this kind of strip does not offer. |
| `value.eq-shape-on-parametric-band` | A middle EQ band states a filter type; only the low and high bands have one, and the others are always bells. |
| `value.eq-shape-unavailable` | The low or high EQ band states a filter type this kind of strip does not offer. |
| `value.eq-strip-unidentified` | An output states EQ or tilt, but the plan never says whether it is a Main or a Matrix, so there is no strip to write it to. |
| `value.eq-strip-unknown` | An EQ is stated on a kind of strip Atoo has no confirmed EQ facts for, so it cannot be checked or written. |
| `value.fader-out-of-range` | A fader level is outside the range the desk's faders can be set to. |
| `value.hpf-out-of-range` | A high-pass frequency is outside the range the desk's filter can be set to. |
| `value.main-index-out-of-range` | A channel routes to a Main number the desk does not have. |
| `value.mute-not-boolean` | A mute value in the plan is not true or false. |
| `value.presend-eq-band-duplicate` | A PreSend EQ band is stated twice on one channel, so which setting is meant cannot be told. |
| `value.presend-eq-band-empty` | A PreSend EQ band is listed with no frequency, gain or Q, so nothing is written for it. |
| `value.presend-eq-band-unavailable` | A PreSend EQ names a band it does not have; it has only its bell bands and no shelves. |
| `value.presend-eq-unavailable` | A PreSend EQ is stated on a strip that has none; only channel strips do. |
| `value.send-level-out-of-range` | A bus send level is outside the range the desk's sends can be set to. |
| `value.send-mode-unknown` | A bus send names a mode the desk does not have; it has PRE, POST and GRP. |
| `value.send-mode-unrepresented` | A bus send names a mode the desk has but plan.json cannot hold, so apply would not know what to write. |

## Presets and effects

Processing carried in from the preset library, and the FX engines it loads.

| Code | What it means |
|---|---|
| `fx.engine-allocated` | A bus preset's effect is placed in a chosen FX engine, with the reason for that choice. |
| `fx.engine-not-offered` | A bus preset's effect is placed in an FX engine that cannot hold that effect, or that does not exist. |
| `fx.engine-shared` | Two or more strips insert effects into the same FX engine; one engine holds one effect, so the last loaded would replace the others. |
| `fx.insert-switched-on` | A bus preset was saved with its effect insert bypassed; the build switches it on, because an FX bus with its effect bypassed is silent. |
| `fx.inserts` | Lists the FX inserts the plan loads and switches on, each read back from the desk after it is written. |
| `fx.no-engine` | No FX engine is left that can hold a bus preset's effect, because every engine that can is taken by another bus. |
| `fx.parameter-typed-from-value` | Some effect parameters have no single known type, so each is written with the type of its saved value and read back. |
| `fx.unknown-model` | A bus preset loads an effect that no FX engine on the desk offers. |
| `fx.value-not-offered` | A bus preset sets effect parameter values that the desk cannot take. |
| `preset.ambiguous` | Two or more presets in the library share one name; the newest is used and the others are ignored. |
| `preset.bus-expanded` | Busses carry a bus preset's processing in the plan, which apply writes and reads back; the finding lists them. |
| `preset.contradicts-input-list` | The plan names a different preset, or none, from the one input.csv's preset column states for a channel; the input list wins. |
| `preset.expanded` | Channels carry a preset's values in the plan, which apply writes at the processing stage and reads back; the finding lists them. |
| `preset.input-list-pair-disagrees` | The two input.csv rows of a stereo pair state different presets; the channel takes the first row's. |
| `preset.leaf-dropped` | A value in a preset file is left out of the plan, because it is not a processing setting a preset may carry or it points a sidechain at another strip. |
| `preset.leaf-not-on-strip` | Some of a preset's values are for sections this kind of strip does not have, so they are left out of the plan. |
| `preset.leaf-not-written` | Some preset values carried in the plan will not be written to the desk; the message names each one and why. |
| `preset.leaf-untyped` | A preset carries a value that cannot be written as its setting's type, or is not one a preset may set, so it is left out of the plan. |
| `preset.library-changed` | The library's copy of a preset has changed since the plan was built; the values the plan carries are what apply writes. |
| `preset.no-library` | Channels or busses name presets, but no preset library is configured and the plan carries none of their values, so they are built without that processing. |
| `preset.not-expanded` | A channel or bus names a preset the library has, but the plan carries none of its values, so nothing from that preset is written. |
| `preset.overridden` | The plan's own processing sets a value its preset also sets; the plan's value is the one written. |
| `preset.stale-expansion` | A strip carries the values of one preset but names a different one, or none; the values it carries are what apply writes. |
| `preset.unknown` | A channel or bus names a preset that is not in the library, so it is built without it; close names in the library are suggested. |
| `preset.unreadable-library` | The preset library cannot be read, so no preset named in the plan can be found. |
| `preset.value-not-on-strip` | A preset makes a choice this kind of strip does not offer; the build carries the strip's equivalent, or leaves it out so the strip keeps its current value. |

## Apply, Patch and Undo

Writing to the desk: the Apply pre-flight and run, a live change, and undo.

| Code | What it means |
|---|---|
| `amend.socket-missing-on-box` | A change would patch sockets past the end of the stage box connected on that AES50 port, so it is refused and nothing is written. |
| `amend.socket-missing-on-desk` | A change or amend would patch sockets this desk does not have, so it is refused and nothing is written, even with --skip-verify. |
| `amend.verify-failed` | The changed or rebuilt plan fails verification against this desk, so nothing is written; each error is listed alongside. |
| `apply.aborted` | An apply stopped part way, because the desk stopped answering or Stop was pressed; the journal records every write that reached the desk, and undo takes them back. |
| `apply.cross-model` | The plan was built for a different WING model than this desk, but every socket it patches exists here, so it is applied and verified against the desk's model. |
| `apply.desk-model-unmeasured` | The desk did not report a WING model Atoo knows, so sockets were checked only against the plan's model; the apply goes ahead and reads every write back. |
| `apply.failed` | The apply command did not run at all; the message carries its last words, and the run log on the Apply screen has the rest. |
| `apply.init` | Before writing the plan, a full apply resets the desk to its initialized state, writing back only the settings that differ; the note gives how much it reads and writes. |
| `apply.init-no-capture` | A full apply cannot reset the desk to initialized first, because no initialized capture exists for this model; the plan is applied over what the desk holds. |
| `apply.init-off` | The reset to initialized is switched off (--no-init), so anything the plan does not write keeps whatever the desk holds. |
| `apply.journal-note` | A note the apply recorded in its journal while writing to the desk. |
| `apply.journal-warning` | A warning the apply recorded in its journal about something it wrote, or could not write, to the desk. |
| `apply.journalled` | The apply wrote to the desk and recorded each address with its previous value in a journal; undo with that journal reverses the run. |
| `apply.mismatch` | Some parameters did not land: the desk reads back a value other than the one written. Running the apply again retries only those. |
| `apply.replaces-changes` | A full apply would overwrite changes made on this desk that are not in plan.json: a channel a change dropped comes back, and one it added is left untracked on its strip. |
| `apply.socket-missing-on-desk` | The plan is for another WING model and patches sockets this desk does not have, so the apply refuses; rebuild for this desk or repatch. |
| `apply.talkback-assign` | The apply sets the desk's talkback assign (Setup, Audio) to the plan's talkback strip, or to OFF when the plan has none. |
| `apply.unbuilt-strips` | Strips the plan does not use are unpatched from their sources, so none listens to a socket the plan uses; a strip already unpatched is left alone. |
| `apply.undeclared-outputs` | Output sockets that no bus or output in the plan uses are disconnected, rather than left on whatever the desk or an earlier show put there. |
| `apply.unreadable` | Some addresses could not be read before writing, so they were skipped: a write with no known prior value could not be undone. |
| `preview.failed` | An apply preview did not finish, and nothing was written; the run log on the Apply screen holds the command's own output. |
| `undo.aborted` | An undo stopped part way, because the desk stopped answering or Stop was pressed; undo again finishes the reversal. |
| `undo.did-not-land` | Some reversals in an undo did not land: the desk does not read back the value that was sent. |
| `undo.failed` | An undo did not run; the run log on the Apply screen holds the command's own output. |
| `undo.partial` | An undo put back what it could and left some addresses as they are, because they changed since the write, could not be read, or had no earlier value. |

## A saved show file against the plan

What differs when the plan is compared with a show file saved from the desk.

| Code | What it means |
|---|---|
| `snapshot.d-membership` | The plan puts a strip in a DCA, but the show file saved from the desk does not have it there. |
| `snapshot.fader` | A strip's fader level in the show file saved from the desk differs from the level the plan starts it at. |
| `snapshot.field-not-found` | A value the plan sets (name, patch, fader or DCA and mute-group membership) cannot be found in the saved show file, so that part is not compared. |
| `snapshot.hpf` | A strip's high-pass frequency in the show file saved from the desk differs from the plan's. |
| `snapshot.hpf-off` | The plan sets a high-pass filter on a strip, but the show file saved from the desk has the filter switched off. |
| `snapshot.m-membership` | The plan puts a strip in a mute group, but the show file saved from the desk does not have it there. |
| `snapshot.mute` | A strip's mute state in the show file saved from the desk is the opposite of the plan's. |
| `snapshot.name` | A strip's name in the show file saved from the desk differs from the name the plan gives it. |
| `snapshot.no-console-index` | A DCA or mute group in the plan has no desk number, so membership in it cannot be compared with the saved show file; hand-written plans may lack them. |
| `snapshot.patch` | A strip's input in the show file saved from the desk is patched to a different socket than the plan's. |
| `snapshot.send-level` | A bus send level in the show file saved from the desk differs from the plan's. |
| `snapshot.send-mode` | A bus send's pre/post mode in the show file saved from the desk differs from the plan's. |
| `snapshot.send-off` | The plan sends a strip to a bus, but the show file saved from the desk has that send switched off. |
| `snapshot.strip-missing` | The plan uses a strip that the show file saved from the desk does not contain. |
| `snapshot.*-membership` | The plan puts a strip in a DCA (d) or mute group (m), but the show file saved from the desk does not have it there. |
