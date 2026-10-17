"""What a released strip's input patch goes back to.

At the Compact session of 2026-09-24 a channel returned to free did not
look like an initialized one: *"A truly initialized channel 19 would be
patched to LCL 19 and have an icon like the other initialized channels.
Otherwise, it is reset and appears ready to be patched."* The icon is the
LCL socket's own glyph, shown through the patch, so the patch is the one
real difference. Of three options he chose:

    *"The factory patch, unless the plan uses that socket, otherwise OFF.
    Ch 19 goes back to LCL 19 and looks exactly like an initialized
    channel, glyph included. If the rebuilt plan now uses LCL 19 for
    something else, it stays OFF rather than double-patching the socket,
    and an INFO says so."*

**The trap these tests exist for** is `console_facts.factory_input_patch`'s
channel-n-from-LCL-n fallback. It is right for reading occupancy and wrong
for a write: a model nobody measured may not have LCL 19 at all. Several
tests below use `wing-rack` (24 local inputs, never measured) and an
unknown model to pin that the fallback never reaches the wire.

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


def test_a_compact_release_goes_back_on_its_own_lcl_socket():
    """The case the maintainer named: ch 19 goes back to LCL 19. Both halves of
    the patch, the number the desk shows (19, not the GET's 18)."""
    targets = apply_module.release_write_targets([VOX], console_model="wing-compact")
    assert patch_writes(targets) == {"/ch/19/in/conn/grp": "LCL", "/ch/19/in/conn/in": 19}
    order = [t.address for t in targets]
    assert order.index("/ch/19/in/conn/grp") < order.index("/ch/19/in/conn/in")
    # Where the unpatch used to sit: after the old socket's label and
    # phantom are cleared, before the strip's own name and clink.
    assert order.index("/io/in/A/5/name") < order.index("/ch/19/in/conn/grp")
    assert order.index("/io/in/A/5/vph") < order.index("/ch/19/in/conn/grp")
    assert order.index("/ch/19/in/conn/in") < order.index("/ch/19/clink")


def test_a_claimed_factory_socket_is_left_off():
    claim = {("LCL", 19): "channel 'Horn' on ch:21 in the rebuilt plan"}
    targets = apply_module.release_write_targets(
        [VOX], console_model="wing-compact", claimed_sockets=claim)
    assert patch_writes(targets) == {"/ch/19/in/conn/grp": "OFF"}
    grp = next(t for t in targets if t.address == "/ch/19/in/conn/grp")
    assert "LCL 19" in grp.description and "'Horn'" in grp.description


def test_a_kept_socket_is_a_claim_even_when_the_caller_names_no_claims():
    """The absent case of the guard above: a caller passing only
    `keep_sockets` (as every caller did before this change) must still
    never be handed a double patch."""
    targets = apply_module.release_write_targets(
        [VOX], console_model="wing-compact", keep_sockets={("LCL", 19)})
    assert patch_writes(targets) == {"/ch/19/in/conn/grp": "OFF"}


@pytest.mark.parametrize("model", ["wing-rack", "wing-ultra", None])
def test_an_unmeasured_model_is_left_off_and_never_given_the_identity(model):
    """The trap. `factory_input_patch("wing-rack", "ch", 19)` answers
    LCL 19 -- the identity fallback -- and a write must not use it.
    `None` is the absent case: no model passed at all."""
    assert facts.factory_input_patch(model, "ch", 19) == ("LCL", 19)  # the fallback exists
    kwargs = {} if model is None else {"console_model": model}
    targets = apply_module.release_write_targets([VOX], **kwargs)
    assert patch_writes(targets) == {"/ch/19/in/conn/grp": "OFF"}
    assert not [t for t in targets if t.compute_value(None) == "LCL"]


def test_a_full_size_channel_past_its_local_inputs_goes_off():
    """Measured: a full-size WING has 8 local inputs and ships ch 9-40
    unpatched. The identity fallback would have written LCL 19 -- a socket
    that does not exist on that panel."""
    targets = apply_module.release_write_targets([VOX], console_model="wing-full")
    assert patch_writes(targets) == {"/ch/19/in/conn/grp": "OFF"}
    socket, why = apply_module.release_patch_decision(VOX, console_model="wing-full")
    assert socket is None and "unpatched from the factory" in why


def test_a_full_size_channel_inside_its_local_inputs_is_restored():
    vox5 = channel(5, "Lead Vox", "A", 5)
    targets = apply_module.release_write_targets([vox5], console_model="wing-full")
    assert patch_writes(targets, "/ch/5") == {"/ch/5/in/conn/grp": "LCL", "/ch/5/in/conn/in": 5}


def test_a_strip_the_factory_leaves_unpatched_goes_off():
    """Ch 25-40 on a Compact are OFF from the factory, so OFF is their
    factory patch -- and the reason says so."""
    ch30 = channel(30, "Horn", "A", 30)
    targets = apply_module.release_write_targets([ch30], console_model="wing-compact")
    assert patch_writes(targets, "/ch/30") == {"/ch/30/in/conn/grp": "OFF"}
    _, why = apply_module.release_patch_decision(ch30, console_model="wing-compact")
    assert "leaves ch:30 unpatched from the factory" in why


def test_a_compact_media_aux_goes_back_on_its_player():
    aux1 = channel(1, "Walk-in", "A", 40, bank="aux")
    targets = apply_module.release_write_targets([aux1], console_model="wing-compact")
    assert patch_writes(targets, "/aux/1") == {"/aux/1/in/conn/grp": "USB",
                                               "/aux/1/in/conn/in": 1}


def test_a_measured_socket_the_panel_lacks_is_never_written(monkeypatch):
    """The panel check behind the measured table: a measured row naming a
    socket `CONSOLE_MODELS` says is not there (a transcription slip) goes
    OFF rather than onto the wire."""
    monkeypatch.setitem(facts.FACTORY_INPUT_PATCHES, "wing-full",
                        {"ch": {19: ("LCL", 19)}, "aux": {}, "bus": {}})
    targets = apply_module.release_write_targets([VOX], console_model="wing-full")
    assert patch_writes(targets) == {"/ch/19/in/conn/grp": "OFF"}


# --------------------------------------------------------------------------
# Through the amend engine: the claims, the INFO, the model
# --------------------------------------------------------------------------


def test_amend_restores_the_factory_patch_and_says_so():
    applied = plan([KICK, VOX])
    amendment = release(applied, plan([KICK]), desk(applied))
    assert amendment.released == ["ch:19"]
    assert patch_writes(amendment_targets(amendment).releases) == {
        "/ch/19/in/conn/grp": "LCL", "/ch/19/in/conn/in": 19}
    info = release_info(amendment)
    assert "patched back to LCL 19" in info and "WING Compact" in info


def test_amend_leaves_it_off_when_the_rebuilt_plan_uses_the_socket():
    """The maintainer's own example: the rebuild now uses LCL 19 for something
    else, so ch 19 stays OFF and the INFO names the socket and what took
    it."""
    applied = plan([KICK, VOX])
    rebuilt = plan([KICK, channel(21, "Podium Mic", "LCL", 19)])
    amendment = release(applied, rebuilt, desk(applied))
    assert kinds(amendment, ChangeKind.ADDED) and amendment.released == ["ch:19"]
    targets = amendment_targets(amendment)
    assert patch_writes(targets.releases) == {"/ch/19/in/conn/grp": "OFF"}
    info = release_info(amendment)
    assert "LCL 19" in info and "'Podium Mic'" in info and "OFF" in info


def test_amend_leaves_it_off_when_the_desk_has_something_else_on_the_socket():
    """A strip in neither plan -- somebody else's -- patched to LCL 19.
    The kept plan cannot see it; the occupancy read can."""
    applied = plan([KICK, VOX])
    state = desk(applied, extra={"/ch/30/in/conn/grp": "LCL", "/ch/30/in/conn/in": 19,
                                 "/io/in/LCL/19/name": "Podium"})
    amendment = release(applied, plan([KICK]), state)
    assert {s for s in amendment.released} == {"ch:19"}
    assert patch_writes(amendment_targets(amendment).releases) == {"/ch/19/in/conn/grp": "OFF"}
    assert "ch:30" in release_info(amendment)


def test_a_strip_being_released_does_not_claim_its_own_old_socket():
    """Two strips released in one run, one of them sitting on the other's
    factory socket: both are vacating, so neither blocks the other."""
    applied = plan([KICK, VOX, channel(3, "BV", "LCL", 19)])
    amendment = release(applied, plan([KICK]), desk(applied))
    assert sorted(amendment.released) == ["ch:19", "ch:3"]
    releases = amendment_targets(amendment).releases
    assert patch_writes(releases) == {"/ch/19/in/conn/grp": "LCL", "/ch/19/in/conn/in": 19}
    assert patch_writes(releases, "/ch/3") == {"/ch/3/in/conn/grp": "LCL", "/ch/3/in/conn/in": 3}


def test_amend_on_an_unmeasured_model_leaves_it_off_and_says_why():
    applied = plan([KICK, VOX], model="wing-rack")
    amendment = release(applied, plan([KICK], model="wing-rack"), desk(applied, "wing-rack"))
    assert patch_writes(amendment_targets(amendment).releases) == {"/ch/19/in/conn/grp": "OFF"}
    assert "nobody has measured" in release_info(amendment)


def test_the_model_comes_from_the_plan_when_the_desk_did_not_say():
    """A `--state` file carries no model. The plan's `meta.console_model`
    fills the gap, as it does for the audit."""
    applied = plan([KICK, VOX])
    state = desk(applied, model=None)
    amendment = plan_amendment(applied, plan([KICK]), strip_occupancy(state, applied))
    assert amendment.console_model == "wing-compact"
    assert patch_writes(amendment_targets(amendment).releases)["/ch/19/in/conn/grp"] == "LCL"


def test_the_desk_s_model_beats_the_plan_s():
    """The plan says Compact, the desk says full-size: ch 19 has no
    factory socket on a Full, so it goes OFF."""
    applied = plan([KICK, VOX])
    amendment = release(applied, plan([KICK]), desk(applied, "wing-full"))
    assert amendment.console_model == "wing-full"
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
    applied plan. It is back on LCL 19 and it is FREE.

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
    assert status.patch == ("LCL", 19)
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
    """`atoo amend --console`: the desk says it is a full-size WING
    on its `/?` reply, the plans say Compact. The desk wins, so ch 19 --
    which a Full ships unpatched -- goes OFF, and the INFO says why. If the
    command dropped the desk's answer on the floor, the plan's Compact
    would put ch 19 back on LCL 19: a socket a Full does not have."""
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
    assert "WING (full-size console) leaves ch:19 unpatched from the factory" in out
    assert "/ch/19/in/conn/in" not in out
    assert console.set_param_calls == [] and console.set_node_calls == []
