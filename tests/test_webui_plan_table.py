"""Build step 04 as mockup version H's table (the maintainer, 2026-09-26: *"Per
mockup version H, the step for Plan output is tabular, with a disclosure
for more detail instead of cards"*).

Two halves:

* **What the server adds for the table** -- `channel_display` on the
  plan payload (where each channel's name is written, its desk colour,
  its sockets spelled as an input list spells them) and `socket_key` on
  every input-list record, the key the page joins a channel to its row
  by. Derived, never written into the plan.
* **The served assets.** The Python suite cannot see the browser, so
  every id, class and contract name the table's JS relies on is pinned
  here (CLAUDE.md, "A rename that crosses into atoo/web/static/ is
  invisible to the test suite"). The table itself was checked in
  Chromium; this is what stands between a rename and a quietly broken
  page.

Every plan and bundle here is built in the test -- nothing under
`examples/` is read (tests/conftest.py enforces that).
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import apply  # noqa: E402
from atoo.webui import _bus_display, _channel_display, _output_display, create_app  # noqa: E402
import test_webui as webui_tests  # noqa: E402


def _channel(n, name, group, sockets, color=None, **extra):
    channel = {
        "channel": n, "bank": "ch", "name": name, "color": color,
        "source": {"input": name, "type": "Mic", "model": None,
                   "stereo": len(sockets) == 2, "phantom": False},
        "patch": {"group": group, "sockets": sockets, "stated": True},
        "processing": {"hpf_hz": None, "preset": None},
        "fader": {"fader_db": None, "muted": None},
        "dca": [], "mute_group": [], "bus_sends": [], "main_routes": [],
        "provenance": {},
    }
    channel.update(extra)
    return channel


PLAN = {
    "channels": [
        _channel(1, "Kick", "A", [1], color="Red"),
        _channel(2, "Keys L/R", "A", [15, 16], color="cyan"),
        # One socket feeding two strips: the one case where the strips
        # carry their own names (apply.py, `clink` = 0).
        _channel(3, "Podium", "LCL", [20], color="Gold"),
        _channel(4, "Podium IEM", "LCL", [20]),
        # A group with no name leaf on the socket at all.
        _channel(5, "Bus in", "BUS", [3], bank="aux"),
    ],
    "busses": {}, "outputs": {}, "unassigned_inputs": ["Spare"], "notes": [], "meta": {},
}


# ---- apply.source_name_link: the one rule, shared ----------------------


def test_source_name_link_is_the_rule_apply_writes_by():
    assert apply.source_name_link("A", [4], {}) == (True, None)
    linked, why = apply.source_name_link("LCL", [20], {("LCL", 20): ["Podium", "Podium IEM"]})
    assert not linked and why == "LCL 20 feeds several strips"
    linked, why = apply.source_name_link("BUS", [3], {})
    assert not linked and why == "BUS has no nameable socket"


def test_apply_still_links_and_unlinks_by_that_rule():
    """The refactor moved the decision, not what is written."""
    shared = apply._shared_source_sockets(PLAN)
    kick = apply._channel_write_targets(PLAN["channels"][0], {}, {}, {}, [], True, shared)
    podium = apply._channel_write_targets(PLAN["channels"][2], {}, {}, {}, [], True, shared)
    by_address = {t.address: t for t in kick + podium}
    assert by_address["/ch/1/clink"].compute_value(None) == 1
    assert "/io/in/A/1/name" in by_address
    assert by_address["/ch/3/clink"].compute_value(None) == 0
    assert "LCL 20 feeds several strips" in by_address["/ch/3/clink"].description
    assert "/io/in/LCL/20/name" not in by_address


# ---- channel_display ---------------------------------------------------


def test_channel_display_says_where_each_name_is_written():
    display = _channel_display(PLAN)
    assert len(display) == len(PLAN["channels"])
    kick, keys, podium, iem, bus_in = display
    assert kick["sockets"] == ["AES50-A 1"] and kick["patch_keys"] == ["A 1"]
    assert "socket_keys" not in kick          # its name
    assert kick["name_home"] == {"linked": True, "addresses": ["/io/in/A/1/name"],
                                 "strip": "/ch/1", "why": None, "shared_with": []}
    # Both sockets of a stereo pair carry the name.
    assert keys["name_home"]["addresses"] == ["/io/in/A/15/name", "/io/in/A/16/name"]
    assert keys["patch_keys"] == ["A 15", "A 16"]
    # A shared socket: the strip itself, and why.
    assert podium["name_home"]["linked"] is False
    assert podium["name_home"]["addresses"] == ["/ch/3/name"]
    assert podium["name_home"]["why"] == "LCL 20 feeds several strips"
    assert podium["name_home"]["shared_with"] == ["Podium", "Podium IEM"]
    assert bus_in["name_home"]["addresses"] == ["/aux/5/name"]
    assert bus_in["name_home"]["why"] == "BUS has no nameable socket"


def test_channel_display_gives_the_desks_own_colour_or_says_it_has_none():
    kick, keys, podium, iem, _ = _channel_display(PLAN)
    assert kick["colour"] == {"stated": "Red", "index": 9, "name": "Red"}
    assert keys["colour"] == {"stated": "cyan", "index": 14, "name": "Cyan"}
    # Gold is not one of the WING's eighteen: said, not guessed at.
    assert podium["colour"] == {"stated": "Gold", "index": None, "name": None}
    assert "colour" not in iem
    # A stated `col` wins, as it does in apply.
    plan = {"channels": [_channel(1, "Kick", "A", [1], color="Red", col=5)]}
    assert _channel_display(plan)[0]["colour"]["index"] == 5
    assert _channel_display(plan)[0]["colour"]["name"] == "Green"


def test_channel_display_tolerates_a_malformed_channel():
    assert _channel_display({"channels": [{"name": "x"}, "junk"]}) == [{}, {}]
    assert _channel_display(None) == []


# ---- the desk number each row starts with -----------------------------

BUSSES = {
    # Deliberately out of name order and gapped: the number is the index
    # the plan states, never a position.
    "Wedge 2": {"index": 7, "col": 13, "destination": None},
    "Drums": {"index": 2, "destination": None},
    "IEM": {"index": 12, "col": None, "destination": None},
    "Broken": {"destination": None},
}
OUTPUTS = {
    "FOH": {"kind": "main", "index": 1, "socket": None},
    "Delays": {"kind": "matrix", "index": 3, "socket": None},
    "Loose": {"kind": None, "socket": None},
}


def test_desk_label_is_the_desks_own_spelling():
    assert apply.desk_label("channel", 3) == "3"
    assert apply.desk_label("channel", 3, "aux") == "Aux 3"
    assert apply.desk_label("bus", 7) == "B7"
    assert apply.desk_label("main", 1) == "M1"
    assert apply.desk_label("matrix", 3) == "MX3"
    with pytest.raises(ValueError):
        apply.desk_label("dca", 1)


def test_channel_display_labels_each_channel_by_bank_and_number():
    labels = [d.get("label") for d in _channel_display(PLAN)]
    assert labels == ["1", "2", "3", "4", "Aux 5"]


def test_bus_display_numbers_each_bus_as_apply_writes_it():
    display = _bus_display({"busses": BUSSES})
    assert display["Wedge 2"] == {"number": 7, "label": "B7",
                                  "colour": {"index": 13, "name": "Amber", "stated": None}}
    assert display["Drums"] == {"number": 2, "label": "B2", "colour": None}
    assert display["IEM"]["colour"] is None
    assert display["Broken"] == {}
    # The same number apply addresses every /bus/{n} write by.
    plan = {"channels": [], "dcas": {}, "mute_groups": {}, "outputs": {},
            "busses": {k: v for k, v in BUSSES.items() if k != "Broken"}}
    targets, _ = apply._build_write_targets(plan, set_fader_levels=False)
    written = {t.address.split("/")[2] for t in targets if t.address.endswith("/name")}
    assert written == {str(d["number"]) for d in display.values() if d}
    assert any(t.address == "/bus/7/col" and t.compute_value(None) == 13 for t in targets)


def test_output_display_labels_mains_and_matrices_and_never_colours_them():
    display = _output_display({"outputs": OUTPUTS})
    assert display["FOH"] == {"kind": "main", "index": 1, "label": "M1", "colour": None}
    assert display["Delays"] == {"kind": "matrix", "index": 3, "label": "MX3", "colour": None}
    assert display["Loose"] == {}
    assert _output_display(None) == {} and _bus_display(None) == {}


def test_the_plan_payload_carries_it_beside_the_plan_not_in_it(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN))
    app = create_app(initial_plan=json.loads(path.read_text()), initial_plan_path=str(path))
    with fastapi_testclient.TestClient(app) as c:
        body = c.get("/api/plan").json()
    assert body["plan"] == PLAN, "the plan must reach the page exactly as written"
    assert body["channel_display"] == json.loads(json.dumps(_channel_display(PLAN)))
    assert body["bus_display"] == {} and body["output_display"] == {}


# ---- patch_key on every record -----------------------------------------


@pytest.mark.parametrize("header", ["patch", "socket"])
def test_every_input_list_record_carries_the_patch_key_the_table_joins_by(tmp_path, header):
    """`patch_key` (was `socket_key`), and the row's patch
    under `values.patch` whatever the file's header calls the column --
    the page knows one name. The header itself is reported as written."""
    csv = (f"{header},name,category,type,model,phantom,notes\n"
           "AES50-A 1,Kick,drums,Mic,,FALSE,\n"
           "local 3,Vox,vocals,Mic,,TRUE,\n"
           ",Spare,misc,DI,,FALSE,\n"
           "nowhere 9,Odd,misc,DI,,FALSE,\n")
    directory = webui_tests._build_bundle(tmp_path, input_csv=csv)
    app = create_app(initial_bundle=str(directory),
                     initial_conventions=str(webui_tests._house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        source = c.get("/api/build/sources").json()["input_list"]
    records = source["records"]
    assert [r["patch_key"] for r in records] == ["A 1", "LCL 3", None, None]
    assert all("socket_key" not in r for r in records)
    assert [r["values"]["patch"] for r in records] == ["AES50-A 1", "local 3", "", "nowhere 9"]
    assert all("socket" not in r["values"] for r in records)
    assert source["header"][0] == header
    assert source["columns"][:2] == ["order", "patch"]


# ---- the served assets -------------------------------------------------


@pytest.fixture
def client():
    app = create_app()
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_setup_js_draws_channels_busses_and_outputs_as_tables(client):
    js = client.get("/static/setup.js").text
    for text in ('id="plan-channels-table"', 'id="plan-busses-table"', 'id="plan-outputs-table"',
                 'id="plan-rows"', "ct--input-slim", "ct--plan-collapsed",
                 'class="row-expand-btn"', 'class="row-detail"', 'class="row-detail-inner"',
                 "cell-input-extra", "cell-plan", "cell-plan-collapsed-note",
                 'id="grp-toggle-input"', 'id="grp-toggle-plan"', 'id="grpth-input"',
                 'id="grpth-plan"', 'data-group="input"', 'data-group="plan"',
                 '-detail"', "setup-provenance", "colour-chip", "colour-unknown",
                 "row-pair", "row-unplanned", "ct-unassigned", "plan.unassigned_inputs",
                 'id="plan-input-toolbar-slot"'):
        assert text in js, f"setup.js never has {text}"
    # The cards are gone, and nothing still draws one.
    for gone in ("setup-card", "setup-grid", "renderChannel", "renderBus(", "renderOutput("):
        assert gone not in js, f"setup.js still has {gone}"


def test_setup_js_reads_the_keys_the_server_adds_for_the_table(client):
    """`channel_display` and `patch_key` cross the wire; a rename on the
    Python side is otherwise a blank Written-to line and an unjoined row.
    The names before an earlier change are still read, for a payload or plan from then."""
    js = client.get("/static/setup.js").text
    for key in ("current.channel_display", "d.patch_keys || d.socket_keys", "item.d.sockets",
                "display.name_home", "r.patch_key || r.socket_key", "entry.patches", "entry.patch",
                "entry.sockets", "entry.socket", "values.patch", "values.socket",
                "display.colour", "home.linked", "home.addresses", "home.why",
                "home.shared_with", "colour.index", "colour.name", "colour.stated",
                "sources.input_list.records",
                "current.bus_display", "current.output_display", "item.d.label",
                "display.label", "bd.label", "bd.colour", "od.label", "od.colour"):
        assert key in js, f"setup.js never reads {key}"


def test_every_table_starts_with_the_desk_number_in_its_colour(client):
    js = client.get("/static/setup.js").text
    # The number is the first cell of every row of all three tables...
    assert js.count('<td class="col-num">') >= 5
    assert '<th class="col-num" rowspan="2"' in js
    assert js.count('<th class="col-num" title=') == 2
    # ...a stereo pair's second socket carrying the same number, quieter.
    assert "numChip(item.d.label, item.d.colour, null, true)" in js
    assert "num-chip-sub" in js
    # The chip is painted by the colour name, and says it.
    assert 'attr = ` data-colour="${esc(String(colour.name).toLowerCase())}"`;' in js
    assert "title = `Colour: ${colour.name} (col ${colour.index})`;" in js
    # The Plan group's Ch # is gone: the number is the first column now.
    assert "Ch&nbsp;#" not in js
    # Strip is gone (2026-09-28): Patch leads the Plan group instead.
    assert '<th class="subhead-plan col-patch">Patch</th>' in js
    # 2026-09-28 (UI batch): the Plan group gained Phantom, and a Findings
    # column follows it -- 13 became 15.
    assert "const CHANNEL_COLS = 15;" in js


def test_number_chips_share_the_colour_chips_palette_with_readable_text(client):
    css = client.get("/static/styles.css").text
    # Apply's scribble strips (`.desk-strip-name`) take the
    # same palette, from the same rule.
    rules = re.findall(r'\.colour-chip\[data-colour="(\w+)"\], \.num-chip\[data-colour="(\w+)"\], '
                       r'\.desk-strip-name\[data-colour="\w+"\] '
                       r'\{ background: #([0-9a-f]{6}); color: #([0-9a-f]{6}); \}', css)
    # The desk's eighteen, plus the two retired names still accepted as
    # aliases (Crimson, Magenta), each painting the colour it now maps to.
    assert len(rules) == 20, "every desk colour and alias paints all three, from one rule"

    def luminance(hex_):
        channels = [int(hex_[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    for chip, num, bg, fg in rules:
        assert chip == num
        light, dark = sorted((luminance(bg), luminance(fg)), reverse=True)
        assert (light + 0.05) / (dark + 0.05) >= 4.5, f"{chip}: text on #{bg} is hard to read"
    assert ".num-chip {" in css and ".num-chip-sub {" in css


def test_every_jump_target_is_still_on_a_row_and_a_jump_opens_it(client):
    js = client.get("/static/setup.js").text
    # The id a finding's jump link names, now on the table row.
    assert 'return "plan-" + kind + "-" + String(name == null ? "" : name)' in js
    assert 'id="${esc(id)}" data-step="plan"' in js
    assert 'document.getElementById(cardId(object.kind, object.name))' in js
    # The shell tells the row it was jumped to; the table opens it.
    assert 'container.addEventListener("atoo:jump"' in js
    shell = client.get("/static/shell.js").text
    assert 'target.dispatchEvent(new CustomEvent("atoo:jump", { bubbles: true, detail: jump }));' in shell


def test_step_04_edits_through_step_02s_editor_not_a_second_save_path(client):
    """The Input columns are step 02's rows: an edit is made on step 02's
    own input, and saved by the one `saveInputList`."""
    js = client.get("/static/setup.js").text
    for text in ("SP_.inputEditor.set(input.dataset.inputKey", "SP_.inputEditor.remove(",
                 "SP.inputEditor.onChange(", "editor.rows()", "editor.available()",
                 'data-input-col="', 'data-input-key="', "data-input-remove"):
        assert text in js, f"setup.js never has {text}"
    assert "/api/build/input-list/save" not in js, "step 04 must not have a save path of its own"
    shell = client.get("/static/shell.js").text
    assert shell.count('fetch("/api/build/input-list/save"') == 1
    for text in ("inputEditor: {", "set: setInputCell,", "save: saveInputList,",
                 "discard: discardInputList,", "rows: inputRowsNow,",
                 'planInputSave.addEventListener("click", saveInputList)',
                 '"plan-input-dirty-badge"', '"plan-input-save-btn"', '"plan-input-discard-btn"',
                 '"plan-input-save-note"', "tr.dataset.key = String(++inputKeySeq);",
                 'notifyInput("plan");'):
        assert text in shell, f"shell.js never has {text}"


def test_the_shell_page_carries_step_04s_input_toolbar(client):
    html = client.get("/").text
    for element_id in ("plan-input-toolbar", "plan-input-mode", "plan-input-edit-link",
                       "plan-input-dirty-badge", "plan-input-discard-btn", "plan-input-save-btn",
                       "plan-input-save-note", "plan-input-save-text", "plan-input-save-reload",
                       # kept as they were: the stale reason, Recompile and its critic box
                       "plan-stale-reason", "plan-rebuild-btn", "run-build-btn", "run-critic",
                       "back-to-instructions"):
        assert f'id="{element_id}"' in html, f"shell.html has no #{element_id}"


def test_styles_carry_the_tables_rules(client):
    css = client.get("/static/styles.css").text
    for rule in (".ct.ct--input-slim td.cell-input-extra { display: none; }",
                 ".ct.ct--plan-collapsed th.subhead-plan, .ct.ct--plan-collapsed td.cell-plan { display: none; }",
                 '.row-expand-btn[aria-expanded="true"] .chevron { transform: rotate(90deg); }',
                 ".row-detail-inner {", '.colour-chip[data-colour="red"]',
                 '.colour-chip[data-colour="white"]', ".colour-unknown {", "tr.jump-flash {"):
        assert rule in css, f"styles.css has no {rule}"
    assert ".setup-card" not in css and ".setup-grid" not in css


# ---- The maintainer's quick fixes, 2026-09-28 ----------------------------------
# Step 04: Socket moved into the Plan group and headed "Patch" (an earlier change
# renames labels only here -- the data keeps `socket`), and the Strip
# column removed, with what it carried moved onto other cells. Step 02:
# Patch the last column before the ✕, and Notes an icon with a popup.


def _channel_header(js):
    start = js.index('function channelTable(plan, display)')
    return js[start:js.index("function busTable(", start)]


def test_step_04_has_patch_in_the_plan_group_and_no_strip_column(client):
    js = client.get("/static/setup.js").text
    header = _channel_header(js)
    # No Socket column before the Input group, and no Strip heading at all.
    assert "Socket" not in header
    assert ">Strip<" not in header
    # Patch is the Plan group's first subhead, then Phantom (the UI batch,
    # 2026-09-28), DCAs and Mute Groups.
    plan_heads = re.findall(r'<th class="subhead-plan(?: [^"]*)?"[^>]*>([^<]+)</th>', header)
    assert plan_heads == ["Patch", "Phantom", "DCAs", "Mute Groups"]
    # The Plan group spans those four columns when open.
    assert 'colspan="${planCollapsed ? 1 : PLAN_COLS}"' in header
    assert "const PLAN_COLS = 4;" in js
    # Every row draws its patch through planCells' first cell.
    assert '`<td class="cell-plan col-patch">${patch}</td>' in js
    assert "planCells(patchText(patch), phantomCell(ch), listOrDash(ch.dca), listOrDash(ch.mute_group))" in js
    assert '<td class="col-sock">' not in js
    # The outputs table says Patch too.
    assert "<th>Output</th><th>Kind</th><th>Patch</th><th>Fed by</th>" in js


def test_what_the_strip_column_carried_is_still_drawn(client):
    """A name the plan changed, the second row of a stereo pair, and an
    input the plan does not place: each still says so, on another cell."""
    js = client.get("/static/setup.js").text
    # The plan's name for the strip, under the Name cell, only when it differs.
    assert "const deskName = row && row.values.name !== ch.name" in js
    assert "on desk: ${esc(ch.name)}" in js
    assert "inputCells(row, editable, deskName)" in js
    # The pair's second row says whose it is, beside its patch (it said
    # "+ stereo pair" until the ST badge, 2026-09-28).
    assert "`second input of ${esc(item.ch.name)}</span>`" in js
    assert '"+ stereo pair</span>"' not in js
    # "unassigned" / "not in this plan" beside the unplaced input's patch.
    assert "planCells(`${patchOf(row.values) ? patchText(patchOf(row.values))" in js
    assert ">unassigned</span>" in js and ">not in this plan</span>" in js
    css = client.get("/static/styles.css").text
    assert ".ct-desk-name {" in css


def test_step_02_draws_patch_last_and_notes_as_an_icon(client):
    html = client.get("/").text
    start = html.index('<table class="it" id="input-table">')
    head = html[start:html.index("</thead>", start)]
    heads = re.findall(r"<th(?:\s[^>]*)?>([^<]*)<", head)
    assert heads == ["", "Order", "Name", "Category", "Type", "Model", "Phantom", "Preset",
                     "Notes", "Patch", ""]
    assert "Socket" not in head
    shell = client.get("/static/shell.js").text
    # The cells follow the header: the patch drawn last, under either name.
    assert 'const PATCH_COLUMNS = ["patch", "socket"];' in shell
    assert "return inputColumns.filter((c) => PATCH_COLUMNS.indexOf(c) === -1).concat(patch);" in shell
    # An empty Patch cell shows nothing that reads like a value.
    assert 'placeholder = "LCL 3"' not in shell
    assert 'box.title = "Where this input is patched' in shell
    assert "inputDisplayColumns().forEach((column) => {" in shell
    # Notes: a hidden data-col input (so every save path sees it) and a button.
    assert 'if (column === "notes") return notesCell(value, isNew);' in shell
    assert 'input.type = "hidden";\n    input.dataset.col = "notes";' in shell
    assert 'button.classList.toggle("has-note", has);' in shell
    assert 'button.title = has ? text : "Add a note";' in shell
    assert 'if (column === "notes") syncNoteButton(input.closest("td"));' in shell


def test_the_note_popup_is_a_keyboard_dialog_that_edits_the_row(client):
    html = client.get("/").text
    for element_id in ("note-dialog", "note-dialog-title", "note-dialog-text",
                       "note-dialog-ok", "note-dialog-cancel"):
        assert f'id="{element_id}"' in html, f"shell.html has no #{element_id}"
    assert '<dialog class="note-dialog" id="note-dialog"' in html
    shell = client.get("/static/shell.js").text
    # Esc is the dialog's own cancel; Ctrl/Cmd+Enter is OK; Enter is left alone.
    assert 'dialog.addEventListener("cancel", (ev) => { ev.preventDefault(); closeNoteDialog(false); });' in shell
    assert 'if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {' in shell
    # OK writes the row's own cell and marks the list dirty, like a typed edit.
    assert "input.value = box.value;" in shell
    assert 'input.dataset.touched = "1";\n      syncNoteButton(td);\n      setInputDirty(true);' in shell
    css = client.get("/static/styles.css").text
    for rule in (".note-btn.has-note {", ".note-dialog {", ".note-dialog::backdrop {"):
        assert rule in css, f"styles.css has no {rule}"


# ---- the UI batch from the maintainer's testing, 2026-09-28 --------------------
# Step 04: an ST badge on stereo channels, Notes through step 02's popup,
# Phantom and Findings columns, bigger borderless triangles, the build
# log folded. Step 02: Patch as a badge, edited in place and validated.


def test_a_stereo_channel_carries_st_and_its_partner_row_says_so(client):
    js = client.get("/static/setup.js").text
    # Stereo is what apply writes (`source.stereo`), or a two-socket patch.
    assert "(ch.source && ch.source.stereo) || (ch.patch && (ch.patch.sockets || []).length > 1)" in js
    assert '`<span class="st-badge${partner ? " st-badge-partner" : ""}"' in js
    assert '`${stereo ? stBadge(ch) : ""}${changeChip(cardId("channel", ch.name))}</td>`' in js
    assert "stBadge(item.ch, true)" in js
    # The pair keeps its first row's shading, and names it.
    assert 'if (item.type !== "pair") alt = !alt;' in js
    assert 'data-pair-of="${esc(cardId("channel", item.ch.name))}"' in js
    css = client.get("/static/styles.css").text
    for rule in (".st-badge {", ".st-badge-partner {", ".ct tbody tr.row-pair td.col-num"):
        assert rule in css, f"styles.css has no {rule}"


def test_step_04_notes_are_step_02s_icon_and_popup_with_no_second_save_path(client):
    js = client.get("/static/setup.js").text
    # The table cell and the row's disclosure both draw the same button...
    assert 'if (col === "notes") return `<td class="${cls}">${noteButton(row)}</td>`;' in js
    assert 'row ? ["Notes", notesDesc(row, editable)] : null,' in js
    assert "editor.noteIcon(text)" in js
    # ...and a click opens step 02's popup on step 02's own row.
    assert "SP_.inputEditor.editNote(note.dataset.noteKey, note);" in js
    # No text box for notes is left in step 04's table.
    assert 'data-input-col="notes"' not in js
    shell = client.get("/static/shell.js").text
    # The popup lives at the top of the page: inside step 02's panel it
    # could not show while step 04 is the step on screen.
    for text in ("document.body.appendChild(dialog);",
                 "noteIcon: noteIcon,", "editNote: editNote,", "openNoteDialog(td, returnTo);",
                 'const td = tr && tr.querySelector("td.col-notes");'):
        assert text in shell, f"shell.js never has {text}"
    assert shell.count('fetch("/api/build/input-list/save"') == 1


def test_step_04_has_a_phantom_column_as_the_plan_sets_it(client):
    js = client.get("/static/setup.js").text
    assert "const on = !!(ch && ch.source && ch.source.phantom);" in js
    assert '<span class="phantom-badge"' in js
    assert '<th class="subhead-plan col-plan-phantom"' in js
    assert "if (th) th.colSpan = open ? PLAN_COLS : 1;" in js
    assert ".phantom-badge {" in client.get("/static/styles.css").text


def test_findings_badges_count_the_docks_findings_by_its_own_jump_targets(client):
    js = client.get("/static/setup.js").text
    # One Findings cell per row of all three tables, filled from the dock.
    assert js.count("findingsCell(cardId(") == 3
    assert js.count("FINDINGS_TH") >= 4
    # A finding is a row's when one of its jump links lands on that row,
    # or its structured `where` names it (Apply's pre-flight links to its
    # own panel, but `channels[Snare].patch` is still Snare's row).
    assert "/^#plan-(channel|bus|output)-/.test(j.target)" in js
    assert "const m = /^(channels|busses|outputs)\\[([^\\]]+)\\]/.exec(f.where || \"\");" in js
    assert "if (!findingRowIds(f)[id]) return;" in js
    assert "if (f._resolved) return;" in js
    for text in ('["error", "E", "error"]', '["warning", "W", "warning"]', '["info", "I", "info"]',
                 "`<button type=\"button\" class=\"fbadge fbadge-${sev}\" data-sev=\"${sev}\"",
                 "SP_.showFindings(list);", "SP.onFindingsChange(paintFindingBadges);",
                 "restoreOpenRows();\n    paintFindingBadges();"):
        assert text in js, f"setup.js never has {text}"
    shell = client.get("/static/shell.js").text
    for text in ("onFindingsChange: (fn) =>", "showFindings: showFindings,",
                 "findingsListeners.forEach((fn) => {", "function showFindings(list) {"):
        assert text in shell, f"shell.js never has {text}"
    css = client.get("/static/styles.css").text
    for rule in (".fbadge-error { background: var(--danger-bg); color: var(--danger-fg); }",
                 ".fbadge-warning { background: var(--warning-bg); color: var(--warning-fg); }",
                 ".fbadge-info {", ".dock-item.jump-flash {"):
        assert rule in css, f"styles.css has no {rule}"


def test_disclosure_triangles_are_bigger_and_borderless_but_still_focusable(client):
    css = client.get("/static/styles.css").text
    start = css.index(".row-expand-btn {")
    rule = css[start:css.index("}", start)]
    assert "border: none;" in rule
    assert "width: 32px; height: 32px;" in rule
    assert ".row-expand-btn:focus-visible { outline: 2px solid var(--accent);" in css
    # Still a <button>: in the tab order without a tabindex.
    assert '`<td class="col-expand"><button type="button" class="row-expand-btn" `' in \
        client.get("/static/setup.js").text


def test_the_build_log_is_folded_closed_by_default(client):
    html = client.get("/").text
    start = html.index('id="run-log-fold"')
    fold = html[html.rindex("<details", 0, start):html.index("</details>", start)]
    assert "<details " in fold and " open" not in fold.split(">", 1)[0]
    assert 'id="run-log-summary">Build log output</summary>' in fold
    assert 'id="run-last-command"' in fold and 'id="run-log"' in fold
    js = client.get("/static/setup.js").text
    assert 'el("run-log-summary").textContent = "Build log output"' in js
    assert 'logFold.addEventListener("toggle"' in js


def test_step_02_patch_is_a_badge_edited_in_place_and_validated(client):
    shell = client.get("/static/shell.js").text
    for text in ('if (PATCH_COLUMNS.indexOf(column) !== -1) return patchCell(column, value, isNew);',
                 'badge.className = "patch-badge";', 'badge.classList.toggle("is-empty", !value);',
                 'badge.textContent = value || "+ add";',
                 'fetch("/api/build/validate-patch?value=" + encodeURIComponent(typed)',
                 'if (ev.key === "Enter") { ev.preventDefault(); commit(true); }',
                 'else if (ev.key === "Escape") { ev.preventDefault(); close(true); }',
                 'ok.addEventListener("click", () => commit(true));',
                 # Refused: the row's own value is left as it was.
                 "if (!verdict.ok) {", 'error.className = "patch-edit-error";',
                 # Accepted: dirty, like any other edit; saved by the one Save.
                 "input.value = spelled;", "await Promise.all(waiting);"):
        assert text in shell, f"shell.js never has {text}"
    # The value is still a hidden data-col input, so every save path sees it.
    assert 'input.type = "hidden";\n    input.dataset.col = column;' in shell
    css = client.get("/static/styles.css").text
    for rule in (".patch-badge {", ".patch-badge.is-empty {", ".patch-edit-error {"):
        assert rule in css, f"styles.css has no {rule}"


def test_step_02_has_order_skip_insert_and_row_moves(client):
    """FR-1.1 (the maintainer, 2026-10-09). The Python suite cannot run the page,
    so this pins the served assets: a rename here is a blank or dead
    control there (CLAUDE.md, `atoo/web/static/`). Driven for real in
    Chromium when it was built (PR body)."""
    shell = client.get("/static/shell.js").text
    # The Order cell, first after the move handle, with its Skip box.
    assert 'const INPUT_COLUMNS = ["order", "patch", "name",' in shell
    assert 'const SKIP_MARK = "-";' in shell
    assert 'if (column === "order") return orderCell(value, isNew);' in shell
    assert 'input.dataset.col = "order";' in shell
    assert 'box.className = "skip-box";' in shell
    assert 'tr.classList.toggle("row-skipped", skipped);' in shell
    # Insert below a row, and + Add row at the end, through one function.
    assert "insert.addEventListener(\"click\", () => insertInputRow(tr));" in shell
    assert 'addRowBtn.addEventListener("click", () => insertInputRow(null));' in shell
    assert "body.insertBefore(tr, after.nextSibling);" in shell
    # Moves: a drag handle, up/down buttons, and Alt+Up/Down.
    assert "tr.appendChild(moveCell(tr));" in shell
    assert 'up.addEventListener("click", () => moveInputRow(tr, -1, up));' in shell
    assert 'down.addEventListener("click", () => moveInputRow(tr, 1, down));' in shell
    assert 'if (!ev.altKey || (ev.key !== "ArrowUp" && ev.key !== "ArrowDown")) return;' in shell
    assert 'body.addEventListener("dragstart"' in shell
    assert 'body.addEventListener("dragover"' in shell
    # A skipped row may share a name; a bad order cell is marked on the row.
    assert "if (name && !skipped) {" in shell
    assert "order is the band's input number, '-' to skip, or blank" in shell
    css = client.get("/static/styles.css").text
    assert ".it tr.row-skipped td" in css
    assert ".drag-handle {" in css
    # Step 04 says "skipped" for such a row, not "not in this plan".
    setup = client.get("/static/setup.js").text
    assert 'const skipped = String(row.values.order || "").trim() === "-";' in setup
    assert ">skipped</span>" in setup
