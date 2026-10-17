"""One plan, more than one WING model (the check, regraded 2026-09-24).

*"you might generate a plan, and want to apply it to
more than one console, ex: primary console wing compact, backup console
wing rack (both have similar I/O.)"* Until then `apply` refused ANY
difference between the plan's model and the desk's, although every socket
a Compact plan can name exists on a Rack -- and the Apply screen had no
way past it at all.

The rule "an error of judgement is not an error of patching" decides the
new behaviour, and each branch is a test here:

* different model, every socket the plan patches exists on the desk --
  proceed, INFO naming both models, pre-flight verify re-run against the
  DESK's model (and still refusing on a real error);
* a socket the plan patches does not exist on the desk's model -- refuse,
  naming each one and both models, `--skip-verify` or not;
* the desk's model cannot be resolved (a token nobody has measured) --
  proceed with a WARNING naming the token, and journal the token. This
  used to happen silently;
* same model -- nothing new said.

**No test here touches a real console** (`FakeConsole` stands in for
`WingConsole`) and **none reads a bundle under `examples/`**: the plan is
frozen in `tests/fixtures/` and edited in the test, so what each test
depends on is visible in the test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import atoo.console as console_module
from atoo import apply as apply_module
from atoo import cli
from atoo.apply import (CROSS_MODEL, DESK_MODEL_UNMEASURED, SAME_MODEL, SOCKETS_MISSING,
                             check_desk_model, sockets_missing_on_model)
from atoo.cli import main
from atoo.console import OscReply
from test_apply import FakeConsole

FIXTURES = Path(__file__).parent / "fixtures"

# A Compact plan patching AES50 A 1..20 in and LCL 7..8 out: every socket
# it uses exists on all three models. Verifies with no errors against each.
COMPACT_PLAN = json.loads((FIXTURES / "applied-show.plan.json").read_text())
assert COMPACT_PLAN["meta"]["console_model"] == "wing-compact"

RACK_ID = "WING,198.51.100.6,BACKUP,wing-rack,SER-R,3.1-0"
FULL_ID = "WING,198.51.100.7,FOH,wing-fullsize,SER-F,3.1-0"
COMPACT_ID = "WING,198.51.100.5,PRIMARY,wing-compact,SER-C,3.1-0"
UNMEASURED_ID = "WING,198.51.100.6,BACKUP,wing-racksize,SER-R,3.1-0"


def _plan(**edits) -> dict:
    plan = copy.deepcopy(COMPACT_PLAN)
    for key, value in edits.items():
        plan[key] = value
    return plan


def _with_input(plan: dict, group: str, socket: int, index: int = 0) -> dict:
    plan["channels"][index]["patch"] = {"group": group, "sockets": [socket], "stated": True}
    return plan


class _Desk(FakeConsole):
    """`FakeConsole` answering `/?` as `identity_args`, shaped like
    `WingConsole` so `cli.apply_cmd` can construct it itself. Every
    address reads back as something, so a dry run has a baseline and a
    confirmed run writes."""

    identity_args: list = [COMPACT_ID]
    made: list = []

    def __init__(self, address, port=2223, timeout=1.0, raw_log=None):
        super().__init__({})
        self.address = address
        type(self).made.append(self)

    def get(self, address):
        if address not in self.state:
            self.state[address] = ("desk-was-" + address, "s")
        return super().get(address)

    def identity(self):
        return OscReply(address="/?", typetag="s", args=list(type(self).identity_args))

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def desk(monkeypatch):
    _Desk.identity_args = [COMPACT_ID]
    _Desk.made = []
    monkeypatch.setattr(console_module, "WingConsole", _Desk)
    return _Desk


@pytest.fixture
def verified_against(monkeypatch):
    """Every model `apply_cmd` ran `verify_plan` against, in order."""
    seen: list = []
    real = cli.verify_plan

    def spy(plan, rows=None, **kwargs):
        seen.append(kwargs.get("console_model"))
        return real(plan, rows, **kwargs)

    monkeypatch.setattr(cli, "verify_plan", spy)
    return seen


def _writes(desk) -> int:
    return sum(len(d.set_param_calls) + len(d.set_node_calls) for d in desk.made)


def _apply(tmp_path, plan, *extra):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    journal = tmp_path / "j.json"
    return main(["apply", "--plan", str(path), "--console", "198.51.100.6",
                 "--journal", str(journal), *extra]), journal


# ======================================================================
# Different model, every socket present: proceed, INFO, verify vs desk
# ======================================================================

def test_a_compact_plan_applies_to_a_rack_and_says_so(tmp_path, desk, verified_against, capsys):
    desk.identity_args = [RACK_ID]
    code, journal = _apply(tmp_path, _plan(), "--confirm")
    err = capsys.readouterr().err

    assert code == 0
    assert _writes(desk) > 0
    assert "INFO: This plan is for a WING Compact, but 198.51.100.6 is a WING Rack" in err
    assert "Every socket the plan patches exists on this desk" in err
    assert "pre-flight verify re-run against wing-rack" in err
    # The pre-flight gate checked what is actually being written to.
    assert verified_against[-1] == "wing-rack"
    recorded = json.loads(journal.read_text())
    assert recorded["model_check"]["outcome"] == CROSS_MODEL
    assert recorded["model_check"]["severity"] == "info"
    assert recorded["desk"]["model"] == "wing-rack"


def test_a_cross_model_apply_is_still_refused_on_a_real_error_against_the_desk(
        tmp_path, desk, monkeypatch, capsys):
    """The re-verify is a gate, not a formality. The Compact and Rack
    panels are identical, so the error is injected: verify fails only
    when asked about the Rack."""
    from atoo.verify_plan import VerifyResult

    def verify(plan, rows=None, **kwargs):
        result = VerifyResult()
        if kwargs.get("console_model") == "wing-rack":
            result.add("error", "output.socket-out-of-range", "outputs[Matrix 1]", "wrong for a Rack")
        return result

    monkeypatch.setattr(cli, "verify_plan", verify)
    desk.identity_args = [RACK_ID]
    code, journal = _apply(tmp_path, _plan(), "--confirm")
    err = capsys.readouterr().err

    assert code == 2
    assert "wrong for a Rack" in err
    assert "does not verify against the WING Rack" in err
    assert _writes(desk) == 0 and not journal.exists()


def test_skip_verify_across_models_does_not_claim_a_verify_ran(
        tmp_path, desk, verified_against, capsys):
    desk.identity_args = [RACK_ID]
    code, _ = _apply(tmp_path, _plan(), "--skip-verify")
    err = capsys.readouterr().err
    assert code == 0
    assert verified_against == []
    assert "--skip-verify was passed, so the plan was not verified against either model" in err


def test_console_model_is_still_an_explicit_override(tmp_path, desk, verified_against, capsys):
    """`--console-model wing-rack` on a Rack: the plan is checked for the
    desk named, the desk agrees, and there is nothing further to say."""
    desk.identity_args = [RACK_ID]
    code, journal = _apply(tmp_path, _plan(), "--console-model", "wing-rack")
    err = capsys.readouterr().err
    assert code == 0
    assert verified_against == ["wing-rack"]
    assert "This plan is for a" not in err
    assert "model_check" not in json.loads(journal.read_text())


# ======================================================================
# A socket the desk's model does not have: refuse, naming it
# ======================================================================

@pytest.mark.parametrize("skip_verify", [False, True])
def test_a_compact_plan_on_lcl_20_is_refused_by_a_full_size(
        tmp_path, desk, capsys, skip_verify):
    """The full-size has 8 local inputs; LCL 20 is a jack that is not
    there. `--skip-verify` is about the plan's findings, not the desk."""
    desk.identity_args = [FULL_ID]
    plan = _with_input(_plan(), "LCL", 20)
    code, journal = _apply(tmp_path, plan, "--confirm",
                           *(["--skip-verify"] if skip_verify else []))
    err = capsys.readouterr().err

    assert code == 2
    assert "ERROR: This plan is for a WING Compact, but 198.51.100.6 is a WING (full-size " \
           "console)" in err
    assert "LCL 20 (input) -- channel 'Kick'; LCL inputs are 1..8 on a WING (full-size " \
           "console)" in err
    assert "Refusing to apply: LCL 20 does not exist on the WING (full-size console)" in err
    assert "--console-model wing-full" in err
    assert _writes(desk) == 0 and not journal.exists()


