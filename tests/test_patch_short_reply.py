"""A reply that is short of the change, or retracts itself, is not accepted. Fake replies only; built here, nothing read from examples/."""

from __future__ import annotations

import json

import pytest

from atoo import patch
from atoo.ai_provider import FakeProvider
from test_amend import applied_plan, horn

MODELS = ["wing-compact", "wing-full", "wing-rack"]


class Repairing(FakeProvider):
    """A fake that, like the api provider, takes one repair round; replies
    are played in order, the last one repeating."""
    repairs_replies = True

    def __init__(self, *replies: dict):
        super().__init__(response="")
        self.replies = [json.dumps(r) for r in replies]

    def complete(self, *, system, user, response_schema=None, label=""):
        self.calls.append((system, user))
        self.labels.append(label)
        return self.replies[min(len(self.calls), len(self.replies)) - 1]


def _set(*names, notes=(), stereo=False):
    cs = patch.empty_change_set("x")
    cs["add"]["channels"] = [horn(20 + i, n, 21 + i) for i, n in enumerate(names)]
    cs["notes"] = list(notes)
    return cs


def _compile(provider, text, model):
    infos: list[str] = []
    cs = patch.compile_change(text, applied_plan(), provider=provider, console_model=model, infos=infos)
    return cs, infos


CHOIR = 'Add two choir mics, "Choir L" and "Choir R"'
SHORT = _set("Choir L", notes=["Superseded by a fuller answer; needs a rerun."])
FULL = _set("Choir L", "Choir R")


@pytest.mark.parametrize("model", MODELS)
def test_the_failing_reply_is_sent_back_once_and_the_full_one_used(model):
    p = Repairing(SHORT, FULL)
    cs, infos = _compile(p, CHOIR, model)
    assert [c["name"] for c in cs["add"]["channels"]] == ["Choir L", "Choir R"]
    assert p.labels == ["", "change-repair"] or p.labels[-1] == "change-repair"
    assert "own note says it is not the answer" in p.calls[1][1]


@pytest.mark.parametrize("model", MODELS)
def test_a_second_short_reply_is_refused_and_says_what_is_missing(model):
    p = Repairing(_set("Choir L"), _set("Choir L"))
    with pytest.raises(patch.ChangeError) as exc:
        _compile(p, CHOIR, model)
    assert '"Choir R"' in str(exc.value) and "does not add it" in str(exc.value)
    assert len(p.calls) == 2


@pytest.mark.parametrize("model", MODELS)
def test_a_second_retracting_reply_is_refused_with_the_note_quoted(model):
    with pytest.raises(patch.ChangeError) as exc:
        _compile(Repairing(SHORT, SHORT), CHOIR, model)
    assert "Superseded by a fuller answer" in str(exc.value)


@pytest.mark.parametrize("model", MODELS)
def test_the_stereo_merged_choir_is_accepted(model):
    p = Repairing(_set("Choir"))
    cs, _ = _compile(p, CHOIR, model)
    assert len(p.calls) == 1 and cs["add"]["channels"][0]["name"] == "Choir"


@pytest.mark.parametrize("model", MODELS)
def test_a_benign_note_and_a_full_reply_are_accepted(model):
    p = Repairing(_set("Choir L", "Choir R", notes=["supersedes the factory name"]))
    _compile(p, CHOIR, model)
    assert len(p.calls) == 1


@pytest.mark.parametrize("model", MODELS)
def test_a_count_in_words_is_checked_and_a_request_without_one_is_not(model):
    with pytest.raises(patch.ChangeError, match="asks for 3 channels; the reply adds 1"):
        _compile(Repairing(_set("A"), _set("A")), "add 3 channels", model)
    p = Repairing(_set("A"))
    _compile(p, "put a lead vocal mic on A 21", model)
    _compile(p, "add the choir mics", model)
    assert len(p.calls) == 2


def test_a_provider_that_cannot_repair_refuses_at_once():
    p = FakeProvider(response=json.dumps(SHORT))
    with pytest.raises(patch.ChangeError):
        _compile(p, CHOIR, "wing-compact")
    assert len(p.calls) == 1


@pytest.mark.parametrize("note", [
    "Superseded; needs a rerun", "This reply is incomplete", "Please rerun this change",
    "Ignore this reply", "I could not find a free socket", "I cannot place Choir R",
    "This change will not apply", "The previous answer was superseded",
    "not the final answer", "This response is retracted"])
def test_every_retraction_phrase_is_caught(note):
    assert patch.retraction_note({"notes": [note]}) == note


@pytest.mark.parametrize("note", [
    "supersedes the factory name", "Kick is renamed; the old name is superseded on the desk",
    "Choir L and R are a stereo pair", "No socket was named, so A 21 was chosen",
    "The rerun button is not involved"])
def test_benign_notes_are_not_retractions(note):
    assert patch.retraction_note({"notes": [note]}) is None


# The reply Forge replayed from the live eval: one channel,
# a title that echoes both names, and a note that retracts it.
LIVE_NOTE = ("Superseded: the entry above is incorrect, see the corrected set below is not "
             "possible in this format; please treat this change as needing a rerun.")
LIVE_TEXT = 'Add two choir mics, "Choir L" and "Choir R"'


def _live(note=True):
    cs = _set("Choir L", notes=[LIVE_NOTE] if note else [])
    cs["name"] = "Add Choir L and Choir R"
    return cs


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("note", [True, False])
def test_the_live_reply_is_sent_back_once_then_refused(model, note):
    p = Repairing(_live(note), _live(note))
    with pytest.raises(patch.ChangeError):
        _compile(p, LIVE_TEXT, model)
    assert len(p.calls) == 2


@pytest.mark.parametrize("model", MODELS)
def test_the_live_reply_repaired_by_a_full_one_is_used(model):
    cs, _ = _compile(Repairing(_live(), FULL), LIVE_TEXT, model)
    assert len(cs["add"]["channels"]) == 2


@pytest.mark.parametrize("note", [
    "Needing a rerun", "treat this change as needing a rerun", "Superseded: see below",
    "the entry above is incorrect", "see the corrected set below"])
def test_wider_retraction_phrases(note):
    assert patch.retraction_note({"notes": [note]}) == note


def test_a_name_echoed_in_prose_is_not_written():
    cs = _set("Choir L")
    cs["notes"] = ['"Choir R" is not here']
    cs["inferred"] = [{"basis": "Choir R"}]
    assert "Choir R" in patch.reply_shortfall(LIVE_TEXT, applied_plan(), cs)
