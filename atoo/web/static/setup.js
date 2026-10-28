(() => {
  "use strict";

  // Build step 04, Plan (version H) -- loaded by the
  // shell (`/`) after shell.js, and coded against `window.Atoo`.
  //
  // Two halves. The first is the plan RENDERER that was the read-only
  // viewer at `/setup` (FR-6.3): it ports the grouping and labeling
  // *ideas* from atoo/render.py's private helpers into JS (that file
  // is prose for `atoo build --pretty` and is not imported here).
  // `/setup` retired when step 04 landed; its renderers did not, and this
  // is still the only thing that draws a plan -- since 2026-09-26 as
  // version H's combined Input+Plan table, whose Input cells are step
  // 02's own editor (`SP.inputEditor`), not a copy of it.
  //
  // The second half runs the build: `POST /api/build/run` starts
  // `atoo build --show DIR` in a worker thread on the server, and
  // `GET /api/build/status` says running / done / failed with the
  // build's own output, so a long build reads as working rather than
  // hung -- and its `progress`, the model call the build is in, drawn as
  // a live readout (renderProgress), with what the model is writing read
  // out of its partial JSON (renderLive). Stop (`POST /api/build/stop`)
  // ends the build and its model call; the run then reads Stopped, with
  // the server's checked sentence about what was written (nothing, unless
  // the stop came after the plan landed). The plan it writes is drawn here and its verify and critic
  // findings go to the shared dock, each with a jump link back to the
  // section and the plan object that caused it -- and only there: this step draws one line counting them (`paintFindingsSummary`).
  // A Build refused for a missing input list or house file puts that
  // ERROR in the dock too (`publishRefusal`).
  //
  // Nothing here writes to a console. The only write is the build's own,
  // to the bundle's plan.json (and the watchlist it drafts), exactly as
  // the same command does from a terminal.

  const el = (id) => document.getElementById(id);
  // The shell's contract, for the renderer's editable Input cells (step
  // 02's editor, `inputEditor`); null only if shell.js did not load.
  const SP_ = window.Atoo || null;

  function esc(s) {
    const div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  // ---- Descriptive helpers -- same grouping/labeling ideas as
  // render.py's _source_desc/_processing_desc/_bus_send_desc/_socket_desc/
  // _patch_desc/_destination_desc/_fed_by_desc, ported to JS rather than
  // imported (render.py is plain-text-for-a-terminal output, not a data
  // API, and this issue's scope says not to edit it).

  function sourceDesc(source) {
    if (!source) return "-";
    const bits = [source.type];
    if (source.model) bits.push(source.model);
    let desc = bits.join("/");
    const tags = [];
    if (source.stereo) tags.push("stereo");
    if (source.phantom) tags.push("phantom");
    if (tags.length) desc += ` (${tags.join(", ")})`;
    return desc;
  }

  function eqDesc(eq) {
    // Band ids are the console's own ("low", "1".."6",
    // "high"), so nothing here has to know that a channel stops at 4 and a
    // bus runs to 6 -- it renders what the plan states, and the schema and
    // verifier are what refuse a band the strip does not have.
    if (!eq) return "";
    const bands = [];
    for (const band of eq.bands || []) {
      const parts = [];
      if (band.freq_hz != null) parts.push(`${band.freq_hz}Hz`);
      if (band.gain_db != null) parts.push(`${band.gain_db > 0 ? "+" : ""}${band.gain_db}dB`);
      if (band.q != null) parts.push(`Q${band.q}`);
      if (band.shape) parts.push(band.shape);
      bands.push(parts.length ? `${band.band} ${parts.join(" ")}` : `${band.band} (empty)`);
    }
    if (eq.model) bands.push(eq.model);
    if (eq.mix_pct != null) bands.push(`mix ${eq.mix_pct}%`);
    if (!bands.length) return eq.on != null ? `EQ ${eq.on ? "on" : "off"}` : "";
    return `${eq.on === false ? "EQ (off)" : "EQ"} [${bands.join("; ")}]`;
  }

  // A plan carries a named preset's values
  // (`processing.preset_values`, resolved by build) or only its name. The
  // count says which -- a name with no values writes nothing. An older
  // plan has no `preset_values` key at all, which reads as the latter.
  function presetCount(processing) {
    const values = processing && processing.preset_values;
    const leaves = values && values.leaves;
    if (leaves && typeof leaves === "object") {
      return ` (${Object.keys(leaves).length} values)`;
    }
    return " (not expanded \u2014 nothing written)";
  }

  function processingDesc(processing) {
    if (!processing) return "-";
    const bits = [];
    if (processing.hpf_hz != null) bits.push(`HPF ${processing.hpf_hz}Hz`);
    // The fields, phase 1 and then phase 2a. The phase 1 six had
    // been representable, writable and rendered by render.py
    // while this function still showed only two of them -- a page that
    // silently omits a stated value is the same class of failure as one
    // that silently blanks a renamed one.
    if (processing.hi_cut_hz != null) bits.push(`Hi-cut ${processing.hi_cut_hz}Hz`);
    if (processing.tilt_db != null) bits.push(`Tilt ${processing.tilt_db}dB`);
    if (processing.trim_db != null) bits.push(`Trim ${processing.trim_db}dB`);
    if (processing.balance_db != null) bits.push(`Balance ${processing.balance_db}dB`);
    if (processing.invert) bits.push("Inverted");
    if (processing.gain_db != null) bits.push(`Gain ${processing.gain_db}dB`);
    if (processing.preset) bits.push(`preset "${processing.preset}"${presetCount(processing)}`);
    const eq = eqDesc(processing.eq);
    if (eq) bits.push(eq);
    // The channel's second EQ (`ch.{n}.peq`, the PreSend EQ) -- same band
    // shape, different tap point, so it is labelled rather than merged.
    const peq = eqDesc(processing.presend_eq);
    if (peq) bits.push(peq.replace("EQ", "PreSend EQ"));
    return bits.length ? bits.join(", ") : "-";
  }

  function faderDesc(fader) {
    if (!fader) return "-";
    const bits = [];
    if (fader.fader_db != null) bits.push(`${fader.fader_db}dB`);
    if (fader.muted) bits.push("muted");
    return bits.length ? bits.join(", ") : "-";
  }

  function busSendDesc(send) {
    const mode = send.mode || "mode?";
    const level = send.level_db != null ? `${send.level_db}dB` : "level?";
    return `${send.bus} (${mode}, ${level})`;
  }

  function socketDesc(socket) {
    if (!socket) return "patch?";
    return `${socket.group} ${(socket.sockets || []).join("-")}`;
  }

  // An input-list row's patch cell. The server names it `patch` whatever
  // the file's header says; `socket` is read too, for a payload from
  // .
  function patchOf(values) {
    if (!values) return "";
    return values.patch != null ? values.patch : (values.socket || "");
  }

  function patchDesc(patch) {
    if (!patch) return "-";
    const desc = socketDesc({ group: patch.group, sockets: patch.sockets });
    return patch.stated ? desc : `${desc} (auto)`;
  }

  // A note's source in brackets, except the model's own -- most notes
  // are the model's, and step 04 is reading its plan.
  function noteLine(note) {
    if (note && typeof note === "object" && note.source && note.source !== "model") {
      return `[${note.source}] ${note.text || ""}`;
    }
    if (note && typeof note === "object") return note.text || "";
    return String(note);
  }

  // ---- Provenance (FR-6.3's acceptance criterion: a finding traces back
  // to the specific convention that produced it -- shown per field,
  // exactly as compile_plan()/generate.py already computed it, never
  // re-derived here).

  const PROVENANCE_LABELS = {
    channel: "Channel", patch: "Patch", processing: "Processing", dca: "DCA",
    mute_group: "Mute group", bus_sends: "Bus sends", fader: "Fader",
  };

  function renderProvenance(prov) {
    if (prov == null) return "";
    if (typeof prov === "string") {
      // One sentence for the whole object (a bus, an output): still behind
      // the same disclosure, so every row's detail reads the same way.
      return prov ? '<details class="setup-provenance"><summary>Provenance</summary>' +
        `<p class="setup-provenance-line">${esc(prov)}</p></details>` : "";
    }
    const keys = Object.keys(prov);
    if (!keys.length) return "";
    let rows = "";
    for (const k of keys) {
      const label = PROVENANCE_LABELS[k] || k;
      rows += `<dt>${esc(label)}</dt><dd>${esc(prov[k])}</dd>`;
    }
    return `<details class="setup-provenance"><summary>Provenance</summary>` +
      `<dl class="setup-kv">${rows}</dl></details>`;
  }

  // ---- Channels / busses / outputs, as tables (version H) ---------
  //
  // Per version H, the step for Plan output
  // is tabular, with a disclosure for more detail instead of cards. So
  // channels are H's combined Input+Plan table -- one row per input,
  // Input columns (collapsed to Socket + Name by default) beside the
  // plan's Ch #, DCAs and Mute Groups -- and every row has a disclosure
  // for the rest: HPF, preset, fader, colour, sends, where the name is
  // actually written, provenance. Busses and outputs are two compact
  // tables of the same kind below it (H draws channels only; the
  // rest was decided 2026-09-26).
  //
  // Nothing the cards printed is lost: the card's header and every
  // `<dt>` it drew is a column or a detail line here.

  // Every row a finding can be about carries what it is and its name, and
  // an id built from both, so a finding in the dock can jump to it.
  // `data-step="plan"` is what makes the shell's jump open step 04 first;
  // the jump then opens the row's disclosure (`atoo:jump`, below).
  function cardId(kind, name) {
    return "plan-" + kind + "-" + String(name == null ? "" : name)
      .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  function rowOpen(kind, name, cls, extra) {
    const id = cardId(kind, name);
    // A strip this build changed is marked (`changeRowClass`).
    return `<tr class="row-primary${cls ? " " + cls : ""}${changeRowClass(id)}" id="${esc(id)}" data-step="plan" ` +
      `data-kind="${esc(kind)}" data-name="${esc(name)}"${extra || ""}>`;
  }

  function expandCell(kind, name) {
    const id = cardId(kind, name);
    return `<td class="col-expand"><button type="button" class="row-expand-btn" ` +
      `aria-expanded="false" aria-controls="${esc(id)}-detail" ` +
      `aria-label="${esc(name)} — show details"><span class="chevron" aria-hidden="true">&#9656;</span>` +
      "</button></td>";
  }

  // A stereo channel (stereo channels are
  // visible): the source is linked as a pair, which is what apply writes
  // (`source.stereo` -> the socket's mode "ST"), or the plan patches it
  // to two sockets. Either says two input rows are one strip.
  function isStereo(ch) {
    return !!((ch.source && ch.source.stereo) || (ch.patch && (ch.patch.sockets || []).length > 1));
  }

  function stBadge(ch, partner) {
    const title = partner
      ? `The second input of ${ch.name}: the same stereo channel as the row above`
      : `Stereo channel: this row and the next are one stereo strip, ${ch.name}`;
    return `<span class="prop ct-st" title="${esc(title)}">` +
      `${partner ? "&#8627; ST" : "ST"}</span>`;
  }

  // The plan's Phantom column: 48V as apply will write it
  // (`channel.source.phantom`), not the input list's own tick.
  function phantomCell(ch) {
    const on = !!(ch && ch.source && ch.source.phantom);
    return `<td class="cell-plan col-plan-phantom">${on
      ? '<span class="prop" title="Phantom power (48V) on: the plan sets it on this ' +
        'channel\'s socket">48V</span>'
      : '<span class="setup-dim" title="Phantom power off">—</span>'}</td>`;
  }

  // Step 04's Notes icon: step 02's own (`inputEditor.noteIcon`), and a
  // click opens step 02's own popup on that row (`inputEditor.editNote`).
  function noteButton(row, extraCls) {
    const editor = SP_ && SP_.inputEditor;
    const text = (row.values && row.values.notes) || "";
    const has = String(text).trim() !== "";
    const icon = editor && editor.noteIcon ? editor.noteIcon(text) : "";
    return `<button type="button" class="btn-icon note-btn${has ? " has-note" : ""}${extraCls ? " " + extraCls : ""}" ` +
      `data-note-key="${esc(row.key)}" title="${esc(has ? text : "Add a note")}" ` +
      `aria-label="${esc(has ? "Edit note: " + text : "Add a note")}">${icon}</button>`;
  }

  // The Findings column: filled by paintFindingBadges from the dock.
  function findingsCell(id) {
    return `<td class="col-findings" data-findings-for="${esc(id)}"></td>`;
  }

  function detailRow(kind, name, colspan, inner) {
    return `<tr class="row-detail" id="${esc(cardId(kind, name))}-detail" hidden>` +
      `<td colspan="${colspan}"><div class="row-detail-inner">${inner}</div></td></tr>`;
  }

  function kv(pairs) {
    const rows = pairs.filter((p) => p).map(([dt, dd]) => `<dt>${esc(dt)}</dt><dd>${dd}</dd>`).join("");
    return rows ? `<dl class="setup-kv">${rows}</dl>` : "";
  }

  const DASH = '<span class="setup-dim">—</span>';

  function listOrDash(list) {
    return list && list.length ? esc(list.join(", ")) : DASH;
  }

  // The colour the desk will show: the chip, the desk's own name and its
  // 1..18 index (`channel_display.colour`, from console_facts). A colour
  // the desk does not have is said, not guessed at -- apply leaves it
  // unwritten.
  function colourDesc(colour) {
    if (!colour) return DASH;
    if (colour.index == null) {
      return '<span class="colour-chip colour-unknown"></span>' +
        `${esc(colour.stated)} <span class="setup-dim">— not a desk color; not written</span>`;
    }
    const name = colour.name || colour.stated || "";
    return `<span class="colour-chip" data-colour="${esc(String(name).toLowerCase())}"></span>` +
      `${esc(name)} <span class="readout">col ${esc(colour.index)}</span>`;
  }

  // The desk number that heads a row -- "3", "Aux 3", "B3", "M1", "MX1",
  // always as the server labelled it (`channel_display.label`,
  // `bus_display.label`, `output_display.label`, from apply's own
  // numbering), never worked out here. Painted the colour the plan will
  // set on that object when it states one the desk has; neutral when it
  // states none, or one the desk does not have (apply writes nothing
  // then). The tooltip names the colour. `sub` is a stereo pair's second
  // socket: the same strip, drawn quieter.
  function numChip(label, colour, noColourNote, sub) {
    if (label == null || label === "") return DASH;
    const cls = "ch-num num-chip" + (sub ? " num-chip-sub" : "");
    let attr = "";
    let title;
    if (colour && colour.index != null && colour.name) {
      attr = ` data-colour="${esc(String(colour.name).toLowerCase())}"`;
      title = `Color: ${colour.name} (col ${colour.index})`;
    } else if (colour && colour.stated) {
      title = `Color: ${colour.stated} is not a desk color; not written`;
    } else {
      title = noColourNote || "Color: none in the plan";
    }
    if (sub) title += " — the second socket of this stereo pair";
    return `<span class="${cls}"${attr} title="${esc(title)}">${esc(label)}</span>`;
  }

  // Where the name lands on the desk (`channel_display.name_home`, from
  // apply.source_name_link -- the rule the write uses). With `clink` on,
  // the socket carries it and the strip inherits.
  function writtenToDesc(ch, home) {
    if (!home) return DASH;
    const codes = (home.addresses || []).map((a) => `<code>${esc(a)}</code>`).join(" and ");
    const strip = (ch.bank === "aux" ? "aux " : "strip ") + esc(ch.channel);
    if (home.linked) {
      return `${codes} — the socket, not the strip; ${strip} inherits it ` +
        '(<code>clink</code> = 1, "Link Customization to Source")';
    }
    let text = `${codes} — the strip itself (<code>clink</code> = 0: ${esc(home.why || "")})`;
    if (home.shared_with && home.shared_with.length > 1) {
      text += `; the socket is labeled for all of ${esc(home.shared_with.join(", "))}`;
    }
    return text;
  }

  function sendsDesc(ch) {
    const bits = (ch.bus_sends || []).map(busSendDesc);
    return bits.length ? esc(bits.join(", ")) : DASH;
  }

  // Everything the processing block states beyond HPF and preset, which
  // have lines of their own -- the same words processingDesc gives.
  function processingRest(processing) {
    if (!processing) return "-";
    return processingDesc(Object.assign({}, processing, { hpf_hz: null, preset: null }));
  }

  function channelDetail(ch, display, row, editable) {
    const p = ch.processing || {};
    const rest = processingRest(p);
    const mains = (ch.main_routes || []).map((r) => "Main " + r.index).join(", ");
    const nameLine = ch.color ? `${esc(ch.name)} <span class="setup-tag">[${esc(ch.color)}]</span>` : esc(ch.name);
    const first = kv([
      ["HPF", p.hpf_hz != null ? `<span class="readout">${esc(p.hpf_hz)} Hz</span>` : DASH],
      ["Preset", p.preset ? esc(p.preset + presetCount(p)) : DASH],
      rest !== "-" ? ["Processing", esc(rest)] : null,
      ["Fader", ch.fader ? `<span class="readout">${esc(faderDesc(ch.fader))}</span>` : DASH],
      ["Color", colourDesc(display.colour)],
      ["Sends", sendsDesc(ch)],
      mains ? ["Direct route", esc(mains)] : null,
    ]);
    const second = kv([
      ["Strip", `${numChip(display.label, display.colour)} ${nameLine}`],
      ["Source", esc(sourceDesc(ch.source))],
      ["Patch", esc(patchDesc(ch.patch))],
      // The alternate input, only when the plan states one
      // (a plan built before it has no `alt_patch` at all).
      ch.alt_patch ? ["Alternate", esc(patchDesc(ch.alt_patch))] : null,
      ["Written to", writtenToDesc(ch, display.name_home)],
    ]);
    return first + second + renderProvenance(ch.provenance);
  }

  // The row's note, in the disclosure: the same icon and popup as the
  // table cell (and step 02's), with the note written out beside it.
  function notesDesc(row, editable) {
    const text = (row.values && row.values.notes) || "";
    const shown = String(text).trim() ? `<span class="ct-note-text">${esc(text)}</span>` : DASH;
    return editable ? `${noteButton(row, "ct-note-detail")} ${shown}` : shown;
  }

  // ---- the join: one row per input -------------------------------------
  //
  // A plan channel names the input-list row it came from (`source.input`)
  // and the socket(s) it is patched to; a row is joined by that name
  // first, then by patch (`patch_key`, parsed on the server, as
  // `channel_display.patch_keys` is -- `socket_key`/`socket_keys`, still read). A stereo channel's second socket
  // is a row of its own; an input the plan does not place is a row with
  // empty Plan cells; a channel no row feeds is a row with empty Input
  // cells. Joined on the row's ORIGINAL name, so renaming it here does
  // not unhook it mid-edit.

  function joinRows(plan, display, inputs) {
    const used = {};
    const free = (r) => !used[r.key];
    const out = [];
    (plan.channels || []).forEach((ch, i) => {
      const d = display[i] || {};
      const keys = d.patch_keys || d.socket_keys || [];
      const wanted = ch.source && ch.source.input;
      let row = inputs.filter((r) => free(r) && wanted && r.original.name === wanted)[0]
        || inputs.filter((r) => free(r) && r.patchKey && r.patchKey === keys[0])[0]
        || null;
      let sharesWith = null;
      if (row) used[row.key] = true;
      else {
        const other = inputs.filter((r) => r.patchKey && keys.indexOf(r.patchKey) !== -1)[0];
        if (other) sharesWith = other;
      }
      out.push({ type: "channel", ch: ch, d: d, input: row, sharesWith: sharesWith });
      // The pair's second row: by the socket the input list states for
      // it, else by name (`source.pair_input`) -- a pair whose rows state
      // no socket, the sockets counted by the build.
      const pairName = ch.source && ch.source.pair_input;
      keys.slice(1).forEach((key, n) => {
        const pair = inputs.filter((r) => free(r) && r.patchKey && r.patchKey === key)[0]
          || inputs.filter((r) => free(r) && pairName && r.original.name === pairName)[0];
        if (pair) {
          used[pair.key] = true;
          out.push({ type: "pair", ch: ch, d: d, input: pair, socket: (d.sockets || [])[n + 1] || "" });
        }
      });
    });
    inputs.filter(free).forEach((r) => out.push({ type: "input", input: r }));
    return out;
  }

  // The rows step 04 edits: step 02's own, through the shell
  // (`inputEditor`), unsaved edits included -- or none, when the plan on
  // screen is not this bundle's (read-only, from the plan's own source).
  function editableInputs() {
    const editor = SP_ && SP_.inputEditor;
    if (!editor || !editor.available() || !planIsBundles()) return null;
    const sources = SP_.buildSources ? SP_.buildSources() : null;
    const records = (sources && sources.input_list && sources.input_list.records) || [];
    const keyByLine = {};
    records.forEach((r) => { keyByLine[r.line] = r.patch_key || r.socket_key || null; });
    return editor.rows().map((row) => Object.assign({}, row, {
      patchKey: row.line == null ? null : keyByLine[row.line] || null,
    }));
  }

  // ---- the Channels table: the input list's own columns ------------------
  //
  // One editable view (mockup revision 3; the maintainer: "Can we
  // just combine it into one, editable view?"): the sheet's columns, every one
  // editable through step 02's own cells. A blank cell is blank in the file;
  // its placeholder is what the plan has there -- what the conventions or
  // the last build put -- so nothing the plan does is hidden. The rest of
  // a row (model, preset, notes, and the plan's own detail) folds open.
  const SHEET_COLS = ["channel", "patch", "name", "category", "type", "phantom", "dca", "mute_group"];
  const SHEET_HEADS = { channel: "Channel", patch: "Patch", name: "Name", category: "Category",
    type: "Type", phantom: "48V", dca: "DCA", mute_group: "Mute group" };

  // What the plan has for a row's sheet cells, as the sheet would write them.
  function planCellValues(ch, d, pairIndex) {
    if (!ch) return {};
    const sockets = (d && d.sockets) || [];
    return {
      channel: ch.bank === "aux" ? `Aux ${ch.channel}` : String(ch.channel == null ? "" : ch.channel),
      patch: sockets[pairIndex || 0] || "",
      dca: (ch.dca || []).join("; "),
      mute_group: (ch.mute_group || []).join("; "),
    };
  }

  // The input socket's own colour on the desk, beside a Patch cell
  // (`outputs_sheet.display`): what a strip linked to it shows.
  function socketChip(text) {
    const s = outParseSocket(text);
    const colour = s ? ((outSheet.display || {}).sockets || {})[`${s.group} ${s.n}`] : null;
    return colour ? `<span class="colour-chip sock-chip" data-colour="${esc(colour)}" ` +
      `title="${esc(colour.charAt(0).toUpperCase() + colour.slice(1))}, the socket's own color on the desk"></span>` : "";
  }

  // `after` is html for under the Name cell: the name the plan puts on the
  // strip when it is not the input's own, or why the row is not on a strip.
  function sheetCells(row, editable, planValues, after) {
    const v = row.values;
    const shown = planValues || {};
    return SHEET_COLS.map((col) => {
      const extra = col === "name" && after ? after : "";
      // `cell-input` only on a cell that holds an input: a text cell keeps
      // the table's own 8 by 12 padding.
      const cls = `${editable ? "cell-input " : ""}col-sheet-${col.replace("_", "-")}`;
      if (!editable && col === "phantom") {
        // The same neutral tag step 02 draws for 48V when it is read-only.
        return `<td class="${cls}">${v.phantom ? '<span class="prop" title="Phantom power (48V) on">48V</span>' : ""}</td>`;
      }
      if (!editable) {
        const text = v[col] || "";
        const fallback = !text && shown[col]
          ? `<span class="setup-dim ct-from-plan" title="Blank in the input list: the plan's">${esc(shown[col])}</span>`
          : DASH;
        return `<td class="${cls}">${col === "patch" ? socketChip(text || shown.patch) : ""}` +
          `${text ? esc(text) : fallback}${extra}</td>`;
      }
      if (col === "phantom") {
        return `<td class="${cls} col-phantom"><input type="checkbox" data-input-col="phantom" ` +
          `data-input-key="${esc(row.key)}" aria-label="Phantom power (48V)"${v.phantom ? " checked" : ""}></td>`;
      }
      const list = col === "type" ? ' list="input-type-options"'
        : (col === "category" ? ' list="input-category-options"' : "");
      const placeholder = shown[col]
        ? ` placeholder="${esc(shown[col])}" title="Blank in the input list; the plan has ${esc(shown[col])}"`
        : "";
      return `<td class="${cls}">${col === "patch" ? socketChip(v.patch || shown.patch) : ""}` +
        `<input type="text" data-input-col="${col}" data-input-key="${esc(row.key)}"` +
        `${list}${placeholder} aria-label="${esc(SHEET_HEADS[col])}" value="${esc(v[col] || "")}">${extra}</td>`;
    }).join("") + (editable
      ? '<td class="cell-input col-remove"><button type="button" class="btn-icon" ' +
        `data-input-remove="${esc(row.key)}" title="Remove row" aria-label="Remove row">✕</button></td>`
      : '<td class="col-remove"></td>');
  }

  // A plan channel no input-list row feeds (a talkback strip the
  // instructions asked for): its cells as the plan has them, read-only.
  function planOnlyCells(ch, d, note) {
    const values = planCellValues(ch, d);
    const cell = (col, html) => `<td class="col-sheet-${col.replace("_", "-")}">${html}</td>`;
    return cell("channel", esc(values.channel)) +
      cell("patch", values.patch ? `${socketChip(values.patch)}<span class="socket-chip">${esc(values.patch)}</span>` : DASH) +
      cell("name", `${esc(ch.name)} <span class="setup-dim" title="${esc(note)}">· no row</span>`) +
      cell("category", DASH) + cell("type", esc((ch.source && ch.source.type) || "")) +
      phantomCell(ch).replace('class="cell-plan col-plan-phantom"', 'class="col-sheet-phantom"') +
      cell("dca", listOrDash(ch.dca)) + cell("mute-group", listOrDash(ch.mute_group)) +
      '<td class="col-remove"></td>';
  }

  // The input-list cells a row folds open: model, preset and notes.
  function inputDetail(row, editable) {
    if (!row) return "";
    const v = row.values;
    const field = (col, label) => [label, editable
      ? `<input type="text" class="detail-input" data-input-col="${col}" data-input-key="${esc(row.key)}"` +
        `${col === "preset" ? ' list="input-preset-options"' : ""} aria-label="${esc(label)}" ` +
        `value="${esc(v[col] || "")}">`
      : (v[col] ? esc(v[col]) : DASH)];
    return kv([field("model", "Model"), field("preset", "Preset"), ["Notes", notesDesc(row, editable)]])
      .replace('<dl class="setup-kv">', '<dl class="setup-kv sheet-kv">');
  }

  const CHANNEL_COLS = 12;  // Ch, expand, the eight sheet columns, remove, Findings

  // `plan.unassigned_inputs` holds bare names in a plan built before
  // 2026-09-29, and `{input, quote, from}` since: the words that said to
  // leave the row off the desk. Both are read.
  function unassignedName(entry) {
    return entry && typeof entry === "object" ? (entry.input || "") : (entry || "");
  }

  function unassignedLine(entry) {
    const name = unassignedName(entry);
    return entry && typeof entry === "object" && entry.quote
      ? `${name} ("${entry.quote}")` : name;
  }

  function channelRows(plan, display, inputs, editable) {
    const unassigned = (plan.unassigned_inputs || []).map(unassignedName);
    let html = "";
    let alt = false;
    joinRows(plan, display, inputs).forEach((item) => {
      // A stereo pair's second row keeps its first row's shading: one
      // channel, one band.
      if (item.type !== "pair") alt = !alt;
      const altCls = alt ? "" : "alt";
      if (item.type === "channel") {
        const ch = item.ch;
        const row = item.input;
        // The name the plan puts on the desk, under the input's own name --
        // only when the two differ ("Keys L" -> "Keys L/R").
        const deskName = row && row.values.name !== ch.name
          ? `<span class="meta ct-desk-name" title="The strip's name in the plan -- what the desk will ` +
            `show, not the input's own">on desk: ${esc(ch.name)}</span>`
          : "";
        const stereo = isStereo(ch);
        // A plan built before its row was skipped still has the channel;
        // it is dimmed like the row, and verify says why
        // (`reconcile.skipped-source`).
        const rowSkipped = row && String(row.values.order || "").trim() === "-";
        html += rowOpen("channel", ch.name,
          altCls + (stereo ? " row-stereo" : "") + (rowSkipped ? " row-skipped" : ""),
          row ? ` data-input-key="${esc(row.key)}"` : "");
        html += `<td class="col-num">${numChip(item.d.label, item.d.colour)}` +
          `${stereo ? stBadge(ch) : ""}${changeChip(cardId("channel", ch.name))}</td>`;
        html += expandCell("channel", ch.name);
        html += row ? sheetCells(row, editable, planCellValues(ch, item.d, 0), deskName)
          : planOnlyCells(ch, item.d, item.sharesWith
            ? `${ch.name} has no input-list row of its own: it shares ` +
              `${patchOf(item.sharesWith.values) || "its patch"} with ${item.sharesWith.values.name}`
            : `${ch.name} has no input-list row: the plan made it (the instructions, or a row ` +
              "since renamed or removed)");
        html += findingsCell(cardId("channel", ch.name));
        html += "</tr>";
        html += detailRow("channel", ch.name, CHANNEL_COLS,
          inputDetail(row, editable) + channelDetail(ch, item.d, row, editable));
      } else if (item.type === "pair") {
        const row = item.input;
        // The partner row: the same chip, drawn quieter, with "↳ ST" under
        // the first row's ST, and a bracket down the left of both rows
        // (`.row-stereo` / `.row-pair`) -- one channel on two input rows.
        html += `<tr class="row-primary row-pair ${altCls}" data-input-key="${esc(row.key)}" ` +
          `data-pair-of="${esc(cardId("channel", item.ch.name))}" ` +
          `title="The second input of ${esc(item.ch.name)}'s stereo pair: the same strip">`;
        html += `<td class="col-num">${numChip(item.d.label, item.d.colour, null, true)}` +
          `${stBadge(item.ch, true)}</td>`;
        html += '<td class="col-expand"></td>';
        html += sheetCells(row, editable, planCellValues(item.ch, item.d, 1), "");
        html += '<td class="col-findings"></td>';
        html += "</tr>";
      } else {
        const row = item.input;
        const name = row.original.name || row.values.name;
        const onPurpose = unassigned.indexOf(name) !== -1;
        // `-` in the order column (FR-1.1): left out of the build on
        // purpose, from the input list itself.
        const skipped = String(row.values.order || "").trim() === "-";
        const mark = skipped
          ? '<span class="ct-unassigned" title="Skipped on the input list (- in its Order ' +
            'cell): the next build leaves it out">skipped</span>'
          : onPurpose
          ? '<span class="ct-unassigned" title="The plan leaves this input off the desk on purpose ' +
            '(plan.unassigned_inputs)">unassigned</span>'
          : '<span class="setup-dim ct-unplanned-note" title="Added or renamed since this plan was ' +
            'built: Save places it when its Channel cell names a channel; otherwise rebuild">' +
            "not in this plan</span>";
        html += `<tr class="row-primary row-unplanned${skipped ? " row-skipped" : ""} ${altCls}" ` +
          `data-input-key="${esc(row.key)}">`;
        html += `<td class="col-num">${DASH}</td>`;
        html += '<td class="col-expand"></td>';
        html += sheetCells(row, editable, {}, mark);
        html += '<td class="col-findings"></td>';
        html += "</tr>";
      }
    });
    return html;
  }

  // The plan's own source, when there is no editable input list to join:
  // a plan opened from elsewhere, or no bundle. Read-only.
  function inputsFromPlan(plan) {
    const rows = (plan.channels || []).map((ch, i) => {
      const s = ch.source || {};
      const values = { patch: "", name: s.input || ch.name, category: "", type: s.type || "",
                       model: s.model || "", phantom: !!s.phantom, notes: "", channel: "",
                       dca: "", mute_group: "" };
      return { key: "plan-" + i, line: null, values: values, original: { name: s.input || "" },
               patchKey: null };
    });
    // The inputs the plan leaves off the desk on purpose are rows too.
    (plan.unassigned_inputs || []).map(unassignedName).forEach((name, i) => {
      rows.push({ key: "plan-unassigned-" + i, line: null, patchKey: null, original: { name: name },
                  values: { patch: "", name: name, category: "", type: "", model: "",
                            phantom: false, notes: "", channel: "", dca: "", mute_group: "" } });
    });
    return rows;
  }

  function channelTable(plan, display) {
    const inputs = editableInputs();
    const editable = !!inputs;
    const rows = channelRows(plan, display, inputs || inputsFromPlan(plan), editable);
    return '<div class="table-wrap ct-wrap">' +
      `<table class="ct ct-sheet" id="plan-channels-table" data-editable="${editable ? "1" : "0"}">` +
      "<thead><tr>" +
      '<th class="col-num" title="The channel the plan puts this input on, in the color it sets">Ch</th>' +
      '<th class="col-expand"><span class="visually-hidden">Expand</span></th>' +
      SHEET_COLS.map((col) => `<th class="subhead-sheet col-sheet-${col.replace("_", "-")}">` +
        `${esc(SHEET_HEADS[col])}</th>`).join("") +
      '<th class="col-remove"><span class="visually-hidden">Remove</span></th>' +
      FINDINGS_TH +
      `</tr></thead><tbody id="plan-rows">${rows}</tbody></table></div>`;
  }

  const FINDINGS_TH = '<th class="col-findings" title="This row\'s findings in the Findings panel: ' +
    'E errors, W warnings, I info. Click a badge to find them there.">Findings</th>';

  // A bus's bus preset, and the effect it loads -- the
  // engine build allocated, switched on whatever the preset was saved as.
  function busPresetDesc(b) {
    const v = b.preset_values;
    if (!v) return `${b.preset} (its values are not in the plan: nothing from it is written)`;
    return `${v.preset} (${v.file || "?"})`;
  }

  function busEffectDesc(b) {
    const inserts = (b.preset_values && b.preset_values.inserts) || [];
    return inserts.map((ins) => {
      const point = ins.point === "postins" ? "post-insert" : "pre-insert";
      if (ins.engine == null) return `${ins.model} -- no engine, not loaded`;
      return `${ins.model} on FX${ins.engine}, ${point}, switched on` +
        (ins.saved_on === false ? " (saved bypassed)" : "");
    }).join("; ");
  }

  // ---- the Busses and Mains and Matrix tables: the bus sheet -------------
  //
  // `busses.csv`, one row per bus, Main and Matrix. Both tables
  // edit the one file, so they share one editor (`busSheet`) and one Save.
  // A row shows the sheet's own columns; a blank cell's placeholder is what
  // the plan has (`derived`, `sheets.bus_rows_from_plan`), and the rest of
  // the row -- its sources and their tap, fx, preset, DCAs, mute groups,
  // label, notes, and the read-only Feeds -- folds open under it. Its
  // Outputs are read-only badges: outputs.csv says what feeds each socket,
  // and the Outputs table edits it (revision 3).
  const BUS_ROW_COLS = ["name", "role", "width", "outputs"];
  const BUS_DETAIL_COLS = [["sources", "Sources"], ["tap", "Tap"], ["fx", "FX"], ["preset", "Preset"],
    ["dca", "DCA"], ["mute_group", "Mute group"], ["label", "Label"], ["notes", "Notes"]];
  const BUS_HEADS = { name: "Name", role: "Role", width: "Width", sources: "Sources", tap: "Tap",
    outputs: "Outputs" };
  const BUS_NOTE = "Save writes the busses.csv file and updates the build plan.";
  const busSheet = {
    loaded: false, source: null, derived: [], roles: { bus: [], output: [] }, rows: [],
    dirty: false, refusals: [], checking: null, note: "", noteKind: "", editable: false,
  };

  // `Bus 3`, `Main 1`, `Matrix 6` (or `Mtx 6`, `MX6`): the row's object.
  function busLabel(text) {
    const m = /^\s*(bus|main|matrix|mtx|mx)\s*(\d+)?\s*$/i.exec(String(text || ""));
    if (!m) return String(text || "").trim();
    const kind = { bus: "Bus", main: "Main", matrix: "Matrix", mtx: "Matrix", mx: "Matrix" }[m[1].toLowerCase()];
    return m[2] ? `${kind} ${Number(m[2])}` : kind;
  }

  function busKindOf(label) {
    return /^Bus\b/.test(label) ? "bus" : (/^(Main|Matrix)\b/.test(label) ? "output" : "bus");
  }

  // The sheet as the server read it, and a row for every plan object it has
  // no row for (blank, so its cells show the plan's values).
  function loadBusSheetPayload(data) {
    busSheet.loaded = true;
    busSheet.source = data.bus_sheet || null;
    busSheet.derived = data.derived || [];
    busSheet.roles = data.roles || { bus: [], output: [] };
    busSheet.rows = ((busSheet.source && busSheet.source.records) || []).map((r) => ({
      label: busLabel(r.values.bus), line: r.line,
      values: Object.assign({}, r.values), original: Object.assign({}, r.values),
    }));
    busSheet.derived.forEach((d) => {
      if (!busSheet.rows.some((r) => r.label === d.bus)) {
        busSheet.rows.push({ label: d.bus, line: null, values: { bus: d.bus }, original: { bus: d.bus } });
      }
    });
    busSheet.dirty = false;
    busSheet.refusals = [];
    // The sheet says something this plan has not taken in (a rebuild, or an
    // edit in a spreadsheet): Save lays it on, with nothing typed here.
    busSheet.behind = !!data.plan_behind;
  }

  function busRow(label) {
    return busSheet.rows.find((r) => r.label === label) || null;
  }

  function derivedRow(label) {
    return busSheet.derived.find((d) => d.bus === label) || null;
  }

  function busCellEdited(row, col) {
    return (row.values[col] || "") !== (row.original[col] || "");
  }

  function busRefusals(label, col) {
    return busSheet.refusals.filter((r) => r.sheet === "busses.csv" && r.row === label &&
      (col === undefined || r.column === col));
  }

  function busCell(row, col, derived, editable) {
    const value = row.values[col] || "";
    const shown = derived ? (col === "name" ? (derived.name || derived.key) : derived[col]) || "" : "";
    const marks = (busCellEdited(row, col) ? " is-edited" : "") +
      (busRefusals(row.label, col).length ? " is-refused" : "");
    const attrs = `data-bus-row="${esc(row.label)}" data-bus-col="${col}" aria-label="${esc(row.label)} ${esc(BUS_HEADS[col] || col)}"`;
    if (col === "outputs") return busOutputBadges(row.label, derived);
    if (!editable) {
      return value ? esc(value)
        : (shown ? `<span class="setup-dim ct-from-plan" title="Blank in busses.csv: the plan's">${esc(shown)}</span>` : DASH);
    }
    if (col === "role" || col === "width" || col === "tap") {
      const choices = col === "role" ? (busKindOf(row.label) === "bus" ? busSheet.roles.bus : busSheet.roles.output)
        : (col === "width" ? ["mono", "stereo"] : ["pre", "post"]);
      const options = choices.slice();
      if (value && options.indexOf(value) === -1) options.push(value);
      const blank = shown ? `(${shown})` : "—";
      return `<select class="cell-select${marks}" ${attrs}>` +
        `<option value=""${value ? "" : " selected"}>${esc(blank)}</option>` +
        options.map((o) => `<option value="${esc(o)}"${o === value ? " selected" : ""}>${esc(o)}</option>`).join("") +
        "</select>";
    }
    const placeholder = shown ? ` placeholder="${esc(shown)}"` : "";
    const wide = col === "sources" ? " cell-wide" : "";
    return `<input type="text" class="cell-text${wide}${marks}" ${attrs}${placeholder} value="${esc(value)}"` +
      ` title="${esc(value || (shown ? "Blank in busses.csv; the plan has " + shown : ""))}">`;
  }

  // Where a row goes, worked out from the other rows' sources (spec §1:
  // "Where it goes is shown, not stored").
  function busFeeds(label, key) {
    const names = [label.toLowerCase(), String(key || "").toLowerCase()];
    return busSheet.rows.filter((r) => r.label !== label).filter((r) => {
      const d = derivedRow(r.label) || {};
      const text = r.values.sources || d.sources || "";
      return text.split(";").some((part) => {
        const name = part.replace(/\((pre|post)\)\s*$/i, "").trim().toLowerCase();
        return name && names.indexOf(name) !== -1;
      });
    }).map((r) => {
      const d = derivedRow(r.label);
      const name = r.values.name || (d && (d.name || d.key)) || "";
      return name && name !== r.label ? `${r.label} ${name}` : r.label;
    });
  }

  function busDetail(row, derived, entry, editable) {
    const fields = BUS_DETAIL_COLS.map(([col, head]) => {
      if (col === "dca" && busKindOf(row.label) !== "bus") return null;
      if (col === "sources" || col === "tap") return [head, busCell(row, col, derived, editable)];
      const shown = derived && derived[col] ? derived[col] : "";
      const value = row.values[col] || "";
      const html = editable
        ? `<input type="text" class="detail-input${busCellEdited(row, col) ? " is-edited" : ""}" ` +
          `data-bus-row="${esc(row.label)}" data-bus-col="${col}" aria-label="${esc(row.label)} ${esc(head)}"` +
          `${shown ? ` placeholder="${esc(shown)}"` : ""} value="${esc(value)}">`
        : (value ? esc(value) : (shown ? esc(shown) : DASH));
      return [head, html];
    });
    const feeds = busFeeds(row.label, derived && derived.key);
    fields.push(["Feeds", (feeds.length ? esc(feeds.join(", ")) : DASH) +
      ' <span class="setup-dim">worked out from the other rows\' sources; edit those to change it</span>']);
    const sheet = kv(fields).replace('<dl class="setup-kv">', '<dl class="setup-kv sheet-kv">');
    if (!entry) return sheet;
    return sheet + kv([
      entry.fader ? ["Fader", `<span class="readout">${esc(faderDesc(entry.fader))}</span>`] : null,
      entry.processing ? ["Processing", esc(processingDesc(entry.processing))] : null,
      entry.preset ? ["Bus preset", esc(busPresetDesc(entry))] : null,
      busEffectDesc(entry) ? ["Effect", esc(busEffectDesc(entry))] : null,
    ]) + renderProvenance(entry.provenance);
  }

  const BUS_COLS = 10;  // #, expand, the six sheet columns, the refusal-free Findings, spare

  // One table's rows: every plan object of `kind` ("bus" / "output"), in the
  // plan's order, then any sheet row the plan does not have yet.
  function busSheetRows(kind, entries, display, cardKind) {
    const editable = busSheet.editable;
    const drawn = {};
    let html = "";
    let i = 0;
    const draw = (label, key, entry, derived) => {
      const row = busRow(label) || { label: label, line: null, values: { bus: label }, original: { bus: label } };
      drawn[label] = true;
      const bd = (display && key != null && display[key]) || {};
      const id = cardId(cardKind, key != null ? key : label);
      html += rowOpen(cardKind, key != null ? key : label, (i % 2 ? "alt" : "") +
        (busRefusals(label).length ? " row-refused" : ""), ` data-bus-label="${esc(label)}"`);
      html += `<td class="col-num">${numChip(bd.label || label.replace(/^Bus /, "B").replace(/^Main /, "M")
        .replace(/^Matrix /, "MX"), bd.colour, cardKind === "output"
        ? "Color: none stated — Apply leaves the desk's" : null)}` +
        `${key != null ? changeChip(cardId(cardKind, key)) : ""}</td>`;
      html += expandCell(cardKind, key != null ? key : label);
      BUS_ROW_COLS.forEach((col) => {
        html += `<td class="${editable && col !== "outputs" ? "cell-input " : ""}col-bus-${col}">${busCell(row, col, derived, editable)}` +
          (col === "name" && !entry ? ' <span class="setup-dim ct-unplanned-note">not in this plan: Save ' +
            "adds it</span>" : "") + "</td>";
      });
      html += findingsCell(id) + "</tr>";
      busRefusals(label).forEach((r) => {
        html += `<tr class="row-refusal" data-refusal-for="${esc(label)}"><td colspan="2"></td>` +
          `<td colspan="${BUS_COLS - 2}">${esc(r.column ? `${r.column}${r.value ? " " + JSON.stringify(r.value) : ""}: ` : "")}` +
          `${esc(r.reason)}</td></tr>`;
      });
      html += detailRow(cardKind, key != null ? key : label, BUS_COLS, busDetail(row, derived, entry, editable));
      i += 1;
    };
    busSheet.derived.filter((d) => (kind === "bus") === (d.kind === "bus")).forEach((d) => {
      draw(d.bus, d.key, entries[d.key], d);
    });
    // Without the bus sheet's payload yet, the plan's own objects.
    if (!busSheet.loaded) {
      Object.keys(entries).forEach((key) => {
        const e = entries[key] || {};
        const label = kind === "bus" ? `Bus ${e.index}` : `${e.kind === "main" ? "Main" : "Matrix"} ${e.index}`;
        if (!drawn[label]) draw(label, key, e, null);
      });
    }
    busSheet.rows.filter((r) => !drawn[r.label] && (kind === "bus") === (busKindOf(r.label) === "bus"))
      .forEach((r) => draw(r.label, null, null, null));
    return html;
  }

  function busTableHead(kind) {
    return "<thead><tr>" +
      `<th class="col-num" title="${kind === "bus" ? "The bus number apply writes it to, in the color it sets"
        : "The Main (M) or Matrix (MX) this row is"}">#</th>` +
      '<th class="col-expand"><span class="visually-hidden">Expand</span></th>' +
      BUS_ROW_COLS.map((col) => `<th class="col-bus-${col}">${esc(BUS_HEADS[col])}</th>`).join("") +
      FINDINGS_TH + "</tr></thead>";
  }

  function busTable(busses, display) {
    return '<div class="table-wrap ct-wrap"><table class="ct ct-compact ct-sheet" id="plan-busses-table">' +
      busTableHead("bus") + `<tbody>${busSheetRows("bus", busses, display, "bus")}</tbody></table></div>`;
  }

  function outputTable(outputs, display) {
    return '<div class="table-wrap ct-wrap"><table class="ct ct-compact ct-sheet" id="plan-outputs-table">' +
      busTableHead("output") + `<tbody>${busSheetRows("output", outputs, display, "output")}</tbody></table></div>`;
  }

  // The Save, Discard and Unsaved badge in a block's header, and the note at
  // the top of its box. Busses and Mains and Matrix write one file, so each carries
  // the same controls, wired to the one editor.
  function busControls() {
    if (!busSheet.editable) return "";
    const locked = busSheet.refusals.length
      ? `Save is locked: ${busSheet.refusals.length} cell(s) cannot work on the desk -- see the red rows.`
      : "";
    return `<span class="state is-warn bus-dirty-badge"${busSheet.dirty ? "" : " hidden"}>Unsaved changes</span>` +
      `<button type="button" class="btn btn-secondary btn-sm" data-bus-discard${busSheet.dirty ? "" : " hidden"}>Discard</button>` +
      // Hidden until there is something to save, as the
      // Channels Save is; locked, with the reason, while a cell is refused.
      `<button type="button" class="btn btn-primary btn-sm" data-bus-save title="${esc(locked || "Save busses.csv")}"` +
      `${busSheet.dirty || busSheet.behind ? "" : " hidden"}` +
      `${busSheet.refusals.length ? " disabled" : ""}>Save busses.csv</button>`;
  }

  function busNoteBox() {
    const locked = busSheet.refusals.length
      ? '<div class="sheet-refusals" role="alert"><strong>Save is locked:</strong> ' +
        `${busSheet.refusals.length} cell(s) cannot work on the desk, each named in red under its row.</div>`
      : "";
    const note = locked + (busSheet.note
      ? `<div class="save-note is-${esc(busSheet.noteKind || "ok")}" role="status">${esc(busSheet.note)}</div>` : "");
    const behind = busSheet.editable && busSheet.behind && !busSheet.dirty
      ? '<div class="save-note is-warn" role="status">busses.csv says things this plan does not ' +
        "have yet (a rebuild replaced them, or it was edited in another program). Save lays the " +
        "sheet onto the plan.</div>" : "";
    return `<div class="sheet-note">${busSheet.editable ? esc(BUS_NOTE)
      : "Read-only: " + esc(busReadOnlyWhy())}</div>${behind}${note}`;
  }

  // The plan on screen is the open show's own plan.json, and the show is
  // not the demo: only then are its sheets edited here.
  function planIsBundlesHere() {
    const b = SP_ && SP_.bundle ? SP_.bundle() : null;
    return !!(b && !b.demo && planIsBundles());
  }

  function busReadOnlyWhy() {
    if (SP_ && SP_.bundle && SP_.bundle() && SP_.bundle().demo) return "the demo show cannot be edited.";
    if (!(SP_ && SP_.bundle && SP_.bundle())) return "there is no show open, so there is no busses.csv to edit.";
    return "this plan is not the open show's plan.json, so it is shown as the plan has it.";
  }

  // ---- the User signals and patches table: user.csv --------
  //
  // One row per USR slot the show uses, in the desk's words: the slot, what
  // it takes (a strip for a user signal, an input socket for a user patch),
  // a user signal's tap and leg, and its name. What reads a slot -- an
  // output fed from it, a channel patched from it -- is shown, as badges,
  // and set in Outputs or Channels. Save writes the whole file.
  const USER_COLS = ["slot", "source", "tap", "leg", "name"];
  const USER_NOTE = "The desk's USR slots this show uses, one row each, in the desk's words. A " +
    "user signal (USR 1-24) takes a channel, aux, bus, Main or Matrix before or after its fader; a " +
    "user patch (USR 25-56) takes an input socket as it is. An output or a channel fed from a slot " +
    "reads it: that is set in Outputs or Channels. Type OFF as the source to take a slot out. " +
    "Save writes user.csv and updates the build plan.";
  const userSheet = {
    loaded: false, source: null, rows: [], original: [], readers: {}, dirty: false,
    refusals: [], note: "", noteKind: "", behind: false, editable: false,
  };

  function userSlotNumber(text) {
    const m = /^\s*(?:usr\s*)?(\d+)\s*$/i.exec(String(text || ""));
    return m ? Number(m[1]) : null;
  }

  function userKind(n) {
    if (n >= 1 && n <= 24) return "user signal";
    if (n >= 25 && n <= 56) return "user patch";
    return "";
  }

  function loadUserSheetPayload(data) {
    userSheet.loaded = true;
    userSheet.source = data.user_sheet || null;
    const rows = (userSheet.source && userSheet.source.present ? userSheet.source.rows : data.derived) || [];
    userSheet.rows = rows.map((r) => Object.assign({}, r));
    userSheet.original = rows.map((r) => Object.assign({}, r));
    userSheet.readers = data.readers || {};
    userSheet.dirty = false;
    userSheet.refusals = [];
    userSheet.behind = !!data.plan_behind;
  }

  function userRowEdited(i, col) {
    const now = userSheet.rows[i] || {};
    const was = userSheet.original[i] || {};
    return (now[col] || "") !== (was[col] || "");
  }

  function userRefusals(label, col) {
    return userSheet.refusals.filter((r) => r.row === label && (col === undefined || r.column === col));
  }

  // Consecutive sockets of one group as one badge: `CRD 27-28`.
  function socketSpans(list) {
    const spans = [];
    list.forEach((words) => {
      const m = /^(.*\D)\s*(\d+)$/.exec(String(words));
      if (!m) { spans.push([words, null, null]); return; }
      const group = m[1].trim();
      const n = Number(m[2]);
      const last = spans[spans.length - 1];
      if (last && last[0] === group && last[2] === n - 1) last[2] = n;
      else spans.push([group, n, n]);
    });
    return spans.map(([g, a, b]) => (a == null ? g : (a === b ? `${g} ${a}` : `${g} ${a}-${b}`)));
  }

  // The name beside a source: the strip's, or the channel on the socket.
  function userSourceName(plan, slot, text) {
    const m = /^\s*(CH|AUX|BUS|MAIN|MTX)\s*(\d+)\s*$/i.exec(String(text || ""));
    if (m) {
      const group = m[1].toUpperCase();
      const n = Number(m[2]);
      if (group === "CH" || group === "AUX") {
        const bank = group === "CH" ? "ch" : "aux";
        const ch = (plan.channels || []).find((c) => c.channel === n && (c.bank || "ch") === bank);
        return ch ? ch.name || "" : "";
      }
      if (group === "BUS") {
        const key = Object.keys(plan.busses || {}).find((k) => (plan.busses[k] || {}).index === n);
        return key || "";
      }
      const kind = group === "MAIN" ? "main" : "matrix";
      const key = Object.keys(plan.outputs || {}).find((k) => (plan.outputs[k] || {}).kind === kind &&
        (plan.outputs[k] || {}).index === n);
      return key || "";
    }
    const s = /^\s*(?:AES50-)?([A-Z]+)\s*(\d+)\s*$/i.exec(String(text || ""));
    if (!s) return "";
    const group = s[1].toUpperCase();
    const n = Number(s[2]);
    const ch = (plan.channels || []).find((c) => c.patch && c.patch.group === group &&
      (c.patch.sockets || []).indexOf(n) !== -1);
    return ch ? ch.name || "" : "";
  }

  function userSelect(i, col, value, choices, extra) {
    const options = choices.slice();
    if (value && options.indexOf(value) === -1) options.push(value);
    return `<select class="cell-select${extra}" data-user-row="${i}" data-user-col="${col}" ` +
      `aria-label="${esc((userSheet.rows[i] || {}).slot || "new slot")} ${col}">` +
      `<option value=""${value ? "" : " selected"}>—</option>` +
      options.map((o) => `<option value="${esc(o)}"${o === value ? " selected" : ""}>${esc(o)}</option>`).join("") +
      "</select>";
  }

  function userTable(plan) {
    const editable = userSheet.editable;
    let html = "";
    userSheet.rows.forEach((row, i) => {
      const n = userSlotNumber(row.slot);
      const label = n != null ? `USR ${n}` : (row.slot || "");
      const kind = n != null ? userKind(n) : "";
      const refused = userRefusals(label);
      const mark = (col) => (userRowEdited(i, col) ? " is-edited" : "") +
        (userRefusals(label, col).length ? " is-refused" : "");
      const field = (col, value, size) => editable
        ? `<input type="text" class="cell-text${mark(col)}" data-user-row="${i}" data-user-col="${col}" ` +
          `aria-label="${esc(label || "new slot")} ${col}" value="${esc(value || "")}"${size || ""}>`
        : (value ? esc(value) : DASH);
      const isPatch = kind === "user patch";
      const tapLeg = (col, choices) => {
        if (isPatch && !(row[col] || "")) return `<span class="setup-dim">${DASH}</span>`;
        return editable ? userSelect(i, col, row[col] || "", choices, mark(col)) : (row[col] ? esc(row[col]) : DASH);
      };
      const reads = socketSpans(userSheet.readers[String(n)] || []);
      const name = userSourceName(plan, n, row.source);
      html += `<tr class="row-primary${i % 2 ? " alt" : ""}${refused.length ? " row-refused" : ""} user-row" ` +
        `data-user-label="${esc(label)}">` +
        `<td class="col-user-slot">${editable && userRowEdited(i, "slot") && !(userSheet.original[i] || {}).slot
          ? field("slot", row.slot, ' size="7"') : `<span class="badge-ro user-slot">${esc(label)}</span>`}` +
        (kind ? ` <span class="user-kind">${esc(kind)}</span>` : "") + "</td>" +
        `<td class="cell-input col-user-source">${field("source", row.source)}` +
        (name ? ` <span class="setup-dim user-src-name">${esc(name)}</span>` : "") + "</td>" +
        `<td class="cell-input col-user-tap">${tapLeg("tap", ["PRE", "POST"])}</td>` +
        `<td class="cell-input col-user-leg">${tapLeg("leg", ["L+R", "L", "R"])}</td>` +
        `<td class="cell-input col-user-name">${field("name", row.name)}</td>` +
        `<td class="col-user-readby">${reads.length
          ? reads.map((r) => `<span class="badge-ro" title="${esc(r)} is fed from ${esc(label)}">${esc(r)}</span>`).join("")
          : `<span class="setup-dim">read by nothing yet${editable ? ": patch an output or a channel to " + esc(label) : ""}</span>`}</td>` +
        "</tr>";
      refused.forEach((r) => {
        html += `<tr class="row-refusal"><td></td><td colspan="5">${esc(r.column ? `${r.column}${r.value ? " " + JSON.stringify(r.value) : ""}: ` : "")}` +
          `${esc(r.reason)}</td></tr>`;
      });
    });
    return '<div class="table-wrap ct-wrap"><table class="ct ct-compact ct-sheet" id="plan-user-table">' +
      "<thead><tr>" +
      '<th class="col-user-slot">Slot</th>' +
      '<th class="col-user-source" title="What the slot takes: a strip (user signal) or an input socket (user patch)">Source</th>' +
      '<th class="col-user-tap" title="A user signal\'s tap: before (PRE) or after (POST) its fader">Tap</th>' +
      '<th class="col-user-leg" title="Which side of a stereo strip: both summed, left or right">Leg</th>' +
      '<th class="col-user-name">Name</th>' +
      '<th class="col-user-readby" title="The outputs and channels fed from this slot: set those in Outputs or Channels">Read by</th>' +
      `</tr></thead><tbody>${html}</tbody></table></div>`;
  }

  function userControls() {
    if (!userSheet.editable) return "";
    const locked = userSheet.refusals.length
      ? `Save is locked: ${userSheet.refusals.length} cell(s) cannot work on the desk -- see the red rows.`
      : "";
    return `<span class="state is-warn user-dirty-badge"${userSheet.dirty ? "" : " hidden"}>Unsaved changes</span>` +
      `<button type="button" class="btn btn-secondary btn-sm" data-user-discard${userSheet.dirty ? "" : " hidden"}>Discard</button>` +
      `<button type="button" class="btn btn-primary btn-sm" data-user-save title="${esc(locked || "Save user.csv")}"` +
      `${userSheet.dirty || userSheet.behind ? "" : " hidden"}${userSheet.refusals.length ? " disabled" : ""}>Save user.csv</button>` +
      '<button type="button" class="btn btn-secondary btn-sm" data-user-add>Add a slot</button>';
  }

  function userNoteBox() {
    const locked = userSheet.refusals.length
      ? '<div class="sheet-refusals" role="alert"><strong>Save is locked:</strong> ' +
        `${userSheet.refusals.length} cell(s) cannot work on the desk, each named in red under its row.</div>`
      : "";
    const note = userSheet.note
      ? `<div class="save-note is-${esc(userSheet.noteKind || "ok")}" role="status">${esc(userSheet.note)}</div>` : "";
    const behind = userSheet.editable && userSheet.behind && !userSheet.dirty
      ? '<div class="save-note is-warn" role="status">user.csv says things this plan does not have ' +
        "yet (a rebuild replaced them, or it was edited in another program). Save lays the sheet " +
        "onto the plan.</div>" : "";
    return `<div class="sheet-note">${userSheet.editable ? esc(USER_NOTE)
      : "Read-only: " + esc(busReadOnlyWhy().replace("busses.csv", "user.csv"))}</div>${behind}${locked}${note}`;
  }

  // ---- the Outputs table: outputs.csv --------------------
  //
  // One row per output socket the desk patches, in the desk's words: the
  // socket, what feeds it, notes. Runs of sockets that go up together, fed
  // by sources that go up together, show folded as one line of read-only
  // badges; open one to edit its rows. A show with no outputs.csv yet shows
  // the plan's own rows, and its first Save writes the file. The row's left
  // edge says what feeds it; the swatch is the desk's own colour for the
  // source.
  const OUT_COLS = ["output", "source", "notes"];
  const OUT_NOTE = "Every output socket the desk patches, one row each: what feeds it, in the " +
    "desk's own words. Runs that go up together show as one line; open one to edit its rows. Type " +
    "OFF as the source to disconnect a socket. Save writes outputs.csv and updates the build plan.";
  const OUT_KINDS = [["split", "straight from an input socket"], ["mix", "a bus, Main or Matrix"],
    ["usr", "a user signal or patch (USR)"], ["other", "a send, the monitor or the oscillator"]];
  const outSheet = {
    loaded: false, source: null, rows: [], original: [], display: { sockets: {}, objects: {} },
    dirty: false, refusals: [], note: "", noteKind: "", behind: false, editable: false, open: {},
  };
  const OUT_OBJECT_WORDS = { bus: "Bus", main: "Main", matrix: "Matrix", mtx: "Matrix", mx: "Matrix" };

  // `LCL 3` -> {group: "LCL", n: 3}; `AES50-B 12` keeps its whole group.
  function outParseSocket(text) {
    const m = /^\s*(AES50-[ABC]|[A-Z]+)\s*(\d+)\s*$/i.exec(String(text || ""));
    return m ? { group: m[1].toUpperCase(), n: Number(m[2]) } : null;
  }

  // A source cell: an input socket (`split`), a bus's, Main's or Matrix's
  // side (`mix`, with its object, `Bus 9`), a user signal or patch (`usr`),
  // or a send, the monitor or the oscillator (`other`). Null for OFF, a
  // blank, or words the server will refuse.
  function outParseSource(text) {
    const t = String(text || "").trim();
    let m = /^(bus|main|matrix|mtx|mx)\s*(\d+)\s*([LR])$/i.exec(t);
    if (m) {
      const kind = OUT_OBJECT_WORDS[m[1].toLowerCase()];
      const n = Number(m[2]);
      return { kind: "mix", group: kind, n: 2 * n - (m[3].toUpperCase() === "L" ? 1 : 0),
        obj: `${kind} ${n}`, side: m[3].toUpperCase() };
    }
    m = /^(USR|SEND|MON|OSC)\s*(\d+)$/i.exec(t);
    if (m) return { kind: m[1].toUpperCase() === "USR" ? "usr" : "other", group: m[1].toUpperCase(), n: Number(m[2]) };
    const s = outParseSocket(t);
    return s && !/^OFF$/i.test(t) ? { kind: "split", group: s.group, n: s.n } : null;
  }

  function outLabel(row) {
    const s = outParseSocket(row && row.output);
    return s ? `${s.group} ${s.n}` : String((row && row.output) || "").trim();
  }

  function loadOutputsSheetPayload(data) {
    outSheet.loaded = true;
    outSheet.source = data.outputs_sheet || null;
    const rows = (outSheet.source ? outSheet.source.rows : data.derived) || [];
    outSheet.rows = rows.map((r) => Object.assign({}, r));
    outSheet.original = rows.map((r) => Object.assign({}, r));
    outSheet.display = data.display || { sockets: {}, objects: {} };
    outSheet.dirty = false;
    outSheet.refusals = [];
    outSheet.behind = !!data.plan_behind;
  }

  function outRowEdited(i, col) {
    const now = outSheet.rows[i] || {};
    const was = outSheet.original[i] || {};
    return (now[col] || "") !== (was[col] || "");
  }

  function outRefusals(label, col) {
    return outSheet.refusals.filter((r) => r.row === label && (col === undefined || r.column === col));
  }

  // The rows as runs, from the sheet as it was read (an edit does not fold
  // or unfold the table under the cursor): consecutive sockets of one group,
  // fed by consecutive sources of one group, a bus's, Main's or Matrix's run
  // staying on its one object. Each run is a list of row indexes.
  function outRuns() {
    const runs = [];
    outSheet.rows.forEach((_row, i) => {
      const row = outSheet.original[i] || {};
      const out = outParseSocket(row.output);
      const src = outParseSource(row.source);
      const last = runs.length ? runs[runs.length - 1] : null;
      const prev = last ? outSheet.original[last[last.length - 1]] || {} : null;
      const pOut = prev && outParseSocket(prev.output);
      const pSrc = prev && outParseSource(prev.source);
      if (out && src && pOut && pSrc && out.group === pOut.group && out.n === pOut.n + 1 &&
          src.kind === pSrc.kind && src.group === pSrc.group && src.n === pSrc.n + 1 &&
          (src.kind !== "mix" || src.obj === pSrc.obj)) {
        last.push(i);
      } else {
        runs.push([i]);
      }
    });
    return runs;
  }

  function outRunWords(run) {
    const first = outSheet.original[run[0]] || {};
    const last = outSheet.original[run[run.length - 1]] || {};
    const a = outParseSocket(first.output);
    const b = outParseSocket(last.output);
    const src = outParseSource(first.source);
    const end = outParseSource(last.source);
    const output = `${a.group} ${a.n}-${b.n}`;
    const source = src.kind === "mix" ? `${src.obj} L-R` : `${src.group} ${src.n}-${end.n}`;
    return [output, source];
  }

  function outSwatch(src) {
    const d = outSheet.display || {};
    let colour = null;
    if (src && src.kind === "mix") colour = ((d.objects || {})[src.obj] || {}).colour;
    else if (src && src.kind === "split") colour = (d.sockets || {})[`${src.group} ${src.n}`];
    if (!colour) return '<span class="out-no-swatch" aria-hidden="true"></span>';
    const what = src.kind === "mix" ? src.obj : `${src.group} ${src.n}`;
    return `<span class="colour-chip" data-colour="${esc(colour)}" ` +
      `title="${esc(colour.charAt(0).toUpperCase() + colour.slice(1))}, the desk's color for ${esc(what)}"></span>`;
  }

  function outObjectName(src) {
    if (!src || src.kind !== "mix") return "";
    const name = (((outSheet.display || {}).objects || {})[src.obj] || {}).name || "";
    return name && name !== src.obj ? ` <span class="setup-dim out-objname">${esc(name)}</span>` : "";
  }

  function outRowHtml(i, alt, member) {
    const row = outSheet.rows[i];
    const label = outLabel(row);
    const editable = outSheet.editable;
    const src = outParseSource(row.source);
    const refused = outRefusals(label);
    const mark = (col) => (outRowEdited(i, col) ? " is-edited" : "") +
      (outRefusals(label, col).length ? " is-refused" : "");
    const field = (col, extra) => editable
      ? `<input type="text" class="cell-text${mark(col)}${extra || ""}" data-out-row="${i}" ` +
        `data-out-col="${col}" aria-label="${esc(label || "new socket")} ${col}" value="${esc(row[col] || "")}"` +
        ` title="${esc(row[col] || "")}">`
      : `<span class="out-text">${row[col] ? esc(row[col]) : DASH}</span>`;
    let html = `<tr class="row-primary out-row out-kind-${src ? src.kind : "none"}${alt ? " alt" : ""}` +
      `${member ? " out-run-member" : ""}${refused.length ? " row-refused" : ""}" data-out-label="${esc(label)}">` +
      '<td class="col-expand"></td>' +
      `<td class="cell-input col-out-output">${field("output")}</td>` +
      `<td class="cell-input col-out-source"><span class="out-arrow" aria-hidden="true">&larr;</span>` +
      `${outSwatch(src)}${field("source")}${outObjectName(src)}</td>` +
      `<td class="cell-input col-out-notes">${field("notes")}</td>` +
      findingsCell(cardId("socket", label)) + "</tr>";
    refused.forEach((r) => {
      html += `<tr class="row-refusal"><td></td><td colspan="4">${esc(r.column ? `${r.column}${r.value ? " " + JSON.stringify(r.value) : ""}: ` : "")}` +
        `${esc(r.reason)}</td></tr>`;
    });
    return html;
  }

  function outRunHtml(run, alt, open) {
    const [output, source] = outRunWords(run);
    const src = outParseSource((outSheet.original[run[0]] || {}).source);
    const key = (outSheet.original[run[0]] || {}).output || "";
    const what = open ? "hide" : "show";
    const cell = (text) => open ? `<span class="out-run-text">${esc(text)}</span>`
      : `<span class="badge-ro out-badge" title="Open the run to edit its ${run.length} sockets">${esc(text)}</span>`;
    return `<tr class="row-primary out-run ${open ? "out-run-open" : "out-run-closed"} ` +
      `out-kind-${src ? src.kind : "none"}${alt ? " alt" : ""}" data-out-run="${esc(key)}">` +
      `<td class="col-expand"><button type="button" class="row-expand-btn" data-out-toggle="${esc(key)}" ` +
      `aria-expanded="${open ? "true" : "false"}" aria-label="${esc(output)}: ${what} its ${run.length} rows">` +
      '<span class="chevron" aria-hidden="true">&#9656;</span></button></td>' +
      `<td class="col-out-output">${cell(output)}</td>` +
      `<td class="col-out-source"><span class="out-arrow" aria-hidden="true">&larr;</span>` +
      `${outSwatch(src)}${cell(source)}${outObjectName(src)}</td>` +
      '<td class="col-out-notes"></td><td class="col-findings"></td></tr>';
  }

  function outputsTable() {
    let html = "";
    let alt = false;
    outRuns().forEach((run) => {
      if (run.length === 1) {
        html += outRowHtml(run[0], alt, false);
      } else {
        const key = (outSheet.original[run[0]] || {}).output || "";
        // A run with an edited or refused row stays open: its rows are where
        // the edit is.
        const busy = run.some((i) => OUT_COLS.some((c) => outRowEdited(i, c)) ||
          outRefusals(outLabel(outSheet.rows[i])).length);
        const open = !!outSheet.open[key] || busy;
        html += outRunHtml(run, alt, open);
        if (open) run.forEach((i, j) => { html += outRowHtml(i, j % 2 === 1, true); });
      }
      alt = !alt;
    });
    return '<div class="table-wrap ct-wrap"><table class="ct ct-compact ct-sheet" id="plan-sockets-table">' +
      "<thead><tr>" +
      '<th class="col-expand"><span class="visually-hidden">Expand</span></th>' +
      '<th class="col-out-output" title="The output socket, as the desk names it">Output</th>' +
      '<th class="col-out-source" title="What feeds it: one of the desk\'s source groups and a number">Source</th>' +
      '<th class="col-out-notes">Notes</th>' + FINDINGS_TH +
      `</tr></thead><tbody>${html}</tbody></table></div>`;
  }

  function outControls() {
    if (!outSheet.editable) return "";
    const locked = outSheet.refusals.length
      ? `Save is locked: ${outSheet.refusals.length} cell(s) cannot work on the desk -- see the red rows.`
      : "";
    const unsaved = outSheet.dirty || outSheet.behind || !(outSheet.source && outSheet.source.present);
    return `<span class="state is-warn out-dirty-badge"${outSheet.dirty ? "" : " hidden"}>Unsaved changes</span>` +
      `<button type="button" class="btn btn-secondary btn-sm" data-out-discard${outSheet.dirty ? "" : " hidden"}>Discard</button>` +
      `<button type="button" class="btn btn-primary btn-sm" data-out-save title="${esc(locked || "Save outputs.csv")}"` +
      `${unsaved ? "" : " hidden"}${outSheet.refusals.length ? " disabled" : ""}>Save outputs.csv</button>` +
      '<button type="button" class="btn btn-secondary btn-sm" data-out-add>Add a socket</button>';
  }

  function outNoteBox() {
    const locked = outSheet.refusals.length
      ? '<div class="sheet-refusals" role="alert"><strong>Save is locked:</strong> ' +
        `${outSheet.refusals.length} cell(s) cannot work on the desk, each named in red under its row.</div>`
      : "";
    const note = outSheet.note
      ? `<div class="save-note is-${esc(outSheet.noteKind || "ok")}" role="status">${esc(outSheet.note)}</div>` : "";
    const fresh = outSheet.editable && outSheet.source && !outSheet.source.present && !outSheet.dirty
      ? '<div class="save-note is-warn" role="status">This show has no outputs.csv yet -- these are ' +
        "the plan's outputs. Save writes outputs.csv, which will then take priority over " +
        "conventions and instructions during a build.</div>" : "";
    const behind = outSheet.editable && outSheet.behind && !outSheet.dirty
      ? '<div class="save-note is-warn" role="status">outputs.csv says things this plan does not have ' +
        "yet (a rebuild replaced them, or it was edited in another program). Save lays the sheet " +
        "onto the plan.</div>" : "";
    const legend = '<div class="out-legend" aria-label="What the edge of a row says">' +
      OUT_KINDS.map(([kind, words]) => `<span class="out-key out-kind-${kind}">${esc(words)}</span>`).join("") +
      '<span class="out-key-note"><span class="colour-chip" data-colour="red"></span>' +
      "the desk's own color for the source</span></div>";
    return `<div class="sheet-note">${outSheet.editable ? esc(OUT_NOTE)
      : "Read-only: " + esc(busReadOnlyWhy().replace("busses.csv", "outputs.csv"))}</div>` +
      `${fresh}${behind}${locked}${note}${legend}`;
  }

  // A bus's, Main's or Matrix's sockets, as the Outputs table has them now:
  // read-only badges in its Busses or Mains and Matrix row (edit them in
  // Outputs).
  function busOutputBadges(label, derived) {
    let words = [];
    if (outSheet.loaded) {
      outSheet.rows.forEach((row) => {
        const src = outParseSource(row.source);
        if (src && src.kind === "mix" && src.obj === label) words.push(outLabel(row));
      });
      words = socketSpans(words);
    } else if (derived && derived.outputs) {
      words = String(derived.outputs).split(/[;,]/).map((w) => w.trim()).filter((w) => w);
    }
    if (!words.length) return `<span class="setup-dim">${DASH}</span>`;
    return words.map((w) => `<span class="badge-ro" title="${esc(w)} carries ${esc(label)}; edit it in Outputs">` +
      `${esc(w)}</span>`).join("");
  }

  // ---- the table's own controls ----------------------------------------
  // Kept across a redraw (an edit in step 02, a Save, a rebuild): which
  // column groups are open, and which rows.

  const tableState = { open: {} };

  function setDetail(row, open) {
    if (!row || !row.id) return;
    const button = row.querySelector(".row-expand-btn");
    const detail = document.getElementById(row.id + "-detail");
    if (!button || !detail) return;
    button.setAttribute("aria-expanded", String(open));
    detail.hidden = !open;
    if (open) tableState.open[row.id] = true;
    else delete tableState.open[row.id];
  }

  function restoreOpenRows() {
    Object.keys(tableState.open).forEach((id) => setDetail(document.getElementById(id), true));
  }

  // Wired once, on the container the tables are drawn into, so a redraw
  // does not have to re-bind anything.
  function bindTableEvents(container) {
    container.addEventListener("click", (ev) => {
      // An Outputs run folds and unfolds its own rows.
      const runToggle = ev.target.closest("[data-out-toggle]");
      if (runToggle) { toggleOutRun(runToggle.dataset.outToggle); return; }
      const expand = ev.target.closest(".row-expand-btn");
      if (expand) {
        const row = expand.closest("tr.row-primary");
        setDetail(row, expand.getAttribute("aria-expanded") !== "true");
        return;
      }
      if (ev.target.closest("[data-bus-save]")) {
        saveBusSheet();
        return;
      }
      if (ev.target.closest("[data-bus-discard]")) {
        discardBusSheet();
        return;
      }
      if (ev.target.closest("[data-user-save]")) { saveUserSheet(); return; }
      if (ev.target.closest("[data-user-discard]")) { discardUserSheet(); return; }
      if (ev.target.closest("[data-user-add]")) { addUserSlot(); return; }
      if (ev.target.closest("[data-out-save]")) { saveOutputsSheet(); return; }
      if (ev.target.closest("[data-out-discard]")) { discardOutputsSheet(); return; }
      if (ev.target.closest("[data-out-add]")) { addOutSocket(); return; }
      const note = ev.target.closest("[data-note-key]");
      if (note && SP_ && SP_.inputEditor && SP_.inputEditor.editNote) {
        SP_.inputEditor.editNote(note.dataset.noteKey, note);
        return;
      }
      const badge = ev.target.closest(".fbadge");
      if (badge && SP_ && SP_.showFindings) {
        const td = badge.closest("[data-findings-for]");
        const list = td ? rowFindings(td.dataset.findingsFor)[badge.dataset.sev] || [] : [];
        SP_.showFindings(list);
        return;
      }
      const remove = ev.target.closest("[data-input-remove]");
      if (remove && SP_ && SP_.inputEditor) SP_.inputEditor.remove(remove.dataset.inputRemove);
    });
    const edit = (ev) => {
      const input = ev.target;
      if (input.dataset && input.dataset.busCol) {
        if ((input.tagName === "SELECT") !== (ev.type === "change")) return;
        editBusCell(input);
        return;
      }
      if (input.dataset && input.dataset.userCol) {
        if ((input.tagName === "SELECT") !== (ev.type === "change")) return;
        editUserCell(input);
        return;
      }
      if (input.dataset && input.dataset.outCol) {
        if (ev.type === "change") return;
        editOutCell(input);
        return;
      }
      if (!input.dataset || !input.dataset.inputCol || !SP_ || !SP_.inputEditor) return;
      const col = input.dataset.inputCol;
      if ((col === "phantom") !== (ev.type === "change")) return;
      SP_.inputEditor.set(input.dataset.inputKey, col, col === "phantom" ? input.checked : input.value);
    };
    container.addEventListener("input", edit);
    container.addEventListener("change", edit);
    // A finding's jump link landed on a row: open what is behind it.
    container.addEventListener("atoo:jump", (ev) => {
      const row = ev.target.closest && ev.target.closest("tr.row-primary");
      if (row) setDetail(row, true);
    });
  }

  // An edit made in step 04 does not redraw the table under the cursor;
  // it only re-marks the rows step 02 says are incomplete.
  function markRowProblems() {
    if (!SP_ || !SP_.inputEditor) return;
    SP_.inputEditor.rows().forEach((row) => {
      document.querySelectorAll('#plan-rows tr[data-input-key="' + row.key + '"]').forEach((tr) => {
        tr.classList.toggle("row-invalid", !!row.problems);
        tr.title = row.problems;
      });
    });
  }

  // ---- the Findings column ---------------------------------------------
  // One per row: coloured badges counting that row's
  // findings in the dock -- E (errors, red), W (warnings, amber) and I
  // (info, quiet: an inferred choice announces itself at INFO, so it is
  // worth a glance, but it is drawn outlined so it never outshouts a
  // warning). A finding belongs to a row when one of its jump links lands
  // on that row (`#plan-channel-kick`), or its `where` names it -- the
  // dock's own targeting (see findingRowIds). Ticked (addressed) findings
  // are not counted, as the dock's own count does not count them.
  // Redrawn whenever the dock is (`onFindingsChange`), and after every
  // table draw.
  const FINDING_SEVS = [["error", "E", "error"], ["warning", "W", "warning"], ["info", "I", "info"]];

  // The rows a finding is about: every row one of its jump links lands
  // on, and the row its structured `where` names (`channels[Snare].patch`)
  // -- which is how step 04 builds those jump links (`planObjectFor`), and
  // what reaches a finding whose own link goes elsewhere: Apply's
  // pre-flight verify of plan.json links to its own panel, but
  // `channels[Snare].patch` is still Snare's row.
  const WHERE_KINDS = { channels: "channel", busses: "bus", outputs: "output", direct_outputs: "socket" };

  function findingRowIds(f) {
    const ids = {};
    // FR-X.15c: a grouped item stands for its `members`, and belongs to
    // every row one of them is about.
    (Array.isArray(f.members) ? f.members : []).forEach((m) => {
      Object.assign(ids, findingRowIds(m));
    });
    (Array.isArray(f.jumps) ? f.jumps : []).forEach((j) => {
      if (j && typeof j.target === "string" && /^#plan-(channel|bus|output)-/.test(j.target)) {
        ids[j.target.slice(1)] = true;
      }
    });
    const m = /^(channels|busses|outputs|direct_outputs)\[([^\]]+)\]/.exec(f.where || "");
    if (m) ids[cardId(WHERE_KINDS[m[1]], m[2])] = true;
    return ids;
  }

  function rowFindings(id) {
    const out = { error: [], warning: [], info: [] };
    if (!SP_ || !SP_.findings) return out;
    // What the dock shows: a finding two producers published
    // is one row there, so it is one on the badge too.
    (SP_.shownFindings ? SP_.shownFindings() : SP_.findings()).forEach((f) => {
      if (f._resolved) return;
      if (!findingRowIds(f)[id]) return;
      const sev = out[f.severity] ? f.severity : "info";
      out[sev].push(f);
    });
    return out;
  }

  function paintFindingBadges() {
    document.querySelectorAll("#plan-render [data-findings-for]").forEach((td) => {
      const found = rowFindings(td.dataset.findingsFor);
      td.innerHTML = FINDING_SEVS.filter(([sev]) => found[sev].length).map(([sev, letter, word]) => {
        const n = found[sev].length;
        const title = `${n} ${word}${n === 1 ? "" : "s"} about this row in the findings list -- click to find ` +
          (n === 1 ? "it" : "them");
        return `<button type="button" class="fbadge fbadge-${sev}" data-sev="${sev}" title="${esc(title)}" ` +
          `aria-label="${esc(title)}">${letter}<span class="fbadge-n">${n}</span></button>`;
      }).join("");
    });
  }

  // ---- Build status -- surfaces plan["meta"], minus
  // its findings. After a plan is rebuilt
  // there is typically a very long list of warnings and info findings down
  // the page under the build status, and that is what the sidebar is for:
  // the plan's verify, critic and build findings are listed in the dock
  // and only there. This step keeps ONE line counting them, with a link
  // that opens the dock -- and says whether verify and the critic ran at
  // all, the one thing the dock cannot: `critic_findings` and
  // `verify_findings` are each None when that pass never ran, distinct
  // from an empty list/dict meaning it ran and found nothing.

  function countLine(counts) {
    const parts = [];
    [["error", "error", "errors"], ["warning", "warning", "warnings"], ["info", "info", "info"]]
      .forEach(([sev, one, many]) => {
        if (counts[sev]) parts.push(counts[sev] + " " + (counts[sev] === 1 ? one : many));
      });
    return parts.join(", ");
  }

  function paintFindingsSummary() {
    const line = document.getElementById("plan-findings-summary");
    if (!line || !SP_) return;
    const meta = (current && current.plan && current.plan.meta) || {};
    const counts = { error: 0, warning: 0, info: 0 };
    const shown = SP_.shownFindings ? SP_.shownFindings() : SP_.findings();
    shown.forEach((f) => {
      if (f._resolved || PLAN_PRODUCERS.indexOf(f._producer) === -1) return;
      counts[counts[f.severity] != null ? f.severity : "info"] += 1;
    });
    const ran = [];
    if (meta.verify_findings == null) ran.push("verify not run");
    if (meta.critic_findings == null) ran.push("critic not run");
    const text = countLine(counts);
    line.textContent = "";
    const words = document.createElement("span");
    words.textContent = (text ? "Findings: " + text : "No findings")
      + (ran.length ? " (" + ran.join(", ") + ")" : "");
    line.appendChild(words);
    if (text) {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "findings-summary-link";
      link.textContent = "in Findings →";
      link.addEventListener("click", () => { if (SP_.revealDock) SP_.revealDock(); });
      line.appendChild(link);
    }
  }

  // Build log: each role's own
  // thinking-SUMMARY lines, with elapsed seconds -- kept for a human
  // reviewing a batch of builds later (`atoo lessons`), never
  // recomputed or re-sent anywhere from here. Collapsed by default: it
  // is the one block on this page nobody needs to see to build the
  // show, and a build can carry hundreds of lines of it.
  function renderBuildLog(buildLog) {
    if (!buildLog || !Object.keys(buildLog).length) return "";
    let body = "";
    for (const role of Object.keys(buildLog).sort()) {
      const entry = buildLog[role] || {};
      const notes = entry.notes || [];
      const usage = entry.usage || {};
      const usageBits = [];
      if (usage.input != null || usage.output != null) {
        // Claude's prompt cache. "in" is every input token;
        // what was read from and written to the cache follows it.
        const cacheBits = [];
        if (usage.cache_read) cacheBits.push(`${esc(usage.cache_read)} read from cache`);
        if (usage.cache_write) cacheBits.push(`${esc(usage.cache_write)} written to cache`);
        usageBits.push(`${esc(usage.input != null ? usage.input : "?")} in` +
          (cacheBits.length ? ` (${cacheBits.join(", ")})` : "") +
          `, ${esc(usage.output != null ? usage.output : "?")} out`);
      }
      // "~" marks an estimate (Claude reports no separate count).
      if (usage.thinking) {
        usageBits.push(`${usage.thinking_source === "reported" ? "" : "~"}` +
          `${esc(usage.thinking)} thinking`);
      }
      if (usage.cost != null) usageBits.push(`$${esc(usage.cost.toFixed(2))}`);
      // The critic and the watchlist run on their own model (Haiku by
      // default, 2026-09-28), so the heading names it: "critic
      // (claude-haiku-4-5, 41,771 in, ...)" reads differently from the
      // generator's line, and should.
      if (usage.model) usageBits.unshift(esc(usage.model));
      if (usage.effort) usageBits.push(`effort ${esc(usage.effort)}`);
      body += `<div class="setup-buildlog-role"><h4>${esc(role)}` +
        (usageBits.length ? ` <span class="setup-dim">(${usageBits.join(", ")})</span>` : "") +
        "</h4>";
      if (!notes.length) {
        body += '<p class="setup-dim">No thinking-summary lines recorded.</p>';
      } else {
        body += '<ul class="setup-buildlog-notes">';
        for (const n of notes) {
          const t = typeof n.t === "number" ? `${n.t.toFixed(1)}s` : "?";
          body += `<li><span class="setup-dim">${esc(t)}</span> ${esc(n.text || "")}</li>`;
        }
        body += "</ul>";
      }
      body += "</div>";
    }
    return '<details class="setup-provenance setup-buildlog"><summary>Build log</summary>' +
      body + "</details>";
  }

  // ---- Step 04's Plan block -------------------------------
  // One block, three sections, in this order: Options (in
  // shell.html), Build output, and Changed since the last build. The
  // tables follow as blocks of their own. A block's header sits outside
  // its box; a section inside it has a grey caps heading.

  // The console models' names, for "built ... for a WING Compact": set by
  // the controller below from the startup data.
  let consoleNames = {};
  // `previous_generated_at` from GET /api/plan: when the plan this one
  // replaced was built, for "It replaced plan.previous.json, built 03:33".
  function fmtWhen(iso, timeOnly) {
    const d = new Date(iso);
    if (!iso || isNaN(d.getTime())) return iso ? String(iso) : "";
    const pad = (n) => String(n).padStart(2, "0");
    const time = pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes());
    if (timeOnly) return time;
    return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate())
      + " " + time + " UTC";
  }

  function sameDay(a, b) {
    const x = new Date(a);
    const y = new Date(b);
    return !isNaN(x.getTime()) && !isNaN(y.getTime())
      && x.toISOString().slice(0, 10) === y.toISOString().slice(0, 10);
  }

  // "The plan in demo-show/plan.json, built 2026-10-13 13:39 UTC for a
  // WING Compact. It replaced plan.previous.json, built 03:33."
  function sourceLine(plan, where) {
    const meta = plan.meta || {};
    const path = where && (where.display_path || where.path);
    let html = path
      ? `The plan in <code title="${esc(where.path || "")}">${esc(path)}</code>`
      : "The plan (no path recorded)";
    if (meta.generated_at) html += `, built ${esc(fmtWhen(meta.generated_at))}`;
    // Which WING this plan's socket numbers were checked
    // against. A plan built before then has no such field; say so rather
    // than leave it out.
    html += meta.console_model
      ? ` for a <b>${esc(consoleNames[meta.console_model] || meta.console_model)}</b>.`
      : '. <span class="meta">Console model not stated -- built by an older version.</span>';
    const changes = changesOf(plan);
    if (changes) {
      const prev = where && where.previous_generated_at;
      html += ` <span class="meta">It replaced <code>${esc(changes.against || "plan.previous.json")}</code>` +
        (prev ? `, built ${esc(fmtWhen(prev, sameDay(prev, meta.generated_at)))}` : "") + ".</span>";
    }
    return html;
  }

  // Verify's verdict as one severity tag -- today's run when the server
  // ran verify now (`verify_now`, the open bundle's own plan), else the
  // one the build recorded -- then the line counting the findings
  // (`paintFindingsSummary`, redrawn whenever the dock is).
  function verifyLine(meta) {
    const v = (current && current.verify_now) || meta.verify_at_generation;
    let html = "";
    if (v) {
      // Severity tags; a skipped verify is
      // a neutral state, not a note.
      let cls = "state";
      let label = v.summary || "Skipped";
      if (!v.skipped) {
        const errors = Number(v.error_count) || 0;
        const warnings = Number(v.warning_count) || 0;
        cls = "sev " + (errors ? "sev-error" : (warnings ? "sev-warning" : "sev-ok"));
        label = `Verify: ${errors} error${errors === 1 ? "" : "s"} · ` +
          `${warnings} warning${warnings === 1 ? "" : "s"}`;
      }
      html += `<span class="${cls}" id="plan-verify-badge">${esc(label)}</span>`;
    }
    return html + '<span class="findings-summary" id="plan-findings-summary"></span>';
  }

  // The plan in one line of counts (the plan stats could be condensed a lot).
  function factsLine(plan) {
    const channels = (plan.channels || []).filter((c) => c && typeof c === "object");
    const aux = channels.filter((c) => c.bank === "aux");
    const strips = channels.filter((c) => c.bank !== "aux");
    const stereo = strips.filter(isStereo).length;
    const count = (n, one, many, extra) =>
      `<span><b>${n}</b> ${n === 1 ? one : many}${extra ? ` <span class="meta">(${extra})</span>` : ""}</span>`;
    const n = (obj) => Object.keys(obj || {}).length;
    return '<p class="facts" id="plan-facts">' +
      count(strips.length, "channel", "channels", stereo ? `${stereo} stereo` : "") +
      (aux.length ? count(aux.length, "aux", "aux") : "") +
      count(n(plan.busses), "bus", "busses") +
      count(n(plan.outputs), "output", "outputs") +
      count(n(plan.dcas), "DCA", "DCAs") +
      count(n(plan.mute_groups), "mute group", "mute groups") +
      count((plan.unassigned_inputs || []).length, "input left unassigned", "inputs left unassigned") +
      "</p>";
  }

  // The model's notes and the build details go
  // together under ONE folded Details line, no more prominent than the
  // notes, to reduce clutter. A
  // `repair` note says how a slip in the model's reply was read -- build
  // plumbing, not a note about the show -- and is the "build details"
  // half.
  function detailsFold(plan) {
    const allNotes = plan.notes || [];
    const detailNotes = allNotes.filter(isDetailNote);
    const showNotes = allNotes.filter((n) => !isDetailNote(n));
    const meta = plan.meta || {};
    const log = renderBuildLog(meta.build_log);
    if (!allNotes.length && !log) return "";
    const bits = [];
    // Who wrote each note: a capture's choices, and a step 04
    // Save's, are not the model's.
    const NOTE_AUTHORS = [["capture", "from the capture"], ["sheets", "on the desk sheets"]];
    const byAuthor = NOTE_AUTHORS.map(([source, words]) =>
      [words, showNotes.filter((n) => n && n.source === source)]);
    const fromModel = showNotes.filter((n) => !(n && NOTE_AUTHORS.some(([s]) => s === n.source)));
    const count = (n, words) => `${n} note${n === 1 ? "" : "s"} ${words}`;
    if (fromModel.length) bits.push(count(fromModel.length, "from the model"));
    byAuthor.forEach(([words, notes]) => { if (notes.length) bits.push(count(notes.length, words)); });
    if (detailNotes.length) {
      bits.push(`${detailNotes.length} line${detailNotes.length === 1 ? "" : "s"} on how the reply was read`);
    }
    if (log) bits.push("the build log");
    let html = '<details class="fold-details" id="plan-notes-details">' +
      `<summary>Details<span class="meta"> · ${esc(bits.join(" · "))}</span></summary>`;
    [["Notes from the model", fromModel]].concat(byAuthor.map(([words, notes]) =>
      ["Notes " + words, notes])).forEach(([label, notes]) => {
      if (!notes.length) return;
      html += `<p class="sub-label">${esc(label)}</p><ul class="setup-notes">` +
        notes.map((n) => `<li>${esc(noteLine(n))}</li>`).join("") + "</ul>";
    });
    if (detailNotes.length) {
      html += '<p class="sub-label">Build details <span class="meta">how the reply was read, for debugging</span></p>' +
        '<ul class="setup-notes">' +
        detailNotes.map((n) => `<li>${esc(n.text || "")}</li>`).join("") + "</ul>";
    }
    return html + log + "</details>";
  }

  function renderBuildOutput(plan, where) {
    const meta = plan.meta || {};
    const source = document.getElementById("plan-source");
    if (source) source.innerHTML = sourceLine(plan, where);
    const verify = document.getElementById("plan-verify-line");
    if (verify) verify.innerHTML = verifyLine(meta);
    const body = document.getElementById("plan-output");
    if (!body) return;
    let html = factsLine(plan);
    if (plan.unassigned_inputs && plan.unassigned_inputs.length) {
      html += `<p class="body-line meta">Left unassigned: ${esc(plan.unassigned_inputs.map(unassignedLine).join(", "))}</p>`;
    }
    body.innerHTML = html + detailsFold(plan);
  }

  // ---- What this rebuild changed ----------------------------
  // `meta.changes_since_previous` (atoo/plan_diff.py, kept by `build`):
  // one entry per strip that differs from the plan this one replaced,
  // graded INFO (something it is made from changed) or WARNING (nothing
  // did: the model rewrote it). Listed worst first, each a jump to its
  // row; the rows themselves carry an ADDED / CHANGED / MOVED chip, amber
  // when nobody asked for it (one meaning per colour: yellow is "check").

  const CHANGE_KIND = { channels: "channel", busses: "bus", outputs: "output" };
  let changeMarks = {};      // row id -> the strip's change
  let changesShownFor = null;  // the plan the fold's open state was set for

  function changesOf(plan) {
    const c = plan && plan.meta && plan.meta.changes_since_previous;
    return c && typeof c === "object" && Array.isArray(c.strips) ? c : null;
  }

  // The row a change is about: a channel by its slot (bank and number),
  // anything else by the longest name in its collection its label ends
  // with ("BUS 3 Keys Wedge" -> "Keys Wedge"). A removed strip has none.
  function changeRowId(plan, strip) {
    const kind = CHANGE_KIND[strip.collection];
    if (!kind || strip.kind === "removed") return null;
    const label = String(strip.label || "");
    if (kind === "channel" && Array.isArray(strip.slot)) {
      const hit = (plan.channels || []).find((c) => c && (c.bank || "ch") === strip.slot[0]
        && c.channel === strip.slot[1]);
      if (hit) return cardId(kind, hit.name);
    }
    const names = kind === "channel"
      ? (plan.channels || []).map((c) => c && c.name).filter(Boolean)
      : Object.keys(plan[strip.collection] || {});
    let best = null;
    names.forEach((name) => {
      if ((label === name || label.endsWith(" " + name)) && (!best || name.length > best.length)) best = name;
    });
    return best == null ? null : cardId(kind, best);
  }

  function changeMarksFor(plan) {
    const marks = {};
    const changes = changesOf(plan);
    if (!changes) return marks;
    changes.strips.forEach((strip) => {
      const id = changeRowId(plan, strip);
      if (id && !marks[id]) marks[id] = strip;
    });
    return marks;
  }

  function changeChip(id) {
    const strip = changeMarks[id];
    if (!strip) return "";
    const unasked = strip.severity === "WARNING";
    const kind = String(strip.kind || "changed");
    // A state tag: yellow when nobody asked
    // for it, neutral when the edit did.
    return `<span class="state chg-state${unasked ? " is-warn" : ""}" title="${esc(
      (unasked ? "Not asked for: " : "Since the last build: ") + (strip.summary || kind) +
      (strip.reason ? " -- " + strip.reason : ""))}">${esc(kind.charAt(0).toUpperCase() + kind.slice(1))}</span>`;
  }

  function changeRowClass(id) {
    const strip = changeMarks[id];
    if (!strip) return "";
    return " row-changed" + (strip.severity === "WARNING" ? " row-unasked" : "");
  }

  const arrows = (text) => String(text || "").replace(/ -> /g, " → ");

  function renderChanges(plan) {
    const box = document.getElementById("sec-changes");
    if (!box) return;
    const changes = changesOf(plan);
    box.hidden = !changes;
    if (!changes) { box.innerHTML = ""; return; }
    const counts = changes.counts || {};
    const strips = changes.strips;
    const unasked = Number(counts.unasked) || 0;
    const parts = ["added", "removed", "changed", "moved"]
      .filter((k) => counts[k]).map((k) => `${counts[k]} ${k}`);
    const aside = strips.length
      ? `${strips.length} strip${strips.length === 1 ? "" : "s"}: ${parts.join(", ")}`
      : "nothing changed";
    let html = '<summary class="section-head"><h3>Changed since the last build</h3>' +
      (unasked ? `<span class="sev sev-warning">${unasked} not asked for</span>` : "") +
      `<span class="push meta">${esc(aside)}</span></summary>`;
    if (!strips.length) {
      html += `<p class="body-line meta">Every strip matches <code>${esc(changes.against || "plan.previous.json")}</code>.</p>`;
    } else {
      html += '<ul class="chg-list">';
      strips.forEach((strip) => {
        const unaskedOne = strip.severity === "WARNING";
        const id = changeRowId(plan, strip);
        const name = id
          ? `<a href="#${esc(id)}" class="chg-link" data-row="${esc(id)}">${esc(strip.label)}</a>`
          : `<b>${esc(strip.label)}</b>`;
        html += "<li>" +
          `<span class="sev ${unaskedOne ? "sev-warning" : "sev-info"}">${unaskedOne ? "Warning" : "Info"}</span>` +
          `<span>${name}: ${esc(arrows(strip.summary || strip.kind))}` +
          (unaskedOne
            ? `<br><span class="meta">Nothing in the input list or the conventions about it changed -- ` +
              "the model rewrote it. The plan may still be right; check it.</span>"
            : (strip.reason ? ` <span class="meta">-- ${esc(strip.reason)}</span>` : "")) +
          "</span></li>";
      });
      html += "</ul>";
    }
    (changes.notes || []).forEach((note) => {
      html += `<p class="chg-basis">${esc(note.charAt(0).toUpperCase() + note.slice(1))}.</p>`;
    });
    // Open when something was not asked for; folded otherwise. Set once
    // per plan, so a redraw (an edit in step 02) keeps the viewer's fold.
    const key = (plan.meta && plan.meta.generated_at) || "";
    const keepOpen = changesShownFor === key ? box.open : unasked > 0;
    box.innerHTML = html;
    box.open = keepOpen;
    changesShownFor = key;
    box.querySelectorAll(".chg-link").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        if (SP_ && SP_.jumpTo) SP_.jumpTo({ mode: "build", target: "#" + a.dataset.row });
      });
    });
  }

  // ---- the tables, as blocks -------------------------------------------

  function blockHead(title, note, extra) {
    return `<div class="block-head"><h2>${esc(title)}</h2>` +
      (note ? `<span class="notation">${esc(note)}</span>` : "") + (extra || "") + "</div>";
  }

  function renderPlan(container, plan, display, busDisplay, outputDisplay) {
    // Step 04's input toolbar (shell.html, wired by shell.js) is parked
    // outside the container before it is redrawn and moved back into the
    // Channels block after, so its buttons and Save note survive.
    const toolbar = document.getElementById("plan-input-toolbar");
    const park = document.getElementById("plan-view");
    if (toolbar && park) park.appendChild(toolbar);
    changeMarks = changeMarksFor(plan);
    renderBuildOutput(plan, current);
    renderChanges(plan);
    renderApplyDifference();

    // Counted as Build output's line counts them: channels and aux apart,
    // stereo among the channels.
    const channels = plan.channels || [];
    const objs = channels.filter((c) => c && typeof c === "object");
    const aux = objs.filter((c) => c.bank === "aux").length;
    const strips = objs.length - aux;
    const stereo = objs.filter((c) => c.bank !== "aux" && isStereo(c)).length;
    const changedRows = Object.keys(changeMarks).filter((id) => id.indexOf("plan-channel-") === 0).length;
    const chNote = [`${strips} channel${strips === 1 ? "" : "s"}`]
      .concat(stereo ? [`${stereo} stereo`] : [])
      .concat(aux ? [`${aux} aux`] : [])
      .concat(changedRows ? [`${changedRows} changed since the last build`] : []).join(" · ");
    // The table's how-to-read-it note is pop-up help, the
    // same `.help-pop` as every other block of instructions on Build;
    // shell.js's delegated handler opens it.
    const help = '<span class="help-pop"><button type="button" class="help-btn" ' +
      'aria-label="Help: reading the channel table" aria-expanded="false" ' +
      'aria-controls="help-plan-table">?</button>' +
      '<span class="help-popover" id="help-plan-table" role="note" hidden>' +
      "Ch is the channel the plan puts the input on, in the color it sets. The other columns are " +
      "the input list's own, every one editable: a blank cell's gray text is what the plan has there. " +
      "ST marks a stereo channel, on the first of its two input rows. ADDED, CHANGED or MOVED marks a " +
      "strip this build changed against the plan it replaced. The Findings column counts each row's " +
      "findings in the Findings panel; click a badge to find them there. Expand a row for its model, " +
      "preset and notes, and the plan's HPF / color / sends / where the name is actually written / " +
      "provenance.</span></span>";
    let html = blockHead("Channels", chNote, help) +
      '<section class="panel box plan-table-section" id="plan-channels-block">' +
      '<div id="plan-input-toolbar-slot"></div>' +
      channelTable(plan, display || []) + "</section>";

    // Busses and Mains and Matrix: the bus sheet. Editable where the Channels are --
    // the open show's own plan.json -- and Save sits on the first of the
    // two blocks; both write busses.csv.
    busSheet.editable = planIsBundlesHere();
    const busses = plan.busses || {};
    const busNames = Object.keys(busses);
    const sheetBusRows = busSheet.rows.filter((r) => busKindOf(r.label) === "bus").length;
    const outputs = plan.outputs || {};
    const outputNames = Object.keys(outputs);
    const sheetOutputRows = busSheet.rows.filter((r) => busKindOf(r.label) === "output").length;
    const sheetFile = busSheet.editable ? " · busses.csv" : "";
    let controlsShown = false;
    if (busNames.length || sheetBusRows) {
      const mono = busNames.filter((n) => busses[n] && busses[n].mono === true).length;
      const st = busNames.filter((n) => busses[n] && busses[n].mono === false).length;
      const note = [String(Math.max(busNames.length, sheetBusRows))].concat(mono ? [`${mono} mono`] : [])
        .concat(st ? [`${st} stereo`] : []).join(" · ") + sheetFile;
      html += blockHead("Busses", note, `<span class="block-head-spacer"></span>${busControls()}`) +
        '<section class="panel box plan-table-section" id="plan-busses-block">' + busNoteBox() +
        busTable(busses, busDisplay || {}) + "</section>";
      controlsShown = true;
    }
    if (outputNames.length || sheetOutputRows) {
      const kinds = {};
      outputNames.forEach((n) => {
        const k = (outputs[n] && outputs[n].kind) || "other";
        kinds[k] = (kinds[k] || 0) + 1;
      });
      const note = [String(outputNames.length)]
        .concat(Object.keys(kinds).map((k) => `${kinds[k]} ${k}`)).join(" · ") + sheetFile;
      html += blockHead("Mains and Matrix", note,
        controlsShown ? "" : `<span class="block-head-spacer"></span>${busControls()}`) +
        '<section class="panel box plan-table-section" id="plan-outputs-block">' +
        (controlsShown ? `<div class="sheet-note">${esc(busSheet.editable ? BUS_NOTE
          : "Read-only: " + busReadOnlyWhy())}</div>` : busNoteBox()) +
        outputTable(outputs, outputDisplay || {}) + "</section>";
    }
    // Outputs: outputs.csv. Every patched output socket; a show
    // with no outputs.csv shows the plan's, and a Save writes the file.
    outSheet.editable = planIsBundlesHere();
    if (outSheet.rows.length || outSheet.editable) {
      const n = outSheet.rows.length;
      const lines = outRuns().length;
      html += blockHead("Outputs",
        `${n} socket${n === 1 ? "" : "s"} · ${lines} line${lines === 1 ? "" : "s"}` +
        `${outSheet.editable ? " · outputs.csv" : ""}`,
        `<span class="block-head-spacer"></span>${outControls()}`) +
        '<section class="panel box plan-table-section" id="plan-sockets-block">' + outNoteBox() +
        (n ? outputsTable() : '<div class="sheet-note setup-dim">No output socket is patched. Add a ' +
          "socket to send a split, a recording feed or a bus to one.</div>") + "</section>";
    }
    // User signals and patches: user.csv. Shown once the show
    // has a slot in use, or can have one added here.
    userSheet.editable = planIsBundlesHere();
    if (userSheet.rows.length || userSheet.editable) {
      const n = userSheet.rows.length;
      html += blockHead("User signals and patches",
        `${n} slot${n === 1 ? "" : "s"}${userSheet.editable ? " · user.csv" : ""}`,
        `<span class="block-head-spacer"></span>${userControls()}`) +
        '<section class="panel box plan-table-section" id="plan-user-block">' + userNoteBox() +
        (n ? userTable(plan) : '<div class="sheet-note setup-dim">No USR slot in use. Add a slot to ' +
          "define a processed feed or a user patch.</div>") + "</section>";
    }
    container.innerHTML = html;
    const slot = document.getElementById("plan-input-toolbar-slot");
    if (toolbar && slot) slot.appendChild(toolbar);
    restoreOpenRows();
    paintFindingBadges();
    paintFindingsSummary();
  }

  // ======================================================================
  // Build step 04: the controller. Everything below needs the shell.
  // ======================================================================

  const SP = window.Atoo;
  if (!SP) return;

  const startup = (() => {
    const tag = el("initial-shell");
    if (!tag) return {};
    try { return JSON.parse(tag.textContent) || {}; } catch (e) { return {}; }
  })();
  // Plan-note sources that are build details
  // (`finding_groups.DETAIL_NOTE_SOURCES`, in the startup data).
  const DETAIL_NOTE_SOURCES = new Set(startup.detail_note_sources || []);
  function isDetailNote(note) {
    return !!note && typeof note === "object" && DETAIL_NOTE_SOURCES.has(note.source);
  }

  let current = startup.plan || null;  // {path, plan, findings}
  // True from the moment a build starts until it ends: the plan on screen
  // is the one being replaced, so its findings stay off the dock even when
  // it is redrawn meanwhile (see `clearFindingsForBuild`).
  let holdPlanFindings = false;
  let run = startup.run || { state: "idle" };
  let pollTimer = null;
  // Stop was pressed and the request is in flight (see stopBuild).
  let stopping = false;

  const modelSelect = el("run-console-model");
  const modelNote = el("run-model-note");
  const critic = el("run-critic");
  const runBtn = el("run-build-btn");
  const runMessage = el("run-message");
  const runPanel = el("run-panel");
  const stopBtn = el("run-stop-btn");
  const planPathInput = el("plan-path");

  function showRunMessage(text) {
    runMessage.textContent = text || "";
    runMessage.hidden = !text;
  }

  // ---- the console model -------------------------------------------------
  // `build` refuses an unstated model, and so does this page
  // -- a Full's 8 local inputs and a Compact's 24 are the difference
  // between a patch that lands and one that cannot. What it WILL do is
  // start from the model the plan on screen was built for, and say so:
  // an inferred value that announces itself is one the engineer can see.
  (startup.console_models || []).forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label + " (" + model.id + ")";
    modelSelect.appendChild(option);
    consoleNames[model.id] = model.label;
  });

  // ---- Options folds -----------------------------
  // First in the Plan block, and collapsible. Its summary names what is
  // chosen, so a closed fold still says which WING and whether the critic
  // runs. Open by default; the viewer's choice is kept (a private window
  // throws, and then it is simply open). A build opens it, since its
  // progress is drawn there.
  const OPTIONS_OPEN_KEY = "atoo.build.optionsOpen";
  const optionsFold = el("sec-options");
  if (optionsFold) {
    try {
      if (localStorage.getItem(OPTIONS_OPEN_KEY) === "0") optionsFold.open = false;
    } catch (e) { /* not kept */ }
    optionsFold.addEventListener("toggle", () => {
      try { localStorage.setItem(OPTIONS_OPEN_KEY, optionsFold.open ? "1" : "0"); } catch (e) { /* not kept */ }
    });
  }
  function openOptions() {
    if (optionsFold) optionsFold.open = true;
  }
  function renderOptionsAside() {
    const aside = el("options-aside");
    if (!aside) return;
    const model = modelSelect.value;
    aside.textContent = (model ? (consoleNames[model] || model) : "no console model chosen")
      + " · critic " + (critic.checked ? "on" : "off");
  }

  function seedConsoleModel() {
    const stated = current && current.plan && current.plan.meta && current.plan.meta.console_model;
    if (stated && !modelSelect.value && modelSelect.querySelector('option[value="' + stated + '"]')) {
      modelSelect.value = stated;
      modelNote.textContent = "Chosen from the plan on screen (meta.console_model) -- "
        + "change it if this desk is a different WING.";
      modelNote.hidden = false;
    }
  }
  modelSelect.addEventListener("change", () => { modelNote.hidden = true; });

  function commandPreview() {
    const bundle = SP.bundle();
    const parts = ["atoo build --show", bundle ? bundle.name + "/" : "<bundle>"];
    parts.push("--console-model", modelSelect.value || "<model>");
    if (critic.checked) parts.push("--critic");
    el("run-command").textContent = parts.join(" ");
    renderOptionsAside();
  }
  modelSelect.addEventListener("change", commandPreview);
  critic.addEventListener("change", commandPreview);

  // ---- the plan tile and the plan ----------------------------------------

  // A build is a model call: with none set up, Build plan and both Rebuilds
  // are locked, saying why -- a build that cannot run must not be pressed
  // (`build_model`, from the Build payload).
  function buildModelWhy() {
    const sources = SP.buildSources ? SP.buildSources() : null;
    const model = sources && sources.build_model;
    if (!model || model.ready !== false) return "";
    return "a build needs a model, and none is set up here (" +
      (model.why || "no model configured") + ")";
  }

  function renderPlanTile() {
    const badge = el("badge-plan");
    const hint = el("hint-plan");
    const bundle = SP.bundle();
    const states = {
      running: ["Building…", "is-live"],
      failed: ["Failed", "is-err"],
    };
    let label = current ? ["Loaded", "is-ok"] : ["Not built", ""];
    if (states[run.state]) label = states[run.state];
    else if (planIsStale()) label = ["Stale", "is-warn"];
    else if (run.state === "done" && current) label = ["Built", "is-ok"];
    badge.textContent = label[0];
    badge.className = "state" + (label[1] ? " " + label[1] : "");
    badge.title = planIsStale() ? staleReasons().join(" ") : "";
    hint.textContent = bundle ? bundle.name + "/plan.json" : "no show bundle open";
    hint.title = (current && current.path) || "";
    const noModel = buildModelWhy();
    runBtn.disabled = run.state === "running" || !bundle || !!bundle.demo || SP.isStale()
      || !!noModel;
    // A locked control says why, in words.
    const lock = el("run-build-lock");
    if (lock) {
      const why = run.state === "running" ? "a build is running"
        : !bundle ? "open or create a show first"
        : bundle.demo ? "the Demo show is read-only"
        : SP.isStale() ? "this page is out of date; reload it"
        : noModel ? noModel : "";
      lock.textContent = why;
      lock.hidden = !why;
    }
    renderFreshness();
  }

  // ---- the plan is older than its inputs -------------------
  // `plan_freshness` rides in the Build payload (shell.js re-reads it on
  // every Save, on a file changed in another program, and after a build):
  // for the bundle's plan.json, by content -- the sha256s the plan
  // recorded against the files as they are now. "stale" names each file
  // that changed and offers Rebuild; "unknown" is a plan too old to have
  // recorded one, and says so without calling it stale.

  function freshness() {
    const f = SP.planFreshness ? SP.planFreshness() : null;
    // Only about the bundle's own plan.json: a plan opened from somewhere
    // else by path is not what these three files built.
    if (!f || !current || !f.plan_path || f.plan_path !== current.path) return null;
    return f;
  }

  // Is the plan on screen the one this bundle's input list built? Only
  // then are step 04's Input cells that list's rows, and editable.
  function planIsBundles() {
    return !!freshness();
  }

  function planIsStale() {
    const f = freshness();
    return !!(f && f.state === "stale");
  }

  function staleReasons() {
    const f = freshness();
    return ((f && f.reasons) || []).map((reason) => reason.message);
  }

  function renderFreshness() {
    const f = freshness();
    const box = el("plan-stale-reason");
    const list = el("plan-stale-list");
    const title = el("plan-stale-title");
    const rebuild = el("plan-rebuild-btn");
    const running = run.state === "running";
    const stalePlan = !!(f && f.state === "stale");
    const unknown = !!(f && f.state === "unknown");
    if (box && list && title) {
      box.hidden = !(stalePlan || unknown) || running;
      box.classList.toggle("is-unknown", unknown);
      title.textContent = stalePlan
        ? "This plan is stale -- its inputs changed after it was built."
        : "Can't tell whether this plan is current.";
      list.textContent = "";
      (stalePlan ? f.reasons : (f ? f.unknown : [])).forEach((reason) => {
        const li = document.createElement("li");
        li.textContent = reason.message;
        list.appendChild(li);
      });
    }
    // Build output's state, on the right of its heading:
    // one state tag -- green Plan current, yellow Stale, grey Can't tell
    // or Building. A plan opened from outside the bundle has none.
    const tag = el("plan-state-tag");
    if (tag) {
      const state = running ? ["Building", "is-live"]
        : stalePlan ? ["Stale", "is-warn"]
        : unknown ? ["Can't tell", ""]
        : (f && f.state === "current") ? ["Plan current", "is-ok"] : null;
      tag.hidden = !state || !current;
      if (state) {
        tag.textContent = state[0];
        tag.className = "state" + (state[1] ? " " + state[1] : "");
      }
    }
    if (rebuild) {
      rebuild.textContent = stalePlan ? "Rebuild plan" : "Rebuild to record it";
      rebuild.disabled = running || !SP.bundle() || SP.isStale() || !!buildModelWhy();
      rebuild.title = buildModelWhy();
    }
    // The status line's plan badge beside a Rebuild button, on the tile.
    // It says only what the tile's own badge does not: a stale plan or a build under way is already the tile's
    // **Stale** or **Building…**, and one word said twice on one tile
    // read as two different states (the old status-line wording).
    const badge = el("status-plan-badge");
    const sep = el("status-plan-sep");
    const statusRebuild = el("status-rebuild-btn");
    if (badge && sep) {
      const shown = !running && !!(current && f) && f.state !== "stale";
      badge.hidden = sep.hidden = !shown;
      if (shown) {
        const words = { unknown: ["Plan: can't tell", ""],
                        current: ["Plan current", "is-ok"] }[f.state] || ["Plan", ""];
        badge.textContent = words[0];
        badge.className = "state" + (words[1] ? " " + words[1] : "");
        badge.title = "";
      }
    }
    if (statusRebuild) {
      statusRebuild.hidden = !stalePlan || running;
      statusRebuild.disabled = !SP.bundle() || SP.isStale() || !!buildModelWhy();
      statusRebuild.title = buildModelWhy();
    }
    renderApplyDifference();
  }

  // ---- Apply the difference ----------------------------------------------
  // After a rebuild that changed something, a line in Build output with the
  // shortcut to Apply: Full build chosen and the preview already run, so the
  // next thing read is how many addresses will change. A Full build writes
  // only the addresses where the desk differs from the plan, so this is not
  // a second way to write; it is the first step of the same one. Shown only
  // for the bundle's own plan while it is current: a stale plan is rebuilt
  // first, and a plan opened from somewhere else is not what Apply writes.
  function renderApplyDifference() {
    const box = el("plan-apply-diff");
    if (!box) return;
    const f = freshness();
    const changes = changesOf(current && current.plan);
    const n = changes ? changes.strips.length : 0;
    const show = !!(n && f && f.state === "current" && run.state !== "running" && SP.bundle());
    box.hidden = !show;
    if (!show) return;
    el("plan-apply-diff-text").textContent = n + (n === 1 ? " strip differs" : " strips differ") +
      " from the last build. A full build writes only what differs; this opens Apply with the preview run.";
    el("plan-apply-diff-btn").disabled = SP.isStale();
  }

  el("plan-apply-diff-btn").addEventListener("click", () => {
    if (SP.applyTheDifference) SP.applyTheDifference();
  });

  // Rebuild is Build plan, from wherever the Stale badge is: the same
  // `POST /api/build/run`, with the model and critic choice step 04 holds.
  function rebuild() {
    SP.activateMode("build");
    if (SP.activateStep) SP.activateStep("plan");
    buildAsking();
  }

  // A captured show's plan was read from the desk, and a
  // build replaces it: Build plan asks first, with Cancel focused. A built
  // plan builds at once, as before.
  const capturedBuild = el("captured-build-dialog");
  function isCapturedPlan() {
    const meta = (current && current.plan && current.plan.meta) || {};
    return meta.made_from === "desk" || meta.made_from === "snap";
  }
  function buildAsking() {
    if (!isCapturedPlan() || !capturedBuild || typeof capturedBuild.showModal !== "function") {
      startBuild();
      return;
    }
    capturedBuild.showModal();
    el("captured-build-cancel").focus();
  }
  if (capturedBuild) {
    el("captured-build-cancel").addEventListener("click", () => capturedBuild.close());
    el("captured-build-continue").addEventListener("click", () => {
      capturedBuild.close();
      startBuild();
    });
  }

  // Step 04's Input cells are step 02's editor (`SP.inputEditor`): the
  // same rows, the same unsaved state, the same Save to input.csv -- and
  // after it, the same Stale badge. Where there is no such list to edit
  // (a plan opened from elsewhere, or no bundle), they are the plan's own
  // record of its inputs, read-only, and say so.
  function renderInputToolbar() {
    const table = el("plan-channels-table");
    const editable = !!(table && table.dataset.editable === "1");
    const mode = el("plan-input-mode");
    if (mode) {
      // The maintainer's words (mockup revision 3).
      mode.textContent = editable
        ? "Save writes the input.csv file and updates the build plan."
        : (SP.bundle() && SP.bundle().demo
          ? "Read-only: the demo show cannot be edited -- the inputs are shown as the "
            + "plan recorded them."
          : current && current.path && !planIsBundles() && SP.bundle()
          ? "Read-only: this plan is not the open bundle's plan.json, so its inputs are "
            + "shown as the plan recorded them."
          : "Read-only: there is no input list to edit -- the inputs are shown as the "
            + "plan recorded them.");
    }
    const link = el("plan-input-edit-link");
    if (link) link.hidden = editable || !SP.bundle() || !!(SP.bundle() && SP.bundle().demo);
    const dirty = editable && SP.inputEditor && SP.inputEditor.dirty();
    // Hidden until there is something to save as the bus
    // sheet's Save is, and only where these cells are the editable list.
    ["plan-input-save-btn", "plan-input-discard-btn"].forEach((id) => {
      const node = el(id);
      if (node) node.hidden = !editable || !dirty;
    });
    const badge = el("plan-input-dirty-badge");
    if (badge) badge.hidden = !dirty;
    const save = el("plan-input-save-btn");
    if (save) {
      save.disabled = !dirty || SP.isStale() || inputRefusals.length > 0;
      save.title = inputRefusals.length
        ? `Save is locked: ${inputRefusals.length} cell(s) cannot work on the desk -- see the list above the table.`
        : "Save input.csv";
    }
    paintInputRefusals();
    const discard = el("plan-input-discard-btn");
    if (discard) discard.disabled = !dirty;
  }

  // ---- what a Save would refuse, before it is pressed ----------------------
  // `POST /api/build/sheets/check` lays the unsaved sheet onto the plan and
  // says what cannot work on the desk, with nothing written. A refused cell
  // is red, its reason under its row, and Save is locked with the reason.

  let inputRefusals = [];
  let inputCheckTimer = null;
  let busCheckTimer = null;

  async function checkSheet(sheet, rows) {
    try {
      const r = await fetch("/api/build/sheets/check", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sheet: sheet, rows: rows,
                               expected_bundle: SP.bundle() ? SP.bundle().directory : null }),
      });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  function scheduleInputCheck() {
    clearTimeout(inputCheckTimer);
    if (!SP.inputEditor || !SP.inputEditor.collect || !planIsBundlesHere()) return;
    if (!SP.inputEditor.dirty()) {
      inputRefusals = [];
      renderInputToolbar();
      return;
    }
    inputCheckTimer = setTimeout(async () => {
      const data = await checkSheet("input_list", SP.inputEditor.collect());
      if (!data) return;
      inputRefusals = data.refusals || [];
      renderInputToolbar();
    }, 400);
  }

  function paintInputRefusals() {
    const slot = el("plan-input-refusals");
    if (slot) {
      slot.hidden = !inputRefusals.length;
      slot.innerHTML = inputRefusals.length
        ? "<strong>Save is locked:</strong> " + inputRefusals.map((r) => `<div>${esc(r.text)}</div>`).join("")
        : "";
    }
    document.querySelectorAll("#plan-channels-table tr.row-refused").forEach((tr) => tr.classList.remove("row-refused"));
    document.querySelectorAll("#plan-channels-table .is-refused").forEach((n) => n.classList.remove("is-refused"));
    inputRefusals.forEach((r) => {
      // "row 7 (Kick 2)" or "CH 4 (Acoustic L)": the input's name.
      const m = /\(([^)]*)\)\s*$/.exec(r.row || "");
      const name = m ? m[1] : r.row;
      document.querySelectorAll("#plan-channels-table tr.row-primary").forEach((tr) => {
        const box = tr.querySelector('[data-input-col="name"]');
        if (!box || box.value !== name) return;
        tr.classList.add("row-refused");
        const cell = r.column && tr.querySelector(`[data-input-col="${r.column}"]`);
        if (cell) cell.classList.add("is-refused");
      });
    });
  }

  function scheduleBusCheck() {
    clearTimeout(busCheckTimer);
    busCheckTimer = setTimeout(async () => {
      const data = await checkSheet("bus_sheet", busSaveRows());
      if (!data) return;
      busSheet.refusals = (data.refusals || []).filter((r) => r.sheet === "busses.csv");
      redrawTables();
    }, 400);
  }

  // ---- the bus sheet's editor ----------------------------------------------

  async function loadBusSheet() {
    if (!SP.bundle()) {
      loadBusSheetPayload({ bus_sheet: null, derived: [] });
      busSheet.loaded = false;
      return;
    }
    try {
      const r = await fetch("/api/build/bus-sheet");
      if (r.ok) loadBusSheetPayload(await r.json());
    } catch (e) {
      /* the tables draw from the plan alone until it answers */
    }
  }

  // One cell edited: kept in the editor (a redraw keeps it), marked, and
  // checked. The table is not redrawn under the cursor.
  function editBusCell(input) {
    const row = busRow(input.dataset.busRow);
    if (!row) return;
    row.values[input.dataset.busCol] = input.value;
    busSheet.dirty = busSheet.rows.some((r) => Object.keys(Object.assign({}, r.values, r.original))
      .some((c) => (r.values[c] || "") !== (r.original[c] || "")));
    busSheet.note = "";
    input.classList.toggle("is-edited", busCellEdited(row, input.dataset.busCol));
    paintBusControls();
    scheduleBusCheck();
  }

  function paintBusControls() {
    document.querySelectorAll(".bus-dirty-badge").forEach((n) => { n.hidden = !busSheet.dirty; });
    document.querySelectorAll("[data-bus-discard]").forEach((n) => { n.hidden = !busSheet.dirty; });
    document.querySelectorAll("[data-bus-save]").forEach((n) => {
      n.hidden = !(busSheet.dirty || busSheet.behind);
      n.disabled = busSheet.refusals.length > 0 || SP.isStale();
    });
  }

  // The sheet as Save sends it: every row the file has, in its order, whole;
  // then a row for each plan object the file has no row for, when a cell of
  // it was filled in.
  function busSaveRows() {
    const kept = busSheet.rows.filter((r) => r.line != null).sort((a, b) => a.line - b.line)
      .map((r) => ({ line: r.line, values: Object.assign({}, r.values) }));
    const added = busSheet.rows.filter((r) => r.line == null && Object.keys(r.values)
      .some((c) => c !== "bus" && String(r.values[c] || "").trim()))
      .map((r) => ({ line: null, values: Object.assign({}, r.values, { bus: r.label }) }));
    return kept.concat(added);
  }

  async function saveBusSheet() {
    if (!(busSheet.dirty || busSheet.behind) || busSheet.refusals.length) return;
    if (!(await SP.checkServer())) {
      busSheet.note = "Nothing was saved: this page is out of date -- see the banner.";
      busSheet.noteKind = "error";
      redrawTables();
      return;
    }
    let data;
    let ok = false;
    try {
      const r = await fetch("/api/build/bus-sheet/save", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_sha256: (busSheet.source && busSheet.source.sha256) || "",
          expected_bundle: SP.bundle() ? SP.bundle().directory : null,
          rows: busSaveRows(),
        }),
      });
      data = await r.json();
      ok = r.ok;
    } catch (e) {
      data = { error: String(e) };
    }
    if (!ok) {
      if (data.stale === "bundle") SP.markStale(data.error);
      busSheet.refusals = (data.refusals || []).filter((r) => r.sheet === "busses.csv");
      busSheet.note = data.error || "couldn't save";
      busSheet.noteKind = "error";
      redrawTables();
      return;
    }
    loadBusSheetPayload(data);
    busSheet.note = data.message || "Saved.";
    busSheet.noteKind = "ok";
    if (SP.refreshBuild) SP.refreshBuild();
    // plan.json changed: step 04 draws it again, and Apply re-reads its
    // pre-flight (the same as after a build).
    if (SP.planBuilt) SP.planBuilt();
    else await fetchPlan();
  }

  function discardBusSheet() {
    busSheet.rows.forEach((r) => { r.values = Object.assign({}, r.original); });
    busSheet.dirty = false;
    busSheet.refusals = [];
    busSheet.note = "";
    redrawTables();
  }

  // ---- outputs.csv's editor ------------------------------------------------

  async function loadOutputsSheet() {
    if (!SP.bundle()) {
      loadOutputsSheetPayload({ outputs_sheet: null, derived: [] });
      outSheet.loaded = false;
      return;
    }
    try {
      const r = await fetch("/api/build/outputs-sheet");
      if (r.ok) loadOutputsSheetPayload(await r.json());
    } catch (e) {
      /* the table waits for it */
    }
  }

  function outDirty() {
    if (outSheet.rows.length !== outSheet.original.length) return true;
    return outSheet.rows.some((r, i) => OUT_COLS.some((c) => outRowEdited(i, c)));
  }

  function paintOutControls() {
    const unsaved = outSheet.dirty || outSheet.behind || !(outSheet.source && outSheet.source.present);
    document.querySelectorAll(".out-dirty-badge").forEach((n) => { n.hidden = !outSheet.dirty; });
    document.querySelectorAll("[data-out-discard]").forEach((n) => { n.hidden = !outSheet.dirty; });
    document.querySelectorAll("[data-out-save]").forEach((n) => {
      n.hidden = !unsaved;
      n.disabled = outSheet.refusals.length > 0 || SP.isStale();
    });
  }

  let outCheckTimer = null;
  function scheduleOutCheck() {
    clearTimeout(outCheckTimer);
    outCheckTimer = setTimeout(async () => {
      try {
        const r = await fetch("/api/build/outputs-sheet/check", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rows: outSheet.rows }),
        });
        if (!r.ok) return;
        outSheet.refusals = (await r.json()).refusals || [];
      } catch (e) {
        return;
      }
      redrawTables();
    }, 400);
  }

  function editOutCell(input) {
    const i = Number(input.dataset.outRow);
    const row = outSheet.rows[i];
    if (!row) return;
    row[input.dataset.outCol] = input.value;
    outSheet.dirty = outDirty();
    outSheet.note = "";
    input.classList.toggle("is-edited", outRowEdited(i, input.dataset.outCol));
    paintOutControls();
    scheduleOutCheck();
  }

  function toggleOutRun(key) {
    outSheet.open[key] = !outSheet.open[key];
    redrawTables();
  }

  // A new row at the end, ready for its socket.
  function addOutSocket() {
    outSheet.rows.push({ output: "", source: "", notes: "" });
    outSheet.original.push({});
    outSheet.dirty = true;
    redrawTables();
    const box = el("plan-render") && el("plan-render").querySelector(
      `[data-out-row="${outSheet.rows.length - 1}"][data-out-col="output"]`);
    if (box) box.focus();
  }

  async function saveOutputsSheet() {
    if (outSheet.refusals.length) return;
    if (!(await SP.checkServer())) {
      outSheet.note = "Nothing was saved: this page is out of date -- see the banner.";
      outSheet.noteKind = "error";
      redrawTables();
      return;
    }
    let data;
    let ok = false;
    try {
      const r = await fetch("/api/build/outputs-sheet/save", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_sha256: (outSheet.source && outSheet.source.sha256) || "",
          expected_bundle: SP.bundle() ? SP.bundle().directory : null,
          rows: outSheet.rows,
        }),
      });
      data = await r.json();
      ok = r.ok;
    } catch (e) {
      data = { error: String(e) };
    }
    if (!ok) {
      if (data.stale === "bundle") SP.markStale(data.error);
      outSheet.refusals = data.refusals || [];
      outSheet.note = data.error || "couldn't save";
      outSheet.noteKind = "error";
      redrawTables();
      return;
    }
    loadOutputsSheetPayload(data);
    outSheet.note = data.message || "Saved.";
    outSheet.noteKind = "ok";
    // busses.csv's Outputs cells may have followed: read it again.
    if (!busSheet.dirty) await loadBusSheet();
    if (SP.refreshBuild) SP.refreshBuild();
    if (SP.planBuilt) SP.planBuilt();
    else await fetchPlan();
  }

  function discardOutputsSheet() {
    outSheet.rows = outSheet.original.filter((r) => Object.keys(r).length)
      .map((r) => Object.assign({}, r));
    outSheet.original = outSheet.rows.map((r) => Object.assign({}, r));
    outSheet.dirty = false;
    outSheet.refusals = [];
    outSheet.note = "";
    redrawTables();
  }

  // ---- user.csv's editor ---------------------------------------------------

  async function loadUserSheet() {
    if (!SP.bundle()) {
      loadUserSheetPayload({ user_sheet: null, derived: [] });
      userSheet.loaded = false;
      return;
    }
    try {
      const r = await fetch("/api/build/user-sheet");
      if (r.ok) loadUserSheetPayload(await r.json());
    } catch (e) {
      /* the table waits for it */
    }
  }

  function userDirty() {
    if (userSheet.rows.length !== userSheet.original.length) return true;
    return userSheet.rows.some((r, i) => USER_COLS.some((c) => userRowEdited(i, c)));
  }

  function paintUserControls() {
    document.querySelectorAll(".user-dirty-badge").forEach((n) => { n.hidden = !userSheet.dirty; });
    document.querySelectorAll("[data-user-discard]").forEach((n) => { n.hidden = !userSheet.dirty; });
    document.querySelectorAll("[data-user-save]").forEach((n) => {
      n.hidden = !(userSheet.dirty || userSheet.behind);
      n.disabled = userSheet.refusals.length > 0 || SP.isStale();
    });
  }

  let userCheckTimer = null;
  function scheduleUserCheck() {
    clearTimeout(userCheckTimer);
    userCheckTimer = setTimeout(async () => {
      try {
        const r = await fetch("/api/build/user-sheet/check", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rows: userSheet.rows }),
        });
        if (!r.ok) return;
        userSheet.refusals = (await r.json()).refusals || [];
      } catch (e) {
        return;
      }
      redrawTables();
    }, 400);
  }

  function editUserCell(input) {
    const row = userSheet.rows[Number(input.dataset.userRow)];
    if (!row) return;
    row[input.dataset.userCol] = input.value;
    // A slot moved between kinds takes that kind's cells: a user patch has
    // no tap or leg, a user signal starts at POST, both sides.
    if (input.dataset.userCol === "slot") {
      const kind = userKind(userSlotNumber(input.value));
      if (kind === "user patch" && (row.tap || row.leg)) {
        row.tap = ""; row.leg = "";
        setTimeout(redrawTables, 0);
      } else if (kind === "user signal" && !row.tap && !row.leg) {
        row.tap = "POST"; row.leg = "L+R";
        setTimeout(redrawTables, 0);
      }
    }
    userSheet.dirty = userDirty();
    userSheet.note = "";
    input.classList.toggle("is-edited", userRowEdited(Number(input.dataset.userRow), input.dataset.userCol));
    paintUserControls();
    scheduleUserCheck();
  }

  // A new row on the next user signal no row has (USR 1-24), ready for its
  // source; the slot can be changed to any other.
  function addUserSlot() {
    const used = new Set(userSheet.rows.map((r) => userSlotNumber(r.slot)));
    let n = 1;
    while (used.has(n) && n < 24) n += 1;
    if (used.has(n)) n = 25;
    while (used.has(n) && n < 56) n += 1;
    userSheet.rows.push({ slot: `USR ${n}`, source: "", tap: n <= 24 ? "POST" : "",
      leg: n <= 24 ? "L+R" : "", name: "" });
    userSheet.original.push({});
    userSheet.dirty = true;
    redrawTables();
    const box = el("plan-render") && el("plan-render").querySelector(
      `[data-user-row="${userSheet.rows.length - 1}"][data-user-col="source"]`);
    if (box) box.focus();
  }

  async function saveUserSheet() {
    if (!(userSheet.dirty || userSheet.behind) || userSheet.refusals.length) return;
    if (!(await SP.checkServer())) {
      userSheet.note = "Nothing was saved: this page is out of date -- see the banner.";
      userSheet.noteKind = "error";
      redrawTables();
      return;
    }
    let data;
    let ok = false;
    try {
      const r = await fetch("/api/build/user-sheet/save", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_sha256: (userSheet.source && userSheet.source.sha256) || "",
          expected_bundle: SP.bundle() ? SP.bundle().directory : null,
          rows: userSheet.rows,
        }),
      });
      data = await r.json();
      ok = r.ok;
    } catch (e) {
      data = { error: String(e) };
    }
    if (!ok) {
      if (data.stale === "bundle") SP.markStale(data.error);
      userSheet.refusals = data.refusals || [];
      userSheet.note = data.error || "couldn't save";
      userSheet.noteKind = "error";
      redrawTables();
      return;
    }
    loadUserSheetPayload(data);
    userSheet.note = data.message || "Saved.";
    userSheet.noteKind = "ok";
    if (SP.refreshBuild) SP.refreshBuild();
    if (SP.planBuilt) SP.planBuilt();
    else await fetchPlan();
  }

  function discardUserSheet() {
    userSheet.rows = userSheet.original.filter((r) => Object.keys(r).length)
      .map((r) => Object.assign({}, r));
    userSheet.original = userSheet.rows.map((r) => Object.assign({}, r));
    userSheet.dirty = false;
    userSheet.refusals = [];
    userSheet.note = "";
    redrawTables();
  }

  function redrawTables() {
    if (!current || !current.plan) return;
    // A redraw while a cell is being typed in (a check came back) puts the
    // cursor back where it was.
    const active = document.activeElement;
    const keep = active && active.dataset && (active.dataset.busCol || active.dataset.inputCol ||
      active.dataset.userCol || active.dataset.outCol)
      ? { bus: active.dataset.busRow, busCol: active.dataset.busCol, key: active.dataset.inputKey,
          col: active.dataset.inputCol, user: active.dataset.userRow, userCol: active.dataset.userCol,
          out: active.dataset.outRow, outCol: active.dataset.outCol,
          start: active.selectionStart, end: active.selectionEnd }
      : null;
    // The page stays where it was: replacing the tables under the reader
    // (a check came back, a Role was chosen) moved it about 40-100 px when the
    // browser re-anchored the scroll.
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    try {
      renderPlan(el("plan-render"), current.plan, current.channel_display,
        current.bus_display, current.output_display);
      renderInputToolbar();
    } catch (e) {
      console.error("Build step 04: failed to redraw the plan", e);
    }
    if (keep) {
      const selector = keep.outCol
        ? `[data-out-row="${CSS.escape(keep.out)}"][data-out-col="${CSS.escape(keep.outCol)}"]`
        : keep.userCol
        ? `[data-user-row="${CSS.escape(keep.user)}"][data-user-col="${CSS.escape(keep.userCol)}"]`
        : keep.busCol
          ? `[data-bus-row="${CSS.escape(keep.bus)}"][data-bus-col="${CSS.escape(keep.busCol)}"]`
          : `[data-input-key="${CSS.escape(keep.key || "")}"][data-input-col="${CSS.escape(keep.col)}"]`;
      const again = el("plan-render").querySelector(selector);
      if (again) {
        again.focus({ preventScroll: true });
        try { if (keep.start != null) again.setSelectionRange(keep.start, keep.end); } catch (e) { /* a select */ }
      }
    }
    if (window.scrollX !== scrollX || window.scrollY !== scrollY) window.scrollTo(scrollX, scrollY);
  }

  function renderCurrentPlan() {
    const view = el("plan-view");
    const empty = el("plan-empty");
    const output = el("sec-output");
    if (!current || !current.plan) {
      view.hidden = true;
      empty.hidden = false;
      if (output) output.hidden = true;
      const changes = el("sec-changes");
      if (changes) changes.hidden = true;
      if (!holdPlanFindings) publishPlanFindings([]);
      renderPlanTile();
      return;
    }
    try {
      renderPlan(el("plan-render"), current.plan, current.channel_display,
        current.bus_display, current.output_display);
      renderInputToolbar();
    } catch (e) {
      // A render failure must not be silent: an empty step looks exactly
      // like "no plan", which is what made the tag-ordering bug so
      // hard to notice.
      console.error("Build step 04: failed to render the plan", e);
      showRunMessage("Could not display this plan -- see the browser console.");
    }
    if (current.path) planPathInput.value = current.path;
    view.hidden = false;
    empty.hidden = true;
    if (output) output.hidden = false;
    seedConsoleModel();
    renderOptionsAside();
    if (!holdPlanFindings) publishPlanFindings(current.findings || []);
    renderPlanTile();
  }

  // ---- findings, and where each one came from ----------------------------
  // `jumps` is UI-only (see shell.js's dock): a Diagnostic has no idea
  // where on a screen its cause is shown, so the step that draws the
  // cause is the step that says.

  // The plan object a finding is about. Verify's `where` is structured
  // (`channels[Kick].patch`, `busses[Drums].processing`, `outputs[Main 1]`);
  // the critic's is the name as a person would write it ("Drums Comp",
  // "Main 1 / Matrix 1"), so that falls back to the longest plan name the
  // text contains -- longest first, or "Drums" would claim "Drums Comp".
  function planObjectFor(where) {
    const plan = current && current.plan;
    if (!plan || !where) return null;
    const channels = plan.channels || [];
    const kinds = { channels: "channel", busses: "bus", outputs: "output" };
    const m = /^(channels|busses|outputs)\[([^\]]+)\]/.exec(where);
    if (m) {
      let name = m[2];
      if (m[1] === "channels" && /^\d+$/.test(name)) {
        // `channels[10]` is channel NUMBER 10 where a preset finding says
        // it (`preset_expand`: "ch 10 ('Sample Pad')"); a structure
        // finding on a strip with no usable name gives its list index.
        // The number is tried first -- a list index read as a number
        // put every preset finding's jump one row down.
        const byNumber = channels.filter((c) => c && String(c.channel) === name)[0];
        const byIndex = channels[Number(name)];
        const found = byNumber || byIndex;
        if (found) name = found.name;
      }
      return { kind: kinds[m[1]], name: name };
    }
    const named = []
      .concat(channels.map((c) => ({ kind: "channel", name: c.name })))
      .concat(Object.keys(plan.busses || {}).map((n) => ({ kind: "bus", name: n })))
      .concat(Object.keys(plan.outputs || {}).map((n) => ({ kind: "output", name: n })))
      .filter((o) => o.name)
      .sort((a, b) => String(b.name).length - String(a.name).length);
    const text = String(where).toLowerCase();
    return named.filter((o) => text === String(o.name).toLowerCase())[0]
      || named.filter((o) => text.indexOf(String(o.name).toLowerCase()) !== -1)[0]
      || null;
  }

  // A finding about the conventions TEXT (FR-6.2) jumps to the step whose
  // file it quotes, and selects the quoted line in that step's editor.
  // Steps 01 and 03 are one editor each over the whole file (there is no
  // sections view), so there is no section card to land
  // on: `where` says which file ("instructions § Busses" is step 03's,
  // anything else step 01's) and `line` is the quote conventions_audit.py
  // checked is really there. A finding with no verified quote gets no
  // jump -- it still shows in the dock, with its quote in its message.
  function conventionsJump(finding) {
    const code = finding.code || "";
    if (!(/^conventions\./.test(code) || code === "critic.conventions")) return null;
    if (!finding.line) return null;
    const instructions = /^instructions/.test(finding.where || "");
    return {
      label: instructions ? "03 Instructions" : "01 Conventions",
      mode: "build",
      target: instructions ? "#instr-text" : "#conv-text",
      find: finding.line,
    };
  }

  function withJumps(finding) {
    // FR-X.15c: a grouped item (one message, many rows -- `members` from
    // webui.py's finding_groups) jumps to each member's row, so the
    // Findings column still counts it on every row it is about.
    if (Array.isArray(finding.members) && finding.members.length) {
      const seen = {};
      const jumps = [];
      finding.members.forEach((m) => {
        withJumps(m).jumps.forEach((j) => {
          const key = j.target + "\u0000" + (j.find || "");
          if (seen[key]) return;
          seen[key] = true;
          // Six links all reading "01 Conventions" say nothing; each
          // member's own quoted line tells them apart.
          const label = j.find
            ? j.label + ": " + (j.find.length > 28 ? j.find.slice(0, 27) + "…" : j.find)
            : j.label;
          jumps.push(Object.assign({}, j, { label: label }));
        });
      });
      return Object.assign({}, finding, { jumps: jumps, _producer: "plan" });
    }
    const object = planObjectFor(finding.where);
    const jumps = [];
    const text = conventionsJump(finding);
    if (text) jumps.push(text);
    // A change nobody asked for jumps to the list that says
    // what changed, as well as to its row.
    if (finding.code === "rebuild.unasked-change") {
      jumps.push({ label: "Changed since the last build", mode: "build", target: "#sec-changes" });
    }
    if (object && document.getElementById(cardId(object.kind, object.name))) {
      jumps.push({ label: object.name, mode: "build", target: "#" + cardId(object.kind, object.name) });
    }
    return Object.assign({}, finding, { jumps: jumps, _producer: "plan" });
  }

  // Replaces this step's own findings and leaves everybody else's alone
  // -- the dock is shared by three modes and four steps.
  function replaceFindings(producer, list) {
    SP.setFindings(SP.findings().filter((f) => f._producer !== producer));
    if (list.length) SP.addFindings(list);
  }

  function publishPlanFindings(list) {
    replaceFindings("plan", list.map(withJumps));
  }

  function publishRunFindings(list) {
    replaceFindings("run", (list || []).map((finding) => {
      // Build has no watch step, so the one finding
      // that says a build drafted watch conditions opens Watch, on the
      // rules editor whose Source column marks them Drafted.
      // Switching mode is what makes watch.js re-read watch.json, so the
      // rows the build just added are the rows the jump lands on.
      const jumps = finding.code === "build.watchlist-drafted"
        ? [{ label: "Review on Watch", mode: "watch", target: "#wc-panel" }]
        : [{ label: "04 Plan", mode: "build", target: "#run-panel" }];
      return Object.assign({}, finding, { jumps: jumps, _producer: "run" });
    }));
  }

  // A rebuild has to clear the list of findings in the side bar. The first
  // fix cleared only the producers that describe the plan ("plan", "run",
  // "apply-preflight", "build-refusal") and kept the rest, which read to
  // the engineer as a dock that was not cleared. So a build now empties the dock:
  // the last apply's ("apply") was about a plan this build replaces, and a
  // copy's provenance ("bundle-copy") was said once, when the copy was
  // made. Steps 01-03's findings ("build") are about the three source
  // files and are still true, so they come back when the build ends
  // (`SP.publishBuildFindings`), beside the run's and the new plan's.
  // The bundle bar's message goes too: it was about the last thing done.
  // The producers that describe the plan (and a refused Build): what step
  // 04's one-line findings summary counts.
  const PLAN_PRODUCERS = ["plan", "run", "apply-preflight", "build-refusal"];

  function clearFindingsForBuild() {
    holdPlanFindings = true;
    SP.setFindings([]);
    if (SP.showBundleMessage) SP.showBundleMessage("");
  }

  const REFUSAL_STEP = { "build.no-conventions": "conventions",
                         "build.conventions-missing": "conventions",
                         "build.input-list-missing": "input_list" };

  function publishRefusal(list) {
    replaceFindings("build-refusal", list.map((finding) => {
      const step = REFUSAL_STEP[finding.code];
      const jumps = step
        ? [{ label: step === "conventions" ? "01 Conventions" : "02 Input list", mode: "build",
             target: "#tab-" + step.replace(/_/g, "-") }]
        : [];
      return Object.assign({}, finding, { jumps: jumps, _producer: "build-refusal", _step: step });
    }));
  }

  // A refusal is about a file that was not there. Once it is (Change
  // file, New file, a copy made in another program), its ERROR goes.
  function dropAnsweredRefusals(sources) {
    const kept = SP.findings().filter((f) => f._producer !== "build-refusal"
      || !(f._step && sources && sources[f._step] && sources[f._step].present));
    if (kept.length !== SP.findings().length) SP.setFindings(kept);
  }

  // Which plan.json is on screen, well enough to tell a rebuilt one: every
  // build stamps `meta` afresh (generated_at, the fingerprints).
  function planStamp(plan) {
    return plan && plan.plan ? String(plan.path) + "|" + JSON.stringify(plan.plan.meta || null) : "";
  }

  // ---- the run ----------------------------------------------------------

  function renderRun() {
    const badge = el("run-state");
    const labels = {
      running: ["Running", "state-stale"],
      done: ["Done", "state-loaded"],
      failed: ["Failed", "state-missing"],
      stopped: ["Stopped", "state-notset"],
    };
    runPanel.hidden = run.state === "idle" || !run.state;
    if (run.state === "running") openOptions();
    // A build under way says so on the Options heading, and
    // "No plan yet" stays down while it writes one.
    const building = el("options-building");
    if (building) building.hidden = run.state !== "running";
    const empty = el("plan-empty");
    if (empty && run.state === "running") empty.hidden = true;
    const label = labels[run.state] || ["Idle", "state-notset"];
    badge.textContent = label[0];
    badge.className = "state-badge " + label[1];
    let elapsed = run.elapsed_s;
    if (run.state === "running" && run.started_at) elapsed = Date.now() / 1000 - run.started_at;
    el("run-elapsed").textContent = elapsed != null ? Math.round(elapsed) + " s" : "";
    el("run-exit").textContent = run.exit_code != null ? "exit " + run.exit_code : "";
    el("run-last-command").textContent = (run.command || []).join(" ");
    // Stop: offered while the build runs; "Stopping…" once asked, until
    // the run lands in `stopped`.
    const running = run.state === "running";
    stopBtn.hidden = !running;
    stopBtn.disabled = !running || !!run.stop_requested || stopping || SP.isStale();
    stopBtn.textContent = (run.stop_requested || stopping) && running ? "Stopping…" : "Stop";
    if (!running) stopping = false;
    const stoppedBox = el("run-stopped");
    const stoppedText = run.state === "stopped" && run.stopped ? run.stopped.message : "";
    stoppedBox.textContent = stoppedText;
    stoppedBox.hidden = !stoppedText;
    const log = el("run-log");
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
    log.textContent = (run.log || []).join("\n")
      || (run.state === "running" ? "Started -- waiting for the build's first line…" : "");
    if (atBottom) log.scrollTop = log.scrollHeight;
    // Folded closed by default (#run-log-fold); the summary says how much
    // is behind it, so a closed fold still shows the log is moving.
    const lines = (run.log || []).length;
    el("run-log-summary").textContent = "Build log output"
      + (lines ? " (" + (lines === 1 ? "1 line" : fmtCount(lines) + " lines") + ")" : "");
    renderProgress();
    renderPlanTile();
  }

  // ---- the live readout: which model call, how long, how much ----------
  // `run.progress` is GET /api/build/status's structured progress (the
  // provider's own ModelCallProgress, via a listener on the build's
  // thread) -- not scraped from the log. Read-only. The clock is worked
  // out here from `started_at`, so it keeps moving between polls and
  // while the model is silent, which is most of a hosted build: with
  // thinking not streamed, the elapsed time IS the progress.

  const PHASE_WORDS = {
    // The resolve step (2026-09-30): the house conventions and the domain
    // knowledge restated as one set of rules, made only when either changed.
    resolve: "Resolving the conventions",
    generator: "Generating the plan",
    // The one fix-up round (2026-09-29): verify's errors, or the format
    // check's, sent back to the generator's model for a corrected reply.
    fixup: "Fix-up round",
    critic: "Critic review",
    watchlist: "Drafting watch conditions",
  };
  const STAGE_WORDS = {
    waiting: "waiting for the first reply",
    thinking: "thinking",
    writing: "writing the answer",
    done: "done",
    failed: "failed",
    stopped: "stopped by you",
  };
  const LIVE_STAGES = ["waiting", "thinking", "writing"];

  function phaseName(label) {
    return PHASE_WORDS[label] || (label ? label : "Model call");
  }

  function fmtSeconds(s) {
    if (s == null || isNaN(s)) return "";
    s = Math.max(0, Math.round(s));
    if (s < 60) return s + " s";
    const m = Math.floor(s / 60);
    const rest = s % 60;
    return m + " m " + (rest < 10 ? "0" : "") + rest + " s";
  }

  function fmtCount(n) {
    return n == null ? "" : Number(n).toLocaleString("en-US");
  }

  function callElapsed(p) {
    if (run.state === "running" && LIVE_STAGES.indexOf(p.stage) >= 0 && p.started_at) {
      return Date.now() / 1000 - p.started_at;
    }
    return p.elapsed_s;
  }

  // "thinking ~1,200 · output ~3,400 tokens" while it runs (estimated from
  // characters, hence the ~); the provider's own numbers once it ends.
  function tokenWords(p) {
    if (p.total_output_tokens != null) {
      let words = "";
      if (p.input_tokens != null) words += fmtCount(p.input_tokens) + " in, ";
      words += fmtCount(p.total_output_tokens) + " out";
      if (p.thinking_tokens) words += " (~" + fmtCount(p.thinking_tokens) + " thinking)";
      return words;
    }
    const thinking = p.thinking_tokens == null ? "not streamed" : "~" + fmtCount(p.thinking_tokens);
    return "thinking " + thinking + " · output ~" + fmtCount(p.output_tokens || 0) + " tokens";
  }

  function renderProgress() {
    const box = el("run-progress");
    const bar = el("run-progress-bar");
    const status = el("status-build-progress");
    const running = run.state === "running";
    const p = run.progress || null;
    if (!running && !p) {
      box.hidden = true;
      if (status) status.hidden = true;
      return;
    }
    box.hidden = false;
    bar.classList.toggle("is-stopped", !running);
    const note = el("run-progress-note");
    let noteText = "";
    let summary = "";
    if (!p) {
      // Running, no model call yet: the build is reading the show.
      el("run-progress-phase").textContent = "Starting";
      el("run-progress-stage").textContent = "reading the show's files";
      el("run-progress-elapsed").textContent = fmtSeconds(
        run.started_at ? Date.now() / 1000 - run.started_at : run.elapsed_s);
      el("run-progress-tokens").textContent = "";
      el("run-progress-tokens").hidden = true;
      summary = "starting";
    } else {
      const live = running && LIVE_STAGES.indexOf(p.stage) >= 0;
      let stage = STAGE_WORDS[p.stage] || p.stage || "";
      if (p.stage === "waiting" && p.streams === false) stage = "waiting for the reply";
      if (running && !live) stage += " -- the build carries on";
      // "Critic (claude-sonnet-5, effort medium)": the critic and the
      // watchlist run at their own effort, so the effort is named with
      // the model (it is "" from a provider that has none).
      const who = [p.model, p.effort ? "effort " + p.effort : ""].filter(Boolean).join(", ");
      el("run-progress-phase").textContent = phaseName(p.phase) + (who ? " (" + who + ")" : "");
      el("run-progress-stage").textContent = stage;
      el("run-progress-elapsed").textContent = fmtSeconds(callElapsed(p));
      el("run-progress-tokens").textContent = tokenWords(p);
      el("run-progress-tokens").hidden = false;
      if (live && p.stage === "thinking" && p.thinking_tokens == null) {
        noteText = "This model does not stream its thinking, so its tokens are counted "
          + "when the call ends -- until then the clock is the progress.";
      } else if (live && p.streams === false) {
        noteText = "This provider does not stream: the reply arrives all at once.";
      }
      summary = (p.phase || "model") + " · " + (STAGE_WORDS[p.stage] || p.stage) + " · "
        + fmtSeconds(callElapsed(p));
    }
    note.textContent = noteText;
    note.hidden = !noteText;

    // One chip per model call: the finished ones with their time and
    // spend, the one in flight marked. A phase-based indicator that only
    // claims what has happened -- the build does not announce its next call.
    const list = el("run-progress-calls");
    list.textContent = "";
    const calls = (p && p.calls) || [];
    calls.forEach((call) => {
      const li = document.createElement("li");
      const failed = call.stage === "failed";
      const halted = call.stage === "stopped";
      li.className = failed ? "is-failed" : (halted ? "is-stopped" : "");
      // Each chip names its call's model: the critic and the watchlist
      // run on their own (Haiku by default, 2026-09-28), so "Critic ·
      // claude-haiku-4-5 · 12s" next to "Generator · claude-sonnet-5 ·
      // effort high · 3m" is the split the INFO line announced.
      li.textContent = (failed ? "✗ " : (halted ? "■ " : "✓ ")) + phaseName(call.label) + " · "
        + (call.model ? call.model + " · " : "")
        + (call.effort ? "effort " + call.effort + " · " : "")
        + fmtSeconds(call.elapsed_s)
        + (call.total_output_tokens != null ? " · " + fmtCount(call.total_output_tokens) + " out" : "");
      list.appendChild(li);
    });
    if (p && running && LIVE_STAGES.indexOf(p.stage) >= 0) {
      const li = document.createElement("li");
      li.className = "is-active";
      li.textContent = "● " + phaseName(p.phase) + " · "
        + (p.model ? p.model + " · " : "")
        + (p.effort ? "effort " + p.effort + " · " : "") + fmtSeconds(callElapsed(p));
      list.appendChild(li);
    }
    list.hidden = !list.children.length;
    renderLive(p, running);

    if (status) {
      status.hidden = !running;
      status.textContent = running ? summary : "";
    }
  }

  // ---- what the model is writing -----------------------------------------
  // `progress.outline` is the server's tolerant read of the JSON the model
  // has written so far: the part it is on, the names in each part, and
  // the item in progress. Drawn as sentences, not as JSON scrolling by --
  // "Channels · now: Ch 10 T.Sax -- DCA: Horns" is what tells a person
  // whether to press Stop. By default only the latest message
  // shows, in a box two lines tall; the parts and names written so far,
  // and the raw tail, are each one click away, folded closed.

  const SECTION_WORDS = {
    channels: "Channels", busses: "Busses", dcas: "DCAs",
    mute_groups: "Mute groups", outputs: "Mains and Matrix",
    category_colors: "Colours",
    findings: "Findings", conditions: "Watch conditions",
  };
  const FIELD_WORDS = {
    dca: "DCA", mute_group: "mute groups", bus_sends: "sends", main_routes: "mains",
    patch: "patch", alt_patch: "alternate patch", processing: "processing", source: "source", fader: "fader",
    provenance: "provenance", destination: "destination", destinations: "destinations",
    sends: "sends", pair: "pair",
  };
  const NAMES_SHOWN = 14;

  function sectionName(key) {
    if (SECTION_WORDS[key]) return SECTION_WORDS[key];
    const words = String(key || "").replace(/_/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }

  function itemWords(item) {
    if (!item) return "";
    let who = item.name || "(unnamed)";
    if (item.section === "channels" && item.number != null) who = "Ch " + item.number + " " + who;
    const parts = [];
    const values = item.values || {};
    Object.keys(values).forEach((field) => {
      if (values[field].length) {
        parts.push((FIELD_WORDS[field] || field.replace(/_/g, " ")) + ": " + values[field].join(", "));
      }
    });
    let text = who;
    if (parts.length) text += " — " + parts.join(" · ");
    if (item.field && !values[item.field]) {
      text += (parts.length ? " · " : " — ") + "writing " + (FIELD_WORDS[item.field] || item.field.replace(/_/g, " "));
    }
    return text;
  }

  function renderLive(p, running) {
    const box = el("run-live");
    const outline = p && p.outline;
    const tail = (p && p.tail) || "";
    const thinkingLine = (p && p.thinking_line) || "";
    const show = !!(p && (outline || tail || thinkingLine));
    box.hidden = !show;
    if (!show) return;

    const thinking = el("run-live-thinking");
    // The summary line belongs to the thinking stretch; once the model is
    // writing, what it writes is the better account.
    const showThinking = !!thinkingLine && (p.stage === "thinking" || !outline);
    thinking.textContent = showThinking ? "Thinking: " + thinkingLine : "";
    thinking.hidden = !showThinking;

    const now = el("run-live-now");
    now.textContent = "";
    if (outline && outline.section) {
      // Finished: what it wrote last. In flight: what it is writing now.
      // Stopped or failed part way: what it was writing when it ended.
      const inFlight = running && LIVE_STAGES.indexOf(p.stage) >= 0;
      const verb = outline.complete ? "Wrote " : (inFlight ? "Writing " : "Was writing ");
      const strong = document.createElement("strong");
      strong.textContent = verb + sectionName(outline.section);
      now.appendChild(strong);
      if (outline.item && outline.item.section === outline.section) {
        const item = outline.complete ? Object.assign({}, outline.item, { field: null }) : outline.item;
        now.appendChild(document.createTextNode(
          (outline.complete ? " — last: " : (inFlight ? " — now: " : " — at: ")) + itemWords(item)));
      }
    }
    // One message at a time in the two-line box: the thinking line while
    // the model thinks, what it is writing once it writes.
    now.hidden = !now.textContent || showThinking;

    const list = el("run-live-sections");
    list.textContent = "";
    ((outline && outline.sections) || []).forEach((part) => {
      const li = document.createElement("li");
      if (outline.section === part.name) li.className = "is-current";
      const label = document.createElement("span");
      label.className = "run-live-section";
      label.textContent = sectionName(part.name) + " (" + part.count + ")";
      li.appendChild(label);
      const names = part.names || [];
      const shown = names.slice(-NAMES_SHOWN);
      const earlier = part.count - shown.length;
      let text = shown.length ? ": " + (earlier > 0 ? "… " : "") + shown.join(", ") : "";
      li.appendChild(document.createTextNode(text));
      list.appendChild(li);
    });
    list.hidden = !list.children.length;
    const written = el("run-live-written");
    written.hidden = list.hidden;
    const total = ((outline && outline.sections) || []).reduce((n, part) => n + (part.count || 0), 0);
    el("run-live-written-summary").textContent = "Model output ("
      + (list.children.length === 1 ? "1 part" : list.children.length + " parts")
      + ", " + (total === 1 ? "1 item" : fmtCount(total) + " items")
      + (outline && outline.complete ? ")" : " so far)");

    const pre = el("run-live-tail");
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
    pre.textContent = tail || "(nothing written yet)";
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  }

  async function fetchPlan() {
    try {
      const r = await fetch("/api/plan");
      current = r.ok ? await r.json() : null;
    } catch (e) {
      current = null;
    }
    // The bus sheet comes with it (an edit not saved yet is kept).
    if (!busSheet.dirty) await loadBusSheet();
    if (!userSheet.dirty) await loadUserSheet();
    if (!outSheet.dirty) await loadOutputsSheet();
    renderCurrentPlan();
  }

  async function poll() {
    let status;
    try {
      const r = await fetch("/api/build/status");
      status = await r.json();
    } catch (e) {
      pollTimer = setTimeout(poll, 2000);
      return;
    }
    const wasRunning = run.state === "running";
    run = status;
    renderRun();
    if (run.state === "running") {
      pollTimer = setTimeout(poll, 1000);
      return;
    }
    pollTimer = null;
    publishRunFindings(run.findings);
    if (wasRunning) {
      const before = planStamp(current);
      await fetchPlan();
      // A failed build, or one stopped before it wrote, leaves plan.json
      // as it was: the dock then shows only what this run said.
      holdPlanFindings = false;
      if (planStamp(current) !== before) {
        publishPlanFindings((current && current.findings) || []);
        if (SP.planBuilt) SP.planBuilt();
      }
      // The source files' own findings, emptied with the rest when the
      // build started (see `clearFindingsForBuild`).
      if (SP.publishBuildFindings) SP.publishBuildFindings();
      // A new plan.json records new fingerprints: re-read the sources so
      // the Stale badge answers for the plan that just landed.
      if (SP.refreshBuild) SP.refreshBuild();
    }
  }

  // The elapsed counter ticks between polls: a number that only moves
  // once a second when the server answers is one that stops when the
  // server does, which is the case it most needs to show.
  setInterval(() => { if (run.state === "running") renderRun(); }, 250);

  async function startBuild() {
    showRunMessage("");
    openOptions();
    if (!modelSelect.value) {
      showRunMessage("Choose the console model first -- a build refuses to guess it.");
      modelSelect.focus();
      return;
    }
    runBtn.disabled = true;
    // A build writes plan.json into the bundle the SERVER has open. If that
    // is no longer the one this page shows (restarted, or another tab
    // opened one), the stale-page banner goes up and nothing is sent.
    if (!(await SP.checkServer())) {
      showRunMessage("Nothing was sent: this page is out of date -- reload it.");
      renderPlanTile();
      return;
    }
    try {
      const r = await fetch("/api/build/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // `expected_bundle` (FR-6.11): the bundle this page shows. A build
        // writes into the bundle the SERVER has open; a mismatch is a 409.
        body: JSON.stringify({ console_model: modelSelect.value, critic: critic.checked,
                               expected_bundle: SP.bundle() ? SP.bundle().directory : null }),
      });
      const data = await r.json();
      if (!r.ok) {
        if (data.stale === "bundle") SP.markStale(data.error);
        showRunMessage(data.error || "couldn't start the build");
        // A file that is not there is a to-do on its tile
        // until now -- pressing Build is when it becomes an ERROR, in the
        // dock, jumping back to the tile that needs it.
        publishRefusal(data.findings || []);
        renderPlanTile();
        return;
      }
      run = data;
      clearFindingsForBuild();
      // The build moves plan.json aside as it starts: the plan on screen
      // is the one being replaced, not current.
      current = null;
      renderCurrentPlan();
      renderRun();
      if (!pollTimer) pollTimer = setTimeout(poll, 500);
    } catch (e) {
      showRunMessage(String(e));
      renderPlanTile();
    }
  }

  // Opening the folded build log lands on its latest line.
  const logFold = el("run-log-fold");
  if (logFold) {
    logFold.addEventListener("toggle", () => {
      const log = el("run-log");
      if (logFold.open && log) log.scrollTop = log.scrollHeight;
    });
  }

  bindTableEvents(el("plan-render"));
  // The dock changed (a rebuild, a pre-flight, a tick): recount the rows.
  if (SP.onFindingsChange) {
    SP.onFindingsChange(paintFindingBadges);
    SP.onFindingsChange(paintFindingsSummary);
  }
  // Step 02's rows changed. An edit made HERE only re-marks the rows (the
  // table is not redrawn under the cursor); anything else -- an edit in
  // step 02, a row added or removed, Save, Discard -- redraws, so the two
  // views never disagree.
  if (SP.inputEditor) {
    SP.inputEditor.onChange((origin) => {
      if (origin === "plan") markRowProblems();
      else redrawTables();
      scheduleInputCheck();
    });
  }
  const editLink = el("plan-input-edit-link");
  if (editLink) editLink.addEventListener("click", () => SP.activateStep("input_list"));

  // Stop: `POST /api/build/stop`. The server closes the model call's
  // connection at once; this page keeps polling until the run reads
  // `stopped`, whose sentence says what (if anything) was written.

  async function stopBuild() {
    if (run.state !== "running") return;
    stopping = true;
    renderRun();
    try {
      const r = await fetch("/api/build/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_bundle: SP.bundle() ? SP.bundle().directory : null }),
      });
      const data = await r.json();
      if (!r.ok) {
        stopping = false;
        if (data.stale === "bundle") SP.markStale(data.error);
        showRunMessage(data.error || "couldn't stop the build");
        renderRun();
        // A 409 is usually a build that ended by itself a moment ago: the
        // next poll draws how it ended.
        if (!pollTimer) pollTimer = setTimeout(poll, 250);
        return;
      }
      run = data;
      renderRun();
      if (!pollTimer) pollTimer = setTimeout(poll, 250);
    } catch (e) {
      stopping = false;
      showRunMessage(String(e));
      renderRun();
    }
  }

  runBtn.addEventListener("click", buildAsking);
  stopBtn.addEventListener("click", stopBuild);
  el("plan-rebuild-btn").addEventListener("click", rebuild);
  el("status-rebuild-btn").addEventListener("click", rebuild);
  // A Save, a file changed in another program, a build that landed: each
  // re-reads the sources, and the Stale badge follows.
  SP.onBuildChange((sources) => {
    renderPlanTile();
    dropAnsweredRefusals(sources);
  });
  // The stale-page banner went up: Build plan and both Rebuilds go off
  // with every other control that writes.
  SP.onStale(() => renderPlanTile());
  // A Save in step 02 or 04 laid the input list onto plan.json: draw it.
  if (SP.onPlanBuilt) SP.onPlanBuilt(() => fetchPlan());

  // ---- open a plan.json that is somewhere else ---------------------------
  // What `/setup` did, kept for a plan that is not this bundle's: the
  // in-browser equivalent of `atoo ui --plan`. Read-only.

  async function loadPlanPath() {
    const path = (planPathInput.value || "").trim();
    if (!path) {
      showRunMessage("Enter a plan.json path.");
      return;
    }
    showRunMessage("");
    try {
      const r = await fetch("/api/plan/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path }),
      });
      const data = await r.json();
      if (!r.ok || data.error) {
        showRunMessage(data.error || "Could not load that plan.");
        return;
      }
      current = data;
      renderCurrentPlan();
    } catch (e) {
      showRunMessage("Could not reach the Atoo server.");
    }
  }

  el("plan-load-btn").addEventListener("click", loadPlanPath);
  // Version H's loop: a finding sends you back to the instructions, you
  // correct them, you build again. The tab's own click opens the step.
  el("back-to-instructions").addEventListener("click", () => el("tab-instructions").click());
  planPathInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); loadPlanPath(); }
  });

  // A different show is a different plan: the server swaps in the new
  // bundle's plan.json (or none) on the same event, so re-read it.
  SP.onBundleChange(() => {
    modelSelect.value = "";
    modelNote.hidden = true;
    // The last build was the last show's: its log and its
    // findings go with it -- the server forgets it on the same event. A
    // build still running carries on and reports when it ends.
    if (run.state !== "running") {
      run = { state: "idle" };
      renderRun();
      publishRunFindings([]);
    }
    // A refused Build was about the last show's files.
    publishRefusal([]);
    commandPreview();
    fetchPlan();
  });

  // ---- first paint -------------------------------------------------------
  // shell.js ran first and has drawn steps 01-03, so the editors a
  // finding's jump link looks for already exist.
  renderCurrentPlan();
  // Watch's Edit sheets, or a "Sheet differs from desk" row's
  // Show in Build 04, brings this page to step 04 (the watch keeps running
  // on the server), says so, and finds the row it was sent to. The line
  // goes when the page leaves Build.
  const fromWatchLine = el("plan-from-watch");
  SP.sheetsFromWatch = (row) => {
    SP.activateMode("build");
    SP.activateStep("plan");
    if (fromWatchLine) fromWatchLine.hidden = false;
    if (row && /^plan-(channel|bus|output)-[a-z0-9-]*$/.test(row) && SP.jumpTo) {
      SP.jumpTo({ mode: "build", target: "#" + row });
    }
  };
  if (el("plan-back-to-watch")) {
    el("plan-back-to-watch").addEventListener("click", () => SP.activateMode("watch"));
  }
  SP.onModeChange((mode) => {
    if (mode !== "build" && fromWatchLine) fromWatchLine.hidden = true;
  });
  Promise.all([loadBusSheet(), loadUserSheet(), loadOutputsSheet()]).then(() => {
    if (current && current.plan) redrawTables();
  });
  commandPreview();
  renderRun();
  if (run.state === "running") {
    // The page was opened (or reloaded) while a build runs.
    clearFindingsForBuild();
    poll();
  } else publishRunFindings(run.findings);
})();
