import copy
import json
from pathlib import Path

from atoo.render import render_plan

FIXTURES = Path(__file__).parent / "fixtures"

# These tests used to compile a plan on the spot to have something to
# render. The deterministic compile path was retired, so the exact
# plans (and the warning lists that went with them) are checked in --
# generated from the compiler at `origin/main` immediately before deletion,
# so every assertion here is still made against the same bytes. `render.py`
# does not care how a plan was produced.
_COMPILED = json.loads((FIXTURES / "compiled_plans.json").read_text())


class _Compiled:
    """Just enough of the old CompileResult for these tests to keep reading
    `result.plan` / `result.warnings`."""

    def __init__(self, case: str):
        self.plan = copy.deepcopy(_COMPILED[case]["plan"])
        self.warnings = list(_COMPILED[case]["warnings"])


def _compile_smallband():
    return _Compiled("smallband")


def test_render_includes_every_channel_name():
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    for ch in result.plan["channels"]:
        assert ch["name"] in text


def test_render_shows_bus_send_mode_and_level():
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    assert "Drums (post, 0.0dB)" in text
    assert "Monitor 1 (pre, 0.0dB)" in text


def test_render_shows_bus_destinations():
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    assert '-> Dedicated output "Drum wedge", LCL 3-4' in text
    assert "-> Main" in text
    assert "(unresolved)" in text  # FX


def test_render_shows_channel_patch():
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    bass = next(c for c in result.plan["channels"] if c["name"] == "Bass")
    assert bass["patch"]["stated"] is True
    assert "Patch: LCL 9" in text
    kick = next(c for c in result.plan["channels"] if c["name"] == "Kick")
    assert kick["patch"]["stated"] is False
    assert "Patch: LCL 1 (auto)" in text


def test_render_shows_output_sockets():
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    assert "OUTPUTS" in text
    assert "Main" in text and "LCL 1-2" in text
    assert "patch?" in text  # Matrix has none stated


def test_render_shows_warning_count_and_text():
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    assert f"NOTES ({len(result.warnings)})" in text
    for w in result.warnings:
        assert w in text


def test_render_no_warnings_says_so():
    text = render_plan({"channels": [], "busses": {}}, [])
    assert "No notes." in text


def test_render_names_the_texts_from_the_plans_meta():
    """`build --pretty` crashed (KeyError: 'conventions_file') on every
    plan built since the conventions became a stack in `meta`."""
    plan = {"channels": [], "busses": {}, "meta": {
        "conventions_stack": [{"path": "house.md", "role": "conventions"},
                              {"path": "show/instructions.md", "role": "instructions"}],
        "input_list": {"path": "show/input.csv"}}}
    text = render_plan(plan, [])
    assert "  conventions: house.md, show/instructions.md" in text
    assert "  input list:  show/input.csv" in text


def test_render_shows_a_direct_to_main_channel_route():
    result = _Compiled("host_main2")
    rendered = render_plan(result.plan, result.warnings)
    assert "Direct route: -> Main 2" in rendered


def test_render_shows_channel_color_when_stated():
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    plan["channels"][0]["color"] = "Red"
    text = render_plan(plan, result.warnings)
    assert "[Red]" in text


def test_render_omits_color_bracket_when_not_stated():
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    assert "[" not in text.split("BUSSES")[0]  # no channel line carries a bracket


def test_render_shows_bus_dca_and_mute_group_membership():
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    plan["busses"]["FX"]["dca"] = ["FX"]
    plan["busses"]["FX"]["mute_group"] = ["Vocals"]
    text = render_plan(plan, result.warnings)
    assert "DCA: FX" in text
    assert "Mute group: Vocals" in text


def test_render_flags_an_unsupported_matrix_bus_destination():
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    plan["busses"]["FX"]["destination"] = {"type": "matrix", "index": 1}
    text = render_plan(plan, result.warnings)
    assert "-> Matrix (wrong field -- state this on the matrix's own outputs[].fed_by instead)" in text


def test_render_shows_what_feeds_a_matrix():
    # Smallband.md's Matrix is "fed from Main".
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    assert "Fed by: Main 1" in text


def test_render_shows_a_matrix_fed_by_a_bus():
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    plan["outputs"]["Matrix"]["fed_by"] = {"type": "bus", "name": "Drums"}
    text = render_plan(plan, result.warnings)
    assert "Fed by: bus Drums" in text


