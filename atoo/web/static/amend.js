(() => {
  "use strict";

  // Patch, inside Apply (where a change is typed) -- loaded by the shell
  // before apply.js, and coded against `window.Atoo`.
  //
  // THIS FILE WRITES NOTHING AND ARMS NOTHING. It is a renderer: it draws
  // the review of one `atoo patch` run (a typed change) under Preview,
  // step 2, from the review the command itself wrote (`--review-json`, `amend.review_payload`) -- the
  // desk itself is drawn as scribble strips by apply.js, from the review's
  // `desk` -- the model call's progress while a change
  // compiles, and the bundle's journal stack (step 4, History) from `GET
  // /api/journals` -- a patch row by its change's short name and text.
  // Every POST that can reach a console -- apply, patch, undo -- is
  // apply.js's, behind its one arming checkbox. Patch lives inside Apply
  // precisely so that stays true: exactly one screen writes to
  // a console.
  //
  // Words: what is typed is a CHANGE. "Patch" in a
  // finding or a plan field means socket routing.
  //
  // Three rules this renderer keeps, all from the issue:
  //
  //   * UNKNOWN is not FREE. An unread strip is drawn hatched and dashed,
  //     with its own legend entry and its own line naming what did not
  //     answer. It is never offered as a place to put anything, and there
  //     is no click-to-open on the drawing: the strip to reuse is typed.
  //   * A strip's own name is not the whole truth. On a WING a name typed
  //     at the desk lands on the source SOCKET ("Podium" on LCL 20),
  //     so a strip whose own name is blank can be in use. Where the source
  //     carries the name, that is what is shown, and said to be the source.
  //   * A removal is not an addition. "Returned to free" CLEARS a strip on
  //     the desk; it is drawn in a colour of its own, listed address by
  //     address, and counted apart.
  //
  // It does not word the verdicts. `line` on each change, the occupancy
  // summary and the targets summary are the command's own sentences.

  const SP = window.Atoo;
  const el = (id) => document.getElementById(id);

  const KIND_LABEL = {
    added: "Added",
    released: "Returned to free",
    removed: "Removed, left alone",
    modified: "Modified, not written",
    edited: "Edited: named fields only",
    shifted: "Moved down by the insert",
    renumbered: "Refused: renumbered",
    unplaceable: "Refused: no free strip",
    refused: "Refused: cannot be written as asked",
  };

  const KIND_NOTE = {
    released: "Clears this strip on the desk: back on its factory input patch (or OFF -- " +
      "the INFO below says which, and why), name, color and icon cleared on the strip " +
      "AND its source socket, the processing this plan set undone, and its fader pulled to " +
      "-inf -- as an untouched strip reads -- before it is unmuted. A bus returned to free " +
      "reads as an initialized bus, and every send into it is switched off.",
    removed: "Dropped from the rebuild, but the desk no longer reads as the strip this " +
      "plan built (or did not answer) -- so it is reported and nothing on it is touched.",
    modified: "Already on the desk and running, and this part was not written: a running " +
      "object changes only in the fields a change names, and this one was restated whole, " +
      "said in words only, is a fader the change did not name, or is a DCA, mute group or " +
      "output the change drops (not yet built).",
    edited: "Already on the desk and running. Only the fields the change names are written " +
      "(listed below, old -> new); every other address of it is in the untouched proof.",
    refused: "The change asks for something the plan or the desk cannot take: an object " +
      "that is not there, a field a running object does not carry or a change may not set, " +
      "a value out of range, or a bus, DCA, mute group or channel that is neither on the " +
      "desk nor added by the change. The line says which. Nothing is written until it is " +
      "said again.",
  };

  function text(tag, cls, value) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    node.textContent = value == null ? "" : String(value);
    return node;
  }

  function patchText(patch) {
    return patch ? patch[0] + " " + patch[1] : "not patched";
  }

  // The lines under the drawing: one for every strip that is not ours and
  // not free -- the two states somebody has to read before trusting the
  // placement. The strips themselves are drawn by apply.js (`desk`).
  function renderStripNotes(review) {
    const notes = el("amend-strip-notes");
    notes.textContent = "";
    (review.occupancy || []).forEach((strip) => {
      if (strip.state === "theirs") {
        let where;
        if (strip.source_name && !strip.name) {
          where = "its own name is blank, but its source " + patchText(strip.patch) +
            " is named '" + strip.source_name + "' -- in use by somebody, whoever typed it";
        } else if (strip.name) {
          where = "named '" + strip.name + "'" +
            (strip.source_name ? " (source " + patchText(strip.patch) + ": '" +
              strip.source_name + "')" : "");
        } else {
          where = "patched to " + patchText(strip.patch) + ", which the desk did not ship with";
        }
        notes.appendChild(text("li", "is-theirs", strip.label + ": somebody else's -- " + where +
          ". Refused; nothing on it is read or written."));
      } else if (strip.state === "unknown") {
        notes.appendChild(text("li", "is-unknown", strip.label +
          ": never answered (" + (strip.unread || []).join(", ") + ") -- an unread strip " +
          "is not a free strip, so it is treated as OCCUPIED."));
      }
    });
    el("amend-occupancy-summary").textContent = review.occupancy_summary || "";
  }

  function renderChanges(review) {
    const box = el("amend-changes");
    box.textContent = "";
    const counts = {};
    let unchanged = 0;
    (review.changes || []).forEach((change) => {
      counts[change.kind] = (counts[change.kind] || 0) + 1;
      if (change.kind === "unchanged") {
        unchanged += 1;
        return;
      }
      const row = document.createElement("div");
      row.className = "amend-change kind-" + change.kind;
      row.dataset.kind = change.kind;
      row.appendChild(text("span", "amend-change-kind", KIND_LABEL[change.kind] || change.kind));
      // The command's own sentence, verbatim.
      row.appendChild(text("span", "amend-change-line", (change.line || "").trim()));
      if (KIND_NOTE[change.kind]) row.appendChild(text("span", "amend-change-note", KIND_NOTE[change.kind]));
      box.appendChild(row);
    });
    if (unchanged) {
      box.appendChild(text("p", "panel-note", unchanged + " object(s) unchanged -- already " +
        "applied and still running, so nothing is written to them."));
    }

    // The first line of `Amendment.summary()` is its own count line --
    // "3 added, 1 returned to free, 11 unchanged" -- the command's words.
    const headline = (review.amendment_summary || "").split("\n")[0];
    const head = el("amend-delta-headline");
    head.textContent = headline;
    head.classList.toggle("is-bad", !!review.blocked || !!(review.collisions || []).length);

    const infos = el("amend-infos");
    infos.textContent = "";
    // A change that names presets, with no library to take
    // their values from -- said first, as the command says it up top.
    if (review.preset_warning) {
      infos.appendChild(text("li", "is-warning", "WARNING " + review.preset_warning));
    }
    (review.infos || []).forEach((i) => infos.appendChild(text("li", "", "INFO " + i)));
    (review.warnings || []).concat(review.targets_warnings || [])
      .forEach((w) => infos.appendChild(text("li", "", "note: " + w)));

    // Each named field a change sets on something
    // already running, old -> new -- the command's own line. A physical
    // repatch (`moves_audio`) and a phantom switch (`switches_phantom`) are
    // drawn first and in the danger colour: each acts on the desk the
    // moment it is written.
    const isLive = (e) => !!(e.moves_audio || e.switches_phantom);
    const edits = (review.edits || []).slice().sort((a, b) =>
      (isLive(b) ? 1 : 0) - (isLive(a) ? 1 : 0));
    el("amend-edits").hidden = !edits.length;
    const ed = el("amend-edits-list");
    ed.textContent = "";
    edits.forEach((e) => ed.appendChild(text("li", isLive(e) ? "is-live" : "", e.line)));

    const releases = review.releases || [];
    el("amend-releases").hidden = !releases.length;
    const rl = el("amend-releases-list");
    rl.textContent = "";
    releases.forEach((r) => rl.appendChild(text("li", "", r.address + " -- " + r.description)));

    // `AmendmentTargets.summary()`'s first line: "N will be written; M
    // belonging to objects this amend does not own will NOT be."
    el("amend-targets-line").textContent = (review.targets_summary || "").split("\n")[0];

    const withheld = review.withheld || [];
    el("amend-withheld-count").textContent = withheld.length + " address(es), " +
      (review.withheld_groups || []).length + " object(s)";
    const groups = el("amend-withheld-groups");
    groups.textContent = "";
    (review.withheld_groups || []).forEach((g) => {
      // A readout (§6): data, not a tag.
      groups.appendChild(text("span", "readout", g.base + " " + g.count));
    });

    const proof = review.proof;
    el("amend-proof-line").textContent = proof ? proof.line : "";
  }

  // Apply's pre-flight, asked of the amend -- the verify of the
  // effective plan and the socket check over what this amend writes. A
  // refusal is the command's own text, verbatim; `review.blocked` is set
  // with it, which is what keeps the write from arming (apply.js).
  function renderPreflight(review) {
    const pre = review.preflight;
    const box = el("amend-preflight");
    box.hidden = !pre;
    if (!pre) return;
    let line;
    if (pre.refusal) line = "REFUSED -- nothing can be written. Checked against " + pre.where + ".";
    else if (pre.skip_verify) line = "--skip-verify: the amended plan was NOT verified. The " +
      "sockets this amend writes were checked against " + pre.where + ", and all exist.";
    else line = "Verified against " + pre.where + ", and every socket this amend writes " +
      "exists there.";
    const head = el("amend-preflight-line");
    head.textContent = line;
    head.classList.toggle("is-bad", !!pre.refusal);
    const refusal = el("amend-preflight-refusal");
    refusal.hidden = !pre.refusal;
    refusal.textContent = pre.refusal || "";
    const notes = el("amend-preflight-notes");
    notes.textContent = "";
    const check = pre.model_check;
    if (check && check.message) {
      notes.appendChild(text("li", "is-" + check.severity,
        (check.severity === "info" ? "INFO " : "WARNING ") + check.message));
    }
    const verify = pre.verify || {};
    (verify.errors || []).forEach((e) => notes.appendChild(text("li", "is-error", e)));
    (verify.warnings || []).forEach((w) => notes.appendChild(text("li", "is-warning", w)));
  }

  // The change this review is of: "change 3: Add Trumpet and Sax on LCL 21-22", and the
  // words that were typed.
  function renderChange(review) {
    const change = review.change;
    el("patch-change-head").hidden = !change;
    if (change) {
      el("patch-change-name").textContent = (change.number ? "change " + change.number
        : "change") + ": " + (change.name || "");
      el("patch-change-quote").textContent = change.text || "";
    }
    // How long it took: the model call and the desk read ("I just don't know how fast it would be").
    el("patch-timing").textContent = (review.timing && review.timing.line) || "";
  }

  function renderReview(review) {
    const box = el("amend-review");
    box.hidden = !review;
    if (!review) return;
    renderChange(review);
    renderStripNotes(review);
    renderChanges(review);
    renderPreflight(review);
  }

  // ---- the model call's progress ------------------------------------------
  // `run.progress` is the runner's structured progress (the
  // ModelCallProgress, via the listener on the run's own thread) -- the same
  // payload Build step 04 draws. Shown while a change compiles; the clock is
  // worked out here from `started_at` so it keeps moving between polls.

  const STAGE_WORDS = {
    waiting: "waiting for the first reply",
    thinking: "thinking",
    writing: "writing the answer",
    done: "done",
    failed: "stopped",
  };
  const LIVE = ["waiting", "thinking", "writing"];

  function fmtSeconds(s) {
    if (s == null || isNaN(s)) return "";
    s = Math.max(0, Math.round(s));
    if (s < 60) return s + " s";
    return Math.floor(s / 60) + " m " + (s % 60 < 10 ? "0" : "") + (s % 60) + " s";
  }

  function renderProgress(run) {
    const box = el("patch-progress");
    const running = run && run.state === "running";
    const p = run && run.kind === "patch" ? run.progress : null;
    if (!run || run.kind !== "patch" || (!running && !p)) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    el("patch-progress-bar").classList.toggle("is-stopped", !running);
    if (!p) {
      el("patch-progress-phase").textContent = "Reading the desk";
      el("patch-progress-stage").textContent = "which strips are free, before the change is compiled";
      el("patch-progress-elapsed").textContent = fmtSeconds(
        run.started_at ? Date.now() / 1000 - run.started_at : run.elapsed_s);
      el("patch-progress-tokens").textContent = "";
      el("patch-progress-tokens").hidden = true;
      return;
    }
    const live = running && LIVE.indexOf(p.stage) >= 0;
    el("patch-progress-phase").textContent = "Compiling the change" + (p.model ? " (" + p.model + ")" : "");
    el("patch-progress-stage").textContent = (STAGE_WORDS[p.stage] || p.stage || "") +
      (running && !live ? " -- reviewing the result" : "");
    const elapsed = live && p.started_at ? Date.now() / 1000 - p.started_at : p.elapsed_s;
    el("patch-progress-elapsed").textContent = fmtSeconds(elapsed);
    // Estimated from characters while it runs (hence the ~); the provider's
    // own count once the call ends.
    const parts = [];
    if (p.total_output_tokens != null) parts.push(p.total_output_tokens + " tokens out");
    else {
      if (p.thinking_tokens != null) parts.push("thinking ~" + p.thinking_tokens);
      if (p.output_tokens) parts.push("output ~" + p.output_tokens);
    }
    el("patch-progress-tokens").textContent = parts.join(" · ");
    el("patch-progress-tokens").hidden = !parts.length;
  }

  // ---- the journal stack -------------------------------------------------

  let stack = { entries: [] };
  // The id of the write this page just made, or null.
  let fresh = null;
  // What apply.js says about the Preview undo button: `reason` is why it is
  // locked right now ("" when it is not), `shown` is true while the Preview
  // box (step 2) is showing an undo preview, so the button reads "Preview
  // undo again" and points at it.
  let undoUi = { reason: "", shown: false };

  // Each row names the desk it wrote to (per-desk journal history: one plan, a
  // primary and a backup). `on_this_desk` is the
  // server's answer for the console in the bundle bar -- true, false, or
  // null with no console -- and `is_top` is that desk's newest standing
  // write: the one Undo reverses. A row from before entries named their
  // desk has `desk: null` and counts as this desk's.
  function deskCell(entry) {
    if (!entry.desk) return "not recorded";
    const d = entry.desk;
    return (d.name ? d.name + " " : "") + (d.model ? "(" + d.model + ") " : "") +
      (d.serial ? "#" + d.serial : "") + (d.address ? " @ " + d.address : "");
  }

  // A patch row reads as a change: its short name, the words typed, and
  // then the run's own summary line. Every other row is its summary.
  function summaryCell(entry) {
    const td = document.createElement("td");
    const change = entry.change;
    if (!change) {
      td.textContent = entry.summary || "";
      return td;
    }
    td.appendChild(text("span", "journal-change-name", entry.change_label ||
      ("change " + (change.number || "") + ": " + (change.name || ""))));
    if (change.text) td.appendChild(text("span", "journal-change-text", "\u201c" + change.text + "\u201d"));
    td.appendChild(text("span", "journal-change-summary", entry.summary || ""));
    return td;
  }

  // Preview undo, in the last cell of the newest standing row. Brass until it
  // has been used; then the outline "Preview undo again" with a link to where
  // the preview is shown. Locked, it says why in words beside the button.
  function undoPreviewControls(box) {
    const btn = text("button", undoUi.shown
      ? "btn btn-secondary btn-sm" : "btn btn-primary btn-sm",
      undoUi.shown ? "Preview undo again" : "Preview undo");
    btn.type = "button";
    btn.id = "undo-preview-btn";
    btn.disabled = !!undoUi.reason;
    box.appendChild(btn);
    if (undoUi.reason) {
      const note = text("span", "act-note", undoUi.reason);
      note.id = "undo-preview-reason";
      btn.setAttribute("aria-describedby", note.id);
      box.appendChild(note);
    } else if (undoUi.shown) {
      const link = text("button", "shown-in", "shown in step 2 \u2191");
      link.type = "button";
      link.dataset.shownIn = "1";
      box.appendChild(link);
    }
  }

  function renderStack() {
    const rows = el("journal-stack-rows");
    rows.textContent = "";
    const entries = stack.entries || [];
    entries.forEach((entry) => {
      const tr = document.createElement("tr");
      const other = entry.on_this_desk === false;
      if (entry.is_top) tr.className = "is-top";
      else if (entry.undone_by) tr.className = "is-undone";
      else if (other) tr.className = "is-other-desk";
      // The write this page just made, highlighted at the top.
      if (fresh && entry.id === fresh) tr.classList.add("is-fresh");
      // Each cell carries its column's name: at phone width a row is a stack
      // of labelled lines, drawn from `data-l`.
      const labelled = (td, label) => { td.dataset.l = label; tr.appendChild(td); return td; };
      labelled(text("td", "readout-cell", (entry.timestamp || "").replace("T", " ").slice(0, 19)),
               "When (UTC)");
      labelled(text("td", "", entry.kind), "Kind");
      const desk = labelled(text("td", "journal-desk-cell", deskCell(entry)), "Desk");
      if (entry.desk_label) desk.title = entry.desk_label;
      labelled(summaryCell(entry), "Summary");
      labelled(text("td", "", entry.mismatches), "Mismatches");
      const flag = document.createElement("td");
      flag.className = "journal-act-cell";
      flag.dataset.l = "";
      const stack_ = document.createElement("div");
      stack_.className = "act-stack";
      flag.appendChild(stack_);
      // A tag holds a word and nothing else: Undone, or Other desk. The
      // newest standing write on this desk carries Preview undo instead; the
      // button is the mark. Older rows have none.
      if (entry.undone_by) stack_.appendChild(text("span", "prop", "Undone"));
      else if (other) stack_.appendChild(text("span", "prop", "Other desk"));
      if (entry.is_top) undoPreviewControls(stack_);
      if (entry.kind === "patch" && entry.change && !entry.undone_by && !entry.aborted) {
        const keep = text("button", "btn btn-secondary btn-sm promote-btn", "Keep this in the show");
        keep.type = "button";
        // Drawn here, handled by apply.js (a delegated click on the stack's
        // rows): this file posts nothing and listens to nothing.
        keep.dataset.promote = entry.id;
        keep.dataset.label = entry.change_label || "this change";
        keep.title = "Put this change's text in instructions.md and the inputs it added in " +
          "input.csv, so the next rebuild owns them. Previews first.";
        stack_.appendChild(keep);
      }
      tr.appendChild(flag);
      tr.title = entry.path;
      rows.appendChild(tr);
    });
    // No row yet: the line says so, and where the button will be it holds a
    // locked Preview undo with its reason in words.
    const empty = el("journal-stack-empty");
    empty.hidden = entries.length > 0;
    empty.textContent = "";
    const demo = !!SP.console().demo;
    empty.appendChild(text("span", "", !stack.bundle ? "No show bundle open."
      : demo ? "The Demo show has no history: nothing is written to its simulated desk."
        : "Nothing written from this show yet."));
    if (stack.bundle && !entries.length) {
      const box = document.createElement("div");
      box.className = "act-stack";
      const btn = text("button", "btn btn-secondary btn-sm", "Preview undo");
      btn.type = "button";
      btn.id = "undo-preview-btn";
      btn.disabled = true;
      const note = text("span", "act-note", demo ? "the Demo show is read-only"
        : "nothing has been written from this show");
      note.id = "undo-preview-reason";
      btn.setAttribute("aria-describedby", note.id);
      box.appendChild(btn);
      box.appendChild(note);
      empty.appendChild(box);
    }
    const deskNote = el("journal-stack-desk");
    deskNote.textContent = !stack.bundle ? ""
      : stack.desk_label
        ? "Undo acts on " + stack.desk_label + "." +
          (stack.desk && !stack.desk.serial
            ? " Rows match it by address until it is pinged." : "")
        : (SP.console().demo
          // Demo is not a desk, so it has no journal rows either
          // (apply.js says, beside Preview undo, that Undo is switched off).
          ? ""
          : "No console in the bar: Undo has no desk to act on.");
  }

  async function refreshStack() {
    try {
      const r = await fetch("/api/journals");
      stack = r.ok ? await r.json() : { entries: [] };
    } catch (e) {
      stack = { entries: [] };
    }
    renderStack();
    return stack;
  }

  function hasUndoable() {
    return (stack.entries || []).some((e) => e.is_top);
  }

  // The id of the newest standing row, the one Preview undo is on: what a
  // confirmed undo sends as `expected_undo_id`, so a write recorded since
  // (from another tab or a terminal) refuses the undo instead of reversing
  // a row this page never showed.
  function topId() {
    const top = (stack.entries || []).find((e) => e.is_top);
    return top ? top.id : null;
  }

  function renderSubject() {
    const bundle = SP.bundle();
    const subject = el("amend-subject");
    subject.textContent = "";
    if (!bundle) {
      subject.textContent = "No show bundle open. Open one in the bar above.";
      return;
    }
    // Per-desk journals: the applied plan is the one
    // the bar's desk's own newest write left on it, found by serial, and
    // plan.json only when this bundle has not written to that desk yet.
    // The review's first INFO line says which it was.
    // Which plan a change starts from is in the stage head's '?'; the review's first INFO line says which it was.
    subject.appendChild(document.createTextNode("This patches "));
    subject.appendChild(text("code", "", bundle.name));
    subject.appendChild(document.createTextNode(" as it stands on the desk. Strips already " +
      "in use stay where they are. Setup window only, not mid-show."));
  }

  // The stack is refreshed by apply.js -- at first paint, on a bundle
  // change and after every run -- because the Undo button's state hangs
  // off it, and that button is apply.js's.
  SP.onBundleChange(() => {
    renderReview(null);
    renderSubject();
  });

  renderSubject();

  SP.amendView = {
    renderReview: renderReview,
    renderProgress: renderProgress,
    refreshStack: refreshStack,
    hasUndoable: hasUndoable,
    topId: topId,
    entries: () => (stack.entries || []).slice(),
    // Highlight one row as the write just made (null clears it).
    setFresh: (id) => { fresh = id || null; renderStack(); },
    // Preview undo's state, from apply.js: why it is locked ("" when it is
    // not) and whether the Preview box is showing an undo preview.
    setUndoUi: (reason, shown) => {
      const next = { reason: reason || "", shown: !!shown };
      if (next.reason === undoUi.reason && next.shown === undoUi.shown) return;
      undoUi = next;
      renderStack();
    },
    // The desk the newest standing row was written to, as its row names it.
    topDesk: () => {
      const top = (stack.entries || []).find((e) => e.is_top);
      return top ? deskCell(top).trim() : "";
    },
  };
})();
