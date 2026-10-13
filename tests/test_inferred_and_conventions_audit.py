"""Decided values and the conventions audit -- the prompt-independent code.

Two things landed together on 2026-09-25:

* `atoo/inferred.py` -- CLAUDE.md's "an error of judgement is not an
  error of patching". A bus width, a send's pre/post, a mix bus's route to
  Main and a stereo pairing are DECIDED where the conventions are silent,
  and each decision announces itself as an INFO. A plan that still arrives
  with a null width or mode is decided by a deterministic fallback, the
  same way everywhere.
* `atoo/conventions_audit.py` -- FR-6.2 folded into the build. The
  generator's `conventions_audit` entries and the critic's `conventions`
  findings must quote the conventions text, and code checks the quotes.

No model is called here. What a model does with the prompt is
`tests/test_prompt_fidelity.py`'s job (opt-in, `live_model`); what the
prompt SAYS is `tests/test_prompts.py`. Every plan below is built in the
test, so nothing depends on a bundle under `examples/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import conventions_audit as ca
from atoo import generate
from atoo import inferred
from atoo.ai_provider import FakeProvider
from atoo.cli import main
from atoo.diagnostics import Diagnostic, Severity
from atoo.plan_schema import GENERATION_SCHEMA, PLAN_SCHEMA
from atoo.schema_check import validate as validate_schema
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).parent / "fixtures"


def _channel(n, name, sends):
    return {
        "channel": n, "bank": "ch", "name": name,
        "source": {"input": name, "stereo": False, "phantom": False},
        "patch": {"group": "LCL", "sockets": [n], "stated": False},
        "processing": {"hpf_hz": None, "preset": None},
        "fader": {"fader_db": None, "muted": None},
        "dca": [], "mute_group": [],
        "bus_sends": [{"bus": b, "mode": m, "level_db": 0.0} for b, m in sends],
        "main_routes": [],
    }


def _plan():
    """Two channels, a wedge on one socket, an IEM pair, a mix bus to Main
    -- every width and mode left unstated."""
    return {
        "channels": [
            _channel(1, "Kick", [("Wedge", None), ("IEM", None), ("Drums", None)]),
            _channel(2, "Snare", [("Wedge", None), ("Drums", "post")]),
        ],
        "dcas": {}, "mute_groups": {},
        "busses": {
            "Wedge": {"destination": {"type": "dedicated_output", "label": "wedge",
                                      "patch": {"group": "LCL", "sockets": [1]}},
                      "index": 1, "mono": None},
            "IEM": {"destination": {"type": "dedicated_output", "label": "iem",
                                    "patch": {"group": "LCL", "sockets": [3, 4]}},
                    "index": 2, "mono": None},
            "Drums": {"destination": {"type": "main", "index": 1}, "index": 3},
        },
        "outputs": {},
        "unassigned_inputs": [], "notes": [],
        "meta": {"console_model": "wing-compact"},
    }


# --------------------------------------------------------------------------
# the fallback rules
# --------------------------------------------------------------------------

def test_one_socket_is_mono_a_pair_is_stereo_no_jack_is_factory_stereo():
    busses = _plan()["busses"]
    assert inferred.bus_width_fallback(busses["Wedge"])[0] is True
    assert inferred.bus_width_fallback(busses["IEM"])[0] is False
    mono, basis = inferred.bus_width_fallback(busses["Drums"])
    assert mono is False and "factory" in basis


def test_a_fan_out_with_any_pair_is_stereo():
    # Spelled the pre-#342 way (`socket`/`sockets`) on purpose: a plan on
    # disk still says it so, and plan_compat reads it the same.
    bus = {"destinations": [
        {"type": "dedicated_output", "socket": {"group": "LCL", "sockets": [1]}},
        {"type": "dedicated_output", "sockets": [{"group": "USB", "sockets": [1, 2]}]}]}
    assert inferred.bus_width_fallback(bus)[0] is False


def test_monitor_sends_are_pre_everything_else_post():
    busses = _plan()["busses"]
    assert inferred.send_mode_fallback("Wedge", busses["Wedge"])[0] == "pre"
    assert inferred.send_mode_fallback("Drums", busses["Drums"])[0] == "post"
    # A bus feeding a jack AND a Main is not a monitor mix.
    both = {"destinations": [{"type": "main", "index": 1},
                             {"type": "dedicated_output",
                              "patch": {"group": "LCL", "sockets": [5]}}]}
    assert inferred.send_mode_fallback("Both", both)[0] == "post"


def test_decide_unstated_fills_and_marks_and_is_idempotent():
    plan = _plan()
    decided = inferred.decide_unstated(plan)
    # three widths, four null modes (Kick x3, Snare x1 -- its other was stated)
    assert decided == 7
    assert plan["busses"]["Wedge"]["mono"] is True
    assert plan["busses"]["IEM"]["mono"] is False
    assert plan["busses"]["Drums"]["mono"] is False
    kick = plan["channels"][0]["bus_sends"]
    assert [s["mode"] for s in kick] == ["pre", "pre", "post"]
    assert kick[0]["inferred"][0]["by"] == "fallback"
    # the stated send is untouched and carries no marker
    assert "inferred" not in plan["channels"][1]["bus_sends"][1]
    assert inferred.decide_unstated(plan) == 0
    assert validate_schema(plan, PLAN_SCHEMA) == []


def test_with_decisions_copies_and_leaves_a_decided_plan_alone():
    plan = _plan()
    decided = inferred.with_decisions(plan)
    assert decided is not plan
    assert plan["busses"]["Wedge"]["mono"] is None
    assert inferred.with_decisions(decided) is decided


def test_a_send_into_an_undeclared_bus_is_left_for_verify_to_report():
    plan = _plan()
    plan["channels"][0]["bus_sends"].append({"bus": "Ghost", "mode": None, "level_db": 0.0})
    inferred.decide_unstated(plan)
    assert plan["channels"][0]["bus_sends"][-1]["mode"] is None


def test_a_stale_marker_is_replaced_not_duplicated():
    plan = _plan()
    plan["busses"]["Wedge"]["inferred"] = [{"field": "mono", "basis": "old", "by": "model"}]
    inferred.decide_unstated(plan)
    markers = plan["busses"]["Wedge"]["inferred"]
    assert len(markers) == 1 and markers[0]["by"] == "fallback"


# --------------------------------------------------------------------------
# markers -> INFO
# --------------------------------------------------------------------------

def _by_code(diags, code):
    return [d for d in diags if d.code == code]


def test_every_decision_is_an_info_naming_object_field_value_and_basis():
    diags = inferred.inferred_diagnostics(_plan())
    assert all(d.severity == Severity.INFO for d in diags)
    widths = {d.where: d.message for d in _by_code(diags, inferred.CODE_BUS_WIDTH)}
    assert set(widths) == {"busses[Wedge]", "busses[IEM]", "busses[Drums]"}
    assert "width set to mono" in widths["busses[Wedge]"]
    assert "single socket (LCL 1)" in widths["busses[Wedge]"]
    assert "fallback" in widths["busses[Wedge]"]


def test_sends_are_reported_once_per_bus_naming_the_channels():
    modes = _by_code(inferred.inferred_diagnostics(_plan()), inferred.CODE_SEND_MODE)
    wedge = [d for d in modes if d.where == "busses[Wedge]"]
    assert len(wedge) == 1
    assert "pre-fader on 2 channel(s) (Kick, Snare)" in wedge[0].message


def test_generator_markers_are_reported_as_the_generators():
    plan = _plan()
    plan["busses"]["Wedge"].update(mono=True, inferred=[
        {"field": "mono", "basis": "named Wedge, one socket", "by": "model"}])
    plan["busses"]["Drums"].update(inferred=[
        {"field": "destination", "basis": "a mix bus", "by": "model"}])
    plan["channels"][0]["source"]["stereo"] = False
    plan["channels"][0]["inferred"] = [{"field": "stereo", "basis": "no L/R in the name"}]
    diags = inferred.inferred_diagnostics(plan)
    [width] = [d for d in _by_code(diags, inferred.CODE_BUS_WIDTH) if d.where == "busses[Wedge]"]
    assert "decided by the generator: named Wedge, one socket" in width.message
    [dest] = _by_code(diags, inferred.CODE_BUS_DESTINATION)
    assert "routed to Main 1" in dest.message
    [stereo] = _by_code(diags, inferred.CODE_CHANNEL_STEREO)
    assert stereo.where == "channels[Kick]" and "kept mono" in stereo.message


def test_a_marker_on_a_hand_nulled_value_gives_way_to_the_fallback():
    plan = _plan()
    plan["busses"]["IEM"]["inferred"] = [{"field": "mono", "basis": "was mono", "by": "model"}]
    [note] = [d for d in _by_code(inferred.inferred_diagnostics(plan), inferred.CODE_BUS_WIDTH)
              if d.where == "busses[IEM]"]
    assert "stereo" in note.message and "fallback" in note.message


def test_verify_never_refuses_an_unstated_width_or_mode():
    result = verify_plan(_plan(), console_model="wing-compact")
    codes = {f.code for f in result.findings}
    assert "bus.unstated-width-for-dedicated-output" not in codes
    assert "value.send-mode-unknown" not in codes
    assert {f.code for f in result.infos} >= {inferred.CODE_BUS_WIDTH, inferred.CODE_SEND_MODE}
    assert "note(s)" in result.report()


# --------------------------------------------------------------------------
# generate_plan: the plan on disk carries the decision
# --------------------------------------------------------------------------

def test_generate_plan_writes_the_decided_values_and_their_markers():
    reply = _plan()
    del reply["meta"]
    # The model decided one width itself and marked it (no `by`)...
    reply["busses"]["IEM"].update(mono=False, inferred=[
        {"field": "mono", "basis": "an in-ear mix on a socket pair"}])
    provider = FakeProvider(response=json.dumps(reply))
    plan = generate.generate_plan("conventions", "name\nKick\nSnare\n",
                                  provider=provider, console_model="wing-compact")
    # ...which is tagged as its own; the ones it left null are the fallback's.
    assert plan["busses"]["IEM"]["inferred"] == [
        {"field": "mono", "basis": "an in-ear mix on a socket pair", "by": "model"}]
    assert plan["busses"]["Wedge"]["mono"] is True
    assert plan["busses"]["Wedge"]["inferred"][0]["by"] == "fallback"
    assert all(s["mode"] is not None for ch in plan["channels"] for s in ch["bus_sends"])
    assert validate_schema(plan, GENERATION_SCHEMA) == []


# --------------------------------------------------------------------------
# conventions_audit: a quote is checked, not believed
# --------------------------------------------------------------------------

HOUSE = """# House
## Busses
- Monitor sends are **pre-fader**.
- Monitor sends are post-fader.
## DCAs
- FX: all FX returns
"""
SHOW = """# Show
## Busses
- MON1 is a stereo in-ear mix.
"""
LAYERS = ca.layers_for(HOUSE, "house.md", SHOW, "instructions.md")


def test_normalise_folds_what_a_model_retypes():
    assert ca.normalise("Monitor  sends are **pre-fader**.") == \
        ca.normalise("monitor sends are pre-fader.")
    assert ca.normalise("“quoted”") == "'quoted'"
    # Double and single quotes are one, and an escape goes: the resolve
    # step quoted `- "INST Reverb" -- ...` as `'INST Reverb' -- ...`.
    assert ca.normalise('"INST Reverb" -- All') == ca.normalise("'INST Reverb' -- All")
    assert ca.normalise('mode: \\"ST\\"') == ca.normalise('mode: "ST"')


def test_locate_reads_an_elision_as_parts_in_order():
    text = "- Color coding: Drums-Red, Bass-Blue, Vocals-Green, Speech-Purple\n"
    layer = [ca.Layer("conventions", "c.md", text)]
    assert ca.locate("Color coding: Drums-Red...Speech-Purple", layer) is not None
    assert ca.locate("Color coding: Speech-Purple...Drums-Red", layer) is None   # out of order


def test_locate_finds_the_section_and_prefers_the_instructions():
    spot = ca.locate("Monitor sends are pre-fader.", LAYERS)
    assert spot == ca.Located("conventions", "Busses")
    assert ca.locate("...MON1 is a stereo in-ear mix", LAYERS) == ca.Located("instructions", "Busses")
    assert ca.locate("Monitor sends are side-fader.", LAYERS) is None


def test_generator_entries_with_real_quotes_become_infos_with_a_section():
    plan = {"conventions_audit": [
        {"kind": "conflict",
         "quotes": ["Monitor sends are pre-fader.", "Monitor sends are post-fader."],
         "message": "followed the first: monitor sends are normally pre"},
        {"kind": "unused", "quotes": ["FX: all FX returns"],
         "message": "no FX returns in this show"},
    ]}
    diags = ca.findings_from_plan(plan, LAYERS)
    assert [d.code for d in diags] == ["conventions.conflict", "conventions.unused"]
    assert all(d.severity == Severity.INFO and d.source == "build" for d in diags)
    assert diags[0].where == "conventions § Busses" and diags[0].category == "Busses"
    assert '"Monitor sends are post-fader."' in diags[0].message
    assert diags[1].category == "DCAs"


def test_a_generator_entry_quoting_text_that_is_not_there_is_kept_untrusted():
    plan = {"conventions_audit": [
        {"kind": "conflict", "quotes": ["Monitor sends are pre-fader.", "Wedges are purple."],
         "message": "picked one"}]}
    [diag] = ca.findings_from_plan(plan, LAYERS)
    assert diag.code == ca.CODE_UNVERIFIED and diag.severity == Severity.INFO
    assert "Wedges are purple." in diag.message and "not trusted" in diag.message


def _critic_reply(severity, quotes):
    return json.dumps({"findings": [{
        "severity": severity, "kind": "conventions", "where": "Busses",
        "message": "the conventions say both pre and post for monitor sends",
        "quotes": quotes}]})


def test_a_critic_conventions_finding_with_real_quotes_keeps_its_severity():
    [f] = generate.parse_critic_findings(
        _critic_reply("warning", ["Monitor sends are post-fader."]), layers=LAYERS)
    assert f.severity == Severity.WARNING and f.code == "critic.conventions"
    assert f.category == "Busses" and f.where == "conventions § Busses"
    assert f.line == "Monitor sends are post-fader."


def test_the_critic_never_reports_an_error():
    """The maintainer, 2026-10-02: a "confirm LCL 20/22/23-24 are wired" note came
    back as ERROR. Whether the desk can work is verify's call."""
    reply = json.dumps({"findings": [{"severity": "error", "kind": "intent", "where": "x",
                                      "message": "confirm the sockets are wired"}]})
    [f] = generate.parse_critic_findings(reply)
    assert f.severity == Severity.WARNING


