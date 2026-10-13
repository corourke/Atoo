#!/usr/bin/env python3
"""Generate `docs/user/cli-reference.md` from the CLI's own argparse tree.

An earlier change, and the maintainer's call on the one decision it carried: the
reference is generated, not hand-written, because a hand-written one
drifts. The old hand-written reference (a section of the desk-testing
walkthrough) drifted from `--help` more than once; it was deleted when this file took over.

    python3 tools/gen_cli_reference.py          # rewrite the file
    python3 tools/gen_cli_reference.py --check  # exit 1 if it is stale

`tests/test_cli_reference.py` runs the second form, so a flag added to
`cli.py` without regenerating fails the suite rather than quietly
shipping an incomplete reference.

**Hand-written prose survives.** Everything between a command's
`<!-- preamble:start -->` and `<!-- preamble:end -->` is carried across
untouched -- that is where "what this command is for, in a sentence a
person wants" belongs. Argparse holds the flags; it does not hold the
intent.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "docs" / "user" / "cli-reference.md"

# Generate from THIS checkout, not from whatever `atoo` happens to be
# installed. Run as a script, `sys.path[0]` is `tools/`, so `import
# atoo` would otherwise resolve through the editable install -- which
# points at the primary clone. In a `git worktree` (which CLAUDE.md's
# review discipline uses for every PR) that silently generated the
# reference for a DIFFERENT tree: the generator and the test disagreed, and
# `--check` passed while the test failed. Found resolving an earlier change.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PREAMBLE_RE = re.compile(
    r"<!-- preamble:start -->\n(.*?)\n<!-- preamble:end -->", re.S)

HEADER = """<!-- GENERATED FILE -- edit the preamble blocks only.

     Every option table below comes from `atoo/cli.py`'s argparse
     tree via `tools/gen_cli_reference.py`. Editing a table by hand will
     be overwritten, and `tests/test_cli_reference.py` will fail until
     the file is regenerated:

         python3 tools/gen_cli_reference.py

     Text inside a `<!-- preamble:start/end -->` block IS hand-written
     and is preserved across regeneration. Put the "why you would use
     this" there.
-->

# Command reference

Every command and every option, generated from the code so it cannot
drift. For how to *use* these together, start at
[`README.md`](README.md).

<!-- preamble:start -->
__INTRO__
<!-- preamble:end -->

"""

# Front matter for the page as a whole -- the environment table lives here
# because environment variables are not in the argparse tree and so cannot
# be generated. Used only when the file does not exist yet; after that the
# committed text is preserved like any other preamble.
DEFAULT_INTRO = """## Environment variables

None of these are argparse options, so none appear in the tables below.
They configure the AI provider that `atoo build` uses to generate a
plan, and that `build --critic` uses for the review pass. Every other
command ignores them entirely -- `verify`, `compare`, `apply`, `audit`
and `watch` never call a model.

