"""Every JSON example the intent prompts show a model is a key order the decoding grammar allows.

On Ollama the reply schema is sent as `format`, and llama.cpp turns it into a grammar
(`common/json-schema-to-grammar.cpp`, `_build_object_rule`) that fixes the key order of every
object: the required keys first, in the order the schema declares them, then any of the optional
keys, in declared order. A key declared BEFORE one already written can no longer be written. So an
example that writes `mode` before `members` teaches a model a reply in which, under the grammar,
`members` is impossible -- every bus came out empty on the local models (2026-10-24). This holds
the prompts' examples to the schemas' order, so the two cannot drift apart again."""

from __future__ import annotations

import json
import re

import pytest

from atoo import category_table, generate, intent_schema, intent_steps

PROMPTS = ["intent.md", "intent_build.md", *(s.prompt for s in intent_steps.STEPS)]
CONSOLE = "wing-compact"


def _objects(text: str) -> list[dict]:
    """Every JSON object in `text` that starts with `{"` and parses, outermost first."""
    found = []
    for m in re.finditer(r'\{\s*"', text):
        depth, i = 0, m.start()
        for j in range(i, len(text)):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                try:
                    found.append(json.loads(text[i:j + 1]))
                except ValueError:
                    pass
                break
    return found


def _branches(schema: dict) -> dict[str, dict]:
    return {b["properties"]["op"]["enum"][0]: b for b in schema["properties"]["ops"]["items"]["oneOf"]}


def _object_schema(schema: dict) -> dict | None:
    """The object schema inside a (possibly nullable) property, or None."""
    if not isinstance(schema, dict):
        return None
    if schema.get("properties"):
        return schema
    for alt in schema.get("anyOf") or schema.get("oneOf") or []:
        found = _object_schema(alt)
        if found:
            return found
    return None


def order_problems(value: dict, schema: dict, where: str) -> list[str]:
    """Where `value`'s keys are not an order the grammar of `schema` allows, recursively."""
    props = list(schema.get("properties") or {})
    required = [k for k in props if k in set(schema.get("required") or [])]
    optional = [k for k in props if k not in set(required)]
    keys = list(value)
    problems = []
    if keys[:len(required)] != required:
        problems.append(f"{where}: starts {keys[:len(required)]}, the grammar requires {required} first")
    else:
        rest = [k for k in keys[len(required):] if k in optional]
        if rest != sorted(rest, key=optional.index):
            problems.append(f"{where}: optional keys {rest}, the grammar allows them only in the order {optional}")
    for k, v in value.items():
        sub = _object_schema((schema.get("properties") or {}).get(k))
        if isinstance(v, dict) and sub:
            problems += order_problems(v, sub, f"{where}.{k}")
        if isinstance(v, list):
            items = (schema.get("properties") or {}).get(k, {}).get("items")
            sub_items = _object_schema(items) if isinstance(items, dict) and "oneOf" not in items else None
            for n, x in enumerate(v):
                if isinstance(x, dict) and sub_items:
                    problems += order_problems(x, sub_items, f"{where}.{k}[{n}]")
    return problems


def check(obj: dict, prompt: str) -> list[str]:
    build = intent_schema.intent_schema(CONSOLE, build=True)
    if "op" in obj:
        branch = _branches(build).get(obj["op"])
        return order_problems(obj, branch, f"{prompt}: {obj['op']} {obj.get('name')!r}") if branch else []
    if "ops" in obj:
        step = next((s for s in intent_steps.STEPS if s.prompt == prompt), None)
        schema = intent_steps.step_schema(CONSOLE, step) if step else build
        problems = []
        keys = [k for k in obj if k in schema["properties"]]
        declared = [k for k in schema["properties"] if k in keys]
        if keys != declared:
            problems.append(f"{prompt}: a reply's keys {keys}, the grammar's order is {declared}")
        for op in obj["ops"]:
            problems += check(op, prompt)
        return problems
    if "aliases" in obj:
        return order_problems(obj, category_table.ENTRY_SCHEMA, f"{prompt}: category {obj.get('name')!r}")
    return []


@pytest.mark.parametrize("prompt", PROMPTS)
def test_every_example_in_the_prompt_is_a_key_order_the_grammar_allows(prompt):
    text = generate.load_prompt(prompt, label="x", bounds="x", menu="x") if prompt == "intent.md" \
        else generate.load_prompt(prompt)
    examples = _objects(text)
    assert examples, f"no JSON example found in {prompt}"
    seen, problems = set(), []
    for obj in examples:
        key = json.dumps(obj, sort_keys=True)
        if key not in seen:
            seen.add(key)
            problems += check(obj, prompt)
    problems = list(dict.fromkeys(problems))
    assert not problems, "\n".join(problems)


def test_the_checker_catches_the_order_that_emptied_every_bus():
    bus = {"op": "add_bus", "name": "Wedge", "stereo": False, "mode": "pre", "members": {"categories": ["horns"]}}
    assert check(bus, "intent_step_buses.md")
    assert not check({**{k: bus[k] for k in ("op", "name", "stereo")}, "members": bus["members"], "mode": "pre"},
                     "intent_step_buses.md")


def test_step_1s_reply_declares_categories_before_ops():
    schema = intent_steps.step_schema(CONSOLE, intent_steps.STEPS[0])
    assert list(schema["properties"]) == ["name", "categories", "ops", "notes"]
    assert list(intent_schema.intent_schema(CONSOLE, build=True)["properties"])[:2] == ["name", "categories"]
