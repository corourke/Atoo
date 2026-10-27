<!-- GENERATED FILE -- edit the preamble blocks only.

     Every option table below comes from `atoo/cli.py`'s argparse
     tree, by a script in the development repository. Editing a table
     by hand will be overwritten there.

     Text inside a `<!-- preamble:start/end -->` block IS hand-written
     and is preserved across regeneration. Put the "why you would use
     this" there.
-->

# Command reference

Every command and every option, generated from the code so it cannot
drift. For how to *use* these together, start at
[`README.md`](README.md).

<!-- preamble:start -->
`a2` is a short spelling of `atoo`: the same program, so `a2 build`
and `atoo build` are one command. This page writes `atoo` throughout.

`atoo --version` (or `a2 --version`) prints which copy of Atoo is
running, and exits `0`: the version, the folder the code runs from and,
for a git checkout, its branch, short commit and whether tracked files
have uncommitted changes, then the Python it runs on. It is not an option
of any command, so it is not in the tables below.
[Which atoo am I running?](install-from-checkout.md#4-which-atoo-am-i-running)
reads it.

Every command that reads or writes a desk or calls a model (`build`,
`apply`, `patch`, `amend`, `undo`, `ping`, `audit`, `watch`, `resolve`)
prints the same first line on stderr, `atoo 0.2.5 (running from ...)`, before it does
anything else, so the output of a run that went wrong always says which copy
produced it.

## Exit codes

This is the canonical statement; everywhere else in the docs points here.
Exit codes are not argparse options, so they are not in the tables below.

| code | what it means |
|---|---|
| `0` | it ran, and there is nothing to report |
| `1` | it could not run -- a file it could not read, a desk that did not answer, a connection that dropped mid-run. **Plus, for `audit` and `watch` only, "it ran and found errors"** |
| `2` | it ran and found problems -- `build`, `verify`, `compare`, `apply`, `patch`, `amend`. **Also** any command line that was rejected before a command started |

One more `1`, for every command: when whatever is reading the output stops
early (`atoo --help | head`, or quitting `less`), the command stops
quietly with `1` -- no traceback, since nothing went wrong but the cut.

There is no single sentence that covers all eleven commands, so here is
each one. "Found problems" is the outcome worth scripting against, and
which code carries it depends on the command:

| command | "it ran and found problems" is... | meaning |
|---|---|---|
| `build` | `2` | verification found errors. The plan is still written, so you can read and fix it |
| `verify` | `2` | one or more errors. Warnings alone are still `0` |
| `compare` | `2` | the snapshot differs from the plan on a field the plan states |
| `apply` | `2` | something did not land, or it refused to proceed before writing anything |
| `patch` | `2` | the change was refused (it named something that is not there, a field the object does not carry, or a value out of range), a channel could not be placed, the pre-flight refused, something did not land, or an address belonging to a strip the change does not own moved across the write. A model that could not be reached, or answered with something that is not a change set, is `1` |
| `amend` | `2` | a channel could not be placed, the rebuild tried to renumber a running strip, something did not land, or an address belonging to a strip the amend does not own moved across the write |
| `audit` | **`1`** | a finding at error severity. Warnings and info alone are still `0` |
| `watch` | **`1`** | the last pass had a finding at error severity -- an audit rule or one of your own [watch conditions](watch-conditions.md) |
| `ping` | n/a | it has nothing to find. `0` if the desk answered, `1` if it did not |
| `presets` | n/a | it reports library problems but none of them blocks a build, so `0` either way. `1` only if the library is not there to read, or, with `--expand`, the plan cannot be read or written |
| `ui` | n/a | `0` when the server stops, and when an Atoo UI was already serving on the port (it is opened instead). `1` if it could not start -- the `[ui]` extra is not installed, a plan or watch-conditions file would not load, or something else is using the port |
| `init` | n/a | `0` when it is done, including when there was nothing to do. `1` if the folder or a config value could not be written |
| `resolve` | `2` | the resolved conventions are usable but the check found a quote that is not there -- or, with `--check`, the file is stale. A conventions line no rule covers is only a note (the generator is given it as written), and leaves it `0`. `1` when there is no usable file: missing, refused (empty, or nothing it cites is found), or the model call failed |

### Why `audit` and `watch` stay at `1`

It is a deliberate split, not an oversight.

The commands on `2` all hold a plan: they compile one, check one,
compare a desk against one, or write one. For those, "the plan and the
desk disagree" is a genuinely separate outcome from "I could not do the
job at all", and it is worth a code of its own.

`audit` and `watch` hold no plan. They are read-only readings of whatever
a desk currently is, against a fixed rule catalogue, and reporting
something is the ordinary result rather than the exceptional one. They
are a different kind of command, and they keep the code they have always
returned.

### Telling the two meanings of `1` apart

`audit` and `watch` return `1` both for "found errors" and for "could not
run", so `$?` alone does not separate them. **What does: stdout.**

- A run that never started prints its reason on **stderr** and writes
  **nothing at all** to stdout -- `couldn't read state file 'nope.json':
  No such file or directory`.
- A run that did its job prints to **stdout** -- `Audit findings: 1
  error, 9 warning, 6 info.` from `audit`, and from `watch` its
  `Watching ... every Ns` banner followed by a baseline and a line per
  pass.

So `out=$(atoo audit --state s.json)` followed by a test on whether
`$out` is empty distinguishes the two, and `atoo ping` first
separates "the desk is unreachable" from either. (Do not test stderr
instead: a run that resolved its console from the environment or from
`~/.atoo.config` prints where it came from there, on a perfectly good run.)

### A rejected command line exits `2`, not `1`

`2` is argparse's own code for a command line it will not accept, and
Atoo does not override it. An unknown flag, a missing required
option, a value that will not parse (`--interval notanumber`), an unknown
subcommand: all `2`, from every command, including `audit` and `watch`.

**"No console address" is `2` for the same reason.** The message that
`ping`, `apply`, `amend`, `audit` and `watch` print when none of `--console`,
`$ATOO_CONSOLE` and `~/.atoo.config` supplies one replaced
argparse's own `required=True` error, and kept its code so a script that
tested for it keeps working.

Atoo's *own* "you have to tell me which file" errors are `1`, not
`2` -- `atoo verify` with neither `--plan` nor `--show`, `atoo
apply` the same. Those are cases argparse no longer rejects, because the
flag stopped being `required=True` once `--show` could supply it.

### In a script

```bash
atoo audit --show touringband --console 192.0.2.16
case $? in
  0) echo "clean, or warnings and info only" ;;
  1) echo "errors found -- or it could not run. Read stdout to tell which" ;;
  2) echo "the command line was rejected, or no console address was given" ;;
esac
```

```bash
atoo apply --show touringband --console 192.0.2.16 --confirm
case $? in
  0) echo "every value landed" ;;
  1) echo "could not run -- check the address and the plan path" ;;
  2) echo "ran, and something is wrong -- read what it printed" ;;
esac
```

## Environment variables

None of these are argparse options, so none appear in the tables below.

They come in two unrelated groups.

### Pointing commands at a console

`--console <ip>` otherwise has to be retyped on every `ping`, `apply`,
`amend`, `audit` and `watch`. Set it once instead:

```bash
export ATOO_CONSOLE=192.0.2.16
atoo ping
atoo apply --show touringband --confirm
```

| Variable | Applies to | Default |
|---|---|---|
| `ATOO_CONSOLE` | `ping`, `apply`, `amend`, `audit`, `watch` | -- |
| `ATOO_CONSOLE_PORT` | the same five | `2223` |
| `ATOO_CONSOLE_TIMEOUT` | the same five | `1.0` seconds |
| `ATOO_CONSOLE_WINDOW` | every command that reads a console, and the Watch page | `8` reads in flight at once; `1` reads one at a time |

**Precedence:** an explicit `--console` beats the environment, which
beats a `[console]` section in `~/.atoo.config`, which beats the
built-in default. `atoo ui` is not in the list: its console address
is typed into the browser, and its own `--port` is the web server's.

**A run that was not told its console on the command line says where it
got one**, on stderr, once:

```
Using console 192.0.2.16 from ATOO_CONSOLE
Using console 192.0.2.16 from /home/you/.atoo.config [console]
```

That line is the point of the feature as much as the convenience is. The
failure it prevents is a stale `export` in a shell, left over from last
week's desk, on a command carrying `--confirm`.

The config-file form suits a desk you always use, where the environment
variable suits a session:

```toml
[console]
default = "192.0.2.16"
port = 2223
timeout = 1.0
```

Every key is optional and independent -- a port with no address is a
perfectly reasonable thing to set.

`ATOO_CONSOLE_WINDOW` is set in the environment only, not in the
config file. It is how many reads Atoo keeps on the wire at once
while it reads the desk -- the reset's read, a preview, `audit`, `watch`,
`patch`'s and `amend`'s reads -- so a read takes about requests x round
trip / window instead of requests x round trip. It is at most 64. Writes, and the
readback of each write, are always one at a time. `1` is the old
one-at-a-time read, exactly; a run with any other value than `8` prints it
on stderr (`Using console window 1 from ATOO_CONSOLE_WINDOW`) -- and
from the page, in the run's log on the Apply screen, or as a *Console
window* note on Watch's *This watch* line. See
[A desk read is slow](troubleshooting-desk.md#a-desk-read-is-slow).

### Choosing and tuning the model

Most configure the AI provider that `atoo build` uses to generate a
plan, and that `build --critic` uses for the review pass. Every other
command ignores those entirely -- `verify`, `compare`, `apply`, `audit`
and `watch` never call a model. The one exception is the OSC variable at
the bottom of the table, which applies to every command that talks to a
console and to none that do not.


| Variable | Applies to | Default |
|---|---|---|
| `ATOO_AI_PROVIDER` | all | `claude` (needs `ANTHROPIC_API_KEY`) -- or `ollama` for a local model, or `api` for any OpenAI-compatible host |
| `ATOO_AI_MODEL` | all | `claude-sonnet-5-5` / `llama3.1` / `gpt-4o-mini` |
| `ATOO_AI_API_KEY` | claude, api | -- (`claude` also reads `ANTHROPIC_API_KEY`) |
| `ATOO_AI_BASE_URL` | all | per provider |
| `ATOO_AI_NUM_CTX` | ollama | unset = sized per prompt |
| `ATOO_AI_NUM_PREDICT` | ollama | unset = unlimited (`-1`) |
| `ATOO_AI_TIMEOUT` | ollama, api | `120` seconds on ollama, `600` on api (a reasoning model can think for minutes before its first token) |
| `ATOO_AI_EFFORT` | claude | `medium` (`low`...`max`) -- the generator's |
| `ATOO_AI_CRITIC_EFFORT` | claude | `medium` (`low`...`max`) -- the critic's (`--critic`) |
| `ATOO_AI_WATCHLIST_EFFORT` | claude | `medium` (`low`...`max`) -- the watchlist draft's. None of the three is sent to Haiku 4.5, which takes no effort |
| `ATOO_AI_CRITIC_MODEL` | claude | `claude-sonnet-5-5` -- the model the critic (`--critic`) runs on; set it to `ATOO_AI_MODEL`'s value to run it on the generator's |
| `ATOO_AI_WATCHLIST_MODEL` | claude | `claude-sonnet-5-5` -- the model the watchlist draft runs on, likewise. Both announced on the `INFO model and effort by role` line |
| `ATOO_AI_RESOLVE_MODEL` | claude | `claude-sonnet-5-5` -- the model the resolve step runs on (`atoo resolve`, and `build` when the resolved conventions are missing or stale) |
| `ATOO_AI_RESOLVE_EFFORT` | claude | `medium` (`low`...`max`) -- the resolve step's |
| `ATOO_RESOLVE` | build | on -- `0` is `build --no-resolve`: the generator reads the raw conventions and the domain knowledge, not `<conventions>.resolved.md` |
| `ATOO_AI_FIXUP_ROUNDS` | all | `1` -- when a built plan fails verify with errors, or the reply fails the format check, the reply and the exact messages go back to the generator's model once (role `fixup`, the generator's model and effort) for a corrected reply; `0` turns it off, and more than one round is never spent |
| `ATOO_AI_THINKING_BUDGET` | claude | `16000` -- `budget_tokens` for the generator on a model that thinks only when given a budget (Haiku 4.5); `0` turns it off. Ignored on the adaptive-thinking models; never sent to the critic or the watchlist |
| `ATOO_AI_MAX_TOKENS` | claude | the model's output limit: `128000`, or `64000` on Haiku (thinking tokens count against it). A role on a model with a lower limit is sent that limit |
| `ATOO_AI_THINKING_SUMMARIES` | claude | on -- `0` stops asking for the thinking summaries step 04 shows while the model thinks |
| `ATOO_AI_STREAM` | api | on -- `0` asks the host for one reply instead of a stream (step 04 then has no live text) |
| `ATOO_AI_PRICE_IN`, `ATOO_AI_PRICE_OUT` | api | unset = the usage line says `no price set`. Dollars per million input and output tokens; both or neither. They add the `-- $x.xx` a Claude call prints and the build log's cost. A host that reports its own cost (xAI's `cost_in_usd_ticks`) is believed instead, and the line names it |
| `ATOO_AI_PRICE_CACHED` | api | unset = cached input is priced as ordinary input. Dollars per million cached input tokens, used when the host reports them (`prompt_tokens_details.cached_tokens`) and the two prices above are set |
| `ATOO_PROMPT_DIR` | generate, critic | the packaged `atoo/prompts` |
| `ATOO_OSC_REPLY_MATCH` | apply, audit, watch, compare, ui | on -- set to `off` to disable reply matching |

