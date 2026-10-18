"""`amend`'s pre-flight -- apply's verify gate and the socket check,
asked of an amend.

Before this, `atoo apply` verified a plan and checked every socket it
patches against the model the desk says it is, and `atoo amend` did
neither: it would write a new strip onto LCL 20 of a full-size WING, which
has 8 local inputs. Under the rule that a judgement call is not an error of patching, that is the case which IS an
error -- a socket that does not exist is a physical setting the desk cannot
be left in -- so it is refused by name, in the preview as well as on
`--confirm`, and `--skip-verify` does not get past it. A model difference
with every socket present is a judgement call the conventions already
made, so it proceeds with the INFO apply prints; an identity token nobody
has measured proceeds with apply's WARNING.

Everything runs the real `atoo apply` and `amend` through `cli.main`
against the fake desks of `test_amend_two_desks.py` -- `WingConsole` is
replaced, so `_open_console`'s identity handling is the real one -- seeded
from the frozen `tests/fixtures/applied-show.plan.json` scenario. Bundles
are built in `tmp_path`; nothing here reads a bundle under `examples/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import cli
from atoo.amend import (plan_amendment, preflight, strip_occupancy,
                             written_sockets_missing)
from test_amend import amended_plan, applied_plan, occupancy_state
from test_amend_two_desks import Desk, fresh_state, podium_patched_by_hand, writes

COMPACT_IP, RACK_IP, FULL_IP, ODD_IP = "198.51.100.5", "198.51.100.6", "198.51.100.7", "198.51.100.8"
COMPACT_ID = "WING,{ip},PRIMARY,wing-compact,S-C,3.1.0"
RACK_ID = "WING,{ip},BACKUP,wing-rack,S-R,3.1.0"
#: The token a real full-size WING sends (A17, `IDENTITY_MODEL_ALIASES`).
FULL_ID = "WING,{ip},FOH,wing-fullsize,S-F,3.1.0"
#: A token nobody has measured.
ODD_ID = "WING,{ip},SPARE,wing-racksize,S-X,3.1.0"


@pytest.fixture
def desks(monkeypatch):
    network = {COMPACT_IP: Desk(fresh_state(), COMPACT_ID),
               RACK_IP: Desk(fresh_state(), RACK_ID),
               FULL_IP: Desk(fresh_state(), FULL_ID),
               ODD_IP: Desk(fresh_state(), ODD_ID)}

    def connect(address, port=None, timeout=None, raw_log=None):
        desk = network[address]
        desk.ip = address
        return desk

    monkeypatch.setattr("atoo.console.WingConsole", connect)
    _NETWORK.clear()
    _NETWORK.update(network)
    return network


_NETWORK: dict = {}


def bundle(tmp_path: Path, rebuilt: dict) -> Path:
    directory = tmp_path / "show"
    directory.mkdir()
    (directory / "plan.json").write_text(json.dumps(applied_plan(), indent=2) + "\n")
    (directory / "rebuilt.plan.json").write_text(json.dumps(rebuilt, indent=2))
    return directory


def applied_to(show: Path, ip: str, capsys) -> None:
    """The show on the desk, the way it gets there: `atoo apply`. The
    frozen plan is a Compact's; its sockets (A 1-20, LCL 1-4) exist on every
    model, so apply proceeds on each of these desks.

    `--no-init`: these desks are seeded with stand-in factory values (0, ''),
    not a real WING's initialized capture, so a reset to initialized would rewrite the very occupancy these tests are about."""
    code = cli.main(["apply", "--show", str(show), "--console", ip, "--confirm",
                     "--skip-verify", "--no-init"])
    assert code == 0, capsys.readouterr()
    capsys.readouterr()
    podium_patched_by_hand(_NETWORK[ip])


def amend(show: Path, ip: str, *extra: str) -> int:
    return cli.main(["amend", "--show", str(show),
                     "--amended-plan", str(show / "rebuilt.plan.json"),
                     "--console", ip, "--no-progress", *extra])