def test_skip_verify_on_the_same_model_still_refuses_a_socket_the_desk_lacks(
        tmp_path, desk, capsys):
    """A full-size plan patching LCL 20 on a full-size desk (8 local
    inputs). Same model, so the cross-model walk never ran; without
    --skip-verify, verify refuses it -- but WITH it, nothing checked the
    sockets and the plan was written. Found reviewing an earlier change, where amend
    refuses this whatever --skip-verify says; apply now matches.

    Mutation-checked: drop the `args.skip_verify` socket block in
    `cli.apply_cmd` and the write count below is no longer 0."""
    desk.identity_args = [FULL_ID]
    plan = _with_input(_plan(), "LCL", 20)
    plan["meta"]["console_model"] = "wing-full"
    code, journal = _apply(tmp_path, plan, "--confirm", "--skip-verify")
    err = capsys.readouterr().err

    assert _writes(desk) == 0 and not journal.exists()
    assert code == 2
    assert "LCL 20 (input)" in err
    assert "--skip-verify skips the plan's findings, not the hardware" in err


def test_skip_verify_on_the_same_model_with_every_socket_present_still_applies(
        tmp_path, desk, capsys):
    """The absent case: the new check refuses only a missing socket."""
    desk.identity_args = [FULL_ID]
    plan = _with_input(_plan(), "LCL", 3)
    plan["meta"]["console_model"] = "wing-full"
    code, _ = _apply(tmp_path, plan, "--confirm", "--skip-verify")
    assert code == 0, capsys.readouterr().err
    assert _writes(desk) > 0


