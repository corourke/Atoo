"""The resolved conventions' Category table (2026-09-30,
`atoo/category_table.py`, `reply_expand.CategoryRules`, FR-1.18a).

The resolve step writes a small per-category table after its prose; code
checks it, and during expansion writes each table field on every channel
of that input-list category whose reply left the field out. A value the
reply wrote wins. `--no-category-rules` / `ATOO_CATEGORY_RULES=0`
ignores the table.

No model is called. The real resolved file is frozen, with a hand-written
table restating its Categories section, at
`tests/fixtures/conventions_2026-09-30.resolved-body.md`; nothing here
reads `examples/`.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from atoo import apply, category_table, conventions_resolve, generate
from atoo.ai_provider import AIProviderError, FakeProvider
from atoo.cli import main
from atoo.diagnostics import Severity
from atoo.input_list import parse_input_list
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BODY = (FIXTURES / "conventions_2026-09-30.resolved-body.md").read_text()
SIXPIECE_CSV = (FIXTURES / "sixpiece_2026-09-29.csv").read_text()
SIXPIECE_CONVENTIONS = (FIXTURES / "sixpiece_conventions_2026-09-29.md").read_text()
SIXPIECE_INSTRUCTIONS = (FIXTURES / "sixpiece_instructions_2026-09-29.md").read_text()
SIXPIECE_REPLY = json.loads((FIXTURES / "haiku45_sixpiece_2026-09-29_fixup.reply.json").read_text())

TABLE_FIELDS = ("color", "dca", "mute_group", "main_routes", "fader")
PROCESSING_FIELDS = ("hpf_hz", "gain_db", "trim_db")


def _table():
    parsed = category_table.parse(BODY)
    assert parsed.state == "valid", parsed.reason
    return parsed.table


def _with_table(entries) -> str:
    return (category_table.strip(BODY) + "\n\n## Category table\n\n```json\n"
            + json.dumps(entries) + "\n```\n")


# ---------------------------------------------------------------------------
# the table: parsed and checked
# ---------------------------------------------------------------------------

def test_the_frozen_table_is_valid_and_matched_by_category_word():
    table = _table()
    assert len(table.entries) == 11
    assert table.entry_for("DRUMS")["name"] == "Drums"
    assert table.entry_for(" keys ")["name"] == "Keyboards"
    assert table.entry_for("trax")["name"] == "Tracks/Playback"
    assert table.entry_for("perc") is None


def test_a_file_with_no_table_is_one_info_and_nothing_is_applied():
    parsed = category_table.parse("## Categories\n- Drums: red.\n", resolved_name="c.resolved.md")
    assert parsed.table is None and parsed.state == "missing"
    [finding] = parsed.findings
    assert finding.severity == Severity.INFO and finding.code == category_table.CODE_MISSING


@pytest.mark.parametrize("table, why", [
    ("[{\"name\": \"Drums\", \"aliases\": [\"drums\"],}]", "not JSON"),
    ([{"name": "Drums", "aliases": ["drums"], "hpf_hz": 5}], "below the minimum"),
    ([{"name": "Drums", "aliases": []}], "aliases"),
    ([{"name": "Drums", "aliases": ["drums"], "sends": ["MON1"]}], "sends"),
    ([{"name": "Drums", "aliases": ["drums"]}, {"name": "Perc", "aliases": ["Drums"]}],
     "alias of both 'Drums' and 'Perc'"),
    ([], "table"),
])
def test_an_invalid_table_is_one_warning_and_nothing_is_applied(table, why):
    text = ("## Categories\n\n## Category table\n\n```json\n"
            + (table if isinstance(table, str) else json.dumps(table)) + "\n```\n")
    parsed = category_table.parse(text)
    assert parsed.table is None and parsed.state == "invalid"
    [finding] = parsed.findings
    assert finding.severity == Severity.WARNING and finding.code == category_table.CODE_INVALID
    assert why in finding.message


def test_the_generator_reads_the_prose_not_the_json():
    body = conventions_resolve.prompt_text(BODY, [], "conventions.md")
    assert "## Category table" not in body and '"aliases"' not in body
    assert "### Drums" in body and "## Lines with no effect" in body


def test_the_note_says_what_code_writes_for_the_categories_this_list_uses():
    note = category_table.prompt_note(_table(), ["drums", "Drums", "keys", "perc", "misc"])
    assert "leave those fields out unless a channel is an exception" in note
    assert '- drums: color Red, hpf_hz 40, dca ["Drums"]' in note
    assert "main_routes []" in note.split("- keys")[0]          # drums: only via busses
    keys = next(line for line in note.splitlines() if line.startswith("- keys"))
    assert "main_routes" not in keys and "(Keyboards)" in keys  # depends on the Keys bus
    assert "Not covered, so write every field yourself: perc." in note
    assert note.count("- drums") == 1
    assert "- bass" not in note and "- speech" not in note     # not on this list


# ---------------------------------------------------------------------------
# applied during expansion
# ---------------------------------------------------------------------------

def _lean(reply: dict, keep=()) -> dict:
    """`reply` with every table field left out of every row's channel."""
    reply = copy.deepcopy(reply)
    for channel in reply["channels"]:
        if channel["input"] == "Talkback" or channel["input"] in keep:
            continue
        for key in ("color", "dca", "mute_group", "main_routes", "fader"):
            channel.pop(key, None)
        for key in PROCESSING_FIELDS:
            (channel.get("processing") or {}).pop(key, None)
    reply.pop("category_colors", None)
    return reply


