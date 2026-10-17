"""Editing the three files a build reads, from the Setup page, and the plan going Stale when one of them changes.

The maintainer edits these files in Obsidian as well as on the page, so four
things are tested hardest:

* **Round-trip fidelity.** Saving a file nobody changed leaves it
  byte-identical (nothing is written); steps 01 and 03 save the whole
  file as their one editor holds it (no sections
  view), keeping CRLF line endings, comments and whatever headings --
  or none -- the file has. input.csv is spliced by row.
* **An outside edit is never overwritten.** A save whose file changed on
  disk since the page read it is a 409, and the file keeps the other edit.
* **A stale page cannot save** (FR-6.11): a save naming another bundle,
  or none, is a 409 and writes nothing.
* **Staleness by content.** A plan built before one of its inputs changed
  says so (`plan_freshness`); a plan too old to have recorded a file says
  "cannot tell", never "stale".

Every bundle here is built in the test -- nothing under `examples/` is
read (tests/conftest.py enforces that).
"""

from __future__ import annotations

import json

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import input_list, plan_freshness, source_edit  # noqa: E402
from atoo.webui import create_app  # noqa: E402
import test_webui as webui_tests  # noqa: E402

# A file with everything a careless save would lose: prose before the
# first heading, a comment, a heading that is not canonical, a
# commented-out heading, trailing spaces, CRLF line endings, and a file
# ending with no final newline.
TRICKY = (
    "# house-rules.md\r\n"
    "Prose before any heading.\r\n"
    "<!-- a note to myself -->\r\n"
    "\r\n"
    "## Inputs\r\n"
    "Patch in list order.   \r\n"
    "\r\n"
    "## Stage Notes\r\n"
    "Not one of the eight.\r\n"
    "<!--\r\n"
    "## DCAs\r\n"
    "-->\r\n"
    "\r\n"
    "## Channels\r\n"
    "Drums first."
)


# ======================================================================
# source_edit: the whole-file save, as text
# ======================================================================


def test_an_unchanged_save_is_the_same_text():
    # The page's textarea hands back \n; the file is CRLF. Same words,
    # so nothing changes.
    out, changed = source_edit.replace_text(TRICKY, TRICKY.replace("\r\n", "\n"))
    assert out is TRICKY and changed is False


def test_a_changed_save_keeps_the_files_line_ending_and_everything_else():
    new = TRICKY.replace("\r\n", "\n").replace("Drums first.", "Drums first.\nThen bass.")
    out, changed = source_edit.replace_text(TRICKY, new)
    assert changed is True
    assert out == TRICKY.replace("Drums first.", "Drums first.\r\nThen bass.")


def test_a_file_with_no_headings_saves_like_any_other():
    out, changed = source_edit.replace_text("Kick first.\n", "Kick first.\nSnare second.\n")
    assert (out, changed) == ("Kick first.\nSnare second.\n", True)


def test_an_empty_file_takes_whatever_is_written_into_it():
    out, changed = source_edit.replace_text("", "## Inputs\nPatch in list order.\n")
    assert (out, changed) == ("## Inputs\nPatch in list order.\n", True)


# ---- the input list -------------------------------------------------------

CSV = (
    "name,socket,category,type,model,phantom,notes,rig\r\n"  # not canonical order
    '"Kick",AES50-A 1,drums,Mic,,yes,,drum riser\r\n'
    "Snare,AES50-A 2,drums,Mic,,FALSE,\"top,\r\nand bottom\",drum riser\r\n"
    "MLD VOX,AES50-A 9,vocals,Mic,,TRUE,lead,\r\n"
)


def _rows(text):
    _header, records, _end = source_edit.read_records(text)
    return [{"line": i, "values": {}} for i in range(len(records))]


def test_an_unchanged_input_list_is_the_same_text():
    out, summary = source_edit.splice_input_list(CSV, _rows(CSV))
    assert out == CSV
    assert summary == {"changed": [], "added": 0, "removed": 0, "columns_added": []}


def test_one_row_edited_changes_only_that_row_in_the_files_own_column_order():
    rows = _rows(CSV)
    rows[2]["values"] = {"name": "LEAD VOX"}
    out, summary = source_edit.splice_input_list(CSV, rows)
    assert summary["changed"] == ["LEAD VOX"]
    # The file's own column order and CRLF; the other rows' quoting, the
    # "yes" spelling and the multi-line field are untouched.
    assert out == CSV.replace("MLD VOX,AES50-A 9,vocals,Mic,,TRUE,lead,\r\n",
                              "LEAD VOX,AES50-A 9,vocals,Mic,,TRUE,lead,\r\n")


