"""A socket beyond the end of a stage box does not exist.

A desk with an S16 on AES50-A lists 48 sockets on A whatever is plugged in
(`/io/in/A` is the address space), so a change that left the socket to the
model got `A 17`, which Atoo accepted and wrote: a mic patched to nothing.
The desk names the device on each port (`/$stat/A/dev` reads `S16`), and the
box's own size bounds the choice: Patch will not choose past it, and Patch's
pre-flight and Apply refuse a socket that is past it, naming the box and its
size. A device name Atoo has no size for is reported and left unchecked.

Every plan and desk here is built in the test (nothing reads `examples/`).
"""

from __future__ import annotations

import json

import pytest

from atoo import amend, patch
from atoo import apply as apply_module
from atoo import console_facts as facts
from atoo.amend import strip_occupancy
from atoo.cli import main
from atoo.console import OscReply
from test_amend import applied_plan, horn, occupancy_state  # noqa: E402

S16_ON_A = {"A": "S16", "B": "", "C": ""}


# ------------------------------------------------------------------ the facts


def test_the_s16_has_sixteen_inputs_and_eight_outputs():
    assert facts.box_size("S16") == (16, 8)
    assert facts.box_size(" s16 ") == (16, 8)


@pytest.mark.parametrize("name", ["", None, "SD16", "DL32", "S16X"])
def test_a_box_nobody_has_measured_has_no_size(name):
    assert facts.box_size(name) is None


def test_the_device_leaf_is_the_one_the_desk_answers():
    assert facts.aes50_device_address("A") == "/$stat/A/dev"


class _Desk:
    def __init__(self, answers):
        self.answers = answers

    def get(self, address):
        if address in self.answers:
            return OscReply(address=address, typetag="s", args=[self.answers[address]])
        return None


def test_the_desk_is_asked_what_is_on_each_port():
    devices = apply_module.read_aes50_devices(_Desk({"/$stat/A/dev": "S16", "/$stat/B/dev": ""}))
    assert devices == {"A": "S16", "B": "", "C": None}, \
        "an empty port is empty; a port that did not answer is not claimed empty"


# ------------------------------------------------------------------ the check


def _plan(*patches, outputs=None) -> dict:
    channels = []
    for i, (group, socket) in enumerate(patches, start=1):
        channel = horn(i, f"Mic {i}", socket)
        channel["patch"] = {"group": group, "sockets": [socket], "stated": True}
        channels.append(channel)
    return {"channels": channels, "dcas": {}, "mute_groups": {}, "busses": {},
            "outputs": outputs or {}, "meta": {"console_model": "wing-compact"}}


def test_a_socket_past_the_end_of_the_box_is_named_with_the_box_and_its_size():
    [row] = apply_module.box_sockets_missing(_plan(("A", 16), ("A", 17)), S16_ON_A)
    assert row["socket"] == "A 17" and row["box"] == "the S16 on AES50-A"
    assert "channel 'Mic 2'" in row["line"] and "has 16 inputs" in row["line"]


def test_the_last_socket_the_box_has_is_fine_and_other_ports_are_not_the_boxes():
    assert apply_module.box_sockets_missing(_plan(("A", 16), ("B", 40), ("LCL", 3)), S16_ON_A) == []


def test_an_output_is_held_to_the_boxs_outputs():
    plan = _plan(outputs={"Wedge": {"kind": "main", "index": 1,
                                    "patch": {"group": "A", "sockets": [9]}}})
    rows = apply_module.box_sockets_missing(plan, S16_ON_A, output_sockets=[("A", 9)])
    assert [r["socket"] for r in rows] == ["A 9"] and "8 outputs" in rows[0]["line"]
    assert apply_module.box_sockets_missing(plan, S16_ON_A, output_sockets=[("A", 8)]) == []


def test_an_unknown_box_is_reported_and_its_sockets_are_not_refused():
    devices = {"A": "SD99", "B": "", "C": None}
    assert apply_module.box_sockets_missing(_plan(("A", 40)), devices) == []
    assert apply_module.unknown_boxes(devices) == {"A": "SD99"}