def _sixpiece_plan(reply: dict, *, table=None, findings=None) -> dict:
    return generate.plan_from_reply(
        json.dumps(reply), input_csv=SIXPIECE_CSV, console_model="wing-compact",
        findings=findings, conventions=SIXPIECE_CONVENTIONS, conventions_name="conventions.md",
        instructions=SIXPIECE_INSTRUCTIONS, instructions_name="instructions.md",
        resolved=conventions_resolve.prompt_text(BODY, [], "conventions.md"),
        resolved_name="conventions.resolved.md", category_table=table)


def _as_table_says(reply: dict) -> dict:
    """`reply` with each row's channel writing exactly what the frozen
    table says for its category (Keys' Main routing, which the table
    leaves to the model, as the reply had it)."""
    table = _table()
    rows = {r.name: r for r in parse_input_list(SIXPIECE_CSV)}
    reply = copy.deepcopy(reply)
    # The one row the reply left to code (`build_left_out_rows`), written
    # here so both plans have it on the same strip.
    named = {c["input"] for c in reply["channels"]}
    reply["channels"] += [{"input": name} for name in rows if name not in named]
    for channel in reply["channels"]:
        row = rows.get(channel["input"])
        if row is None:
            continue
        entry = table.entry_for(row.category)
        processing = channel.setdefault("processing", {})
        channel["color"] = entry.get("color")
        for key in PROCESSING_FIELDS:
            processing[key] = entry.get(key)
        channel["fader"] = {"fader_db": entry["fader_db"]}
        channel["dca"], channel["mute_group"] = entry["dca"], entry["mute_group"]
        if "main_direct" in entry:
            channel["main_routes"] = [{"index": 1}] if entry["main_direct"] else []
    return reply


def test_a_lean_reply_plus_the_table_is_the_plan_the_full_reply_makes():
    """The load-bearing claim: code writing the table's values is the same
    plan as the model writing them, field for field -- and so verifies
    and applies exactly as that plan does."""
    full = _as_table_says(SIXPIECE_REPLY)
    findings: list = []
    written = _sixpiece_plan(full)
    applied = _sixpiece_plan(_lean(full, keep=("Keys L",)), table=_table(), findings=findings)

    for a, b in zip(written["channels"], applied["channels"], strict=True):
        assert a["name"] == b["name"]
        for key in TABLE_FIELDS:
            assert a[key] == b[key], (a["name"], key)
        for key in PROCESSING_FIELDS:
            assert a["processing"].get(key) == b["processing"].get(key), (a["name"], key)

    rows = parse_input_list(SIXPIECE_CSV)
    verdicts = [verify_plan(p, rows, console_model="wing-compact") for p in (written, applied)]
    assert [(f.severity, f.code) for f in verdicts[0].findings] == \
        [(f.severity, f.code) for f in verdicts[1].findings]
    assert not verdicts[1].errors

    def targets(plan):
        found, _warnings = apply._build_write_targets(plan, True)
        return [(t.address, t.compute_value(None)) for t in found]
    assert targets(written) == targets(applied)