def test_a_column_the_page_does_not_show_is_carried_through_a_changed_row():
    rows = _rows(CSV)
    rows[0]["values"] = {"phantom": "FALSE"}
    out, _ = source_edit.splice_input_list(CSV, rows)
    assert 'Kick,AES50-A 1,drums,Mic,,FALSE,,drum riser\r\n' in out
    assert out.count("\r\n") == CSV.count("\r\n")


def test_rows_added_and_removed():
    rows = _rows(CSV)
    del rows[1]
    rows.append({"line": None, "values": {"name": "Keys L", "category": "keys",
                                          "type": "DI", "phantom": "FALSE"}})
    out, summary = source_edit.splice_input_list(CSV, rows)
    assert summary["added"] == 1 and summary["removed"] == 1
    assert out == ('name,socket,category,type,model,phantom,notes,rig\r\n'
                   '"Kick",AES50-A 1,drums,Mic,,yes,,drum riser\r\n'
                   "MLD VOX,AES50-A 9,vocals,Mic,,TRUE,lead,\r\n"
                   "Keys L,,keys,DI,,FALSE,,\r\n")


def test_a_file_with_no_final_newline_keeps_none():
    text = "socket,name,category,type,phantom\nLCL 1,Kick,drums,Mic,FALSE"
    out, _ = source_edit.splice_input_list(
        text, [{"line": 0, "values": {}},
               {"line": None, "values": {"name": "Snare", "category": "drums", "type": "Mic",
                                         "phantom": "FALSE"}}])
    assert out == text + "\n,Snare,drums,Mic,FALSE"


@pytest.mark.parametrize("sent", ["patch", "socket"])
def test_a_value_for_a_column_the_file_lacks_adds_the_column(sent):
    """A new column is written under the current name, `patch`, whichever name the page sent the value under."""
    text = "name,category,type,phantom\nKick,drums,Mic,FALSE\n"
    out, summary = source_edit.splice_input_list(text, [{"line": 0, "values": {sent: "LCL 1"}}])
    assert summary["columns_added"] == ["patch"]
    assert out == "name,category,type,phantom,patch\nKick,drums,Mic,FALSE,LCL 1\n"


@pytest.mark.parametrize("header", ["socket", "patch"])
def test_a_save_keeps_the_patch_columns_header_byte_for_byte(header):
    """The page sends the patch as `patch`; a file headed
    `socket` (every list written before 2026-09-28, the maintainer's bundles
    among them) has it written into its own `socket` column, and its
    header line is not touched. Nor is any row the Save did not change."""
    text = (f"{header},name,category,type,model,phantom,notes\r\n"
            "AES50-A 1,Kick,drums,Mic,Beta91A,TRUE,\r\n"
            ",Snare,drums,Mic,,FALSE,\r\n")
    out, summary = source_edit.splice_input_list(text, [
        {"line": 0, "values": {}},
        {"line": 1, "values": {"patch": "AES50-A 2"}},
        {"line": None, "values": {"patch": "LCL 3", "name": "Vox", "category": "vocals",
                                  "type": "Mic", "phantom": "TRUE"}},
    ])
    assert summary["columns_added"] == []
    lines = out.split("\r\n")
    assert lines[0] == f"{header},name,category,type,model,phantom,notes"
    assert lines[1] == "AES50-A 1,Kick,drums,Mic,Beta91A,TRUE,"
    assert lines[2] == "AES50-A 2,Snare,drums,Mic,,FALSE,"
    assert lines[3] == "LCL 3,Vox,vocals,Mic,,TRUE,"
    # What was saved reads back as it was meant.
    assert [r.patch for r in input_list.parse_input_list(out)] == ["AES50-A 1", "AES50-A 2", "LCL 3"]


def test_a_save_that_changes_nothing_returns_the_file_itself():
    text = "socket,name,category,type,phantom\nLCL 1,Kick,drums,Mic,FALSE\n"
    out, _ = source_edit.splice_input_list(text, [{"line": 0, "values": {"patch": "LCL 1"}}])
    assert out == text


