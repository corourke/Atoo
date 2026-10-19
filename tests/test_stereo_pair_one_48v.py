"""A stereo channel takes one 48V value for its pair, end to end.

The desk switches a stereo channel's two sockets together (writing A 11
read A 12 back already on), so a channel built from a condenser row and a
dynamic row cannot be put on it as two values. `atoo build` states one --
on if either row wants it -- and says so at INFO naming the row that asked;
`verify` and `apply` agree; a passive ribbon on either side is refused,
by build, by verify and by apply's pre-flight. Everything here is built in
`tmp_path`: the show, the reply and the simulated desk (nothing reads
`examples/`).
"""

from __future__ import annotations

import json

import pytest

from atoo import bundle, cli, console as console_module, inferred
from atoo import initialize as init
from atoo.ai_provider import FakeProvider
from tests.snap_desk import PairedSnapDesk

MODEL = "wing-compact"
HOST = "198.51.100.9"

REPLY = {
    "channels": [{"input": "OH L", "pair": "OH R", "name": "OH"},
                 {"input": "Kick", "name": "Kick"}],
    "dcas": [], "mute_groups": [], "busses": [],
    "outputs": [{"name": "Main", "kind": "main", "patch": {"group": "LCL", "sockets": [7, 8]}}],
    "unassigned_inputs": [], "notes": [],
}


def _csv(oh_l: tuple[str, str], oh_r: tuple[str, str]) -> str:
    """The input list: each overhead row is (model, phantom)."""
    return ("patch,name,category,type,model,phantom,notes\n"
            f"AES50-A 5,OH L,drums,Mic,{oh_l[0]},{oh_l[1]},\n"
            f"AES50-A 6,OH R,drums,Mic,{oh_r[0]},{oh_r[1]},\n"
            "AES50-A 1,Kick,drums,Mic,Beta 52,FALSE,\n")


@pytest.fixture
def make_show(tmp_path, monkeypatch):
    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: FakeProvider(response=json.dumps(REPLY)))
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")

    def build(oh_l, oh_r, *extra):
        show = tmp_path / "show"
        show.mkdir(exist_ok=True)
        (show / bundle.INPUT_LIST).write_text(_csv(oh_l, oh_r))
        (tmp_path / "house.md").write_text("# House conventions\n\nOverheads are a stereo pair.\n")
        code = cli.main(["build", "--show", str(show), "--conventions", str(tmp_path / "house.md"),
                         "--console-model", MODEL, *extra])
        return show, code

    return build


def _flat(text: str) -> str:
    """The report wraps long lines; a sentence is what is asserted on."""
    return " ".join(text.split())


def _oh(show) -> dict:
    plan = json.loads((show / bundle.PLAN).read_text())
    [oh] = [c for c in plan["channels"] if c["name"] == "OH"]
    return oh


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


@pytest.mark.parametrize("l_row,r_row,asked,other", [
    (("KSM137", "TRUE"), ("SM57", "FALSE"), "OH L", "OH R"),
    (("KSM137", "FALSE"), ("SM57", "TRUE"), "OH R", "OH L"),
])
def test_build_states_one_value_for_the_pair_and_names_the_row_that_asked(
        make_show, capsys, l_row, r_row, asked, other):
    show, code = make_show(l_row, r_row)
    err = _flat(capsys.readouterr().err)
    assert code == 0, err
    source = _oh(show)["source"]
    assert source["phantom"] is True and source["pair_phantom"] is True
    assert f"{asked!r} asks for it and {other!r} does not" in err
    assert f"split the pair into two mono channels if you want {other!r} without 48V" in err
    assert "phantom.pair-differs" not in err


def test_build_says_nothing_when_the_rows_agree(make_show, capsys):
    show, code = make_show(("KSM137", "TRUE"), ("KSM137", "TRUE"))
    err = capsys.readouterr().err
    assert code == 0, err
    assert "asks for it and" not in err
    assert _oh(show)["source"]["pair_phantom"] is True