**`ATOO_OSC_REPLY_MATCH=off` is an escape hatch, not a tuning knob.**
UDP does not pair a reply with its request, so the client checks that a
reply carries the address it asked for and drains anything else. Without
that check, one duplicated datagram from the console makes every
subsequent read return the *previous* read's value, silently and for the
rest of the session. On one real run, 880 of 1142 reads were answered by
the wrong leaf and the journal recorded 188 mismatches that had not
happened.

Setting it to `off` restores the old take-the-next-datagram behaviour. The
only reason to do that is a console that answers on an address this client
does not predict, leaving reads timing out where they used to work. If you
ever need it, that is worth reporting -- and a run made with it off cannot
prove anything landed.
<!-- preamble:end -->


## `atoo amend`

<!-- preamble:start -->
The same as `atoo patch --amended-plan FILE`, kept under this name
with every flag it had: the change is a rebuilt plan rather than typed
words. See
[Patching from a rebuilt plan](amend.md).
<!-- preamble:end -->

```
Change a console from a REBUILT plan -- the same as `atoo patch
--amended-plan`, kept under this name so existing scripts keep running.

  atoo amend --show ./touringband --amended-plan ./touringband/rebuilt.plan.json --console 192.0.2.16
  atoo amend --show ./touringband --amended-plan ./touringband/rebuilt.plan.json --console 192.0.2.16 --confirm

The horn section has turned up late in the setup window, the show is already
built on the desk and there is a mix on it. `apply` would write the whole plan,
every fader included. `amend` reads which strips are free, places only the new
channels on them, and writes only those. To type the change in plain English
instead of rebuilding, use `atoo patch`.

This is a setup and rehearsal tool -- use it before doors, not during the show.
Save a console snapshot once the board is patched and a bad amend costs you a
reload rather than the rest of your setup time.

The same operation covers a vocalist who has left and a set of delay speakers
dropped from the rider. A channel the rebuild DROPPED is RETURNED TO FREE --
unpatched (OFF, as a full apply leaves a strip the plan does not use, with an
INFO), left unmuted, its fader at -inf, and its name, colour and icon cleared on the strip
and on the source socket -- only where the desk still reads as the strip your
plan built: a strip somebody has renamed, repatched or named on its SOURCE
socket since is reported and left exactly as it is, and so is one that did not
answer. A change to a strip that is still in the plan and still running is
reported and never written -- a full build is how one of those changes.

Four stages, and the first three change nothing:
  1. read the desk -- about 200 addresses, not audit's full sweep: a name, a
     link-to-source flag and an input patch per strip, plus the name of every
     socket a strip is patched to, which on a WING is where a name somebody
     typed by hand actually lives. A strip that does not answer counts as
     OCCUPIED, and so does one whose SOURCE carries somebody's name.
  2. work out the delta against the plan on the desk, placing new channels on
     free strips, skipping occupied ones and never renumbering a running one.
  3. show what will be written AND what will not -- the target filter, not a
     fader flag, is what keeps the running show still.
  4. with --confirm, write the new strips and clear the dropped ones, read every
     unrelated address before and after to prove none of them moved, and
     journal the run with the scope it was allowed.

Before step 4 -- and in the preview -- amend runs apply's pre-flight: the amended
plan is verified against the desk's model (errors refuse, warnings do not;
--skip-verify skips this, as on apply), and every socket the amend WRITES is
checked against the desk's panel. A socket the desk does not have (LCL 20 on a
full-size WING) is REFUSED, --skip-verify or not.

plan.json is NOT replaced: only a build writes it.
What is on the desk is recorded in that desk's journal entry, which the next
amend or patch of the desk compares against -- so amending again from the same
rebuild still finds nothing to add. `atoo undo` takes the amend off again.

--state FILE reviews the whole thing offline against a saved capture, contacting
no console at all. Exit 2 means it ran and found problems: a channel that could
not be placed, a strip the rebuild tried to renumber, a pre-flight refusal, a
readback mismatch, or an unrelated address that moved.
```

| Option | What it does |
|---|---|
| `--amended-plan` `FILE` | The rebuild: the same show, built again from the same conventions with the change in it (three horn rows added to input.csv, a line in instructions.md). `atoo build` produces it; amend works out what is new in it and writes only that. The same as `atoo patch --amended-plan`. |
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--plan` | The plan that is ALREADY on the desk. Normally left out: with --show, it is the plan the desk's own newest journal entry left on it, else the bundle's plan.json. |
| `--console` | Console IP address -- read which strips are free from the live desk. Falls back to $ATOO_CONSOLE, then to a [console] default in ~/.atoo.config -- a run that uses either prints where the address came from, on stderr. |
| `--state` | A JSON object of address -> value (the same shape `audit --state` takes) -- work out the delta from that instead of a live console. Reviews the whole amendment offline; it can never write. |
| `--port` `VALUE` | Console OSC port (default: 2223) |
| `--timeout` `VALUE` | Per-request timeout in seconds (default: 1.0) |
| `--channels` `VALUE` | Channel strips to read occupancy for (default: 40, WING Compact) |
| `--aux` `VALUE` | Aux strips to read occupancy for (default: 8, WING Compact) |
| `--allow-strip` `BANK:N` | Let the amend place a new object on one strip the desk says is occupied or did not answer, e.g. --allow-strip ch:20. Per strip and repeatable; there is deliberately no 'allow everything' switch. A strip the plan on the desk owns can never be opened this way. |
| `--confirm` | Actually write. Without this, amend is a preview that changes nothing -- the same arming `apply` requires, on the same reasoning. This ONE flag arms everything the preview showed, including returning a dropped channel's strip to free; there is deliberately no second switch for the clears, because a second switch is a second thing to tick past. |
| `--journal` | Where to record every write with its prior value AND this run's scope -- which strips it was allowed to touch. Defaults to a new timestamped entry in the bundle's journals/ directory, or <plan>.amend-journal.json without --show. With --show, a confirmed run is added to the bundle's journals/ stack whatever this says, with the plan it left on the desk. |
| `--skip-verify` | Write without the pre-flight verify of the amended plan -- the same gate, and the same escape, as `apply --skip-verify`: without it, a verify ERROR refuses the amend (warnings never do). It does NOT skip the socket check: a socket this amend would write that the desk does not have is refused either way. |
| `--skip-untouched-proof` | Do not read every unrelated address before and after the write. That read is the PROOF that nothing already in use moved -- not merely the absence of a write to it. It should rarely be worth skipping now: a PREVIEW never runs it at all (it writes nothing, so there is nothing to prove), and a --confirm run reads the set through the node-dump path -- about 140 requests rather than 670, roughly 1.4s a pass on a Compact. This flag only affects a --confirm run, and skipping leaves that run resting on the target filter alone. |
| `--per-leaf` | Read the before/after untouched-strip proof one request per leaf instead of by node dump -- about 670 requests a pass rather than 140, roughly 4-5x slower. The diagnostic path, as on audit and watch: the two read paths agreed on every value compared on a real WING Compact. The occupancy read is per-leaf either way. |
| `--review-json` `FILE` | Also write the review -- every strip's occupancy verdict, the delta, and what will and will NOT be written -- as JSON to FILE, using the same words the command prints. Written before any refusal, so a blocked amend still says why; a --confirm run adds the untouched-strip proof after the write. `atoo ui`'s Patch screen reads it. |
| `--no-progress` | Do not print what the run is doing while it reads and writes the console. Each long phase -- reading the desk (a preview reads the reset's settings and the plan's in one pass), writing (each setting is read back as it is written), reading back again what disagreed -- normally prints its name, how far it has got and the address in flight on stderr as it goes, and a line with its count and time when it ends. Without it a slow run looks like a hung one, so pass this only when something downstream is parsing stderr. |

## `atoo apply`

<!-- preamble:start -->
Every command's exit codes, in one table: [Exit codes](#exit-codes).
<!-- preamble:end -->

```
Write a plan to a console, then read every value back.

  atoo apply --plan band+rules.plan.json --console 203.0.113.50
  atoo apply --plan band+rules.plan.json --console 203.0.113.50 --confirm

The first form changes nothing: it reads the console's current value for every
address the plan would touch and shows you the before/after. Writing requires
--confirm. It reads every address again before its writes and sends only
those that differ, so the number written is the number the preview said would
change (unless the console moved in between); each is journalled with its prior
value so it can be reversed.

Every address written is read back afterwards -- remote console writes can fail
silently, so an acknowledgement is not proof. Anything that didn't land is
reported by address, and the command exits 2 -- the code build, verify, compare
and apply use for "it ran and found problems", as against 1 when the command
could not run at all. audit and watch report their own findings
with 1, not 2. The exit-code table is at https://docs.atoo.app/reference/cli-reference/

Before writing, apply asks the desk what is in its two expansion bays
(/cards/$type and /$syscfg/opt_mod) and REFUSES a plan that patches from or to
one the console reports empty. A WING answers all 64 CRD and MOD
sockets whether or not a card or module is fitted, and accepts the patch either
way, so nothing else -- not the readback, not the journal, not audit -- would
tell you the channel is silent.

It asks what is on each AES50 port the plan uses (/$stat/A/dev) and REFUSES a
socket past the end of the stage box there: an S16 has 16 inputs and 8 outputs,
and A 17 is patched to nothing though the desk lists 48 on every port. A box
whose size Atoo has not recorded is reported and its sockets are not checked.

ONE PLAN, TWO MODELS. The desk states its own model on /?, and apply compares it
with the plan's. A different model whose panel has every socket the plan patches
-- a Compact plan on a Rack backup -- is applied, with an INFO naming both and the
verify re-run against the desk's model. A socket the desk does not have (LCL 20 on
a full-size WING) is REFUSED, each one named, --skip-verify or not. A desk whose
model Atoo has never measured is applied with a WARNING, sockets checked
against the plan's model only, and its token journalled as desk.model_token.
--console-model states which model to check the plan for.

THE WHOLE DESK. Every channel and aux strip the plan does not build is unpatched
(its /in/conn/grp set to OFF, nothing else), so none listens to a socket the plan
uses; a strip already OFF is not written. A talkback strip the plan builds on
ch 40 or aux 8 sets Setup -> Audio's talkback assign (/cfg/talk/assign) to
CH40/AUX8. One INFO line says each; both are journalled, so undo reverses them.
amend and patch never do either.