def test_a_row_naming_a_record_that_is_gone_is_refused():
    with pytest.raises(source_edit.EditError, match="reload it"):
        source_edit.splice_input_list(CSV, [{"line": 7, "values": {}}])


# ======================================================================
# The endpoints
# ======================================================================

HOUSE = webui_tests.HOUSE_CONVENTIONS
SHOW = webui_tests.SHOW_INSTRUCTIONS


@pytest.fixture
def show(tmp_path):
    directory = webui_tests._build_bundle(tmp_path)
    house = webui_tests._house(tmp_path)
    app = create_app(initial_bundle=str(directory), initial_conventions=str(house))
    with fastapi_testclient.TestClient(app) as c:
        c.directory, c.house = directory, house
        yield c


def _source(c, slot):
    return c.get("/api/build/sources").json()[slot]


def _save(c, slot, text=None, **over):
    source = _source(c, slot)
    body = {"slot": slot, "expected_path": source["path"], "expected_sha256": source["sha256"],
            "expected_bundle": str(c.directory), "text": text}
    body.update(over)
    return c.post("/api/build/sections/save", json=body)


def test_the_sources_carry_what_an_editor_needs(show):
    data = show.get("/api/build/sources").json()
    for slot in ("conventions", "input_list", "instructions"):
        assert len(data[slot]["sha256"]) == 64, slot
    assert data["instructions"]["text"] == (show.directory / "instructions.md").read_text()
    assert data["input_list"]["header"][:2] == ["socket", "name"]
    assert data["input_list"]["records"][0]["line"] == 0
    assert data["plan_freshness"]["state"] == "none"
    # No sections view any more: nothing keyed on
    # headings reaches the page.
    assert "sections" not in data["conventions"] and "sections" not in data["instructions"]
    assert "canonical_sections" not in data


def test_the_sources_carry_the_examples_as_suggestions_only(show):
    from atoo.webui import conventions_example, instructions_example
    data = show.get("/api/build/sources").json()
    assert data["examples"] == {
        "conventions": conventions_example(show.house.name),
        "instructions": instructions_example(show.directory.name),
    }
    # Offering them wrote nothing.
    assert (show.directory / "instructions.md").read_text() == SHOW


def test_saving_the_instructions_writes_the_whole_file_as_given(show):
    path = show.directory / "instructions.md"
    source = _source(show, "instructions")
    new = source["text"].replace("MLD VOX is the lead vocal -- alert if it is muted.\n",
                                 "Alert if MLD VOX is muted.\nAnd Kick.\n")
    assert new != source["text"]
    r = _save(show, "instructions", new)
    assert r.status_code == 200, r.json()
    assert r.json()["saved"] == {"slot": "instructions", "path": str(path), "changed": True}
    assert path.read_text() == new
    # The page's re-read is in the answer: the new text, and a new hash.
    assert r.json()["instructions"]["sha256"] != source["sha256"]
    assert "Saved touringband/instructions.md." in r.json()["message"]


def test_saving_with_nothing_changed_writes_nothing(show):
    path = show.directory / "instructions.md"
    mtime = path.stat().st_mtime_ns
    r = _save(show, "instructions", _source(show, "instructions")["text"])
    assert r.status_code == 200
    assert r.json()["saved"]["changed"] is False
    assert "Nothing to save" in r.json()["message"]
    assert path.stat().st_mtime_ns == mtime


def test_a_crlf_file_with_comments_and_odd_headings_round_trips_through_the_endpoint(show):
    path = show.directory / "instructions.md"
    path.write_bytes(TRICKY.encode())
    source = _source(show, "instructions")
    # What a textarea hands back: the text as read, \n line endings.
    r = _save(show, "instructions", source["text"])
    assert r.json()["saved"]["changed"] is False
    assert path.read_bytes() == TRICKY.encode()
    r = _save(show, "instructions", source["text"] + "\n\n## Busses\nMON 1-4, mono.\n")
    assert r.status_code == 200, r.json()
    assert path.read_bytes().decode() == TRICKY + "\r\n\r\n## Busses\r\nMON 1-4, mono.\r\n"


def test_a_file_with_no_headings_is_edited_and_saved_like_any_other(show):
    path = show.directory / "instructions.md"
    path.write_text("Kick first.\n")
    r = _save(show, "instructions", "Kick first.\nNo talkback tonight.\n")
    assert r.status_code == 200, r.json()
    assert path.read_text() == "Kick first.\nNo talkback tonight.\n"
    data = r.json()
    assert not [f for f in data["findings"] if f["code"].startswith("conventions.")]


