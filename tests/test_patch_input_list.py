"""The Patch pre-flight reads the show's input list.

The pre-flight verify of a typed change ran without the show's input list,
so every review of a show that has one carried `reconcile.not-checked`
("no input list was supplied"). It now reads the bundle's `input.csv` and
runs the checks that need it. A change is not a rebuild, so the list is held
to it as `verify_plan.rows_for_a_change` cuts it: a channel the change adds
is checked against the change, not called invented; a row the plan has no
channel for is not called dropped; and a socket the change states stands over
the one the list states. That choice is said at INFO. A show with no list
still gets the warning.

The plan is the frozen applied show and the list is written from it in the
test; nothing reads a bundle under `examples/`.
"""

from __future__ import annotations

import json

import pytest

from atoo import cli, patch
from atoo.ai_provider import FakeProvider
from atoo.input_list import parse_input_list
from atoo.verify_plan import rows_for_a_change
from test_amend import DeskConsole, applied_plan, horn
from test_amend_plan_json import _seed
from test_patch import horns_change_set


def _list_text(*, extra: tuple[str, ...] = (), patches: dict | None = None) -> str:
    """An input list for the applied show: one row per channel's input."""
    lines = ["socket,name,category,type,model,phantom,notes"]
    for ch in applied_plan()["channels"]:
        source = ch["source"]
        socket = ""
        if patches and source["input"] in patches:
            socket = patches[source["input"]]
        lines.append(f"{socket},{source['input']},drums,{source['type']},{source['model']},"
                     f"{'TRUE' if source['phantom'] else 'FALSE'},")
    lines.extend(extra)
    return "\n".join(lines) + "\n"


def _show(tmp_path, *, input_list: str | None):
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps(applied_plan(), indent=4) + "\n")
    if input_list is not None:
        (show / "input.csv").write_text(input_list)
    return show


@pytest.fixture
def desk(monkeypatch):
    console = DeskConsole(_seed(applied_plan()))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    return console


def _model(monkeypatch, change_set: dict) -> None:
    fake = FakeProvider(response=json.dumps(change_set))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)


def _review(show, tmp_path, capsys, text="horns for tonight") -> tuple[int, dict, str]:
    out = tmp_path / "review.json"
    code = cli.main(["patch", "--show", str(show), text, "--console", "198.51.100.9",
                     "--no-progress", "--review-json", str(out)])
    captured = capsys.readouterr()
    return code, json.loads(out.read_text()), captured.out + captured.err


def _codes(review: dict) -> list[str]:
    verify = review["preflight"]["verify"]
    return [w.rsplit("(", 1)[-1].rstrip(")") for w in verify["warnings"] + verify["errors"]]


def test_a_show_with_an_input_list_has_no_not_checked_warning_and_says_what_was_checked(
        tmp_path, desk, monkeypatch, capsys):
    _model(monkeypatch, horns_change_set())
    code, review, said = _review(_show(tmp_path, input_list=_list_text()), tmp_path, capsys)
    assert code == 0, said
    assert "reconcile.not-checked" not in _codes(review)
    assert review["preflight"]["verify"]["errors"] == []
    [info] = review["preflight"]["infos"]
    assert info.startswith("input.csv: 19 of its 19 row(s) are used by the changed plan")
    assert "3 channel(s) of the changed plan are not on it (Trumpet, Trombone, T.Sax)" in info
    assert "taken as they stand, not called invented" in info and info in review["infos"]
    assert f"INFO {info}" in said


def test_a_show_with_no_input_list_still_gets_the_warning(tmp_path, desk, monkeypatch, capsys):
    _model(monkeypatch, horns_change_set())
    code, review, said = _review(_show(tmp_path, input_list=None), tmp_path, capsys)
    assert code == 0, said
    assert "reconcile.not-checked" in _codes(review)
    assert review["preflight"]["infos"] == []


def test_a_channel_the_change_adds_is_not_invented_and_an_unused_row_is_not_dropped(
        tmp_path, desk, monkeypatch, capsys):
    """The horns are not on the list; a Congas row is, and the plan has no
    channel for it. A full build would call the first invented and the
    second dropped, both ERRORs; a change is neither."""
    _model(monkeypatch, horns_change_set())
    show = _show(tmp_path, input_list=_list_text(extra=("AES50-A 40,Congas,percussion,Mic,,FALSE,",)))
    code, review, said = _review(show, tmp_path, capsys)
    assert code == 0, said
    codes = _codes(review)
    assert "reconcile.invented-source" not in codes and "reconcile.dropped-input" not in codes
    assert review["preflight"]["verify"]["errors"] == []
    assert review["blocked"] is False


def test_what_the_list_says_about_a_channel_the_plan_uses_is_still_checked(
        tmp_path, desk, monkeypatch, capsys):
    """Kick is cabled into AES50-A 9 on the list and A 1 in the plan: a change
    that does not touch Kick does not make that right."""
    _model(monkeypatch, horns_change_set())
    show = _show(tmp_path, input_list=_list_text(patches={"Kick": "AES50-A 9"}))
    code, review, said = _review(show, tmp_path, capsys)
    assert "patch.contradicts-input-list" in _codes(review)
    assert review["blocked"] is True and review["preflight"]["refusal_code"] == "amend.verify-failed"


def test_the_socket_a_change_states_stands_over_the_one_the_list_states(
        tmp_path, desk, monkeypatch, capsys):
    """The list has Congas in AES50-A 40; the change adds them on A 33.
    The engineer's change is what corrects the list, so it is not refused
    for disagreeing with it, and the INFO names the channel."""
    change_set = patch.empty_change_set("Congas")
    change_set["add"]["channels"] = [horn(20, "Congas", 33)]
    _model(monkeypatch, change_set)
    show = _show(tmp_path, input_list=_list_text(
        extra=("AES50-A 40,Congas,percussion,Mic,,FALSE,",)))
    code, review, said = _review(show, tmp_path, capsys, text="congas on A 33")
    assert code == 0, said
    assert "patch.contradicts-input-list" not in _codes(review), said
    [info] = review["preflight"]["infos"]
    assert "For Congas the change states a socket other than the one input.csv does" in info


def test_an_unreadable_input_list_is_said_and_the_warning_stays(
        tmp_path, desk, monkeypatch, capsys):
    _model(monkeypatch, horns_change_set())
    code, review, said = _review(_show(tmp_path, input_list="not,a,list\n1,2,3\n"),
                                 tmp_path, capsys)
    assert code == 0, said
    assert "reconcile.not-checked" in _codes(review)
    assert any(i.startswith("input.csv: couldn't be read") for i in review["infos"])


# ----------------------------------------------------------------------
# The cut itself
# ----------------------------------------------------------------------


def test_the_cut_keeps_the_rows_the_plan_names_and_stands_in_for_the_rest():
    rows = parse_input_list(_list_text(extra=("AES50-A 40,Congas,percussion,Mic,,FALSE,",)))
    plan = applied_plan()
    plan["channels"].append(horn(20, "Trumpet", 21))
    cut, stand_ins, set_aside = rows_for_a_change(plan, rows)
    names = {row.name for row in cut}
    assert "Congas" not in names and "Trumpet" in names and "Kick" in names
    assert stand_ins == ["Trumpet"] and set_aside == []
