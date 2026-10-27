# Troubleshooting: building a plan

`build` failing, or stopping before it writes a plan. When `build` worked
but `verify` refuses the plan, see [When `verify` refuses a plan](troubleshooting-verify.md).

## `build` says "generation failed"

Every build calls a model, and there is no fallback that does not. It
is the only command that needs one: `verify`, `compare`, `apply`,
`audit`, `watch`, `ping` and `ui` all work on a plan that already
exists. The last line names the cause. There are three common ones.

**No API key.** The default model is Claude, which needs your key. With
none set, the build stops before it starts, and nothing on disk changes:
the show's `plan.json` is left exactly as it was.

```
build failed: a build needs a model: the default is Claude, which needs an API key in ANTHROPIC_API_KEY (or ATOO_AI_API_KEY) -- or set ATOO_AI_PROVIDER=ollama to use a local Ollama model instead. See 'Setting up an AI provider' in the user guide. Nothing was changed: plan.json is as it was.
```

Set it, as in [Setting up an AI provider](ai-provider.md):

```bash
export ANTHROPIC_API_KEY=...        # or ATOO_AI_API_KEY
```

**No internet.** Easy to hit at the desk: a laptop cabled to the WING's
network, with no uplink, cannot reach the model. The message explains this
after the raw error. This one came from `patch`, which calls the same
model; `build` prints the same words after `generation failed:`.

```
the change could not be compiled: The AI isn't responding.
  Reason: the call to https://api.anthropic.com failed: <urlopen error [Errno 8] nodename nor servname provided, or not known> -- this machine could not look up api.anthropic.com, so it has no internet connection right now. On the desk's network, keep a second connection (Wi-Fi or a phone hotspot) for the internet and the desk on its own port, then try again.
```

Keep the desk on Ethernet and the internet on Wi-Fi or a phone hotspot.
`atoo ping` to the desk and `curl -sI https://api.anthropic.com`
should both answer before you try again.

**A local model that is not running.** With
`ATOO_AI_PROVIDER=ollama`, the build asks an Ollama server on this
laptop, and fails if it is not there:

```
llama3.1 (generator): sending, waiting for the first reply... (a progress line every 10-60s -- stderr is not a terminal)
generation failed: The AI isn't responding.
  Reason: the call to http://localhost:11434 failed after 0 characters: <urlopen error [Errno 111] Connection refused>
```

Start Ollama (`ATOO_AI_BASE_URL` moves the address), or
`unset ATOO_AI_PROVIDER` to build on Claude. Local models have not
worked well so far.

A misspelt provider is named too:

```
generation failed: unknown ATOO_AI_PROVIDER 'bogus' -- expected 'ollama', 'claude' or 'api'
```