def test_a_save_without_the_text_is_refused(show):
    path = show.directory / "instructions.md"
    before = path.read_bytes()
    r = _save(show, "instructions", None)
    assert r.status_code == 400 and "whole file" in r.json()["error"]
    assert path.read_bytes() == before


def test_the_house_file_needs_house_confirmed(show):
    before = show.house.read_bytes()
    text = _source(show, "conventions")["text"].replace(
        "Main is the full mix.", "Main is the full mix, EQed for the recording.")
    r = _save(show, "conventions", text)
    assert r.status_code == 400
    assert "house_confirmed" in r.json()["error"]
    assert show.house.read_bytes() == before
    r = _save(show, "conventions", text, house_confirmed=True)
    assert r.status_code == 200, r.json()
    assert show.house.read_bytes() == before.replace(b"Main is the full mix.",
                                                     b"Main is the full mix, EQed for the recording.")
    assert "every show that names this house file" in r.json()["message"]


def test_a_file_changed_on_disk_since_the_page_read_it_is_never_overwritten(show):
    path = show.directory / "instructions.md"
    source = _source(show, "instructions")          # the page reads the file...
    path.write_text(SHOW + "\n## Output\nEdited in Obsidian.\n")   # ...Obsidian saves it...
    outside = path.read_bytes()
    r = _save(show, "instructions", "From the page.",
              expected_sha256=source["sha256"])     # ...and the page saves what it read
    assert r.status_code == 409
    body = r.json()
    assert body["stale"] == "file" and body["slot"] == "instructions"
    assert "changed on disk after this page read it" in body["error"]
    assert "Nothing was saved" in body["error"]
    assert path.read_bytes() == outside


def test_a_save_that_does_not_say_what_it_read_is_refused(show):
    r = _save(show, "instructions", "x", expected_sha256=None)
    assert r.status_code == 409 and r.json()["stale"] == "file"


def test_a_save_from_a_page_reading_another_file_is_refused(show, tmp_path):
    r = _save(show, "instructions", "x", expected_path=str(tmp_path / "elsewhere.md"))
    assert r.status_code == 409 and r.json()["stale"] == "file"


@pytest.mark.parametrize("expected", [None, "", "/some/other/bundle"])
def test_a_save_from_a_stale_page_is_refused(show, expected):
    path = show.directory / "instructions.md"
    before = path.read_bytes()
    r = _save(show, "instructions", "x", expected_bundle=expected)
    assert r.status_code == 409
    assert r.json()["stale"] == "bundle"
    assert "Nothing was saved" in r.json()["error"]
    assert path.read_bytes() == before


def test_an_instructions_tile_pointed_outside_the_bundle_is_not_edited_here(show, tmp_path):
    other = tmp_path / "other.md"
    other.write_text("## Channels\nElsewhere.\n")
    show.post("/api/build/sources/load", json={"slot": "instructions", "path": str(other)})
    r = _save(show, "instructions", "x")
    assert r.status_code == 400 and "bundle's files" in r.json()["error"]
    assert other.read_text() == "## Channels\nElsewhere.\n"


# ---- step 02 -------------------------------------------------------------

def _save_rows(c, rows, **over):
    source = _source(c, "input_list")
    body = {"expected_path": source["path"], "expected_sha256": source["sha256"],
            "expected_bundle": str(c.directory), "rows": rows}
    body.update(over)
    return c.post("/api/build/input-list/save", json=body)


def test_saving_an_input_row_changes_only_that_row(show):
    path = show.directory / "input.csv"
    before = path.read_text()
    r = _save_rows(show, [{"line": 0, "values": {"model": "Beta 91A"}}, {"line": 1, "values": {}}])
    assert r.status_code == 200, r.json()
    assert path.read_text() == before.replace("AES50-A 1,Kick,drums,Mic,,FALSE,",
                                              "AES50-A 1,Kick,drums,Mic,Beta 91A,FALSE,")
    assert r.json()["saved"]["rows_changed"] == ["Kick"]
    assert r.json()["input_list"]["rows"][0]["model"] == "Beta 91A"