def test_each_field_is_filled_only_where_the_reply_left_it_out():
    reply = _lean(SIXPIECE_REPLY)
    kick = next(c for c in reply["channels"] if c["input"] == "Kick")
    kick["processing"]["hpf_hz"] = 60          # the model's exception
    kick["dca"] = []                           # an explicit "no DCA" is written too
    snare = next(c for c in reply["channels"] if c["input"] == "Snare")
    snare["fader"] = {"fader_db": None}        # null is "not stated": filled
    findings: list = []
    plan = _sixpiece_plan(reply, table=_table(), findings=findings)
    by_name = {c["name"]: c for c in plan["channels"]}

    kick = by_name["Kick"]
    assert kick["processing"]["hpf_hz"] == 60 and kick["dca"] == []
    assert kick["color"] == "Red" and kick["mute_group"] == ["Band"]
    assert kick["processing"]["gain_db"] == 20 and kick["processing"]["trim_db"] == 0
    assert kick["provenance"]["color"] == "category table: Drums"
    assert "category table: Drums: gain 20 dB, trim 0 dB" in kick["provenance"]["processing"]
    assert by_name["Snare"]["fader"]["fader_db"] == -144
    assert by_name["Snare"]["dca"] == ["Drums"] and by_name["Snare"]["processing"]["hpf_hz"] == 40
    assert by_name["Bass"]["main_routes"] == [{"index": 1}]
    assert by_name["DSR Vox"]["main_routes"] == []

    drums = next(f for f in findings if f.code == "reply.category-rule"
                 and f.message.startswith("Drums"))
    assert drums.severity == Severity.INFO
    assert "HPF 40 Hz (Snare, Hi-hat" in drums.message        # not Kick
    assert "The reply's own, different value kept: HPF (Kick); DCA (Kick)" in drums.message
    rules = [f for f in findings if f.code == "reply.category-rule"]
    assert len(rules) == 6                    # one per category this list uses


def test_an_instructed_channel_gets_nothing_from_the_table():
    """Talkback is built from the instructions, not an input-list row
    (`instructed_channels`): the model owns it."""
    reply = _lean(SIXPIECE_REPLY)
    talkback = next(c for c in reply["channels"] if c["input"] == "Talkback")
    for key in ("color", "dca", "mute_group", "main_routes", "fader"):
        talkback.pop(key, None)
    talkback["processing"] = {}
    plan = _sixpiece_plan(reply, table=_table())
    built = next(c for c in plan["channels"] if c["name"] == "Talkback")
    assert built["fader"]["fader_db"] is None and built["processing"]["gain_db"] is None
    assert not any("category table" in str(v) for v in built["provenance"].values())


def test_an_aux_strip_gets_no_hpf_and_a_digital_source_no_gain():
    csv = ("patch,name,category,type,model,phantom,notes\n"
           "LCL 1,Kick,drums,Mic,,FALSE,\n"
           "USB 1,Trax,tracks,Line,,FALSE,\n"
           "LCL 2,Walk-in,drums,Line,,FALSE,\n")
    reply = {"channels": [{"input": "Kick"}, {"input": "Trax"},
                          {"input": "Walk-in", "bank": "aux"}],
             "busses": [], "outputs": [{"name": "Main", "kind": "main", "index": 1,
                                        "patch": None}],
             "unassigned_inputs": [], "notes": []}
    findings: list = []
    plan = generate.plan_from_reply(json.dumps(reply), input_csv=csv,
                                    console_model="wing-compact", findings=findings,
                                    resolved="rules", category_table=_table())
    by_name = {c["name"]: c for c in plan["channels"]}
    assert by_name["Kick"]["processing"]["hpf_hz"] == 40
    assert by_name["Walk-in"]["bank"] == "aux"
    assert by_name["Walk-in"]["processing"]["hpf_hz"] is None
    assert by_name["Walk-in"]["processing"]["gain_db"] == 20
    assert by_name["Trax"]["processing"]["gain_db"] is None       # USB: no head amp
    assert by_name["Trax"]["processing"]["trim_db"] == 0
    text = " ".join(f.message for f in findings if f.code == "reply.category-rule")
    assert "Not applied, an aux strip has no high-pass: Walk-in" in text
    assert "Not applied, no gain on USB: that source has no head amp: Trax" in text
    # The Tracks DCA the reply never declared is declared, and said so.
    assert "Tracks" in plan["dcas"]
    assert any(f.code == "reply.category-group-declared" and "'Tracks'" in f.message
               for f in findings)