def trumpet_on(group: str, socket: int, *, model: str | None = None) -> dict:
    """The horn rebuild, with the Trumpet patched to `group socket`. The
    rebuild numbers it 20; strip 20 is somebody's "Podium", so it is placed
    on ch 21."""
    rebuilt = amended_plan()
    trumpet = next(c for c in rebuilt["channels"] if c["name"] == "Trumpet")
    trumpet["patch"] = {"group": group, "sockets": [socket], "stated": True}
    if model is not None:
        rebuilt["meta"]["console_model"] = model
    return rebuilt


def amend_entries(show: Path) -> list:
    """The amend entries on the bundle's journal stack -- the only record
."""
    from atoo import journal_stack

    return [e for e in journal_stack.entries(show) if e.kind == "amend"]


def amend_journal(show: Path) -> dict:
    return json.loads(amend_entries(show)[-1].path.read_text())


# --------------------------------------------------------------------------
# A socket the desk does not have: refused, by name, nothing written
# --------------------------------------------------------------------------


@pytest.mark.parametrize("extra", [(), ("--confirm",), ("--confirm", "--skip-verify")],
                         ids=["preview", "confirm", "confirm-skip-verify"])
def test_a_new_strip_on_lcl_20_of_a_full_size_desk_is_refused(tmp_path, desks, capsys,
                                                             extra):
    """The issue's own example. A full-size WING has LCL 1..8; the rebuild
    (a Compact's, where LCL 20 exists) patches the new Trumpet to LCL 20.
    Refused in the preview and on `--confirm`, with or without
    `--skip-verify`, naming the socket and the channel, and nothing
    reaches the desk."""
    show = bundle(tmp_path, trumpet_on("LCL", 20))
    applied_to(show, FULL_IP, capsys)
    desk = desks[FULL_IP]
    before, plan_before = writes(desk), (show / "plan.json").read_bytes()

    review = tmp_path / "review.json"
    code = amend(show, FULL_IP, "--review-json", str(review), *extra)
    captured = capsys.readouterr()

    assert code == 2, captured
    assert writes(desk) == before
    assert (show / "plan.json").read_bytes() == plan_before
    assert not amend_entries(show)
    assert ("  - LCL 20 (input) -- channel 'Trumpet'; LCL inputs are 1..8 on a WING "
            "(full-size console); channel 'Trumpet', new on ch:21") in captured.err
    last = [line for line in captured.err.splitlines() if line.strip()][-1]
    assert last.startswith("Refusing to amend: LCL 20 (channel 'Trumpet', new on ch:21) "
                           "does not exist on the WING (full-size console) at 198.51.100.7.")
    assert "--console-model wing-full" in last

    written = json.loads(review.read_text())
    assert written["blocked"] is True
    assert written["preflight"]["refusal_code"] == "amend.socket-missing-on-desk"
    assert "LCL 20" in written["preflight"]["refusal"]


def test_skip_verify_does_not_skip_the_socket_check_on_the_same_model(tmp_path, desks,
                                                                      capsys):
    """The socket check is not only a cross-model check. A rebuild for THIS
    model that names a socket no WING has (A 99: A inputs are 1..48) is
    something the verify would refuse -- and `--skip-verify` turns the
    verify off. What is left must still refuse it, because the flag is a
    judgement about the plan and this is a fact about the panel."""
    show = bundle(tmp_path, trumpet_on("A", 99))
    applied_to(show, COMPACT_IP, capsys)
    desk = desks[COMPACT_IP]
    before = writes(desk)

    code = amend(show, COMPACT_IP, "--confirm", "--skip-verify")
    captured = capsys.readouterr()

    assert code == 2, captured
    assert writes(desk) == before
    assert "--skip-verify: the amended plan was NOT verified" in captured.err
    assert ("Refusing to amend: A 99 (channel 'Trumpet', new on ch:21) does not exist on "
            "the WING Compact at 198.51.100.5.") in captured.err