def test_an_unchanged_input_list_save_writes_nothing(show):
    path = show.directory / "input.csv"
    mtime = path.stat().st_mtime_ns
    r = _save_rows(show, [{"line": 0, "values": {}}, {"line": 1, "values": {}}])
    assert r.status_code == 200 and r.json()["saved"]["changed"] is False
    assert path.stat().st_mtime_ns == mtime


def test_an_invalid_row_is_saved_and_reported_as_a_finding_not_refused(show):
    """The design (setup-ui-design.md §6.2): warn, never silently refuse.
    The engine's own loader reads the file back, and its verdict -- naming
    the row -- is an ERROR in the dock."""
    r = _save_rows(show, [{"line": 0, "values": {}}, {"line": 1, "values": {}},
                          {"line": None, "values": {"name": "", "category": "keys",
                                                    "type": "DI", "phantom": "FALSE"}}])
    assert r.status_code == 200, r.json()
    data = r.json()
    assert data["input_list"]["rows"] is None
    codes = [f["code"] for f in data["input_list"]["findings"]]
    assert "input-list.invalid" in codes
    assert "row 4" in next(f["message"] for f in data["input_list"]["findings"]
                           if f["code"] == "input-list.invalid")
    assert "does not load as it stands" in data["message"]
    # ...and the lenient read still shows every row, so it can be fixed.
    assert len(data["input_list"]["records"]) == 3


def test_an_invalid_input_list_finding_names_the_file_as_the_tile_does(show):
    """The finding says `<bundle>/input.csv`, not
    the absolute path -- a dock line is what gets pasted into a request
    for help, and the home folder has no business in it."""
    r = _save_rows(show, [{"line": 0, "values": {}}, {"line": 1, "values": {}},
                          {"line": None, "values": {"name": "Click Track", "category": "",
                                                    "type": "", "phantom": "FALSE"}}])
    finding = next(f for f in r.json()["input_list"]["findings"]
                   if f["code"] == "input-list.invalid")
    assert finding["where"] == f"{show.directory.name}/input.csv"
    assert finding["where"] == r.json()["input_list"]["display_path"]
    assert str(show.directory) not in json.dumps(finding)
    # Both blank columns in the one message.
    assert finding["message"] == "row 4: 'category' and 'type' are required and cannot be blank"


def test_the_input_list_editor_marks_required_cells_and_asks_before_saving_a_broken_list(show):
    """An earlier change, over the served assets (the Python suite cannot run the
    page): Name, Category and Type carry a "required" placeholder and an
    outline while empty, and Save warns once before writing a list those
    marks say will not load -- a second Save writes it anyway."""
    js = show.get("/static/shell.js").text
    css = show.get("/static/styles.css").text
    assert 'const REQUIRED_INPUT_COLUMNS = ["name", "category", "type"];' in js
    assert 'input.placeholder = "required";' in js
    assert 'cell.classList.toggle("is-required-empty", empty);' in js
    assert "if (problems.length && summary !== unloadableWarned) {" in js
    assert "or press Save again to save it anyway." in js
    assert ".it td input.is-required-empty { border-color: var(--warning-fg); }" in css


def test_an_input_list_changed_on_disk_is_never_overwritten(show):
    path = show.directory / "input.csv"
    source = _source(show, "input_list")
    path.write_text(path.read_text() + "LCL 5,Keys L,keys,DI,,FALSE,\n")
    outside = path.read_bytes()
    r = _save_rows(show, [{"line": 0, "values": {"name": "Kick In"}}],
                   expected_sha256=source["sha256"])
    assert r.status_code == 409 and r.json()["stale"] == "file"
    assert path.read_bytes() == outside


def test_an_input_list_save_from_a_stale_page_is_refused(show):
    r = _save_rows(show, [{"line": 0, "values": {"name": "Kick In"}}], expected_bundle="/elsewhere")
    assert r.status_code == 409 and r.json()["stale"] == "bundle"


# ======================================================================
# Staleness
# ======================================================================


