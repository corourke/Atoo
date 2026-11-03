"""What a build checks before any model call, and what a failed build does
with the plan it replaces (items 3 and 4).

A duplicate strip in the input list's channel column, or a sheet row the
desk cannot have, is wrong whatever the model replies: it is found before
the model is asked, so nothing is spent and `plan.json` is as it was. Once
the model has been asked, a rebuild has cleared the current plan (the
maintainer, 2026-10-02), so a failure then says where it went and how to
have it back.
"""

from __future__ import annotations

import json
from pathlib import Path

from atoo.ai_provider import FakeProvider
from atoo.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
HOUSE = FIXTURES / "smallband.md"

LIST = ("channel,patch,name,category,type,phantom\n"
        "1,LCL 1,Kick,drums,Mic,FALSE\n"
        "1,LCL 2,Lead Vox,vocals,Mic,FALSE\n"
        ",LCL 3,Keys L,keys,DI,FALSE\n"
        ",LCL 4,Keys R,keys,DI,FALSE\n")


class _NoCall(FakeProvider):
    def __init__(self):
        super().__init__(response="{}")

    def complete(self, *args, **kwargs):  # pragma: no cover - the test fails if reached
        raise AssertionError("the model was asked")

    generate = stream = complete


def _show(tmp_path, csv_text=LIST) -> Path:
    d = tmp_path / "show"
    d.mkdir()
    (d / "input.csv").write_text(csv_text)
    (d / "plan.json").write_text('{"channels": [], "marker": "old"}')
    return d


def _build(d, monkeypatch, provider):
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    return main(["build", "--console-model", "wing-compact", "--show", str(d),
                 "--conventions", str(HOUSE), "--no-resolve"])


def test_two_rows_on_one_strip_stop_the_build_before_the_model(tmp_path, monkeypatch, capsys):
    d = _show(tmp_path)
    assert _build(d, monkeypatch, _NoCall()) == 1
    err = capsys.readouterr().err
    assert ("build failed: input list: 'Kick' and 'Lead Vox' both name CH 1 in the channel "
            "column, and a strip holds one input (or the two rows of one stereo pair). Change "
            "one of the two cells. Nothing was sent to a model and nothing was changed: "
            "plan.json is as it was.") in err
    assert json.loads((d / "plan.json").read_text())["marker"] == "old"
    assert not (d / "plan.previous.json").exists()


def test_the_two_rows_of_one_pair_may_share_a_strip(tmp_path, monkeypatch, capsys):
    d = _show(tmp_path, LIST.replace("1,LCL 2,Lead Vox", ",LCL 2,Lead Vox")
              .replace(",LCL 3,Keys L", "5,LCL 3,Keys L").replace(",LCL 4,Keys R", "5,LCL 4,Keys R"))
    _build(d, monkeypatch, FakeProvider(response=None))
    assert "both name" not in capsys.readouterr().err


def test_an_output_socket_the_desk_does_not_have_stops_the_build_before_the_model(
        tmp_path, monkeypatch, capsys):
    d = _show(tmp_path, LIST.replace("1,LCL 2,Lead Vox", ",LCL 2,Lead Vox"))
    (d / "outputs.csv").write_text("output,source,notes\nLCL 99,Bus 9 L,\n")
    (d / "busses.csv").write_text("bus,name,width,outputs\nBus 20,Wedge,mono,\n"
                                  "Bus 3,Fold,stereo,LCL 40-41\n")
    assert _build(d, monkeypatch, _NoCall()) == 1
    err = capsys.readouterr().err
    assert "outputs.csv, LCL 99: this console has no LCL 99 (its LCL outputs are 1-8)" in err
    assert "busses.csv, Bus 20: the desk has Bus 1-16, so there is no Bus 20" in err
    assert ("busses.csv, Bus 3, outputs 'LCL 40-41': this console has no LCL 40 (its LCL "
            "outputs are 1-8)") in err
    assert json.loads((d / "plan.json").read_text())["marker"] == "old"


def test_a_build_that_fails_after_the_model_says_where_the_plan_went(tmp_path, monkeypatch, capsys):
    d = _show(tmp_path, LIST.replace("1,LCL 2,Lead Vox", ",LCL 2,Lead Vox"))
    assert _build(d, monkeypatch, FakeProvider(response=None)) == 1
    err = capsys.readouterr().err
    assert not (d / "plan.json").exists()
    assert json.loads((d / "plan.previous.json").read_text())["marker"] == "old"
    assert ("plan.json was moved aside to plan.previous.json when this build started, because a "
            "rebuild clears the current plan. To go back to it, rename plan.previous.json to "
            f"plan.json in {d}.") in err