| Variable | Applies to | Default |
|---|---|---|
| `ATOO_AI_PROVIDER` | all | `claude` (needs `ANTHROPIC_API_KEY`) -- or `ollama` for a local model, or `api` for any OpenAI-compatible host |
| `ATOO_AI_MODEL` | all | `claude-sonnet-5-5` / `llama3.1` / `gpt-4o-mini` |
| `ATOO_AI_API_KEY` | claude, api | -- (`claude` also reads `ANTHROPIC_API_KEY`) |
| `ATOO_AI_BASE_URL` | all | per provider |
| `ATOO_AI_NUM_CTX` | ollama | unset = sized per prompt |
| `ATOO_AI_NUM_PREDICT` | ollama | unset = unlimited (`-1`) |
| `ATOO_AI_TIMEOUT` | ollama | `120` seconds |
| `ATOO_AI_EFFORT` | claude | `medium` (`low`...`max`) -- the generator's |
| `ATOO_AI_CRITIC_EFFORT` | claude | `medium` (`low`...`max`) -- the critic's (`--critic`) |
| `ATOO_AI_WATCHLIST_EFFORT` | claude | `medium` (`low`...`max`) -- the watchlist draft's. None of the three is sent to Haiku 4.5, which takes no effort |
| `ATOO_AI_CRITIC_MODEL` | claude | `claude-sonnet-5-5` -- the model the critic (`--critic`) runs on; set it to `ATOO_AI_MODEL`'s value to run it on the generator's |
| `ATOO_AI_WATCHLIST_MODEL` | claude | `claude-sonnet-5-5` -- the model the watchlist draft runs on, likewise. Both announced on the `INFO model and effort by role` line |
| `ATOO_AI_FIXUP_ROUNDS` | all | `1` -- when a built plan fails verify with errors, or the reply fails the format check, the reply and the exact messages go back to the generator's model once (role `fixup`, the generator's model and effort) for a corrected reply; `0` turns it off, and more than one round is never spent |
| `ATOO_AI_THINKING_BUDGET` | claude | `16000` -- `budget_tokens` for the generator on a model that thinks only when given a budget (Haiku 4.5); `0` turns it off. Ignored on the adaptive-thinking models; never sent to the critic or the watchlist |
| `ATOO_AI_MAX_TOKENS` | claude | the model's output limit: `128000`, or `64000` on Haiku (thinking tokens count against it). A role on a model with a lower limit is sent that limit |
| `ATOO_AI_THINKING_SUMMARIES` | claude | on -- `0` stops asking for the thinking summaries step 04 shows while the model thinks |
| `ATOO_AI_STREAM` | api | on -- `0` asks the host for one reply instead of a stream (step 04 then has no live text) |
| `ATOO_PROMPT_DIR` | generate, critic | the packaged `atoo/prompts` |"""


def _options(parser: argparse.ArgumentParser) -> list[tuple[str, str]]:
    """(invocation, help) for every option this parser defines, in order."""
    rows = []
    for action in parser._actions:                       # noqa: SLF001
        if not action.option_strings:
            continue
        if isinstance(action, argparse._HelpAction):      # noqa: SLF001
            continue
        if action.help == argparse.SUPPRESS:
            continue
        flags = ", ".join(f"`{s}`" for s in action.option_strings)
        if action.metavar:
            flags += f" `{action.metavar}`"
        elif action.nargs != 0 and action.type is not None:
            flags += " `VALUE`"
        rows.append((flags, " ".join((action.help or "").split())))
    return rows


def _command_section(name: str, parser: argparse.ArgumentParser,
                     preamble: str) -> str:
    out = [f"## `atoo {name}`", ""]
    out += ["<!-- preamble:start -->", preamble or "_Not written yet._",
            "<!-- preamble:end -->", ""]

    description = (parser.description or "").strip()
    if description:
        out += ["```", description, "```", ""]

    rows = _options(parser)
    if rows:
        out += ["| Option | What it does |", "|---|---|"]
        out += [f"| {flags} | {help_text} |" for flags, help_text in rows]
        out += [""]
    return "\n".join(out)


def render() -> str:
    from atoo.cli import build_parser

    existing = TARGET.read_text() if TARGET.exists() else ""
    preambles = _existing_preambles(existing)

    _root, subparsers = build_parser()
    parts = [HEADER.replace("__INTRO__", _existing_intro(existing))]
    for name in sorted(subparsers):
        parts.append(_command_section(name, subparsers[name],
                                      preambles.get(name, "")))
    return "\n".join(parts).rstrip("\n") + "\n"


def _existing_intro(text: str) -> str:
    """The page's hand-written front matter, above the first command.

    Everything the reference needs to say that argparse cannot hold --
    environment variables above all -- lives here, and is carried across a
    regeneration exactly like a per-command preamble. The old hand-written
    reference used to be the only place the environment table existed,
    which is why deleting it needed somewhere for the table to go first.
    """
    head = re.split(r"^## `atoo ", text, flags=re.M)[0]
    match = PREAMBLE_RE.search(head)
    return match.group(1) if match else DEFAULT_INTRO


def _existing_preambles(text: str) -> dict[str, str]:
    """Hand-written preamble per command, keyed by command name."""
    out: dict[str, str] = {}
    for block in re.split(r"^## `atoo ", text, flags=re.M)[1:]:
        name = block.split("`", 1)[0]
        match = PREAMBLE_RE.search(block)
        if match and match.group(1).strip() != "_Not written yet._":
            out[name] = match.group(1)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="Exit 1 if the committed file is stale, writing nothing.")
    args = ap.parse_args(argv)

    wanted = render()
    if args.check:
        current = TARGET.read_text() if TARGET.exists() else ""
        if current == wanted:
            return 0
        print(f"{TARGET.relative_to(REPO)} is stale -- run "
              f"`python3 tools/gen_cli_reference.py`", file=sys.stderr)
        return 1

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(wanted)
    print(f"wrote {TARGET.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
