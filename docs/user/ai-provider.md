# Setting up an AI provider

A build needs a model: it drafts the plan from your input list and conventions, and code checks the draft before anything can reach the desk. Only `atoo build` calls one, from the terminal or from Build in `atoo ui` (and `atoo resolve`, the step a build runs for you when your conventions change), and `patch` when you type the change in words. The Demo show, `verify`, `apply`, `audit` and `watch` never do, so you can leave this until your first build.

The model is chosen by environment variables. Put the `export` lines in your shell's startup file (`~/.zshrc` on a Mac, `~/.bashrc` on most Linux) so every new terminal has them. Start `atoo ui` from a terminal that has them too: the browser's builds run on the settings of the terminal that started the UI.

## Claude (what Atoo is tuned against)

```bash
export ATOO_AI_PROVIDER=claude
export ANTHROPIC_API_KEY=sk-ant-...     # or ATOO_AI_API_KEY
```

A key comes from the Anthropic Console ([console.anthropic.com](https://console.anthropic.com)), under **API keys**. That is all a Claude build needs. By default every call runs on `claude-sonnet-5-5`: the plan, the `--critic` review, the watch-conditions draft and the resolve step. `ATOO_AI_MODEL` changes the first; `ATOO_AI_CRITIC_MODEL`, `ATOO_AI_WATCHLIST_MODEL` and `ATOO_AI_RESOLVE_MODEL` change the other three.

**Never put the key in a file in a repository.** A shell startup file in your home directory is fine. `~/.atoo.config` is the wrong place: it has no key setting, on purpose.

Claude caches the start of each call, so later calls cost less; the [AI provider reference](ai-provider-reference.md#prompt-caching-claude) explains how.

## A local model with Ollama

Claude is the default. With `ATOO_AI_PROVIDER=ollama`, `build` asks an Ollama server on this machine (`http://localhost:11434`) for `llama3.1` instead. This is the only setup that works with no network at all. Plans from small local models have not been shown to be good enough for a real show, so check them hard. To choose the model:

```bash
export ATOO_AI_PROVIDER=ollama
export ATOO_AI_MODEL=qwen2.5-coder:7b
```

Two more settings are worth making for a local model:

```bash
export ATOO_AI_NUM_CTX=24576
export ATOO_AI_TIMEOUT=1800
```

- **`ATOO_AI_NUM_CTX`** is how much of the conversation the model holds at once, in tokens. Unset, Atoo sizes it to each request. Fixing it at `24576` keeps the model's memory use the same from one build to the next, and saves Ollama reloading the model when the size changes.
- **`ATOO_AI_TIMEOUT`** is how many seconds Atoo waits for the model to say anything before giving up: `120` by default on Ollama. A large local model reading a big show can be silent for longer than that, so give it `1800`.

**Memory.** A model of 14 to 30 billion parameters needs a machine with 32 GB of memory. An Apple Silicon Mac with 32 GB runs one entirely on its GPU at the context size above; a larger model spills onto the CPU and slows right down. With less memory, or no GPU, expect a build to take far longer.

## Any OpenAI-compatible host

```bash
export ATOO_AI_PROVIDER=api
export ATOO_AI_API_KEY=...
export ATOO_AI_MODEL=gpt-4o-mini
export ATOO_AI_BASE_URL=https://api.openai.com   # the host, without /v1
```

The [AI provider reference](ai-provider-reference.md) has what an `api` call sends, what happens when a host refuses part of it, and how to price a host.

## Confirm which model is in use

A build names the model before it sends anything. On a Claude build the plan's call looks like this:

```
claude-sonnet-5-5 (generator, effort medium): sending, waiting for the first reply...
```

and with `ATOO_AI_PROVIDER=ollama` like this:

```
llama3.1 (generator): sending, waiting for the first reply...
```

The first build after your conventions change makes one call before that, to resolve them. It is named the same way, as `(resolve, effort medium)` on Claude, and the line above it says why.

With no key, a build stops before it sends anything, and says both ways forward:

```
generation failed: a build needs a model: the default is Claude, which needs an API key in ANTHROPIC_API_KEY (or ATOO_AI_API_KEY) -- or set ATOO_AI_PROVIDER=ollama to use a local Ollama model instead
```

When the provider is reached and answers with an error (a rejected key, a rate or spend limit, a server error) or does not answer at all, the command says **The AI isn't responding.** and, on the next line, the provider's own reason. It is the same for Claude, an `api` host and Ollama. See [the build troubleshooting page](troubleshooting-build.md#the-ai-isnt-responding).

The effort levels, token limits, thinking budget and timeouts are in the full table in the [CLI reference](cli-reference.md#choosing-and-tuning-the-model). You do not need any of them to get started.

---

## Next

[Build your first show](change-the-demo.md): your own copy of the Demo show, changed, applied to your desk and watched.
