# Setting up an AI provider

A build needs a model: it drafts the plan from your input list and
conventions, and code checks the draft before anything can reach the
desk. Only `atoo build` calls one, from the terminal or from Build in
`atoo ui` (and `atoo resolve`, the step a build runs for you when your
conventions change), and `patch` when you type the change in words. The
Demo show, `verify`, `apply`, `audit` and `watch` never do, so you can
leave this until your first build.

The model is chosen by environment variables. Put the `export` lines in
your shell's startup file (`~/.zshrc` on a Mac, `~/.bashrc` on most
Linux) so every new terminal has them. Start `atoo ui` from a
terminal that has them too: the browser's builds run on the settings of
the terminal that started the UI.

## Claude (what Atoo is tuned against)

```bash
export ATOO_AI_PROVIDER=claude
export ANTHROPIC_API_KEY=sk-ant-...     # or ATOO_AI_API_KEY
```

A key comes from the Anthropic Console
([console.anthropic.com](https://console.anthropic.com)), under **API
keys**. That is all a Claude build needs. By default every call runs on
`claude-sonnet-5-5`: the plan, the `--critic` review, the
watch-conditions draft and the resolve step. `ATOO_AI_MODEL` changes the first;
`ATOO_AI_CRITIC_MODEL`, `ATOO_AI_WATCHLIST_MODEL` and
`ATOO_AI_RESOLVE_MODEL` change the other three.

**Never put the key in a file in a repository.** A shell startup file in
your home directory is fine. `~/.atoo.config` is the wrong place:
it has no key setting, on purpose.

### Prompt caching (Claude)

Every Build, Patch, repair and review call sends a large prompt that is
mostly the same each time: the audio knowledge, the format, your
conventions, the desk as it stands. Atoo asks Anthropic to keep that part
(its *prompt cache*), so the next call that starts with the same text is
read back at a fraction of the price instead of paid for in full. **It needs
nothing from you**: no setting, no key option, and the model's answers do not
change, only what the call costs. It is on for every Claude model.

The usage line shows what the cache did. `in` is every input token, and the
brackets say where it went:

```
  claude-sonnet-5-5 (change, effort medium): 41,120 in (520 uncached, 40,600 cache write, 0 cache read), 3,400 out -- $0.14
  claude-sonnet-5-5 (change, effort medium): 41,240 in (640 uncached, 0 cache write, 40,600 cache read), 3,100 out -- $0.04
```

- **uncached** is paid at the model's normal input price: the part that is
  different on every call (your change request, the reply that was refused).
- **cache write** is the part stored for next time. It costs 25% more than
  normal input.
- **cache read** is the part found already stored. It costs a tenth of normal
  input, or a twentieth on Sonnet 5.5 and Opus 5.5.

The dollar figure is what Anthropic bills for that mix, not the token count
times one price. The second line above is the same show a moment later:
nearly everything is read back, and the call costs less than a third of
the first. A repair after a refused change, and the next fix-up round of a
build, read what the call before them wrote in the same way.

**The cache lasts five minutes** from the last call that used it, and each
use renews it. Run something after a longer pause and that call writes the
prefix again (its line shows a cache write and no read, and costs a little
more than it would have without caching); the rest of that session reads it.
A call that is the only one of its kind in five minutes, such as one review
after one build, pays the write and reads nothing: that is the price of
the reads elsewhere.

If a call's prefix is shorter than the model can cache (512 tokens on Sonnet
5.5, 1,024 on Sonnet 5, 4,096 on Haiku 4.5; Anthropic's published minimums),
nothing is cached, and the line shows why, for example
`300 in (prefix ~300 tokens, below the 512-token minimum, not cached)`. If the
prefix is long enough and the API still reports nothing written or read, the
line says that too. The Setup page's Build log shows the same split beside each
call's cost.

## A local model with Ollama

Claude is the default. With `ATOO_AI_PROVIDER=ollama`, `build` asks
an Ollama server on this machine (`http://localhost:11434`) for
`llama3.1` instead. This is the only setup that works with no network at
all. Plans from small local models have not
been shown to be good enough for a real show, so check them hard. To
choose the model:

```bash
export ATOO_AI_PROVIDER=ollama
export ATOO_AI_MODEL=qwen2.5-coder:7b
```

Two more settings are worth making for a local model:

```bash
export ATOO_AI_NUM_CTX=24576
export ATOO_AI_TIMEOUT=1800
```

- **`ATOO_AI_NUM_CTX`** is how much of the conversation the model holds at
  once, in tokens. Unset, Atoo sizes it to each request. Fixing it at
  `24576` keeps the model's memory use the same from one build to the
  next, and saves Ollama reloading the model when the size changes.
- **`ATOO_AI_TIMEOUT`** is how many seconds Atoo waits for the model to
  say anything before giving up: `120` by default on Ollama. A large
  local model reading a big show can be silent for longer than that, so
  give it `1800`.

**Memory.** A model of 14 to 30 billion parameters needs a machine with
32 GB of memory. An Apple Silicon Mac with 32 GB runs one entirely on its
GPU at the context size above; a larger model spills onto the CPU and
slows right down. With less memory, or no GPU, expect a build to take far
longer.

## Any OpenAI-compatible host

```bash
export ATOO_AI_PROVIDER=api
export ATOO_AI_API_KEY=...
export ATOO_AI_MODEL=gpt-4o-mini
export ATOO_AI_BASE_URL=https://api.openai.com   # the host, without /v1
```

### What an `api` call sends, and what happens when a host says no

One code path serves every OpenAI-compatible host; nothing in it knows a
vendor's name. A call sends the model, your system and user text,
`temperature: 0`, `stream` (see `ATOO_AI_STREAM`), and **the reply format
as `response_format`**: a strict `json_schema`, so a host that holds to it
cannot return a reply of the wrong shape. Atoo derives that schema from
its own reply format in code. Strict mode cannot describe an object whose
keys are names you choose (the busses, DCAs, mute groups and outputs a
change adds), so those travel as lists of `{key, value}` entries and are
turned back into the objects Atoo reads; a field a reply may leave out is
written `null`, and read as not stated. Atoo still checks every reply
against its full format, whatever the host held to.

A host that does not know one of these fields answers 400 and names it.
Atoo asks again **once per field, without it**, and prints:

```
INFO the host at https://api.example.com refused `response_format` (Unknown field: response_format); asked again without it -- the reply is still checked against the full plan format here
```

The fields that are retried this way are `response_format`,
`stream_options`, `temperature` (a model that reasons may refuse it),
`reasoning_effort` and `max_completion_tokens`. A field the host refuses is
remembered for the rest of the run (the INFO says "not sent again this run"),
so later calls do not pay for a refused request; a model that rejects
`reasoning_effort` (`grok-build-0.1` does) costs one refused request, not one
per call. Any other 400, and any
other error, is shown as it came; nothing is retried that might spend
twice.

| Variable | Does |
|---|---|
| `ATOO_AI_STRUCTURED` | `0` stops sending the reply format as `response_format` |
| `ATOO_AI_REASONING_EFFORT` | sent as `reasoning_effort` (the host's own words: `low`, `medium`, `high`) to a model that reasons; unset sends nothing. A long wait with little output is usually a reasoning model thinking, and a lower effort shortens it |
| `ATOO_AI_TIMEOUT` | seconds of silence before a call is given up on. **Atoo chose 600 for the `api` provider** (120 on Ollama): a reasoning model can think for minutes before its first token, and 120 s cut those calls off. Raise it for a slower model, lower it to fail faster |
| `ATOO_AI_MAX_TOKENS` | sent as `max_completion_tokens`, which counts a reasoning model's hidden tokens too; unset sends none |

**A reply that fails the format is sent back once.** When a change's reply
does not match the change-set format (a field of the wrong type, a missing
key), or the desk refuses what it proposed (a bus that is not there), Atoo
sends the same request again with the reply and the exact message, and
asks for the corrected change set. It is one extra call, never more; both
calls print their usage line (the second is labelled `change-repair`) and
the second is said at INFO. The Claude provider does not do this.

A `null` in a place where the format lets a reply say nothing is not
refused: it is read as left out, and an INFO names the fields. A `null`
48V (`source.phantom`) is read as off, and a `null` `patch.stated` as
"chosen, not named"; both are said.

### Pricing a host

Atoo knows what Claude models cost, so a Claude call ends its usage line
with a dollar figure. It does not know any other host's rates and will
not guess them. With nothing more set, an `api` call ends like this:

```
  my-model (generator): 21,027 in, 6,100 out -- no price set
```

Give it your host's rates, in dollars per million tokens (read them off
the host's price list; both are required, or neither):

```bash
export ATOO_AI_PRICE_IN=0.20     # per million input tokens
export ATOO_AI_PRICE_OUT=0.50    # per million output tokens
```

and the line carries the same `-- $x.xx` a Claude call prints, and the
build log records the cost:

```
  my-model (generator): 21,027 in, 6,100 out -- $0.01
```

Setting only one of the two is refused, and so is a value that is not a
number of dollars (`ATOO_AI_PRICE_IN and ATOO_AI_PRICE_OUT go together
(dollars per million input and output tokens): set both, or neither`).
The rates change nothing about which model runs or what is sent.

Three things refine the figure, and the usage line says when one applies:

- **A host that reports its own cost is believed.** xAI sends
  `usage.cost_in_usd_ticks` (ticks of 1/10,000,000,000 of a dollar; that unit
  is assumed from xAI's documentation, not yet checked against a live reply).
  The `-- $x.xx` then ends `(host-reported cost)` and the build log and the live
  eval's `report.json` carry it. Your prices stay the fallback for a host that
  gives none.
- **Reasoning tokens.** xAI's `completion_tokens` leaves out
  `reasoning_tokens`, so counting only `completion_tokens` understates a
  reasoning model. When the host's `total_tokens` shows they were kept out,
  Atoo bills them as output and the line ends `(reasoning tokens counted as
  output)`. OpenAI counts them inside `completion_tokens`; nothing is added
  there.
- **Cached input.** Set `ATOO_AI_PRICE_CACHED` (dollars per million cached
  tokens) and input the host reports as cached
  (`prompt_tokens_details.cached_tokens`) is priced at that rate. Atoo also
  sends an `x-grok-conv-id` header, a random id that is the same for every
  call of one run and is not derived from your key, so xAI can cache the
  prompt prefix; a host that does not know it ignores it. Its name is not a
  setting.

## Check it took

A build names the model before it sends anything. On a Claude build the
plan's call looks like this:

```
claude-sonnet-5-5 (generator, effort medium): sending, waiting for the first reply...
```

and with `ATOO_AI_PROVIDER=ollama` like this:

```
llama3.1 (generator): sending, waiting for the first reply...
```

The first build after your conventions change makes one call before
that, to resolve them. It is named the same way, as
`(resolve, effort medium)` on Claude, and the line above it says why.

With no key, a build stops before it sends anything, and says both ways
forward:

```
generation failed: a build needs a model: the default is Claude, which needs an API key in ANTHROPIC_API_KEY (or ATOO_AI_API_KEY) -- or set ATOO_AI_PROVIDER=ollama to use a local Ollama model instead
```

When the provider is reached and answers with an error (a rejected key,
a rate or spend limit, a server error) or does not answer at all, the
command says **The AI isn't responding.** and, on the next line, the
provider's own reason. It is the same for Claude, an `api` host and
Ollama. See [the build troubleshooting
page](troubleshooting-build.md#the-ai-isnt-responding).

The effort levels, token limits, thinking budget and timeouts are in the
full table in the
[CLI reference](cli-reference.md#choosing-and-tuning-the-model). You do
not need any of them to get started.

---

## Next

[Change the Demo show](change-the-demo.md): your first build, on a copy
of the Demo, then a change onto the desk.