def test_a_desk_that_did_not_answer_checks_nothing():
    assert apply_module.box_sockets_missing(_plan(("A", 40)), None) == []
    assert apply_module.box_sockets_missing(_plan(("A", 40)), {"A": None}) == []


# ------------------------------------------------------------------- Patch


def _review(channel, *, devices=S16_ON_A, text="add the lead vocal", plan=None):
    plan = plan if plan is not None else applied_plan()
    change_set = patch.empty_change_set("Lead")
    change_set["add"]["channels"] = [channel]
    occupancy = strip_occupancy(occupancy_state(theirs=(), plan=plan), plan)
    amendment, merge = patch.plan_patch(plan, change_set, occupancy, console_model="wing-compact",
                                        text=text, aes50_devices=devices)
    return amendment, merge, plan


def _lead(socket, *, stated):
    channel = horn(30, "F Lead2", socket)
    channel["patch"] = {"group": "A", "sockets": [socket], "stated": stated}
    channel["dca"], channel["mute_group"], channel["bus_sends"] = [], [], []
    return channel


def _small_show() -> dict:
    plan = applied_plan()
    plan["channels"] = plan["channels"][:3]
    return plan


def test_patch_does_not_choose_a_socket_past_the_box():
    """The model picked A 17 for a change that named no socket; the S16 has
    16, so the first free one of those is chosen, and said."""
    plan = _small_show()
    amendment, _, plan = _review(_lead(17, stated=False), plan=plan)
    used = {(c["patch"]["group"], s) for c in plan["channels"] for s in c["patch"]["sockets"]}
    [added] = [c for c in amendment.effective_plan["channels"] if c["name"] == "F Lead2"]
    group, [socket] = added["patch"]["group"], added["patch"]["sockets"]
    assert group == "A" and socket <= 16 and (group, socket) not in used
    [info] = [i for i in amendment.infos if "F Lead2" in i and "was picked" in i]
    assert "the S16 on AES50-A has 16 inputs, so there is no A 17" in info


def test_patch_without_a_box_reading_keeps_the_socket_it_was_given():
    amendment, _, _ = _review(_lead(17, stated=False), devices=None, plan=_small_show())
    [added] = [c for c in amendment.effective_plan["channels"] if c["name"] == "F Lead2"]
    assert added["patch"]["sockets"] == [17]


def test_with_every_socket_of_the_box_taken_the_pick_is_left_and_the_preflight_refuses():
    """The S16 on A is full (the show has A 1-20): nothing free to choose
    instead, so the pick stands, with a warning, and the pre-flight is what
    stops it -- a socket that does not exist is never written."""
    amendment, _, _ = _review(_lead(17, stated=False))
    assert any("no free A socket is left" in w for w in amendment.warnings)
    result = amend.preflight(amendment, skip_verify=True, what="change", aes50_devices=S16_ON_A)
    assert result.refuses and "A 17" in result.refusal


def test_a_socket_the_change_names_past_the_box_is_refused_by_the_preflight():
    amendment, _, _ = _review(_lead(17, stated=True), text="lead vocal on A 17")
    result = amend.preflight(amendment, skip_verify=True, what="change", aes50_devices=S16_ON_A)
    assert result.refuses and result.refusal_code == "amend.socket-missing-on-box"
    assert "A 17" in result.refusal and "the S16 on AES50-A" in result.refusal
    assert "has 16 inputs" in result.refusal and "Nothing was written" in result.refusal
    assert "--skip-verify does not change that" in result.refusal
    assert [m["socket"] for m in result.missing] == ["A 17"]


def test_a_socket_the_box_has_passes_the_preflight():
    amendment, _, _ = _review(_lead(16, stated=True), text="lead vocal on A 16")
    result = amend.preflight(amendment, skip_verify=True, what="change", aes50_devices=S16_ON_A)
    assert not result.refuses, result.refusal


def test_an_unknown_box_is_an_info_not_a_refusal():
    amendment, _, _ = _review(_lead(40, stated=True), devices={"A": "SD99", "B": "", "C": ""},
                              text="lead vocal on A 40")
    result = amend.preflight(amendment, skip_verify=True, what="change",
                             aes50_devices={"A": "SD99", "B": "", "C": ""})
    assert not result.refuses
    assert any("'SD99'" in i and "no size recorded" in i for i in result.infos)