def _plan_with(tmp_path, directory, house, *, input_record=True, instructions=True):
    from atoo import conventions_ref

    stack = [{"path": str(house), "role": "conventions", "source": "test",
              **conventions_ref.layer_record(house, directory)}]
    if instructions:
        stack.append({"path": str(directory / "instructions.md"), "role": "instructions",
                      "source": "test",
                      **conventions_ref.layer_record(directory / "instructions.md", directory)})
    meta = {"generated_at": "2026-09-25T12:00:00+00:00", "conventions_stack": stack}
    if input_record:
        meta["input_list"] = plan_freshness.input_list_record(directory / "input.csv", directory)
    plan = {"channels": [], "dcas": {}, "mute_groups": {}, "busses": {}, "outputs": {},
            "meta": meta}
    (directory / "plan.json").write_text(json.dumps(plan))
    return plan


def _assess(plan, directory, house):
    return plan_freshness.assess(plan, conventions=house,
                                 instructions=directory / "instructions.md",
                                 input_list=directory / "input.csv")


def test_a_plan_whose_inputs_hash_as_recorded_is_current(tmp_path):
    directory = webui_tests._build_bundle(tmp_path)
    house = webui_tests._house(tmp_path)
    plan = _plan_with(tmp_path, directory, house)
    assert _assess(plan, directory, house)["state"] == "current"


@pytest.mark.parametrize("change, slot, code", [
    (lambda d, h: (d / "input.csv").write_text("socket,name,category,type,phantom\n"), "input_list",
     "plan.input-list-edited"),
    (lambda d, h: h.write_text("## Inputs\nNew.\n"), "conventions", "plan.conventions-edited"),
    (lambda d, h: (d / "instructions.md").write_text("## Channels\nNew.\n"), "instructions",
     "plan.instructions-edited"),
    (lambda d, h: (d / "instructions.md").unlink(), "instructions", "plan.instructions-gone"),
])
def test_a_changed_input_makes_the_plan_stale_and_names_it(tmp_path, change, slot, code):
    directory = webui_tests._build_bundle(tmp_path)
    house = webui_tests._house(tmp_path)
    plan = _plan_with(tmp_path, directory, house)
    change(directory, house)
    result = _assess(plan, directory, house)
    assert result["state"] == "stale"
    assert [(r["slot"], r["code"]) for r in result["reasons"]] == [(slot, code)]


def test_instructions_added_after_the_build_make_it_stale(tmp_path):
    directory = webui_tests._build_bundle(tmp_path, instructions=None)
    house = webui_tests._house(tmp_path)
    plan = _plan_with(tmp_path, directory, house, instructions=False)
    (directory / "instructions.md").write_text("## Channels\nNew.\n")
    result = _assess(plan, directory, house)
    assert [r["code"] for r in result["reasons"]] == ["plan.instructions-added"]


def test_touching_a_file_without_changing_it_is_not_stale(tmp_path):
    import os

    directory = webui_tests._build_bundle(tmp_path)
    house = webui_tests._house(tmp_path)
    plan = _plan_with(tmp_path, directory, house)
    for path in (house, directory / "input.csv", directory / "instructions.md"):
        os.utime(path, (4_000_000_000, 4_000_000_000))
    assert _assess(plan, directory, house)["state"] == "current"


def test_a_plan_that_records_no_input_list_is_cannot_tell_not_stale(tmp_path):
    directory = webui_tests._build_bundle(tmp_path)
    house = webui_tests._house(tmp_path)
    plan = _plan_with(tmp_path, directory, house, input_record=False)
    (directory / "input.csv").write_text("socket,name,category,type,phantom\n")
    result = _assess(plan, directory, house)
    assert result["state"] == "unknown"
    assert [u["slot"] for u in result["unknown"]] == ["input_list"]
    assert result["reasons"] == []


def test_a_plan_from_before_any_fingerprints_is_cannot_tell(tmp_path):
    directory = webui_tests._build_bundle(tmp_path)
    house = webui_tests._house(tmp_path)
    plan = {"meta": {"conventions_stack": [{"path": "conventions.md", "role": "conventions",
                                            "source": "--conventions"}]}}
    result = _assess(plan, directory, house)
    assert result["state"] == "unknown"
    assert {u["slot"] for u in result["unknown"]} == {"conventions", "input_list"}


def test_no_plan_is_none():
    assert plan_freshness.assess(None, conventions=None, instructions=None,
                                 input_list=None)["state"] == "none"