def test_a_full_size_plan_on_aux_is_refused_by_a_rack_naming_every_socket(
        tmp_path, desk, capsys):
    """AUX is the other model-variant group: 8 in / 8 out on the full-size,
    none at all on the Rack. Input side and output side both named."""
    desk.identity_args = [RACK_ID]
    plan = _with_input(_plan(), "AUX", 1)
    plan["meta"]["console_model"] = "wing-full"
    plan["outputs"]["Matrix 1"]["socket"] = {"group": "AUX", "sockets": [1, 2], "stated": True}
    code, _ = _apply(tmp_path, plan, "--confirm")
    err = capsys.readouterr().err

    assert code == 2
    assert "the WING Rack (19\", 4U) has no AUX inputs at all" in err
    assert "AUX 1 (output)" in err and "AUX 2 (output)" in err
    assert "3 socket(s) the plan patches do not exist" in err
    assert _writes(desk) == 0


def test_the_missing_socket_walk_covers_every_place_a_plan_names_one():
    """Unit-level, over `sockets_missing_on_model` itself: channel inputs,
    a USER PATCH's source, bus dedicated outputs and Main/Matrix outputs --
    and NOT the expansion bays, which are the same two on every model
    (their contents are the desk's own inventory, checked separately)."""
    plan = _with_input(_plan(), "LCL", 20)
    plan = _with_input(plan, "CRD", 1, index=1)
    plan["user_sources"] = [{"slot": 30, "source": {"group": "LCL", "index": 12}}]
    plan["outputs"]["Matrix 1"]["socket"] = {"group": "LCL", "sockets": [7, 8]}
    missing = sockets_missing_on_model(plan, "wing-full")
    assert missing == [
        "LCL 20 (input) -- channel 'Kick'; LCL inputs are 1..8 on a WING (full-size console)",
        "LCL 12 (input) -- the source of USR 30; LCL inputs are 1..8 on a WING "
        "(full-size console)",
    ]
    assert sockets_missing_on_model(plan, "wing-rack") == []

    busses = copy.deepcopy(plan.get("busses") or {})
    name = next(iter(busses))
    busses[name]["destinations"] = [{"type": "dedicated_output",
                                     "socket": {"group": "LCL", "sockets": [9]}}]
    plan["busses"] = busses
    assert "LCL 9 (output) -- LCL outputs are 1..8 on a WING Rack (19\", 4U)" in \
        sockets_missing_on_model(plan, "wing-rack")


# ======================================================================
# A desk whose model nobody has measured: proceed, WARNING, journal it
# ======================================================================

def test_an_unmeasured_model_token_is_announced_and_journalled(tmp_path, desk, capsys):
    desk.identity_args = [UNMEASURED_ID]
    code, journal = _apply(tmp_path, _plan(), "--confirm")
    err = capsys.readouterr().err

    assert code == 0
    assert _writes(desk) > 0
    assert ("WARNING: 198.51.100.6 calls itself 'wing-racksize', a model name Atoo has "
            "never measured on a real desk, so it cannot tell which WING this is") in err
    assert "checked against the plan's own model only, the WING Compact" in err
    assert "reads every write back from the desk and proves it landed" in err
    recorded = json.loads(journal.read_text())
    assert recorded["desk"]["model_token"] == "wing-racksize"
    assert recorded["model_check"]["outcome"] == DESK_MODEL_UNMEASURED
    assert recorded["model_check"]["desk_token"] == "wing-racksize"