def test_the_socket_check_covers_a_new_output_the_amend_writes():
    """The sockets an amend writes include a new output's physical socket
    (`_plan_new_outputs`' grant). Unit-level, because the fake desks'
    seeded state covers strips, not outputs."""
    rebuilt = amended_plan()
    rebuilt["outputs"] = dict(rebuilt.get("outputs") or {})
    rebuilt["outputs"]["Delays"] = {
        "kind": "matrix", "index": 7, "label": "Delays",
        "sockets": [{"group": "AUX", "sockets": [3]}]}
    amendment = plan_amendment(applied_plan(), rebuilt,
                               strip_occupancy(occupancy_state(), applied_plan()))
    lines = [m["line"] for m in written_sockets_missing(amendment, "wing-compact")]
    assert lines == ["AUX 3 (output) -- the WING Compact has no AUX outputs at all; the "
                     "socket output 'Delays' feeds"]
    assert written_sockets_missing(amendment, "wing-full") == []


def test_the_factory_patch_a_freed_strip_goes_back_on_is_checked_too():
    """A strip returned to free goes back on its measured factory socket. That comes from measured data for the model the desk stated
    and so should never be missing -- but it is a socket the amend writes,
    so it is checked. Forced here by checking a Compact's restore (ch 19 back
    on LCL 19) against a full-size panel."""
    applied = applied_plan()
    rebuilt = copy.deepcopy(applied)
    dropped = next(c for c in rebuilt["channels"] if c["channel"] == 19)
    rebuilt["channels"].remove(dropped)
    applied_19 = next(c for c in applied["channels"] if c["channel"] == 19)
    occupancy = strip_occupancy(occupancy_state(), applied)
    amendment = plan_amendment(applied, rebuilt, occupancy, console_model="wing-compact")
    assert amendment.released == ["ch:19"]
    missing = written_sockets_missing(amendment, "wing-full")
    assert [m["socket"] for m in missing] == ["LCL 19"], missing
    assert missing[0]["what"] == (f"the factory patch ch:19 is returned to (channel "
                                  f"{applied_19['name']!r}, dropped by the rebuild)")


# --------------------------------------------------------------------------
# A different model with every socket present: proceeds, with apply's INFO
# --------------------------------------------------------------------------


def test_a_compact_built_amend_on_a_rack_proceeds_with_the_info(tmp_path, desks, capsys):
    show = bundle(tmp_path, amended_plan())
    applied_to(show, RACK_IP, capsys)
    desk = desks[RACK_IP]

    code = amend(show, RACK_IP, "--confirm")
    captured = capsys.readouterr()

    assert code == 0, captured
    assert tuple(desk.state[f"/ch/{n}/name"][0] for n in (21, 22, 23)) == (
        "Trumpet", "Trombone", "T.Sax")
    assert ("INFO: This plan is for a WING Compact, but 198.51.100.6 is a WING Rack (19\", 4U). "
            "Every "
            "socket the plan patches exists on this desk, so it is applied as it stands, "
            "with the pre-flight verify re-run against wing-rack") in captured.err
    assert "Refusing" not in captured.err

    journal = amend_journal(show)
    assert journal["model_check"]["outcome"] == "cross-model"
    assert journal["model_check"]["severity"] == "info"
    assert journal["desk"]["model_token"] == "wing-rack"
    # And the stack carries it: the entry is the journal.
    entry = sorted((show / "journals").glob("*-amend-*.json"))[-1]
    assert json.loads(entry.read_text())["model_check"]["outcome"] == "cross-model"


# --------------------------------------------------------------------------
# A token nobody has measured: proceeds, with apply's WARNING
# --------------------------------------------------------------------------


def test_an_unmeasured_token_proceeds_with_the_warning(tmp_path, desks, capsys):
    show = bundle(tmp_path, amended_plan())
    applied_to(show, ODD_IP, capsys)

    code = amend(show, ODD_IP, "--confirm")
    captured = capsys.readouterr()

    assert code == 0, captured
    assert ("WARNING: 198.51.100.8 calls itself 'wing-racksize', a model name Atoo has "
            "never measured on a real desk") in captured.err
    assert "Sockets were checked against the plan's own model only" in captured.err
    journal = amend_journal(show)
    assert journal["model_check"]["outcome"] == "desk-model-unmeasured"
    assert journal["desk"]["model_token"] == "wing-racksize"