INITIALIZED FIRST. Before the plan, a full apply puts the desk into
its initialized state: it reads the desk by node dump and writes back, from an
initialized capture of the desk's model, every setting that differs -- except the
ones the plan sets itself, and a skip-list (network, clock, expansion cards,
meter/RTA display, monitor/solo listening). One INFO line counts it by area and
says how long it took; every write is journalled, so undo reverses it. A desk whose
model Atoo has no capture for gets a WARNING and the plan is applied without the
reset. --no-init skips it, for a desk already initialized by hand.

A plan may state a strip's parametric EQ: a channel's
processing.eq, and a bus's or a Main/Matrix's own processing.eq/tilt_db. Stating
any EQ value turns that strip's EQ on, the way stating a high-pass does. A band a
strip does not have -- a channel has four numbered bands, a bus six -- is reported
and skipped rather than written to an address the console does not answer.

A full apply also disconnects every output socket on the desk's own panel that no bus,
Main or Matrix in the plan is patched to, rather than leave it on what the desk shipped
with or an earlier show put there; one INFO line names the sockets and undo restores them.

--clean-output-sockets NAME=COUNT,... extends that to the groups beyond the panel, such
as a stage box's: it disconnects any physical output socket in the given group(s)
that no bus or output in the plan routes anywhere to, instead of leaving whatever was
already patched there.
```

| Option | What it does |
|---|---|
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--console-model` | Which WING this plan is for. Required unless the plan already states it in meta.console_model (a plan built by Atoo does). Socket counts differ between models, so an unstated model is an error rather than an assumption. |
| `--plan` | A plan JSON produced by `atoo build`. Required unless --show supplies it. |
| `--input` | The input list the plan was built from. Optional, but without it the checks that need it are skipped: that every input became a channel, that no channel was invented, and that phantom power is safe for the microphones in use. |
| `--presets` `DIR` | Atoo's own preset library: a directory of .chn channel-preset exports, looked up by the name inside the file. These are NOT the console's own presets or scenes -- those cannot be recalled remotely at all -- they are parameter values Atoo writes like any other. `build` expands each named preset INTO the plan (its processing values, the plan's own processing winning where both set one), and `apply` writes what the plan carries; verify and apply use the library only to say whether it changed since. A plan naming a preset this library hasn't got is a warning, never a block. Defaults to [presets] default in ~/.atoo.config. |
| `--skip-verify` | Apply the plan without verifying it against the console's limits first. Verification runs before the console is contacted; skipping it means an impossible plan reaches real hardware. |
| `--console` | Console IP address. Falls back to $ATOO_CONSOLE, then to a [console] default in ~/.atoo.config -- a run that uses either prints where the address came from, on stderr. |
| `--port` `VALUE` | Console OSC port (default: 2223) |
| `--timeout` `VALUE` | Per-request timeout in seconds (default: 1.0) |
| `--confirm` | Actually write to the console. Without this, apply is a preview that changes nothing. |
| `--journal` | Where to record every write with its prior value, enough to reverse this apply. Defaults, when --confirm is given, to a new timestamped entry in the bundle's journals/ directory, or to <plan>.apply-journal.json without --show. With --show, a confirmed run is added to the bundle's journals/ stack whatever this says, so `atoo undo --show DIR` can walk the show back one step at a time. |
| `--raw-log` | Append every raw OSC request/reply (address, typetag, args, hex bytes) to this file. Useful when a reported mismatch needs the literal reply bytes to diagnose, not just the extracted value the journal records. |
| `--no-init` | Do not reset the desk to its initialized state before writing the plan -- for a desk already initialized by hand. By default a full apply reads the desk and writes back, from the model's initialized capture, every setting that differs and that the plan does not set itself. |
| `--clean-output-sockets` | Disconnect (`.grp = OFF`) any physical output socket in the given group(s) that no bus or output in the plan routes anywhere to, instead of leaving whatever was already patched there (e.g. from an earlier apply, a different show, or manual patching). A full apply already does this by default for the desk's own panel outputs; this reaches the groups beyond them, such as a stage box's. Same 'no confirmed default' syntax as `atoo audit`'s --output-sockets: 'LCL=24,A=48'. A socket ALREADY undeclared and already disconnected costs one read and nothing else. Shown in the dry-run preview like every other write -- `--confirm` is what actually arms it, same as the rest of apply. |
| `--no-progress` | Do not print what the run is doing while it reads and writes the console. Each long phase -- reading the desk (a preview reads the reset's settings and the plan's in one pass), writing (each setting is read back as it is written), reading back again what disagreed -- normally prints its name, how far it has got and the address in flight on stderr as it goes, and a line with its count and time when it ends. Without it a slow run looks like a hung one, so pass this only when something downstream is parsing stderr. |

## `atoo audit`

<!-- preamble:start -->
_Not written yet._
<!-- preamble:end -->

```
Audit a console's live state against deterministic structural rules, and
optionally trace a signal path across it. Every finding names its rule
by an ID that does not change when the wording does.

  atoo audit --console 203.0.113.50
  atoo audit --state ~/Documents/Atoo/audit-demo/audit_demo_state.json
  atoo audit --state ~/Documents/Atoo/audit-demo/audit_demo_state.json --trace-from input:LCL:3 --trace-to output:LCL:1
  atoo audit --state ~/Documents/Atoo/audit-demo/audit_demo_state.json --plan ~/Documents/Atoo/audit-demo/audit_demo_plan.json

Read-only either way -- nothing here writes to a console. Every finding cites the
specific rule it violated (its ID), never an inferred channel type: this audit works
from confirmed routing/patch/mute/fader facts only, the same address scheme `apply`
writes to, and never guesses what a channel is from its name.

--state takes a JSON object of OSC address -> value, the same shape a live read
produces -- try it with no console attached at all via the demo state `atoo init`
copies into your working folder, ~/Documents/Atoo/audit-demo/audit_demo_state.json
(run `atoo init` first if it is not there; if you chose another --dir, use that folder).
--dump-state FILE writes that shape: a live read saved, to be audited again offline.

  atoo audit --console 203.0.113.50 --dump-state tonight.state.json
  atoo audit --state tonight.state.json --plan my_show_plan.json

--plan adds the conventions-diff audit: compare live state against what a
plan (a `atoo build` JSON output) says a channel's mute, fader level,
DCA/mute-group membership, patch, bus sends, direct-to-Main routes, and the
trim/balance/invert/head-amp-gain, high-pass/hi-cut/tilt and EQ a channel states should
be, so a finding can cite the plan's own provenance text instead of just a structural
fact. A filter or an EQ band is compared within 2%, the desk holding the nearest step of
the control; a bus's, Main's and Matrix's EQ and a channel's PreSend EQ are diffed
the same way. The compressor is not diffed.
--plan also flags (CV009) any
physical output socket --output-sockets read that's patched to something the plan
never routes there at all -- catches stray/leftover routing an apply run never wrote,
same finding `apply --clean-output-sockets` can act on. --plan is independent of
--console/--state: it works on top of whichever live state source you picked.

--plan also makes the report SHORTER, not just longer. A finding
about a strip, bus or socket the plan never mentions is withheld unless its rule is one
that matters on any desk, and any finding about a parameter the plan itself states is
withheld too, because the conventions diff already checks that parameter against what
you asked for. Hazards are never withheld for being outside the plan: 48V on an
unpatched socket, a mix reaching no loudspeaker, a routed strip sitting silent. Nothing
goes quietly -- S001 at the end of the report counts what was withheld and why, and
running without --plan shows everything the rules produced.
```

| Option | What it does |
|---|---|
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--console` | Console IP address -- read its live state and audit that. Falls back to $ATOO_CONSOLE, then to a [console] default in ~/.atoo.config -- a run that uses either prints where the address came from, on stderr. |
| `--state` | A JSON object of address -> value (an offline capture, or a hand-built demo -- try ~/Documents/Atoo/audit-demo/audit_demo_state.json, which `atoo init` copies) -- audit that instead of a live console. Lets a novice operator try this with no console attached at all. |
| `--port` `VALUE` | Console OSC port (default: 2223) |
| `--timeout` `VALUE` | Per-request timeout in seconds (default: 1.0) |
| `--channels` `VALUE` | Channel strips to read (default: 40, WING Compact) |
| `--aux` `VALUE` | Aux strips to read (default: 8, WING Compact) |
| `--buses` `VALUE` | Busses to read (default: 16, WING Compact) |
| `--mains` `VALUE` | Mains to read (default: 4, WING Compact) |
| `--matrices` `VALUE` | Matrices to read (default: 8, WING Compact) |
| `--dcas` `VALUE` | DCAs to read (default: 16, WING Compact) |
| `--mute-groups` `VALUE` | Mute groups to read (default: 8, WING Compact) |
| `--input-sockets` | Physical input socket counts to read phantom power from, e.g. 'LCL=20,A=48'. Omit and Atoo reads the panel of whichever model the desk says it is, plus every group the --plan patches from. Pass this to override that. |
| `--output-sockets` | Physical output socket counts to read patch state from, e.g. 'LCL=16'. Omit and Atoo reads the panel of whichever model the desk says it is, plus every group the --plan patches to. Pass this for a stage box or a card the plan does not mention. The report says which sockets it read. |
| `--raw-log` `FILE` | Append every raw OSC request and reply to FILE, exactly as `apply --raw-log` does -- the literal bytes, not the values made of them. For a read that is slow or comes back short: the progress line says how many addresses went unanswered, and this says which. Written line by line, so a read stopped with Ctrl-C still leaves a complete log. Live reads only. |
| `--no-progress` | Do not print the progress line while reading the console. A live read is a few hundred requests (thousands with --per-leaf) and normally reports 'read 120/323 (37%%) 2s -- /io/in/USR/44 (node)' on stderr as it goes, plus how many addresses went unanswered at the end. Without it a slow read looks like a hung one, so pass this only when something downstream is parsing stderr. |
| `--per-leaf` | Read the console one request per leaf -- about 6,100 requests and two minutes on a WING Compact -- instead of the default, which fetches each object whole with the protocol's node-dump query (`,s *`): about 320 requests and five seconds. The two paths were compared address by address on a real WING Compact and agreed on all 5,860 values; the 304 insert and FX-slot leaves added since have not yet been compared on hardware. This is the diagnostic path: use it if a read looks wrong and you want to rule the node dump out, or if a desk misbehaves when asked for whole nodes. Names and tags are read one at a time either way, and so is any leaf a dump does not carry. |
| `--bulk-read` | Accepted and ignored: reading by node dump is now the default. Kept so scripts written when it was opt-in still run. See --per-leaf. |
| `--dump-state` `FILE` | After a live read, save everything read to FILE as the same address -> value JSON --state takes, so this exact reading can be audited again offline -- with a different --plan, after a fix to a rule, or by someone who was not at the desk. Written before the audit runs. Live reads only: refused with --state. It also records what is on each AES50 port (/$stat/A/dev, B, C; empty when nothing is connected), so an offline `patch` can check a socket against the stage box's size. The file does not record the console model; replay it with --plan to supply one. |
| `--plan` | A plan JSON file (the same shape `atoo build` produces). Independent of --console/--state -- it works on top of whichever live state source was already selected -- and it changes the report two ways. It ADDS conventions-diff findings, comparing live state against what the plan says it should be (mute, fader level, DCA/mute-group membership, patch, bus sends, direct-to-Main routes, and the trim, balance, invert, head-amp gain, high-pass, hi-cut, tilt and EQ it states; the compressor is not compared). And it WITHHOLDS structural findings the plan is not about: one about a strip or bus the plan never mentions, unless the rule is one that matters on any desk (48V on an unpatched socket, a mix that reaches no loudspeaker, a routed strip sitting silent), and any finding about a parameter the plan itself states, since the conventions diff already checks that against what you asked for. Nothing is dropped silently: the count and the reason are reported as S001. Without --plan, nothing is withheld. |
| `--trace-from` | Signal-graph node to trace from, e.g. 'input:LCL:3' or 'strip:/ch/12'. |
| `--trace-to` | Signal-graph node to trace to, e.g. 'output:LCL:1' or 'main:1'. |

## `atoo build`

<!-- preamble:start -->
_Not written yet._
<!-- preamble:end -->

```
Build a plan from an input list + conventions.

A model lays the show out with both in front of it, and deterministic code
verifies the result. Needs a provider -- see ATOO_AI_PROVIDER.

A model call takes minutes, so each one says where it is on stderr while it runs --
which call (generator, critic, watchlist), waiting / thinking / writing, its clock and
the tokens so far: one redrawn line on a terminal, and in a log (2>&1 | tee build.log)
a plain line at each change of stage and every 10-60 seconds, never one per token.

Two ways to fill it in:
  atoo build --input a.csv --conventions b.md [--out plan.json] [--pretty]
  atoo build

The second form is the easy button: with no --input/--conventions given, it looks in
the current directory for exactly one .csv input list and exactly one conventions
source and builds that pair into a plan. Given more than one candidate it prints
what it found and the exact invocation to use, rather than guessing. See
https://docs.atoo.app/build/build-a-show/

The plan is written to a file either way -- an
<input-stem>+<conventions-stem>.plan.json name unless --out says otherwise; pass
--out - to print the JSON to stdout instead.

A show bundle (--show DIR) supplies input.csv and instructions.md
from one directory and writes plan.json back into it. An explicit flag always wins
over the bundle. A bundle's busses.csv (the bus sheet: one row per bus, Main and
Matrix), outputs.csv (one row per output socket: what feeds it) and user.csv (one
row per USR slot: what it takes) are laid onto the plan, in that order: a filled
cell wins over the conventions, each change is a note, and a cell that cannot
work on the desk stops the build, naming it.

