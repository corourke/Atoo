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

Claude is the default. With `ATOO_AI_PROVIDER=ollama`, Atoo asks an Ollama server on this machine (`http://localhost:11434`) instead. This is the only setup that works with no network at all: your show never leaves the laptop, there is no key or account, and a build costs nothing.

A local model works best with `--intent` (`atoo build --intent`, `atoo patch --intent`), where the model says only what your files leave open and Atoo's own code writes the rest ([Let the model say less](build-a-show.md#let-the-model-say-less---intent)).

### Which model

**Every local model is experimental: Claude is the one we recommend.**

We test each model on twenty shows, from an acoustic duo to a festival changeover, and count how much of each show comes out as asked.

| Model | Memory it uses | How it did |
|---|---|---|
| `qwen2.5-coder:14b` | about 9 GB | The best of these. It passed on all twenty of our test shows, with 99% of what we check right; on five shows held back from all our tuning, it built one fully, with 88% of what we check right. On a show it hasn't seen, it most often puts a bus's output or an input on a different socket from the one your conventions ask for, so check the sockets in the plan first. |
| `devstral-small-2:24b` | about 18 GB | Builds our three everyday shows and makes our fifteen test changes, but measured lower on the twenty. |
| `granite4.1:30b` | about 24 GB | Builds our three everyday shows and makes our fifteen test changes, but measured lower on the twenty. Near the limit of a 32 GB machine. |

`qwen3-coder:30b` made our fifteen test changes and came close on the three everyday shows; we have not tested it on the twenty.

These results are a snapshot: `qwen2.5-coder:14b` was measured in early November 2026, the other two on October 28, before the latest fixes. Each fix to Atoo's own code can move them.

Whichever model you use, read the findings and the plan before you apply it, and expect more to check than with Claude.

The memory figures are on an Apple Silicon Mac with 32 GB, running fully on its GPU, with the settings below. A larger model spills onto the CPU and slows right down; with less memory, or no GPU, expect a build to take far longer.

### Setting it up

1. Install [Ollama](https://ollama.com), start it, and pull the model:

   ```bash
   ollama pull qwen2.5-coder:14b
   ```

2. Point Atoo at it:

   ```bash
   export ATOO_AI_PROVIDER=ollama
   export ATOO_AI_MODEL=qwen2.5-coder:14b
   export ATOO_AI_NUM_CTX=24576
   export ATOO_AI_TIMEOUT=1800
   ```

3. Build with `--intent`:

   ```bash
   atoo build --show touringband --intent
   ```

| Variable | What it does |
|---|---|
| `ATOO_AI_MODEL` | The Ollama model. Without it, Atoo asks for `llama3.1`, which we have not tested. |
| `ATOO_AI_NUM_CTX` | How much of the conversation the model holds at once, in tokens. `24576` is the size the models above were tested at; fixing it keeps memory use steady and saves Ollama reloading the model. |
| `ATOO_AI_TIMEOUT` | How many seconds Atoo waits for the model to say anything: `120` by default. A local model reading a big show can be silent for longer, so give it `1800`. |
| `ATOO_AI_NUM_PREDICT` | A limit on how long a reply can be. Leave it unset for a build. |
| `ATOO_AI_BASE_URL` | Where Ollama is, if not on this machine (`http://localhost:11434`). |

### Ollama's cloud models

Ollama also runs larger open-weight models on its own servers, named with `:cloud` (for example `gemma4:cloud`). Atoo talks to them the same way, through the Ollama on your machine, but they are not free and not local:

- You need an [ollama.com](https://ollama.com) account: run `ollama signin` once, and your local Ollama passes cloud requests on for you.
- Use is paid for in usage credits; see [Ollama's pricing](https://ollama.com/pricing).
- Your show's text goes to Ollama's servers.

Then set `ATOO_AI_MODEL` to the cloud model's name. **We have not tested any cloud model yet**, so treat one as untested.

### Want a model that isn't listed?

Open a [Discussion](https://github.com/corourke/Atoo/discussions) or an Issue on corourke/Atoo ([Reporting a problem](reporting.md)) naming the model, its size and its quant, and we'll put it through the same tests before saying whether it works.

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

and with `ATOO_AI_PROVIDER=ollama` and `--intent` like this:

```
qwen2.5-coder:14b (intent): sending, waiting for the first reply...
```

The first build after your conventions change makes one call before that, to resolve them. It is named the same way, as `(resolve, effort medium)` on Claude, and the line above it says why.

With no key, a build stops before it sends anything, and says both ways forward:

```
generation failed: a build needs a model: the default is Claude, which needs an API key in ANTHROPIC_API_KEY (or ATOO_AI_API_KEY) -- or set ATOO_AI_PROVIDER=ollama to use a local Ollama model instead
```

When the provider is reached and answers with an error (a rejected key, a rate or spend limit, a server error) or does not answer at all, the command says **The AI isn't responding.** and, on the next line, the provider's own reason. It is the same for Claude, an `api` host and Ollama. See [the build troubleshooting page](troubleshooting-build.md#the-ai-isnt-responding).

The effort levels, token limits, thinking budget and timeouts are in the full table in the [CLI reference](cli-reference.md#choosing-and-tuning-the-model). You do not need any of them to get started.

---

## What leaves your laptop

A model call sends text to the provider you set, and nothing else leaves the laptop. With Ollama on this machine, nothing leaves at all.

- **A build** sends your conventions and the show's `instructions.md`, and the whole input list, its `notes` column included. Its review passes (the critic and the watch-condition draft) send the plan it built: every channel, bus and output, with their names and sockets, and which WING it is for.
- **A Patch typed in words** sends what you typed, your conventions and `instructions.md`, and the plan on the desk: every channel, bus, output, DCA and mute group, by the names the desk shows.
- **`atoo resolve`** sends your conventions.

Never sent: the desk's address, the folders your files are in (a file goes by its name alone, such as `house.md`), the snapshots under `captures/`, the journal of writes, or anything Watch finds. Watch, Apply, `verify` and `audit` call no model.

## Next

[Build your first show](change-the-demo.md): your own copy of the Demo show, changed, applied to your desk and watched.
