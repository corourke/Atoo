"""The input list's `order` column (FR-1.1, the maintainer 2026-10-09).

An optional column holding the band's own input number (their IEM split,
or how they patch a stage box), `-` to skip the row, or blank. A skipped
row stays in the file and is left out of the next build entirely: not
sent to the model, not built, not reconciled as missing, and named once
at INFO. The number never sets the desk channel; it reaches the model as
data with its row.

No model is called: the build tests use a scripted `FakeProvider`, as
`test_fixup_round.py` does. Nothing reads `examples/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from atoo import promote, source_edit
from atoo.ai_provider import FakeProvider
from atoo.cli import main
from atoo.input_list import (InputListError, build_text, load_input_list,
                                  parse_input_list, skip_finding, skipped_rows)
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"

LIST = """order,patch,name,category,type,model,phantom,notes
1,LCL 1,Kick,drums,Mic,Beta 91A,TRUE,
-,LCL 2,Spare Vox,vocals,Mic,,FALSE,headliner only
3,LCL 7,BassDI,bass,DI,,FALSE,
,LCL 12,VOX 1,vocals,Mic,,FALSE,
"""


# ---- parsing ----------------------------------------------------------------

def test_a_list_without_the_column_reads_as_before():
    rows = parse_input_list("name,category,type,phantom\nKick,drums,Mic,TRUE\n")
    assert [r.name for r in rows] == ["Kick"]
    assert rows[0].order == "" and not rows[0].skipped and rows[0].band_number is None


def test_the_cell_holds_a_number_a_skip_or_nothing():
    rows = parse_input_list(LIST, include_skipped=True)
    assert [(r.name, r.order, r.skipped, r.band_number) for r in rows] == [
        ("Kick", "1", False, 1),
        ("Spare Vox", "-", True, None),
        ("BassDI", "3", False, 3),
        ("VOX 1", "", False, None),
    ]


def test_a_skipped_row_is_left_out_of_what_every_reader_gets():
    assert [r.name for r in parse_input_list(LIST)] == ["Kick", "BassDI", "VOX 1"]
    assert [r.name for r in skipped_rows(LIST)] == ["Spare Vox"]


def test_the_column_can_be_anywhere_in_the_header():
    text = "name,category,type,phantom,order\nKick,drums,Mic,TRUE,-\nSnare,drums,Mic,TRUE,2\n"
    assert [r.name for r in parse_input_list(text)] == ["Snare"]


@pytest.mark.parametrize("cell", ["x", "0", "1.5", "3a", "--", "-1", "two"])
def test_anything_else_is_an_error_naming_the_row(cell):
    text = f"order,name,category,type,phantom\n1,Kick,drums,Mic,TRUE\n{cell},Snare,drums,Mic,TRUE\n"
    with pytest.raises(InputListError, match=r"row 3: column 'order'.*band's input number"):
        parse_input_list(text)


def test_spaces_around_the_cell_are_ignored():
    text = "order,name,category,type,phantom\n 4 ,Kick,drums,Mic,TRUE\n - ,Snare,drums,Mic,TRUE\n"
    rows = parse_input_list(text, include_skipped=True)
    assert [(r.order, r.skipped) for r in rows] == [("4", False), ("-", True)]


def test_a_skipped_row_is_still_checked_like_any_other():
    # Turning it back on must not surface an error nobody saw.
    text = "order,name,category,type,phantom\n1,Kick,drums,Mic,TRUE\n-,Spare,,Mic,FALSE\n"
    with pytest.raises(InputListError, match="row 3: 'category' is required"):
        parse_input_list(text)


def test_a_skipped_row_may_share_an_included_rows_name():
    # A festival list can keep two bands' "Kick" with one of them off.
    text = "order,name,category,type,phantom\n1,Kick,drums,Mic,TRUE\n-,Kick,drums,Mic,TRUE\n"
    assert [r.name for r in parse_input_list(text)] == ["Kick"]
    both = "order,name,category,type,phantom\n1,Kick,drums,Mic,TRUE\n2,Kick,drums,Mic,TRUE\n"
    with pytest.raises(InputListError, match="duplicate input name"):
        parse_input_list(both)


def test_every_row_skipped_is_an_error_but_the_editor_still_reads_it():
    text = "order,name,category,type,phantom\n-,Kick,drums,Mic,TRUE\n"
    with pytest.raises(InputListError, match="every row of the input list is skipped"):
        parse_input_list(text)
    assert [r.name for r in parse_input_list(text, include_skipped=True)] == ["Kick"]


def test_load_reads_the_file_the_same_way(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text(LIST)
    assert [r.name for r in load_input_list(str(path))] == ["Kick", "BassDI", "VOX 1"]
    assert len(load_input_list(str(path), include_skipped=True)) == 4


# ---- what the model is given -----------------------------------------------

def test_build_text_drops_skipped_rows_and_keeps_the_order_column():
    text = build_text(LIST)
    assert "Spare Vox" not in text
    assert text.splitlines()[0] == "order,patch,name,category,type,model,phantom,notes"
    assert text.splitlines()[1:] == [
        "1,LCL 1,Kick,drums,Mic,Beta 91A,TRUE,",
        "3,LCL 7,BassDI,bass,DI,,FALSE,",
        ",LCL 12,VOX 1,vocals,Mic,,FALSE,",
    ]


def test_build_text_is_the_file_to_the_byte_when_nothing_is_skipped():
    text = 'order,name,category,type,phantom,notes\r\n1,Kick,drums,Mic,yes,"a, b"\r\n'
    assert build_text(text) is text


def test_build_text_keeps_crlf_quoting_and_a_last_skipped_row():
    text = ('order,name,category,type,phantom,notes\r\n'
            '1,Kick,drums,Mic,yes,"two\r\nlines"\r\n'
            '-,Snare,drums,Mic,TRUE,\r\n')
    assert build_text(text) == ('order,name,category,type,phantom,notes\r\n'
                                '1,Kick,drums,Mic,yes,"two\r\nlines"\r\n')


def test_the_skip_finding_names_each_row():
    found = skip_finding(skipped_rows(LIST), where="input.csv")
    assert found.severity.value == "info" and found.code == "input-list.skipped"
    assert "Spare Vox" in found.message and "1 input-list row(s) skipped" in found.message
    assert skip_finding([]) is None


# ---- reconcile ---------------------------------------------------------------

def _smallband():
    """The frozen smallband plan (tests/fixtures/README.md)."""
    return json.loads((FIXTURES / "smallband.plan.json").read_text())


def _list_for(plan, skip=()):
    """An input list written from `plan`'s own channels, one row per
    socket, with the rows named in `skip` given `-`."""
    lines = ["order,patch,name,category,type,phantom"]
    for n, ch in enumerate(plan["channels"], 1):
        source = ch["source"]
        patch = ch["patch"]
        sockets = patch["sockets"] if source.get("stereo") else patch["sockets"][:1]
        for i, socket in enumerate(sockets):
            name = source["input"] if i == 0 else source["input"] + " R"
            if i == 0 and source.get("stereo"):
                ch["source"]["pair_input"] = name + " R"
            group = "AES50-A" if patch["group"] == "A" else patch["group"]
            order = "-" if source["input"] in skip else str(n)
            lines.append(f"{order},{group} {socket},{name},x,{source['type']},"
                         f"{'TRUE' if source.get('phantom') else 'FALSE'}")
    return "\n".join(lines) + "\n"


def _about(verdict, name):
    return [f for f in verdict.findings if repr(name) in f.message or f"[{name}]" in f.where]


def test_reconcile_does_not_count_a_skipped_row_as_missing():
    plan = _smallband()
    text = _list_for(plan, skip=("HiHat",))
    # The baseline: with every row in, nothing is said about HiHat.
    assert _about(verify_plan(plan, parse_input_list(_list_for(plan))), "HiHat") == []
    plan["channels"] = [c for c in plan["channels"] if c["source"]["input"] != "HiHat"]
    verdict = verify_plan(plan, parse_input_list(text))
    assert _about(verdict, "HiHat") == [], [f.code for f in verdict.findings]
    # Without the skip, the same plan is missing HiHat -- so the check ran.
    missing = _about(verify_plan(plan, parse_input_list(_list_for(_smallband()))), "HiHat")
    assert missing and missing[0].severity == "error"


def test_a_plan_built_before_the_skip_is_told_so_not_called_invented():
    plan = _smallband()
    verdict = verify_plan(plan, parse_input_list(_list_for(plan, skip=("HiHat",))))
    found = _about(verdict, "HiHat")
    # A WARNING: the desk works, it builds a strip nobody plugs into.
    assert [(f.severity, f.code) for f in found] == [("warning", "reconcile.skipped-source")]
    assert "skipped on the input list" in found[0].message
    assert "rebuild" in found[0].fix


# ---- the build ---------------------------------------------------------------

@dataclass
class _Recorder(FakeProvider):
    script: list = field(default_factory=list)
    model: str = "claude-haiku-4-5"

    def complete(self, *, system, user, response_schema=None, label=""):
        self.response = self.script[len(self.calls)]
        return super().complete(system=system, user=user,
                                response_schema=response_schema, label=label)


def _reply() -> dict:
    reply = json.loads((FIXTURES / "haiku45_festival_dangling_dca.reply.json").read_text())
    for channel in reply["channels"]:
        channel["main_routes"] = channel.get("main_routes") or [{"index": 1}]
        if channel["input"] == "BassDI":
            channel["dca"] = ["Bass"]
    return reply


def test_a_build_sends_the_order_numbers_and_leaves_skipped_rows_out(
        tmp_path, monkeypatch, capsys):
    (tmp_path / "input.csv").write_text(LIST)
    (tmp_path / "conventions.md").write_text(
        "# House conventions\n\n- DCAs: Drums, Bass, Vocals.\n- Main is on LCL 7/8.\n"
        "- Patch the inputs according to the band's channel order numbers.\n")
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")
    provider = _Recorder(script=[json.dumps(_reply())])
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)

    code = main(["build", "--console-model", "wing-compact",
                 "--input", str(tmp_path / "input.csv"),
                 "--conventions", str(tmp_path / "conventions.md"),
                 "--out", str(tmp_path / "plan.json")])
    err = capsys.readouterr().err
    assert code == 0, err

    # The model saw the order column with its numbers, and no skipped row.
    _system, user = provider.calls[0]
    assert "order,patch,name,category,type,model,phantom,notes" in user
    assert "1,LCL 1,Kick,drums" in user and "3,LCL 7,BassDI" in user
    assert "Spare Vox" not in user
    # It was told what the column means, and that it is not a channel number.
    system = provider.calls[0][0]
    assert "band's own number for that input" in system

    # One INFO, said and recorded; nothing built for it, nothing missing.
    assert "INFO 1 input-list row(s) skipped" in err and "Spare Vox" in err
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert all(c["name"] != "Spare Vox" for c in plan["channels"])
    found = [f for f in plan["meta"]["build_findings"] if f["code"] == "input-list.skipped"]
    assert len(found) == 1 and "Spare Vox" in found[0]["message"]
    assert not any("Spare Vox" in str(f) for f in plan["meta"]["verify_findings"]["errors"])
    assert not any("Spare Vox" in str(f) for f in plan["meta"]["verify_findings"]["warnings"])
    # The file itself still holds the row.
    assert "-,LCL 2,Spare Vox" in (tmp_path / "input.csv").read_text()


# ---- saving from the editor ---------------------------------------------------

def test_a_save_writes_the_rows_in_their_new_order_and_keeps_the_header():
    text = LIST
    rows = [{"line": 2, "values": {}}, {"line": 0, "values": {}},
            {"line": None, "values": {"order": "2", "name": "Snare", "category": "drums",
                                      "type": "Mic", "phantom": "TRUE"}},
            {"line": 1, "values": {"order": ""}}, {"line": 3, "values": {}}]
    out, summary = source_edit.splice_input_list(text, rows)
    lines = out.splitlines()
    assert lines[0] == "order,patch,name,category,type,model,phantom,notes"
    assert lines[1] == "3,LCL 7,BassDI,bass,DI,,FALSE,"
    assert lines[2] == "1,LCL 1,Kick,drums,Mic,Beta 91A,TRUE,"
    assert lines[3] == "2,,Snare,drums,Mic,,TRUE,"
    assert lines[4] == ",LCL 2,Spare Vox,vocals,Mic,,FALSE,headliner only"   # un-skipped
    assert summary["added"] == 1 and summary["changed"] == ["Spare Vox"]


def test_a_save_that_adds_the_column_puts_it_first():
    text = "patch,name,category,type,phantom,notes\nLCL 1,Kick,drums,Mic,TRUE,\nLCL 2,Snare,drums,Mic,TRUE,\n"
    out, summary = source_edit.splice_input_list(
        text, [{"line": 0, "values": {"order": "-"}}, {"line": 1, "values": {}}])
    assert summary["columns_added"] == ["order"]
    assert out == ("order,patch,name,category,type,phantom,notes\n"
                   "-,LCL 1,Kick,drums,Mic,TRUE,\n,LCL 2,Snare,drums,Mic,TRUE,\n")
    assert [r.name for r in parse_input_list(out)] == ["Snare"]


# ---- promote --------------------------------------------------------------------

def test_promote_says_when_the_input_it_would_add_is_a_skipped_row(tmp_path, monkeypatch):
    (tmp_path / "input.csv").write_text(LIST)
    header = LIST.splitlines()[0].split(",")

    class _Entry:
        id = "j1"
        timestamp = "2026-10-10T00:00:00"
        aborted = False
        change = {"text": "add Spare Vox on LCL 2"}

    monkeypatch.setattr(promote, "find_change", lambda d, ref: _Entry())
    monkeypatch.setattr(promote.journal_stack, "change_label", lambda c: "patch 1")
    monkeypatch.setattr(promote.journal_stack, "reversed_by", lambda d, e: None)
    monkeypatch.setattr(promote, "_read_payload", lambda e: {})
    monkeypatch.setattr(promote, "_added_channels", lambda p: [
        {"name": "Spare Vox", "source": {"input": "Spare Vox"},
         "patch": {"group": "LCL", "sockets": [2]}}])
    monkeypatch.setattr(promote, "_desk_channels", lambda p: [])
    result = promote.promotion(tmp_path, "1")
    assert result.rows == []
    assert result.header == header
    assert any("skipped ('-' in its order cell)" in line for line in result.infos)