@pytest.mark.parametrize("quotes", [["Monitors are always stereo."], []])
def test_a_critic_conventions_finding_with_a_bad_or_missing_quote_is_downgraded(quotes):
    [f] = generate.parse_critic_findings(_critic_reply("error", quotes), layers=LAYERS)
    assert f.severity == Severity.INFO
    assert f.code == ca.CODE_UNVERIFIED
    # An "error" from the critic is a WARNING before the quote check sees it.
    assert "at warning" in f.message and "downgraded" in f.message


def test_the_critic_may_say_info_now():
    raw = json.dumps({"findings": [{"severity": "info", "kind": "intent",
                                    "where": "Kick", "message": "a choice was made"}]})
    [f] = generate.parse_critic_findings(raw)
    assert f.severity == Severity.INFO


def test_without_layers_a_conventions_finding_passes_through_unchecked():
    [f] = generate.parse_critic_findings(_critic_reply("warning", ["anything"]))
    assert f.code == "critic.conventions" and f.severity == Severity.WARNING


# --------------------------------------------------------------------------
# end to end through `atoo build`, no model
# --------------------------------------------------------------------------

class _Replies:
    def __init__(self, replies):
        self._replies = iter(replies)

    def complete(self, *, system, user, response_schema=None, label=""):
        return next(self._replies)