def test_a_click_is_never_routed_to_main_by_the_table():
    """A "tracks" entry cannot tell the click from the backing tracks; the
    domain knowledge keeps click and guide off Main, recognised by name
    as verify recognises them."""
    table = category_table.parse(_with_table([
        {"name": "Tracks", "aliases": ["tracks"], "main_direct": True, "fader_db": -144}])).table
    csv = ("patch,name,category,type,model,phantom,notes\n"
           "LCL 1,Trax L,tracks,Line,,FALSE,\n"
           "LCL 2,T Click/Guide,tracks,Line,,FALSE,\n")
    reply = {"channels": [{"input": "Trax L"}, {"input": "T Click/Guide"}],
             "busses": [], "outputs": [], "unassigned_inputs": [], "notes": []}
    findings: list = []
    plan = generate.plan_from_reply(json.dumps(reply), input_csv=csv,
                                    console_model="wing-compact", findings=findings,
                                    resolved="rules", category_table=table)
    by_name = {c["name"]: c for c in plan["channels"]}
    assert by_name["Trax L"]["main_routes"] == [{"index": 1}]
    assert by_name["T Click/Guide"]["main_routes"] == []
    assert by_name["T Click/Guide"]["fader"]["fader_db"] == -144
    [info] = [f for f in findings if f.code == "reply.category-rule"]
    assert "a click, guide or talkback strip stays off Main" in info.message


def test_a_row_the_reply_dropped_is_built_with_its_categorys_settings():
    reply = _lean(SIXPIECE_REPLY)
    reply["channels"] = [c for c in reply["channels"] if c["input"] != "Bass"]
    plan = _sixpiece_plan(reply, table=_table())
    bass = next(c for c in plan["channels"] if c["name"] == "Bass")
    assert "built by code" in bass["provenance"]["input"]
    assert bass["color"] == "Blue" and bass["dca"] == ["Band"]
    assert bass["main_routes"] == [{"index": 1}] and bass["processing"]["hpf_hz"] == 80


def test_without_a_table_nothing_is_applied():
    plan = _sixpiece_plan(_lean(SIXPIECE_REPLY))
    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    assert kick["processing"]["hpf_hz"] is None and kick["dca"] == []


# ---------------------------------------------------------------------------
# the build: the switch, the prompt, the record
# ---------------------------------------------------------------------------

CONVENTIONS = """# House conventions

- Drums are red, with a high-pass at 40Hz, in the Drums DCA.
- Bass is blue, in the Bass DCA.
- Vocals are green, in the Vocals DCA and the Vocals mute group.
- Everything goes straight to Main. Faders start fully down.
"""

TABLE = [
    {"name": "Drums", "aliases": ["drums"], "color": "Red", "hpf_hz": 40, "dca": ["Drums"],
     "fader_db": -144, "main_direct": True},
    {"name": "Bass", "aliases": ["bass"], "color": "Blue", "dca": ["Bass"], "fader_db": -144,
     "main_direct": True},
    {"name": "Vocals", "aliases": ["vocals"], "color": "Green", "dca": ["Vocals"],
     "mute_group": ["Vocals"], "fader_db": -144, "main_direct": True},
]

