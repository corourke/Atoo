"""What a released strip's input patch goes to: OFF.

A strip returned to free by a change used to be patched back to its measured
factory socket (a Compact's ch 19 on LCL 19), while a full apply's reset
left a strip the plan does not use at OFF. Two answers to "what is free?"
meant a strip freed by a change and then fully applied ended up different.
The decision: *"freed channels are left unpatched (input off). Patch's
return-to-free should match full apply/reset, not restore LCL n."*

So the release writes `.grp = OFF` for every model, measured or not, claimed
socket or not, and the INFO says so. What still takes the factory patch is
the READ: a strip found on its factory socket, blank, is free (a desk
initialized by hand, or a release that got partway), and a release
re-run must accept it.

Every plan and desk here is built in the test -- nothing is read from a
bundle under `examples/`.
"""

from __future__ import annotations

import pytest

from atoo import apply as apply_module
from atoo import console_facts as facts
from atoo.amend import (
    ChangeKind,
    StripState,
    amendment_targets,
    apply_amendment,
    plan_amendment,
    read_occupancy,
    strip_occupancy,
)
from atoo.audit import ConsoleState
from tests.test_amend import DeskConsole


# --------------------------------------------------------------------------
# Plans and desks, built here
# --------------------------------------------------------------------------


def channel(number: int, name: str, group: str, socket: int, *, bank: str = "ch") -> dict:
    """One channel entry of the shape `build` produces, with nothing on it
    beyond a name, a colour and a patch -- the release's patch step is the
    subject, and every other leaf would only be noise in the write set."""
    return {
        "channel": number,
        "bank": bank,
        "name": name,
        "color": "Blue",
        "source": {"input": name, "type": "Mic", "model": "", "stereo": False,
                   "phantom": False},
        "patch": {"group": group, "sockets": [socket], "stated": True},
        # The two fields the schema requires, both unset: the plan must
        # verify, now that amend runs apply's pre-flight.
        "processing": {"hpf_hz": None, "preset": None},
        "fader": {"fader_db": 0.0, "muted": None},
        "dca": [],
        "mute_group": [],
        "bus_sends": [],
        "main_routes": [],
        "provenance": {},
    }


def plan(channels: list[dict], model: str | None = "wing-compact") -> dict:
    meta = {"console_model": model} if model else {}
    return {"meta": meta, "channels": channels, "busses": {}, "dcas": {}, "mute_groups": {},
            "outputs": {}}


#: The applied show: a kick on ch 1 (its own factory socket) and a lead
#: vocal on ch 19 from stagebox socket A 5 -- the strip the maintainer's session
#: freed, patched from somewhere other than its factory socket so a
#: restore is a visible change.
KICK = channel(1, "Kick", "LCL", 1)
VOX = channel(19, "Lead Vox", "A", 5)


def desk(applied: dict, model: str | None = "wing-compact", *, extra: dict | None = None
         ) -> ConsoleState:
    """The occupancy read of a desk carrying exactly `applied`, every other
    strip untouched and answering (factory label, OFF), every socket a
    strip is patched to named the way `apply` left it."""
    values: dict[str, object] = {}
    by_slot = {(c.get("bank", "ch"), c["channel"]): c for c in applied["channels"]}
    for bank, count in (("ch", 40), ("aux", 8)):
        for n in range(1, count + 1):
            base = f"/{bank}/{n}"
            values[f"{base}/clink"] = 1
            entry = by_slot.get((bank, n))
            if entry is not None:
                group, socket = entry["patch"]["group"], entry["patch"]["sockets"][0]
                values[f"{base}/name"] = entry["name"]
                values[f"{base}/in/conn/grp"] = group
                values[f"{base}/in/conn/in"] = socket
                values[f"/io/in/{group}/{socket}/name"] = entry["name"]
            else:
                values[f"{base}/name"] = ""
                values[f"{base}/in/conn/grp"] = "OFF"
                values[f"{base}/in/conn/in"] = 0
    values.update(extra or {})
    return ConsoleState(values, console_model=model)


def release(applied: dict, amended: dict, state: ConsoleState, **kwargs):
    occupancy = strip_occupancy(state, applied)
    return plan_amendment(applied, amended, occupancy,
                          console_model=state.console_model, **kwargs)


def patch_writes(targets, base: str = "/ch/19") -> dict[str, object]:
    return {t.address: t.compute_value(None) for t in targets
            if t.address.startswith(f"{base}/in/conn/")}


def release_info(amendment, label: str = "ch:19") -> str:
    found = [i for i in amendment.infos if f"on {label} was dropped" in i]
    assert len(found) == 1, amendment.infos
    return found[0]