def test_the_token_lands_on_the_bundle_journal_stack_too(tmp_path, desk, capsys):
    from atoo import journal_stack

    desk.identity_args = [UNMEASURED_ID]
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps(_plan()))
    assert main(["apply", "--show", str(show), "--console", "198.51.100.6", "--confirm"]) == 0
    entry = journal_stack.entries(show)[-1]
    assert entry.desk["model_token"] == "wing-racksize"


def test_a_desk_that_states_no_model_at_all_is_announced_too(tmp_path, desk, capsys):
    desk.identity_args = ["WING,198.51.100.6,BACKUP"]
    code, _ = _apply(tmp_path, _plan())
    err = capsys.readouterr().err
    assert code == 0
    assert "WARNING: 198.51.100.6 stated no model in its identity reply ('WING,198.51.100.6,BACKUP')" \
        in err


def test_an_unmeasured_desk_does_not_excuse_a_socket_the_plans_own_model_lacks(
        tmp_path, desk, capsys):
    """AUX 1 on a Compact plan: verify refuses that before the desk is even
    contacted, whatever the desk turns out to call itself."""
    desk.identity_args = [UNMEASURED_ID]
    code, _ = _apply(tmp_path, _with_input(_plan(), "AUX", 1), "--confirm")
    assert code == 2
    assert "Refusing to apply" in capsys.readouterr().err
    assert desk.made == []


# ======================================================================
# Same model: nothing new
# ======================================================================

@pytest.mark.parametrize("identity", [COMPACT_ID])
def test_the_same_model_says_nothing_new(tmp_path, desk, verified_against, capsys, identity):
    desk.identity_args = [identity]
    # --no-progress: this is about the model check. The reset read's own
    # end-of-read summary names the families this fake desk
    # does not answer at INFO, which is true and not the subject here.
    code, journal = _apply(tmp_path, _plan(), "--confirm", "--no-progress")
    err = capsys.readouterr().err
    assert code == 0
    assert "INFO:" not in err and "WARNING:" not in err and "ERROR:" not in err
    assert verified_against == [None]
    recorded = json.loads(journal.read_text())
    assert "model_check" not in recorded
    assert recorded["desk"]["model_token"] == "wing-compact"


def test_a_measured_alias_counts_as_the_same_model(tmp_path, desk, capsys):
    """`wing-fullsize` IS `wing-full`: no cross-model INFO."""
    desk.identity_args = [FULL_ID]
    plan = _plan()
    plan["meta"]["console_model"] = "wing-full"
    code, _ = _apply(tmp_path, plan)
    assert code == 0
    assert "This plan is for a" not in capsys.readouterr().err


# ======================================================================
# check_desk_model on its own
# ======================================================================

@pytest.mark.parametrize("plan_model, identity, outcome", [
    ("wing-compact", COMPACT_ID, SAME_MODEL),
    ("wing-compact", RACK_ID, CROSS_MODEL),
    ("wing-rack", COMPACT_ID, CROSS_MODEL),
    ("wing-compact", FULL_ID, CROSS_MODEL),          # A 1..20 and LCL out 7..8 exist on it
    ("wing-compact", UNMEASURED_ID, DESK_MODEL_UNMEASURED),
])
def test_each_outcome(plan_model, identity, outcome):
    check = check_desk_model(_plan(), plan_model, [identity], "198.51.100.6")
    assert check.outcome == outcome
    assert (check.message is None) == (outcome == SAME_MODEL)
    assert check.refuses is False


def test_a_missing_socket_is_the_only_refusal():
    check = check_desk_model(_with_input(_plan(), "LCL", 20), "wing-compact", [FULL_ID],
                             "198.51.100.7")
    assert check.outcome == SOCKETS_MISSING and check.refuses
    assert check.verify_against is None
    assert check.missing == ["LCL 20 (input) -- channel 'Kick'; LCL inputs are 1..8 on a "
                             "WING (full-size console)"]


def test_the_journal_record_round_trips():
    check = check_desk_model(_plan(), "wing-compact", [RACK_ID], "198.51.100.6")
    assert check.to_journal()["plan_model"] == "wing-compact"
    assert check.to_journal()["desk_model"] == "wing-rack"
    assert check.verify_against == "wing-rack"
    assert apply_module.check_desk_model is check_desk_model
