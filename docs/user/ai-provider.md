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

## Any OpenAI-compatible host

```bash
export ATOO_AI_PROVIDER=api
export ATOO_AI_API_KEY=...
export ATOO_AI_MODEL=gpt-4o-mini
export ATOO_AI_BASE_URL=https://api.openai.com   # the host, without /v1
```

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

The effort levels, token limits, thinking budget and timeouts are in the
full table in the
[CLI reference](cli-reference.md#choosing-and-tuning-the-model). You do
not need any of them to get started.

---

## Next

[Change the Demo show](change-the-demo.md): your first build, on a copy
of the Demo, then a change onto the desk.