# --------------------------------------------------------------------------
# A real verify error in the effective plan: blocked, as apply blocks it
# --------------------------------------------------------------------------


def test_an_effective_plan_with_a_verify_error_is_blocked(tmp_path, desks, capsys):
    """A high-pass of 5 Hz on a new horn: outside the console's 20..2000 Hz,
    a value the desk cannot take. Refused in the preview, nothing written;
    `--skip-verify` is the same escape it is on apply."""
    rebuilt = amended_plan()
    rebuilt["channels"][-1]["processing"]["hpf_hz"] = 5
    show = bundle(tmp_path, rebuilt)
    applied_to(show, COMPACT_IP, capsys)
    desk = desks[COMPACT_IP]
    before = writes(desk)

    review = tmp_path / "review.json"
    code = amend(show, COMPACT_IP, "--confirm", "--review-json", str(review))
    captured = capsys.readouterr()
    assert code == 2, captured
    assert writes(desk) == before
    assert "value.hpf-out-of-range" in captured.err
    assert ("Refusing to amend: the amended plan does not verify against the WING Compact "
            "at 198.51.100.5") in captured.err
    written = json.loads(review.read_text())
    assert written["blocked"] is True
    assert written["preflight"]["refusal_code"] == "amend.verify-failed"
    assert any("value.hpf-out-of-range" in e for e in written["preflight"]["verify"]["errors"])

    code = amend(show, COMPACT_IP, "--skip-verify")
    captured = capsys.readouterr()
    assert code == 0, captured
    assert "--skip-verify: the amended plan was NOT verified" in captured.err


def test_a_verify_warning_does_not_block(tmp_path, desks, capsys):
    """Warnings never block -- the same gate as apply. The frozen plan
    carries a `reconcile.not-checked` warning on every run. (It carried a
    `strip.colour-not-writable` for 'Pink' too, until A24 found the desk
    has a Pink, 2026-09-28.)"""
    show = bundle(tmp_path, amended_plan())
    applied_to(show, COMPACT_IP, capsys)
    code = amend(show, COMPACT_IP)
    captured = capsys.readouterr()
    assert code == 0, captured
    assert ("Pre-flight verify of the amended plan against the WING Compact at 198.51.100.5: "
            "no errors, 1 warning(s) (reconcile.not-checked) -- "
            "warnings do not block.") in captured.out


def test_an_amend_in_a_show_with_an_input_list_is_held_to_the_whole_list(tmp_path, desks, capsys):
    """An amend is a rebuild, so unlike a typed change it is checked against
    every row of the show's input list, as a full build is -- and the
    `reconcile.not-checked` warning goes."""
    show = bundle(tmp_path, amended_plan())
    lines = ["socket,name,category,type,model,phantom,notes"]
    for ch in amended_plan()["channels"]:
        source = ch["source"]
        lines.append(f",{source['input']},drums,{source['type']},{source['model']},"
                     f"{'TRUE' if source['phantom'] else 'FALSE'},")
    (show / "input.csv").write_text("\n".join(lines) + "\n")
    applied_to(show, COMPACT_IP, capsys)
    code = amend(show, COMPACT_IP)
    captured = capsys.readouterr()
    assert code == 0, captured
    assert "reconcile.not-checked" not in captured.out
    assert "INFO input.csv: 22 row(s), checked against the amended plan" in captured.out


# --------------------------------------------------------------------------
# Same model, clean: nothing new said
# --------------------------------------------------------------------------


