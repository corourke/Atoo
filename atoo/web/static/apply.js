(() => {
  "use strict";

  // Apply (mockup version H, mockups/apply-flow/)
  // -- loaded by the shell (`/`) after shell.js, setup.js and amend.js,
  // and coded against `window.Atoo`.
  //
  // THIS IS THE ONE SCREEN IN ATOO THAT WRITES TO A CONSOLE, and
  // there is exactly ONE arming control on it: `#apply-arm-checkbox`,
  // which is `--confirm`. The maintainer's decision, and the reason Amend is a
  // mode of this screen rather than a page of its own (OPTIONS-H.md) --
  // one console, one arming discipline, one journal, one pre-flight, one
  // place to review when any of it changes. A flow that seems to want a
  // second arming control is a flow to re-read the mockup about.
  //
  // Both modes are the same four steps:
  //
  //   1 What will be written -- the plan and its pre-flight verify (Full
  //     build), or the change (Patch), with the options folded under them;
  //   2 Preview -- one button; its result fills the box, the desk drawn as
  //     scribble strips (`desk_view.py`, sent down as `drawing` / `desk`);
  //   3 Arm and write -- the checkbox and the button together, enabled only
  //     after a preview of exactly what step 1 holds; the write's result
  //     shows in this box;
  //   4 History -- the journal stack, with Preview undo and Undo newest
  //     write; the write just made sits at the top, highlighted.
  //
  // Editing step 1 after a preview marks the preview stale, and Write stays
  // locked until the next one. The Demo show previews against its simulated
  // WING, and its Write and Undo are locked -- each says so under itself;
  // the server refuses them regardless.
  //
  // Nothing here decides whether it is safe to write. `POST
  // /api/apply/run` runs `atoo apply` -- the command, in a worker
  // thread on the server -- so the pre-flight refusal, the console-model
  // cross-check and the empty-bay stop are that command's, exactly as
  // from a terminal. What this file does is make the gate VISIBLE before
  // the button, keep the button disabled until the checkbox is ticked,
  // and draw what the run read and wrote.
  //
  // Patch (an earlier change as "Amend") is a MODE of this screen, not
  // a second one. The `Full build | Patch` switch changes what Preview and
  // the write button run -- `atoo apply`, or `atoo patch` with a
  // typed change, or `atoo amend` from a rebuilt plan -- and nothing
  // about how they are armed. amend.js draws the review's words, the model
  // call's progress and the journal stack; every request that can reach a
  // console is still sent from THIS file, behind THIS checkbox. The journal
  // stack's Undo is one more such request, and it is armed the same way: an
  // undo is a write. The element ids keep the word "amend" -- scripts and
  // tests use them -- while the page says "Patch" and calls what is typed a
  // change.
  //
  // Three things it deliberately does NOT do:
  //
  //   * It does not recompute `would_change`. That is `_values_equal`,
  //     type-aware and tolerant for floats; a `!==` here would overstate
  //     a preview by exactly the addresses an earlier change is about. The
  //     server sends the answer per record, and the counts.
  //   * It does not word the summary. `apply.ApplyResult.summary()` is
  //     sent down as a string and printed, so this page and the terminal
  //     cannot describe the same run differently.
  //   * It does not offer a second console field. There is one console,
  //     the bundle bar's -- resolved at startup, editable only there
  //     (the maintainer, 2026-09-24) -- and this screen names it beside every
  //     write. Every write request carries the desk this page names
  //     (`expected_console`), so a page left open while the address was
  //     changed elsewhere is refused rather than writing to a desk it does
  //     not show; and changing the desk disarms the checkbox.
  //
  // And every write request says WHAT this page reviewed (the maintainer's desk
  // session, 2026-09-24: a tab kept open across a server restart onto a
  // different bundle copy): `expected_bundle`, the bundle it shows, plus
  // `expected_plan_sha256` (the plan.json the pre-flight verified) for an
  // apply, `expected_review_id` (the review drawn in step 2) for a patch or
  // an amend, and `expected_undo_id` (the History row marked top) for an
  // undo. The server refuses a confirmed write when any of them is not what
  // it would write (409, `stale`); before sending, this file asks
  // `SP.checkServer()` whether the server behind the page is still the one
  // that drew it.

  const SP = window.Atoo;
  const el = (id) => document.getElementById(id);

  const subject = el("apply-subject");
  const consoleLine = el("apply-console-line");
  const skipVerify = el("apply-skip-verify");
  const skipVerifyWarn = el("apply-skip-verify-warn");
  const cleanToggle = el("apply-clean-toggle");
  const cleanSub = el("apply-clean-sub");
  const cleanSockets = el("apply-clean-sockets");
  const preflightBadge = el("apply-preflight-badge");
  const preflightBtn = el("apply-preflight-btn");
  const preflightSummary = el("apply-preflight-summary");
  const preflightEmpty = el("apply-preflight-empty");
  const previewBtn = el("apply-preview-btn");
  const armCheckbox = el("apply-arm-checkbox");
  const runBtn = el("apply-run-btn");
  const disabledReason = el("apply-disabled-reason");
  const undoLocked = el("undo-locked");
  const message = el("apply-message");
  const runPanel = el("apply-run-panel");
  const runLabel = el("apply-run-label");
  const resultPanel = el("apply-result-panel");
  const progressLine = el("apply-progress-line");
  const previewNote = el("apply-preview-note");
  const staleNote = el("apply-stale");
  const modeFull = el("apply-mode-full");
  const modeAmend = el("apply-mode-amend");
  const amendRebuilt = el("amend-rebuilt");
  const allowToggle = el("amend-allow-toggle");
  const allowSub = el("amend-allow-sub");
  const amendAllow = el("amend-allow");
  const patchText = el("patch-change-text");
  const patchModelNote = el("patch-model-note");
  const sourceChange = el("patch-source-change");
  const sourceRebuilt = el("patch-source-rebuilt");
  const undoPreviewBtn = el("undo-preview-btn");
  const undoRunBtn = el("undo-run-btn");
  const AV = SP.amendView;

  // Whatever apply is running or last ran, embedded by webui.py in the
  // document before this script -- a reload part way through an apply
  // must land on "running" with the log, not on a blank screen that
  // invites someone to press the button again.
  function readStartup() {
    const tag = el("initial-shell");
    if (!tag) return {};
    try {
      return JSON.parse(tag.textContent) || {};
    } catch (e) {
      return {};
    }
  }

  let preflight = null;   // GET /api/apply/preflight's last answer
  let run = readStartup().apply || { state: "idle" };
  let pollTimer = null;
  let applyMode = run.kind === "amend" || run.kind === "patch" ? "amend" : "full";
  // Inside Patch: a typed change ("change") or a rebuilt plan ("rebuilt").
  let patchSource = run.kind === "amend" ? "rebuilt" : "change";
  // What step 1 held when the last clean preview was started, and when
  // the run in flight was. Write is offered only for what a person has just
  // previewed -- and for a patch or an amend the server refuses any other
  // (409), so this is the courtesy and that is the guard.
  let reviewedFor = null;
  let startedFor = null;

  function isDemo() {
    return !!SP.console().demo;
  }

  // Which command the Patch screen's buttons run right now.
  function patchKind() {
    return patchSource === "change" ? "patch" : "amend";
  }

  function runKindNow() {
    return applyMode === "amend" ? patchKind() : "apply";
  }

  function allowStrips() {
    if (!allowToggle.checked) return [];
    return (amendAllow.value || "").split(",").map((x) => x.trim()).filter(Boolean);
  }

  function cleanValue() {
    return cleanToggle.checked ? ((cleanSockets.value || "").trim() || null) : null;
  }

  function amendInputs() {
    const allow = allowStrips();
    if (patchKind() === "patch") {
      return { change: (patchText.value || "").trim(), allow_strips: allow };
    }
    return {
      amended_plan: (amendRebuilt.value || "").trim() || null,
      allow_strips: allow,
    };
  }

  // The desk this page names, as `address:port` -- sent with every write
  // as `expected_console`, and part of what a preview reviewed.
  function deskLabel() {
    return SP.consoleLabel(SP.console());
  }

  // How the page names the desk a preview reads.
  function deskWords() {
    if (isDemo()) return "the Demo's simulated WING";
    return SP.console().address ? deskLabel() : "the desk in the bar";
  }

  // The bundle this page shows -- sent with every write as
  // `expected_bundle`.
  function bundleShown() {
    const bundle = SP.bundle();
    return bundle ? bundle.directory : null;
  }

  // What step 1 holds right now, and the desk: the key a preview is for.
  // A preview on desk A never arms a write to desk B; the server's
  // `_amend_key` carries the console too.
  function stepOneKey() {
    if (applyMode === "full") {
      return JSON.stringify({ kind: "apply", skip: !!skipVerify.checked, clean: cleanValue(),
        plan: (preflight && preflight.plan_sha256) || null, console: deskLabel() });
    }
    return JSON.stringify({ kind: patchKind(), inputs: amendInputs(), console: deskLabel() });
  }

  // A preview is one worth arming only when the command itself said so.
  // For a patch or an amend: it ran clean, it found something to write, and
  // nothing was refused -- the server applies exactly the same test before
  // it will accept the write. For a full build: it ran, and its journal
  // came back.
  function previewIsWritable(r) {
    if (!r || r.kind !== runKindNow() || r.state !== "done" || !r.preview) return false;
    if (r.kind === "apply") {
      return r.exit_code === 0 && !!(r.result && r.result.dry_run && !r.result.aborted);
    }
    const review = r.review;
    return !!(r.exit_code === 0 && review && !review.blocked &&
      !(review.collisions || []).length && (review.to_write || []).length &&
      r.result && r.result.dry_run);
  }

  function previewIsCurrent() {
    return previewIsWritable(run) && reviewedFor === stepOneKey();
  }

  function showMessage(text, isError) {
    message.textContent = text || "";
    message.hidden = !text;
    message.classList.toggle("panel-message-error", !!isError);
  }

  function setLocked(node, strong, rest) {
    node.textContent = "";
    if (!strong && !rest) {
      node.hidden = true;
      return;
    }
    if (strong) {
      const b = document.createElement("strong");
      b.textContent = strong;
      node.appendChild(b);
    }
    if (rest) node.appendChild(document.createTextNode((strong ? " " : "") + rest));
    node.hidden = false;
  }

  // ---- step 1: what will be written ----------------------------------------

  function fact(parent, n, words) {
    const span = document.createElement("span");
    const b = document.createElement("b");
    b.textContent = String(n);
    span.appendChild(b);
    span.appendChild(document.createTextNode(" " + words));
    parent.appendChild(span);
  }

  function plural(n, one, many) {
    return n === 1 ? one : many;
  }

  function renderSubject() {
    const bundle = SP.bundle();
    subject.textContent = "";
    if (!bundle) {
      subject.textContent = "No show bundle open. Open one in the bar above.";
    } else {
      subject.appendChild(document.createTextNode("The plan in "));
      const path = document.createElement("code");
      path.textContent = bundle.name + "/plan.json";
      subject.appendChild(path);
      // The bytes the pre-flight verified -- and the only plan.json a
      // confirmed apply from this page will write (`expected_plan_sha256`).
      if (preflight && preflight.plan_sha256) {
        const dim = document.createElement("span");
        dim.className = "apply-dim";
        dim.appendChild(document.createTextNode(" (sha256 "));
        const sha = document.createElement("code");
        sha.id = "apply-plan-sha";
        sha.title = preflight.plan_sha256;
        sha.textContent = preflight.plan_sha256.slice(0, 12);
        dim.appendChild(sha);
        dim.appendChild(document.createTextNode(")"));
        subject.appendChild(dim);
      }
    }

    const facts = el("apply-plan-facts");
    facts.textContent = "";
    const counts = preflight && preflight.plan_counts;
    if (counts) {
      [["channels", "channel", "channels"], ["aux", "aux", "aux"], ["busses", "bus", "buses"],
       ["mains", "main", "mains"], ["matrices", "matrix", "matrices"], ["dcas", "DCA", "DCAs"],
       ["mute_groups", "mute group", "mute groups"], ["sockets", "socket", "sockets"]]
        .forEach(([key, one, many]) => {
          if (counts[key]) fact(facts, counts[key], plural(counts[key], one, many));
        });
    }

    const desk = SP.console();
    consoleLine.textContent = "";
    if (desk.demo) {
      consoleLine.textContent = "The console is Demo, a simulated WING Compact: Preview reads " +
        "it, and nothing is written.";
    } else if (!desk.address) {
      consoleLine.textContent = "No console address. Set one in the bar above (Console: Change…).";
    } else {
      consoleLine.appendChild(document.createTextNode("Writing to "));
      const addr = document.createElement("code");
      addr.id = "apply-console-address";
      addr.textContent = deskLabel();
      consoleLine.appendChild(addr);
      const provenance = SP.consoleProvenance(desk);
      if (provenance) consoleLine.appendChild(document.createTextNode(", " + provenance));
      consoleLine.appendChild(document.createTextNode("."));
    }
  }

  // The pre-flight verify line. `apply` runs verify_plan before a single
  // packet goes out and refuses on any ERROR. That gate exists whether or
  // not it is drawn; this line is here so it is visible rather than
  // implied. Its findings are read in the dock and only there;
  // this line carries the badge and the count of what else it found.

  function summaryLine(target, counts, label) {
    const parts = [];
    [["error", "error", "errors"], ["warning", "warning", "warnings"], ["info", "note", "notes"]]
      .forEach(([sev, one, many]) => {
        if (counts[sev]) parts.push(counts[sev] + " " + (counts[sev] === 1 ? one : many));
      });
    target.textContent = "";
    target.hidden = !parts.length;
    if (!parts.length) return;
    const words = document.createElement("span");
    words.textContent = label + parts.join(", ") + " ";
    target.appendChild(words);
    const link = document.createElement("button");
    link.type = "button";
    link.className = "findings-summary-link";
    link.textContent = "in Findings →";
    link.addEventListener("click", () => { if (SP.revealDock) SP.revealDock(); });
    target.appendChild(link);
  }

  function severityCounts(list) {
    const counts = { error: 0, warning: 0, info: 0 };
    (list || []).forEach((f) => {
      const n = Array.isArray(f.members) && f.members.length ? f.members.length : 1;
      counts[counts[f.severity] != null ? f.severity : "info"] += n;
    });
    return counts;
  }

  // Box 1's notes line. The dock's own counts are the whole
  // show's -- the build's notes and, after a preview, the run's too -- so
  // a bare "7 notes in Findings" beside a dock reading "6 notes on
  // choices" was a disagreement nobody could resolve. The line counts the
  // pre-flight's own notes by the dock's two folds, says they are AMONG
  // those, and its link flashes exactly them there. (The folds count
  // rows; notes sharing a code share a row, so "among" is the
  // word, not "of".)
  function preflightNotesLine(target, list) {
    const notes = (list || []).filter((f) => f.severity === "info");
    target.textContent = "";
    target.hidden = !notes.length;
    if (!notes.length) return;
    const isDetail = (f) => (SP.isBuildDetail ? SP.isBuildDetail(f) : false);
    const details = notes.filter(isDetail).length;
    const choices = notes.length - details;
    const folds = [];
    if (choices) folds.push(choices + " among Choices");
    if (details) folds.push(details + " among Build details");
    const words = document.createElement("span");
    words.textContent = notes.length + " " + plural(notes.length, "note", "notes") +
      " (" + folds.join(", ") + ") ";
    target.appendChild(words);
    const link = document.createElement("button");
    link.type = "button";
    link.className = "findings-summary-link";
    link.textContent = "show in Findings →";
    link.addEventListener("click", () => {
      const mine = SP.findings().filter((f) =>
        f._producer === "apply-preflight" && f.severity === "info");
      if (!(SP.showFindings && SP.showFindings(mine)) && SP.revealDock) SP.revealDock();
    });
    target.appendChild(link);
  }

  function renderPreflight() {
    const inputNote = el("apply-preflight-input-note");
    inputNote.hidden = true;
    if (!preflight) {
      preflightBadge.textContent = "Pre-flight verify: not run";
      preflightBadge.className = "state-badge state-notset";
      preflightSummary.hidden = true;
      preflightEmpty.hidden = false;
      preflightEmpty.textContent =
        "No plan to verify yet. Build one on Build step 04, or open a bundle that has one.";
      renderPatchModelNote();
      updateArmState();
      return;
    }
    const errors = preflight.errors || 0;
    const warnings = preflight.warnings || 0;
    preflightBadge.textContent = "Pre-flight verify: " + errors + " error" +
      (errors === 1 ? "" : "s") + " · " + warnings + " warning" + (warnings === 1 ? "" : "s");
    preflightBadge.className = "state-badge " +
      (errors ? "state-missing" : (warnings ? "state-stale" : "state-loaded"));
    // Errors and warnings are on the badge; the line beside it counts the
    // notes, by the dock's folds, and shows them there.
    preflightNotesLine(preflightSummary, preflight.findings);
    preflightEmpty.hidden = true;

    // The three checks that need the input list -- every input became a
    // channel, no channel was invented, phantom is safe for the mics in
    // use -- do not run without it, and a screen that did not say so
    // would be implying an assurance nobody made.
    if (!preflight.checked_input_list) {
      inputNote.textContent =
        "No input list read, so three checks did not run: that every input became a " +
        "channel, that no channel was invented, and that phantom power is safe for the " +
        "microphones in use. Put input.csv in the bundle to include them.";
      inputNote.hidden = false;
    }
    renderPatchModelNote();
    updateArmState();
  }

  async function fetchPreflight() {
    try {
      const r = await fetch("/api/apply/preflight");
      preflight = r.ok ? await r.json() : null;
    } catch (e) {
      preflight = null;
    }
    renderSubject();
    renderPreflight();
    SP.setFindings(SP.findings().filter((f) => f._producer !== "apply-preflight"));
    if (preflight && (preflight.findings || []).length) {
      SP.addFindings(preflight.findings.map((f) => Object.assign({}, f, {
        _producer: "apply-preflight",
        jumps: [{ label: "Apply pre-flight", mode: "apply", target: "#apply-preflight-panel" }],
      })));
    }
  }

  // Patch: a typed change is compiled by one model call, and a model needs
  // setting up. Said at INFO before Preview is pressed, not after it fails;
  // and the Demo show, being read-only, has no rebuilt plan to patch from.
  function patchBlocker() {
    if (applyMode !== "amend") return "";
    if (patchKind() === "patch") {
      const model = preflight && preflight.patch_model;
      if (model && model.ready === false) {
        return "INFO A typed change is compiled by a model, and none is set up here (" +
          (model.why || "no model configured") + ")." +
          (isDemo() ? " The Demo previews a Full build only until one is." : "");
      }
      return "";
    }
    if (isDemo()) {
      return "INFO The Demo show has no rebuilt plan, and can't be given one: it is " +
        "read-only. In the Demo, Patch previews a typed change.";
    }
    return "";
  }

  function renderPatchModelNote() {
    const why = patchBlocker();
    patchModelNote.textContent = why;
    patchModelNote.hidden = !why;
    // The rebuilt-plan note shows under the change box's place too.
    if (why && patchKind() === "amend") {
      const rebuilt = document.querySelector('[data-patch-only="rebuilt"]');
      if (rebuilt && patchModelNote.parentNode !== rebuilt) rebuilt.appendChild(patchModelNote);
    } else {
      const change = document.querySelector('[data-patch-only="change"]');
      if (change && patchModelNote.parentNode !== change) change.appendChild(patchModelNote);
    }
  }

  // ---- the one arming control, and every button's state --------------------
  // The button is disabled until the checkbox is ticked. The SERVER
  // refuses a `confirm` that arrives without an `arm` as well -- this is
  // the courtesy, that is the guard.

  function updateArmState() {
    const desk = SP.console();
    const demo = !!desk.demo;
    const hasBundle = !!SP.bundle();
    const skipping = !!skipVerify.checked;
    const running = run.state === "running";
    const amending = applyMode === "amend";
    const typing = amending && patchKind() === "patch";
    const noChange = typing && !(patchText.value || "").trim();
    const blockedByPreflight = !amending && !!(preflight && preflight.errors && !skipping);
    const previewed = previewIsCurrent();
    const stalePage = SP.isStale();
    const hasDesk = demo || !!desk.address;
    const blocker = patchBlocker();

    // Step 2's Preview.
    previewBtn.disabled = stalePage || !hasBundle || !hasDesk || running || noChange || !!blocker;
    previewNote.textContent = !amending
      ? "Reads every address the plan would write on " + deskWords() +
        ", and draws the desk as it will be. Writes nothing."
      : typing
        ? "Reads which strips are free on " + deskWords() + ", has the model compile the " +
          "change, and shows what would and wouldn't be written. Writes nothing."
        : "Reads which strips are free on " + deskWords() + ", and shows what the rebuilt " +
          "plan would and wouldn't write. Writes nothing.";
    // A preview that was of something else than step 1 holds now.
    staleNote.hidden = !(reviewedFor && reviewedFor !== stepOneKey() && previewIsWritable(run));

    // Step 3's Arm and Write.
    let strong = "";
    let reason = "";
    if (demo) {
      strong = "Writing is switched off in the Demo show.";
      reason = "Choose a console address in the bar to write to a real desk.";
    } else if (stalePage) reason = "This page is out of date — reload it (see the banner at the top).";
    else if (!hasBundle) reason = "No show bundle open — nothing to write.";
    else if (!desk.address) reason = "No console address — set one in the bundle bar.";
    else if (blockedByPreflight) {
      reason = "Blocked: the pre-flight verify has " + preflight.errors + " error(s), and a " +
        "full build refuses a plan in this state. Fix it, or tick Skip the pre-flight verify " +
        "under Options to write it anyway.";
    } else if (running) reason = "";
    else if (!previewed && writeOfThisMode() && run.state === "done") {
      reason = "Written. Preview again before another write.";
    } else if (!previewed) {
      const kind = runKindNow();
      if (run.kind === kind && run.preview && run.review && (run.review.blocked ||
          (run.review.collisions || []).length)) {
        reason = "The last preview refused this change — see step 2. Nothing can be written " +
          "until it previews clean.";
      } else if (run.kind === kind && run.preview && run.review &&
                 !(run.review.to_write || []).length) {
        reason = "The last preview found nothing to write.";
      } else if (reviewedFor && reviewedFor !== stepOneKey()) {
        reason = "Step 1 or the console changed since the preview. Preview again.";
      } else {
        reason = "Preview first. Write unlocks once step 2 shows what it will do.";
      }
    } else if (!armCheckbox.checked) reason = "Tick Arm to enable the write.";
    else if (!amending && preflight && preflight.errors && skipping) {
      reason = "Pre-flight errors skipped: this writes a plan nothing has agreed is applicable.";
    }
    setLocked(disabledReason, strong, reason);
    disabledReason.classList.toggle("is-bypass",
      !demo && !amending && !!(preflight && preflight.errors && skipping) && previewed);

    const canArm = !demo && !stalePage && hasBundle && !!desk.address && !running;
    armCheckbox.disabled = !canArm;
    if (demo) armCheckbox.checked = false;
    runBtn.disabled = !canArm || blockedByPreflight || !previewed || !armCheckbox.checked;
    runBtn.textContent = amending ? "Write changes to console" : "Write to console";

    // Step 4's Undo: a write, armed by the same checkbox; its preview is not.
    undoPreviewBtn.disabled = demo || stalePage || !hasBundle || !desk.address || running;
    undoRunBtn.disabled = demo || stalePage || !hasBundle || !desk.address || running ||
      !armCheckbox.checked || !AV.hasUndoable();
    if (demo) {
      setLocked(undoLocked, "Undo is switched off in the Demo show.",
        "Choose a console address in the bar to write to a real desk.");
    } else if (AV.hasUndoable() && !armCheckbox.checked && !running && desk.address) {
      setLocked(undoLocked, "", "Undo is a write: tick Arm in step 3 to enable it.");
    } else {
      setLocked(undoLocked, "", "");
    }

    renderSteps();
  }

  // The four boxes' numbers and state lines.
  function setStep(n, cls, state) {
    const step = el(n === 4 ? "journal-stack-panel" : "apply-step-" + n);
    step.classList.remove("is-current", "is-done", "is-waiting");
    if (cls) step.classList.add(cls);
    if (state != null) el("apply-step-" + n + "-state").textContent = state;
  }

  function writeOfThisMode() {
    return run.kind === runKindNow() && !run.preview;
  }

  function renderSteps() {
    const previewed = previewIsCurrent();
    const ownPreview = run.kind === runKindNow() && run.preview;
    const running = run.state === "running";
    const written = writeOfThisMode() && run.state !== "idle";

    let s1 = "";
    if (applyMode === "full" && preflight) {
      s1 = preflight.errors ? "pre-flight found errors"
        : preflight.warnings ? "pre-flight passed, with warnings" : "pre-flight passed";
    }
    setStep(1, previewed || written ? "is-done" : "is-current", s1);

    let s2 = "reads the desk, writes nothing";
    if (ownPreview && running) s2 = "reading " + (run.on || deskWords()) + "…";
    else if (ownPreview && run.state === "failed") s2 = "the preview stopped — see its log";
    else if (ownPreview && run.state === "done") {
      const read = readCount(run);
      s2 = read != null ? "read " + read + " addresses on " + (run.on || deskWords())
        : "read " + (run.on || deskWords());
    }
    setStep(2, previewed || written ? "is-done" : "is-current", s2);

    let s3 = "after a preview";
    let c3 = "is-waiting";
    if (written && running) { s3 = "writing…"; c3 = "is-current"; }
    else if (written && run.result && !run.result.dry_run) {
      const bad = run.result.aborted || run.result.counts.mismatch || run.result.counts.unreadable;
      s3 = bad ? "written, with problems" : "written and confirmed";
      c3 = bad ? "is-current" : "is-done";
    } else if (written && run.state === "failed") { s3 = "the write stopped"; c3 = "is-current"; }
    else if (previewed) { s3 = isDemo() ? "" : "ready"; c3 = "is-current"; }
    setStep(3, c3, s3);
    setStep(4, "", null);
  }

  function readCount(r) {
    if (r.kind === "apply") return r.result && r.result.counts ? r.result.counts.total : null;
    const timing = r.review && r.review.timing;
    return timing && timing.desk_addresses != null ? timing.desk_addresses : null;
  }

  // ---- Full build | Patch, and inside Patch: a change | a rebuilt plan -----

  function setApplyMode(mode) {
    applyMode = mode === "amend" ? "amend" : "full";
    [modeFull, modeAmend].forEach((b) => {
      const on = b.dataset.applyMode === applyMode;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    document.querySelectorAll("[data-apply-only]").forEach((node) => {
      node.hidden = node.dataset.applyOnly !== applyMode;
    });
    const hint = el("apply-mode-hint");
    hint.textContent = "";
    const b = document.createElement("strong");
    b.textContent = applyMode === "full" ? "Full build" : "Patch";
    hint.appendChild(b);
    hint.appendChild(document.createTextNode(applyMode === "full"
      ? " writes the whole plan to a desk you own."
      : " writes one change to a desk that's already in use, and moves nothing else."));
    // Switching what the write button means disarms it. A tick given for
    // a full build is not consent to a patch, or the other way round.
    armCheckbox.checked = false;
    renderPatchModelNote();
    renderRun();
  }

  // Every signpost -- Build step 02, the full-build side of this screen --
  // calls this one function, so a new one cannot grow its own opinion of
  // what "go and amend" means (OPTIONS-H).
  function gotoAmend() {
    SP.activateMode("apply");
    setApplyMode("amend");
  }

  function setPatchSource(source) {
    patchSource = source === "rebuilt" ? "rebuilt" : "change";
    [sourceChange, sourceRebuilt].forEach((b) => {
      const on = b.dataset.patchSource === patchSource;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    document.querySelectorAll("[data-patch-only]").forEach((node) => {
      node.hidden = node.dataset.patchOnly !== patchSource;
    });
    // A tick given for one route is not consent to the other.
    armCheckbox.checked = false;
    renderPatchModelNote();
    renderRun();
  }

  // Step 1 changed: a tick given for what it held before is withdrawn.
  function stepOneEdited() {
    if (reviewedFor && reviewedFor !== stepOneKey()) armCheckbox.checked = false;
    updateArmState();
  }

  sourceChange.addEventListener("click", () => setPatchSource("change"));
  sourceRebuilt.addEventListener("click", () => setPatchSource("rebuilt"));
  patchText.addEventListener("input", stepOneEdited);

  modeFull.addEventListener("click", () => setApplyMode("full"));
  modeAmend.addEventListener("click", () => setApplyMode("amend"));
  document.querySelectorAll("[data-goto-amend]").forEach((b) => b.addEventListener("click", gotoAmend));
  SP.gotoAmend = gotoAmend;
  amendRebuilt.addEventListener("input", stepOneEdited);
  amendAllow.addEventListener("input", stepOneEdited);
  allowToggle.addEventListener("change", () => {
    allowSub.hidden = !allowToggle.checked;
    stepOneEdited();
  });
  cleanToggle.addEventListener("change", () => {
    cleanSub.hidden = !cleanToggle.checked;
    if (cleanToggle.checked) cleanSockets.focus();
    stepOneEdited();
  });
  cleanSockets.addEventListener("input", stepOneEdited);

  armCheckbox.addEventListener("change", updateArmState);
  skipVerify.addEventListener("change", () => {
    skipVerifyWarn.hidden = !skipVerify.checked;
    stepOneEdited();
  });
  preflightBtn.addEventListener("click", fetchPreflight);

  // ---- the run ----------------------------------------------------------
  // One runner carries every preview, write and undo. Its log, its progress
  // line and its journal view are moved into the step the run belongs to.

  function slotFor(r) {
    if (r.kind === "undo") return el("apply-log-slot-4");
    return r.preview ? el("apply-log-slot-2") : el("apply-log-slot-3");
  }

  function renderRun() {
    const labels = {
      running: ["Running", "state-stale"],
      done: ["Done", "state-loaded"],
      failed: ["Failed", "state-missing"],
    };
    // A run belongs to the mode that started it. A full
    // build's log is not shown under Patch, nor a patch's under Full build;
    // an undo (History, under both) and a run still in flight show in
    // either.
    const ownMode = run.kind === "undo" || run.state === "running" ||
      (run.kind === "apply") === (applyMode === "full");
    const slot = slotFor(run);
    if (progressLine.parentNode !== slot) slot.appendChild(progressLine);
    if (runPanel.parentNode !== slot) slot.appendChild(runPanel);
    runPanel.hidden = run.state === "idle" || !run.state || !ownMode;
    const label = labels[run.state] || ["Idle", "state-notset"];
    el("apply-run-state").textContent = label[0];
    el("apply-run-state").className = "state-badge " + label[1];
    let elapsed = run.elapsed_s;
    if (run.state === "running" && run.started_at) elapsed = Date.now() / 1000 - run.started_at;
    el("apply-run-elapsed").textContent = elapsed != null ? Math.round(elapsed) + " s" : "";
    el("apply-run-exit").textContent = run.exit_code != null ? "exit " + run.exit_code : "";
    el("apply-run-command").textContent = (run.command || []).join(" ");
    const log = el("apply-run-log");
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
    log.textContent = (run.log || []).join("\n")
      || (run.state === "running" ? "Started — waiting for the first line…" : "");
    if (atBottom) log.scrollTop = log.scrollHeight;
    runLabel.textContent = runLabelFor(run.kind, run.preview) || runLabel.textContent;

    // The phase lines, as the command prints them to stderr: the
    // newest one is the progress, while the run lasts.
    const lines = (run.log || []).map((l) => l.trim()).filter(Boolean);
    progressLine.hidden = run.state !== "running" || !ownMode;
    progressLine.textContent = lines.length ? lines[lines.length - 1] : "Starting…";

    // One runner carries apply, amend and undo, and a write never switches
    // desks part way through: the bar's Change button is off while one
    // runs. The server refuses the edit regardless (409).
    SP.setConsoleLock(run.state === "running"
      ? (run.kind === "apply" && !run.preview ? "An " : "A ") +
        (runLabelFor(run.kind, run.preview) || "write").toLowerCase() +
        " is running -- the console " +
        "cannot change until it finishes."
      : "");
    const ownReview = (run.kind === "amend" || run.kind === "patch") &&
      run.kind === runKindNow() ? run.review : null;
    AV.renderReview(ownReview);
    AV.renderProgress(run);
    renderReview(ownMode);
    renderResult(ownMode);
    updateArmState();
  }

  const RUN_LABEL = { apply: "Full build", patch: "Patch", amend: "Patch (rebuilt plan)", undo: "Undo" };
  // A dry run is labelled as one -- "Preview failed", never
  // "Apply failed", after a press of Preview.
  const PREVIEW_LABEL = { apply: "Preview", patch: "Patch preview",
                          amend: "Patch preview (rebuilt plan)", undo: "Undo preview" };

  function runLabelFor(kind, preview) {
    return (preview ? PREVIEW_LABEL : RUN_LABEL)[kind];
  }

  // A number that only moves when the server answers is a number that
  // stops when the server does, which is the case it most needs to show.
  setInterval(() => { if (run.state === "running") renderRun(); }, 250);

  // ---- step 2: the desk, as scribble strips -------------------------------

  const LEGEND = {
    full: [["", "as the plan sets it"], ["l-changes", "changed by this write"],
           ["l-unused", "not in the plan"]],
    patch: [["", "in use"], ["l-free", "free"], ["l-new", "added by this change"],
            ["l-edit", "edited by this change"]],
  };

  function drawDesk(drawing) {
    const box = el("apply-desk");
    const legend = el("apply-desk-legend");
    box.textContent = "";
    legend.textContent = "";
    if (!drawing) return;
    const patch = drawing.mode === "patch";
    (drawing.sections || []).forEach((section) => {
      const head = document.createElement("h4");
      head.className = "desk-section-title";
      head.textContent = section.title + " ";
      const count = document.createElement("span");
      count.className = "desk-count";
      count.textContent = String(section.count);
      head.appendChild(count);
      box.appendChild(head);
      const grid = document.createElement("div");
      grid.className = "desk-strips";
      grid.dataset.kind = section.kind;
      section.strips.forEach((strip) => grid.appendChild(stripCell(section, strip, patch)));
      box.appendChild(grid);
    });
    const counts = drawing.counts || {};
    const entries = (patch ? LEGEND.patch : LEGEND.full).slice();
    if (patch && counts.released) entries.push(["l-released", "returned to free"]);
    if (patch && counts.unknown) entries.push(["l-unknown", "never answered — treated as in use"]);
    entries.forEach(([cls, words]) => {
      const span = document.createElement("span");
      if (cls) span.className = cls;
      span.textContent = words;
      legend.appendChild(span);
    });
  }

  function stripCell(section, strip, patch) {
    const cell = document.createElement("div");
    const free = strip.state === "free" || strip.state === "unused";
    let cls = "desk-strip";
    if (strip.state === "free" && !strip.mark) cls += " is-free";
    if (strip.state === "unused") cls += " is-free is-unused";
    if (strip.state === "unknown") cls += " is-unknown";
    if (strip.mark === "new") cls += " is-new";
    if (strip.mark === "edit") cls += " is-edit";
    if (strip.mark === "released") cls += " is-released";
    if (!patch && strip.changes && strip.state === "plan") cls += " is-changes";
    cell.className = cls;
    cell.dataset.strip = section.kind + ":" + strip.n;
    cell.dataset.state = strip.mark || strip.state;
    const name = document.createElement("div");
    name.className = "desk-strip-name";
    const showsFace = !(free && !strip.mark) && strip.state !== "unknown";
    if (showsFace && strip.colour) name.dataset.colour = String(strip.colour).toLowerCase();
    name.textContent = strip.state === "unknown" ? "unread"
      : showsFace ? (strip.name || "") : "—";
    cell.appendChild(name);
    const no = document.createElement("span");
    no.className = "desk-strip-no";
    no.textContent = String(strip.n);
    cell.appendChild(no);
    const words = { plan: "as the plan sets it", unused: "not in the plan", used: "in use",
      free: "free", unknown: "never answered — treated as in use" };
    cell.title = section.title.replace(/s$/, "") + " " + strip.n +
      (strip.name ? " — " + strip.name : "") +
      (strip.source_name ? " (the name on its source socket)" : "") +
      (strip.colour ? ", " + strip.colour : "") + " — " +
      ({ new: "added by this change", edit: "edited by this change",
         released: "returned to free" }[strip.mark] || words[strip.state] || strip.state) +
      (strip.changes ? "; this write changes it" : "");
    return cell;
  }

  function renderReview(ownMode) {
    const box = el("apply-review");
    const kind = runKindNow();
    const mine = ownMode !== false && run.kind === kind && run.preview && run.state !== "running";
    const drawing = !mine ? null
      : kind === "apply" ? (run.result && run.result.drawing)
        : (run.review && run.review.desk);
    box.hidden = !mine || !(drawing || run.review || run.result);
    const facts = el("apply-review-facts");
    facts.textContent = "";
    drawDesk(drawing);
    if (!mine) return;
    if (kind === "apply" && run.result) {
      const c = run.result.counts;
      fact(facts, c.total, "addresses read");
      fact(facts, c.would_change, "will change");
      fact(facts, Math.max(0, c.total - c.would_change - c.unreadable), "already match");
      fact(facts, c.unreadable, "didn't answer");
      if (c.cleaned) fact(facts, c.cleaned, plural(c.cleaned, "socket disconnected", "sockets disconnected"));
    } else if (drawing && drawing.counts) {
      const c = drawing.counts;
      fact(facts, c.strips, "strips read");
      fact(facts, c.in_use, "in use");
      fact(facts, c.new, "to add");
      fact(facts, c.edit, "to edit");
      if (c.released) fact(facts, c.released, "to return to free");
      if (c.unknown) fact(facts, c.unknown, "never answered");
    }
  }

  function publishRunFindings(list) {
    SP.setFindings(SP.findings().filter((f) => f._producer !== "apply"));
    const findings = (list || []).map((f) => Object.assign({}, f, {
      _producer: "apply",
      jumps: [{ label: "Apply", mode: "apply", target: "#apply-step-2" }],
    }));
    if (findings.length) SP.addFindings(findings);
  }

  async function poll() {
    let status;
    try {
      const r = await fetch("/api/apply/status");
      status = await r.json();
    } catch (e) {
      pollTimer = setTimeout(poll, 2000);
      return;
    }
    run = status;
    renderRun();
    if (run.state === "running") {
      pollTimer = setTimeout(poll, 1000);
      return;
    }
    pollTimer = null;
    if (run.preview && run.kind !== "undo") {
      reviewedFor = previewIsWritable(run) ? startedFor : null;
    }
    const wrote = !run.preview && run.kind !== "undo" && !!(run.result && run.result.journal_path);
    publishRunFindings(run.findings);
    await AV.refreshStack();
    if (wrote || (!run.preview && run.kind === "undo")) {
      // The write just made, at the top of History.
      const entries = AV.entries();
      AV.setFresh(entries.length ? entries[0].id : null);
    }
    renderRun();
  }

  async function start(confirmMode, what) {
    showMessage("");
    const kind = what || runKindNow();
    if (confirmMode && kind !== "undo" && runBtn.disabled) return;
    if (confirmMode && kind === "undo" && undoRunBtn.disabled) return;
    // Is the server behind this page still the one that drew it? Asked
    // now, not only on the poll: a restart two seconds ago must not get
    // one write through before the banner goes up.
    previewBtn.disabled = true;
    runBtn.disabled = true;
    if (!(await SP.checkServer())) {
      showMessage("Nothing was sent: this page is out of date -- the server behind it was " +
        "restarted or has another bundle open. Reload the page.", true);
      updateArmState();
      return;
    }
    let url = "/api/apply/run";
    // The checkbox itself goes with every request, alongside the button's
    // intent. The server refuses a confirm without it, whichever endpoint.
    // `expected_console` is the desk this page names; the server refuses a
    // confirmed write when the bar now holds a different one. The
    // `expected_*` fields after it are what this page reviewed -- see the
    // header comment.
    let body = {
      confirm: !!confirmMode,
      arm: !!armCheckbox.checked,
      skip_verify: !!skipVerify.checked,
      clean_output_sockets: cleanValue(),
      expected_console: deskLabel(),
      expected_bundle: bundleShown(),
      expected_plan_sha256: (preflight && preflight.plan_sha256) || null,
    };
    if (kind === "amend" || kind === "patch") {
      // A typed change goes to /api/patch/run, a rebuilt plan to
      // /api/amend/run; both armed by the same checkbox, both refused unless
      // the review this page drew is the one the server armed.
      url = kind === "patch" ? "/api/patch/run" : "/api/amend/run";
      body = Object.assign({ confirm: !!confirmMode, arm: !!armCheckbox.checked,
        expected_console: deskLabel(), expected_bundle: bundleShown(),
        expected_review_id: (run.kind === kind && run.review && run.review.review_id) || null,
      }, amendInputs());
    } else if (kind === "undo") {
      url = "/api/undo/run";
      body = { confirm: !!confirmMode, arm: !!armCheckbox.checked,
        expected_console: deskLabel(), expected_bundle: bundleShown(),
        expected_undo_id: AV.topId() };
    }
    if (!confirmMode && kind !== "undo") startedFor = stepOneKey();
    runLabel.textContent = runLabelFor(kind, !confirmMode);
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) {
        showMessage(data.error || "couldn't start the run", true);
        // A stale-page refusal names what this page was wrong about; redraw
        // that, so what is on screen is what the next press would write.
        if (data.stale === "bundle") SP.markStale(data.error);
        else if (data.stale === "plan") fetchPreflight();
        else if (data.stale === "review") reviewedFor = null;
        else if (data.stale === "undo") AV.refreshStack().then(updateArmState);
        if (data.stale) armCheckbox.checked = false;
        updateArmState();
        return;
      }
      run = data;
      AV.setFresh(null);
      // A write has been sent: the tick is spent. The next write -- a
      // second patch, an undo -- is a fresh decision and a fresh tick.
      if (confirmMode) armCheckbox.checked = false;
      publishRunFindings([]);
      renderRun();
      if (!pollTimer) pollTimer = setTimeout(poll, 400);
    } catch (e) {
      showMessage(String(e), true);
      updateArmState();
    }
  }

  previewBtn.addEventListener("click", () => start(false));
  runBtn.addEventListener("click", () => start(true));
  undoPreviewBtn.addEventListener("click", () => start(false, "undo"));
  undoRunBtn.addEventListener("click", () => start(true, "undo"));

  // ---- Keep a change in the show ---------------------
  // A patch row's "Keep this in the show" (drawn by amend.js) previews
  // `atoo patch --promote`: the change's text into instructions.md and
  // the inputs it added into input.csv. It writes the show's FILES, never
  // the console, so it is not behind the arming checkbox -- the preview is
  // the first click, and only the panel's own button writes. The words are
  // the command's (`promote.Promotion.summary`), sent down by the server.
  let promoting = null;
  const promotePanel = el("promote-panel");

  async function promoteCall(ref, confirm) {
    const r = await fetch("/api/patch/promote", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: ref, confirm: confirm }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || body.detail || ("HTTP " + r.status));
    return body;
  }

  function promoteMessage(msg, bad) {
    const m = el("promote-message");
    m.hidden = !msg;
    m.textContent = msg || "";
    m.classList.toggle("is-error", !!bad);
  }

  async function promotePreview(ref, label) {
    promoting = ref;
    promotePanel.hidden = false;
    el("promote-title").textContent = "Keep " + label + " in the show";
    el("promote-preview").textContent = "";
    el("promote-infos").textContent = "";
    promoteMessage("");
    el("promote-confirm-btn").disabled = true;
    try {
      const body = await promoteCall(ref, false);
      el("promote-preview").textContent = body.summary || "";
      (body.infos || []).forEach((i) => {
        const li = document.createElement("li");
        li.textContent = "INFO " + i;
        el("promote-infos").appendChild(li);
      });
      el("promote-confirm-btn").disabled = !!body.already;
      if (body.already) promoteMessage("Already in the show -- nothing to write.");
    } catch (e) {
      promoteMessage(String(e.message || e), true);
    }
  }

  el("journal-stack-rows").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-promote]");
    if (button) promotePreview(button.dataset.promote, button.dataset.label);
  });
  el("promote-confirm-btn").addEventListener("click", async () => {
    if (!promoting) return;
    el("promote-confirm-btn").disabled = true;
    try {
      const body = await promoteCall(promoting, true);
      promoteMessage("Written: " + (body.written || []).join(", ") + ". Rebuild the show to " +
        "put " + body.label + " in plan.json.");
    } catch (e) {
      promoteMessage(String(e.message || e), true);
    }
  });
  el("promote-cancel-btn").addEventListener("click", () => {
    promoting = null;
    promotePanel.hidden = true;
  });

  // ---- the journal view, and step 3's result -----------------------------

  const STATUS_LABEL = {
    mismatch: "Mismatch",
    unreadable: "Unreadable",
    unreadable_skipped: "Unreadable",
    match: "Written",
    skipped_no_change: "Unchanged",
  };

  // A preview records every address as `dry_run` and does NOT split it
  // into "would change" and "already correct" -- a preview asked the
  // console but never asked it to do anything, and a second status would
  // give the journal two vocabularies to keep in step (apply_plan's own
  // docstring). The split is `would_change`, which the SERVER computes
  // with the engine's type-aware comparison; this reads the answer.
  function statusLabel(record) {
    if (record.status === "dry_run") {
      return record.would_change ? "Would change" : "Already correct";
    }
    return STATUS_LABEL[record.status] || record.status;
  }

  function valueText(value) {
    if (value === null || value === undefined) return "—";
    return String(value);
  }

  function recordCard(record, emphasise) {
    const div = document.createElement("div");
    const isMismatch = record.status === "mismatch";
    const isUnreadable = record.status === "unreadable" || record.status === "unreadable_skipped";
    div.className = "apply-record" +
      (isMismatch ? " is-mismatch" : "") + (isUnreadable ? " is-unreadable" : "");

    const head = document.createElement("div");
    head.className = "apply-record-head";
    if (emphasise) {
      const badge = document.createElement("span");
      badge.className = "sev-badge " + (isMismatch ? "sev-error" : "sev-warning");
      badge.textContent = statusLabel(record);
      head.appendChild(badge);
    }
    const addr = document.createElement("code");
    addr.className = "apply-record-addr";
    addr.textContent = record.address;
    head.appendChild(addr);
    const desc = document.createElement("span");
    desc.className = "apply-record-desc";
    desc.textContent = record.description || "";
    head.appendChild(desc);
    // A verdict settled by a late reply or the end-of-run
    // recheck should say so rather than being quietly indistinguishable.
    if (record.readback_source) {
      const src = document.createElement("span");
      src.className = "source-tag";
      src.textContent = record.readback_source === "late_reply"
        ? "settled by a late reply" : "settled on recheck";
      head.appendChild(src);
    }
    div.appendChild(head);

    const vals = document.createElement("div");
    vals.className = "apply-record-vals";
    [["Prior", record.prior_value], ["Intended", record.intended_value],
     ["Readback", record.readback_value]].forEach(([label, value]) => {
      const wrap = document.createElement("span");
      const dt = document.createElement("span");
      dt.className = "apply-record-key";
      dt.textContent = label;
      const dd = document.createElement("span");
      dd.className = "readout";
      dd.textContent = valueText(value);
      wrap.appendChild(dt);
      wrap.appendChild(dd);
      vals.appendChild(wrap);
    });
    div.appendChild(vals);
    return div;
  }

  // A collapsed group is a sample of at most 250 rows (webui's
  // `_APPLY_GROUP_SAMPLE`). After a write the rest are in its journal;
  // a preview writes none (its scratch journal is deleted, and
  // `journal_path` is null), so it must not point at one.
  function sampleNote(group, result) {
    const head = "Showing " + group.records.length + " of " + group.count +
      " — the rest are the same shape";
    if (result && result.journal_path) return head + ", and all of them are in the journal file.";
    if (result && result.dry_run) {
      return head + ". A preview writes no journal; a write records every address in one.";
    }
    return head + ".";
  }

  function groupElement(group, result) {
    const details = document.createElement("details");
    details.className = "apply-journal-group";
    const summary = document.createElement("summary");
    const chevron = document.createElement("span");
    chevron.className = "chevron";
    chevron.textContent = "▸";
    summary.appendChild(chevron);
    const strong = document.createElement("strong");
    strong.textContent = String(group.count);
    summary.appendChild(strong);
    summary.appendChild(document.createTextNode(
      " " + group.label + " — expand to see " +
      (group.records.length < group.count ? "a sample" : "all")));
    details.appendChild(summary);

    const body = document.createElement("div");
    body.className = "apply-journal-group-body";
    if (group.records.length < group.count) {
      const note = document.createElement("div");
      note.className = "apply-record";
      const desc = document.createElement("span");
      desc.className = "apply-record-desc";
      desc.textContent = sampleNote(group, result);
      note.appendChild(desc);
      body.appendChild(note);
    }
    group.records.forEach((r) => body.appendChild(recordCard(r, false)));
    details.appendChild(body);
    return details;
  }

  function chip(label, value, cls) {
    const span = document.createElement("span");
    span.className = "apply-chip" + (cls ? " " + cls : "");
    const key = document.createElement("span");
    key.className = "apply-chip-key";
    key.textContent = label;
    span.appendChild(key);
    span.appendChild(document.createTextNode(String(value)));
    return span;
  }

  // Step 3's two lines after a write: what was written and confirmed, and
  // what didn't land -- or that nothing failed to.
  function renderWriteResult(result) {
    const box = el("apply-write-result");
    const show = !!(result && !result.dry_run) && writeOfThisMode() && run.state !== "running";
    box.hidden = !show;
    if (!show) return;
    const c = result.counts;
    const confirmed = c.written - c.mismatch;
    el("apply-write-line").textContent = c.written + " written · " + confirmed +
      " read back and confirmed";
    const problems = [];
    if (result.aborted) {
      problems.push("The desk stopped answering part way (" + (result.abort_reason || "no reason given") +
        "): what landed is in History, and Undo takes it off again.");
    }
    const mismatched = (result.flagged || []).filter((r) => r.status === "mismatch").map((r) => r.address);
    const unread = (result.flagged || []).filter((r) => r.status !== "mismatch").map((r) => r.address);
    if (c.mismatch) {
      problems.push(c.mismatch + " didn't land: " + mismatched.slice(0, 6).join(", ") +
        (mismatched.length > 6 ? " and " + (mismatched.length - 6) + " more" : "") + ".");
    }
    if (c.unreadable) {
      problems.push(c.unreadable + " couldn't be read back: " + unread.slice(0, 6).join(", ") +
        (unread.length > 6 ? " and " + (unread.length - 6) + " more" : "") + ".");
    }
    const review = run.review;
    const moved = review && review.proof && (review.proof.moved || []).length;
    if (moved) {
      problems.push(review.proof.moved.length + " unrelated address(es) changed while it wrote: " +
        review.proof.moved.slice(0, 6).join(", ") + ".");
    }
    let sub;
    if (problems.length) sub = problems.join(" ");
    else if (run.kind === "apply") sub = "Nothing failed to land. The desk now matches the plan.";
    else {
      const strips = (review && (review.strips || []).concat(review.released || [])) || [];
      sub = "Nothing failed to land. " + (strips.length ? strips.join(", ") + " now match the change" :
        "The change is on the desk") + (review && review.proof && review.proof.read
        ? "; nothing else moved." : ".");
    }
    el("apply-write-sub").textContent = sub;
    box.classList.toggle("is-bad", problems.length > 0);
  }

  function renderResult(ownMode) {
    const result = run.result;
    const mine = ownMode !== false && run.kind === runKindNow();
    renderWriteResult(mine ? result : null);
    const slot = run.preview ? el("apply-preview-slot") : el("apply-write-slot");
    if (resultPanel.parentNode !== slot) slot.appendChild(resultPanel);
    resultPanel.hidden = !result || !mine;
    if (!result || !mine) return;

    const c = result.counts;
    el("apply-result-summary").textContent = result.dry_run
      ? "All " + c.would_change + " changes, address by address →"
      : "The journal: all " + c.total + " addresses, as written →";
    el("apply-watch-footer").hidden = !!result.dry_run || run.kind !== "apply";

    // `apply.ApplyResult.summary()`, exactly as the command prints it.
    const summaryEl = el("apply-summary-line");
    summaryEl.textContent = result.summary || "";
    summaryEl.classList.toggle("is-bad", !!result.aborted || !!c.mismatch);

    const chips = el("apply-chips");
    chips.textContent = "";
    chips.appendChild(chip("evaluated", c.total));
    if (result.dry_run) chips.appendChild(chip("would change", c.would_change));
    else chips.appendChild(chip("written", c.written));
    if (c.mismatch) chips.appendChild(chip("mismatch", c.mismatch, "is-bad"));
    if (c.unreadable) chips.appendChild(chip("unreadable", c.unreadable, "is-warn"));
    if (c.cleaned) chips.appendChild(chip("output sockets disconnected", c.cleaned, "is-warn"));
    // Surfaced in its own right, not only inside the summary paragraph: a
    // desk that duplicates datagrams is the condition that made the
    // 2026-09-21 journal worthless, and a run that says nothing about it
    // cannot be told from a run where it did not happen.
    chips.appendChild(chip("replies discarded", result.replies_discarded,
                           result.replies_discarded ? "is-warn" : ""));
    if (result.replies_used) {
      chips.appendChild(chip("of those, used as a late answer", result.replies_used));
    }

    // The journal's warnings and notes are dock findings: one line here.
    summaryLine(el("apply-result-findings"),
                severityCounts((run && run.findings) || []), "This run: ");

    // Mismatch and unreadable expanded and coloured -- these are the rows
    // somebody has to read. Everything else collapsed behind a count.
    const flagged = el("apply-journal-flagged");
    flagged.textContent = "";
    (result.flagged || []).forEach((r) => flagged.appendChild(recordCard(r, true)));

    const groups = el("apply-journal-groups");
    groups.textContent = "";
    (result.groups || []).forEach((g) => groups.appendChild(groupElement(g, result)));

    const note = el("apply-journal-note");
    note.textContent = "";
    if (result.journal_path) {
      // The file's name, not its absolute path; the whole
      // path is on its title. Undo, in History, reverses it.
      note.appendChild(document.createTextNode("Journal: "));
      const path = document.createElement("code");
      path.textContent = String(result.journal_path).split(/[\\/]/).pop();
      path.title = result.journal_path;
      note.appendChild(path);
      note.appendChild(document.createTextNode(
        ". Undo, in History, puts every address back."));
    } else if (result.dry_run) {
      note.textContent = "A preview: nothing was written.";
    } else {
      note.textContent =
        "Nothing was written: the run stopped before touching an address. The log says why.";
    }
  }

  el("apply-to-watch").addEventListener("click", () => SP.activateMode("watch"));

  // A different show is a different plan and a different journal.
  SP.onBundleChange(() => {
    run = { state: "idle" };
    // What the last apply said was about the last show's plan.
    publishRunFindings([]);
    reviewedFor = null;
    AV.setFresh(null);
    armCheckbox.checked = false;
    renderSubject();
    renderRun();
    fetchPreflight();
    AV.refreshStack().then(updateArmState);
  });

  // A different desk (the bundle bar's Change…): this screen names the new
  // one, and the tick given for the old one is withdrawn -- consent to
  // write to the primary is not consent to write to the backup. The
  // preview stays on screen but no longer arms (its key carries the desk),
  // and History is redrawn for the new desk's rows.
  SP.onConsoleChange(() => {
    armCheckbox.checked = false;
    renderSubject();
    renderPatchModelNote();
    updateArmState();
    AV.refreshStack().then(updateArmState);
  });
  // A Ping taught the server this desk's serial: History can now say
  // exactly which rows it wrote.
  SP.onPing(() => { AV.refreshStack().then(updateArmState); });

  // Coming into Apply re-reads the pre-flight: a build on step 04 of this
  // same page may have just replaced plan.json, and the pre-flight on
  // screen -- and its `plan_sha256`, which a confirmed apply sends -- must
  // be about the plan there now.
  SP.onModeChange((mode) => {
    if (mode === "apply") fetchPreflight();
  });
  // A build on step 04 replaced plan.json: step 04 took this pre-flight's
  // findings off the dock when the build started (they were about the old
  // plan), and this puts the new plan's back.
  if (SP.onPlanBuilt) SP.onPlanBuilt(fetchPreflight);

  // The stale-page banner went up: every write control here goes off with
  // it, and the tick goes.
  SP.onStale(() => {
    armCheckbox.checked = false;
    updateArmState();
  });

  // ---- first paint -------------------------------------------------------
  renderSubject();
  setPatchSource(patchSource);
  setApplyMode(applyMode);
  fetchPreflight();
  AV.refreshStack().then(updateArmState);
  if (run.state === "running") poll();
  else publishRunFindings(run.findings);
})();