def test_render_shows_a_bus_routing_to_main_and_a_dedicated_output_at_once():
    # An earlier change, Festival_STANDALONE.snap's real finding.
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    plan["busses"]["Drums"]["destinations"] = [
        {"type": "main", "index": 1},
        {"type": "dedicated_output", "label": "IEM tap",
         "socket": {"group": "LCL", "sockets": [21]}, "sockets": [{"group": "LCL", "sockets": [21]}]},
    ]
    text = render_plan(plan, result.warnings)
    assert '-> Main + -> Dedicated output "IEM tap", LCL 21' in text


def test_render_shows_an_output_fanning_out_to_several_sockets():
    # An earlier change, TOURING_260821_MIX.snap's real finding.
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    plan["outputs"]["Main"]["sockets"] = [
        {"group": "USB", "sockets": [47, 48]},
        {"group": "SC", "sockets": [31, 32]},
    ]
    text = render_plan(plan, result.warnings)
    assert "USB 47-48 + SC 31-32" in text


# ---------------------------------------------------------------------------
# hi-cut, tilt, trim, balance, invert, head-amp gain in
# `_processing_desc()`.
# ---------------------------------------------------------------------------


def test_render_shows_the_new_processing_fields_when_present():
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    kick["processing"].update(
        hi_cut_hz=8000.0, tilt_db=-2.5, trim_db=6.0, balance_db=-3.0,
        invert=True, gain_db=30.0,
    )
    text = render_plan(plan, result.warnings)
    assert "Hi-cut 8000.0Hz" in text
    assert "Tilt -2.5dB" in text
    assert "Trim 6.0dB" in text
    assert "Balance -3.0dB" in text
    assert "Inverted" in text
    assert "Gain 30.0dB" in text


def test_render_omits_inverted_when_false_or_absent():
    """Same rule as `_source_desc`'s stereo/phantom tags -- present only
    when true, never printed as "not inverted"."""
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    kick["processing"]["invert"] = False
    text = render_plan(plan, result.warnings)
    assert "Inverted" not in text


def test_render_unchanged_for_a_plan_that_uses_none_of_the_new_fields():
    """The smallband fixture never states any of the six new fields --
    rendering must be byte-identical to what it was before this issue."""
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    for label in ("Hi-cut", "Tilt", "Trim", "Balance", "Inverted", "Gain "):
        assert label not in text


# ---------------------------------------------------------------------------
# the EQ, on a channel and on the strips that had no
# `processing` field at all before it.
# ---------------------------------------------------------------------------


def test_render_shows_a_channels_eq_bands():
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    kick["processing"]["eq"] = {
        "model": "SOUL",
        "bands": [{"band": "low", "freq_hz": 120, "gain_db": -3, "shape": "SHV"},
                  {"band": "2", "freq_hz": 2500, "gain_db": 2.5, "q": 1.4}],
    }
    text = render_plan(plan, result.warnings)
    assert "EQ [low 120Hz -3dB SHV; 2 2500Hz +2.5dB Q1.4; SOUL]" in text


def test_render_marks_an_eq_the_plan_asks_to_start_bypassed():
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    kick["processing"]["eq"] = {"on": False, "bands": [{"band": "1", "gain_db": -2}]}
    assert "EQ (off) [1 -2dB]" in render_plan(plan, result.warnings)


def test_render_shows_a_bus_and_an_output_processing_line():
    result = _compile_smallband()
    plan = json.loads(json.dumps(result.plan))
    bus_name = next(iter(plan["busses"]))
    plan["busses"][bus_name]["processing"] = {
        "eq": {"bands": [{"band": "6", "freq_hz": 12000, "gain_db": -2}]}, "tilt_db": -1.5,
    }
    out_name = next(iter(plan["outputs"]))
    plan["outputs"][out_name]["processing"] = {"eq": {"bands": [{"band": "low", "shape": "LR24"}]}}
    text = render_plan(plan, result.warnings)
    assert "Processing: Tilt -1.5dB, EQ [6 12000Hz -2dB]" in text
    assert "Processing: EQ [low LR24]" in text


def test_render_unchanged_for_a_plan_that_states_no_eq():
    result = _compile_smallband()
    text = render_plan(result.plan, result.warnings)
    assert "EQ" not in text
    assert "Processing:" not in text