# --------------------------------------------------------------------------
# release_write_targets, directly
# --------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["wing-compact", "wing-full", "wing-rack", None])
def test_a_release_leaves_the_patch_off_whatever_the_model(model):
    """Ch 19 on a Compact would have gone back on LCL 19; now every model
    gets OFF, `.grp` alone (OFF is fully disconnected, `.in` is
    meaningless after it)."""
    kwargs = {} if model is None else {"console_model": model}
    targets = apply_module.release_write_targets([VOX], **kwargs)
    assert patch_writes(targets) == {"/ch/19/in/conn/grp": "OFF"}
    order = [t.address for t in targets]
    # After the old socket's label and phantom are cleared, before the
    # strip's own name and clink.
    assert order.index("/io/in/A/5/name") < order.index("/ch/19/in/conn/grp")
    assert order.index("/io/in/A/5/vph") < order.index("/ch/19/in/conn/grp")
    assert order.index("/ch/19/in/conn/grp") < order.index("/ch/19/clink")


def test_a_media_aux_is_left_off_too():
    aux1 = channel(1, "Walk-in", "A", 40, bank="aux")
    targets = apply_module.release_write_targets([aux1], console_model="wing-compact")
    assert patch_writes(targets, "/aux/1") == {"/aux/1/in/conn/grp": "OFF"}


def test_the_release_writes_the_same_off_a_full_apply_leaves_an_unused_strip():
    """"Free" means one thing: the full apply's unpatch of a strip the plan
    does not use writes `.grp = OFF`, and so does the release."""
    targets = apply_module.release_write_targets([VOX], console_model="wing-compact")
    grp = next(t for t in targets if t.address == "/ch/19/in/conn/grp")
    assert grp.compute_value(None) == "OFF"


# --------------------------------------------------------------------------
# Through the amend engine: the INFO
# --------------------------------------------------------------------------


def test_amend_leaves_the_patch_off_and_says_so():
    applied = plan([KICK, VOX])
    amendment = release(applied, plan([KICK]), desk(applied))
    assert amendment.released == ["ch:19"]
    assert patch_writes(amendment_targets(amendment).releases) == {"/ch/19/in/conn/grp": "OFF"}
    info = release_info(amendment)
    assert "left unpatched (OFF)" in info and "full apply" in info


def test_a_rebuilt_plan_using_the_factory_socket_changes_nothing_about_the_release():
    """The old rule left ch 19 OFF here to avoid a double patch; OFF is now
    the answer in every case, so the socket is simply not touched."""
    applied = plan([KICK, VOX])
    rebuilt = plan([KICK, channel(21, "Podium Mic", "LCL", 19)])
    amendment = release(applied, rebuilt, desk(applied))
    assert kinds(amendment, ChangeKind.ADDED) and amendment.released == ["ch:19"]
    assert patch_writes(amendment_targets(amendment).releases) == {"/ch/19/in/conn/grp": "OFF"}


def test_two_released_strips_both_go_off():
    applied = plan([KICK, VOX, channel(3, "BV", "LCL", 19)])
    amendment = release(applied, plan([KICK]), desk(applied))
    assert sorted(amendment.released) == ["ch:19", "ch:3"]
    releases = amendment_targets(amendment).releases
    assert patch_writes(releases) == {"/ch/19/in/conn/grp": "OFF"}
    assert patch_writes(releases, "/ch/3") == {"/ch/3/in/conn/grp": "OFF"}


def test_the_model_does_not_change_the_answer():
    applied = plan([KICK, VOX], model="wing-rack")
    amendment = release(applied, plan([KICK], model="wing-rack"), desk(applied, "wing-rack"))
    assert patch_writes(amendment_targets(amendment).releases) == {"/ch/19/in/conn/grp": "OFF"}


def test_a_strip_an_earlier_run_left_on_its_factory_patch_is_still_cleared():
    """A release that got partway -- the patch landed, a later leaf did
    not -- leaves ch 19 blank on LCL 19. Before 2026-09-24 a partial
    release left it OFF, and `release_refusal` accepted OFF as "somebody
    already freed it". It has to accept the factory patch the same way, or
    re-running the amend refuses to finish its own job."""
    applied = plan([KICK, VOX])
    state = desk(applied, extra={"/ch/19/name": "", "/ch/19/in/conn/grp": "LCL",
                                 "/ch/19/in/conn/in": 19, "/io/in/LCL/19/name": ""})
    amendment = release(applied, plan([KICK]), state)
    assert amendment.released == ["ch:19"], [c.detail for c in amendment.changes]


def test_a_podium_on_the_factory_patch_is_still_refused():
    """The source-name arm still runs on a strip found on its factory
    patch: named on its socket by somebody, it is somebody's."""
    applied = plan([KICK, VOX])
    state = desk(applied, extra={"/ch/19/name": "", "/ch/19/in/conn/grp": "LCL",
                                 "/ch/19/in/conn/in": 19, "/io/in/LCL/19/name": "Podium"})
    amendment = release(applied, plan([KICK]), state)
    assert amendment.released == []
    assert [c.slot for c in kinds(amendment, ChangeKind.REMOVED)] == ["ch:19"]


