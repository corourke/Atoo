(() => {
  "use strict";

  // Watch mode (FR-6.4), loaded by the shell (`/`) after shell.js,
  // setup.js and apply.js. This was app.js on a page of
  // its own at `/`; it MOVED into the shell's Watch panel with its
  // element ids unchanged, and was not rewritten. What changed in the
  // move: the rules editor has a Source column, and the editor re-reads
  // watch.json when Watch is entered -- a build on this same page may have
  // just drafted into it.
  //
  // The console is the bundle bar's (editable in the
  // bundle bar only). This form used to carry its own IP and port boxes,
  // seeded from the same resolved console; with the address now
  // editable in the bar, two boxes on one page would let Watch read one
  // desk while Apply wrote another -- and watching the desk you have just
  // written is the point of Watch. So Start sends none: the server watches
  // the bar's. The bar also holds the Demo choice (there
  // is no Source picker here), and this form no longer repeats the
  // address at all -- the line under it says which of the two it watches.
  // Demo is the demo show: choosing it opens that show,
  // so a Demo watch always reads the demo show's watch.json, and its
  // Change file / New file / Save are off (the show is read-only).
  //
  // The watch-conditions file is a bundle file -- Change
  // file / New file / Save, handled as Build's input.csv and
  // instructions.md are; see "The file" below.
  //
  // READ-ONLY toward the console (FR-6.7). Nothing here writes to a desk:
  // `/api/watch/start` opens a loop that reads, and Save writes the
  // watch-conditions file on disk. There is no arming control in this
  // file and there must never be one -- Apply's is the only one.

  const SP = window.Atoo || null;

  const SEVERITY_ORDER = { error: 0, warning: 1, info: 2 };
  const SEVERITY_LABEL = { error: "Error", warning: "Warning", info: "Info" };

  const el = (id) => document.getElementById(id);

  // ---- Watch-conditions panel (FR-6.5) -- a small
  // add/remove/edit table over atoo.watch_conditions's fixed
  // {id, description, channel, field, operator, value, severity} schema
  // (plus `bus` on the send fields),
  // wired to the /api/watch-conditions* endpoints the same "path input +
  // Load button" and fetch/JSON-error conventions Build step 04's plan
  // loader uses (atoo/web/static/setup.js). Placed directly
  // below the connect panel and above the summary/table (shell.html's
  // Watch panel), per the Setup UI design.

  const WC_FIELDS = ["muted", "fader_db", "dca", "mute_group", "patch",
                     "send_on", "send_db", "send_mode", "phantom"];
  const WC_OPERATORS = ["==", "!=", ">", "<", ">=", "<="];
  // `muted` is a bool, and the three relational fields ask a
  // yes/no question ("is it in DCA Drums", "is it patched to AES50-A 12") --
  // ordering operators on any of them are refused at load time by
  // atoo.watch_conditions itself (_BOOL_COMPATIBLE_OPERATORS /
  // _EQUALITY_ONLY_FIELDS), so the operator <select> narrows to just
  // these two the moment `field` is one of them, live, per §6.5.
  const WC_BOOL_OPERATORS = ["==", "!="];
  // These take a STRING value -- a group name for dca/
  // mute_group, a socket like "AES50-A 12" for patch -- so the value cell is a
  // text input rather than the checkbox/number the scalar fields use.
  // This list must stay in step with watch_conditions._RELATIONAL_FIELDS;
  // tests/test_webui.py asserts the served asset offers all five fields,
  // because the Python suite cannot otherwise see this file at all.
  const WC_TEXT_FIELDS = ["dca", "mute_group", "patch"];
  // Boolean fields take a checkbox. The three send fields are about a
  // strip's send to a bus, which the row's Bus box names (the `bus` key,
  // shown under the Field select for those fields only), and send_mode
  // takes one of three words. These lists must stay in step with
  // watch_conditions (_BOOLEAN_FIELDS, _SEND_FIELDS, _SEND_MODES).
  const WC_BOOL_FIELDS = ["muted", "send_on", "phantom"];
  const WC_SEND_FIELDS = ["send_on", "send_db", "send_mode"];
  const WC_SEND_MODES = ["pre", "post", "group"];
  const WC_EQUALITY_ONLY_FIELDS = WC_BOOL_FIELDS.concat(WC_TEXT_FIELDS, ["send_mode"]);
  const WC_BUS_PLACEHOLDER = "to bus: BUS 5-8, or a name";
  // What a valid value looks like, shown as placeholder text. A patch is
  // written the way an input list's patch column writes it and the way
  // CV005's own finding prints it -- one vocabulary, so an operator
  // can paste between them. The AES50 network is spelled out: "AES 1"
  // (AES/EBU) and "AES50-A 1" are different sockets.
  const WC_VALUE_PLACEHOLDER = {
    dca: "DCA name, e.g. Drums",
    mute_group: "mute group name, e.g. Band",
    patch: "socket, e.g. AES50-A 12",
  };
  const WC_SEVERITIES = ["error", "warning", "info"];
  // The Channel cell takes a strip name, or a position, a
  // range, a whole kind, or a kind and a name (`BUS Drums`, 2026-10-01). Which
  // spellings are accepted, and which are
  // refused, is decided by the SERVER (`POST /api/watch-conditions/check`,
  // `watch_conditions.row_problems`) -- the loader's own rules -- rather
  // than by a second copy of them here that could drift.
  const WC_CHANNEL_PLACEHOLDER = "name, or CH 10, DCA 1-4, ALL AUX, BUS Drums";
  // Who wrote a condition. atoo.watch_conditions
  // knows two values -- "drafted" (a bundle build proposed it) and
  // "hand" -- and an ABSENT key means "hand", so a file a person wrote
  // stays byte-for-byte theirs. The column reads Drafted / Yours.
  // Nothing in the evaluator reads it; it is how a machine's suggestion
  // is told apart from the engineer's own decision.
  const WC_SOURCE_DRAFTED = "drafted";

  const wcFile = el("wc-file");
  const wcChangeBtn = el("wc-change-btn");
  const wcNewBtn = el("wc-new-btn");
  const wcDirtyBadge = el("wc-dirty-badge");
  const wcSaveBtn = el("wc-save-btn");
  const wcAddBtn = el("wc-add-btn");
  const wcMessage = el("wc-message");
  const wcEmptyState = el("wc-empty-state");
  const wcTableWrap = el("wc-table-wrap");
  const wcBody = el("wc-body");
  const wcDraftedBadge = el("wc-drafted-badge");
  const wcSaveLock = el("wc-save-lock");
  const wcFoldHint = el("wc-fold-hint");
  const wcTable = el("wc-table");

  // The editor's working copy -- plain objects matching the file's own
  // {id, description, channel, field, operator, value, severity} shape.
  // Mutated in place by each row's own input listeners; Save serializes
  // this array straight into {"watch_conditions": [...]}.
  let wcConditions = [];
  // Unsaved edits in the table. Set by every edit, add and remove; cleared
  // by a load or a save. A re-read of watch.json (on entering Watch, or
  // on opening another bundle) never overwrites a table with unsaved
  // edits -- it says so instead.
  let wcDirty = false;
  // What the server last gave us, to tell "the file changed underneath
  // your edits" from "nothing new".
  let wcLoadedSnapshot = null;
  // The file the editor holds -- the path the server answered with, and
  // the one Save writes. Null: none yet (Save then writes the bundle's).
  let wcLoadedPath = null;
  // The open bundle's own watch.json, as the server last described it
  // (`bundle_file`: path, display_path, present), or null with no bundle.
  let wcBundleFile = null;
  // Per-row handles on the cells the server's check can mark
  // (rebuilt with the table), the last check's answer per row, and a
  // counter so a slow answer to an older edit never paints over a newer.
  let wcRowRefs = [];
  let wcRowChecks = [];
  let wcCheckSeq = 0;
  let wcCheckTimer = null;

  // `ok` marks a message that reports something done (a copy, a New
  // file, a Save) rather than something refused, so it does not read red.
  function wcSetMessage(text, ok) {
    wcMessage.classList.toggle("is-ok", !!(text && ok));
    if (!text) {
      wcMessage.hidden = true;
      wcMessage.textContent = "";
    } else {
      wcMessage.hidden = false;
      wcMessage.textContent = text;
    }
  }

  function wcMakeInput(type, value, cls) {
    const input = document.createElement("input");
    input.type = type;
    input.className = cls;
    if (type === "checkbox") input.checked = !!value;
    else input.value = value == null ? "" : String(value);
    return input;
  }

  function wcMakeSelect(options, selected, cls) {
    const select = document.createElement("select");
    select.className = cls;
    for (const opt of options) {
      const option = document.createElement("option");
      option.value = opt;
      option.textContent = opt;
      if (opt === selected) option.selected = true;
      select.appendChild(option);
    }
    return select;
  }

  function wcIsDrafted(cond) {
    return cond.source === WC_SOURCE_DRAFTED;
  }

  // How many drafted conditions nobody has reviewed is a
  // state in the block's header (`.state.is-warn`), and
  // what that means is its title.
  function wcRenderDraftedNote() {
    const drafted = wcConditions.filter(wcIsDrafted).length;
    wcDraftedBadge.hidden = drafted === 0;
    wcDraftedBadge.textContent = drafted + " drafted, unreviewed";
  }

  // A cell is an input only when it can
  // be edited and saved. On a read-only show (the Demo) the table is
  // text, the controls that would change the file are hidden
  // (styles.css, `body.is-demo-show`), and Save stays up, locked, with
  // the reason -- as Build step 02 does.
  function wcReadOnly() {
    const show = wcBundle();
    return !!(show && show.demo);
  }

  // Save, by the UI style rules: hidden with nothing to save; locked, with
  // the reason in words, when it could not work; a live primary only
  // when pressing it writes a file. It was a live
  // brass button on an empty page with no file and no show.
  let wcSaving = false;
  function wcSaveLockReason() {
    if (wcReadOnly()) return "the Demo show is read-only";
    if (!wcLoadedPath && !wcBundle()) return "no watch-conditions file. Change file to choose one";
    return "";
  }

  function wcRenderSave() {
    const reason = wcSaveLockReason();
    const shown = wcDirty || wcReadOnly();
    wcSaveBtn.hidden = !shown;
    wcSaveBtn.disabled = !!reason || !wcDirty || wcSaving;
    wcSaveLock.textContent = reason;
    wcSaveLock.hidden = !(shown && reason);
    if (wcFoldHint) wcFoldHint.textContent = wcReadOnly() ? "Show" : "Edit";
  }

  // A cell of text, for a read-only show (§7).
  function wcTextCell(tr, text, cls) {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    td.textContent = text == null ? "" : String(text);
    tr.appendChild(td);
    return td;
  }

  function wcBuildRow(cond, index) {
    const tr = document.createElement("tr");
    const readOnly = wcReadOnly();

    // The Source cell, drawn by a function because an edit anywhere in
    // this row changes it in place -- rebuilding the row on every
    // keystroke would take the cursor out of the box being typed in.
    const sourceCell = document.createElement("td");
    sourceCell.className = "wc-source";
    function renderSource() {
      sourceCell.textContent = "";
      if (wcIsDrafted(cond)) {
        // A button, not a label: pressing it is how an engineer keeps a
        // drafted condition exactly as proposed and still says "reviewed".
        // Drafted is a state (unreviewed, §6), so it is yellow; on a
        // read-only show there is nothing to press, so it is only the tag.
        const tag = document.createElement(readOnly ? "span" : "button");
        if (!readOnly) tag.type = "button";
        tag.className = "state is-warn wc-source-drafted";
        tag.textContent = "Drafted";
        tag.title = readOnly ? "Proposed by a bundle build, and not yet reviewed."
          : "Proposed by a bundle build. Edit it, or press this, "
            + "and it is yours; delete it and the next build does not re-add it.";
        if (!readOnly) tag.addEventListener("click", edited);
        sourceCell.appendChild(tag);
      } else {
        // Who wrote it is a fact about the row, not a state (§6).
        const tag = document.createElement("span");
        tag.className = "prop wc-source-yours";
        tag.textContent = "Yours";
        sourceCell.appendChild(tag);
      }
    }
    // Every edit calls this. An edit is a decision, so a drafted condition
    // someone has touched is no longer the machine's: its `source` key is
    // DELETED rather than set to "hand", because absent is what a
    // hand-written condition looks like in the file. The id stays in the
    // file's top-level `drafted` list (the save endpoint carries it
    // forward), so the next build still leaves it alone.
    function edited() {
      wcSetDirty(true);
      wcScheduleCheck();
      if (wcIsDrafted(cond)) {
        delete cond.source;
        renderSource();
        wcRenderDraftedNote();
      }
    }
    renderSource();

    // A read-only show: the same columns, as text (no remove column).
    if (readOnly) {
      wcRowRefs[index] = {};
      wcTextCell(tr, cond.id, "wc-text wc-text-id");
      wcTextCell(tr, cond.description, "wc-text wc-text-desc");
      wcTextCell(tr, cond.channel, "wc-text");
      wcTextCell(tr, cond.bus ? cond.field + " \u2192 " + cond.bus : cond.field,
        "wc-text wc-text-mono");
      wcTextCell(tr, cond.operator, "wc-text wc-text-mono");
      wcTextCell(tr, cond.value, "wc-text wc-text-mono");
      const sevCell = document.createElement("td");
      const sev = WC_SEVERITIES.includes(cond.severity) ? cond.severity : "info";
      const tag = document.createElement("span");
      tag.className = "sev sev-" + sev;
      tag.textContent = SEVERITY_LABEL[sev];
      sevCell.appendChild(tag);
      tr.appendChild(sevCell);
      tr.appendChild(sourceCell);
      return tr;
    }

    const idCell = document.createElement("td");
    const idInput = wcMakeInput("text", cond.id, "wc-id");
    idInput.addEventListener("input", () => { cond.id = idInput.value; edited(); });
    idCell.appendChild(idInput);
    tr.appendChild(idCell);

    const descCell = document.createElement("td");
    const descInput = wcMakeInput("text", cond.description, "wc-description");
    descInput.addEventListener("input", () => { cond.description = descInput.value; edited(); });
    descCell.appendChild(descInput);
    tr.appendChild(descCell);

    const refs = {};
    wcRowRefs[index] = refs;

    const channelCell = document.createElement("td");
    const channelInput = wcMakeInput("text", cond.channel, "wc-channel");
    channelInput.placeholder = WC_CHANNEL_PLACEHOLDER;
    channelInput.addEventListener("input", () => {
      cond.channel = channelInput.value;
      refs.channelNote = "";
      edited();
    });
    // A position is written in its one display spelling (`ch10` -> `CH
    // 10`), and a scoped name's kind word likewise (`bus Drums` -> `BUS
    // Drums`), once the cell is left, as Save would write it. A bare name
    // is never touched, nor a scoped name's own spelling.
    channelInput.addEventListener("blur", async () => {
      await wcRunCheck();
      const check = wcRowChecks[index];
      if (check && (check.position || check.scoped) && !check.channel && check.canonical
          && check.canonical !== cond.channel) {
        // `Main` alone is read as MAIN 1: the server's `check.note` says
        // so, and stays under the cell (not red) until it is edited.
        refs.channelNote = check.note || "";
        cond.channel = check.canonical;
        channelInput.value = check.canonical;
        wcPaintChecks();
      }
    });
    channelCell.appendChild(channelInput);
    refs.channel = [channelInput, wcMakeCellError(channelCell)];
    tr.appendChild(channelCell);

    const fieldCell = document.createElement("td");
    const fieldSelect = wcMakeSelect(WC_FIELDS, cond.field, "wc-field");
    fieldSelect.addEventListener("change", () => {
      cond.field = fieldSelect.value;
      edited();
      if (WC_EQUALITY_ONLY_FIELDS.includes(cond.field)
          && !WC_BOOL_OPERATORS.includes(cond.operator)) {
        cond.operator = "==";
      }
      // The value's TYPE is a function of the field, so switching field
      // has to carry the value across or reset it -- a number left in a
      // `dca` row would be rejected at load time by the Python side.
      if (WC_BOOL_FIELDS.includes(cond.field)) {
        cond.value = typeof cond.value === "boolean" ? cond.value : false;
      } else if (cond.field === "send_mode") {
        cond.value = WC_SEND_MODES.includes(cond.value) ? cond.value : "pre";
      } else if (WC_TEXT_FIELDS.includes(cond.field)) {
        cond.value = typeof cond.value === "string" ? cond.value : "";
      } else {
        cond.value = typeof cond.value === "number" ? cond.value : 0;
      }
      // Only a send field has a bus, and the loader refuses the key on any
      // other.
      if (WC_SEND_FIELDS.includes(cond.field)) {
        if (typeof cond.bus !== "string") cond.bus = "";
      } else {
        delete cond.bus;
      }
      // `field` changing narrows the operator <select> AND switches the
      // value input's type (checkbox <-> number) -- both live only in a
      // full row rebuild, not a targeted DOM patch.
      wcRenderTable();
    });
    fieldCell.appendChild(fieldSelect);
    refs.field = [fieldSelect, wcMakeCellError(fieldCell)];
    if (WC_SEND_FIELDS.includes(cond.field)) {
      const busInput = wcMakeInput("text", cond.bus, "wc-bus");
      busInput.placeholder = WC_BUS_PLACEHOLDER;
      busInput.setAttribute("aria-label", "Send to bus");
      busInput.addEventListener("input", () => { cond.bus = busInput.value; edited(); });
      // A bus is written in its one display spelling (`bus5-8` -> `BUS
      // 5-8`) once the cell is left, as the Channel cell is.
      busInput.addEventListener("blur", async () => {
        await wcRunCheck();
        const check = wcRowChecks[index];
        if (check && !check.bus && check.bus_canonical && check.bus_canonical !== cond.bus) {
          cond.bus = check.bus_canonical;
          busInput.value = check.bus_canonical;
        }
      });
      fieldCell.appendChild(busInput);
      refs.bus = [busInput, wcMakeCellError(fieldCell)];
    }
    tr.appendChild(fieldCell);

    const opCell = document.createElement("td");
    const opOptions = WC_EQUALITY_ONLY_FIELDS.includes(cond.field)
      ? WC_BOOL_OPERATORS : WC_OPERATORS;
    const opSelect = wcMakeSelect(opOptions, cond.operator, "wc-operator");
    opSelect.addEventListener("change", () => { cond.operator = opSelect.value; edited(); });
    opCell.appendChild(opSelect);
    tr.appendChild(opCell);

    const valueCell = document.createElement("td");
    if (WC_BOOL_FIELDS.includes(cond.field)) {
      const checkbox = wcMakeInput("checkbox", cond.value, "wc-value-checkbox");
      checkbox.addEventListener("change", () => { cond.value = checkbox.checked; edited(); });
      valueCell.appendChild(checkbox);
    } else if (cond.field === "send_mode") {
      const mode = wcMakeSelect(WC_SEND_MODES, cond.value, "wc-value-select");
      mode.addEventListener("change", () => { cond.value = mode.value; edited(); });
      valueCell.appendChild(mode);
    } else if (WC_TEXT_FIELDS.includes(cond.field)) {
      const text = wcMakeInput("text", cond.value, "wc-value-text");
      text.placeholder = WC_VALUE_PLACEHOLDER[cond.field] || "";
      text.addEventListener("input", () => { cond.value = text.value; edited(); });
      valueCell.appendChild(text);
    } else {
      const number = wcMakeInput("number", cond.value, "wc-value-number");
      number.step = "any";
      number.addEventListener("input", () => {
        const parsed = parseFloat(number.value);
        cond.value = Number.isNaN(parsed) ? 0 : parsed;
        edited();
      });
      valueCell.appendChild(number);
    }
    refs.value = [valueCell.firstChild, wcMakeCellError(valueCell)];
    tr.appendChild(valueCell);

    const sevCell = document.createElement("td");
    const sevSelect = wcMakeSelect(WC_SEVERITIES, cond.severity, "wc-severity");
    sevSelect.addEventListener("change", () => { cond.severity = sevSelect.value; edited(); });
    sevCell.appendChild(sevSelect);
    tr.appendChild(sevCell);

    tr.appendChild(sourceCell);

    const removeCell = document.createElement("td");
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    // H's compact remove control: in the shell this table shares its row
    // with the findings dock, and a word-width button was the column
    // that fell off the right-hand edge.
    removeBtn.className = "btn-icon wc-remove";
    removeBtn.title = "Remove this condition";
    removeBtn.setAttribute("aria-label", "Remove this condition");
    removeBtn.textContent = "\u2715";
    removeBtn.addEventListener("click", () => {
      wcSetDirty(true);
      wcConditions.splice(index, 1);
      wcRowChecks.splice(index, 1);
      wcRenderTable();
    });
    removeCell.className = "wc-col-remove";
    removeCell.appendChild(removeBtn);
    tr.appendChild(removeCell);

    return tr;
  }

  function wcRenderTable() {
    wcBody.innerHTML = "";
    wcRowRefs = [];
    wcConditions.forEach((cond, index) => wcBody.appendChild(wcBuildRow(cond, index)));
    wcEmptyState.hidden = wcConditions.length > 0;
    wcTableWrap.hidden = wcConditions.length === 0;
    wcTable.classList.toggle("is-readonly", wcReadOnly());
    wcRenderFoldMeta();
    wcRenderDraftedNote();
    wcRenderSave();
    wcPaintChecks();
    if (!wcReadOnly()) wcScheduleCheck();
  }

  // ---- Inline checks -----------------------------------
  //
  // The UI rejects channel names or values that are not
  // well formed. Each row is asked of the server, which answers with
  // the loader's own reasons per cell; a refused cell is outlined and its
  // reason shown under it, and Save refuses while any remain.

  function wcMakeCellError(cell) {
    const err = document.createElement("div");
    err.className = "wc-cell-error";
    err.hidden = true;
    cell.appendChild(err);
    return err;
  }

  function wcPaintChecks() {
    wcRowRefs.forEach((refs, index) => {
      const check = wcRowChecks[index] || {};
      for (const cell of ["channel", "field", "bus", "value"]) {
        if (!refs || !refs[cell]) continue;
        const [control, err] = refs[cell];
        const reason = check[cell] || "";
        if (control && control.classList) control.classList.toggle("is-invalid", !!reason);
        if (control && control.setAttribute) {
          if (reason) control.setAttribute("aria-invalid", "true");
          else control.removeAttribute("aria-invalid");
        }
        const note = (!reason && cell === "channel") ? (check.note || refs.channelNote || "") : "";
        err.textContent = reason || note;
        err.hidden = !(reason || note);
        err.classList.toggle("is-note", !reason && !!note);
      }
    });
  }

  function wcScheduleCheck() {
    if (wcCheckTimer) clearTimeout(wcCheckTimer);
    wcCheckTimer = setTimeout(() => { wcCheckTimer = null; wcRunCheck(); }, 250);
  }

  // Resolves to the number of refused cells, or null when the server
  // could not be asked (Save then leaves the refusing to the server).
  async function wcRunCheck() {
    if (wcCheckTimer) { clearTimeout(wcCheckTimer); wcCheckTimer = null; }
    const seq = ++wcCheckSeq;
    let data;
    try {
      const res = await fetch("/api/watch-conditions/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ watch_conditions: wcConditions }),
      });
      if (!res.ok) return null;
      data = await res.json();
    } catch (e) {
      return null;
    }
    if (seq !== wcCheckSeq) return wcCountProblems(wcRowChecks);
    wcRowChecks = Array.isArray(data.rows) ? data.rows : [];
    wcPaintChecks();
    return wcCountProblems(wcRowChecks);
  }

  function wcCountProblems(rows) {
    let n = 0;
    for (const row of rows) {
      for (const cell of ["channel", "field", "bus", "value", "row"]) if (row && row[cell]) n += 1;
    }
    return n;
  }

  // ---- The file: a bundle file, like Build's -------------
  //
  // The `watch.json` file always goes with the current bundle, and its
  // file handling is consistent with the way the other files are handled:
  // file change / new / save, and if we change to a new
  // file or create a new one, it goes into the bundle. So the row reads
  // like a Build tile's: the file as a readout, then
  //
  //   Change file  the file browser. With a bundle open, a file from
  //                outside it is COPIED in as its watch.json by the very
  //                flow steps 02 and 03 use (`Atoo.adoptIntoBundle`,
  //                `POST /api/bundle/adopt`, slot `watch`): asked before
  //                replacing one, the old one kept as backups/watch.json.bak, and
  //                an INFO in the dock saying where the copy came from.
  //                With no bundle open, the file is used where it is.
  //   New file     an empty watch.json in the bundle, never over one --
  //                offered only when the bundle has none, as step 03's is.
  //   Save         writes the file shown; with none yet, the bundle's.
  //
  // The path is the server's (`wcLoadedPath`); there is no box to type
  // one into any more.

  const WC_FILE_NONE = "no watch-conditions file";

  function wcBundle() {
    return SP && typeof SP.bundle === "function" ? SP.bundle() : null;
  }

  function wcSetDirty(dirty) {
    wcDirty = !!dirty;
    wcDirtyBadge.hidden = !wcDirty;
    wcRenderFoldMeta();
    wcRenderSave();
  }

  // The editor's folded line says what is in it.
  function wcRenderFoldMeta() {
    const meta = el("wc-fold-meta");
    if (!meta) return;
    const n = wcConditions.length;
    // The block's notation (§3): the count, then the file, as data type.
    meta.textContent = n + (n === 1 ? " condition" : " conditions");
    if (wcLoadedPath) {
      const own = wcBundleFile && wcBundleFile.path === wcLoadedPath;
      meta.appendChild(document.createTextNode(" \u00b7 "));
      meta.appendChild(makeCode(own ? wcBundleFile.display_path : wcLoadedPath));
    }
    // The Unsaved tag in the box says so; saying it here too is a second voice.
  }

  // The readout: the bundle's file by its short name (`touringband/
  // watch.json`), anything else by its whole path, said to be outside.
  function wcRenderFile() {
    const show = wcBundle();
    const own = wcBundleFile && wcBundleFile.path;
    let text = WC_FILE_NONE;
    if (wcLoadedPath && own && wcLoadedPath === own) {
      text = wcBundleFile.display_path;
    } else if (wcLoadedPath) {
      text = wcLoadedPath + (show ? "  (outside the bundle -- Change file copies one in)" : "");
    } else if (show) {
      text = (wcBundleFile ? wcBundleFile.display_path : "watch.json") + " -- not created yet";
    }
    wcFile.textContent = text;
    wcFile.title = wcLoadedPath || "";
    wcFile.classList.toggle("is-empty", !wcLoadedPath);
    wcNewBtn.hidden = !(show && wcBundleFile && !wcBundleFile.present);
    wcRenderFoldMeta();
    wcRenderSave();
  }

  function wcApplyResponse(data) {
    if (data && "bundle_file" in data) wcBundleFile = data.bundle_file || null;
    wcConditions = (data && Array.isArray(data.watch_conditions))
      ? data.watch_conditions.map((c) => Object.assign({}, c))
      : [];
    wcRowChecks = [];
    wcSetDirty(false);
    wcLoadedPath = data && data.path ? data.path : null;
    wcLoadedSnapshot = JSON.stringify(wcConditions);
    wcRenderTable();
    wcRenderFile();
  }

  wcAddBtn.addEventListener("click", () => {
    // No `source` key: a row added here is the engineer's own.
    wcSetDirty(true);
    wcConditions.push({
      id: "", description: "", channel: "", field: "muted", operator: "==",
      value: false, severity: "warning",
    });
    wcRenderTable();
  });

  // A file used where it is: no bundle open, or "Keep the bundle's".
  async function wcLoadPointer(path, dialog) {
    const res = await fetch("/api/watch-conditions/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      dialog.error(data.error || "Could not load that watch-conditions file.");
      return false;
    }
    wcApplyResponse(data);
    wcSetMessage(null);
    return true;
  }

  async function wcChooseFile(result, dialog) {
    if (wcDirty) {
      const go = await dialog.ask(
        "The watch conditions have changes on this page that are not saved. Opening " +
        (result.name || result.path) + " puts that file in the editor and throws them " +
        "away -- Cancel and Save them first if you want them.",
        [
          { id: "discard", label: "Open it and discard my changes", primary: true },
          { id: "cancel", label: "Cancel" },
        ]
      );
      if (go !== "discard") return false;
    }
    if (!wcBundle() || !SP || typeof SP.adoptIntoBundle !== "function") {
      return wcLoadPointer(result.path, dialog);
    }
    return SP.adoptIntoBundle("watch", result, dialog, {
      keep: (path) => wcLoadPointer(path, dialog),
      absorb: (data) => {
        wcApplyResponse(data);
        wcSetMessage(data.message || null, true);
        // The copy's provenance, as Build's copies have it: an INFO in the
        // dock, kept while this bundle is open.
        if (data.finding && typeof SP.addFindings === "function") {
          SP.addFindings([Object.assign({}, data.finding, {
            jumps: [{ label: "Watch conditions", mode: "watch", target: "#wc-panel" }],
            _producer: "bundle-copy",
          })]);
        }
      },
    });
  }

  wcChangeBtn.addEventListener("click", () => {
    const files = window.AtooFiles;
    if (!files) return;
    const show = wcBundle();
    files.open({
      mode: "open-file",
      kind: "json",
      title: "Open a watch-conditions file",
      note: show
        ? "A file from outside " + show.name + "/ is copied into it as watch.json -- the " +
          "bundle keeps its own copy, and edits to the original will not reach it."
        : "No show bundle is open, so this file is used where it is. Open or create a " +
          "bundle first to keep a copy with the show.",
      start: wcLoadedPath || (show ? show.directory
        : (SP && typeof SP.workspace === "function" ? SP.workspace() : "")),
      onChoose: wcChooseFile,
    });
  });

  wcNewBtn.addEventListener("click", async () => {
    const show = wcBundle();
    if (!show) return;
    if (SP && typeof SP.checkServer === "function" && !(await SP.checkServer())) return;
    wcNewBtn.disabled = true;
    try {
      const res = await fetch("/api/watch-conditions/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // It writes into the bundle, so it names the one this page shows
        // (FR-6.11); a stale page is refused with a 409.
        body: JSON.stringify({ expected_bundle: show.directory }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        if (res.status === 409 && data.stale && SP && SP.markStale) {
          SP.markStale(data.error);
          return;
        }
        wcSetMessage(data.error || "Could not create watch.json.");
        return;
      }
      if (wcDirty) {
        // Rows typed before there was a file are kept, unsaved: the new
        // file is where Save now puts them.
        wcBundleFile = data.bundle_file || wcBundleFile;
        wcLoadedPath = data.path;
        wcLoadedSnapshot = JSON.stringify([]);
        wcRenderFile();
        wcSetMessage(data.message + " Your unsaved rows are still here -- Save writes them to it.",
          true);
      } else {
        wcApplyResponse(data);
        wcSetMessage(data.message || null, true);
      }
    } catch (e) {
      wcSetMessage("Could not reach the Atoo server.");
    } finally {
      wcNewBtn.disabled = false;
    }
  });

  wcSaveBtn.addEventListener("click", async () => {
    if (!wcLoadedPath && !wcBundle()) {
      wcSetMessage("No show bundle open, and no watch-conditions file -- open a bundle, " +
        "or Change file to pick a file to save into.");
      return;
    }
    // Client-side duplicate-id check (§6.5) -- a duplicate id is a
    // load-time WatchConditionsError with no way to tell which entry
    // from the message alone, so catch it here first, before Save.
    const seenIds = new Set();
    for (const cond of wcConditions) {
      const id = (cond.id || "").trim();
      if (!id) {
        wcSetMessage("Every condition needs a non-empty id.");
        return;
      }
      if (seenIds.has(id)) {
        wcSetMessage(`Duplicate condition id ${JSON.stringify(id)} -- ids must be unique.`);
        return;
      }
      seenIds.add(id);
    }
    // The inline check, run now rather than trusting the last
    // debounced answer. The server refuses a bad row on Save anyway; this
    // is so the refusal names the cell.
    const problems = await wcRunCheck();
    if (problems) {
      wcSetMessage(problems === 1
        ? "One cell is marked in red -- fix it before saving."
        : problems + " cells are marked in red -- fix them before saving.");
      return;
    }
    wcSetMessage(null);
    wcSaving = true;
    wcRenderSave();
    try {
      // No path is the open bundle's watch.json (the server's default).
      const res = await fetch("/api/watch-conditions/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: wcLoadedPath, watch_conditions: wcConditions }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        wcSetMessage(data.error || "Could not save that watch-conditions file.");
        return;
      }
      wcApplyResponse(data);
      // A save while watching is picked up at once.
      wcSetMessage("Saved " + wcFile.textContent + "." +
        (data.watch_reloaded ? " Watch is using it from the next reading." : ""), true);
    } catch (e) {
      wcSetMessage("Could not reach the Atoo server.");
    } finally {
      wcSaving = false;
      wcRenderSave();
    }
  });

  // Reads whatever is currently loaded server-side (the
  // `--watch-conditions` startup flag, the open bundle's watch.json, or
  // an earlier load, copy, New file or Save from any tab), via a fetch
  // rather than the shell's embedded blob.
  //
  // It runs at load AND each time Watch is entered or another bundle is
  // opened. On one page, Build step 04 can draft into
  // watch.json while this table sits in a hidden panel holding the file
  // as it was -- and a Save from that stale table would silently drop
  // every condition the build just added (their ids stay in `drafted`,
  // so the next build would not put them back either). So a table with
  // no unsaved edits is refreshed; one WITH unsaved edits is left alone
  // and told, because overwriting someone's typing is worse.
  // The watch-conditions file the server held when this page was drawn
  // (`--watch-conditions`), from the embedded start-up data.
  function wcStartupPath() {
    const tag = el("initial-shell");
    if (!tag) return null;
    try {
      return (JSON.parse(tag.textContent) || {}).watch_conditions_path || null;
    } catch (e) {
      return null;
    }
  }
  const wcStartedWith = wcStartupPath();

  async function wcRefresh() {
    // With no show open the server holds a file only if one was given at
    // start-up or this page has loaded one: otherwise there is nothing to
    // ask for, and asking would put a 404 in the browser's console.
    if (!wcBundle() && !wcLoadedPath && !wcStartedWith) {
      wcRenderFile();
      return;
    }
    let res;
    try {
      res = await fetch("/api/watch-conditions");
    } catch (e) {
      return; // offline / server not up yet -- keep what is on screen
    }
    let data = null;
    let body = null;
    try { body = await res.json(); } catch (e) { body = null; }
    if (res.ok) {
      if (!body) return;
      data = body;
    } else if (res.status !== 404) {
      return;
    }
    // The bundle's own file, from either answer: New file depends on it.
    if (body && "bundle_file" in body) wcBundleFile = body.bundle_file || null;
    const incoming = JSON.stringify(data && Array.isArray(data.watch_conditions)
      ? data.watch_conditions : []);
    const incomingPath = data && data.path ? data.path : null;
    if (incoming === wcLoadedSnapshot && incomingPath === wcLoadedPath) {
      wcRenderFile();
      return;
    }
    if (wcDirty) {
      // Say which file Save would write, which is still the one these
      // edits belong to -- so when the server moved to a DIFFERENT file
      // (another bundle was opened), Save alone would not reach it.
      const editing = wcLoadedPath;
      if (incomingPath && incomingPath !== editing) {
        wcSetMessage("Watch's file is now " + incomingPath + ", but this table holds "
          + "unsaved edits to " + (editing || "no file yet") + ". Save writes them "
          + "there; Change file opens the new one and discards them.");
      } else if (!incomingPath) {
        wcSetMessage("The server no longer has a watch-conditions file loaded, but this "
          + "table holds unsaved edits. Save writes them to " + (editing || "the bundle's "
          + "watch.json") + ".");
      } else {
        wcSetMessage(incomingPath + " changed on the server while this table has "
          + "unsaved edits. Your edits are still here: Save writes them over it, and "
          + "Change file re-opens the file and discards them.");
      }
      wcRenderFile();
      return;
    }
    wcApplyResponse(data ? data : { bundle_file: wcBundleFile });
  }

  async function wcInit() {
    wcRenderTable();
    await wcRefresh();
    if (SP && typeof SP.onModeChange === "function") {
      SP.onModeChange((mode) => { if (mode === "watch") wcRefresh(); });
    }
    if (SP && typeof SP.onBundleChange === "function") {
      // A read-only show draws the table as text, so a change between a
      // writable show and the Demo redraws it as well as re-reading it.
      let wasReadOnly = wcReadOnly();
      SP.onBundleChange(() => {
        if (wcReadOnly() !== wasReadOnly) {
          wasReadOnly = wcReadOnly();
          wcRenderTable();
        }
        wcRefresh();
      });
    }
  }

  const intervalInput = el("interval");
  const startBtn = el("start-btn");
  const stopBtn = el("stop-btn");
  const panelMessage = el("panel-message");
  const connPill = el("conn-pill");
  const baselineNote = el("baseline-note");
  const coverageNote = el("coverage-note");
  const alertBody = el("alert-body");
  const emptyState = el("empty-state");
  // Whether the alert table has no rows; set by renderTable, and read by
  // renderEmptyState, which is also redrawn when Start's lock changes.
  let tableEmpty = true;
  const lastUpdated = el("last-updated");
  // The block header's notation (which console) and Start's
  // lock reason; the verdict bar that heads the alert table (§10).
  const consoleNote = el("watch-notation");
  const startLock = el("start-lock");
  const verdictBar = el("watch-verdict");
  const verdictWord = el("watch-verdict-word");
  const verdictLine = el("watch-verdict-line");
  const alertHead = document.querySelector("#alert-table thead");
  const consoleOrigin = el("console-origin");
  const watchNotes = el("watch-notes");
  // The flash, and the two folds below the table.
  const watchFlash = el("watch-flash");
  const flashToggle = el("watch-flash-on");
  // "Flash on new" is the engineer's choice: off until turned on, and
  // remembered on this device. A switch (role="switch"), not a
  // checkbox -- the only checkbox that reaches a console is Apply's
  // arming control. (The rows' Hide buttons only hide a
  // row here.)
  let flashOn = false;
  try { flashOn = localStorage.getItem("atoo.watchFlash") === "1"; } catch (e) { /* off */ }
  function renderFlashToggle() {
    flashToggle.setAttribute("aria-checked", flashOn ? "true" : "false");
    flashToggle.querySelector(".word").textContent = flashOn ? "On" : "Off";
  }
  renderFlashToggle();
  flashToggle.addEventListener("click", () => {
    flashOn = !flashOn;
    renderFlashToggle();
    try { localStorage.setItem("atoo.watchFlash", flashOn ? "1" : "0"); } catch (e) { /* this page only */ }
  });
  // Virtual soundcheck: the engineer's word that the alternate inputs are on
  // purpose. A switch (role="switch") with a state tag beside the
  // connection while it is on. Off until pressed, sent with Start, told to the
  // server while a watch runs; the server forgets it at Stop, so every Start
  // begins Off and nothing is stored on this device.
  const vsToggle = el("watch-virtual");
  const vsPill = el("vs-pill");
  let virtualSoundcheck = false;
  function renderVirtualSoundcheck() {
    vsToggle.setAttribute("aria-checked", virtualSoundcheck ? "true" : "false");
    vsToggle.querySelector(".word").textContent = virtualSoundcheck ? "On" : "Off";
    vsPill.hidden = !virtualSoundcheck;
  }
  renderVirtualSoundcheck();
  const wcPanel = el("wc-panel");
  const suppressedFold = el("watch-suppressed");
  const suppressedList = el("watch-suppressed-list");
  const suppressedCount = el("watch-suppressed-count");
  const watchAbout = el("watch-about");
  const watchAboutLine = el("watch-about-line");

  // ---- The console: the bundle bar's, read-only here -------------------
  //
  // One address on the page, and it is the bar's -- resolved at startup
  // from ATOO_CONSOLE / ~/.atoo.config [console] or set
  // in the bar since. The rule still binds: a value nobody typed on
  // this form must say where it came from, so #console-origin names the
  // provenance exactly as the bar does ("from ...", or "set here").
  //
  // What a live watch is reading is named on its pill, and does not move
  // when the bar does: changing the address does not quietly re-point a
  // running watch. The origin line says so until it is restarted.

  const BUILTIN_CONSOLE_TIMEOUT = 1.0;
  let watchingConsole = null;   // "address:port" of a live-console watch, or null

  function barConsole() {
    // `window.Atoo.console()` hands out a copy of the shell's ONE
    // console. No shell, or a shell that sent nothing: nothing to watch
    // but the demo. Every key read below is tested for presence first --
    // the silently-blank trap (`esc()` renders undefined as an empty string).
    if (!SP || typeof SP.console !== "function") return {};
    return SP.console() || {};
  }

  // Must match webui.DEMO_CONSOLE_LABEL -- the label a Demo watch runs
  // under, and what the bar shows.
  const DEMO_LABEL = "Demo";

  function barLabel(desk) {
    return desk && desk.address ? desk.address + ":" + (desk.port || 2223) : "";
  }

  function makeCode(text) {
    const code = document.createElement("code");
    code.textContent = text;
    return code;
  }

  // Which console Start will watch, in words -- and NOT its address, which
  // the bar already shows (no need to
  // repeat the IP address). Demo is the bar's choice too: Watch follows
  // the bar, so there is no Source picker here.
  function renderWatchConsole() {
    const desk = barConsole();
    const label = barLabel(desk);
    const parts = [];
    if (desk.demo) {
      parts.push("Watches Demo: a built-in WING Compact rig whose issues come and go at " +
                 "random, against the demo show's watch.json -- no console needed. Choose a " +
                 "console address in the bundle bar (Console: Change…) to leave the demo " +
                 "and watch a real desk.");
    } else if (!label) {
      parts.push("No console -- choose an address in the bundle bar above (Console: " +
                 "Change…), then Start watching. Demo, in the same dialog, opens the demo show.");
    } else {
      parts.push("Watches the console in the bundle bar. Change it there.");
      const timeout = Number(desk.timeout);
      if (desk.timeout != null && Number.isFinite(timeout) && timeout !== BUILTIN_CONSOLE_TIMEOUT) {
        parts.push(" Timeout ", makeCode(timeout + "s"),
                   desk.timeout_source ? " from " + desk.timeout_source + "." : ".");
      }
    }
    // A running watch does not follow the bar: say so when they differ.
    if (watchingConsole && watchingConsole !== (desk.demo ? DEMO_LABEL : label)) {
      parts.push(" The watch running now is still reading ", makeCode(watchingConsole),
                 " -- Stop, then Start watching, to watch " + (desk.demo ? "Demo" : "the bar's console") +
                 ".");
    }
    consoleOrigin.textContent = "";
    for (const part of parts) {
      consoleOrigin.appendChild(typeof part === "string" ? document.createTextNode(part) : part);
    }
    consoleOrigin.hidden = false;
  }

  if (SP && typeof SP.onConsoleChange === "function") {
    SP.onConsoleChange(() => { renderWatchConsole(); renderAboutLine(); renderStartLock(); });
  }

  // Findings currently shown, keyed the same way atoo.watch does
  // (rule_id + addresses) -- a finding disappearing from a later event's
  // all_findings is exactly "the operator fixed it," and removing its row
  // is the whole point of this table (never a manual dismiss).
  let shown = new Map();
  // The <tr> for each key in `shown`, indexed the same way. A plain Map
  // lookup, not `alertBody.querySelector('tr[data-key="' + key + '"]')` --
  // a finding key can contain characters (`/`, `,`, `|`) that aren't valid
  // inside a CSS attribute-selector value unescaped, and escaping the
  // selector without also escaping what's stored in `dataset.key` (a past
  // bug here) means the lookup silently never matches: every finding gets
  // re-added as a brand-new row instead of reusing/removing its existing
  // one, so the table only ever grows and cleared findings never leave.
  let rowEls = new Map();
  let ws = null;
  // What the server last said about the session: null until it has
  // said anything, then true or false. Set from `/api/status`, the
  // socket's status frames, and this page's own Start and Stop.
  let serverRunning = null;
  let wsRetryMs = 1000;

  // The severity is part of the key: the same rule at another grade (C004
  // at INFO under Virtual soundcheck, a warning once it is off) is the old
  // row cleared and a new one, as the server counts it (`watch.finding_key`).
  function findingKey(f) {
    return f.rule_id + "|" + f.addresses.join(",") + "|" + f.severity;
  }

  // ---- Suppression ----------------------------------------
  //
  // An engineer can suppress either all Warnings or all
  // Infos by clicking on their findings, and individual findings on the
  // Watch page by checking a box, as on the build page's findings panel.
  //
  // Two ways to hide a row, both held by this page only (nothing reaches
  // the server or the desk), and both for the watch session -- Start
  // clears them, as it clears the table. The Build dock's "Mark
  // addressed" is the same: a flag on the finding in memory, gone on the
  // next run.
  //
  //   hiddenSevs   the Warning or Info count pill, clicked. Never Error:
  //                an error is a setting that cannot work, and hiding
  //                every one at once is unsafe. (To allow it, add "error"
  //                to SUPPRESSIBLE_SEVS and make its pill a button.)
  //   suppressed   one finding's box, ticked; keyed by findingKey (rule id
  //                + addresses), so it stays hidden while the same fault
  //                stands. When that fault CLEARS its suppression goes with
  //                it: if it comes back it is a new finding, shown, counted
  //                and flashed like any other -- the safer choice on a show.
  //
  // A hidden finding is in no count but its pill's "(n hidden)", tints
  // nothing, sets no page state, and never flashes.
  const SUPPRESSIBLE_SEVS = ["warning", "info"];
  const hiddenSevs = new Set();
  const suppressed = new Set();

  function isHidden(f) {
    return hiddenSevs.has(f.severity) || suppressed.has(findingKey(f));
  }

  function setSuppressed(f, on) {
    const key = findingKey(f);
    if (on) suppressed.add(key);
    else suppressed.delete(key);
    renderTable();
    updateCounts();
  }

  // The fold below the table: each finding hidden by its row's Hide
  // button, with a Show button in its place to bring the row back.
  function renderSuppressed() {
    if (!suppressedFold) return;
    const items = Array.from(shown.values()).filter((f) => suppressed.has(findingKey(f)));
    items.sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9));
    // The count is the block's notation (§3), not in brackets.
    suppressedCount.textContent = String(items.length);
    suppressedFold.hidden = items.length === 0;
    suppressedList.textContent = "";
    for (const f of items) {
      const parts = splitFinding(f);
      const li = document.createElement("li");
      li.className = "watch-suppressed-item";
      li.dataset.sev = SEVERITY_ORDER[f.severity] !== undefined ? f.severity : "info";
      const badge = document.createElement("span");
      badge.className = "sev sev-" + f.severity;
      badge.textContent = SEVERITY_LABEL[f.severity] || f.severity;
      li.appendChild(badge);
      const where = document.createElement("b");
      where.textContent = parts.where ? parts.where + ":" : "\u2014";
      li.appendChild(where);
      li.appendChild(document.createTextNode(" " + (parts.claim || "")));
      li.appendChild(makeHideButton(f, true));
      li.appendChild(makeCode(f.rule_id));
      suppressedList.appendChild(li);
    }
  }

  // The row's Hide button, and the fold's Show: a quiet button (the guide's
  // §4), labelled in words, with the finding named in its accessible label
  // so a list of them is not twelve buttons called "Hide".
  function makeHideButton(f, hidden) {
    const parts = splitFinding(f);
    const what = joinWhere(parts.where, parts.claim) || f.rule_id;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-quiet watch-row-hide";
    btn.textContent = hidden ? "Show" : "Hide";
    btn.title = hidden ? "Show this finding again"
                       : "Hide this finding on this page while it stands; the desk is not touched";
    btn.setAttribute("aria-label", (hidden ? "Show again: " : "Hide: ") + what);
    btn.addEventListener("click", () => {
      // Hiding moves the row out of the table, so this button goes with it:
      // keep keyboard focus on the next row's button rather than <body>.
      const row = btn.closest("tr, li");
      const next = row && (row.nextElementSibling || row.previousElementSibling);
      setSuppressed(f, !hidden);
      const target = next && next.isConnected ? next.querySelector(".watch-row-hide") : null;
      if (target) target.focus();
    });
    return btn;
  }

  for (const sev of SUPPRESSIBLE_SEVS) {
    const pill = document.querySelector('.count-pill[data-sev="' + sev + '"]');
    if (!pill) continue;
    pill.addEventListener("click", () => {
      if (hiddenSevs.has(sev)) hiddenSevs.delete(sev);
      else hiddenSevs.add(sev);
      renderTable();
      updateCounts();
    });
  }

  function setMessage(text) {
    if (!text) {
      panelMessage.hidden = true;
      panelMessage.textContent = "";
    } else {
      panelMessage.hidden = false;
      panelMessage.textContent = text;
    }
  }

  // What the running watch reads ("Demo", or "address:port"), kept so a
  // live event -- which carries no label -- does not wipe it off the pill.
  let watchingLabel = "";
  // The pill's state, so it can be redrawn when only the bar's console
  // changes: idle reads "Demo ready" beside a chosen Demo, and "Not
  // connected" otherwise.
  let connState = "idle";

  // The connection is a state tag. Watching
  // is good and live -- green, its dot pulsing; not connected is neutral;
  // an error is red, and what the server said goes under the verdict in
  // words, since a tag holds a state word, not a sentence.
  function setConnPill(state, label) {
    connState = state;
    connPill.className = "state";
    connPill.title = "";
    if (state === "watching") {
      if (label) watchingLabel = label;
      connPill.classList.add("is-ok", "is-live");
      connPill.textContent = ("Watching " + (label || watchingLabel)).trim();
    } else if (state === "error") {
      connPill.classList.add("is-err");
      connPill.textContent = "Error";
      connPill.title = label || "";
      if (label) setMessage(label);
    } else {
      connPill.textContent = idlePillText();
    }
    renderConsoleNote();
  }

  // The header's notation: which console this watch reads -- the running
  // watch's own while it runs (it does not follow the bar), the bar's
  // otherwise.
  function idlePillText() {
    return barConsole().demo ? "Demo ready" : "Not connected";
  }

  function renderConsoleNote() {
    if (!consoleNote) return;
    if (connState === "idle") connPill.textContent = idlePillText();
    const desk = barConsole();
    let text;
    if (serverRunning && watchingLabel) text = watchingLabel === DEMO_LABEL ? "Demo rig" : watchingLabel;
    else if (desk.demo) text = "Demo rig";
    else text = barLabel(desk) || "No console";
    consoleNote.textContent = text;
  }

  // Start, by the UI style rules: a button that would do nothing is locked,
  // with the reason beside it. With no console in the bar (and no Demo)
  // there is nothing to watch -- it used to be a live brass
  // button on the empty page. While a watch runs Stop is the action, and
  // the Watching state says why Start is not.
  let startPending = false;
  function startLockReason() {
    const desk = barConsole();
    if (!desk.demo && !barLabel(desk)) return "no console. Choose one in the bar";
    return "";
  }

  function renderStartLock() {
    const running = serverRunning === true || lastRunning === true;
    const reason = running ? "" : startLockReason();
    startBtn.disabled = running || startPending || !!reason;
    startLock.textContent = reason;
    startLock.hidden = !reason;
    // No visible text for the running case (the Watching state says it);
    // the title is for hover and assistive technology.
    if (running) startBtn.title = "Locked: already watching";
    else if (reason) startBtn.title = "Locked: " + reason;
    else startBtn.removeAttribute("title");
    renderConsoleNote();
    renderEmptyState();
  }

  // While a watch runs, the editor and the session details fold to one
  // line each below the table; on Stop they open again. Only on a
  // change, so a fold opened by hand mid-show stays open.
  let lastRunning = null;
  function setRunningUI(running) {
    stopBtn.disabled = !running;
    if (running) stopBtn.removeAttribute("title");
    else stopBtn.title = "Locked: not watching";
    intervalInput.disabled = running;
    if (running !== lastRunning) {
      lastRunning = running;
      wcPanel.open = !running;
      watchAbout.open = !running;
    }
    renderStartLock();
    renderStatus();
  }

  function relativeTime(iso) {
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    return ageText(Date.now() - then);
  }

  function ageText(ms) {
    const seconds = Math.max(0, Math.round(ms / 1000));
    if (seconds < 5) return "just now";
    if (seconds < 60) return seconds + "s ago";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return minutes + "m ago";
    return Math.round(minutes / 60) + "h ago";
  }

  // The counts are what the table shows; what is hidden (by its box or
  // by its pill) is beside them: "4 Warning (2 hidden)".
  function updateCounts() {
    const counts = { error: 0, warning: 0, info: 0 };
    const hidden = { error: 0, warning: 0, info: 0 };
    for (const f of shown.values()) {
      if (counts[f.severity] === undefined) continue;
      if (isHidden(f)) hidden[f.severity] += 1;
      else counts[f.severity] += 1;
    }
    for (const sev of Object.keys(counts)) {
      const pill = document.querySelector('.count-pill[data-sev="' + sev + '"]');
      pill.querySelector(".count-num").textContent = counts[sev];
      pill.classList.toggle("has-count", counts[sev] > 0);
      pill.classList.toggle("has-hidden", hidden[sev] > 0);
      const note = pill.querySelector(".count-hidden");
      if (note) {
        note.hidden = hidden[sev] === 0;
        note.textContent = hidden[sev] ? " (" + hidden[sev] + " hidden)" : "";
      }
      if (SUPPRESSIBLE_SEVS.includes(sev)) {
        const off = hiddenSevs.has(sev);
        const word = SEVERITY_LABEL[sev].toLowerCase();
        pill.classList.toggle("is-suppressed", off);
        pill.setAttribute("aria-pressed", off ? "true" : "false");
        pill.title = off
          ? "Every " + word + " is hidden -- click to show them again"
          : "Click to hide every " + word + "; click again to show them";
      }
    }
    renderSuppressed();
    renderStatus();
  }

  // A built-in finding about the same strip and field as one
  // of the engineer's own conditions is folded under the condition's row
  // (`watch.present_findings`) and named under its claim, from `also`.
  // Each row leads with the strip ("Where", sent by the server
  // as `strip`: `CH 6 "Bass DI"`) and the claim. A built-in's claim is its
  // title; an engineer's condition's title is its description, so its
  // claim is what the reading says -- the detail, which reads
  // `<strip> <what it reads> -- <description>`, with the strip and the
  // description taken off. Both are known values, not guessed at.
  //
  // The claim of a built-in finding is its catalogue title, which is Title
  // Case ("Main Not Patched"); the engineer's conditions say "has its fader
  // at -144 dB". Watch reads both as one sentence after the strip, so the
  // title is sentence-cased here -- in Watch only; the catalogue is
  // unchanged everywhere else.
  function sentenceCase(title) {
    return String(title == null ? "" : title).replace(/[A-Za-z0-9'\u2019]+/g, (word, at) => {
      // The first word keeps its capital; an acronym or a word with a digit
      // (DCA, FX, AES50, OK) is a name and stays as it is.
      if (at === 0 || word === word.toUpperCase()) return word;
      return word.charAt(0).toLowerCase() + word.slice(1);
    });
  }

  // "<where>: <claim>", or the claim alone when the finding has no strip.
  function joinWhere(where, claim) {
    return where && claim ? where + ": " + claim : (where || claim || "");
  }

  function splitFinding(f) {
    const where = f.strip || "";
    const detail = f.detail || "";
    if (String(f.rule_id).startsWith("WATCH:")) {
      let claim = detail;
      if (where && claim.startsWith(where + " ")) claim = claim.slice(where.length + 1);
      const tail = " -- " + (f.title || "");
      if (f.title && claim.endsWith(tail)) claim = claim.slice(0, -tail.length);
      return { where, claim, why: f.title };
    }
    return { where, claim: sentenceCase(f.title), why: detail };
  }

  function findingHtml(f) {
    const parts = splitFinding(f);
    let html = '<span class="row-claim">' + escapeHtml(parts.claim) + "</span>" +
      '<span class="row-why">' + escapeHtml(parts.why) + "</span>";
    for (const g of f.also || []) {
      html += '<span class="finding-also">Also <code>' + escapeHtml(g.rule_id) + "</code> " +
        escapeHtml(sentenceCase(g.title)) + ": " + escapeHtml(g.detail) + "</span>";
    }
    return html;
  }

  // In this table, and only here, the
  // severity tag is the large solid, to be read across the room. An info
  // has no solid: it keeps its tint, so a row of notes stays calm. The
  // rule id is a readout.
  function rowHtml(f) {
    const sevLabel = SEVERITY_LABEL[f.severity] || f.severity;
    const parts = splitFinding(f);
    const solid = f.severity === "error" || f.severity === "warning" ? " solid" : "";
    return (
      '<td class="col-sev"><div class="sev-cell"><span class="sev big' + solid + " sev-" + f.severity + '">' + sevLabel + "</span></div></td>" +
      '<td class="col-where"><span class="row-where">' + escapeHtml(parts.where || "\u2014") + "</span></td>" +
      '<td class="col-title">' + findingHtml(f) + "</td>" +
      '<td class="col-rule"><span class="readout">' + escapeHtml(f.rule_id) + '</span><span class="row-cat">' +
        escapeHtml(f.category) + "</span></td>" +
      '<td class="col-since">' + relativeTime(f._since) + "</td>"
    );
  }

  // Notes about the session itself -- which strip a scoped
  // name resolved to at Start, a condition that is not watched, names
  // refreshed rather than read every pass -- are a status line under the
  // Watch header, not rows in the alert table, which holds what is wrong
  // on the desk. Each note's short form (`summary`) is grouped under its
  // `group`: "Resolved at Start: DCA Band → DCA 1, MAIN PA → MAIN 1". A
  // warning (a condition that is not watched) keeps its badge and comes
  // first; the full sentences are under Details. Redrawn from every
  // event, so a condition saved mid-watch brings its note with it.
  let watchNotesOpen = false;
  let lastNotes = [];

  // The "This watch" fold's one line -- what it reads,
  // the notes in short, and the baseline. A warning note (a condition
  // not watched) keeps its badge here too.
  function renderAboutLine() {
    if (!watchAboutLine) return;
    watchAboutLine.textContent = "";
    const desk = barConsole();
    const parts = [];
    if (watchingLabel && serverRunning) parts.push("Reading " + watchingLabel);
    else parts.push(desk.demo ? "Demo rig" : (barLabel(desk) ? "Console " + barLabel(desk) : "No console chosen"));
    const warned = lastNotes.filter(n => n.severity === "warning" || n.severity === "error");
    const groups = new Map();
    for (const n of lastNotes) {
      if (warned.includes(n)) continue;
      const name = n.group || "Note";
      if (!groups.has(name)) groups.set(name, []);
      const item = n.summary || n.detail || "";
      if (!groups.get(name).includes(item)) groups.get(name).push(item);
    }
    for (const [name, items] of groups) parts.push(name + ": " + items.join(", "));
    if (!baselineNote.hidden && baselineNote.textContent) parts.push(baselineNote.textContent);
    if (warned.length) {
      const badge = document.createElement("span");
      badge.className = "sev sev-warning";
      badge.textContent = warned.length + " not watched";
      watchAboutLine.appendChild(badge);
    }
    watchAboutLine.appendChild(document.createTextNode(parts.join(" \u00b7 ")));
  }

  function renderNotes(notes) {
    watchNotes.textContent = "";
    lastNotes = notes;
    if (!notes.length) {
      watchNotes.hidden = true;
      renderAboutLine();
      return;
    }
    const groups = new Map();
    for (const n of notes) {
      const severity = SEVERITY_ORDER[n.severity] !== undefined ? n.severity : "info";
      const name = n.group || "Note";
      const key = severity + "|" + name;
      if (!groups.has(key)) groups.set(key, { severity, name, items: [] });
      const item = n.summary || n.detail || "";
      if (!groups.get(key).items.includes(item)) groups.get(key).items.push(item);
    }
    const ordered = Array.from(groups.values()).sort(
      (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
    const line = document.createElement("div");
    line.className = "watch-notes-line";
    for (const g of ordered) {
      const part = document.createElement("span");
      part.className = "watch-note watch-note-" + g.severity;
      if (g.severity !== "info") {
        const badge = document.createElement("span");
        badge.className = "sev sev-" + g.severity;
        badge.textContent = SEVERITY_LABEL[g.severity];
        part.appendChild(badge);
        part.appendChild(document.createTextNode(" "));
      }
      const label = document.createElement("strong");
      label.textContent = g.name + ":";
      part.appendChild(label);
      part.appendChild(document.createTextNode(" " + g.items.join(", ")));
      line.appendChild(part);
    }
    watchNotes.appendChild(line);

    const more = document.createElement("details");
    more.className = "watch-notes-more";
    const summary = document.createElement("summary");
    summary.textContent = "Details";
    more.appendChild(summary);
    const list = document.createElement("ul");
    const seen = new Set();
    for (const n of notes) {
      if (seen.has(n.detail)) continue;
      seen.add(n.detail);
      const li = document.createElement("li");
      li.appendChild(makeCode(n.rule_id || ""));
      li.appendChild(document.createTextNode(" " + (n.detail || "")));
      list.appendChild(li);
    }
    more.appendChild(list);
    // Redrawn every reading: keep Details open once someone opened it.
    more.open = watchNotesOpen;
    more.addEventListener("toggle", () => { watchNotesOpen = more.open; });
    watchNotes.appendChild(more);
    watchNotes.hidden = false;
    renderAboutLine();
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  // The sentence under an empty table. It depends on whether Start is live,
  // which follows the bundle bar's console, so it is drawn again when that
  // changes and not only with the table.
  function renderEmptyState() {
    if (tableEmpty) {
      const hiddenNow = Array.from(shown.values()).filter(isHidden).length;
      emptyState.textContent = !shown.__watchedOnce
        ? (startLockReason() ? "Not watching yet. Choose a console in the bar, then Start watching."
          : "Not watching yet. Press Start watching.")
        : hiddenNow
          ? "Nothing shown: " + hiddenNow + " finding(s) hidden. Click a struck-through " +
            "count above, or choose Show on one under Suppressed, to show them."
          : "";
    }
    emptyState.hidden = !tableEmpty || !emptyState.textContent;
  }

  function renderTable() {
    // Errors first, then warnings, then info, and
    // within a severity the newest finding at the top. Every render puts
    // every row back in this order (below), so a finding that arrives
    // later never lands at the bottom of the table.
    // A hidden row leaves the table; showing it again draws
    // it afresh, without the new-row light.
    for (const [key, tr] of rowEls) {
      const f = shown.get(key);
      if (f && isHidden(f)) {
        tr.remove();
        rowEls.delete(key);
      }
    }
    for (const f of shown.values()) if (isHidden(f)) f._isNew = false;
    const rows = Array.from(shown.values()).filter((f) => !isHidden(f)).sort((a, b) => {
      const sa = SEVERITY_ORDER[a.severity] ?? 9;
      const sb = SEVERITY_ORDER[b.severity] ?? 9;
      if (sa !== sb) return sa - sb;
      const ta = Date.parse(a._since) || 0;
      const tb = Date.parse(b._since) || 0;
      if (ta !== tb) return tb - ta;
      return a.rule_id.localeCompare(b.rule_id);
    });

    // The one centred empty state. With
    // nothing in the table its head goes too; a watch with nothing wrong
    // says so in the verdict bar (ALL OK), so the sentence is only for
    // before Start, and for rows that are all hidden.
    tableEmpty = rows.length === 0 && alertBody.children.length === 0;
    if (alertHead) alertHead.hidden = tableEmpty;
    renderEmptyState();

    for (const f of rows) {
      const key = findingKey(f);
      let tr = rowEls.get(key);
      if (!tr) {
        tr = document.createElement("tr");
        tr.dataset.key = key;
        tr.className = "sev-row-" + f.severity;
        tr.innerHTML = rowHtml(f);
        tr.querySelector(".sev-cell").appendChild(makeHideButton(f, false));
        if (f._isNew) {
          f._isNew = false;
          tr.classList.add("row-new");
          tr.addEventListener("animationend", () => tr.classList.remove("row-new"), { once: true });
        }
        rowEls.set(key, tr);
      } else {
        tr.querySelector(".col-since").textContent = relativeTime(f._since);
        // The same fault, read again: say what it says now -- a fader
        // still too low reads its current level, and a built-in folding
        // under it, or leaving it, shows here.
        const cell = tr.querySelector(".col-title");
        const detail = findingHtml(f);
        if (cell.innerHTML !== detail) cell.innerHTML = detail;
      }
      // appendChild moves an existing row, so appending in sorted order
      // re-orders the whole table. A row fading out (clearRow) is no
      // longer in rowEls and is left where it is until it goes.
      alertBody.appendChild(tr);
    }
  }

  function clearRow(f) {
    const key = findingKey(f);
    const tr = rowEls.get(key);
    if (!tr) return;
    // Untracked immediately -- if this same key comes back as a new
    // finding before the fade-out below finishes, renderTable() must not
    // find this (departing) element and mistake it for still-current.
    rowEls.delete(key);
    // The row used to fade with `transform: scaleY(0)`, which
    // does not give a table row's height back -- it went blank and kept
    // its space for most of a second, and the live rows jumped when it
    // finally went. Now each cell's contents fade and collapse together
    // (a wrapper whose max-height runs from its own height to 0, while
    // the cell's padding goes to 0), so the row closes up as it fades and
    // nothing blank holds space. Rows still clear themselves; there is no
    // dismiss button.
    const wraps = [];
    for (const td of Array.from(tr.cells)) {
      const wrap = document.createElement("div");
      wrap.className = "cell-collapse";
      while (td.firstChild) wrap.appendChild(td.firstChild);
      td.appendChild(wrap);
      wraps.push(wrap);
    }
    for (const wrap of wraps) wrap.style.maxHeight = wrap.scrollHeight + "px";
    void tr.offsetHeight;   // commit the starting heights before collapsing
    tr.classList.add("row-clearing");
    for (const wrap of wraps) wrap.style.maxHeight = "0px";
    let gone = false;
    const remove = () => {
      if (gone) return;
      gone = true;
      tr.remove();
      // Redraw for the empty state: the last row out leaves "No
      // findings", not whatever the empty-state line said before.
      renderTable();
    };
    tr.addEventListener("transitionend", (evt) => {
      if (evt.propertyName === "max-height") remove();
    });
    // Fallback in case the transition never fires (hidden tab, reduced
    // motion, etc.)
    setTimeout(remove, 500);
  }

  function tick() {
    for (const [key, tr] of rowEls) {
      const f = shown.get(key);
      if (f) tr.querySelector(".col-since").textContent = relativeTime(f._since);
    }
  }
  setInterval(tick, 15000);

  // ---- "Updated ..." ages, and says so when readings stop --
  //
  // The label used to be written once per reading, so it always read
  // "Updated just now" -- and kept saying so when readings stopped (a
  // desk that stops answering mid-read, a slow per-leaf pass, a wedged
  // server). A table that stopped updating three minutes ago then looked
  // exactly like a quiet, healthy desk. Now it is redrawn every second
  // from the time of the last reading, and once a running watch has gone
  // STALE_READINGS intervals (and at least STALE_MIN_SECONDS) without one,
  // it turns into a warning: "No reading for 45s".
  //
  // The reading's time is the server's (`payload.at`), not when this page
  // received it: on reconnect the server replays its last reading, and a
  // replay must not look fresh. The server's clock and this device's may
  // differ (a tablet on the venue network), so the offset is learned as
  // the smallest receipt-minus-reading gap seen -- network delay plus
  // skew -- and the reading's time is moved onto this device's clock.
  const STALE_READINGS = 4;
  const STALE_MIN_SECONDS = 30;
  let lastReadingAt = null;    // ms on this device's clock, or null
  let clockOffset = null;      // ms: this device minus the server, at best
  let waitingSince = null;     // ms: Start pressed (or page opened on a running watch)

  function noteReading(at) {
    const then = Date.parse(at);
    if (Number.isNaN(then)) {
      lastReadingAt = Date.now();
      return;
    }
    const offset = Date.now() - then;
    clockOffset = clockOffset === null ? offset : Math.min(clockOffset, offset);
    lastReadingAt = then + clockOffset;
  }

  function staleAfterMs() {
    const interval = parseFloat(intervalInput.value) || 2;
    return Math.max(STALE_MIN_SECONDS, STALE_READINGS * interval) * 1000;
  }

  function durationText(ms) {
    const seconds = Math.max(0, Math.floor(ms / 1000));
    if (seconds < 60) return seconds + "s";
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + "m " + (seconds % 60) + "s";
    return Math.floor(minutes / 60) + "h " + (minutes % 60) + "m";
  }

  function renderLastUpdated() {
    const since = lastReadingAt !== null ? lastReadingAt : waitingSince;
    const silent = since === null ? 0 : Date.now() - since;
    const stale = serverRunning === true && since !== null && silent >= staleAfterMs();
    const wasStale = lastUpdated.classList.contains("is-stale");
    // Meta type while readings arrive; a warning state (§6)
    // once they stop.
    lastUpdated.className = stale ? "state is-warn" : "meta";
    lastUpdated.classList.toggle("is-stale", stale);
    if (stale) {
      lastUpdated.textContent = "No reading for " + durationText(silent);
      lastUpdated.title = lastReadingAt !== null
        ? "The last reading arrived at " + new Date(lastReadingAt).toLocaleTimeString() +
          ". The desk may have stopped answering, or the watch has stalled: " +
          "the table shows what was true then."
        : "Watching started, but no reading has arrived yet.";
    } else if (lastReadingAt !== null) {
      lastUpdated.textContent = "Updated " + ageText(silent);
      lastUpdated.title = "";
    } else if (wasStale) {
      // Stopped while still waiting for a first reading.
      lastUpdated.textContent = "";
      lastUpdated.title = "";
    }
    // No reading yet and nothing to warn about: the label keeps what the
    // page or Start put there (the placeholder dash, or blank).
    renderStatus();
  }
  setInterval(renderLastUpdated, 1000);

  // A stopped watch's "Updated 1m ago" is about the show and console it
  // read. Opening another show, or changing the console, makes it a claim
  // about something no longer on the screen, so it goes. A running watch
  // keeps its label: it is still reading what it was started on.
  function forgetStoppedReading() {
    if (serverRunning === true) return;
    lastReadingAt = null;
    waitingSince = null;
    lastUpdated.className = "meta";
    lastUpdated.textContent = "";
    lastUpdated.title = "";
    renderStatus();
  }
  if (SP && typeof SP.onBundleChange === "function") SP.onBundleChange(forgetStoppedReading);
  if (SP && typeof SP.onConsoleChange === "function") SP.onConsoleChange(forgetStoppedReading);

  // ---- The screen's state --------------------------------
  //
  // A glance at the screen tells "everything is OK
  // on the desk" from "something needs attention" -- by how it looks, not
  // by a label. The rows carry it (tinted and barred in their severity's
  // colour); the page carries one state, `body[data-watch-worst]`: none or
  // info (calm), warning, error; idle and starting (neutral); stale (no
  // reading for a while -- the table greys out, never calm).
  function renderStatus() {
    const counts = { error: 0, warning: 0, info: 0 };
    for (const f of shown.values()) {
      if (counts[f.severity] !== undefined && !isHidden(f)) counts[f.severity] += 1;
    }
    let worst;
    if (serverRunning !== true) worst = "idle";
    else if (lastUpdated.classList.contains("is-stale")) worst = "stale";
    else if (lastReadingAt === null) worst = "starting";
    else if (counts.error) worst = "error";
    else if (counts.warning) worst = "warning";
    else worst = counts.info ? "info" : "none";
    document.body.dataset.watchWorst = worst;
    renderVerdict(worst);
  }

  // ---- The verdict bar ------------------
  //
  // Communicate 'All OK' or 'Trouble' at a
  // glance. One word at the head of the table, in the severity's colour:
  // TROUBLE with any error, WARNING with warnings only, ALL OK with
  // neither (an info is a note, not trouble); NOT WATCHING, grey, before
  // Start. Then the first open finding, in words. Two states the drawing
  // has no word for are said in grey rather than guessed at: STARTING
  // before the first reading, and NO READING when readings have stopped
  // -- the table then shows how the desk WAS, so it must not read as ALL
  // OK.
  const VERDICT = {
    error: ["is-trouble", "Trouble"],
    warning: ["is-warn", "Warning"],
    info: ["is-ok", "All OK"],
    none: ["is-ok", "All OK"],
    idle: ["", "Not watching"],
    starting: ["", "Starting"],
    stale: ["", "No reading"],
  };

  function firstOpenFinding() {
    let best = null;
    for (const f of shown.values()) {
      if (isHidden(f) || SEVERITY_ORDER[f.severity] === undefined) continue;
      if (!best) { best = f; continue; }
      const a = SEVERITY_ORDER[f.severity], b = SEVERITY_ORDER[best.severity];
      if (a < b || (a === b && (Date.parse(f._since) || 0) > (Date.parse(best._since) || 0))) best = f;
    }
    return best;
  }

  function renderVerdict(worst) {
    if (!verdictBar) return;
    const [cls, word] = VERDICT[worst] || VERDICT.idle;
    verdictBar.className = "verdict-bar" + (cls ? " " + cls : "");
    verdictBar.dataset.verdict = worst;
    verdictWord.textContent = word;
    let line = "";
    if (worst === "error" || worst === "warning") {
      const f = firstOpenFinding();
      if (f) {
        const parts = splitFinding(f);
        line = joinWhere(parts.where, parts.claim);
      }
    } else if (worst === "none" || worst === "info") {
      line = "Nothing on this desk is out of place.";
    } else if (worst === "starting") {
      line = "Waiting for the first reading.";
    } else if (worst === "stale") {
      line = "The table shows the desk as it was at the last reading.";
    }
    verdictLine.textContent = line;
    verdictLine.hidden = !line;
  }

  // "Flash on new": a new warning or error flashes the whole screen once
  // in its colour (~0.4s). Never for an info, and never again for a
  // finding that is still standing -- only `new_findings` trigger it.
  // Reduced motion: a steady edge glow for a few seconds instead.
  function flashScreen(sev) {
    if (!flashOn) return;
    watchFlash.dataset.sev = sev;
    watchFlash.classList.remove("is-flashing");
    void watchFlash.offsetWidth;
    watchFlash.classList.add("is-flashing");
    const reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Reduced motion: the steady glow stays a few seconds, then goes.
    clearTimeout(flashScreen.timer);
    flashScreen.timer = setTimeout(() => watchFlash.classList.remove("is-flashing"), reduced ? 4000 : 600);
  }

  function handleEvent(payload) {
    shown.__watchedOnce = true;
    const now = new Date().toISOString();

    // Since R002/R005 stand down on a read that never
    // saw the output patch, a shorter list here is no longer necessarily
    // a healthier desk -- so the page has to say which rules went
    // unanswered, on every event and not only at the baseline. Read with
    // `||` so an older server that sends no such key simply hides it
    // rather than printing "undefined".
    const caveat = payload.coverage_caveat || "";
    coverageNote.hidden = caveat === "";
    coverageNote.textContent = caveat;

    renderNotes(payload.notes || []);

    if (payload.baseline) {
      shown = new Map();
      shown.__watchedOnce = true;
      for (const f of payload.all_findings) {
        f._since = now;
        shown.set(findingKey(f), f);
      }
      if (payload.all_findings.length > 0) {
        baselineNote.hidden = false;
        baselineNote.textContent =
          payload.all_findings.length + " finding(s) already present when watching started (not new alerts).";
      } else {
        baselineNote.hidden = false;
        baselineNote.textContent = "No findings present at the start of this watch session.";
      }
      alertBody.innerHTML = "";
      rowEls = new Map();
      for (const key of Array.from(suppressed)) if (!shown.has(key)) suppressed.delete(key);
      renderTable();
    } else {
      for (const f of payload.new_findings) {
        f._since = now;
        f._isNew = true;
        shown.set(findingKey(f), f);
      }
      // A row already showing keeps its Since and takes this reading's
      // detail and folded findings; renderTable redraws its Detail cell.
      for (const f of payload.all_findings) {
        const known = shown.get(findingKey(f));
        if (known && known !== f) {
          known.detail = f.detail;
          known.also = f.also;
        }
      }
      renderTable();
      for (const f of payload.cleared_findings) {
        shown.delete(findingKey(f));
        // Cleared, so no longer suppressed: if it comes back it is new.
        suppressed.delete(findingKey(f));
        clearRow(f);
      }
    }

    updateCounts();
    noteReading(payload.at);
    renderLastUpdated();
    renderAboutLine();
    if (!payload.baseline) {
      const fresh = (payload.new_findings || []).filter(f => !isHidden(f)).map(f => f.severity);
      if (fresh.includes("error")) flashScreen("error");
      else if (fresh.includes("warning")) flashScreen("warning");
    }
  }

  // The server's word on the switch, for a running watch; and Off again once
  // a watch that was running has stopped. A choice made before Start is kept
  // until then.
  function adoptVirtualSoundcheck(status, wasRunning) {
    if (status.running) virtualSoundcheck = !!status.virtual_soundcheck;
    else if (wasRunning) virtualSoundcheck = false;
    renderVirtualSoundcheck();
  }

  vsToggle.addEventListener("click", async () => {
    const wanted = !virtualSoundcheck;
    virtualSoundcheck = wanted;
    renderVirtualSoundcheck();
    if (!serverRunning) return;  // chosen now, sent with Start
    vsToggle.disabled = true;
    try {
      const res = await fetch("/api/watch/virtual-soundcheck", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on: wanted }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        virtualSoundcheck = !wanted;
        setMessage(data.error || "Could not change Virtual soundcheck.");
      }
    } catch (e) {
      virtualSoundcheck = !wanted;
      setMessage("Could not reach the Atoo server.");
    } finally {
      vsToggle.disabled = false;
      renderVirtualSoundcheck();
    }
  });

  function connectWs() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + location.host + "/ws/watch");
    ws.onopen = () => {
      wsRetryMs = 1000;
      // A socket that reconnects is usually a server that restarted: ask
      // at once whether it is still the one that drew this page, rather
      // than waiting for the shell's next poll (the stale-page banner).
      if (SP && typeof SP.checkServer === "function") SP.checkServer();
    };
    ws.onmessage = (evt) => {
      const payload = JSON.parse(evt.data);
      if (payload.type === "status") {
        adoptVirtualSoundcheck(payload, serverRunning);
        serverRunning = !!payload.running;
        setRunningUI(payload.running);
        if (payload.running) setConnPill("watching", payload.label);
        else if (payload.error) setConnPill("error", payload.error);
        else setConnPill("idle");
      } else if (payload.type === "event") {
        // An event is not proof of a running session: the server says so
        // with a status frame on connect and on every Start and Stop.
        // While the last word was "not running", an event is a stale
        // replay -- it held Start disabled on Watching until Stop was
        // pressed (found while checking in Chromium).
        if (serverRunning === false) return;
        setRunningUI(true);
        setConnPill("watching", watchingLabel);
        handleEvent(payload);
      } else if (payload.type === "error") {
        virtualSoundcheck = false;
        renderVirtualSoundcheck();
        serverRunning = false;
        setRunningUI(false);
        setConnPill("error", payload.error);
        setMessage(payload.error);
      }
    };
    ws.onclose = () => {
      setTimeout(connectWs, wsRetryMs);
      wsRetryMs = Math.min(wsRetryMs * 2, 15000);
    };
  }

  async function refreshStatus() {
    try {
      const res = await fetch("/api/status");
      const status = await res.json();
      adoptVirtualSoundcheck(status, serverRunning);
      serverRunning = !!status.running;
      setRunningUI(status.running);
      // A live-console watch is labelled `address:port` by the server
      // and a Demo one "Demo", so a reload still knows which the running
      // watch reads.
      watchingConsole = status.running && (/:\d+$/.test(status.label || "")
        || status.label === DEMO_LABEL) ? status.label : null;
      renderWatchConsole();
      // A page opened on a watch already running counts its silence from
      // now until the first reading arrives (the server replays its last).
      if (status.running && lastReadingAt === null && waitingSince === null) {
        waitingSince = Date.now();
      }
      if (status.running) setConnPill("watching", status.label);
      else if (status.error) setConnPill("error", status.error);
      else setConnPill("idle");
    } catch (e) {
      // offline / server not up yet -- the WebSocket reconnect loop covers this
    }
  }

  startBtn.addEventListener("click", async () => {
    setMessage(null);
    // Watch follows the bar: Demo there is the demo rig here,
    // and the server knows it -- there is only one source.
    const desk = barConsole();
    const body = {
      source: "console",
      interval: parseFloat(intervalInput.value) || 2.0,
      virtual_soundcheck: virtualSoundcheck,
    };
    // No console, port or timeout in the body: the server watches the
    // bundle bar's console, with its port and timeout -- the same one
    // Ping, Apply, Patch and Undo use.
    const startingOn = desk.demo ? DEMO_LABEL : barLabel(desk);
    if (!startingOn) {
      setMessage("No console -- choose an address in the bundle bar above, or Demo to " +
                 "open the demo show.");
      return;
    }
    // Whatever watch-conditions path is currently in the
    // panel above (loaded, or just typed) rides along on Start -- the
    // server loads/validates it itself and folds its rules into the
    // session, the same way `atoo watch --watch-conditions` already
    // does on the CLI side.
    if (wcLoadedPath) body.watch_conditions_path = wcLoadedPath;
    startPending = true;
    renderStartLock();
    // The session's first event can beat both the server's status frame
    // and this fetch's answer to the socket.
    serverRunning = true;
    // Cleared BEFORE the request, not once it answers: the session's
    // first (baseline) event can reach the socket before this fetch
    // resolves, and clearing afterwards wiped it -- the table then showed
    // only what changed later, never what was already wrong at Start
    // (found while checking in Chromium).
    // When you start watching, existing findings
    // need to be deleted -- every trace of the last session goes: rows,
    // counts and the last-updated time.
    shown = new Map();
    alertBody.innerHTML = "";
    rowEls = new Map();
    // Suppressions are the session's: a new watch shows all.
    suppressed.clear();
    hiddenSevs.clear();
    baselineNote.hidden = true;
    coverageNote.hidden = true;
    renderNotes([]);
    lastUpdated.textContent = "";
    lastReadingAt = null;
    waitingSince = Date.now();
    renderTable();
    updateCounts();
    renderStatus();
    try {
      const res = await fetch("/api/watch/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setMessage(data.error || "Could not start watching.");
        serverRunning = false;
        waitingSince = null;
        startPending = false;
        renderStartLock();
        renderStatus();
        return;
      }
      startPending = false;
      setRunningUI(true);
      setConnPill("watching", data.label || "");
      watchingConsole = startingOn;
      renderWatchConsole();
    } catch (e) {
      setMessage("Could not reach the Atoo server.");
      serverRunning = false;
      waitingSince = null;
      startPending = false;
      renderStartLock();
      renderStatus();
    }
  });

  stopBtn.addEventListener("click", async () => {
    stopBtn.disabled = true;
    serverRunning = false;
    // Stopped: the label keeps ageing ("Updated 3m ago") but is no longer
    // a warning -- nothing is expected to arrive.
    waitingSince = null;
    renderLastUpdated();
    await fetch("/api/watch/stop", { method: "POST" });
    // The server forgets the switch at Stop; so does the page.
    virtualSoundcheck = false;
    renderVirtualSoundcheck();
    setRunningUI(false);
    setConnPill("idle");
    watchingConsole = null;
    renderWatchConsole();
  });

  renderWatchConsole();
  renderStartLock();
  refreshStatus();
  connectWs();
  renderTable();
  renderStatus();
  renderAboutLine();
  wcInit();
})();
