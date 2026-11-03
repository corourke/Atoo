"""What `atoo build` says on the terminal about what code did (items 5 and 6).

The build's INFO findings -- the input list's columns carried out, a split
or a feed built -- were kept in plan.json and the Build page's Findings but
never printed, so a sitting run from the terminal could not see them. And a
model's note saying it did not use a column stayed a WARNING after code had
carried the column out.
"""

from __future__ import annotations

import json
from pathlib import Path

from atoo.ai_provider import FakeProvider
from atoo.cli import main

HOUSE = Path(__file__).parent / "fixtures" / "smallband.md"

LIST = ("channel,patch,name,category,type,phantom,dca\n"
        ",LCL 1,Kick,drums,Mic,FALSE,DRUMS\n"
        "1,LCL 2,Lead Vox,vocals,Mic,FALSE,\n")

NOTE = ("Lead Vox: the input list's channel column '1' is not used; conventions order "
        "(drums, bass, guitars, keys, vocals, playback) applies.")


def _build(tmp_path, monkeypatch, capsys) -> tuple[dict, str]:
    show = tmp_path / "show"
    show.mkdir()
    (show / "input.csv").write_text(LIST)
    reply = {"channels": [{"input": "Kick"}, {"input": "Lead Vox"}], "busses": [], "dcas": [],
             "mute_groups": [], "outputs": [], "unassigned_inputs": [],
             "notes": [{"text": NOTE, "source": "model"}]}
    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: FakeProvider(response=json.dumps(reply)))
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")
    main(["build", "--console-model", "wing-compact", "--show", str(show),
          "--conventions", str(HOUSE), "--no-resolve"])
    err = " ".join(capsys.readouterr().err.split())     # the notes wrap
    return json.loads((show / "plan.json").read_text()), err


def test_the_build_prints_what_code_carried_out(tmp_path, monkeypatch, capsys):
    plan, err = _build(tmp_path, monkeypatch, capsys)
    assert next(c for c in plan["channels"] if c["name"] == "Lead Vox")["channel"] == 1
    assert "Build -- " in err
    assert ("the input list's channel column puts 'Lead Vox' on CH 1, where the build had placed "
            "it on CH 2; the list wins") in err
    assert "DCA 'Drums' is named 'DRUMS'" in err or "puts 'Kick' in DRUMS" in err


def test_a_model_note_that_code_has_overridden_is_dropped_and_said(tmp_path, monkeypatch, capsys):
    plan, err = _build(tmp_path, monkeypatch, capsys)
    assert NOTE not in [n.get("text") for n in plan.get("notes") or []]
    assert "WARNING [model] Lead Vox: the input list's channel column" not in err
    assert (f"the reply's note {NOTE!r} is dropped: the input list's channel column is carried "
            "out by code, as every filled cell is") in err