A bundle build also DRAFTS that bundle's watch.json -- the short list of
things worth an alert if they move mid-show. Drafted conditions are marked
"source": "drafted" and are merged in, never written over the top: a condition you
already have is left exactly as you wrote it, one you deleted is not re-added, and
nothing watches until you run `atoo watch`. A draft that fails validation is
reported and discarded -- it can never fail the build or replace a good watch.json.

Your conventions file is NOT part of a bundle. It is your standing house style,
reused across shows, so it is named by --conventions or once in ~/.atoo.config.
A bundle's instructions.md is a LAYER over it -- how this one show works -- and wins
where the two disagree. Every build prints the layers it read, in order, and records
them in the plan at meta.conventions_stack -- each file relative to the bundle, with a
sha256 of what it held -- so `atoo ui` reopens the bundle on the conventions file
that built it. The input list is recorded the same way, at
meta.input_list, so the UI and `apply --show` can say a plan is stale: one of its
three inputs changed after it was built.

RESOLVED CONVENTIONS. Before the generator runs, the build looks for
<conventions-stem>.resolved.md beside your conventions file: your conventions and the
domain knowledge restated once as explicit rules, each citing the line it comes from,
with every open question marked "Decided:". When its fingerprint matches (the
conventions, the domain knowledge and the resolve prompt are unchanged), the generator
and the fix-up read it IN PLACE OF both. When it is missing or stale, the build makes
it first -- one extra model call, role `resolve` -- and notes it. The critic still reads
your raw conventions. --no-resolve (or ATOO_RESOLVE=0) turns this off; the plan
records which it was at meta.resolved_conventions.

CATEGORY TABLE. The resolved file ends with a Category table: each category's colour,
HPF, DCA, mute group, gain, trim, fader and Main routing, restating its prose. Code
writes those values on every channel built from an input-list row of that category,
wherever the generator's reply leaves them out -- a value the reply writes wins -- and
notes it, one note per category. A channel the instructions ask for (Talkback) gets
nothing from it. --no-category-rules (or ATOO_CATEGORY_RULES=0) turns it off.

An HTML comment, <!-- like this -->, inline or across lines, is a note to yourself:
the build strips every comment from both files before a model sees them, so nothing
in one is built. An <!-- that never closes is NOT stripped -- the rest of the file is
read as written, and the build warns with the file and line. (The recorded sha256
is still over the whole file, comments included.)

Where your conventions are silent about something the desk cannot be left without --
a bus's mono/stereo width, a send's pre/post, a mix bus's route to Main, a stereo
pairing -- the build DECIDES it, marks the decision in the plan (`inferred`), and
verify reports each one as a note naming what it chose and why. Everything else your
conventions do not state is left alone on the desk. The build also reads your
conventions and instructions.md together for problems in the text itself -- two
statements that disagree with nothing settling them, something declared that this
show never uses -- and reports them, quoting the lines; a quote that is not really in
your files is marked untrusted (meta.build_findings).

What it tells you goes to stderr, severity-labelled, worst first:
  ERROR    something you asked for will NOT happen -- read this before applying
  WARNING  a default was applied, or a rule matched nothing
  NOTE     a choice made where your conventions were silent, or nothing to do;
           said out loud rather than hidden, and never blocks
