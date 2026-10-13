"""An earlier change, slices 2 and 3: a plan states a channel's ALTERNATE input
patch (`alt_patch`), `verify` checks it, `apply` writes it, and every
strip `apply` builds is put back on its main input. Plus C005, the
console's global alternate switch, read and never written.

Offline throughout: plans built in the test from `tests/fixtures/`, fake
consoles, and (for the evidence the direction rests on) the read-only
captures under `examples/console-runs/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import console_facts as facts
from atoo import plan_schema, schema_check
from atoo.apply import (
    _build_write_targets,
    apply_plan,
    plan_expansion_bay_use,
    release_write_targets,
    sockets_missing_on_model,
    unfitted_bays_the_plan_needs,
)
from atoo.audit import ConsoleState, DEFAULT_RULES, console_read_plan, run_audit
from atoo.undo import load_journal, undo_from_journal
from atoo.verify_plan import verify_plan
from tests.test_apply import compiled
from tests.test_reply_expand import ROWS, _build, _ch, _leave_out, _reply
from tests.test_undo import DeskConsole, raw

RUNS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "console-runs"


def _plan_with_alts(**alts) -> dict:
    """smallband's compiled plan, with `alt_patch` set on the channels
    named (keyword = channel name with spaces as underscores)."""
    plan = compiled("smallband")
    plan["meta"] = {"console_model": "wing-compact"}
    for ch in plan["channels"]:
        key = ch["name"].replace(" ", "_")
        if key in alts:
            ch["alt_patch"] = alts[key]
    return plan


def _crd(*sockets, stated=True) -> dict:
    return {"group": "CRD", "sockets": list(sockets), "stated": stated}


def _codes(result, severity=None) -> list[str]:
    return [f.code for f in result.findings
            if severity is None or f.severity == severity]


# ---------------------------------------------------------------------------
# the vocabulary: console facts, plan schema, prompt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model", sorted(facts.CONSOLE_MODELS))
def test_every_model_knows_crd_as_an_input_group(model):
    """WING LIVE tracks are `CRD n`, and every WING has the card slot."""
    assert facts.input_socket_limit("CRD", model) == 64


def test_the_plan_schema_takes_an_alternate_and_refuses_a_bad_one():
    kick = _plan_with_alts(Kick=_crd(1))["channels"][0]
    schema = plan_schema.CHANNEL_SCHEMA
    assert not schema_check.validate(kick, schema)
    kick["alt_patch"] = None
    assert not schema_check.validate(kick, schema)
    kick["alt_patch"] = {"group": "CRD", "sockets": [1]}   # no `stated`
    assert schema_check.validate(kick, schema)
    kick["alt_patch"] = {"group": "SD", "sockets": [1], "stated": True}
    assert schema_check.validate(kick, schema)


def test_the_compact_reply_schema_carries_it_and_can_still_be_sent():
    props = plan_schema.REPLY_CHANNEL_SCHEMA["properties"]
    assert props["alt_patch"]["required"] == ["group"]
    assert "alt_patch" in plan_schema.PROVENANCE_KEYS
    assert schema_check.anthropic_schema(plan_schema.REPLY_SCHEMA) is not None


@pytest.mark.parametrize("compact", [True, False])
def test_the_prompt_says_to_state_an_alternate_only_when_the_conventions_do(compact):
    text = plan_schema.schema_section(compact=compact)
    start = text.index("  alt_patch")
    line = " ".join(text[start:].split("\n")[:2]).split()
    line = " ".join(line)
    assert "ONLY when the" in line and "conventions state" in line and "CRD" in line


# ---------------------------------------------------------------------------
# a compact reply expands it
# ---------------------------------------------------------------------------

def test_a_counted_alternate_skips_main_sockets_and_is_announced():
    findings: list = []
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"}, "alt_patch": {"group": "LCL"}},
                         {"input": "Snare", "patch": {"group": "LCL"}, "alt_patch": {"group": "CRD"}},
                         {"input": "Keys L", "pair": "Keys R", "name": "Keys",
                          "patch": {"group": "LCL"}, "alt_patch": {"group": "CRD"}},
                         unassigned_inputs=_leave_out("Bass", "Playback",
                                                      "A Very Long Vocalist Name")),
                  ROWS, findings)
    # LCL 1-4 are the main patches (and LCL 9 is stated for Bass on the
    # list, so it is never counted either): Kick's alternate is the first
    # LCL no main patch uses.
    assert _ch(plan, "Kick")["alt_patch"] == {"group": "LCL", "sockets": [5], "stated": False}
    assert _ch(plan, "Snare")["alt_patch"] == {"group": "CRD", "sockets": [1], "stated": False}
    # A stereo channel's alternate is a pair, starting on an odd socket.
    assert _ch(plan, "Keys")["alt_patch"] == {"group": "CRD", "sockets": [3, 4], "stated": False}
    assert list(_ch(plan, "Keys"))[5:7] == ["patch", "alt_patch"]
    info = [f.message for f in findings if f.code == "reply.alt-sockets-chosen"]
    assert any("Snare CRD 1, Keys CRD 3-4" in m for m in info)
    assert _ch(plan, "Snare")["provenance"]["alt_patch"].startswith("next CRD socket")


def test_a_counted_alternate_never_takes_a_socket_the_input_list_states():
    """Review 2026-09-28, R3/R18. FR-1.10: a socket the input list states
    is cabled, so it is never handed out -- the alternate count included.
    `Spare` is cabled into LCL 2 and left unassigned; Kick's counted
    alternate used to land on it, so switching Kick to its alternate at
    the desk played the spare mic."""
    rows = ("patch,name,category,type,model,phantom,notes\n"
            "LCL 1,Kick,drums,Mic,Beta 52,FALSE,\n"
            "LCL 2,Spare,misc,Mic,SM58,FALSE,\n")
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"},
                          "alt_patch": {"group": "LCL"}},
                         unassigned_inputs=["Spare"]), rows)
    kick = _ch(plan, "Kick")
    assert kick["patch"]["sockets"] == [1]
    assert kick["alt_patch"] == {"group": "LCL", "sockets": [3], "stated": False}
    assert "input list" in kick["provenance"]["alt_patch"]


def test_sockets_the_reply_names_are_the_conventions_and_stated():
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"},
                          "alt_patch": {"group": "CRD", "sockets": [17]},
                          "provenance": {"alt_patch": "Instructions: 'kick plays back from CRD 17'"}}),
                  ROWS)
    kick = _ch(plan, "Kick")
    assert kick["alt_patch"] == {"group": "CRD", "sockets": [17], "stated": True}
    assert kick["provenance"]["alt_patch"] == "Instructions: 'kick plays back from CRD 17'"


def test_no_alternate_is_ever_invented():
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"}}), ROWS)
    assert "alt_patch" not in _ch(plan, "Kick")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def test_a_plain_alternate_verifies_with_only_the_bay_warning():
    result = verify_plan(_plan_with_alts(Kick=_crd(1), Snare=_crd(2)), console_model="wing-compact")
    assert not [c for c in _codes(result, "error") if c.startswith("alt-patch")]
    assert not [c for c in _codes(result) if c.startswith("alt-patch")]
    # A CRD alternate is a card-bay patch like any other.
    bay = next(f for f in result.findings if f.code == "patch.expansion-bay-not-checked")
    assert "CRD (expansion card), 2 time(s)" in bay.message


@pytest.mark.parametrize("alt, code", [
    (_crd(65), "alt-patch.socket-out-of-range"),
    ({"group": "SD", "sockets": [1], "stated": True}, "alt-patch.unknown-group"),
    ({"group": "LCL", "sockets": [25], "stated": True}, "alt-patch.socket-out-of-range"),
    (_crd(1, 2), "alt-patch.mono-socket-count"),
    ({"group": "CRD", "sockets": [], "stated": True}, "alt-patch.no-sockets"),
])
def test_an_alternate_the_desk_cannot_take_is_an_error(alt, code):
    result = verify_plan(_plan_with_alts(Kick=alt), console_model="wing-compact")
    assert code in _codes(result, "error")


def test_a_stereo_alternate_must_be_an_odd_even_pair():
    plan = _plan_with_alts(Keys=_crd(2, 3))
    keys = next(c for c in plan["channels"] if c["name"] == "Keys")
    keys["source"]["stereo"] = True
    keys["patch"]["sockets"] = [5, 6]
    assert "alt-patch.stereo-pair-not-odd-even" in _codes(
        verify_plan(plan, console_model="wing-compact"), "error")


def test_sharing_a_socket_warns_and_a_width_clash_is_an_error():
    # Kick's alternate is Snare's main socket: a strip on its alternate
    # hears Snare. Legal, said.
    result = verify_plan(_plan_with_alts(Kick={"group": "LCL", "sockets": [2], "stated": True}),
                         console_model="wing-compact")
    assert "alt-patch.socket-shared" in _codes(result, "warning")
    assert not [c for c in _codes(result, "error") if c.startswith("alt-patch")]
    # A stereo alternate over a mono main socket: the socket's width is
    # one setting, and apply would write both.
    plan = _plan_with_alts(Keys={"group": "LCL", "sockets": [1, 2], "stated": True})
    keys = next(c for c in plan["channels"] if c["name"] == "Keys")
    keys["source"]["stereo"], keys["patch"]["sockets"] = True, [11, 12]
    assert "alt-patch.socket-width-conflict" in _codes(
        verify_plan(plan, console_model="wing-compact"), "error")


def test_an_alternate_equal_to_the_main_patch_warns():
    result = verify_plan(_plan_with_alts(Kick={"group": "LCL", "sockets": [1], "stated": True}),
                         console_model="wing-compact")
    assert "alt-patch.same-as-main" in _codes(result, "warning")


# ---------------------------------------------------------------------------
# apply: what it writes
# ---------------------------------------------------------------------------

def _targets(plan: dict) -> dict:
    targets, _warnings = _build_write_targets(plan, set_fader_levels=False)
    return {t.address: t for t in targets}


def test_a_stated_alternate_is_written_and_nothing_global_ever_is():
    targets = _targets(_plan_with_alts(Kick=_crd(1)))
    assert targets["/ch/1/in/conn/altgrp"].compute_value(None) == "CRD"
    assert targets["/ch/1/in/conn/altin"].compute_value(None) == 1
    assert targets["/io/in/CRD/1/mode"].compute_value(None) == "M"
    # Every strip it builds goes back to its main input -- with or without
    # an alternate of its own.
    for ch in compiled("smallband")["channels"]:
        assert targets[f"/ch/{ch['channel']}/in/set/altsrc"].compute_value(None) == facts.ALT_PATCH_MAIN == 0
    # The words docs/user/applying.md quotes.
    assert targets["/ch/1/in/set/altsrc"].description == \
        "ch 1 (Kick): listening to its main input, not its alternate"
    assert not [a for a in targets if a.startswith("/io/altsw")]
    # A channel with no stated alternate leaves the desk's own alone.
    assert "/ch/2/in/conn/altgrp" not in targets and "/ch/2/in/conn/altin" not in targets


def test_a_stereo_alternate_sets_both_sockets_wide():
    plan = _plan_with_alts(Keys=_crd(5, 6))
    keys = next(c for c in plan["channels"] if c["name"] == "Keys")
    keys["source"]["stereo"], keys["patch"]["sockets"] = True, [11, 12]
    targets = _targets(plan)
    assert targets["/io/in/CRD/5/mode"].compute_value(None) == "ST"
    assert targets["/io/in/CRD/6/mode"].compute_value(None) == "ST"
    assert targets["/ch/6/in/conn/altin"].compute_value(None) == 5


def test_an_empty_bay_under_an_alternate_is_refused_like_a_main_patch():
    use = plan_expansion_bay_use(_plan_with_alts(Kick=_crd(1)))
    assert use == {"CRD": ["channel 'Kick''s alternate from CRD 1"]}
    assert unfitted_bays_the_plan_needs(use, {"CRD": "NONE"}) == use
    assert unfitted_bays_the_plan_needs(use, {"CRD": "WLIVE"}) == {}


def test_an_alternate_the_desk_model_lacks_is_named():
    plan = _plan_with_alts(Kick={"group": "LCL", "sockets": [20], "stated": True})
    assert any("channel 'Kick''s alternate" in line
               for line in sockets_missing_on_model(plan, "wing-full"))


def test_returning_a_strip_to_free_clears_the_alternate_it_had():
    plan = _plan_with_alts(Kick=_crd(1))
    kick, snare = plan["channels"][0], plan["channels"][1]
    released = {t.address: t for t in release_write_targets([kick, snare],
                                                            console_model="wing-compact")}
    assert released["/ch/1/in/conn/altgrp"].compute_value(None) == "OFF"
    assert "/ch/2/in/conn/altgrp" not in released


def test_an_alternate_lands_verifies_through_the_offset_and_undoes(tmp_path):
    """The whole round trip against a desk that answers `.altin` one low,
    as `in/conn/in` does (the inferred offset): written, read back as a
    match, journalled, and reversed by undo to exactly what was there."""
    plan = _plan_with_alts(Kick=_crd(3))
    console = DeskConsole({
        "/ch/1/in/conn/altgrp": ("OFF", "s"),
        "/ch/1/in/conn/altin": (raw("/ch/1/in/conn/altin", 1), "i"),
        "/ch/1/in/set/altsrc": (1, "i"),        # left on alternate after a virtual soundcheck
        "/ch/2/in/set/altsrc": (0, "i"),
    })
    journal = tmp_path / "apply.json"
    result = apply_plan(plan, console, dry_run=False, journal_path=str(journal),
                        set_fader_levels=False)
    by_address = {w.address: w for w in result.writes}
    for address, want in (("/ch/1/in/conn/altgrp", "CRD"), ("/ch/1/in/conn/altin", 3),
                          ("/ch/1/in/set/altsrc", 0)):
        assert by_address[address].status == "match", address
        assert by_address[address].readback_value == want
    assert console.state["/ch/1/in/conn/altin"] == (2, "i")     # the wire value, one low
    assert by_address["/ch/2/in/set/altsrc"].status == "skipped_no_change"

    undo_from_journal(load_journal(str(journal)), console, dry_run=False)
    assert console.state["/ch/1/in/conn/altgrp"] == ("OFF", "s")
    assert console.state["/ch/1/in/conn/altin"] == (0, "i")     # socket 1, as the desk had it
    assert console.state["/ch/1/in/set/altsrc"] == (1, "i")


# ---------------------------------------------------------------------------
# the evidence the direction rests on (read-only captures)
# ---------------------------------------------------------------------------

def _snap_strips(path: Path) -> list[dict]:
    ae = json.loads(path.read_text())["ae_data"]
    return [strip["in"] for bank in ("ch", "aux") for strip in ae[bank].values() if "in" in strip]


def test_altsrc_zero_is_main_on_every_desk_on_file():
    """Why apply may write `altsrc = 0`: a factory desk has no alternate
    at all and reads 0; two show desks with 36 alternates set up for
    virtual soundcheck read 0 on every strip; the one strip deliberately
    put on its alternate (A7) reads 1."""
    factory = _snap_strips(RUNS / "Initialized-Compact.snap")
    assert all(s["conn"]["altgrp"] == "OFF" and not s["set"]["altsrc"] for s in factory)
    for show in ("Church-Full.snap", "2026-09-23-1921/A17-wing-full.snap"):
        strips = _snap_strips(RUNS / show)
        assert sum(s["conn"]["altgrp"] in ("USB", "CRD") for s in strips) == 36
        assert not any(s["set"]["altsrc"] for s in strips)
    a7 = _snap_strips(RUNS / "2026-09-21" / "A7-ch1-with-WLIVE-alt.snap")
    assert a7[0]["conn"]["altgrp"] == "CRD" and a7[0]["set"]["altsrc"] is True


# ---------------------------------------------------------------------------
# C005: the global switch, read and reported, never written
# ---------------------------------------------------------------------------

def _sp_c005(values: dict) -> list:
    rule = next(r for r in DEFAULT_RULES if r.id == "C005")
    return run_audit(ConsoleState(values), rules=[rule])


def test_the_global_switch_engaged_is_one_finding_for_the_whole_desk():
    values = {"/io/altsw": 1}
    for n in range(1, 41):
        values[f"/ch/{n}/in/conn/grp"], values[f"/ch/{n}/in/conn/in"] = "LCL", n % 24 + 1
    findings = _sp_c005(values)
    assert len(findings) == 1
    assert findings[0].severity.name == "WARNING"
    assert findings[0].addresses == ("/io/altsw",)
    assert "inferred" in findings[0].message


@pytest.mark.parametrize("values", [{"/io/altsw": 0}, {}])
def test_the_global_switch_off_or_unread_is_silent(values):
    assert _sp_c005(values) == []


def test_a_read_asks_for_the_global_switch_once():
    assert [a for a, _ in console_read_plan() if a == facts.GLOBAL_ALT_SWITCH] == ["/io/altsw"]


# ---------------------------------------------------------------------------
# the Setup page shows it
# ---------------------------------------------------------------------------

def test_the_setup_page_shows_a_stated_alternate():
    """The Python suite cannot see the page; this asserts the served
    asset reads the field under the name the plan writes."""
    from conftest import require_fastapi_testclient
    TestClient = require_fastapi_testclient().TestClient
    from atoo.webui import create_app

    with TestClient(create_app()) as client:
        js = client.get("/static/setup.js").text
    assert 'ch.alt_patch ? ["Alternate", esc(patchDesc(ch.alt_patch))] : null' in js


def test_an_alternate_added_in_a_rebuild_is_a_change_amend_sees():
    """`apply` turns `alt_patch` into writes, so a rebuild that adds or
    moves one is a MODIFIED channel, not an unchanged one."""
    from atoo.amend import _channel_differs

    before = compiled("smallband")["channels"][0]
    after = copy.deepcopy(before)
    assert not _channel_differs(before, after)
    after["alt_patch"] = _crd(1)
    assert _channel_differs(before, after)