If the build first restates your conventions as rules
([the resolved conventions](conventions-reference.md#the-resolved-conventions)),
the same failure can appear twice: once as a WARNING for that step, which
the build carries on past, and once as the `generation failed` line,
which stops it.

## The AI isn't responding

Whenever the model's provider fails or
refuses a call (an error status, a refused or empty reply, a dropped
connection, a timeout, a rejected key), `build`, `patch` and the rest say
that, then give the provider's own reason on the next line. The reason is
the provider's, word for word; Atoo adds nothing to it and never prints
your key. A spend limit on your account or workspace shows up as one of
these, with the provider's words about the limit:

```
generation failed: The AI isn't responding.
  Reason: https://api.anthropic.com answered HTTP 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified workspace API usage limits."}}
  no plan was written; the build log keeps this attempt.
```

Read the reason, fix what it names (a key, a limit, a model name), and
run the command again. A `build` writes no plan when this happens, and
`patch` changes neither the desk nor the show. Atoo asks again only when
a host refuses an optional setting or the reply format; it does not retry
an error that asking again cannot clear. In the browser, step 04 shows
the same line and reason as its Failed finding.

## A build seems stuck

**Slow is not stuck.** A hosted model thinks for minutes before it
writes a word, and a local one on a laptop CPU can take longer. Each
call prints a progress line: redrawn in place on a terminal, every 10 to
60 seconds in a log, and live on Build step 04 in the browser. While it
reads `thinking -- 1m20s, not streamed`, the model is keeping its
reasoning to itself; the clock moving is the progress. A connection that
has really gone ends as `generation failed: ... timed out` after 600
seconds of silence on Claude (`ATOO_AI_TIMEOUT` sets it for
Ollama, whose default of 120 seconds a full plan on a CPU will need
raised).

**A build that is going wrong can be stopped**: **Stop** on Build step
04, or Ctrl-C in a terminal. The model stops, and so does the billing.
Nothing is written:

```
Stopped by you (Ctrl-C) after 18s. Nothing was written to the show; plan.json is unchanged.
```

The exit code is 130. A stop during the watch-conditions draft, after the plan
was written, reports that instead. The thinking summaries each call shows
are kept in the build's log, which [`atoo lessons`](lessons.md)
reads.

## `build` says the reply "hit max_tokens and is truncated"

```
$ atoo build --console-model wing-compact --input touringband/input.csv --conventions conventions.md --out plan.json
INFO resolved conventions: conventions.resolved.md is fresh (the conventions, the domain knowledge and the resolve prompt are unchanged) -- the generator reads it in place of the conventions and the domain knowledge
resolve: checked conventions.resolved.md: 169 of 169 citation(s) found; 58 of 58 conventions line(s) covered
INFO category table: 10 categories in conventions.resolved.md -- code writes their colour, DCA, mute group, gain, trim, fader and Main routing on every channel of the category whose reply leaves them out
claude-sonnet-5-5 (generator, effort medium): sending, waiting for the first reply... (a progress line every 10-60s -- stderr is not a terminal)
  claude-sonnet-5-5 (generator, effort medium): 21,480 in, 128,000 out (~122,929 of it thinking, not returned) -- $1.32
generation failed: Claude's reply hit max_tokens (128000) and is truncated. Check the usage line above before raising ATOO_AI_MAX_TOKENS: if most of the spend was thinking, a lower ATOO_AI_EFFORT buys the room more cheaply than a bigger ceiling does
  the 17,244 characters that did arrive are in plan.partial.json -- read them before changing anything
```

(Produced by the real `build` against a local stand-in for the Claude
API that stops its reply at the ceiling -- the numbers are the stand-in's,
not a real show's. The first three lines are the build reading its
[resolved conventions](conventions-reference.md#the-resolved-conventions),
which were already up to date.)

The model ran out of room before it finished writing the plan. Nothing
was written: `plan.json` is unchanged, the exit code is 1, and what did
arrive is saved beside it as `plan.partial.json` (inside the bundle, with
`--show`; `generation.partial.json` in the current directory when there
is no `--out`). Despite the name it is usually **not valid JSON** — it is
cut off mid-object, so it will not open as a plan; it is evidence, and it
was paid for. What you are reading is the model's *reply*, not a plan:
shorter than `plan.json` (no nulls, each bus's senders once, each channel
as its input-list row plus what was decided -- see [the pipeline
page](pipeline.md)), and written on one line; a partial that happens to be
whole JSON is saved pretty-printed. A `atoo patch` whose change could
not be compiled saves its partial reply the same way, as
`change.partial.json`.

**The usage line says which kind of "too long" it was.** Every output
token counts against the ceiling, and on a current Claude model most of
them are thinking, which is never returned:

- **Most of it thinking** (as above): the model reasoned itself out of
  room. Lower `ATOO_AI_EFFORT` (`medium` by default; `low` thinks
  less) before raising the ceiling -- it is cheaper, and a bigger ceiling
  mostly buys more of the same thinking.
- **Most of it plan**: the show is simply large. Read the
  `.partial.json` first. A plan that repeats one channel over and over is a model that
  lost its place, and more room will not help. One that is orderly and
  just unfinished needs more room: `ATOO_AI_MAX_TOKENS` raises the
  ceiling, but it defaults to the model's own output limit (`128000`, or
  `64000` on Haiku), so it can only go up on a model with a higher limit.
  On Haiku the generator's thinking budget (`ATOO_AI_THINKING_BUDGET`,
  16,000 by default) counts against that ceiling too; `0` turns it off.

The critic (`--critic`) and the watch-conditions draft can hit their own
ceiling, but they do not fail the build: it carries on without them,
saying `critic pass did not run: ...` or `watch-conditions draft did not run:
...` with the same sentence, which names their own effort setting
(`ATOO_AI_CRITIC_EFFORT`, `ATOO_AI_WATCHLIST_EFFORT`). Those
two run on `claude-sonnet-5-5` by default, whatever the generator runs on
(`ATOO_AI_CRITIC_MODEL`, `ATOO_AI_WATCHLIST_MODEL`). Set one to
a model with a lower output limit (Haiku's is `64000`) and that role is
sent that limit, and the number in the
sentence is the one that role was sent. Haiku takes no effort setting,
so on it the effort variable named has no purchase; the model variable
is the lever. In the browser the same sentence ends Build step 04 as
**Failed** ([below](troubleshooting-ui.md#build-step-04-says-failed)).

## See also

- [Troubleshooting](troubleshooting.md) — every symptom, and the page it is on
- [How a show gets built](pipeline.md) — the stages, and what each model call is for
- [Setting up an AI provider](ai-provider.md) — choosing and setting up the model
