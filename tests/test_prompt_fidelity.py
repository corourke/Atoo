"""Prompt fidelity: is the prompt unambiguous enough that a model reading
it carries a stated fact into the plan?

**Read this before believing a green run.** The subject under test here is
the PROMPT and the schema prose -- `atoo/prompts/plan_generation.md`
and the field descriptions `plan_schema.schema_section()` renders into it.
The model is the instrument, not the thing being measured. These tests go
through `generate.generate_plan`, which is the same prompt-to-plan path
`atoo build` calls, but they are NOT an end-to-end `atoo build`
test: no CLI, no bundle assembly, no critic pass, no verify-at-generation
gate. A pass says the wording reads unambiguously to the model that ran. It
does not say the build command is correct.

Why they exist at all -- an earlier change. Both shipped example plans came out of
`build` with `mono: null` on four busses whose conventions said, in the same
bullet the plan's own `provenance` quotes from, *"these will all be MONO
busses"*. Because `bus.unstated-width-for-dedicated-output` was then an
error, both bundles were unapplicable, and the engineer was told their
conventions never stated something they could see written down. (That
error was retired on 2026-09-25: an unstated width is now DECIDED and
announced as an INFO -- `atoo/inferred.py` -- so the same defect
today reads as a note claiming the conventions were silent.)

Nothing already in this directory could have caught that:

- The verifier's mutation suite (`tests/test_verify_plan.py`) asks whether a
  check fires when a field is null. It does. That is not the question.
- `FakeProvider` returns a canned plan, so a test built on it asserts what
  the fixture author typed, never what a model does with the prompt.
- `tests/test_prompts.py` asserts the prompt *says* a thing. Necessary,
  cheap, and not the same as a model *doing* it. Those assertions are the
  free half of this pair and run on every suite.

Asking the real question needs a real model, which costs money and minutes,
so these are marked `live_model` and need TWO switches before they run --
see pyproject.toml's marker comment:

    ATOO_LIVE_MODEL_TESTS=1 ATOO_AI_PROVIDER=claude \\
        ATOO_AI_API_KEY=... python3 -m pytest -m live_model

`ATOO_LIVE_MODEL_TESTS` is the opt-in; the provider variables are
whatever `atoo build` itself would use. Without the opt-in an ordinary
`python3 -m pytest -q` skips them and costs nothing, even on a machine with
`ATOO_AI_PROVIDER` exported for everyday use.

**These have never run in CI, or in the container they were written in**,
which has no provider configured at all. The evidence behind the wording
change was gathered a different way: the composed prompt was piped to the
`claude` CLI by hand and the reply read. That route bypasses `generate_plan`
-- extraction, schema validation, index allocation, all of it -- so it
proved only that the prompt reads unambiguously, which is a smaller claim
than these tests make. They are here so the larger claim can be checked the
first time someone points a configured provider at them.

**The fixture is shaped like the file that broke.** `bus_width.md` states
each width the way `examples/conventions.md` does -- mid-sentence after the
names, and in a heading governing the list under it -- because a fixture
that states the width in a short sentence of its own is a test the failing
case would have passed.

**Run these against the weakest model available, not the best one.** The
question is whether the prompt is unambiguous, and a strong model papers
over ambiguity by inferring what was meant: `claude-haiku-4-5` and
`claude-sonnet-4-5` both got every width right against the *unfixed*
wording, so neither would have caught an earlier change on its own. A prompt the weakest
model reads correctly is a prompt that says what it means; a prompt only the
strongest model reads correctly is a prompt that got lucky. A local
Ollama model (`ATOO_AI_PROVIDER=ollama`) is the weak end in practice,
so that is the honest bar.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from atoo import ai_provider, generate
from atoo.verify_plan import verify_plan

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CONVENTIONS = FIXTURES / "bus_width.md"
INPUT_LIST = FIXTURES / "bus_width.csv"

# The busses the fixture names. Stated MONO in the middle of the sentence
# that names them; everything else it creates sits under a "These are
# stereo busses" heading.
MONO_BUSSES = ("MON1", "MON2")


def _live_provider():
    """The provider `atoo build` would use, or a skip."""
    if not os.environ.get("ATOO_LIVE_MODEL_TESTS"):
        pytest.skip(
            "live-model test: costs a real model call. Set "
            "ATOO_LIVE_MODEL_TESTS=1 (and a provider) to run it -- see "
            "pyproject.toml's `live_model` marker comment."
        )
    try:
        return ai_provider.provider_from_env(os.environ)
    except ai_provider.AIProviderError as exc:
        pytest.skip(f"live-model test: no usable provider configured ({exc})")


def _generate(conventions: pathlib.Path, input_list: pathlib.Path) -> dict:
    try:
        return generate.generate_plan(
            conventions.read_text(),
            input_list.read_text(),
            provider=_live_provider(),
            conventions_name=conventions.name,
            input_name=input_list.name,
            console_model="wing-compact",
        )
    except ai_provider.AIProviderError as exc:
        # Could not ASK the model -- no Ollama on the default port, a bad
        # key, a network that is not there. That is a different thing from
        # the model answering badly, and only the second one is a finding
        # about this project. `provider_from_env` builds an Ollama provider
        # happily whether or not a server is listening, so this is the first
        # place the difference is knowable.
        pytest.skip(f"live-model test: the provider could not be reached ({exc})")


def _width_marker(bus: dict) -> dict | None:
    for entry in (bus or {}).get("inferred") or []:
        if isinstance(entry, dict) and entry.get("field") == "mono":
            return entry
    return None


@pytest.fixture(scope="module")
def stated_width_plan():
    """One generation for every test that reads it. A second model call to
    assert a second property of the same plan doubles the bill for nothing."""
    return _generate(CONVENTIONS, INPUT_LIST)


def test_the_fixture_states_a_width_for_every_bus_it_asks_for():
    """Free, and it stops the live tests going vacuous: if someone edits the
    width sentences out of the fixture, they would start asserting a property
    the conventions no longer claim, and would pass for the wrong reason."""
    text = CONVENTIONS.read_text()
    assert "MONO busses" in text, "the fixture no longer states a mono width"
    assert text.count("These are stereo busses") >= 2, (
        "the fixture no longer states a stereo width over its mix and FX "
        "bus sections"
    )
    for name in MONO_BUSSES:
        assert name in text


@pytest.mark.live_model
def test_a_stated_bus_width_reaches_the_plan(stated_width_plan):
    """An earlier change, both halves.

    The mono half is what broke visibly: the four MON busses of
    `examples/conventions.md` route to dedicated outputs, so a null width is
    an error and the bundle will not apply.

    The stereo half is the same defect with the alarm disconnected. "These
    are stereo busses" came through null too, on both shipped plans, and drew
    no finding at all only because those busses route to `main` rather than
    to a physical socket. `false` is a stated width exactly as much as `true`
    is, so this asserts it.
    """
    busses = stated_width_plan.get("busses") or {}
    assert busses, "the model produced no busses at all"

    # Since 2026-09-25 `generate_plan` fills a null width itself (the
    # fallback, `atoo/inferred.py`) and marks it -- so "left null" now
    # shows up as a `mono` entry in the bus's `inferred` list, whether the
    # model decided it or the fallback did. A STATED width carries neither.
    unstated = sorted(n for n, b in busses.items() if _width_marker(b) is not None)
    assert not unstated, (
        "the conventions state a width for every bus they ask for, but the "
        f"plan treated these as unstated (decided, not read): {unstated}"
    )

    for name in MONO_BUSSES:
        assert name in busses, f"the conventions ask for {name} and the plan has no such bus"
        assert busses[name].get("mono") is True, (
            f"{name}: the conventions say 'these will all be MONO busses', "
            f"the plan says mono={busses[name].get('mono')!r}"
        )

    stereo = {n: b for n, b in busses.items() if n not in MONO_BUSSES}
    assert stereo, "the fixture asks for mix and FX busses too"
    for name, bus in stereo.items():
        assert bus.get("mono") is False, (
            f"{name} sits under a 'These are stereo busses' heading; the plan "
            f"says mono={bus.get('mono')!r} (false is a stated width, null is "
            "a claim the conventions were silent)"
        )


@pytest.mark.live_model
def test_no_stated_width_is_announced_as_a_decision(stated_width_plan):
    """The consequence the engineer actually meets. Until 2026-09-25 a
    width lost on the way into the plan made `apply`'s pre-flight gate
    return 2 (`bus.unstated-width-for-dedicated-output`). Now it is decided
    and noted instead -- so the failure looks like a note telling him his
    conventions were silent about a width he can see written down."""
    notes = [f for f in verify_plan(stated_width_plan, console_model="wing-compact").findings
             if f.code == "inferred.bus-width"]
    assert not notes, [str(f) for f in notes]


@pytest.mark.live_model
def test_an_unstated_bus_width_is_decided_and_marked_by_the_model():
    """The other direction. `tests/fixtures/smallband.md` states no width
    anywhere. Before 2026-09-25 the right answer was null; under the
    judgement-vs-patching rule ("it is not OK to leave the mono/stereo
    decision undecided because it affects how we patch ... This is why we
    have INFO messages") it is a decided width, with an `inferred` entry
    saying what it was decided from.

    `by: "model"` specifically: a `fallback` marker means the model left it
    null against rule 4b and Atoo's own rule filled it -- a working
    plan, but a prompt the model did not follow.
    """
    plan = _generate(FIXTURES / "smallband.md", FIXTURES / "smallband.csv")
    busses = plan.get("busses") or {}
    assert busses
    undecided = {n: b.get("mono") for n, b in busses.items()
                 if not isinstance((b or {}).get("mono"), bool)}
    assert not undecided, undecided
    unmarked = sorted(n for n, b in busses.items() if _width_marker(b) is None)
    assert not unmarked, (
        f"smallband.md states no width, so every width is decided -- these carry no "
        f"'inferred' entry saying so: {unmarked}")
    by_fallback = sorted(n for n, b in busses.items() if _width_marker(b).get("by") != "model")
    assert not by_fallback, f"the model left these null and the fallback decided: {by_fallback}"