def test_build_refuses_a_ribbon_on_either_side_of_a_powered_pair(make_show, capsys):
    """The dynamic's partner wants 48V and a ribbon is on the other socket:
    the pair would be powered, so build refuses, naming the ribbon's row."""
    show, code = make_show(("KSM137", "TRUE"), ("Royer R-121", "FALSE"))
    err = capsys.readouterr().err
    err = _flat(err)
    assert code != 0
    assert "safety.phantom-on-passive-ribbon" in err and "(OH R, the pair's second socket)" in err
    assert "Split the pair into two mono channels" in err


def test_build_leaves_a_ribbon_pair_nobody_powers_alone(make_show, capsys):
    show, code = make_show(("KSM137", "FALSE"), ("Royer R-121", "FALSE"))
    err = capsys.readouterr().err
    assert code == 0, err
    assert "safety.phantom-on-passive-ribbon" not in err


# --------------------------------------------------------------------------
# verify and apply, on the simulated desk
# --------------------------------------------------------------------------


@pytest.fixture
def desk(monkeypatch):
    sim = PairedSnapDesk({leaf.address: leaf.value for leaf in init.load_capture(MODEL).leaves})
    monkeypatch.setattr(console_module, "WingConsole", lambda *a, **k: sim)
    return sim


def _apply(show, *extra):
    return cli.main(["apply", "--plan", str(show / bundle.PLAN), "--input",
                     str(show / bundle.INPUT_LIST), "--console", HOST, "--no-progress", *extra])


def test_apply_puts_48v_on_both_sockets_and_the_audit_agrees(make_show, desk, capsys):
    show, code = make_show(("KSM137", "TRUE"), ("SM57", "FALSE"))
    assert code == 0
    assert _apply(show, "--confirm") == 0
    assert desk.values["/io/in/A/5/vph"] == 1 and desk.values["/io/in/A/6/vph"] == 1
    capsys.readouterr()
    cli.main(["audit", "--plan", str(show / bundle.PLAN), "--console", HOST, "--no-progress"])
    assert "CV019" not in capsys.readouterr().out


def test_an_older_plan_with_two_values_is_reported_by_verify_and_written_alike(
        make_show, desk, capsys):
    show, code = make_show(("KSM137", "TRUE"), ("SM57", "FALSE"))
    assert code == 0
    plan = json.loads((show / bundle.PLAN).read_text())
    [oh] = [c for c in plan["channels"] if c["name"] == "OH"]
    oh["source"]["pair_phantom"] = False          # what an older build wrote
    (show / bundle.PLAN).write_text(json.dumps(plan))
    capsys.readouterr()
    cli.main(["verify", "--plan", str(show / bundle.PLAN), "--input",
              str(show / bundle.INPUT_LIST)])
    out = capsys.readouterr()
    text = _flat(out.out + out.err)
    assert "phantom.pair-differs" in text
    assert "Rebuild" in text and "split the pair into two mono channels" in text
    assert _apply(show, "--confirm") == 0
    assert desk.values["/io/in/A/5/vph"] == desk.values["/io/in/A/6/vph"] == 1
    assert json.loads((show / bundle.PLAN).read_text())["channels"] == plan["channels"]


def test_apply_refuses_a_ribbon_on_either_side_before_touching_the_desk(
        make_show, desk, capsys):
    show, _code = make_show(("KSM137", "FALSE"), ("Royer R-121", "FALSE"))
    plan = json.loads((show / bundle.PLAN).read_text())
    [oh] = [c for c in plan["channels"] if c["name"] == "OH"]
    oh["source"].update(phantom=True, pair_phantom=True)    # the partner row asked for 48V
    (show / bundle.PLAN).write_text(json.dumps(plan))
    before = dict(desk.values)
    capsys.readouterr()
    assert _apply(show, "--confirm") == 2
    err = _flat(capsys.readouterr().err)
    assert "safety.phantom-on-passive-ribbon" in err and "OH R" in err
    assert "Refusing to apply" in err
    assert desk.values == before


def test_the_pairs_one_value_is_what_the_plan_reads_as():
    channel = {"source": {"stereo": True, "phantom": False, "pair_phantom": True},
               "patch": {"group": "A", "sockets": [5, 6]}}
    assert inferred.socket_phantom(channel) == [(5, True), (6, True)]
