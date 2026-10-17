"""'socket' becomes 'patch' where it means the connection.

The maintainer's vocabulary, 2026-09-28: a **socket** is the physical input or
output on the desk; a **patch** is the connection between a channel or
bus and a socket. So an output's plan entry is `patch`/`patches` (was
`socket`/`sockets`), the input list's column is `patch` (was `socket`),
and `output.no-socket` is `output.no-patch`.

Every plan and input list written before then is still on disk, so the
point of most of these is that the OLD spelling reads exactly the same
as the new one -- verify, apply, render and the page -- through the one
reader that knows both (`atoo/plan_compat.py`).

The plans here are built from `tests/fixtures/`, never from a bundle
under `examples/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import plan_compat
from atoo.ai_provider import FakeProvider
from atoo.apply import apply_plan
from atoo.generate import generate_plan
from atoo.plan_schema import GENERATION_SCHEMA, OUTPUT_SCHEMA
from atoo.render import render_plan
from atoo.verify_plan import verify_plan

from test_apply import FakeConsole

FIXTURES = Path(__file__).parent / "fixtures"


def _old_plan() -> dict:
    """A plan spelled the way every plan before an earlier change is: an output's
    patch under `socket`, its fan-out under `sockets`, and a bus's
    dedicated output under `destination.socket`."""
    plan = json.loads((FIXTURES / "touringband.plan.json").read_text())
    plan["outputs"]["Matrix"]["socket"] = {"group": "LCL", "sockets": [7, 8], "stated": True}
    plan["busses"]["Drums"]["destination"] = {
        "type": "dedicated_output", "label": "Drum fill",
        "socket": {"group": "LCL", "sockets": [1], "stated": True}}
    plan["busses"]["Drums"].pop("destinations", None)
    return plan


def _codes(result) -> list:
    return sorted((f.code, f.where) for f in result.findings)


# ---- the one reader ------------------------------------------------------


def test_the_fixture_really_is_spelled_the_old_way():
    old = _old_plan()
    assert "socket" in old["outputs"]["Main"] and "sockets" in old["outputs"]["Main"]
    assert "patch" not in old["outputs"]["Main"]
    assert "socket" in old["busses"]["Drums"]["destination"]


def test_normalise_renames_old_keys_and_never_mutates_its_input():
    old = _old_plan()
    before = copy.deepcopy(old)
    new = plan_compat.normalise_plan(old)
    assert old == before
    main = new["outputs"]["Main"]
    assert main["patch"] == {"group": "USB", "sockets": [47, 48]}
    assert main["patches"] == [{"group": "USB", "sockets": [47, 48]}]
    assert "socket" not in main and "sockets" not in main
    assert new["busses"]["Drums"]["destination"]["patch"]["sockets"] == [1]
    # A patch's own `sockets` -- the physical sockets it lands on -- keep
    # their name.
    assert new["outputs"]["Matrix"]["patch"]["sockets"] == [7, 8]
    # A plan already spelled the new way comes back as it is.
    assert plan_compat.normalise_plan(new) == new


def test_a_bus_destinations_list_is_read_too():
    bus = {"destinations": [{"type": "main", "index": 1},
                            {"type": "dedicated_output", "socket": {"group": "LCL", "sockets": [3]}}]}
    new = plan_compat.normalise_plan({"busses": {"B": bus}})
    assert new["busses"]["B"]["destinations"][1]["patch"] == {"group": "LCL", "sockets": [3]}


def test_the_new_key_wins_when_both_are_present():
    entry = {"patch": {"group": "LCL", "sockets": [2]}, "socket": {"group": "LCL", "sockets": [9]}}
    assert plan_compat.output_patch(entry) == {"group": "LCL", "sockets": [2]}
    assert plan_compat.output_patches(entry) == [{"group": "LCL", "sockets": [2]}]


@pytest.mark.parametrize("entry,expected", [
    ({"patches": [{"group": "A", "sockets": [1]}], "patch": {"group": "B", "sockets": [2]}},
     [{"group": "A", "sockets": [1]}]),
    ({"patches": [], "patch": {"group": "B", "sockets": [2]}}, [{"group": "B", "sockets": [2]}]),
    ({"sockets": [{"group": "A", "sockets": [1]}]}, [{"group": "A", "sockets": [1]}]),
    ({"socket": {"group": "B", "sockets": [2]}}, [{"group": "B", "sockets": [2]}]),
    ({"patch": None}, []),
    ({}, []),
    (None, []),
])
def test_output_patches_reads_the_fan_out_first(entry, expected):
    assert plan_compat.output_patches(entry) == expected


# ---- an old plan still verifies, applies and renders ------------------------


def test_an_old_plan_verifies_exactly_as_its_new_spelling_does():
    old = _old_plan()
    new = plan_compat.normalise_plan(old)
    old_result, new_result = verify_plan(old), verify_plan(new)
    assert not [f for f in old_result.findings if f.code == "schema"]
    assert _codes(old_result) == _codes(new_result)
    # And the socket checks really ran on the old spelling: an output
    # patched past the end of its group is still refused.
    broken = _old_plan()
    broken["outputs"]["Matrix"]["socket"]["sockets"] = [99, 100]
    assert "output.socket-out-of-range" in {f.code for f in verify_plan(broken).findings}


def test_an_old_plan_applies_the_same_routing():
    def writes(plan):
        result = apply_plan(plan, FakeConsole(), dry_run=True)
        return sorted((w.address, w.intended_value) for w in result.writes)

    old = _old_plan()
    old_writes = writes(old)
    assert old_writes == writes(plan_compat.normalise_plan(old))
    routed = dict(old_writes)
    # The Matrix's own patch, the Main's fan-out, and the bus's dedicated
    # output -- all three read from the old keys.
    assert routed["/io/out/LCL/7/grp"] == "MTX" and routed["/io/out/LCL/8/in"] == 2
    assert routed["/io/out/USB/47/grp"] == "MAIN"
    assert routed["/io/out/LCL/1/grp"] == "BUS"


def test_an_old_plan_renders_the_same():
    old = _old_plan()
    text = render_plan(old, [])
    assert text == render_plan(plan_compat.normalise_plan(old), [])
    assert "LCL 7-8" in text and "USB 47-48" in text and "LCL 1" in text


# ---- a new plan says patch --------------------------------------------------


def test_the_schema_asks_for_patch_and_no_longer_knows_socket():
    for schema in (OUTPUT_SCHEMA, GENERATION_SCHEMA["properties"]["outputs"]["additionalProperties"]):
        assert {"patch", "patches"} <= set(schema["properties"])
        assert not {"socket", "sockets"} & set(schema["properties"])


def test_a_generated_plan_is_written_with_patch_even_from_an_old_spelling():
    """A model that reached for the old names meant the same thing: the
    plan it produces is written the new way, never refused for it. The
    reply is a real model run from before the rename."""
    reply = (Path(__file__).parent / "fixtures"
             / "touringband.generated.plan.json").read_text()
    assert '"socket"' in reply
    plan = generate_plan("c", "i", provider=FakeProvider(response=reply),
                         constrain=False, console_model="wing-compact")
    for entry in plan["outputs"].values():
        assert "socket" not in entry and "sockets" not in entry
        assert "patch" in entry
    for bus in plan["busses"].values():
        assert "socket" not in (bus.get("destination") or {})
    assert plan["busses"]["Monitor 1"]["destination"]["patch"]["group"]


# ---- the renamed code -------------------------------------------------------


def test_an_output_with_no_patch_is_output_no_patch():
    plan = plan_compat.normalise_plan(_old_plan())
    plan["outputs"]["Matrix"]["patch"] = None
    result = verify_plan(plan)
    codes = {f.code for f in result.warnings}
    assert "output.no-patch" in codes
    assert "output.no-socket" not in codes | {f.code for f in result.findings}


def test_a_plan_built_before_the_rename_shows_the_new_code_on_the_page():
    from atoo.webui import _plan_findings

    plan = {"meta": {"verify_findings": {"errors": [
        {"severity": "error", "code": "output.no-socket", "where": "outputs[Matrix]",
         "message": "output has no physical socket -- apply has nothing to write"}]}}}
    assert [f["code"] for f in _plan_findings(plan)] == ["output.no-patch"]