def test_a_save_makes_the_open_bundles_plan_stale_and_the_preflight_says_so(tmp_path):
    directory = webui_tests._build_bundle(tmp_path)
    house = webui_tests._house(tmp_path)
    _plan_with(tmp_path, directory, house)
    app = create_app(initial_bundle=str(directory), initial_conventions=str(house))
    with fastapi_testclient.TestClient(app) as c:
        c.directory = directory
        assert c.get("/api/build/sources").json()["plan_freshness"]["state"] == "current"
        pre = c.get("/api/apply/preflight").json()
        assert "plan.older-than-inputs" not in [f["code"] for f in pre["findings"]]

        r = _save_rows(c, [{"line": 0, "values": {"name": "Kick In"}}, {"line": 1, "values": {}}])
        fresh = r.json()["plan_freshness"]
        assert fresh["state"] == "stale"
        assert fresh["reasons"][0]["message"] == \
            "touringband/input.csv changed after this plan was built."
        assert fresh["plan_path"] == str(directory / "plan.json")

        pre = c.get("/api/apply/preflight").json()
        stale = [f for f in pre["findings"] if f["code"] == "plan.older-than-inputs"]
        assert len(stale) == 1 and stale[0]["severity"] == "warning"
        assert "touringband/input.csv changed after this plan was built." in stale[0]["message"]
        assert pre["plan_freshness"]["state"] == "stale"
        # Announced, never blocking: a stale plan is not an ERROR.
        assert pre["errors"] == 0 or all(f["code"] != "plan.older-than-inputs"
                                         for f in pre["findings"] if f["severity"] == "error")


def test_the_cli_apply_announces_a_stale_bundle_plan(tmp_path):
    from atoo import bundle
    from atoo.cli import _plan_inputs_changed

    directory = webui_tests._build_bundle(tmp_path)
    house = webui_tests._house(tmp_path)
    plan = _plan_with(tmp_path, directory, house)
    show = bundle.load(directory)
    assert _plan_inputs_changed(plan, show) is None
    (directory / "input.csv").write_text((directory / "input.csv").read_text() + "\n")
    finding = _plan_inputs_changed(plan, show)
    assert finding.code == "plan.older-than-inputs" and finding.severity == "warning"
    assert _plan_inputs_changed(plan, None) is None


# ---- build, edit, rebuild -------------------------------------------------

def test_a_build_records_the_input_list_edit_makes_it_stale_rebuild_makes_it_current(
        webui_run_client):
    c = webui_run_client
    r = c.post("/api/build/run", json={"console_model": "wing-compact",
                                       "expected_bundle": str(c.directory)})
    assert r.status_code == 200, r.json()
    assert webui_tests._wait_for_build(c)["state"] == "done"
    plan = json.loads((c.directory / "plan.json").read_text())
    record = plan["meta"]["input_list"]
    assert record["bundle_relative_path"] == "input.csv"
    assert len(record["sha256"]) == 64
    assert c.get("/api/build/sources").json()["plan_freshness"]["state"] == "current"

    source = _source(c, "input_list")
    r = c.post("/api/build/input-list/save", json={
        "expected_path": source["path"], "expected_sha256": source["sha256"],
        "expected_bundle": str(c.directory),
        "rows": [{"line": r["line"], "values": {"notes": "edited"} if r["line"] == 0 else {}}
                 for r in source["records"]]})
    assert r.status_code == 200, r.json()
    assert r.json()["plan_freshness"]["state"] == "stale"

    assert c.post("/api/build/run", json={"console_model": "wing-compact"}).status_code == 200
    assert webui_tests._wait_for_build(c)["state"] == "done"
    assert c.get("/api/build/sources").json()["plan_freshness"]["state"] == "current"


def test_a_build_from_a_page_showing_another_bundle_is_refused(webui_run_client):
    r = webui_run_client.post("/api/build/run", json={"console_model": "wing-compact",
                                                      "expected_bundle": "/another/show"})
    assert r.status_code == 409 and r.json()["stale"] == "bundle"
    assert "Nothing was built" in r.json()["error"]
    assert not (webui_run_client.directory / "plan.json").exists()


