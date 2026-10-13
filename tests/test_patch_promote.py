"""`atoo patch --promote`: keep a change already
written in the show for good -- its text into instructions.md, the inputs
it added into input.csv, and never plan.json.

Changes are written first with a canned change set against the fake desk
(`test_patch`'s fixtures); bundles are built in `tmp_path`. Nothing reads a
bundle under `examples/`.
"""

from __future__ import annotations

import json

import pytest

from atoo import cli, input_list, journal_stack, patch, promote
from test_patch import HORNS_TEXT, _bundle, _patch, _reply, desk, model  # noqa: F401

INPUTS = (
    "socket,name,category,type,model,phantom,notes\n"
    "A 1,Kick,drums,Mic,Beta91A,TRUE,\n"
    "A 18,T.Sax SM57,horns,Mic,SM57,FALSE,\n"
    "A 9,F VOX 1,vocals,Mic,,FALSE,\n"
)
INSTRUCTIONS = "# Tonight's show\n\nKeep the horns dry.\n"


@pytest.fixture
def show(tmp_path):
    show = _bundle(tmp_path)
    (show / "input.csv").write_text(INPUTS)
    (show / "instructions.md").write_text(INSTRUCTIONS)
    return show


def _promote(show, ref, *extra):
    return cli.main(["patch", "--show", str(show), "--promote", ref, *extra])


def test_a_preview_shows_what_would_be_kept_and_writes_nothing(show, desk, model, capsys):
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    plan_before = (show / "plan.json").read_bytes()
    capsys.readouterr()
    assert _promote(show, "1") == 0
    out = capsys.readouterr().out
    assert "Promote change 1: Horns for tonight into the show" in out
    assert HORNS_TEXT in out and "Nothing was written -- this was a preview" in out
    assert (show / "input.csv").read_text() == INPUTS
    assert (show / "instructions.md").read_text() == INSTRUCTIONS
    assert (show / "plan.json").read_bytes() == plan_before


def test_confirm_appends_the_text_and_the_new_inputs(show, desk, model, capsys):
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    plan_before = (show / "plan.json").read_bytes()
    assert _promote(show, "Horns for tonight", "--confirm") == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "Written: instructions.md, input.csv" in out

    text = (show / "instructions.md").read_text()
    assert text.startswith(INSTRUCTIONS)
    assert "## Promoted changes" in text and "change 1: Horns for tonight" in text
    assert HORNS_TEXT in text
    [entry] = journal_stack.entries(show)
    assert f"<!-- atoo: promoted {entry.id} -->" in text

    csv_text = (show / "input.csv").read_text()
    assert csv_text.startswith(INPUTS)  # the header, and every old row, untouched
    rows = input_list.parse_input_list(csv_text)
    added = {r.name: r for r in rows[3:]}
    assert set(added) == {"Trumpet", "Trombone", "T.Sax"}
    # The socket the channel is on now -- where the cable is.
    assert added["Trumpet"].patch == "AES50-A 21"
    # Category: that of the input already on the list sharing its DCA.
    assert added["Trumpet"].category == "horns"
    assert "promoted from change 1: Horns for tonight" in added["Trumpet"].notes
    assert any("shares its DCA 'Horns'" in line for line in out.splitlines())
    assert (show / "plan.json").read_bytes() == plan_before


def test_promoting_twice_writes_nothing_the_second_time(show, desk, model, capsys):
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    assert _promote(show, "change 1", "--confirm") == 0
    once = ((show / "instructions.md").read_text(), (show / "input.csv").read_text())
    capsys.readouterr()
    assert _promote(show, "1", "--confirm") == 0
    assert "already in the show" in capsys.readouterr().out
    assert ((show / "instructions.md").read_text(), (show / "input.csv").read_text()) == once


def test_an_undone_change_is_refused(show, desk, model, capsys):
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9", "--confirm"]) == 0
    capsys.readouterr()
    assert _promote(show, "1", "--confirm") == 1
    err = capsys.readouterr().err
    assert "was undone" in err and "nothing of it to keep" in err
    assert (show / "instructions.md").read_text() == INSTRUCTIONS


def test_an_old_socket_header_and_crlf_line_ends_are_kept(show, desk, model, capsys):
    (show / "input.csv").write_bytes(INPUTS.replace("\n", "\r\n").encode())
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    assert _promote(show, "1", "--confirm") == 0, capsys.readouterr()
    raw = (show / "input.csv").read_bytes().decode()
    assert raw.startswith("socket,name,") and "\n" not in raw.replace("\r\n", "")
    assert raw.endswith("\r\n")


def test_a_new_patch_header_is_filled_under_patch(show, desk, model, capsys):
    (show / "input.csv").write_text(INPUTS.replace("socket,", "patch,", 1))
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    assert _promote(show, "1", "--confirm") == 0, capsys.readouterr()
    rows = input_list.parse_input_list((show / "input.csv").read_text())
    assert rows[-1].patch == "AES50-A 23"


def test_an_input_already_on_the_list_gets_no_second_row(show, desk, model, capsys):
    (show / "input.csv").write_text(INPUTS + "A 21,Trumpet,horns,Mic,,FALSE,\n")
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    assert _promote(show, "1", "--confirm") == 0
    out = capsys.readouterr().out
    assert "'Trumpet' is already on the input list" in out
    names = [r.name for r in input_list.parse_input_list((show / "input.csv").read_text())]
    assert names.count("Trumpet") == 1


def test_a_change_that_only_edits_is_promoted_as_text(show, desk, model, capsys):
    change_set = patch.empty_change_set("Vocal HPF")
    change_set["modify"] = [{"object": "channel", "name": "F VOX 1", "change": "HPF 100",
                             "fields": {"processing.hpf_hz": 100}}]
    model.response = _reply(change_set)
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    assert _promote(show, "vocal hpf", "--confirm") == 0, capsys.readouterr()
    assert "no rows to add" in capsys.readouterr().out
    assert (show / "input.csv").read_text() == INPUTS
    assert HORNS_TEXT in (show / "instructions.md").read_text()


def test_the_changes_are_listed_when_the_reference_matches_none(show, desk, model, capsys):
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    capsys.readouterr()
    assert _promote(show, "bagpipes") == 1
    err = capsys.readouterr().err
    assert "no change 'bagpipes'" in err and "change 1: Horns for tonight" in err


def test_usage(show, desk, model, capsys):
    assert cli.main(["patch", "--promote", "1"]) == 1
    assert "--promote needs --show" in capsys.readouterr().err
    assert cli.main(["patch", "--show", str(show), "horns", "--promote", "1"]) == 1
    assert "--promote keeps a change already written, so it takes no change text" in \
        capsys.readouterr().err


def test_a_stereo_channel_is_two_rows(show, desk, model, capsys):
    change_set = patch.empty_change_set("Playback")
    from test_amend import horn
    playback = horn(20, "Playback", 21)
    playback["source"] = {"input": "Playback", "type": "Line", "model": None,
                          "stereo": True, "phantom": False}
    playback["patch"] = {"group": "A", "sockets": [21, 22], "stated": True}
    change_set["add"]["channels"] = [playback]
    model.response = _reply(change_set)
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    assert _promote(show, "1", "--confirm") == 0, capsys.readouterr()
    rows = input_list.parse_input_list((show / "input.csv").read_text())
    assert [(r.name, r.patch, r.type) for r in rows[3:]] == [
        ("Playback L", "AES50-A 21", "Line"), ("Playback R", "AES50-A 22", "Line")]
