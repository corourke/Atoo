# Troubleshooting: writing to the desk

`apply`, `amend` and `undo` reached the desk but did not do what you expected. When the desk does not answer at all, see [`atoo` cannot reach the console](troubleshooting.md#atoo-cannot-reach-the-console).

## `apply` or `undo` looks like it has hung

**Look at the progress line on stderr before you stop it.** Each step that talks to the desk names itself and the address in flight:

```
  reading the desk for the reset 198/1988 (9%) 0s -- /io/in/SC/22 (node)
```

While the count moves, the run is working. If it sits on one address for about three seconds, the desk did not answer that request: each unanswered request is asked three times and waits a second each time. The line at the end of the step says how many went unanswered and names them. To see every request and reply, run it again with `--raw-log FILE`.

## A desk read is slow

Each long read ends with a line giving its count and its time:

```
  reading the desk for the reset: 2028 of 2028 addresses in 4.3s
  every address answered.
```

A request's round trip is almost all network: the desk itself answers in well under a millisecond. A wired link to the desk is a fraction of a millisecond; a busy or wireless one can be 15ms or more, and a read of two thousand requests one at a time at 15ms is half a minute.

So Atoo keeps several reads on the wire at once -- 8 by default -- and a read takes about **requests x round trip / 8**: two thousand requests at 15ms is about 4s rather than 30s. Turned round, **the time divided by the count, times 8, is roughly the round trip** -- 4.3s over 2028 requests is about 17ms. On a simulated desk 15ms away, the Demo show's `apply` preview (about 3,700 requests) takes 8s like this and about 60s one at a time.

- **Every address answered, but slow:** the network. Use a wired connection to the desk if you can. `ATOO_CONSOLE_WINDOW=16` keeps more reads in flight; if a read with 16 reports unanswered addresses that 8 did not, go back to 8.
- **Some addresses went unanswered:** each one cost the timeout and two retries (about 3s). With several in flight they wait side by side, so a handful costs about one address's 3s rather than 3s each, and the summary says that rather than adding them up -- `18 address(es) went unanswered, each waiting about 3s, up to 8 at a time` -- and names them.
- **The read reports unanswered addresses that one at a time does not:** the desk may be dropping requests when several arrive together. Run it again with `ATOO_CONSOLE_WINDOW=1`, which reads one at a time exactly as Atoo always did, and report it with the two summary lines -- that is a fact about the desk worth knowing. To keep it for every command in that terminal, `export ATOO_CONSOLE_WINDOW=1` there, and start `atoo ui` from the same shell so the browser's runs use it too: an Apply, Patch or Undo says `Using console window 1 from ATOO_CONSOLE_WINDOW` in its run log, and Watch's *This watch* line reads *Console window: 1, from ATOO_CONSOLE_WINDOW*. The window takes a whole number from 1 to 64; anything else is said on stderr (and in those same two places), and 8 (or 64) is used instead.

Writes are never sent several at a time: each setting is written, then read back, before the next, whatever the window.

## `apply` says a value did not land, but the desk shows it

```
APPLIED: 670 address(es) evaluated, 357 written, 1 mismatch(es).
  MISMATCH /ch/7/tags: expected '#D7,#M1', read back ''
```

**Check the desk first, and believe it over this message.** A mismatch means the console reported something other than the intended value when it was asked, and the reasons divide into two:

1. **The write really did not land.** The usual causes are a value the parameter cannot hold (out of range, wrong type -- WING accepts these silently on the unacked path and keeps what it had) and a parameter that is not writable in the desk's current state.
2. **The desk answered the question late.** A `set_param` write -- used for any string containing a space, comma or equals sign, so names like `VOX Delay` and tag strings like `#D7,#M1` -- is not acknowledged, so the readback goes out immediately and can be answered from the value the address held a moment earlier.

The second one is the message above, and it is what the console's next few datagrams settle: `apply` now reads them (matched by the address they name), and re-checks anything still in doubt after the last write of the run, so a value that lands late is reported as a match rather than a mismatch.

**To tell them apart on a run you already have**, look at the journal (its entry in the bundle's `journals/`, or wherever `--journal` put it):

- `"status": "mismatch"` with `"readback_value"` showing the *old* value and `"method": "param"` is the shape a late answer leaves behind.
- `"readback_source": "late_reply"` or `"recheck"` marks an address that only verified on the second look -- a desk answering slowly, not a failure, but worth knowing about if there are many.
- The summary's `note:` line counts the datagrams the console volunteered. A large count is normal under load (125 in one 670-address run); it does not invalidate the readbacks, which are matched by address.

**To diagnose it properly**, re-run with `--raw-log PATH` and search the log for the address. Every request and reply is there with its hex bytes, in order, which is how all three of these were identified in the first place. `atoo audit --console <ip>` also reads the live desk, so it is a second opinion that does not depend on the apply's own reading.

## `apply` says the console has nothing in a bay

```
192.0.2.16 reports NOTHING in the MOD bay (AoIP module: Dante/WSG), and this plan uses it 1 time(s):
  - channel 'Kick' from MOD 1
```

The plan patches a channel (or routes an output) through one of the console's two expansion slots — the rear-panel card `CRD`, or the internal AoIP module `MOD` — and the desk has just reported that slot empty. Atoo stops before writing anything.

**This is almost always a real problem, not a false alarm.** The desk does not refuse the patch itself: it answers all 64 `CRD`/`MOD` addresses whether or not hardware is fitted, accepts the write, and reads it back unchanged. The strip shows a patch, the journal says `match`, and the channel is silent. Atoo stopping is the only sign that anything is wrong.

Three things to check, in order:

1. **Is the card or module actually installed?** `MOD` is an option almost nobody has: a WING ships with that slot empty. Check the desk's own screen, or ask it: `atoo ping` does not report this, but the error above names the exact value the console gave.
2. **Is the plan naming the right bay?** `CRD` and `MOD` are two different slots and Dante is sold as both, so a plan built from an input list that said "Dante" may well name the wrong one. `CRD` is the rear-panel expansion card; `MOD` is the internal module. Fix it on the input list (`CRD 1`, not `Dante 1`) and rebuild.
3. **Is this the desk the plan was built for?** A plan written for a rig with a Dante card is correct, and correct nowhere else. Repatch to a group this console has — `LCL`, `A`/`B`/`C`, `SC`.

**There is no flag that overrides this**, and `--skip-verify` does not. That flag means "this plan has findings, write it anyway", which is a judgement about the plan; this is the console's own read-only report of what is plugged into it, and there is no second opinion to state. If you genuinely want the patch written into an empty bay, change the plan.

**If the console did not answer** the two addresses at all — old firmware, a dropped datagram — `apply` carries on rather than refusing. Silence is not the same claim as `NONE`.

## `apply` says a socket does not exist on this desk

```
ERROR: This plan is for a WING Compact, but 198.51.100.10 is a WING (full-size console), and 1 socket(s) the plan patches do not exist on the WING (full-size console):
  - LCL 20 (input) -- channel 'Kick'; LCL inputs are 1..8 on a WING (full-size console)
Refusing to apply: LCL 20 does not exist on the WING (full-size console) at 198.51.100.10. Rebuild for this desk (--console-model wing-full), or repatch to sockets it has.
```

The plan was built for one WING model and the desk on the line is another, and the plan patches at least one jack this desk does not have. Nothing was written. The three models differ in their local and aux I/O: the full-size WING has 8 local inputs and 8 aux in and out; the Compact and Rack have 24 local inputs and no aux jacks. A different model on its own is not a refusal — a Compact plan applies to a Rack, with an INFO saying so — only a missing socket is.

Rebuild the plan for this desk (`atoo build --console-model wing-full ...`), or repatch the listed channels and outputs to sockets it has. `--skip-verify` does not get past this: it is about the plan's findings, and this is about the hardware. See [A plan built for a different model](two-desks.md#a-plan-built-for-a-different-model).

## `amend` says a socket does not exist on this desk

```
ERROR: This amend would patch 1 socket(s) that do not exist on the WING (full-size console) at 198.51.100.10:
  - LCL 20 (input) -- channel 'Trumpet'; LCL inputs are 1..8 on a WING (full-size console); channel 'Trumpet', new on ch:21
The rebuild is for a WING Compact; this desk is a WING (full-size console).
Refusing to amend: LCL 20 (channel 'Trumpet', new on ch:21) does not exist on the WING (full-size console) at 198.51.100.10. Nothing was written; --skip-verify does not change that. Rebuild for this desk (--console-model wing-full), or repatch to sockets it has.
```

The same refusal as `apply`'s, above, worded for an amend: it names the strip the new channel *would* have gone on, and it checks only the sockets the amend writes — a new strip's patch and a new output's socket — not the running show. It fires on the same model too, not only across models. The preview says it, so it is seen before anything can be armed; on the Apply screen it is in the review's Pre-flight panel and the write will not arm.

Repatch the new channel in the rebuild to a socket this desk has, or rebuild for this desk, and preview again. `--skip-verify` does not get past it. See [The pre-flight](amend.md#the-pre-flight-the-same-checks-as-apply).

A typed change (`atoo patch`) is refused the same way, in its own words — `This change would patch 1 socket(s) that do not exist on …` and `Refusing to write this change: LCL 30 (…) does not exist on …` ("patch" there meaning the socket, as everywhere in Atoo). Say the change again with a socket this desk has.

**`Refusing to amend: the amended plan does not verify against …`** is the other pre-flight refusal: a verify error somewhere in the rebuild, listed above that line exactly as `verify` lists it ([`verify` says `BLOCKED`](troubleshooting-verify.md#verify-says-blocked-do-not-apply)). Fix the rebuild; or, if it is a finding you already wrote past with `apply --skip-verify`, pass `--skip-verify` to the amend too.

## `apply` warns that the desk's model has never been measured

```
WARNING: 198.51.100.8 calls itself 'wing-racksize', a model name Atoo has never measured on a real desk, so it cannot tell which WING this is. Sockets were checked against the plan's own model only, the WING Compact; a confirmed apply still reads every write back from the desk and proves it landed. The desk's own token is recorded in the journal (desk.model_token) -- once the model is known it is one line in console_facts.IDENTITY_MODEL_ALIASES.
```

Not a failure: the apply carries on. Atoo recognises a desk's model only from spellings read off a real console, and this one has not been seen yet. The plan was verified against the model it was built for, so a socket that model lacks has already been refused; what could not be checked is whether *this desk* has the same panel. Every write is still read back, so a patch that did not take shows as a mismatch rather than passing silently.

Please report the token (it is in the warning, in `atoo ping`'s output, and in the journal under `desk.model_token`), so it can become one line in `console_facts.IDENTITY_MODEL_ALIASES`.

## `undo` says "nothing more to undo on this desk"

```
nothing more to undo on this desk: my-show/journals keeps only the newest 5 entries. This desk's last write still journalled is
  2026-09-23T00:00:00+00:00  apply  APPLIED: 1 address(es) evaluated, 1 written, 0 mismatch(es).  [on no serial, at 198.51.100.7]
and the write beneath it was pruned (20261002T162704.453182Z-apply-198.51.100.7.json, apply). Undoing it would leave the desk holding a write no journal records, so amend and patch would compare against the wrong plan. Nothing was written. To change the desk from here, apply a plan (a full apply replaces everything) or patch it.
```

A bundle's `journals/` keeps only the newest **5** entries, so undo reaches back at most five writes. The write beneath this one is still on the desk, but its journal — the values undo would put back — was pruned; the run that pruned it said so at INFO (`... were pruned ... Undo now reaches back no further than the oldest entry kept`). Undoing the last journalled write would leave the desk holding something no journal records, and the next `amend` or `patch` would compare against the wrong plan, so undo refuses and writes nothing (exit code 1).

To go further back, put the desk where you want it another way: a full `atoo apply` of the plan you want replaces everything Atoo built, or `atoo patch` changes one thing. If a run must stay undoable for longer, copy its journal aside before five more writes go on the stack — `atoo undo <that copy>` still reads it, under the usual guards. See [How far back undo reaches](journals.md#how-far-back-undo-reaches-the-newest-5).

The same limit gives two related refusals: `patch --promote` on a change whose journal was pruned (it quotes the change's text, to add to `instructions.md` by hand), and the redo of an undo whose run was pruned.

## See also

- [Troubleshooting](troubleshooting.md) — every symptom, and the page it is on
- [Applying a plan](applying.md) — the result words
- [The journal](journals.md) — what the journal records
- [Undoing a write](undo.md)
