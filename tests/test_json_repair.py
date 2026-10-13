"""Closing a JSON document a model left open -- and refusing to when that
would be a guess.

Written from a real 85-minute run whose only flaw was one missing `}`.
Naively closing at EOF made it parse, and produced a document with
`outputs`, `unassigned_inputs` and `notes` swallowed into `busses`. Valid
JSON, completely wrong plan. That case is the reason for `expect_keys`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo.generate import PLAN_TOP_LEVEL
from atoo.json_repair import loads_with_repair

EVIDENCE = Path(__file__).parents[1] / "experiments" / "generator" / "evidence"


def test_valid_json_is_returned_untouched():
    value, repairs = loads_with_repair('{"a": 1}')
    assert (value, repairs) == ({"a": 1}, [])


@pytest.mark.parametrize("text,expected", [
    ('{"channels": [', {"channels": []}),
    ('{"channels": [{"name": "Kick"}', {"channels": [{"name": "Kick"}]}),
    ('{"a": {"b": {"c": 1}', {"a": {"b": {"c": 1}}}),
    ('{"a": 1,', {"a": 1}),
])
def test_a_document_cut_off_at_the_end_is_closed(text, expected):
    value, repairs = loads_with_repair(text)
    assert value == expected
    assert len(repairs) == 1
    assert "missing" in repairs[0]


def test_the_repair_is_always_reported():
    _, repairs = loads_with_repair('{"a": [1, 2')
    assert repairs and "]}" in repairs[0]


def test_braces_inside_strings_are_not_structure():
    value, _ = loads_with_repair('{"name": "a } { \\" b"')
    assert value == {"name": 'a } { " b'}


def test_a_reply_cut_off_mid_string_is_refused():
    """Closing the string would invent the rest of a value."""
    with pytest.raises(json.JSONDecodeError):
        loads_with_repair('{"name": "Kic')


@pytest.mark.parametrize("text", ['{"a": 1}}', '{"a": ]', 'not json at all'])
def test_nothing_else_is_guessed_at(text):
    with pytest.raises(json.JSONDecodeError):
        loads_with_repair(text)


def test_a_repair_that_would_re_nest_expected_keys_is_refused():
    """The case this was built for, in miniature: the missing brace belongs
    after `busses`, so closing at EOF puts `outputs` inside it."""
    text = ('{"channels": [], "busses": {"FX": {"destination": {"type": "main"}}, '
            '"outputs": {"Main": {}}, "notes": []')
    with pytest.raises(json.JSONDecodeError) as exc:
        loads_with_repair(text, expect_keys=PLAN_TOP_LEVEL)
    assert "no longer be top-level" in str(exc.value)
    assert "outputs" in str(exc.value)

    # ...and without that knowledge it silently produces the wrong document,
    # which is exactly why callers must pass expect_keys.
    value, _ = loads_with_repair(text)
    assert "outputs" in value["busses"]
    assert "outputs" not in value


def test_the_real_14b_reply_is_refused_rather_than_mangled():
    raw = EVIDENCE / "qwen2.5-14b.touringband.raw.txt"
    if not raw.exists():
        pytest.skip("evidence not present")
    text = raw.read_text()
    body = text[text.index("{"):text.rindex("}") + 1]
    with pytest.raises(json.JSONDecodeError, match="no longer be top-level"):
        loads_with_repair(body, expect_keys=PLAN_TOP_LEVEL)