RESOLVED = f"""## Categories
### Drums
- Red, HPF 40 Hz, DCA Drums. [conventions: "Drums are red, with a high-pass at 40Hz, in the Drums DCA."]
### Bass
- Blue, DCA Bass. [conventions: "Bass is blue, in the Bass DCA."]
### Vocals
- Green, DCA Vocals, mute group Vocals. [conventions: "Vocals are green, in the Vocals DCA and the Vocals mute group."]

## Faders
- Straight to Main, faders fully down. [conventions: "Everything goes straight to Main. Faders start fully down."]

## Category table

```json
{json.dumps(TABLE)}
```
"""

LEAN_REPLY = {
    "channels": [{"input": "Kick"}, {"input": "BassDI"}, {"input": "VOX 1"}],
    "dcas": [{"name": "Drums"}, {"name": "Bass"}, {"name": "Vocals"}],
    "mute_groups": [{"name": "Vocals"}],
    "busses": [],
    "outputs": [{"name": "Main", "kind": "main", "index": 1,
                 "patch": {"group": "LCL", "sockets": [7, 8]}}],
    "unassigned_inputs": [], "notes": [],
}


@dataclass
class ScriptedProvider(FakeProvider):
    script: list[str] = field(default_factory=list)
    stream_chunks: int = 2
    model: str = "claude-sonnet-5"

    def complete(self, *, system, user, response_schema=None, label=""):
        if len(self.calls) >= len(self.script):
            raise AIProviderError("the script has no reply for this call")
        self.response = self.script[len(self.calls)]
        return super().complete(system=system, user=user,
                                response_schema=response_schema, label=label)


@pytest.fixture
def show(tmp_path, monkeypatch):
    monkeypatch.delenv("ATOO_RESOLVE", raising=False)
    monkeypatch.delenv(category_table.ENV, raising=False)
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "1")
    (tmp_path / "input.csv").write_text(
        (FIXTURES / "haiku45_festival_dangling_dca.csv").read_text())
    (tmp_path / "conventions.md").write_text(CONVENTIONS)
    return tmp_path


def _write_resolved(show, body: str = RESOLVED) -> None:
    text = conventions_resolve.run(CONVENTIONS, "conventions.md",
                                   provider=FakeProvider(response=body),
                                   now="2026-09-30T00:00:00Z")
    (show / "conventions.resolved.md").write_text(text)


def _build(show, monkeypatch, *replies, extra=()) -> tuple[int, ScriptedProvider]:
    provider = ScriptedProvider(script=[json.dumps(r) for r in replies])
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    code = main(["build", "--console-model", "wing-compact",
                 "--input", str(show / "input.csv"),
                 "--conventions", str(show / "conventions.md"),
                 "--out", str(show / "plan.json"), *extra])
    return code, provider


def _plan(show) -> dict:
    return json.loads((show / "plan.json").read_text())


def test_a_build_applies_the_table_and_tells_the_generator(show, monkeypatch, capsys):
    _write_resolved(show)
    code, provider = _build(show, monkeypatch, LEAN_REPLY)
    assert code == 0
    assert ("INFO category table: 3 categories in conventions.resolved.md -- code writes "
            "their color, HPF, DCA, mute group, fader and Main routing on every channel of "
            "the category whose reply leaves them out") in capsys.readouterr().err

    _system, user = provider.calls[0]
    assert "## What code writes for you" in user
    assert '- drums: color Red, hpf_hz 40, dca ["Drums"], fader_db -144, ' \
           'main_routes [{"index":1}] (Drums)' in user
    assert '"aliases"' not in user and "## Category table" not in user

    plan = _plan(show)
    kick, bass, vox = plan["channels"]
    assert (kick["color"], kick["processing"]["hpf_hz"], kick["dca"]) == ("Red", 40, ["Drums"])
    assert bass["dca"] == ["Bass"] and vox["mute_group"] == ["Vocals"]
    assert all(c["fader"]["fader_db"] == -144 and c["main_routes"] == [{"index": 1}]
               for c in plan["channels"])
    record = plan["meta"]["resolved_conventions"]["category_table"]
    assert record == {"state": "valid", "applied": True, "categories": 3}
    assert sum(f["code"] == "reply.category-rule" for f in plan["meta"]["build_findings"]) == 3

    # The plan verifies as any other does.
    assert main(["verify", "--plan", str(show / "plan.json"),
                 "--input", str(show / "input.csv")]) == 0