def test_the_refusal_reaches_the_review_as_blocked():
    amendment, _, _ = _review(_lead(17, stated=True), text="lead vocal on A 17")
    result = amend.preflight(amendment, skip_verify=True, what="change", aes50_devices=S16_ON_A)
    assert result.to_review()["refusal"] == result.refusal
    assert result.to_review()["refusal_code"] == "amend.socket-missing-on-box"


# ------------------------------------------------------------------- Apply


def _desk(devices: dict | None, model="wing-compact"):
    class FakeConsole:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def identity(self):
            return OscReply(address="/?", typetag="s",
                            args=[f"WING,192.0.2.16,Fake,{model},SN,3.1-0"])

        def get(self, address):
            for port, device in (devices or {}).items():
                if address == f"/$stat/{port}/dev" and device is not None:
                    return OscReply(address=address, typetag="s", args=[device])
            return None

        def close(self):
            pass

    return FakeConsole


def _plan_file(tmp_path, *patches) -> str:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(_plan(*patches)))
    return str(path)


def test_apply_refuses_a_plan_patched_past_the_end_of_the_box(tmp_path, capsys, monkeypatch):
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole", _desk(S16_ON_A))
    code = main(["apply", "--plan", _plan_file(tmp_path, ("A", 16), ("A", 17)),
                 "--console", "192.0.2.16", "--skip-verify", "--confirm"])
    err = capsys.readouterr().err
    assert code == 2
    assert "channel 'Mic 2'" in err and "A 17" in err
    assert "the S16 on AES50-A has 16 inputs" in err
    assert "Nothing was written" in err


def test_apply_goes_ahead_when_every_socket_is_the_boxs(tmp_path, capsys, monkeypatch):
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole", _desk(S16_ON_A))
    code = main(["apply", "--plan", _plan_file(tmp_path, ("A", 15), ("A", 16)),
                 "--console", "192.0.2.16", "--skip-verify"])
    assert "does not exist" not in capsys.readouterr().err
    assert code == 0


def test_apply_says_when_it_could_not_check_an_unknown_box(tmp_path, capsys, monkeypatch):
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole", _desk({"A": "SD99", "B": "", "C": ""}))
    code = main(["apply", "--plan", _plan_file(tmp_path, ("A", 40)), "--console", "192.0.2.16",
                 "--skip-verify"])
    err = capsys.readouterr().err
    assert code == 0
    assert "AES50-A reports a 'SD99'" in err and "were not checked" in err


def test_apply_asks_nothing_of_a_desk_when_the_plan_uses_no_port(tmp_path, monkeypatch):
    import atoo.console as console_module
    asked: list[str] = []
    desk = _desk(S16_ON_A)
    original = desk.get

    def spying_get(self, address):
        asked.append(address)
        return original(self, address)

    desk.get = spying_get
    monkeypatch.setattr(console_module, "WingConsole", desk)
    main(["apply", "--plan", _plan_file(tmp_path, ("LCL", 1)), "--console", "192.0.2.16",
          "--skip-verify"])
    assert not [a for a in asked if a.startswith("/$stat/")]


# ------------------------------------------------- the worked example in the docs


def test_the_docs_stage_box_example_runs_as_the_page_shows(tmp_path, capsys):
    from pathlib import Path

    root = Path(__file__).parent.parent
    state = json.loads((root / "atoo" / "web" / "demo_states" / "before.json").read_text())
    state["/$stat/A/dev"] = "S16"
    capture = tmp_path / "s16.json"
    capture.write_text(json.dumps(state))
    code = main(["patch", "--show", str(root / "starter" / "demo-show"), "--change-set",
                 str(root / "docs" / "user" / "demo" / "demo-show" / "hihat-a17.change-set.json"),
                 "--state", str(capture), "HiHat on A 17"])
    out = capsys.readouterr()
    assert code == 2
    assert ("ERROR: This change would patch 1 socket(s) that do not exist on the S16 on "
            "AES50-A:") in out.err + out.out
    assert "  - A 17 (input) -- channel 'HiHat'; the S16 on AES50-A has 16 inputs, so A 17 " \
           "does not exist" in out.err + out.out