@pytest.fixture
def webui_run_client(tmp_path, stub_build, monkeypatch):
    stub_build("touringband")
    monkeypatch.setattr("atoo.generate.draft_watch_conditions", lambda *a, **k: [])
    directory = webui_tests._touringband_bundle(tmp_path)
    app = create_app(initial_bundle=str(directory),
                     initial_conventions=str(webui_tests._house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        c.directory = directory
        yield c


# ======================================================================
# The served assets -- the Python suite cannot otherwise see the browser
# ======================================================================


def test_the_editing_controls_are_in_the_served_page(show):
    html = show.get("/").text
    for element_id in (
        "conv-ro-badge", "conv-save-btn", "conv-cancel-btn", "conv-text",
        "conv-edit-warning", "conv-save-note", "conv-save-text", "conv-save-reload",
        "conv-example", "conv-example-text", "conv-example-insert",
        "instr-save-btn", "instr-cancel-btn", "instr-text",
        "instr-edit-badge", "instr-save-note", "instr-save-text", "instr-save-reload",
        "instr-example", "instr-example-text", "instr-example-insert",
        "input-add-row", "input-save-btn", "input-discard-btn", "input-dirty-badge",
        "input-save-note", "input-save-text", "input-save-reload", "input-edit-toolbar",
        "input-type-options", "input-category-options",
        "plan-stale-reason", "plan-stale-title", "plan-stale-list", "plan-rebuild-btn",
        "status-plan-badge", "status-plan-sep", "status-rebuild-btn",
    ):
        assert f'id="{element_id}"' in html, f"the page has no #{element_id}"
    # Step 01 is edited like step 03; the mockup's
    # blast-radius warning is up while it has changes.
    assert "Edit house style&hellip;" not in html
    assert "<strong>Editing your house style.</strong>" in html
    # One editor per step, no sections view: the
    # cards, View source and Add section are gone from steps 01 and 03.
    for gone in ("conv-editor", "instr-editor", "conv-source", "instr-source",
                 "conv-add-section", "instr-add-section", "conv-edit-btn", "instr-edit-btn"):
        assert f'id="{gone}"' not in html, gone
    # A finding's jump lands on the editor, and opens its step on the way.
    assert 'id="conv-text" class="source-editor" data-step="conventions"' in html
    assert 'id="instr-text" class="source-editor" data-step="instructions"' in html
    assert "changes the next build of <em>every</em> show that names it" in html
    # Every save and rebuild control is inside .layout-main, which the
    # stale-page CSS turns off with every other write control.
    main = html[html.index('class="layout-main"'):html.index('id="dock-col"')]
    for element_id in ("conv-save-btn", "instr-save-btn", "input-save-btn",
                       "plan-rebuild-btn", "status-rebuild-btn"):
        assert f'id="{element_id}"' in main, element_id


def test_shell_js_sends_what_the_server_checks_and_reads_what_it_sends(show):
    js = show.get("/static/shell.js").text
    for text in ('"/api/build/sections/save"', '"/api/build/input-list/save"',
                 "expected_sha256: source.sha256", "expected_path: source.path",
                 "expected_bundle: bundleDirectory()", "house_confirmed:",
                 "source.sha256", "text: box.value", "source.records",
                 "record.line", "record.values", "build.examples",
                 'data.stale === "bundle"', 'data.stale === "file"', "checkServer()",
                 "plan_freshness", "planFreshness", "onBuildChange", "refreshBuild"):
        assert text in js, f"shell.js never has {text}"
    # A re-read must not redraw a step someone is typing into.
    assert "if (!editingStep[slot]) {" in js
    assert "if (editingStep.input_list) return;" in js
    # Nothing of the sections view is left to read a field the server no
    # longer sends (a stale read renders silently blank).
    for gone in ("source.sections", "section.index", "canonical_sections", "layer_tag",
                 "sectionCard", "addSectionCard", "editingMode"):
        assert gone not in js, f"shell.js still has {gone}"


def test_setup_js_draws_staleness_and_sends_the_bundle_with_a_build(show):
    js = show.get("/static/setup.js").text
    for text in ("SP.planFreshness()", "f.plan_path", "f.reasons", "f.unknown", "f.state",
                 "reason.message", '"plan-rebuild-btn"', '"status-rebuild-btn"',
                 "expected_bundle: SP.bundle() ? SP.bundle().directory : null",
                 '["Stale", "is-warn"]', "SP.onBuildChange", "SP.refreshBuild()"):
        assert text in js, f"setup.js never has {text}"


def test_there_is_no_watch_editor_on_build(show):
    """OPTIONS-H point 3: watch conditions are edited on the Watch page
    and nowhere else."""
    html = show.get("/").text
    build = html[html.index('id="mode-build"'):html.index('id="mode-apply"')]
    assert "wc-" not in build