@pytest.mark.parametrize("how", ["flag", "env"])
def test_the_switch_turns_the_table_off_and_the_prompt_back(show, monkeypatch, capsys, how):
    _write_resolved(show)
    full = copy.deepcopy(LEAN_REPLY)
    for channel in full["channels"]:
        channel["main_routes"] = [{"index": 1}]
    if how == "env":
        monkeypatch.setenv(category_table.ENV, "0")
    code, provider = _build(show, monkeypatch, full,
                            extra=["--no-category-rules"] if how == "flag" else [])
    assert code == 0
    off = "--no-category-rules" if how == "flag" else "ATOO_CATEGORY_RULES=0"
    assert f"INFO category table: off ({off})" in capsys.readouterr().err
    _system, user = provider.calls[0]
    assert "What code writes for you" not in user and '"aliases"' not in user
    assert "### Drums" in user                     # the prose still reaches it
    kick = _plan(show)["channels"][0]
    assert kick["dca"] == [] and kick["processing"]["hpf_hz"] is None
    record = _plan(show)["meta"]["resolved_conventions"]["category_table"]
    assert record == {"state": "valid", "applied": False, "categories": 3, "off": off}


def test_an_invalid_table_is_a_warning_and_the_build_goes_on_as_before(show, monkeypatch,
                                                                       capsys):
    _write_resolved(show, RESOLVED.replace('"hpf_hz": 40', '"hpf_hz": "forty"'))
    full = copy.deepcopy(LEAN_REPLY)
    for channel in full["channels"]:
        channel["main_routes"] = [{"index": 1}]
    code, provider = _build(show, monkeypatch, full)
    assert code == 0
    assert "category-table.invalid" in capsys.readouterr().err
    _system, user = provider.calls[0]
    assert "What code writes for you" not in user
    plan = _plan(show)
    assert plan["channels"][0]["dca"] == []
    assert any(f["code"] == "category-table.invalid" and f["severity"] == "warning"
               for f in plan["meta"]["build_findings"])
    assert plan["meta"]["resolved_conventions"]["category_table"]["state"] == "invalid"


def test_the_fixup_is_told_too_and_its_reply_is_filled_the_same_way(show, monkeypatch):
    _write_resolved(show)
    broken = copy.deepcopy(LEAN_REPLY)
    broken["channels"][0]["dca"] = ["Nowhere"]      # a DCA nothing declares: verify refuses
    code, provider = _build(show, monkeypatch, broken, LEAN_REPLY)
    assert code == 0
    assert provider.labels == ["generator", "fixup"]
    _system, fixup_user = provider.calls[1]
    assert "## What code writes for you" in fixup_user
    assert _plan(show)["channels"][0]["dca"] == ["Drums"]


def test_resolve_check_says_whether_the_table_is_valid(show, monkeypatch, capsys):
    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: pytest.fail("--check made a model call"))
    _write_resolved(show)
    assert main(["resolve", "--conventions", str(show / "conventions.md"), "--check"]) == 0
    assert "Category table valid, 3 categories" in capsys.readouterr().out

    _write_resolved(show, RESOLVED.replace('"aliases": ["bass"]', '"aliases": ["drums"]'))
    assert main(["resolve", "--conventions", str(show / "conventions.md"), "--check"]) == 2
    captured = capsys.readouterr()
    assert "Category table invalid" in captured.out
    assert "category-table.invalid" in captured.err


def test_the_resolve_prompt_asks_for_the_table_and_the_system_prompt_is_unchanged():
    system = conventions_resolve.resolve_system()
    assert "## Category table" in system and '"main_direct"' in system
    assert "What code writes for you" not in generate.generator_system("wing-compact")