@pytest.fixture
def show(tmp_path):
    (tmp_path / "input.csv").write_text(
        "name,category,type,phantom\nKick,drums,Mic,no\nSnare,drums,Mic,no\n")
    (tmp_path / "house.md").write_text(HOUSE)
    return tmp_path


def test_build_records_decisions_and_the_checked_conventions_audit(show, monkeypatch, capsys):
    reply = _plan()
    del reply["meta"]
    reply["conventions_audit"] = [
        {"kind": "conflict",
         "quotes": ["Monitor sends are pre-fader.", "Monitor sends are post-fader."],
         "message": "followed pre"},
        {"kind": "unused", "quotes": ["Reverb: all vocals"], "message": "made up"},
    ]
    critique = _critic_reply("warning", ["Monitor sends are post-fader."])
    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: _Replies([json.dumps(reply), critique]))
    out = show / "plan.json"
    code = main(["build", "--console-model", "wing-compact",
                 "--input", str(show / "input.csv"), "--conventions", str(show / "house.md"),
                 "--critic", "--out", str(out)])
    assert code == 0
    plan = json.loads(out.read_text())
    meta = plan["meta"]

    # the plan on disk carries every decided value
    assert plan["busses"]["Wedge"]["mono"] is True
    # verify's notes, mirrored for the Setup UI's dock
    info_codes = {f["code"] for f in meta["verify_findings"]["info"]}
    assert {inferred.CODE_BUS_WIDTH, inferred.CODE_SEND_MODE} <= info_codes
    assert meta["verify_at_generation"]["note_count"] == len(meta["verify_findings"]["info"])
    # the generator's audit, quote-checked
    assert [f["code"] for f in meta["build_findings"]] == [
        "conventions.conflict", ca.CODE_UNVERIFIED]
    # the critic's, quote-checked
    assert meta["critic_findings"][0]["code"] == "critic.conventions"
    assert meta["critic_findings"][0]["category"] == "Busses"

    err = capsys.readouterr().err
    assert "The conventions themselves" in err
    assert "conventions.conflict" in err


def test_the_setup_page_dock_reads_notes_and_build_findings():
    from atoo.webui import _plan_findings

    plan = {"meta": {
        "verify_findings": {"errors": [], "warnings": [],
                            "info": [{"severity": "info", "code": "inferred.bus-width",
                                      "where": "busses[MON1]", "message": "m"}]},
        "critic_findings": None,
        "build_findings": [{"severity": "info", "code": "conventions.conflict",
                            "where": "conventions § Busses", "category": "Busses",
                            "message": "m"}],
    }}
    got = {(f["code"], f["source"]) for f in _plan_findings(plan)}
    assert got == {("inferred.bus-width", "verify"), ("conventions.conflict", "build")}
    # a plan built before either key existed still opens
    assert _plan_findings({"meta": {"verify_findings": {"errors": [], "warnings": []}}}) == []
