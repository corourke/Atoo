"""Close a JSON document a model left open, and say so.

A local model spent 85 minutes producing a complete, correctly ordered
19-channel plan for `touringband` and the result was unusable, because the
`busses` object was missing one closing brace. Every channel was right.
Every input was placed. One character.

Throwing that away is the wrong trade. But so is quietly "fixing" model
output, because the same missing brace could mean a reply that was cut off
halfway -- and a plan silently repaired from a truncated reply is a plan
missing channels that looks complete.

So the rule here is narrow on purpose:

  - ONLY unterminated structures at the very end of the document are
    closed. Nothing in the interior is touched, ever.
  - Every repair is REPORTED. The caller decides whether a document that
    needed closing is one it trusts.
  - Verification still runs afterwards. A repair that papered over a
    truncation shows up as dropped inputs, which is an error.

What this deliberately does not do: fix missing commas, quote bare keys,
strip trailing commas, or any of the other things a "tolerant JSON parser"
does. Those are guesses about intent. Closing a structure at EOF is not.
"""

from __future__ import annotations

import re

import json


def _scan(text: str) -> list[str]:
    """The closers needed to balance `text`, outermost last.

    A hand-rolled scan rather than a regex because strings can contain
    braces, and escapes can contain quotes: `"name": "A }{ \\" b"` is one
    string and zero structure.
    """
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            escaped = False
            continue
        if in_string:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
            else:
                # Mismatched or extra closer: not something to guess at.
                return []
    if in_string:
        return []          # cut off mid-string; closing it would invent data
    return list(reversed(stack))


def loads_with_repair(text: str, *, expect_keys: frozenset[str] = frozenset()) -> tuple[dict, list[str]]:
    """Parse `text`, closing structures left open at the end if needed.

    `expect_keys` is the caller's knowledge of what the document's
    top-level keys should be, and it is what makes this safe. Appending
    closers at EOF assumes the missing closer belongs at the END -- and
    that assumption is often wrong.

    The real case this was written for: a 14B model produced a 19-channel
    plan whose `busses` object was missing one `}`. Closing at EOF DID
    yield valid JSON -- with `outputs`, `unassigned_inputs` and `notes`
    swallowed into `busses`, and no `outputs` at top level at all. Parsed
    fine. Completely wrong. A brace missing in the middle cannot be
    repaired from the end, and the only reliable signal that it happened
    is that keys the caller expected are no longer where they belong.

    So a repair whose result is missing an expected key is discarded, and
    the original error raised. Better to hand back the raw reply and let a
    human look than to hand back a confidently wrong document.

    Returns the object and repair notes -- empty when it parsed as-is.
    """
    try:
        return json.loads(text), []
    except json.JSONDecodeError as first_error:
        closers = _scan(text)
        if not closers:
            raise

        trimmed = text.rstrip().rstrip(",")
        try:
            value = json.loads(trimmed + "".join(closers))
        except json.JSONDecodeError:
            raise first_error from None
        if not isinstance(value, dict):
            raise first_error from None

        missing = {k for k in expect_keys if k in text} - set(value)
        if missing:
            raise json.JSONDecodeError(
                f"a closing {''.join(closers)} would make this parse, but then "
                f"{sorted(missing)} would no longer be top-level key(s) -- the missing "
                "character belongs somewhere in the middle, not at the end, and guessing "
                "where would invent structure. Repair it by hand, or re-run",
                first_error.doc, first_error.pos,
            ) from None

        return value, [
            f"the reply was missing {len(closers)} closing "
            f"{'character' if len(closers) == 1 else 'characters'} "
            f"({''.join(closers)}) and was closed to parse it -- check that nothing "
            "is missing from the end"
        ]


# --------------------------------------------------------------------------
# Unwrapping a model's reply before it can be parsed at all.
#
# Moved here from extract.py when the deterministic compile path was retired. It has nothing to do with extraction -- it is the same
# "a model wrapped its JSON in prose" problem this module already exists to
# solve, one step earlier. `generate.py` is the caller.
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

def extract_json_object(text: str) -> dict:
    """Models routinely wrap JSON in ```json fences, or preface it with a
    sentence, despite being told not to (found against real models by
    archive/experiments/archive/spike_ai_conventions.py, 2026-09-10) -- search for
    a fenced
    block anywhere in the response and fall back to the whole text."""
    text = text.strip()
    match = _FENCE_RE.search(text)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


# The pre-#29 private spelling from extract.py, kept because generate.py and
# its tests were written against it.
_extract_json_object = extract_json_object