def test_another_socket_than_the_factory_one_is_still_a_repatch():
    applied = plan([KICK, VOX])
    state = desk(applied, extra={"/ch/19/in/conn/grp": "LCL", "/ch/19/in/conn/in": 7})
    amendment = release(applied, plan([KICK]), state)
    assert amendment.released == []


def test_an_unmeasured_model_does_not_accept_the_identity_as_a_factory_patch():
    """The refusal errs towards refusing: on a Rack nobody has measured,
    ch 19 on LCL 19 is not known to be the factory patch."""
    applied = plan([KICK, VOX], model="wing-rack")
    state = desk(applied, "wing-rack", extra={
        "/ch/19/name": "", "/ch/19/in/conn/grp": "LCL", "/ch/19/in/conn/in": 19,
        "/io/in/LCL/19/name": ""})
    amendment = release(applied, plan([KICK], model="wing-rack"), state)
    assert amendment.released == []


def kinds(amendment, kind) -> list:
    return [c for c in amendment.changes if c.kind is kind]


# --------------------------------------------------------------------------
# And afterwards the strip reads FREE -- on a desk, through the real read
# --------------------------------------------------------------------------


def _desk_console(applied: dict) -> DeskConsole:
    """A fake WING holding `applied` on the wire, with the readback offset
    a real one has (`DeskConsole`), every occupancy address answering."""
    state: dict = {}
    for address, value in desk(applied).values.items():
        state[address] = (value, "s" if isinstance(value, str) else "i")
    built, _ = apply_module._build_write_targets(applied, set_fader_levels=True)
    for t in built:
        state.setdefault(t.address, (t.compute_value(None), t.value_type))
    # The socket ch 19 goes back to, as an untouched desk answers for it.
    state["/io/in/LCL/19/name"] = (facts.FACTORY_SOURCE_NAME, "s")
    return DeskConsole(state)


@pytest.mark.parametrize("model", ["wing-compact", None])
def test_the_freed_strip_reads_free_on_a_fresh_occupancy_read(model):
    """A15's step 5, on a fake desk: release ch 19, then read the desk
    again through `read_occupancy` -- the real read, readback offset and
    second pass included -- and ask about it with the rebuild as the
    applied plan. It is unpatched (OFF) and it is FREE.

    `None` is the offline replay: a state with no model of its own, which
    `strip_occupancy` fills from the plan, as the release did."""
    applied = plan([KICK, VOX])
    rebuilt = plan([KICK])
    console = _desk_console(applied)
    amendment = release(applied, rebuilt, desk(applied))
    result = apply_amendment(amendment, console, dry_run=False)
    assert result.mismatches == []

    fresh = read_occupancy(console, console_model=model)
    status = {s.label: s for s in strip_occupancy(fresh, rebuilt)}["ch:19"]
    assert status.patch is None
    assert status.name == ""
    assert status.state is StripState.FREE, status


def test_a_restored_media_aux_reads_free_when_the_state_has_no_model():
    """Why `strip_occupancy` takes the model from the plan: the identity
    fallback does not know the media auxes, so without it a Compact's
    `/aux/1` back on USB 1 would read as somebody's on an offline replay."""
    values = {"/aux/1/name": "", "/aux/1/clink": 1, "/aux/1/in/conn/grp": "USB",
              "/aux/1/in/conn/in": 1, "/io/in/USB/1/name": ""}
    status = {s.label: s for s in strip_occupancy(ConsoleState(values), plan([]))}["aux:1"]
    assert status.state is StripState.FREE


def test_the_cli_takes_the_model_the_desk_states(tmp_path, monkeypatch, capsys):
    """`atoo amend --console`: the desk says it is a full-size WING on its
    `/?` reply, the plans say Compact. The model is taken from the desk;
    ch 19 goes OFF, and the INFO says so."""
    import json
    from atoo import cli

    applied, rebuilt = plan([KICK, VOX]), plan([KICK])
    applied_path, rebuilt_path = tmp_path / "applied.json", tmp_path / "rebuilt.json"
    applied_path.write_text(json.dumps(applied))
    rebuilt_path.write_text(json.dumps(rebuilt))
    console = _desk_console(applied)
    console.console_model = "wing-full"
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)

    code = cli.main(["amend", "--plan", str(applied_path), "--amended-plan", str(rebuilt_path),
                     "--console", "192.0.2.16", "--no-progress"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "left unpatched (OFF)" in out
    assert "/ch/19/in/conn/in" not in out
    assert console.set_param_calls == [] and console.set_node_calls == []