def test_same_model_clean_says_nothing_new(tmp_path, desks, capsys):
    show = bundle(tmp_path, amended_plan())
    applied_to(show, COMPACT_IP, capsys)

    code = amend(show, COMPACT_IP, "--confirm")
    captured = capsys.readouterr()

    assert code == 0, captured
    for said in ("INFO: This plan is for", "WARNING:", "ERROR:", "Refusing"):
        assert said not in captured.err, said
    journal = amend_journal(show)
    assert "model_check" not in journal
    # The desk block apply records, with the model exactly as the desk spelled it.
    assert journal["desk"]["model_token"] == "wing-compact"
    assert journal["desk"]["serial"] == "S-C"


def test_an_offline_review_is_refused_too(tmp_path, capsys):
    """`--state` contacts no desk, so the plan's own model stands in -- and
    says so. A rebuild that names a socket that model does not have is
    still refused, with the exit code, before the offline return."""
    show = bundle(tmp_path, trumpet_on("LCL", 20, model="wing-full"))
    state = tmp_path / "state.json"
    state.write_text(json.dumps(occupancy_state().values))
    code = cli.main(["amend", "--show", str(show), "--amended-plan",
                     str(show / "rebuilt.plan.json"), "--state", str(state),
                     "--skip-verify"])
    captured = capsys.readouterr()
    assert code == 2, captured
    assert ("does not exist on the WING (full-size console) the plan is for (reviewed "
            "offline: no desk was asked)") in captured.err


def test_nothing_to_write_is_nothing_to_check(tmp_path, desks, capsys):
    """An amend with nothing to write runs no pre-flight: it is not refused
    for a finding in a plan it does not touch. Here the running show itself
    carries a verify error (a 5 Hz high-pass on ch 1) and the rebuild is the
    same show: nothing to add, exit 0, and the review is not blocked."""
    show = bundle(tmp_path, applied_plan())
    applied_to(show, COMPACT_IP, capsys)
    broken = applied_plan()
    broken["channels"][0]["processing"]["hpf_hz"] = 5
    for name in ("plan.json", "rebuilt.plan.json"):
        (show / name).write_text(json.dumps(broken, indent=2))
    review = tmp_path / "review.json"
    code = cli.main(["amend", "--plan", str(show / "plan.json"), "--amended-plan",
                     str(show / "rebuilt.plan.json"), "--console", COMPACT_IP,
                     "--no-progress", "--review-json", str(review)])
    captured = capsys.readouterr()
    assert code == 0, captured
    assert "Nothing to add and nothing to return to free" in captured.out
    written = json.loads(review.read_text())
    assert written["blocked"] is False and written["preflight"] is None


def test_the_verify_runs_against_the_desk_s_model_not_only_the_plan_s(tmp_path, desks,
                                                                      capsys):
    """The verify is over the whole effective plan, against the DESK's
    model -- which catches what the socket check, over written sockets
    only, cannot: a running strip the rebuild repatched to LCL 20. The
    amend does not write that strip (MODIFIED), but a confirmed bundle
    amend makes the effective plan `plan.json`, and on a full-size desk
    that plan names a jack the panel does not have. Against the plan's own
    Compact it would verify clean."""
    rebuilt = amended_plan()
    rebuilt["channels"][0]["patch"] = {"group": "LCL", "sockets": [20], "stated": True}
    show = bundle(tmp_path, rebuilt)
    applied_to(show, FULL_IP, capsys)
    before = writes(desks[FULL_IP])

    code = amend(show, FULL_IP, "--confirm")
    captured = capsys.readouterr()
    assert code == 2, captured
    assert writes(desks[FULL_IP]) == before
    assert "patch.socket-out-of-range" in captured.err
    assert ("Refusing to amend: the amended plan does not verify against the WING "
            "(full-size console) at 198.51.100.7") in captured.err


def test_preflight_same_model_has_no_model_check_to_journal():
    amendment = plan_amendment(applied_plan(), amended_plan(),
                               strip_occupancy(occupancy_state(), applied_plan()))
    result = preflight(amendment, identity_args=[COMPACT_ID.format(ip=COMPACT_IP)],
                       address=COMPACT_IP)
    assert result.model_check.outcome == "same-model"
    assert result.journal_model_check() is None
    assert not result.refuses and result.verify.errors == []