A finding that is a limitation of Atoo itself tells you -- editing your
conventions file will not fix it. The code in parentheses is
stable across rewordings; quote it in a bug report.
```

| Option | What it does |
|---|---|
| `--console-model` | Which WING this plan is for. Required unless the plan already states it in meta.console_model (a plan built by Atoo does). Socket counts differ between models, so an unstated model is an error rather than an assumption. With --show, a show that has been built before takes the model from its own plan.json, with an INFO; this flag overrides that. |
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--input` | Input list CSV path -- one band/event/venue's physical inputs. Omit together with --conventions to auto-detect the pair in the current directory instead. |
| `--conventions` | Your conventions file (Markdown) -- standing house style, reusable across every show, like the conventions.md `atoo init` copies in. Plain English; the model reads it directly. Defaults to ~/.atoo.config's [conventions] default. A show bundle's instructions.md layers over this, it does not replace it. |
| `--out` | Write the plan JSON here. Default: <input-stem>+<conventions-stem>.plan.json in the current directory. Pass '-' to print to stdout instead of writing a file. |
| `--critic` | Run a second model pass in a separate reviewer role over the generated plan, looking for omissions first, then at the conventions text itself (every such finding must quote your files, and is downgraded to a note when it does not). Its findings are printed, never enforced -- only the deterministic verifier gates anything. |
| `--no-constrain` | Don't constrain decoding to the reply schema (the shorter form the model writes, which build expands into the plan). Constrained decoding makes a malformed or off-schema reply impossible on the providers that support it (claude, ollama, api), but a grammar can degrade the content it shapes and slows local generation -- this exists so that trade-off can be measured rather than argued about. The api provider (OpenAI-compatible) sends it as `response_format`, and stops with this. |
| `--prompt-dir` | Read the generator and critic prompts from here instead of the packaged atoo/prompts. Copy that directory, edit the copy, point this at it -- prompt variants without a branch. Equivalent to ATOO_PROMPT_DIR. |
| `--no-resolve` | Give the generator the raw conventions and the domain knowledge instead of the resolved conventions (<conventions-stem>.resolved.md beside your conventions file; see `atoo resolve`). Equivalent to ATOO_RESOLVE=0. For comparing builds with and without it. |
| `--no-category-rules` | Ignore the resolved conventions' Category table: code writes no per-category channel setting (colour, HPF, DCA, mute group, gain, trim, fader, Main routing) and the generator writes every one. Equivalent to ATOO_CATEGORY_RULES=0. For comparing builds with and without it; the plan records which at meta.resolved_conventions.category_table. |
| `--presets` `DIR` | Atoo's own preset library: a directory of .chn channel-preset exports, looked up by the name inside the file. These are NOT the console's own presets or scenes -- those cannot be recalled remotely at all -- they are parameter values Atoo writes like any other. `build` expands each named preset INTO the plan (its processing values, the plan's own processing winning where both set one), and `apply` writes what the plan carries; verify and apply use the library only to say whether it changed since. A plan naming a preset this library hasn't got is a warning, never a block. Defaults to [presets] default in ~/.atoo.config. |
| `--all-changes` | In the "Changed since the last build" section a rebuild ends with, print every changed value of every strip, and why each change is graded as it is, instead of one short line per strip. The section compares the new plan with the show bundle's plan.previous.json, strip by strip: a change to a strip whose input-list rows or conventions lines changed is INFO; one to a strip nothing about changed is a WARNING, never an error. A first build has none. |
| `--skip-verify` | Don't run the deterministic verifier over the finished plan. Verification checks the plan against the console's real limits, the input list it claims to cover, and equipment-safety rules. Skipping it is almost never what you want. |
| `--pretty` | Also print a human-readable rendering, not just the raw JSON plan |

## `atoo capture`

<!-- preamble:start -->
For a desk you didn't build and won't rebuild: it reads the desk, or a
`.snap` saved on it, and makes a show folder you can watch and edit, with
no model and nothing written to the desk. What it writes, what it
decides, and what it cannot hold yet: [Capturing a desk you didn't
build](capture.md).
<!-- preamble:end -->

```
Capture a desk you didn't build as a show you can watch and edit.

  atoo capture --console 192.0.2.148
  atoo capture --snap CCC-20261024.snap --console-model wing-full

Reads the desk, or a .snap saved on it, and makes a show folder in your Atoo
folder: input.csv (one row per input, with its channel, DCAs and mute groups),
busses.csv (one row per bus, Main and Matrix: what feeds it, where it goes, its
effects), outputs.csv (one row per output socket the desk patches: a split, a
recording feed, a bus's side), user.csv (only when the desk uses one: each USR
slot a channel or an output reads, and what it takes), plan.json (the desk as
it is: patch, routing, membership and widths, not faders or EQ), an empty
watch.json, and the snapshot under captures/.

No model, and nothing is written to the desk. Every name is written in: a
channel with no name of its own takes its source's. What the desk does not
state is decided and said, at INFO: a category from the channel's first DCA,
a type from its source, the role fx for a bus whose effects are all reverbs,
delays or modulation set fully wet. Every send is in the plan, on its source,
with its tap: a channel sent to a Matrix, a bus sent to a bus. Every effect
inserted on a channel, bus, Main or Matrix is in the plan with its engine's
settings (from a live desk, one more request per engine after the desk's read),
so apply loads it back. What the plan cannot hold yet (a GRP-mode tap) stays in
the sheets and the snapshot, and is listed too.

Then watch it with the show: atoo watch --show DIR --console ADDRESS, and edit
its sheets in `atoo ui`, Build step 04, whose Save updates the plan. The UI's
New show... > From a desk does the same as this command.
```

| Option | What it does |
|---|---|
| `--console` | Console IP address. Falls back to $ATOO_CONSOLE, then to a [console] default in ~/.atoo.config -- a run that uses either prints where the address came from, on stderr. |
| `--snap` `FILE` | Capture a .snap show file saved on the console instead of a live desk. Needs --console-model: a .snap does not say which WING wrote it. |
| `--console-model` | Which WING the --snap came from. A live desk states its own model. |
| `--dir` `DIR` | The folder to make the show in (default: your Atoo folder, ~/Documents/Atoo unless ~/.atoo.config's [workspace] says otherwise). |
| `--name` | The show folder's name (default: the .snap's name, or the desk's model and today's date). A name already taken gets -2, -3. |
| `--port` `VALUE` | Console OSC port (default: 2223) |
| `--timeout` `VALUE` | Per-request timeout in seconds (default: 1.0) |
| `--no-progress` | Do not print the progress line while reading the console. |

## `atoo compare`

<!-- preamble:start -->
_Not written yet._
<!-- preamble:end -->

| Option | What it does |
|---|---|
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--plan` | The plan to compare against. Required unless --show supplies it. |
| `--snapshot` | A .snap show file saved on the console and copied off it (USB stick or the console's own file browser). There is no remote save-and-download; the desk writes it, you fetch it. |

## `atoo init`

<!-- preamble:start -->
The first command to run: a working folder with house conventions and a
preset library in it (no show -- you make that with the UI's New show...), and
`~/.atoo.config` pointed at it. It never overwrites anything. See
[Set up Atoo](configuration.md#1-create-your-atoo-folder-atoo-init) for a real
run.
<!-- preamble:end -->

```
First-run setup: a working folder of your own, and
~/.atoo.config pointed at it.

  atoo init
  atoo init --dir ~/shows
  atoo init --demo

Makes ~/Documents/Atoo (or --dir) and copies a starter set into it:

  README.md          what each file is, and what to do next
  conventions.md     example house conventions -- make them yours
  presets/           your library of WING channel presets (.chn): the starter
                     presets the conventions name, and three bus presets
                     (.bus: one for mix busses, two for FX busses). Export
                     your own into it

and sets three defaults in ~/.atoo.config: [conventions] to conventions.md,
[presets] to presets/, and [workspace] to the folder, where `atoo ui`
starts. Every value written and every value left alone is printed.

It makes no show: which show you start with is yours to choose. Make the
first one with `atoo ui`'s New show…, in the folder init made.
--demo also copies the Demo show into the folder as demo-show/, a bundle of
your own to edit, build and apply to a desk (the one the UI opens is read-only).

It never overwrites. A file already there is left alone and reported; a config
value already set to something else is left alone, and the line says what init
would have set. Run twice, the second run changes nothing and reports that. --force
replaces those config values, and starter files that are UNCHANGED copies of an
older starter set (init records what it copied in .atoo-starter.json) --
never a file you have edited. A demo-show folder already there is left whole,
with or without --force.

Exit status: 0 done (including nothing to do); 1 the folder, a config value or
the Demo show's copy could not be written.
```

| Option | What it does |
|---|---|
| `--dir` `PATH` | Where to make the working folder (default: ~/Documents/Atoo). Made if it is not there; a folder that is there already is filled in around what it holds. |
| `--force` | Replace ~/.atoo.config values that name something else, and starter files that are unchanged copies of an older starter set. A file you have edited is never replaced. |
| `--demo` | Also copy the Demo show into the folder as demo-show/, a writable bundle beside the starter conventions and presets. A demo-show already there is left alone. |

## `atoo lessons`

<!-- preamble:start -->
_Not written yet._
<!-- preamble:end -->

```
Mine a show bundle's builds for what keeps being unclear -- recurring build-log
notes, critic findings, conventions-audit entries, inferred markers, plan notes
and verify warnings -- grouped by topic, most-recurring first. It opens with
where each build's thinking went: every role's share of time spent on
mechanical work, conventions questions, the plan format itself, writing the
reply, and judgement. Read-only, no model call.

  atoo lessons --show my-show
  atoo lessons --show my-show --last 2  # only the 2 newest
                                              # builds/ files
  atoo lessons --show my-show --git 5   # + the last 5 committed
                                              # versions of plan.json
  atoo lessons --show my-show --json

Every build writes its own thinking-summary lines (never sent back to a
model) to <bundle>/builds/<timestamp>.json -- builds/
keeps the newest 5 -- and this command reads every one of those files
(newest first), plus the current
plan's own findings, and -- with --git N, for an older plan that still
carries its log inline -- committed versions of plan.json itself. A topic
that shows up under one build is worth a look; one that recurs across builds
is the kind of question that belongs in conventions.md or a show's
instructions.md, once answered, so no future build has to work it out again.
```

| Option | What it does |
|---|---|
| `--show` `DIR` | The show bundle to mine -- its current plan.json is always read. |
| `--last` `N` | Only the N newest builds/ files (default: all of them -- builds/ keeps the newest 5, so at most 5 are ever read). |
| `--git` `N` | Also read the last N committed versions of plan.json from git history, if the bundle is inside a git repository -- otherwise this notes it and reads the current plan only. Useful for an older plan that still carries its build log inline. |
| `--json` | Machine-readable output instead of the plain-text report. |

## `atoo patch`

<!-- preamble:start -->
Type a change — *"trumpet, sax and trombone on LCL 21-23, Band DCA"* — and
write only that to a desk that already has a show on it (or nothing yet).
What you type is a **change**; "patch" in findings and plan fields keeps
meaning socket routing. `plan.json` is never touched. The whole workflow,
with a worked example you can run offline:
[Patching a show that is already on the desk](patch.md).
<!-- preamble:end -->

```
Change a console that already has a show on it -- or nothing yet -- and move
nothing else.

  atoo patch --show ./touringband --console 192.0.2.16 \
      "trumpet, sax and trombone on A 21-23, Horns DCA, send to MON2"
  ... --confirm --change-set horns.json      (write exactly what the preview showed)
  atoo patch --show ./touringband --console 192.0.2.16 "HPF 100 on the vocals"
  atoo patch --show ./touringband --promote 3 --confirm
  atoo patch --show ./touringband --amended-plan ./touringband/rebuilt.plan.json ...

What you type is a CHANGE, and it is called that in messages, the journal and
the page ("change 3: Add horns on A 21-23"). "Patch" in findings and plan fields
keeps meaning socket routing only; the command is called patch because it is
the word for a small change on top of something that exists.

A permanent change to the show means editing the input list, conventions or
instructions and rebuilding. patch is for ad-hoc changes to what is on the
board now, at short notice -- a horn section turning up, a vocalist leaving --
and it works for building a show up one change at a time from an initialized
board. A setup and rehearsal tool: use it before doors, not during the show.

The model sees only your change, the plan the desk's own journal says is on it
(else plan.json, else an empty board -- the review says which), and your
conventions and the bundle's instructions.md. It returns a change set -- what to
add, what to drop, which named fields to set on things already on the desk,
and a short name -- never a whole plan. Code merges it and
refuses a reference to anything that does not exist (a send to a bus that is
neither on the desk nor added). Sockets the change names are honoured; others
are chosen, and each choice is said at INFO.

Everything after that is amend's: new channels are placed on genuinely free
strips (skipping occupied ones, never renumbering a running one unless the
change says INSERT -- see below), a dropped
channel's strip is RETURNED TO FREE -- one the change names, even where the desk
no longer reads it as the strip the show built (said at WARNING, and Undo puts
it back), the pre-flight verifies the result and checks every socket written
against the desk, the review shows what will and will NOT be written, and only
--confirm writes -- reading every unrelated address before and after to prove
none moved, and journalling the run with the change's text and short name.
`atoo undo --show DIR` takes the newest write off again.

A change may also EDIT something already running -- "move the sax to MON3 at
-10", "rename ch 5 Kick In", "HPF 100 on the vocals" -- but only in the fields
it names. Code writes exactly the addresses those fields change, shows old -> new
for each at INFO, and keeps every other address of the strip in the untouched
proof. A fader moves only when the change says "fader"; a repatch of a running
strip is marked MOVES AUDIO LIVE, and switching its 48V phantom power SWITCHES 48V
LIVE. A strip's source can be changed in its phantom, type and model, not in
which input it is or whether it is stereo. Undo puts the old values back.

INSERT AND RENUMBER. "insert HiHat after Snare and renumber the channels after
it" (or "insert", "renumber", "move the rest down") puts the channel there and
moves the strips after it down: each is rewritten whole on its new number, with
its patch, sends, DCA and mute groups, and the review lists every strip that
moves. Undo puts them all back. "add HiHat after Snare" does NOT renumber: the
channel goes on the next free strip and an INFO gives the words that would.

A Line source patched to a head amp does not keep a mic's gain: it takes 0 dB
unless a gain is stated for it, said at INFO. A socket past the end of a stage
box on an AES50 port (A 17 on an S16) does not exist: the pre-flight REFUSES it,
naming the box and its size.

plan.json is never touched: only a build writes it, and a full apply warns
before it replaces changes that are not in it. To keep a change for good,
--promote it: its text goes into instructions.md, the inputs it added into
input.csv, and the next rebuild owns them.

Each run prints how long it took: the desk read and the model call. A preview
compiles the change; a --confirm run compiles it again unless given
--change-set, so save the one you reviewed with --save-change-set. --state FILE
reviews offline against a saved capture. Exit 2 means it ran and found
problems: a refused change (a reference, field or value the plan cannot take),
a channel with no free strip, a pre-flight refusal, a readback mismatch, or an
unrelated address that moved.

A bus, DCA or mute group the starting plan does not know (a desk Atoo did
not set up) is read off the desk when the change names it -- only that
object, not a sweep -- and the change is carried out against what the desk
holds. A name the desk does not hold either is REFUSED.
```

| Option | What it does |
|---|---|
| `--change-file` `FILE` | Read the change from FILE instead -- for a long one, or one written in an editor. |
| `--amended-plan` `FILE` | Patch from a rebuilt plan instead of a typed change: the same show, built again (`atoo build --out FILE`) with the change in its inputs. This is what `atoo amend` does, and is recorded as an amend. |
| `--change-set` `FILE` | Use this compiled change set instead of calling the model -- one --save-change-set wrote, or a --review-json file. How a --confirm run writes exactly the change set a preview showed, and how a change is reviewed with no model at all. |
| `--save-change-set` `FILE` | Also save the compiled change set (with the change's text) to FILE, for --change-set to write later. |
| `--promote` `CHANGE` | Keep a change already written in the show for good: append its text to the bundle's instructions.md, under a dated 'Promoted changes' heading, and a row to input.csv for each input it added that the list does not have. CHANGE is its number (3, or 'change 3'), its short name, or its journal entry. Needs --show; no console or model. A preview unless --confirm. plan.json is not touched: rebuild to put the change in it. A change that was undone is refused. |
| `--conventions` `FILE` | The house conventions to compile the change with. Default: the file the show on the desk was built from (recorded in its plan), else the [conventions] default in ~/.atoo.config. The bundle's instructions.md layers on top, as for a build. |
| `--presets` `DIR` | The preset library the change's new channels and busses take their presets from (.chn channel presets, .bus bus presets), expanded into the change as a build expands them into a plan. Not needed as a rule: without it, the library the plan on the desk was built with (or the packaged starter presets, when its files match them), else [presets] default in ~/.atoo.config; an INFO says which. With none, a change that names presets warns up front, as a WARNING, and its new strips are written without those presets' values. |
| `--console-model` | Which WING this plan is for. Required unless the plan already states it in meta.console_model (a plan built by Atoo does). Socket counts differ between models, so an unstated model is an error rather than an assumption. |
| `--no-constrain` | Do not constrain the model's reply to the change-set format (the same escape as `build --no-constrain`). The reply is still checked against it. The claude, ollama and api providers constrain decoding (the api provider sends it as `response_format`; ATOO_AI_STRUCTURED=0 also stops that). |
| `--prompt-dir` `DIR` | Read change_compile.md from DIR instead of the packaged prompts (sets ATOO_PROMPT_DIR for this run). |
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--plan` | The plan that is ALREADY on the desk. Normally left out: with --show, it is the plan the desk's own newest journal entry left on it, else the bundle's plan.json, else an empty board. |
| `--console` | Console IP address -- read which strips are free from the live desk. Falls back to $ATOO_CONSOLE, then to a [console] default in ~/.atoo.config -- a run that uses either prints where the address came from, on stderr. |
| `--state` | A JSON object of address -> value (the same shape `audit --state` takes) -- work out the delta from that instead of a live console. Reviews the whole change offline; it can never write. |
| `--port` `VALUE` | Console OSC port (default: 2223) |
| `--timeout` `VALUE` | Per-request timeout in seconds (default: 1.0) |
| `--channels` `VALUE` | Channel strips to read occupancy for (default: 40, WING Compact) |
| `--aux` `VALUE` | Aux strips to read occupancy for (default: 8, WING Compact) |
| `--allow-strip` `BANK:N` | Let the patch place a new object on one strip the desk says is occupied or did not answer, e.g. --allow-strip ch:20. Per strip and repeatable; there is deliberately no 'allow everything' switch. A strip the plan on the desk owns can never be opened this way. |
| `--confirm` | Actually write. Without this, patch is a preview that changes nothing -- the same arming `apply` requires, on the same reasoning. This ONE flag arms everything the preview showed, including returning a dropped channel's strip to free; there is deliberately no second switch for the clears, because a second switch is a second thing to tick past. |
| `--journal` | Where to record every write with its prior value AND this run's scope -- which strips it was allowed to touch. Defaults to a new timestamped entry in the bundle's journals/ directory, or <plan>.patch-journal.json without --show. With --show, a confirmed run is added to the bundle's journals/ stack whatever this says, with the plan it left on the desk and the change's text and short name. |
| `--skip-verify` | Write without the pre-flight verify of the patched plan -- the same gate, and the same escape, as `apply --skip-verify`: without it, a verify ERROR refuses the patch (warnings never do). It does NOT skip the socket check: a socket this patch would write that the desk does not have is refused either way. |
| `--skip-untouched-proof` | Do not read every unrelated address before and after the write. That read is the PROOF that nothing already in use moved -- not merely the absence of a write to it. It should rarely be worth skipping now: a PREVIEW never runs it at all (it writes nothing, so there is nothing to prove), and a --confirm run reads the set through the node-dump path -- about 140 requests rather than 670, roughly 1.4s a pass on a Compact. This flag only affects a --confirm run, and skipping leaves that run resting on the target filter alone. |
| `--per-leaf` | Read the before/after untouched-strip proof one request per leaf instead of by node dump -- about 670 requests a pass rather than 140, roughly 4-5x slower. The diagnostic path, as on audit and watch: the two read paths agreed on every value compared on a real WING Compact. The occupancy read is per-leaf either way. |
| `--review-json` `FILE` | Also write the review -- every strip's occupancy verdict, the delta, and what will and will NOT be written -- as JSON to FILE, using the same words the command prints. Written before any refusal, so a blocked patch still says why; a --confirm run adds the untouched-strip proof after the write. `atoo ui`'s Patch screen reads it. |
| `--no-progress` | Do not print what the run is doing while it reads and writes the console. Each long phase -- reading the desk (a preview reads the reset's settings and the plan's in one pass), writing (each setting is read back as it is written), reading back again what disagreed -- normally prints its name, how far it has got and the address in flight on stderr as it goes, and a line with its count and time when it ends. Without it a slow run looks like a hung one, so pass this only when something downstream is parsing stderr. |

## `atoo ping`

<!-- preamble:start -->
The first thing to run at a desk, and the first thing to run when
something else cannot reach one. It asks the console who it is and
prints the answer:

```
$ atoo ping --console 192.0.2.16
Console: WING,192.0.2.16,FOH,wing-compact,SN12345,3.1-0
Detected model: WING Compact (wing-compact)
```

It reads nothing else -- one request, no strip sweep, no writes -- so it
is safe during a show, and it is instant even on a full-size desk.

The second line matters before an apply: `atoo apply` compares the
plan's model with the desk's, and refuses a plan that patches a socket
the desk's model does not have. This is how you see which model the desk
says it is without running an apply to find out. A model it does not
recognise is printed as the desk spelled it -- the string to report.

A failure names which of the two things went wrong:

```
no reply from 192.0.2.16:2223 -- is the console reachable, and is its OSC remote enabled?
couldn't reach 192.0.2.16:2223 -- OSError: [Errno 65] No route to host
```

The first means the packets went out and nothing came back: the usual
cause is that the console's OSC remote control is switched off. The
second is the network refusing to carry them at all -- wrong address,
wrong subnet, cable out.
<!-- preamble:end -->

```
Check that a console is reachable, and say which one answered.

  atoo ping --console 203.0.113.50

One OSC round trip -- the same `/?` identity request every online command opens
with -- and nothing else. No strip sweep, no writes, nothing touched, so this is
safe to run in the middle of a show. Exits 0 when the desk answers, 1 when it
does not.

It also prints the model the desk states for itself, which is what `atoo
apply` cross-checks a plan against before writing anything -- worth seeing
before an apply rather than during one. A model it does not recognise is
printed as the desk spelled it: that is the string to report.
```

| Option | What it does |
|---|---|
| `--console` | Console IP address. Falls back to $ATOO_CONSOLE, then to a [console] default in ~/.atoo.config -- a run that uses either prints where the address came from, on stderr. |
| `--port` `VALUE` | Console OSC port (default: 2223) |
| `--timeout` `VALUE` | Per-request timeout in seconds (default: 1.0) |

## `atoo presets`

<!-- preamble:start -->
**What a preset is called is not what its file is called.** The name lives
in the `info_text` field inside the `.chn`, because that is the label the
engineer gave it on the desk — so `ls` does not tell you, and a
conventions file that names a preset by its filename rather than its
saved name finds no preset at all.

This is the command that tells you. See
[Ask the library what it is called](presets.md#ask-the-library-what-it-is-called)
for the output and what the `params` column means.
<!-- preamble:end -->

```
List a preset library: what each preset is CALLED, which file it came from, and
anything wrong with it.

  atoo presets --presets starter/presets
  atoo presets                      # uses the [presets] default in ~/.atoo.config

A preset's name lives in the `info_text` field INSIDE the .chn file -- it is the
name the engineer gave it on the desk, and it is what a plan and a conventions
file match on. It need not be the filename, nor the channel's name: the
starter's `Kick In.chn` holds `Kick In`, and the Kick channel that uses it
stays called Kick; rename the file and the preset keeps its name. So `ls` cannot answer "what is my library called", and
this can -- it opens every file to do it. Bus presets (.bus) are listed after
the channel presets, with the effect each one inserts: a bus names one by the
same `info_text` name.

It also reports two things that are otherwise invisible until some plan happens
to name the preset carrying them: a preset with a field this tool does not
recognise or a sidechain keyed off another channel, and two files claiming the
same name. Neither stops a build -- the newest of two duplicates wins -- so this
exits 0 either way. Nothing is read from a console and nothing is written.

  atoo presets --presets starter/presets --expand plan.json

--expand does what `build` does to a plan's named presets, without a model call:
each preset's processing values are put INTO the plan, keyed by the address each
is written to, so the plan says exactly what `apply` will write. Where the plan
states a value of its own at the same address (a high-pass, an EQ band), the
plan wins, with an INFO. Processing only -- a preset never writes sends, main
routing, fader, mute, the input patch or tags. A bus preset also loads the
effect it inserts into an FX engine, chosen by code (reverbs and delays on 1-8,
the preset's own engine when it is free) and announced. Preset writes are read
back like every other write; they have not yet been confirmed on a desk.
```

| Option | What it does |
|---|---|
| `--presets` `DIR` | Atoo's own preset library: a directory of .chn channel-preset exports, looked up by the name inside the file. These are NOT the console's own presets or scenes -- those cannot be recalled remotely at all -- they are parameter values Atoo writes like any other. `build` expands each named preset INTO the plan (its processing values, the plan's own processing winning where both set one), and `apply` writes what the plan carries; verify and apply use the library only to say whether it changed since. A plan naming a preset this library hasn't got is a warning, never a block. Defaults to [presets] default in ~/.atoo.config. |
| `--expand` `PLAN` | Instead of listing, resolve every preset PLAN names into it -- the preset's processing values, keyed by the address each is written to, with the plan's own processing winning wherever both set one -- exactly as `build` does. Rewrites PLAN in place (only if something changed), or writes --out. For a plan built before presets were expanded, or without a library. |
| `--out` `FILE` | With --expand: write the expanded plan here instead of over PLAN. |

## `atoo resolve`

<!-- preamble:start -->
An experiment. How to read the file it writes, and what
`Decided:` means: [Conventions reference](conventions-reference.md#the-resolved-conventions).
Where it sits in a build: [How a show gets built](pipeline.md#0-resolve-your-conventions-restated-once-as-rules).
<!-- preamble:end -->

```
Resolve your house conventions (an experiment).

One model call (role `resolve`) reads your conventions file and Atoo's domain
knowledge and writes <conventions-stem>.resolved.md beside the conventions file:
plain Markdown that states, per category, the HPF, colour, DCA, mute group, monitor
and bus sends, Main routing, gain, trim and phantom; the busses, outputs, groups,
head-amp scope, faders and channel order; every open question settled once as a
"Decided:" line with its reason; and every conventions line that yields no rule,
under "Lines with no effect". Every rule cites the text it comes from, verbatim, as
[conventions: "..."] or [domain: "..."].

Code then checks it: every citation must be in the conventions or the domain
knowledge, and every conventions line (not blank, not a heading, not a comment) must
be cited or listed as having no effect. A citation not found is a WARNING; a line
no rule covers is a note, and is given to the generator verbatim. A line of your
preset map (- Kick: "Kick In", indented under a line that names presets) is
covered when your preset library -- [presets] default in ~/.atoo.config -- has
every preset it names (a bus preset under a line that says bus), cited or not; one
naming a preset the library has not got is a note saying so, and so is one that
also states a rule. A library that cannot be read is said at INFO. The file is
still used with warnings, and refused only when
it is empty or none of its citations is found.

The file ends with a Category table: one JSON object per category restating its
colour, HPF, DCA, mute group, gain, trim, fader and Main routing, which the build
writes on every channel of that category the generator leaves them out of. Code
checks its shape; an invalid table is a WARNING and is not applied. --check says
whether it is valid.

`atoo build` does this for you when the file is missing or stale, so you run
this command to resolve again on purpose (after reading the file and disagreeing
with a decision, say), or with --check to check the file you have without a model
call.

  atoo resolve --conventions conventions.md
  atoo resolve --conventions conventions.md --check

Model and effort: ATOO_AI_RESOLVE_MODEL (default claude-sonnet-5-5,
whatever the generator runs on) and ATOO_AI_RESOLVE_EFFORT (default medium).

Exit status: 0 the file is fresh and every check passed; 2 it is usable, with
warnings (or, with --check, stale); 1 it is missing, refused, or could not be made.
```

| Option | What it does |
|---|---|
| `--conventions` | Your conventions file. Defaults to ~/.atoo.config's [conventions] default. The resolved file is written beside it. |
| `--check` | Check the resolved file that is there -- its fingerprint, its citations and its coverage of your conventions -- and make no model call. |
| `--prompt-dir` | Read the resolve prompt (conventions_resolve.md) from here instead of the packaged atoo/prompts. Equivalent to ATOO_PROMPT_DIR. |

## `atoo ui`

<!-- preamble:start -->
_Not written yet._
<!-- preamble:end -->

```
Serve the operator UI as a local web page: one page with three modes --
Build | Apply | Watch -- over one show bundle and one console. A browser client
over the same engine the commands use, not a separate implementation.

  atoo ui
  atoo ui --port 9000
  atoo ui --show my-show
  atoo ui --no-browser

The page opens in your default browser once the server answers, and its address is
printed too (--no-browser only prints it; with no display, as over SSH, nothing is
opened). If an Atoo UI is already serving on the port, `ui` opens that one and
exits 0 rather than failing. Loopback-only by default and no
external network calls at any point -- this is meant to run on a laptop with no
internet access, only LAN reach to the console.

With no --show, the file browser starts in the working folder `atoo init` made
(~/.atoo.config's [workspace] default), so Open… and New show… land there.

Shared by all three modes: the bundle bar (--show opens one; it can be changed or
created from the page), the console readout -- editable there with Change…, and
nowhere else -- with a Ping button (one round trip, nothing read, safe mid-show),
and the Findings panel: the one place findings are listed, each once -- a verdict
first, then one line per finding, the critic's advice apart, and every info note
folded.

Build: the three files a build reads -- one not there yet is a to-do on its tile,
and an error only if Build is pressed without it -- and 04 Plan, which runs
`atoo build --show` from the page and shows the plan it writes -- a table, one
row per input, each opening onto its detail and provenance -- with its verify and
critic findings in the Findings panel. --plan seeds that step with a plan.json.

Files and folders are chosen in a file browser on the page, which this server
lists for this machine's own browser only. An input list, instructions file or
watch-conditions file chosen from outside the open bundle is copied into it as
input.csv, instructions.md or watch.json (asking before it replaces one); the house
conventions file is used where it is.

Apply: the one screen in Atoo that writes to a console. A pre-flight verify
shown before the buttons rather than implied, a dry-run preview that is always
available, an `Arm` checkbox that IS --confirm and gates the
write, and the run's journal -- mismatches and unreadable addresses expanded, the
rest counted and folded away, with the journal file named and the `atoo undo`
line that reverses it. It runs `atoo apply --show` itself, so every gate that
command has is the gate here.

Watch: read-only, like `atoo watch`. It watches the console in the bundle bar.
Alerts appear in a
table, color-coded by severity, and disappear on their own once the operator fixes
whatever tripped them. Under Watch conditions it edits
the bundle's watch.json (Change file, New file, Save, as for Build's files), and
marks each condition Drafted (a bundle build proposed it) or Yours.

Demo (Console: Change…, then Demo) opens a packaged demo show on a built-in
WING Compact rig that needs no console: Build's tiles and plan, Apply's pre-flight
and Preview against the simulated rig, and Watch with the demo's own watch.json,
whose conditions fire as the rig's faults come and go. The demo show is read-only
-- Save, Build, New file and Change file are refused, and Apply never writes and
never undoes. Choosing an address, or opening or creating a show, leaves it.

--watch-conditions PATH loads a watch-conditions file into Watch conditions
at startup, and threads its rules into any watch session started from the
browser -- the same file `atoo watch --watch-conditions` accepts. With
--show and no --watch-conditions, the bundle's own watch.json is loaded.

There is no --console here, and the --port above is the WEB SERVER's, not a desk's.
The console is resolved from $ATOO_CONSOLE / $ATOO_CONSOLE_PORT /
$ATOO_CONSOLE_TIMEOUT, or from ~/.atoo.config's [console] section -- the
same resolution `ping`, `apply`, `audit` and `watch` use -- and the page shows where
it came from. That is only where it STARTS: the bundle bar's Console Change… sets
another address (and port) without a restart. It is one
console for the whole page -- Ping, Apply, Patch, Undo and Watch all use it, and no
screen has a second box to type the wrong address into -- so one plan can be
applied to a primary desk and then a backup by changing the bar between them. The
bar cannot change while a write is running, and each desk keeps its own undo
history (see `atoo undo --help`).

The page is at /. /app redirects there.
```

| Option | What it does |
|---|---|
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--host` | Interface to bind (default: 127.0.0.1, loopback only). On a network address a second machine may Watch; opening files and every write from the page (apply, patch, undo, build, saving a file) still answer this machine only |
| `--port` `VALUE` | Port to serve on (default: 8420). If an Atoo UI is already serving there, that one is opened instead |
| `--no-browser` | Do not open the page in a browser; only print its address. By default the page opens in the default browser once the server answers |
| `--plan` | A plan.json to show at startup on Build step 04 -- the same shape `atoo build` produces. Optional; a plan can also be loaded (or replaced) later from the browser without restarting. |
| `--watch-conditions` | A watch-conditions JSON file to load at startup into Watch conditions, on the Watch screen -- the same file `atoo watch --watch-conditions` accepts. Optional; falls back to ~/.atoo.config's [watch_conditions] default when omitted (see `atoo watch --help`), and can also be loaded (or replaced) later from the browser without restarting. |
| `--presets` `DIR` | Atoo's preset library (a directory of .chn exports): the names Build step 02's Preset column offers, and the library a build started from the page is given. Defaults to [presets] default in ~/.atoo.config; with neither, the column still takes a name as free text. |

## `atoo undo`

<!-- preamble:start -->
Takes one optional positional argument, `JOURNAL` — the journal to
reverse. That is an entry in a show bundle's `journals/`,
`<plan-stem>.apply-journal.json` beside a plan, or wherever `apply
--journal` put it. A `patch` or `amend` journal works the same
way, and so does an undo's own journal, which is the redo. With `--show`
and no `JOURNAL`, undo reverses the newest write in the bundle's
`journals/`.

Nothing is written without `--confirm`; the preview shows, per address,
what it would restore and what it would refuse. See
[Undoing a write](undo.md).
<!-- preamble:end -->

```
Reverse the last write to the console, from the journal that wrote it.

  atoo undo --show touringband --console 203.0.113.50
  atoo undo --show touringband --console 203.0.113.50 --confirm
  atoo undo touringband/journals/<entry>.json --console 203.0.113.50

The first form changes nothing: it reads the console's current value for every
address the run wrote and shows you, per address, what it would restore and what
it would refuse. Writing requires --confirm, same as apply.

With --show and no journal named, undo walks the bundle back ONE STEP IN TIME.
Every confirmed apply, patch (a change), amend and undo is recorded
in the bundle's journals/ directory as a timestamped entry, and undo reverses the
newest one still standing on the desk, whatever kind it was. It POPS: after
undoing a change, the next undo reverses what is under it. journals/ keeps the
newest 5 entries, so undo reaches back at most 5 writes: it stops, with nothing
written, at a desk's last kept write when an older one was pruned while still on
the desk. journals/ is the only
record: a bundle with no journals/ has nothing to undo with --show.
A journal file anywhere else -- <plan>.apply-journal.json, or one --journal
wrote -- is undone by naming it, as in the third form.

A change or an amend never writes plan.json -- only a build does -- so undoing
one leaves it alone. An amend recorded by an older Atoo DID replace it; undoing
that one puts the old plan.json back, but only while plan.json is still the file
the amend wrote (a sha256 it recorded), and the redo re-installs it the same way.

Naming a journal that is no longer the newest entry is REFUSED, because undo's
guard is per address and cannot see a later run: an apply an amend was built on
top of would pass every address and come off the desk under it. The refusal names
what is above it; --out-of-order overrides it.

PER DESK. One plan can be applied to two consoles -- a primary and a backup --
and every entry records the desk it wrote to: the serial it states on /? (which
also names the entry's file) and the address it was reached at. So "the newest"
means the newest write on THE DESK THIS COMMAND REACHES: undo --show pops that
desk's newest and leaves the other desk's history alone. Undo only ever reverses
a journal on the desk it was written to. The serial is the desk: the same serial
at a new address is the same desk (said at INFO), and a different serial is
refused even at the same address, naming both. There is no override. A desk that
states no serial is matched by its address. An entry recorded before entries
named their desk is taken to be this desk's, and undo notes it.

An undo reverses OUR RUN and nothing else -- which is what a console snapshot
cannot do. A snapshot puts the whole desk back to a moment, throwing away every
other change made since; this puts back only the addresses this journal records,
and only where they are still the value we wrote.

That last clause is the whole safety property. Before restoring an address, undo
reads it: if it no longer holds what we wrote, somebody has changed it since, and
reversing would clobber their change -- so that address is REFUSED and reported,
never written. An address whose prior value the apply could never read has nothing
to restore and is reported too; no default is invented for it. The summary counts
the three apart: "41 reversed, 2 refused (changed since), 1 unreversible".

Only writes that actually happened are candidates. A skipped_no_change was never
written -- unless its selector (a delay mode, a dynamics or EQ model) was changed
by the run and is being put back, when its recorded prior is written after the
selector, at INFO. The journal of a dry run is refused outright rather than
appearing to work. Reversals go out in reverse order -- except a strip's
processing, restored selectors, then values, then switches -- are read back and
proved like any other write, and are journalled themselves -- so `atoo undo`
on the undo's own journal is the redo, and there is no separate command for it.
An undo's journal is kept (it is the only record of what the undo REFUSED to
touch) but is never a step forward: it pops the entry it reversed rather than
becoming a new one.

Exit codes: 0 clean, 1 the command could not run (bad journal, no console), 2 it
ran and the console is not fully back -- something refused (changed since) or a
reversal that did not land. An address with no earlier value (the run wrote it
for the first time) has nothing to put back; it is named at INFO and exits 0.
```

| Option | What it does |
|---|---|
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--console` | Console IP address. Falls back to $ATOO_CONSOLE, then to a [console] default in ~/.atoo.config -- a run that uses either prints where the address came from, on stderr. |
| `--port` `VALUE` | Console OSC port (default: 2223) |
| `--timeout` `VALUE` | Per-request timeout in seconds (default: 1.0) |
| `--state` | A JSON object of address -> value (the same shape `atoo audit --state` takes) to preview the reversal against, instead of contacting a console. Preview only: a value read from a file says nothing about what the desk holds now, which is the whole question the 'still ours' guard asks, so --state can never be combined with --confirm. |
| `--only` `SELECTORS` | Reverse only part of the run: a comma-separated list of strip labels (ch:21, aux:3, bus:4, main:1, mtx:2, dca:7 -- the same spelling amend's --allow-strip and the journal's own scope use) or address prefixes (/io/in/A/5). Everything else in the journal is left exactly as it is. Without this, an amend journal defaults to the scope the amend itself was held to, and any other journal to all of it. |
| `--confirm` | Actually write the prior values back. Without this, undo is a preview that changes nothing and shows, per address, what it would restore and what it would refuse. |
| `--out-of-order` | Reverse a journal that is NOT the newest entry in the bundle's stack. Refused by default: undo's guard is per address and cannot see a later run, so reversing an apply that an amend was built on top of would pass every address and take the show off the desk under the amend. This says you know what is above it and want it reversed anyway. |
| `--journal` `PATH` | Where to record this undo's own writes. Defaults to a new timestamped entry in the bundle's journals/ directory when reversing one of those, and to <JOURNAL stem>.undo.json beside the journal otherwise -- never over it, because overwriting the evidence destroys the only thing that could reverse the undo. It is an ordinary apply journal, so `atoo undo` on it is the redo. |
| `--raw-log` | Append every raw OSC request/reply to this file, exactly as `apply --raw-log` does. |
| `--result-json` `FILE` | Write the run as JSON to FILE, for a page to draw: one row per address (the strip, the value the journalled run wrote, the value on the desk now, the value an undo puts back, and whether it goes back, is already back, has changed since, or has no earlier value), the counts, and one word for the whole run. Written for a preview and for a confirmed run alike. |
| `--no-progress` | Do not print what the run is doing while it reads and writes the console. Each long phase -- reading the desk (a preview reads the reset's settings and the plan's in one pass), writing (each setting is read back as it is written), reading back again what disagreed -- normally prints its name, how far it has got and the address in flight on stderr as it goes, and a line with its count and time when it ends. Without it a slow run looks like a hung one, so pass this only when something downstream is parsing stderr. |

## `atoo verify`

<!-- preamble:start -->
_Not written yet._
<!-- preamble:end -->

| Option | What it does |
|---|---|
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--console-model` | Which WING this plan is for. Required unless the plan already states it in meta.console_model (a plan built by Atoo does). Socket counts differ between models, so an unstated model is an error rather than an assumption. |
| `--plan` | A plan JSON to check. Required unless --show supplies it. |
| `--input` | The input list the plan was built from. Without it, the checks that need it are skipped: that every input became a channel, that no channel was invented, and that phantom power is safe. |
| `--presets` `DIR` | Atoo's own preset library: a directory of .chn channel-preset exports, looked up by the name inside the file. These are NOT the console's own presets or scenes -- those cannot be recalled remotely at all -- they are parameter values Atoo writes like any other. `build` expands each named preset INTO the plan (its processing values, the plan's own processing winning where both set one), and `apply` writes what the plan carries; verify and apply use the library only to say whether it changed since. A plan naming a preset this library hasn't got is a warning, never a block. Defaults to [presets] default in ~/.atoo.config. |

## `atoo watch`

<!-- preamble:start -->
_Not written yet._
<!-- preamble:end -->

```
Continuously re-run the audit against a console and alert on what CHANGED
since the last read -- not the same finding restated every
poll, only a finding that just started applying, or just stopped.

  atoo watch --console 203.0.113.50
  atoo watch --console 203.0.113.50 --interval 5
  atoo watch --state-sequence ~/Documents/Atoo/audit-demo/audit_demo_state_before.json,~/Documents/Atoo/audit-demo/audit_demo_state.json

Polling, not push: WING's OSC offers one event subscription for the whole network, and
it dies after 10 seconds unless renewed, so this reads the same address set `audit` does
on an interval and diffs. Every read says how far through it is and how many addresses
went unanswered, so a slow pass can be told from a hung one. Session-based
and read-only -- nothing here writes to a console, and it stops the moment you
stop it (Ctrl-C); there is no background service and nothing persists between runs.

Names (strips, buses, DCAs, mute groups, input sockets) are read on the first read and
every --name-refresh reads after it (default 5, about every 30s; 1 with --per-leaf), not
every read: a node dump cannot carry a name, so they are over a quarter of a read's requests.
Between refreshes the rules see the last names read, and a rename shows up at the next
refresh -- the findings say so at INFO (W001). --name-refresh 1 reads them every time.

With --console it also listens to the console's meters (a read-only native connection on
port 2222, one of its 24 client slots) and raises L003 Clipped, an ERROR, for a channel,
aux, bus, main or matrix that clips (-0.5 dBFS) for 60 seconds after its last clip. A clip
ends once the strip has been below -0.5 dBFS for 200 ms. If the connection cannot be had, or
the meter data stops, it notes it at INFO (W002) and carries on.

A channel on its alternate input (C004) and the global alternate switch (C005) are
warnings, since a show never starts on them. During a virtual soundcheck they are
right: --virtual-soundcheck reports them at INFO instead (each strip still named, and W003
saying the switch is on) for this run only. Leave it off when the show is live.

The first read is reported as a baseline, not an alert -- whatever's already wrong when
you start watching isn't a change. --state-sequence plays a fixed list of JSON captures
in order (then repeats) instead of a live console, so a novice operator can see an alert
fire with no hardware at all.

With --show, the bundle's plan adds drift checks, each a WARNING (CV018 an
INFO) that clears when the desk is put back: a channel whose every planned send and Main route is off
(CV016), a planned send switched off or flipped between pre and post (CV006), a
channel's Main route off that the plan lists or on that it does not (CV007), a send
to a Matrix, or a bus's route to a Main, that is on and the plan does not have
(CV018), a channel, bus, DCA, Main or Matrix muted that the plan leaves unmuted
(CV017), 48V that is on where the plan has none or off where it has it (CV019), a bus that
is mono or stereo where the plan states the other (CV020), talkback that reaches
some destinations but not a monitor mix the plan builds (CV021; CV022 is the INFO
naming the busses it took for monitor mixes), and an
effect the plan inserts bypassed or changed (CV015). The plan's output
sockets are read too. With or without a plan, so are the outputs of any AES50
stage box, and of any module or card, the desk reports.

--watch-conditions PATH adds operator-authored alerts on top of the built-in
structural rules -- deterministic, structured, no AI in the runtime path. Each
condition says when to alert: it fires while it is true. A JSON file of:

  { "version": 2, "watch_conditions": [
      { "id": "crowd-mic-muted",
        "description": "Crowd Mic is muted",
        "channel": "Crowd Mic", "field": "muted", "operator": "==",
        "value": true, "severity": "error" } ] }

  atoo watch --console 203.0.113.50 --watch-conditions my_show.watch.json

Fields: "muted" (bool), "fader_db" (number), "dca" and "mute_group" (a group NAME,
e.g. "Drums"; "not in" alerts when the strip is not in it, "in" when it is) and
"patch" (a socket written the way an input list's patch column writes one --
"AES50-A 12", "LCL 3", "AES 1", "CRD 64"; "!=" alerts when it is patched anywhere
else, "==" when it is patched there). Note "AES 1" (AES/EBU) and "AES50-A 1" are
different sockets. A file without "version": 2 was written when a condition said
what should hold, and is refused with how to convert it.

Sends and 48V: "send_on" (bool), "send_db" (number) and "send_mode" ("pre", "post" or
"group") are about the channel's send to the bus a "bus" key names -- written like
"channel": a bus's name, "BUS 5", "BUS 5-8", "ALL BUS", "MTX 3" or "MAIN 1" -- and
"phantom" (bool) is the 48V on the socket the strip is patched to (and the next, for
a stereo source).

  { "id": "kick-out-of-drums", "description": "Kick is not in the Drums DCA",
    "channel": "Kick", "field": "dca", "operator": "not in", "value": "Drums",
    "severity": "warning" }

"channel" is a channel's or aux's name, matched case-insensitively; a name matching zero
or more than one live channel is skipped for that poll cycle rather than guessed at, and
a DCA or mute-group name is resolved the same way. It may instead be a position ("CH 10",
"BUS 3", "MAIN 1", "DCA 14"), a range ("DCA 10-16"), a whole kind ("ALL AUX"), or a
kind and a name ("BUS Drums", "DCA Vocals", "MAIN PA"). A kind and a name is resolved
ONCE, at the first read, to a position -- said at INFO in the baseline -- and that
position is what is watched; a rename or move after that is not followed until watch
starts again, and a name matching no strip of its kind, or more than one, is a WARNING
and is not watched.

If --watch-conditions is omitted, a settled house watch-conditions file named in
~/.atoo.config's [watch_conditions] section is used instead, mirroring
[conventions]'s existing default (see `atoo build --help`); an explicit
--watch-conditions always wins over that default.
```

| Option | What it does |
|---|---|
| `--show` `DIR` | A show bundle: one directory holding everything for this show, under fixed filenames (input.csv, instructions.md, plan.json, watch.json, and a journals/ directory of every write in time order) with no manifest to maintain. Each command takes the pieces it needs from the directory instead of being handed them one flag at a time, and everything a run produces is written back into it. An explicit flag always wins over the bundle, so --show DIR --plan elsewhere.json reads that plan. More: https://docs.atoo.app/build/show-bundles/ |
| `--console` | Console IP address -- poll its live state and audit each read. Falls back to $ATOO_CONSOLE, then to a [console] default in ~/.atoo.config -- a run that uses either prints where the address came from, on stderr. |
| `--state-sequence` | Comma-separated JSON state files, played in order and then repeated -- an offline demo of an operator making changes between polls, with no console attached. Try ~/Documents/Atoo/audit-demo/audit_demo_state_before.json and audit_demo_state.json, which `atoo init` copies. |
| `--port` `VALUE` | Console OSC port (default: 2223) |
| `--timeout` `VALUE` | Per-request timeout in seconds (default: 1.0) |
| `--channels` `VALUE` | Channel strips to read (default: 40, WING Compact) |
| `--aux` `VALUE` | Aux strips to read (default: 8, WING Compact) |
| `--buses` `VALUE` | Busses to read (default: 16, WING Compact) |
| `--mains` `VALUE` | Mains to read (default: 4, WING Compact) |
| `--matrices` `VALUE` | Matrices to read (default: 8, WING Compact) |
| `--dcas` `VALUE` | DCAs to read (default: 16, WING Compact) |
| `--mute-groups` `VALUE` | Mute groups to read (default: 8, WING Compact) |
| `--input-sockets` | Physical input socket counts to read phantom power from, e.g. 'LCL=20,A=48'. Omit and Atoo reads the panel of whichever model the desk says it is, plus every group the --plan patches from. Pass this to override that. |
| `--output-sockets` | Physical output socket counts to read patch state from, e.g. 'LCL=16'. Omit and Atoo reads the panel of whichever model the desk says it is, plus every group the --plan patches to. Pass this for a stage box or a card the plan does not mention. The report says which sockets it read. |
| `--raw-log` `FILE` | Append every raw OSC request and reply to FILE, exactly as `apply --raw-log` does -- the literal bytes, not the values made of them. For a read that is slow or comes back short: the progress line says how many addresses went unanswered, and this says which. Written line by line, so a read stopped with Ctrl-C still leaves a complete log. Live reads only. |
| `--no-progress` | Do not print the progress line while reading the console. A live read is a few hundred requests (thousands with --per-leaf) and normally reports 'read 120/323 (37%%) 2s -- /io/in/USR/44 (node)' on stderr as it goes, plus how many addresses went unanswered at the end. Without it a slow read looks like a hung one, so pass this only when something downstream is parsing stderr. |
| `--per-leaf` | Read the console one request per leaf -- about 6,100 requests and two minutes on a WING Compact -- instead of the default, which fetches each object whole with the protocol's node-dump query (`,s *`): about 320 requests and five seconds. The two paths were compared address by address on a real WING Compact and agreed on all 5,860 values; the 304 insert and FX-slot leaves added since have not yet been compared on hardware. This is the diagnostic path: use it if a read looks wrong and you want to rule the node dump out, or if a desk misbehaves when asked for whole nodes. Names and tags are read one at a time either way, and so is any leaf a dump does not carry. |
| `--bulk-read` | Accepted and ignored: reading by node dump is now the default. Kept so scripts written when it was opt-in still run. See --per-leaf. |
| `--interval` `VALUE` | Seconds between reads (default: 2.0). Read-only polling -- WING's OSC offers only a single, network-wide event subscription that expires every 10 seconds, so nothing here pushes. Note this is the gap BETWEEN reads, not their period: one read of a live console is 6,197 addresses, fetched by node dump in about 320 requests and ~5 seconds on a WING Compact, so at the default a pass starts every seven seconds or so. With --per-leaf a read is about two minutes and an interval this short changes almost nothing. |
| `--count` `VALUE` | Stop after this many reads. Default: run until Ctrl-C for --console, or once through the list for --state-sequence. Against a live console budget ~5s per read plus --interval between them: --count 8 is about a minute. With --per-leaf it is ~2 minutes per read, so --count 8 is about 17 minutes. watch prints its own estimate before the first read, and each read reports its progress and how many addresses went unanswered. |
| `--name-refresh` `N` | Read strip, bus, DCA, mute-group and input-socket names on the first read and then every N reads, instead of every read. A node dump cannot carry a name, so on a WING Compact names are 88 of a read's ~320 requests. Default: 5 -- about every 30 seconds at the default --interval -- or 1 with --per-leaf. 1 reads names every time. Between refreshes each read carries the last names read, so every rule still runs; a rename shows up at the next refresh, and the findings say so at INFO (W001). |
| `--findings-log` `FILE` | Save what the watch finds to FILE as it runs (appended, flushed every pass, so Ctrl-C or a crash loses nothing): a header (atoo version and where it runs from, the console address and what the desk answered, the plan, the conditions, the start time), one JSON line per pass (findings standing, what appeared and what cleared, the meters, anything the desk did not answer) and a footer on a clean stop. Read-only: nothing is written to the desk, and no key is ever in it. |
| `--record-meters` `FILE` | With --console: write every meter packet the console sends to FILE as it comes, with its time (JSON lines), so the clips a watch reported can be replayed and checked later exactly as the desk sent them. Read-only, like the rest of watch. |
| `--watch-conditions` | Path to a JSON file of operator-authored watch conditions -- alerts on top of the built-in structural rules, e.g. "the crowd mic must never be unmuted." Optional; without it, only the built-in rules run. See the watch subcommand's own --help text for the file's shape. |
| `--virtual-soundcheck` | Say that a virtual soundcheck is under way, so channels on their alternate input (C004) and the global alternate switch (C005) are reported at INFO instead of as warnings. Every strip on its alternate is still named, and an INFO (W003) says the switch is on. It is for this run only; the next `atoo watch` starts with it off, and with it off a channel still on its alternate is a warning. |
