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

  function socketsDesc(sockets) {
    if (!sockets || !sockets.length) return "patch?";
    return sockets.map(socketDesc).join(" + ");
  }

  // Every patch of an output or a bus's dedicated output -- plan_compat.
  // output_patches: `patches` (the fan-out) when not empty, else the one
  // `patch`. A plan built before the rename calls them `sockets` and
  // `socket`, and those plans are on disk, so both are read.
  function outputPatches(entry) {
    if (!entry) return [];
    const many = (entry.patches && entry.patches.length) ? entry.patches
      : ((entry.sockets && entry.sockets.length) ? entry.sockets : null);
    if (many) return many;
    const one = entry.patch !== undefined ? entry.patch : entry.socket;
    return one ? [one] : [];
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

  function destinationDesc(destination) {
    if (!destination) return "(unresolved)";
    if (destination.type === "main") return "→ Main";
    if (destination.type === "matrix") {
      return "→ Matrix (wrong field — state this on the matrix's own " +
        "outputs[].fed_by instead)";
    }
    const label = destination.label ? `"${destination.label}"` : "(unlabeled)";
    return `→ Dedicated output ${label}, ${socketsDesc(outputPatches(destination))}`;
  }

  function fedByDesc(fedBy) {
    if (!fedBy) return "?";
    if (fedBy.type === "main") return `Main ${fedBy.index}`;
    return `bus ${fedBy.name}`;
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
        `${esc(colour.stated)} <span class="setup-dim">— not a desk colour; not written</span>`;
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
      title = `Colour: ${colour.name} (col ${colour.index})`;
    } else if (colour && colour.stated) {
      title = `Colour: ${colour.stated} is not a desk colour; not written`;
    } else {
      title = noColourNote || "Colour: none in the plan";
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
      text += `; the socket is labelled for all of ${esc(home.shared_with.join(", "))}`;
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
      ["Colour", colourDesc(display.colour)],
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
      row ? ["Notes", notesDesc(row, editable)] : null,
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

  const INPUT_COLS = ["category", "type", "model", "phantom", "notes"];

  // `deskName` is html for under the Name cell: the name the plan puts on
  // the strip, when it is not the input's own (a separate Strip column
  // would be redundant).
  function inputCells(row, editable, deskName) {
    const v = row.values;
    const cell = (col, extra) => {
      const cls = "cell-input" + (col === "name" ? "" : " cell-input-extra") + (extra ? " " + extra : "");
      const after = col === "name" && deskName ? deskName : "";
      if (!editable) {
        const text = col === "phantom" ? (v.phantom ? "✓" : "") : (v[col] || "");
        return `<td class="${cls}">${text ? esc(text) : (col === "phantom" ? "" : DASH)}${after}</td>`;
      }
      if (col === "notes") return `<td class="${cls}">${noteButton(row)}</td>`;
      if (col === "phantom") {
        return `<td class="${cls}"><input type="checkbox" data-input-col="phantom" ` +
          `data-input-key="${esc(row.key)}" aria-label="Phantom power"${v.phantom ? " checked" : ""}></td>`;
      }
      const list = col === "type" ? ' list="input-type-options"'
        : (col === "category" ? ' list="input-category-options"' : "");
      return `<td class="${cls}"><input type="text" data-input-col="${col}" data-input-key="${esc(row.key)}"` +
        `${list} aria-label="${col}" value="${esc(v[col] || "")}">${after}</td>`;
    };
    let html = cell("name");
    html += cell("category") + cell("type") + cell("model") + cell("phantom", "col-phantom") +
      cell("notes", "col-notes");
    html += editable
      ? '<td class="cell-input cell-input-extra col-remove"><button type="button" class="btn-icon" ' +
        `data-input-remove="${esc(row.key)}" title="Remove row" aria-label="Remove row">✕</button></td>`
      : '<td class="cell-input cell-input-extra col-remove"></td>';
    return html;
  }

  function noInputCells(note) {
    return `<td class="cell-input"><span class="setup-dim">${esc(note)}</span></td>` +
      '<td class="cell-input cell-input-extra"></td>'.repeat(6);
  }

  // The Plan group: Patch (where the input is patched -- the input list's
  // `patch` column), Phantom (as the plan sets it), DCAs,
  // Mute Groups. There is no Strip column (it would be redundant): the strip's number and colour are the Ch chip, a name
  // the plan changed is under the Name cell, a stereo pair's second row
  // says whose it is, and "unassigned" / "not in this plan" sit beside
  // the patch they qualify.
  function planCells(patch, phantom, dcas, mutes) {
    return `<td class="cell-plan col-patch">${patch}</td>${phantom}<td class="cell-plan">${dcas}</td>` +
      `<td class="cell-plan">${mutes}</td><td class="cell-plan-collapsed-note">Plan collapsed</td>`;
  }

  const NO_PHANTOM = '<td class="cell-plan col-plan-phantom"></td>';
  const PLAN_COLS = 4;  // Patch, Phantom, DCAs, Mute Groups
  const CHANNEL_COLS = 15;

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
      const patchText = (label) => label ? `<span class="socket-chip">${esc(label)}</span>` : DASH;
      if (item.type === "channel") {
        const ch = item.ch;
        const row = item.input;
        const patch = (row && patchOf(row.values)) || (item.d.sockets || []).join(" + ");
        // The name the plan puts on the desk, under the input's own name --
        // only when the two differ ("Keys L" -> "Keys L/R"): the same name
        // twice was the Strip column's redundancy.
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
        html += row ? inputCells(row, editable, deskName)
          : noInputCells(item.sharesWith
            ? `${ch.name} — shares ${patchOf(item.sharesWith.values) || "its patch"} with ${item.sharesWith.values.name}`
            : `${ch.name} — no input-list row`);
        html += planCells(patchText(patch), phantomCell(ch), listOrDash(ch.dca), listOrDash(ch.mute_group));
        html += findingsCell(cardId("channel", ch.name));
        html += "</tr>";
        html += detailRow("channel", ch.name, CHANNEL_COLS, channelDetail(ch, item.d, row, editable));
      } else if (item.type === "pair") {
        const row = item.input;
        // The partner row: the same chip, drawn quieter, with "↳ ST" under
        // the first row's ST, and a bracket down the left of both rows
        // (`.row-stereo` / `.row-pair`) -- one channel on two input rows.
        html += `<tr class="row-primary row-pair ${altCls}" data-input-key="${esc(row.key)}" ` +
          `data-pair-of="${esc(cardId("channel", item.ch.name))}">`;
        html += `<td class="col-num">${numChip(item.d.label, item.d.colour, null, true)}` +
          `${stBadge(item.ch, true)}</td>`;
        html += '<td class="col-expand"></td>';
        html += inputCells(row, editable);
        html += planCells(`${patchText(patchOf(row.values) || item.socket)} <span class="ct-strip-name ct-pair-note" title="The ` +
                          `second input of ${esc(item.ch.name)}'s stereo pair: the same strip">` +
                          `second input of ${esc(item.ch.name)}</span>`,
                          phantomCell(item.ch), DASH, DASH);
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
          : '<span class="setup-dim" title="Added or renamed since this plan was built -- rebuild ' +
            'to place it">not in this plan</span>';
        html += `<tr class="row-primary row-unplanned${skipped ? " row-skipped" : ""} ${altCls}" ` +
          `data-input-key="${esc(row.key)}">`;
        html += `<td class="col-num">${DASH}</td>`;
        html += '<td class="col-expand"></td>';
        html += inputCells(row, editable);
        html += planCells(`${patchOf(row.values) ? patchText(patchOf(row.values)) + " " : ""}${mark}`,
          NO_PHANTOM, "", "");
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
                       model: s.model || "", phantom: !!s.phantom, notes: "" };
      return { key: "plan-" + i, line: null, values: values, original: { name: s.input || "" },
               patchKey: null };
    });
    // The inputs the plan leaves off the desk on purpose are rows too.
    (plan.unassigned_inputs || []).map(unassignedName).forEach((name, i) => {
      rows.push({ key: "plan-unassigned-" + i, line: null, patchKey: null, original: { name: name },
                  values: { patch: "", name: name, category: "", type: "", model: "",
                            phantom: false, notes: "" } });
    });
    return rows;
  }

  function channelTable(plan, display) {
    const inputs = editableInputs();
    const editable = !!inputs;
    const rows = channelRows(plan, display, inputs || inputsFromPlan(plan), editable);
    const slim = !tableState.inputOpen;
    const planCollapsed = !tableState.planOpen;
    const cls = "ct" + (slim ? " ct--input-slim" : "") + (planCollapsed ? " ct--plan-collapsed" : "");
    return '<div class="table-wrap ct-wrap">' +
      `<table class="${cls}" id="plan-channels-table" data-editable="${editable ? "1" : "0"}">` +
      "<thead><tr>" +
      '<th class="col-num" rowspan="2" title="The channel number the plan puts this input on, ' +
      'in the colour it sets">Ch</th>' +
      '<th class="col-expand" rowspan="2"><span class="visually-hidden">Expand</span></th>' +
      `<th class="grp-th grp-input" id="grpth-input" colspan="${slim ? 1 : 7}">` +
      `<button type="button" class="grp-toggle" id="grp-toggle-input" data-group="input" ` +
      `aria-expanded="${slim ? "false" : "true"}"><span class="chevron">&#9656;</span> Input</button></th>` +
      `<th class="grp-th grp-plan" id="grpth-plan" colspan="${planCollapsed ? 1 : PLAN_COLS}">` +
      `<button type="button" class="grp-toggle" id="grp-toggle-plan" data-group="plan" ` +
      `aria-expanded="${planCollapsed ? "false" : "true"}"><span class="chevron">&#9656;</span> Plan ` +
      '<span class="grp-count">(+ detail)</span></button></th>' +
      FINDINGS_TH.replace("<th ", '<th rowspan="2" ') +
      "</tr><tr>" +
      '<th class="subhead-input">Name</th>' +
      '<th class="subhead-input subhead-input-extra">Category</th>' +
      '<th class="subhead-input subhead-input-extra">Type</th>' +
      '<th class="subhead-input subhead-input-extra">Model</th>' +
      '<th class="subhead-input subhead-input-extra">Phantom</th>' +
      '<th class="subhead-input subhead-input-extra">Notes</th>' +
      '<th class="subhead-input subhead-input-extra"><span class="visually-hidden">Remove</span></th>' +
      '<th class="subhead-plan col-patch">Patch</th>' +
      '<th class="subhead-plan col-plan-phantom" title="Phantom power (48V) as the plan sets it -- ' +
      'what apply writes, from the input list\'s phantom column">Phantom</th>' +
      '<th class="subhead-plan">DCAs</th>' +
      '<th class="subhead-plan">Mute Groups</th>' +
      '<th class="subhead-plan-collapsed-note">Plan collapsed</th>' +
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

  function busTable(busses, display) {
    const names = Object.keys(busses);
    let rows = "";
    names.forEach((name, i) => {
      const b = busses[name];
      const destinations = (b.destinations && b.destinations.length)
        ? b.destinations
        : (b.destination ? [b.destination] : []);
      const desc = destinations.length
        ? destinations.map(destinationDesc).join(" + ")
        : destinationDesc(null);
      const width = b.mono === true ? "mono" : (b.mono === false ? "stereo" : null);
      const bd = display[name] || {};
      rows += rowOpen("bus", name, i % 2 ? "alt" : "");
      rows += `<td class="col-num">${numChip(bd.label, bd.colour)}${changeChip(cardId("bus", name))}</td>`;
      rows += expandCell("bus", name);
      rows += `<td class="ct-name">${esc(name)}</td>`;
      rows += `<td>${width ? esc(width) : DASH}</td>`;
      rows += `<td>${esc(desc)}</td>`;
      rows += `<td>${listOrDash(b.dca)}</td><td>${listOrDash(b.mute_group)}</td>`;
      rows += findingsCell(cardId("bus", name)) + "</tr>";
      rows += detailRow("bus", name, 8, kv([
        ["Fader", b.fader ? `<span class="readout">${esc(faderDesc(b.fader))}</span>` : DASH],
        b.processing ? ["Processing", esc(processingDesc(b.processing))] : null,
        b.preset ? ["Bus preset", esc(busPresetDesc(b))] : null,
        busEffectDesc(b) ? ["Effect", esc(busEffectDesc(b))] : null,
        ["Description", b.description ? esc(b.description) : DASH],
      ]) + renderProvenance(b.provenance));
    });
    return '<div class="table-wrap ct-wrap"><table class="ct ct-compact" id="plan-busses-table">' +
      '<thead><tr><th class="col-num" title="The bus number apply writes it to, in the colour it sets">#</th>' +
      '<th class="col-expand"><span class="visually-hidden">Expand</span></th>' +
      "<th>Bus</th><th>Width</th><th>Destination</th><th>DCAs</th><th>Mute Groups</th>" +
      FINDINGS_TH + "</tr></thead>" +
      `<tbody>${rows}</tbody></table></div>`;
  }

  function outputTable(outputs, display) {
    const names = Object.keys(outputs);
    let rows = "";
    names.forEach((name, i) => {
      const o = outputs[name];
      const sockets = outputPatches(o);
      const od = display[name] || {};
      rows += rowOpen("output", name, i % 2 ? "alt" : "");
      rows += `<td class="col-num">${numChip(od.label, od.colour,
        "Colour: none — the plan sets no colour on a Main or a Matrix")}${changeChip(cardId("output", name))}</td>`;
      rows += expandCell("output", name);
      rows += `<td class="ct-name">${esc(name)}</td>`;
      rows += `<td>${o.kind ? esc(o.kind) : DASH}</td>`;
      rows += `<td>${sockets.length ? `<span class="socket-chip">${esc(socketsDesc(sockets))}</span>` : DASH}</td>`;
      rows += `<td>${o.kind === "matrix" ? esc(fedByDesc(o.fed_by)) : DASH}</td>`;
      rows += findingsCell(cardId("output", name)) + "</tr>";
      rows += detailRow("output", name, 7, kv([
        o.fader ? ["Fader", `<span class="readout">${esc(faderDesc(o.fader))}</span>`] : null,
        o.processing ? ["Processing", esc(processingDesc(o.processing))] : null,
        ["Description", o.description ? esc(o.description) : DASH],
      ]) + renderProvenance(o.provenance));
    });
    return '<div class="table-wrap ct-wrap"><table class="ct ct-compact" id="plan-outputs-table">' +
      '<thead><tr><th class="col-num" title="The Main (M) or Matrix (MX) this output is">#</th>' +
      '<th class="col-expand"><span class="visually-hidden">Expand</span></th>' +
      "<th>Output</th><th>Kind</th><th>Patch</th><th>Fed by</th>" + FINDINGS_TH + "</tr></thead>" +
      `<tbody>${rows}</tbody></table></div>`;
  }

  // ---- the table's own controls ----------------------------------------
  // Kept across a redraw (an edit in step 02, a Save, a rebuild): which
  // column groups are open, and which rows.

  const tableState = { inputOpen: false, planOpen: true, open: {} };

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

  function setGroup(group, open) {
    const table = document.getElementById("plan-channels-table");
    if (!table) return;
    if (group === "input") {
      tableState.inputOpen = open;
      table.classList.toggle("ct--input-slim", !open);
      const th = document.getElementById("grpth-input");
      if (th) th.colSpan = open ? 7 : 1;
    } else {
      tableState.planOpen = open;
      table.classList.toggle("ct--plan-collapsed", !open);
      const th = document.getElementById("grpth-plan");
      if (th) th.colSpan = open ? PLAN_COLS : 1;
    }
    const button = document.getElementById("grp-toggle-" + group);
    if (button) button.setAttribute("aria-expanded", String(open));
  }

  function restoreOpenRows() {
    Object.keys(tableState.open).forEach((id) => setDetail(document.getElementById(id), true));
  }

  // Wired once, on the container the tables are drawn into, so a redraw
  // does not have to re-bind anything.
  function bindTableEvents(container) {
    container.addEventListener("click", (ev) => {
      const expand = ev.target.closest(".row-expand-btn");
      if (expand) {
        const row = expand.closest("tr.row-primary");
        setDetail(row, expand.getAttribute("aria-expanded") !== "true");
        return;
      }
      const toggle = ev.target.closest(".grp-toggle");
      if (toggle) {
        setGroup(toggle.dataset.group, toggle.getAttribute("aria-expanded") !== "true");
        return;
      }
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
  const WHERE_KINDS = { channels: "channel", busses: "bus", outputs: "output" };

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
    const m = /^(channels|busses|outputs)\[([^\]]+)\]/.exec(f.where || "");
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
    if (showNotes.length) bits.push(`${showNotes.length} note${showNotes.length === 1 ? "" : "s"} from the model`);
    if (detailNotes.length) {
      bits.push(`${detailNotes.length} line${detailNotes.length === 1 ? "" : "s"} on how the reply was read`);
    }
    if (log) bits.push("the build log");
    let html = '<details class="fold-details" id="plan-notes-details">' +
      `<summary>Details<span class="meta"> · ${esc(bits.join(" · "))}</span></summary>`;
    if (showNotes.length) {
      html += '<p class="sub-label">Notes from the model</p><ul class="setup-notes">' +
        showNotes.map((n) => `<li>${esc(noteLine(n))}</li>`).join("") + "</ul>";
    }
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
      "Ch is the channel number, in the colour the plan sets. Input " +
      "collapsed to Name; Plan columns (Patch, Phantom, DCAs, Mute Groups) expanded. ST marks a stereo " +
      "channel, on the first of its two input rows. ADDED, CHANGED or MOVED marks a strip this " +
      "build changed against the plan it replaced; yellow when nothing it is made from changed. " +
      "The Findings column counts each row's findings in the Findings panel; " +
      "click a badge to find them there. Expand a row for HPF / colour / sends / where the name is " +
      "actually written / notes / provenance.</span></span>";
    let html = blockHead("Channels", chNote, help) +
      '<section class="panel box plan-table-section" id="plan-channels-block">' +
      '<div id="plan-input-toolbar-slot"></div>' +
      channelTable(plan, display || []) + "</section>";

    const busses = plan.busses || {};
    const busNames = Object.keys(busses);
    if (busNames.length) {
      const mono = busNames.filter((n) => busses[n] && busses[n].mono === true).length;
      const st = busNames.filter((n) => busses[n] && busses[n].mono === false).length;
      const note = [String(busNames.length)].concat(mono ? [`${mono} mono`] : [])
        .concat(st ? [`${st} stereo`] : []).join(" · ");
      html += blockHead("Busses", note) +
        '<section class="panel box plan-table-section">' +
        busTable(busses, busDisplay || {}) + "</section>";
    }

    const outputs = plan.outputs || {};
    const outputNames = Object.keys(outputs);
    if (outputNames.length) {
      const kinds = {};
      outputNames.forEach((n) => {
        const k = (outputs[n] && outputs[n].kind) || "other";
        kinds[k] = (kinds[k] || 0) + 1;
      });
      const note = [String(outputNames.length)]
        .concat(Object.keys(kinds).map((k) => `${kinds[k]} ${k}`)).join(" · ");
      html += blockHead("Outputs", note) +
        '<section class="panel box plan-table-section">' +
        outputTable(outputs, outputDisplay || {}) + "</section>";
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
    runBtn.disabled = run.state === "running" || !bundle || !!bundle.demo || SP.isStale();
    // A locked control says why, in words.
    const lock = el("run-build-lock");
    if (lock) {
      const why = run.state === "running" ? "a build is running"
        : !bundle ? "open or create a show first"
        : bundle.demo ? "the Demo show is read-only"
        : SP.isStale() ? "this page is out of date; reload it" : "";
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
      rebuild.disabled = running || !SP.bundle() || SP.isStale();
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
      statusRebuild.disabled = !SP.bundle() || SP.isStale();
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
    startBuild();
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
      mode.textContent = editable
        ? "The Input columns are step 02's input list: an edit here is the same edit, "
          + "saved to the bundle's input.csv by the same Save -- the plan then reads Stale "
          + "until it is rebuilt."
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
    // Hidden until there is something to save, and only where these cells are
    // the editable list.
    ["plan-input-save-btn", "plan-input-discard-btn"].forEach((id) => {
      const node = el(id);
      if (node) node.hidden = !editable || !dirty;
    });
    const badge = el("plan-input-dirty-badge");
    if (badge) badge.hidden = !dirty;
    const save = el("plan-input-save-btn");
    if (save) save.disabled = !dirty || SP.isStale();
    const discard = el("plan-input-discard-btn");
    if (discard) discard.disabled = !dirty;
  }

  function redrawTables() {
    if (!current || !current.plan) return;
    try {
      renderPlan(el("plan-render"), current.plan, current.channel_display,
        current.bus_display, current.output_display);
      renderInputToolbar();
    } catch (e) {
      console.error("Build step 04: failed to redraw the plan", e);
    }
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
    mute_groups: "Mute groups", outputs: "Outputs",
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

  runBtn.addEventListener("click", startBuild);
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
  commandPreview();
  renderRun();
  if (run.state === "running") {
    // The page was opened (or reloaded) while a build runs.
    clearFindingsForBuild();
    poll();
  } else publishRunFindings(run.findings);
})();
