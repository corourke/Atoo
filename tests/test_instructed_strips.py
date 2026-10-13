"""Strips the conventions ask for that are not input-list rows, built by
code from the resolved conventions' `## Instructed strips` block
(2026-10-01; `atoo/instructed_channels.py`, `reply_expand.py`).

The case is the maintainer's sixpiece build of 2026-10-01 (commit c04dd25): the
conventions say "Setup a MUSIC playback on Aux 1, source LCL 23-24",
"Setup HOST mic on Aux 2, Preset "Host CO2", Source LCL 20" and "Setup
TALKBACK on Aux 8, source LCL 22 if available"; the resolved file stated
all three, and the generator built none ("not in the input list ...
nothing invented"). Now the resolve step writes them as a JSON block and
code builds them.

Every file read here is frozen under `tests/fixtures/` (CLAUDE.md):
the conventions and resolved conventions as of c04dd25, that resolved file
with the block a resolve call now writes appended, sixpiece's input list
and instructions, and its reply reconstructed from the committed plan.
Nothing reads `examples/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from atoo import (category_table, conventions_resolve, generate, instructed_channels as ic,
                       plan_schema, reply_expand)
from atoo.ai_provider import AIProviderError, FakeProvider
from atoo.allocate import allocate_console_indices
from atoo.apply import _build_write_targets
from atoo.cli import main
from atoo.diagnostics import Severity
from atoo.input_list import parse_input_list
from atoo.schema_check import validate
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONVENTIONS = (FIXTURES / "conventions_2026-10-01.md").read_text()
RESOLVED_RAW = (FIXTURES / "conventions_2026-10-01.resolved.md").read_text()
RESOLVED = (FIXTURES / "conventions_2026-10-01_strips.resolved.md").read_text()
SIXPIECE_CSV = (FIXTURES / "sixpiece_2026-10-01.csv").read_text()
SIXPIECE_INSTRUCTIONS = (FIXTURES / "sixpiece_instructions_2026-10-01.md").read_text()
SIXPIECE_REPLY = (FIXTURES / "sixpiece_2026-10-01.reply.json").read_text()

MUSIC_QUOTE = "Setup a MUSIC playback on Aux 1, source LCL 23-24"
HOST_QUOTE = 'Setup HOST mic on Aux 2, Preset "Host CO2", Source LCL 20'
TALKBACK_QUOTE = "Setup TALKBACK on Aux 8, source LCL 22 if available"


def _strips(text: str = RESOLVED):
    return ic.parse_strips(text, resolved_name="conventions.resolved.md").strips


def _table():
    return category_table.parse(RESOLVED).table


def _layers(instructions: str | None = SIXPIECE_INSTRUCTIONS):
    return ic.layers_from_texts(CONVENTIONS, "conventions.md", instructions,
                                "instructions.md" if instructions else None,
                                resolved=RESOLVED, resolved_name="conventions.resolved.md")


def _expand(reply: dict, csv: str, findings: list | None = None, *, strips=None,
            table="default", instructions: str | None = None) -> dict:
    reply_expand.expand(reply, input_csv=csv, findings=findings, console_model="wing-compact",
                        layers=_layers(instructions),
                        category_table=_table() if table == "default" else table,
                        strips=_strips() if strips is None else strips)
    reply.setdefault("meta", {})["console_model"] = "wing-compact"
    allocate_console_indices(reply, console_model="wing-compact")
    return reply


def _sixpiece(findings: list | None = None, **kw) -> dict:
    return _expand(json.loads(SIXPIECE_REPLY), SIXPIECE_CSV, findings,
                   instructions=SIXPIECE_INSTRUCTIONS, **kw)


def _strip(plan: dict, bank: str, number: int) -> dict:
    [found] = [c for c in plan["channels"] if (c["bank"], c["channel"]) == (bank, number)]
    return found


def _verify(plan: dict, csv: str, instructions: str | None = None):
    return verify_plan(plan, parse_input_list(csv), console_model="wing-compact",
                       layers=_layers(instructions))


def _codes(result, severity: str) -> list[str]:
    return [f.code for f in result.findings if f.severity == severity]


# A small show to build conflicts from: every row counted onto LCL, a
# monitor bus every channel sends to, and Main.
def _small_csv(rows: list[tuple[str, str]]) -> str:
    lines = ['"patch","name","category","type","model","phantom","preset","notes"']
    lines += [f'"{patch}","{name}","{cat}","Mic","","FALSE","",""' for name, cat, patch in
              [(n, c, p) for n, c, *rest in rows for p in [rest[0] if rest else ""]]]
    return "\n".join(lines) + "\n"


def _small_reply(names: list[str], extra_channels: list[dict] | None = None,
                 monitor_from: list[str] | None = None) -> dict:
    return {
        "channels": [{"input": n, "patch": {"group": "LCL"}} for n in names]
        + (extra_channels or []),
        "busses": [{"name": "MON1", "mono": True,
                    "destination": {"type": "dedicated_output", "label": "MON1",
                                    "patch": {"group": "LCL", "sockets": [1]}},
                    "sends": [{"from": monitor_from or ["*"], "mode": "pre",
                               "level_db": -144}]}],
        "dcas": [], "mute_groups": [],
        "outputs": [{"name": "Main 1", "kind": "main",
                     "patch": {"group": "LCL", "sockets": [7, 8]}}],
    }


# --------------------------------------------------------------------------
# the block
# --------------------------------------------------------------------------

def test_the_block_parses_into_three_strips():
    parsed = ic.parse_strips(RESOLVED, resolved_name="conventions.resolved.md")
    assert parsed.state == "valid" and parsed.findings == []
    music, host, talkback = parsed.strips
    assert (music.name, music.bank, music.number, music.group, music.sockets) == \
        ("MUSIC", "aux", 1, "LCL", [23, 24])
    # Stereo is not stated in the block; two sockets make it, and it says so.
    assert music.stereo and music.stereo_why == "two sockets (LCL 23-24) make one stereo strip"
    assert (host.number, host.sockets, host.preset, host.category) == \
        (2, [20], "Host CO2", "Speech")
    assert (talkback.number, talkback.sockets, talkback.if_available) == (8, [22], True)
    assert talkback.main_direct is False and [s["bus"] for s in talkback.sends] == \
        ["MON1", "MON2", "MON3", "MON4"]
    assert [s.quote for s in parsed.strips] == [MUSIC_QUOTE, HOST_QUOTE, TALKBACK_QUOTE]


def test_a_file_made_before_the_block_existed_builds_none_and_says_so():
    parsed = ic.parse_strips(RESOLVED_RAW, resolved_name="conventions.resolved.md")
    assert parsed.state == "missing" and parsed.strips == []
    [note] = parsed.findings
    assert note.severity == Severity.INFO and note.code == ic.CODE_STRIPS_MISSING


def test_a_block_that_is_not_json_is_one_warning_and_builds_none():
    parsed = ic.parse_strips("## Instructed strips\n\n```json\n[{oops\n```\n")
    assert parsed.state == "invalid" and parsed.strips == []
    [warning] = parsed.findings
    assert warning.severity == Severity.WARNING and warning.code == ic.CODE_STRIPS_INVALID


def test_an_entry_code_cannot_build_is_named_and_the_others_still_build():
    block = [
        {"name": "OK", "kind": "aux", "number": 3, "source": "LCL 5", "quote": "q one two three"},
        {"name": "NOSOCKET", "kind": "aux", "number": 4, "source": None, "quote": "q four"},
        {"name": "BADNUM", "kind": "aux", "number": 9, "source": "LCL 6", "quote": "q five"},
        {"name": "GAP", "kind": "channel", "number": 1, "source": "LCL 7-9", "quote": "q six"},
    ]
    parsed = ic.parse_strips(f"## Instructed strips\n\n```json\n{json.dumps(block)}\n```\n")
    assert [s.name for s in parsed.strips] == ["OK"]
    reasons = " | ".join(f.message for f in parsed.findings)
    assert all(f.code == ic.CODE_STRIP_INVALID for f in parsed.findings)
    assert "states no source socket" in reasons
    assert "aux 9 does not exist" in reasons
    assert "not consecutive" in reasons


@pytest.mark.parametrize("raw, want", [
    ("LCL 23-24", ("LCL", [23, 24])), ("LCL 23+24", ("LCL", [23, 24])),
    ("LCL 20", ("LCL", [20])), ("A 40", ("A", [40])), ("AES50-A 39-40", ("A", [39, 40])),
    (None, (None, [])), ("somewhere", None),
])
def test_a_source_is_read_as_a_group_and_its_sockets(raw, want):
    assert ic.parse_source(raw) == want


def test_the_resolve_check_verifies_each_strip_quote_like_any_other_citation():
    result = conventions_resolve.check(RESOLVED, CONVENTIONS, conventions_name="conventions.md")
    mine = [c for c in result.citations if c.section == ic.STRIPS_HEADING]
    assert [c.quote for c in mine] == [MUSIC_QUOTE, HOST_QUOTE, TALKBACK_QUOTE]
    assert all(c.found for c in mine)

    invented = RESOLVED.replace(HOST_QUOTE.replace('"', '\\"'),
                                "Setup HOST mic on Aux 2 from the moon")
    result = conventions_resolve.check(invented, CONVENTIONS, conventions_name="conventions.md")
    assert any(c.section == ic.STRIPS_HEADING and not c.found for c in result.citations)
    assert any(f.code == conventions_resolve.CODE_QUOTE
               and "from the moon" in f.message for f in result.findings)
    # And code does not build the strip whose quote is not there.
    kept = ic.drop_unquoted(ic.parse_strips(invented), CONVENTIONS,
                            conventions_name="conventions.md", resolved_name="r")
    assert [s.name for s in kept.strips] == ["MUSIC", "TALKBACK"]
    assert any("HOST" in f.message for f in kept.findings)


def test_the_generator_reads_a_note_not_the_json():
    body = conventions_resolve.prompt_text(RESOLVED, [], "conventions.md")
    assert "## Instructed strips" not in body and '"kind": "aux"' not in body
    user = generate.generator_user(CONVENTIONS, SIXPIECE_CSV, conventions_name="conventions.md",
                                   input_name="input.csv", resolved=body,
                                   resolved_name="conventions.resolved.md",
                                   category_table=_table(), instructed_strips=_strips())
    assert "## Strips code builds for you" in user
    assert "- MUSIC: aux 1, from LCL 23-24, stereo, category Misc" in user
    assert "- HOST: aux 2, from LCL 20, preset 'Host CO2', category Speech" in user
    assert "- TALKBACK: aux 8, from LCL 22 if available, category Misc" in user


# --------------------------------------------------------------------------
# sixpiece, rebuilt with no model call
# --------------------------------------------------------------------------

def test_the_frozen_reply_alone_builds_no_aux_strip_as_the_real_build_did():
    plan = _sixpiece(strips=[])
    assert len(plan["channels"]) == 23
    assert not [c for c in plan["channels"] if c["bank"] == "aux"]


def test_sixpiece_gets_music_host_and_talkback_on_their_stated_strips_and_sockets():
    findings: list = []
    plan = _sixpiece(findings)
    assert validate(plan, plan_schema.PLAN_SCHEMA) == []

    music = _strip(plan, "aux", 1)
    assert music["name"] == "MUSIC"
    assert music["patch"] == {"group": "LCL", "sockets": [23, 24], "stated": True}
    assert music["source"]["stereo"] is True
    assert music["source"]["from"] == "conventions" and music["source"]["quote"] == MUSIC_QUOTE
    assert music["inferred"] == [{"field": "stereo", "by": "fallback",
                                  "basis": "two sockets (LCL 23-24) make one stereo strip"}]
    assert music["main_routes"] == [{"index": 1}]

    host = _strip(plan, "aux", 2)
    assert host["name"] == "HOST"
    assert host["patch"] == {"group": "LCL", "sockets": [20], "stated": True}
    assert host["processing"]["preset"] == "Host CO2"
    # Category defaults: Speech, from the Category table.
    assert (host["color"], host["dca"], host["mute_group"]) == ("Purple", ["Speech"], ["Speech"])
    assert (host["processing"]["gain_db"], host["processing"]["trim_db"],
            host["fader"]["fader_db"]) == (20, 0, -144)
    assert host["processing"].get("hpf_hz") is None      # an aux strip has no filter
    assert "Speech" in plan["dcas"] and "Speech" in plan["mute_groups"]

    talkback = _strip(plan, "aux", 8)
    assert talkback["patch"] == {"group": "LCL", "sockets": [22], "stated": True}
    assert talkback["main_routes"] == []
    assert sorted(s["bus"] for s in talkback["bus_sends"]) == ["MON1", "MON2", "MON3", "MON4"]
    assert all((s["mode"], s["level_db"]) == ("pre", -144) for s in talkback["bus_sends"])

    said = [f for f in findings if f.code == "reply.instructed-strip"]
    assert len(said) == 3 and all(f.severity == Severity.INFO for f in said)
    assert "stereo (two sockets (LCL 23-24) make one stereo strip)" in said[0].message


def test_sixpiece_verifies_with_each_strip_reported_as_instructed():
    plan = _sixpiece()
    result = _verify(plan, SIXPIECE_CSV, SIXPIECE_INSTRUCTIONS)
    assert _codes(result, "error") == []
    noted = [(f.severity.value, f.message) for f in result.findings
             if f.code == "reconcile.from-instructions"]
    # Each is asked for verbatim with its socket, so each is an INFO.
    assert noted == [
        ("info", f"aux 1 'MUSIC' is not on the input list; built because conventions.md says "
                 f"{MUSIC_QUOTE!r}, on LCL 23-24 as it states"),
        ("info", f"aux 2 'HOST' is not on the input list; built because conventions.md says "
                 f"{HOST_QUOTE!r}, on LCL 20 as it states"),
        ("info", f"aux 8 'TALKBACK' is not on the input list; built because conventions.md says "
                 f"{TALKBACK_QUOTE!r}, on LCL 22 as it states"),
    ]


def test_sixpiece_apply_writes_aux_1_2_and_8():
    targets, _warnings = _build_write_targets(_sixpiece(), True)
    addresses = {t.address for t in targets}
    assert {"/aux/1/in/conn/grp", "/aux/1/in/conn/in", "/aux/2/in/conn/in",
            "/aux/8/in/conn/in", "/io/in/LCL/23/mode", "/io/in/LCL/24/mode",
            "/aux/8/send/1/on"} <= addresses
    by_address = {t.address: t for t in targets}
    assert by_address["/io/in/LCL/23/mode"].description.endswith("ST width on LCL 23")


def test_a_reply_in_the_plans_own_shape_gets_the_strips_once():
    plain = _sixpiece(strips=[])            # a full plan with no aux strip
    plain.pop("meta", None)
    replayed = _expand(json.loads(json.dumps(plain)), SIXPIECE_CSV,
                       instructions=SIXPIECE_INSTRUCTIONS)
    assert sorted(c["name"] for c in replayed["channels"] if c["bank"] == "aux") == \
        ["HOST", "MUSIC", "TALKBACK"]
    replayed.pop("meta", None)
    again = _expand(json.loads(json.dumps(replayed)), SIXPIECE_CSV,
                    instructions=SIXPIECE_INSTRUCTIONS)
    assert len([c for c in again["channels"] if c["bank"] == "aux"]) == 3


def test_no_counted_row_lands_on_a_strip_socket_or_number():
    # 20 rows counted onto LCL: without the strips they would take LCL 1-20.
    names = [f"Mic {n}" for n in range(1, 21)]
    csv = _small_csv([(n, "vocals") for n in names])
    plan = _expand(_small_reply(names), csv)
    taken = {n for c in plan["channels"] if c["source"].get("from") is None
             for n in c["patch"]["sockets"]}
    assert taken.isdisjoint({20, 22, 23, 24})
    assert _codes(_verify(plan, csv), "error") == []


def test_a_bus_every_channel_sends_to_does_not_reach_a_code_built_strip():
    plan = _expand(_small_reply(["Kick"]), _small_csv([("Kick", "drums")]))
    assert [s["bus"] for s in _strip(plan, "ch", 1)["bus_sends"]] == ["MON1"]
    assert _strip(plan, "aux", 1)["bus_sends"] == []         # MUSIC: no stated sends
    assert [s["bus"] for s in _strip(plan, "aux", 8)["bus_sends"]] == ["MON1"]  # stated


# --------------------------------------------------------------------------
# conflicts: "if available" is INFO, anything else an ERROR at verify
# --------------------------------------------------------------------------

def test_if_available_and_the_socket_is_taken_builds_the_strip_unpatched():
    csv = _small_csv([("Kick", "drums", "LCL 22")])
    findings: list = []
    plan = _expand(_small_reply(["Kick"]), csv, findings)
    talkback = _strip(plan, "aux", 8)
    assert talkback["patch"] is None
    assert talkback["source"]["condition"] == "if available"
    assert validate(plan, plan_schema.PLAN_SCHEMA) == []
    [said] = [f for f in findings if f.code == "reply.instructed-strip"
              and "TALKBACK" in f.message]
    assert said.severity == Severity.INFO
    assert "Left UNPATCHED" in said.message and "input list row 'Kick'" in said.message

    result = _verify(plan, csv)
    assert _codes(result, "error") == []
    [warning] = [f for f in result.findings if f.code == "reconcile.from-instructions"
                 and "TALKBACK" in f.message]
    assert "Left unpatched (if available): LCL 22 is taken by input list row 'Kick'" in warning.message

    targets, warnings = _build_write_targets(plan, True)
    by_address = {t.address: t for t in targets}
    assert by_address["/aux/8/in/conn/grp"].description.endswith("left unpatched (OFF)")
    assert "/aux/8/in/conn/in" not in by_address
    assert any("aux 8 ('TALKBACK'): left unpatched" in w for w in warnings)


def test_a_stated_socket_an_input_list_row_states_is_an_error_at_verify():
    csv = _small_csv([("Kick", "drums", "LCL 20")])
    findings: list = []
    plan = _expand(_small_reply(["Kick"]), csv, findings)
    host = _strip(plan, "aux", 2)
    assert host["patch"]["sockets"] == [20]           # built, never silently dropped
    [said] = [f for f in findings if f.code == "reply.instructed-strip" and "HOST" in f.message]
    assert said.severity == Severity.WARNING and "physical conflict" in said.message
    errors = [f for f in _verify(plan, csv).findings
              if f.code == "reconcile.instructed-conflict"]
    assert len(errors) == 1 and errors[0].severity == "error"
    assert "LCL 20 -- which is taken by input list row 'Kick'" in errors[0].message


def test_a_stated_strip_number_the_reply_uses_is_an_error_at_verify():
    reply = _small_reply(["Kick", "Pad"])
    reply["channels"][1].update({"bank": "aux", "channel": 2})
    csv = _small_csv([("Kick", "drums"), ("Pad", "keys")])
    findings: list = []
    plan = _expand(reply, csv, findings)
    [said] = [f for f in findings if f.code == "reply.instructed-strip" and "HOST" in f.message]
    assert said.severity == Severity.WARNING and "aux 2 is also 'Pad'" in said.message
    assert "strip.double-booked" in _codes(_verify(plan, csv), "error")


# --------------------------------------------------------------------------
# the generator built one too
# --------------------------------------------------------------------------

def test_a_strip_the_reply_also_built_is_built_once_with_codes_strip_and_socket():
    talkback = {"input": "Talkback", "bank": "ch", "channel": 30,
                "patch": {"group": "LCL", "sockets": [21]},
                "quote": "Setup TALKBACK on Aux 8, source LCL 22 if available.",
                "dca": ["Comms"]}
    reply = _small_reply(["Kick"], extra_channels=[talkback], monitor_from=["Kick", "Talkback"])
    reply["dcas"] = [{"name": "Comms"}]
    csv = _small_csv([("Kick", "drums")])
    findings: list = []
    plan = _expand(reply, csv, findings)
    named = [c for c in plan["channels"] if c["name"].casefold() == "talkback"]
    assert len(named) == 1
    [built] = named
    assert (built["bank"], built["channel"], built["name"]) == ("aux", 8, "TALKBACK")
    assert built["patch"] == {"group": "LCL", "sockets": [22], "stated": True}
    assert built["dca"] == ["Comms"]                     # the reply's own decision stands
    assert [s["bus"] for s in built["bus_sends"]] == ["MON1"]   # its send renamed to the strip
    [said] = [f for f in findings if f.code == "reply.instructed-strip" and "TALKBACK" in
              f.message]
    assert "merged with the reply's own channel" in said.message
    assert _codes(_verify(plan, csv), "error") == []


def test_an_input_list_row_that_is_a_strip_goes_where_the_conventions_put_it():
    csv = _small_csv([("Kick", "drums"), ("HOST", "speech")])
    findings: list = []
    plan = _expand(_small_reply(["Kick", "HOST"]), csv, findings)
    hosts = [c for c in plan["channels"] if c["name"] == "HOST"]
    assert len(hosts) == 1
    [host] = hosts
    assert (host["bank"], host["channel"]) == ("aux", 2)
    assert host["patch"] == {"group": "LCL", "sockets": [20], "stated": True}
    assert host["processing"]["preset"] == "Host CO2"
    assert "from" not in host["source"]                 # a row, not an invented strip
    assert any(f.code == "reply.instructed-strip-row" for f in findings)
    assert _codes(_verify(plan, csv), "error") == []


# --------------------------------------------------------------------------
# build: the block reaches the build; --no-resolve keeps today's path
# --------------------------------------------------------------------------

@dataclass
class ScriptedProvider(FakeProvider):
    script: dict = field(default_factory=dict)

    def complete(self, *, system, user, response_schema=None, label=""):
        if label not in self.script:
            raise AIProviderError(f"no reply scripted for {label}")
        self.response = self.script[label]
        return super().complete(system=system, user=user, response_schema=response_schema,
                                label=label)


@pytest.fixture
def show(tmp_path, monkeypatch):
    monkeypatch.delenv("ATOO_RESOLVE", raising=False)
    monkeypatch.delenv(category_table.ENV, raising=False)
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")
    (tmp_path / "input.csv").write_text(SIXPIECE_CSV)
    (tmp_path / "conventions.md").write_text(CONVENTIONS)
    body = RESOLVED.split("# Resolved conventions (conventions.md)", 1)[1]
    (tmp_path / "conventions.resolved.md").write_text(conventions_resolve.run(
        CONVENTIONS, "conventions.md", provider=FakeProvider(response=body),
        now="2026-10-01T00:00:00Z"))
    return tmp_path


def _build(show, monkeypatch, *extra) -> tuple[int, ScriptedProvider]:
    provider = ScriptedProvider(script={"generator": SIXPIECE_REPLY})
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    code = main(["build", "--console-model", "wing-compact",
                 "--input", str(show / "input.csv"),
                 "--conventions", str(show / "conventions.md"),
                 "--out", str(show / "plan.json"), *extra])
    return code, provider


def test_a_build_builds_the_strips_and_records_them(show, monkeypatch, capsys):
    code, provider = _build(show, monkeypatch)
    assert code == 0
    assert ("INFO instructed strips: 3 in conventions.resolved.md -- code builds MUSIC (aux 1), "
            "HOST (aux 2), TALKBACK (aux 8)") in capsys.readouterr().err
    [(_system, user)] = provider.calls
    assert "## Strips code builds for you" in user
    plan = json.loads((show / "plan.json").read_text())
    assert {(c["bank"], c["channel"], c["name"]) for c in plan["channels"]
            if c["bank"] == "aux"} == {("aux", 1, "MUSIC"), ("aux", 2, "HOST"),
                                       ("aux", 8, "TALKBACK")}
    record = plan["meta"]["resolved_conventions"]["instructed_strips"]
    assert record == {"state": "valid", "applied": True,
                      "strips": ["MUSIC", "HOST", "TALKBACK"]}
    assert main(["verify", "--plan", str(show / "plan.json"),
                 "--input", str(show / "input.csv")]) == 0


def test_no_resolve_leaves_the_strips_to_the_generator_as_before(show, monkeypatch):
    code, provider = _build(show, monkeypatch, "--no-resolve")
    assert code == 0
    [(_system, user)] = provider.calls
    assert "## Strips code builds for you" not in user
    plan = json.loads((show / "plan.json").read_text())
    assert not [c for c in plan["channels"] if c["bank"] == "aux"]


def test_resolve_check_reports_the_block(show, capsys):
    code = main(["resolve", "--conventions", str(show / "conventions.md"), "--check"])
    out = capsys.readouterr().out
    assert "Instructed strips valid, 3 built by code (MUSIC, HOST, TALKBACK)" in out
    assert code in (0, 2)


def test_a_strip_with_no_category_takes_the_one_its_name_or_kind_points_at():
    """The maintainer's sixpiece rebuild, 2026-10-01: the resolve wrote
    `"category": null` for TALKBACK and MUSIC, and both were built with no
    gain, trim or fader, though Misc ("aux", "music") states all three."""
    no_category = RESOLVED.replace('"preset": null, "category": "Misc"',
                                   '"preset": null, "category": null')
    assert no_category.count('"category": null') == 2
    findings: list = []
    plan = _sixpiece(findings, strips=_strips(no_category))
    for number in (1, 8):
        strip = _strip(plan, "aux", number)
        assert (strip["processing"]["gain_db"], strip["processing"]["trim_db"],
                strip["fader"]["fader_db"]) == (20, 0, -144), strip["name"]
    said = {f.where: f.message for f in findings if f.code == "reply.instructed-strip"}
    # MUSIC is a Misc word; TALKBACK is not, but it is an aux strip.
    assert "category Misc (its name 'MUSIC' is a Misc word)" in said["channels[MUSIC]"]
    assert ("category Misc (no category is stated, and Misc is the category for aux strips)"
            in said["channels[TALKBACK]"])
    assert _strip(plan, "aux", 8)["provenance"]["category"].startswith("decided: Misc")
