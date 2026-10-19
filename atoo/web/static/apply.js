(() => {
  "use strict";

  // Apply (version H)
  // -- loaded by the shell (`/`) after shell.js, setup.js and amend.js,
  // and coded against `window.Atoo`.
  //
  // THIS IS THE ONE SCREEN IN ATOO THAT WRITES TO A CONSOLE, and
  // there is exactly ONE arming control on it: `#apply-arm-checkbox`,
  // which is `--confirm`. That is a deliberate decision, and the reason
  // Amend is a mode of this screen rather than a page of its own --
  // one console, one arming discipline, one journal, one pre-flight, one
  // place to review when any of it changes. A flow that seems to want a
  // second arming control is a flow to rethink.
  //
  // Both modes are the same four steps:
  //
  //   1 What will be written -- the plan and its pre-flight verify (Full
  //     build), or the change (Patch), with the options folded under them;
  //   2 Preview -- one button; its result fills the box, the desk drawn as
  //     scribble strips (`desk_view.py`, sent down as `drawing` / `desk`).
  //     It is the one place any preview is drawn: the write's or, after
  //     History's Preview undo, the undo's -- whichever was asked for last;
  //   3 Arm and write, or Arm and undo -- the checkbox, then ONE red button
  //     under its own header, enabled only after a preview of exactly what it
  //     will do; its result shows in this box;
  //   4 History -- the journal stack; the newest standing write on this desk
  //     carries Preview undo, and the write just made sits at the top,
  //     highlighted.
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
  // Patch is a MODE of this screen, not a second one. The
  // `Full build | Patch` switch changes what Preview and the write button
  // run -- `atoo apply`, or `atoo patch` with a typed change -- and nothing
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
  //     a preview by exactly the addresses that would not really change. The
  //     server sends the answer per record, and the counts.
  //   * It does not word the summary. `apply.ApplyResult.summary()` is
  //     sent down as a string and printed, so this page and the terminal
  //     cannot describe the same run differently.
  //   * It does not offer a second console field. There is one console,
  //     the bundle bar's -- resolved at startup, editable only there
  //     -- and this screen names it beside every
  //     write. Every write request carries the desk this page names
  //     (`expected_console`), so a page left open while the address was
  //     changed elsewhere is refused rather than writing to a desk it does
  //     not show; and changing the desk disarms the checkbox.
  //
  // And every write request says WHAT this page reviewed (from a desk
  // session, 2026-09-24: a tab kept open across a server restart onto a
  // different bundle copy): `expected_bundle`, the bundle it shows, plus
  // `expected_plan_sha256` (the plan.json the pre-flight verified) for an
  // apply, `expected_review_id` (the review drawn in step 2) for a patch,
  // and `expected_undo_id` (the History row marked top) for an
  // undo. The server refuses a confirmed write when any of them is not what
  // it would write (409, `stale`); before sending, this file asks
  // `SP.checkServer()` whether the server behind the page is still the one
  // that drew it.

  const SP = window.Atoo;
  const el = (id) => document.getElementById(id);

  const subject = el("apply-subject");
  const consoleLine = el("apply-console-line");
  const planStale = el("apply-plan-stale");
  const planStaleText = el("apply-plan-stale-text");
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
  const bypassNote = el("apply-bypass-note");
  const undoLocked = el("undo-locked");
  const message = el("apply-message");
  const runPanel = el("apply-run-panel");
  const runLabel = el("apply-run-label");
  const resultPanel = el("apply-result-panel");
  const progressLine = el("apply-progress-line");
  const previewNote = el("apply-preview-note");
  const staleNote = el("apply-stale");
  // Full build | Patch: a segmented control (shell.js, wireSeg).
  const modeSeg = SP.wireSeg(el("apply-mode-seg"), (mode) => setApplyMode(mode));
  const allowToggle = el("amend-allow-toggle");
  const allowSub = el("amend-allow-sub");
  const amendAllow = el("amend-allow");
  const patchText = el("patch-change-text");
  const patchModelNote = el("patch-model-note");
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
  // The server has one runner, and each run replaces the last one's status.
  // The page keeps three views of it: `latest` is whatever the runner holds,
  // `run` is the apply, patch or confirmed undo that steps 2 and 3 are
  // drawn from, and `undoView` is the last undo preview. A preview of an undo
  // reads and writes nothing, so it replaces neither step's account of the
  // write. Step 2 is ONE box for both previews: `lastPreview` says which was
  // asked for last, and that is the one drawn.
  let run = { state: "idle" };
  let latest = run;
  let undoView = null;
  let lastPreview = "write";   // "write" | "undo"
  let undoDesk = null;         // the desk the undo preview was asked of
  take(readStartup().apply || { state: "idle" });
  let pollTimer = null;
  let applyMode = run.kind === "patch" ? "amend" : "full";
  // What step 1 held when the last clean preview was started, and when
  // the run in flight was. Write is offered only for what a person has just
  // previewed -- and for a patch the server refuses any other
  // (409), so this is the courtesy and that is the guard.
  let reviewedFor = null;
  let startedFor = null;

  // Take a status from the runner and put it where it belongs (see above). A
  // write that has been sent -- anything that is not a preview -- changes
  // what an undo would reverse, so it ends the last undo preview; so does a
  // fresh preview of the write, which the Preview box then shows instead.
  function take(status) {
    latest = status;
    if (status.kind === "undo") {
      if (status.preview) {
        undoView = status;
        lastPreview = "undo";
        if (undoDesk === null) undoDesk = deskLabel();
      } else {
        run = status;
        undoView = null;
        lastPreview = "write";
      }
    } else {
      run = status;
      undoView = null;
      lastPreview = "write";
    }
  }

  function isDemo() {
    return !!SP.console().demo;
  }

  function runKindNow() {
    return applyMode === "amend" ? "patch" : "apply";
  }

  function allowStrips() {
    if (!allowToggle.checked) return [];
    return (amendAllow.value || "").split(",").map((x) => x.trim()).filter(Boolean);
  }

  function cleanValue() {
    return cleanToggle.checked ? ((cleanSockets.value || "").trim() || null) : null;
  }

  function amendInputs() {
    return { change: (patchText.value || "").trim(), allow_strips: allowStrips() };
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
  // review key carries the console too.
  function stepOneKey() {
    if (applyMode === "full") {
      return JSON.stringify({ kind: "apply", skip: !!skipVerify.checked, clean: cleanValue(),
        plan: (preflight && preflight.plan_sha256) || null, console: deskLabel() });
    }
    return JSON.stringify({ kind: "patch", inputs: amendInputs(), console: deskLabel() });
  }

  // A preview is one worth arming only when the command itself said so.
  // For a patch: it ran clean, it found something to write, and
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

  // A locked control's reason, beside it: the shared
  // `.lock-reason` draws the bold "Locked:" before it, so the words here
  // start lower-case, as the guide's own examples do.
  function setLocked(node, reason) {
    node.textContent = reason || "";
    node.hidden = !reason;
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
    link.className = "btn btn-quiet findings-summary-link";
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
    link.className = "btn btn-quiet findings-summary-link";
    link.textContent = "show in Findings →";
    link.addEventListener("click", () => {
      const mine = SP.findings().filter((f) =>
        f._producer === "apply-preflight" && f.severity === "info");
      if (!(SP.showFindings && SP.showFindings(mine)) && SP.revealDock) SP.revealDock();
    });
    target.appendChild(link);
  }

  // A plan older than the files it was built from is previewed and applied
  // as it is -- an engineer may mean that -- but never without saying so,
  // here beside the plan and in the dock's verdict. The same freshness the
  // Plan tile on Build reads, so the screens cannot disagree.
  function renderPlanStale() {
    const fresh = SP.planFreshness ? SP.planFreshness() : null;
    const isStale = !!fresh && fresh.state === "stale";
    planStale.hidden = !isStale;
    planStaleText.textContent = isStale
      ? SP.stalePlanWhat(fresh) + " changed after this plan was built. Rebuild it on Build step 04 " +
        "so the edit reaches the desk, or apply it as it is if the edit is not meant for the desk."
      : "";
  }
  SP.onBuildChange(renderPlanStale);

  function renderPreflight() {
    renderPlanStale();
    const inputNote = el("apply-preflight-input-note");
    inputNote.hidden = true;
    if (!preflight) {
      // Not run is a state, neutral grey.
      preflightBadge.textContent = "Not run";
      preflightBadge.className = "state";
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
    // A severity tag (§6): green when clean, the worst
    // severity's colour otherwise. Blue is information only.
    preflightBadge.textContent = errors + " error" +
      (errors === 1 ? "" : "s") + " · " + warnings + " warning" + (warnings === 1 ? "" : "s");
    preflightBadge.className = "sev " +
      (errors ? "sev-error" : (warnings ? "sev-warning" : "sev-ok"));
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

  // The read in flight, so a caller that needs the pre-flight (the preview
  // sends the plan it verified) can wait for exactly that answer. Null
  // when none is under way.
  let preflightLoading = null;
  let preflightSeq = 0;

  function fetchPreflight() {
    const mine = ++preflightSeq;
    const loading = loadPreflight(mine).then(() => {
      if (preflightLoading === loading) preflightLoading = null;
    });
    preflightLoading = loading;
    return loading;
  }

  async function loadPreflight(mine) {
    let answer = null;
    // Apply writes the open show's own plan.json, and the server refuses a
    // write with no show open: with none there is no pre-flight to ask for,
    // and asking would only put a 404 in the browser's console.
    if (SP.bundle()) {
      try {
        const r = await fetch("/api/apply/preflight");
        answer = r.ok ? await r.json() : null;
      } catch (e) {
        answer = null;
      }
    }
    // A newer read was asked for while this one was away: its answer is the
    // one to draw, not this one arriving late.
    if (mine !== preflightSeq) return;
    preflight = answer;
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
  // setting up. Said at INFO before Preview is pressed, not after it fails.
  function patchBlocker() {
    if (applyMode !== "amend") return "";
    const model = preflight && preflight.patch_model;
    if (model && model.ready === false) {
      return "INFO A typed change is compiled by a model, and none is set up here (" +
        (model.why || "no model configured") + ")." +
        (isDemo() ? " The Demo previews a Full build only until one is." : "");
    }
    return "";
  }

  function renderPatchModelNote() {
    const why = patchBlocker();
    patchModelNote.textContent = why;
    patchModelNote.hidden = !why;
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
    const running = latest.state === "running";
    const amending = applyMode === "amend";
    const noChange = amending && !(patchText.value || "").trim();
    const blockedByPreflight = !amending && !!(preflight && preflight.errors && !skipping);
    const previewed = previewIsCurrent();
    const stalePage = SP.isStale();
    const hasDesk = demo || !!desk.address;
    const blocker = patchBlocker();

    // Step 2's Preview.
    previewBtn.disabled = stalePage || !hasBundle || !hasDesk || running || noChange || !!blocker;
    // Primary marks the next action now: once this preview
    // is current, Write is next, so Preview drops to secondary and says
    // "Preview again". It is primary again when the preview goes stale --
    // step 1 or the desk changed, it was refused, or a write spent it.
    // While the box shows the undo preview, this is the way back to the
    // write's: "Preview write", an outline button.
    const previewedNow = previewIsCurrent();
    const undoOnShow = undoShown();
    previewBtn.className = "btn " + (previewedNow || undoOnShow ? "btn-secondary" : "btn-primary");
    previewBtn.textContent = undoOnShow ? "Preview write" : previewedNow ? "Preview again" : "Preview";
    previewNote.textContent = undoOnShow
      ? "Showing the undo preview that History asked for. Preview write reads " +
        (amending ? "the change" : "the plan") + " again."
      : !amending
      ? "Reads every address the plan would write on " + deskWords() +
        ", and draws the desk as it will be. Writes nothing."
      : "Reads which strips are free on " + deskWords() + ", has the model compile the " +
        "change, and shows what would and wouldn't be written. Writes nothing.";
    let previewReason = "";
    if (stalePage) previewReason = "this page is out of date — reload it (see the banner at the top)";
    else if (!hasBundle) previewReason = "no show bundle open";
    else if (!hasDesk) previewReason = "no console address — set one in the bundle bar";
    else if (running) previewReason = "wait for the current run to finish";
    else if (blocker) previewReason = "no model is set up to compile a typed change (see step 1)";
    else if (noChange) previewReason = "type the change in step 1 first";
    setLocked(el("apply-preview-reason"), previewReason);
    // Locked, the reason is the line to read; what Preview does comes back
    // once it can be pressed.
    previewNote.hidden = !!previewReason;
    // A preview that was of something else than step 1 holds now.
    staleNote.hidden = undoOnShow ||
      !(reviewedFor && reviewedFor !== stepOneKey() && previewIsWritable(run));

    // Step 3's Arm and Write. Every locked control on this screen says
    // why beside it, after the shared "Locked:".
    const canArm = !demo && !stalePage && hasBundle && !!desk.address && !running;
    let reason = "";
    if (demo) {
      reason = "writing is switched off in the Demo show. " +
        "Choose a console address in the bar to write to a real desk.";
    } else if (stalePage) reason = "this page is out of date — reload it (see the banner at the top)";
    else if (!hasBundle) reason = "no show bundle open — nothing to write";
    else if (!desk.address) reason = "no console address — set one in the bundle bar";
    else if (blockedByPreflight) {
      reason = "the pre-flight verify has " + preflight.errors + " error(s), and a " +
        "full build refuses a plan in this state. Fix it, or tick Skip the pre-flight verify " +
        "under Options to write it anyway.";
    } else if (running) reason = "wait for the current run to finish";
    else if (!previewed && writeOfThisMode() && run.state === "done") {
      reason = "already written; preview again before another write";
    } else if (!previewed) {
      const kind = runKindNow();
      if (run.kind === kind && run.preview && run.review && (run.review.blocked ||
          (run.review.collisions || []).length)) {
        reason = "the last preview refused this change — see step 2. Nothing can be written " +
          "until it previews clean.";
      } else if (run.kind === kind && run.preview && run.review &&
                 !(run.review.to_write || []).length) {
        reason = "the last preview found nothing to write";
      } else if (reviewedFor && reviewedFor !== stepOneKey()) {
        reason = "step 1 or the console changed since the preview. Preview again.";
      } else {
        reason = "preview first. Write unlocks once step 2 shows what it will do.";
      }
    } else if (!armCheckbox.checked) reason = "tick Arm first";
    setLocked(disabledReason, reason);
    // Armed past a pre-flight with errors: not a lock, a warning under the row.
    const bypass = !demo && !amending && !!(preflight && preflight.errors && skipping) && previewed &&
      armCheckbox.checked && !running;
    bypassNote.textContent = bypass
      ? "Pre-flight errors skipped: this writes a plan nothing has agreed is applicable." : "";
    bypassNote.hidden = !bypass;

    // Step 3 holds Arm and ONE action. Under an undo the tick is offered only
    // once there is an undo preview worth acting on.
    const undoStep = step3IsUndo();
    const undoable = AV.hasUndoable();
    const undoCurrent = undoPreviewCurrent();
    const undoGoes = undoCurrent ? undoCounts(undoView.result.undo).back : 0;
    const canArmUndo = canArm && undoCurrent && undoGoes > 0;
    armCheckbox.disabled = undoStep ? !canArmUndo : !canArm;
    if (demo) armCheckbox.checked = false;
    runBtn.disabled = !canArm || blockedByPreflight || !previewed || !armCheckbox.checked;
    runBtn.textContent = amending ? "Write changes to console" : "Write to console";

    // Undo: a write, armed by the same checkbox, and only for the newest
    // standing write on this desk, after its own preview. Its preview is not
    // a write: the History row asks for it, and needs no tick.
    undoRunBtn.disabled = !canArmUndo || !armCheckbox.checked;
    let rowReason = "";
    if (demo) {
      rowReason = "undo is switched off in the Demo show";
    } else if (stalePage) rowReason = "this page is out of date — reload it";
    else if (!hasBundle) rowReason = "no show bundle open";
    else if (!desk.address) rowReason = "no console address — set one in the bundle bar";
    else if (running) rowReason = "wait for the current run to finish";
    let undoReason = rowReason;
    if (demo) {
      undoReason = "undo is switched off in the Demo show. " +
        "Choose a console address in the bar to write to a real desk.";
    } else if (undoReason) { /* said above */ }
    else if (!undoable) {
      undoReason = run.kind === "undo" && !run.preview && run.state === "done"
        ? "every write recorded on this desk has been undone"
        : "nothing to undo on this desk";
    } else if (!undoCurrent) {
      undoReason = undoView && undoView.preview && undoView.state === "done"
        ? "preview the undo again" : "preview the undo first";
    } else if (!undoGoes) undoReason = "nothing in the preview would go back";
    else if (!armCheckbox.checked) undoReason = "tick Arm first";
    setLocked(undoLocked, undoReason);
    AV.setUndoUi(rowReason, undoShown());

    // Say what the tick is for, and that it is spent.
    const armNote = el("apply-tick-note");
    const sent = run.state === "done" && !run.preview && (run.kind === "undo" || writeOfThisMode());
    const what = undoStep ? "undo" : "write";
    armNote.textContent = armCheckbox.checked
      ? "Armed. The next " + what + " goes to the desk. It clears after it."
      : sent && armCheckbox.disabled
        ? "Cleared. The tick is spent after each write or undo."
        : "Arms the one action below. It clears after it, and whenever you preview something else.";
    armNote.classList.toggle("is-armed", armCheckbox.checked);

    renderStepThreeView();
    renderSteps();
  }

  // The four steps' numbers and state tags: the number circle takes
  // is-current / is-done; the step's
  // state, when it has one, is a `.state` tag on the right of its header.
  // What a step does is its notation, which does not change.
  function setStep(n, cls, state, tone) {
    const step = el(n === 4 ? "journal-stack-panel" : "apply-step-" + n);
    step.classList.remove("is-current", "is-done", "is-waiting");
    if (cls) step.classList.add(cls);
    const no = el("apply-step-" + n + "-no");
    no.classList.remove("is-current", "is-done");
    if (cls === "is-current" || cls === "is-done") no.classList.add(cls);
    const tag = el("apply-step-" + n + "-state");
    if (!tag) return;
    tag.textContent = state || "";
    tag.className = "state" + (tone ? " " + tone : "");
    tag.hidden = !state;
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
    let t1 = "";
    if (applyMode === "full" && preflight) {
      if (preflight.errors) { s1 = "Pre-flight failed"; t1 = "is-err"; }
      else if (preflight.warnings) { s1 = "Pre-flight warnings"; t1 = "is-warn"; }
      else { s1 = "Pre-flight passed"; t1 = "is-ok"; }
    }
    // Step 1 is done once it holds something writable: a plan the
    // pre-flight passed, or a change typed.
    let ready1 = false;
    if (applyMode === "full") ready1 = !!(preflight && (!preflight.errors || skipVerify.checked));
    else ready1 = !!(patchText.value || "").trim();
    // Not green while Preview is locked by something step 1 says (no model).
    ready1 = ready1 && !patchBlocker();
    setStep(1, previewed || written || ready1 ? "is-done" : "is-current", s1, t1);

    let s2 = "";
    let t2 = "";
    if (ownPreview && running) { s2 = "Reading"; t2 = "is-live"; }
    else if (ownPreview && run.state === "failed") { s2 = "Stopped"; t2 = "is-err"; }
    else if (ownPreview && run.state === "done") {
      const read = readCount(run);
      s2 = read != null ? "Read " + read + " addresses" : "Done";
      t2 = "is-ok";
    }
    // Where the preview read: beside step 2's Result, in meta type.
    el("apply-review-on").textContent = ownPreview && run.state === "done"
      ? "read on " + (run.on || deskWords()) : "";
    // One brass circle at a time: step 2 is current only once step 1 is done.
    // The Preview box shows one preview: when it is the undo's, its tag says so.
    let c2 = previewed || written ? "is-done" : (ready1 ? "is-current" : "");
    if (undoShown()) {
      const v = undoVerdict(undoView);
      s2 = undoView.state === "running" ? "Reading"
        : undoView.state === "failed" ? "Stopped" : "Undo preview \u00b7 " + v.text;
      t2 = undoView.state === "running" ? "is-live"
        : undoView.state === "failed" ? "is-err" : v.state;
      c2 = undoView.state === "done" ? "is-done" : "is-current";
    }
    setStep(2, c2, s2, t2);

    let s3 = "";
    let t3 = "";
    let c3 = "is-waiting";
    if (written && running) { s3 = "Writing"; t3 = "is-live"; c3 = "is-current"; }
    else if (written && run.result && !run.result.dry_run) {
      const bad = run.result.aborted || run.result.counts.mismatch || run.result.counts.unreadable;
      s3 = bad ? "Written, with problems" : "Written and confirmed";
      t3 = bad ? "is-err" : "is-ok";
      c3 = bad ? "is-current" : "is-done";
    } else if (written && run.state === "failed") { s3 = "Stopped"; t3 = "is-err"; c3 = "is-current"; }
    else if (previewed) { s3 = isDemo() ? "" : "Ready"; t3 = "is-ok"; c3 = "is-current"; }
    if (armCheckbox.checked && previewed && !isDemo() && !written) { s3 = "Armed"; t3 = "is-err"; }
    if (step3IsUndo()) [s3, t3, c3] = undoStepThreeTag();
    setStep(3, c3, s3, t3);
    setStep(4, "", null);
  }

  function readCount(r) {
    if (r.kind === "apply") return r.result && r.result.counts ? r.result.counts.total : null;
    const timing = r.review && r.review.timing;
    return timing && timing.desk_addresses != null ? timing.desk_addresses : null;
  }

  // ---- Full build | Patch -------------------------------------------------

  function setApplyMode(mode) {
    applyMode = mode === "amend" ? "amend" : "full";
    modeSeg.select(applyMode);
    document.querySelectorAll("[data-apply-only]").forEach((node) => {
      node.hidden = node.dataset.applyOnly !== applyMode;
    });
    // Step 1's notation says what that step holds in this mode.
    el("apply-step-1-notation").textContent = applyMode === "full"
      ? "The whole plan · reads nothing" : "One change · reads nothing";
    const hint = el("apply-mode-hint");
    hint.textContent = "";
    const b = document.createElement("strong");
    b.textContent = applyMode === "full" ? "Full build" : "Patch";
    hint.appendChild(b);
    hint.appendChild(document.createTextNode(applyMode === "full"
      ? " sets a desk you own to the plan, writing only what differs."
      : " writes one change to a desk that's already in use, and moves nothing else."));
    // Switching what the write button means disarms it. A tick given for
    // a full build is not consent to a patch, or the other way round.
    armCheckbox.checked = false;
    renderPatchModelNote();
    renderRun();
  }

  // Every signpost -- Build step 02, the full-build side of this screen --
  // calls this one function, so a new one cannot grow its own opinion of
  // what "go and amend" means.
  function gotoAmend() {
    SP.activateMode("apply");
    setApplyMode("amend");
  }

  // Build's "Apply the difference": this screen with Full build chosen and
  // the preview started, nothing armed. The preview's "will change" count is
  // the difference; a Full build then writes exactly those addresses. A
  // preview that cannot start (no desk named, a run in flight) is left to
  // say why beside its own button.
  // The preview names the plan the pre-flight verified, so it starts only
  // once that read has come back: on a slow load it would otherwise go
  // out with no plan named. If the read fails, the page is left as if
  // Apply had been opened and nothing pressed, and says so.
  async function applyTheDifference() {
    SP.activateMode("apply");
    setApplyMode("full");
    updateArmState();
    // Coming into Apply has asked for the pre-flight; if the page was
    // already on Apply, ask now.
    if (!preflightLoading) fetchPreflight();
    while (preflightLoading) await preflightLoading;
    if (SP.currentMode() !== "apply") return;
    if (!preflight) {
      showMessage("Preview is ready when the desk has been read.");
      return;
    }
    updateArmState();
    if (!previewBtn.disabled) start(false);
  }
  SP.applyTheDifference = applyTheDifference;

  // Step 1 changed: a tick given for what it held before is withdrawn.
  function stepOneEdited() {
    if (reviewedFor && reviewedFor !== stepOneKey()) armCheckbox.checked = false;
    updateArmState();
  }

  patchText.addEventListener("input", stepOneEdited);

  document.querySelectorAll("[data-goto-amend]").forEach((b) => b.addEventListener("click", gotoAmend));
  SP.gotoAmend = gotoAmend;
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
    return r.preview ? el("apply-log-slot-2") : el("apply-log-slot-3");
  }

  function renderRun() {
    // State tags (§6): Done is good, Failed an error, Running live.
    const labels = {
      running: ["Running", "is-live"],
      done: ["Done", "is-ok"],
      failed: ["Failed", "is-err"],
    };
    // A run belongs to the mode that started it. A full
    // build's log is not shown under Patch, nor a patch's under Full build;
    // an undo (its own panels, in steps 2 and 3, under both modes) and a run
    // still in flight show in either.
    const ownMode = run.kind === "undo" || run.state === "running" ||
      (run.kind === "apply") === (applyMode === "full");
    const slot = slotFor(run);
    if (progressLine.parentNode !== slot) slot.appendChild(progressLine);
    if (runPanel.parentNode !== slot) slot.appendChild(runPanel);
    // An undo's command, log and state are drawn by its own panels
    // (`renderUndoView`, `renderUndoBanner`), which say Partly undone where
    // this would say Done.
    runPanel.hidden = run.state === "idle" || !run.state || !ownMode || run.kind === "undo";
    const label = labels[run.state] || ["Idle", ""];
    el("apply-run-state").textContent = label[0];
    el("apply-run-state").className = "state" + (label[1] ? " " + label[1] : "");
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
    progressLine.hidden = run.state !== "running" || !ownMode || run.kind === "undo";
    progressLine.textContent = lines.length ? lines[lines.length - 1] : "Starting…";

    // One runner carries apply, patch and undo, and a write never switches
    // desks part way through: the bar's Change button is off while one
    // runs. The server refuses the edit regardless (409).
    SP.setConsoleLock(latest.state === "running"
      ? (latest.kind === "apply" && !latest.preview ? "An " : "A ") +
        (runLabelFor(latest.kind, latest.preview) || "write").toLowerCase() +
        " is running -- the console " +
        "cannot change until it finishes."
      : "");
    const ownReview = run.kind === "patch" && run.kind === runKindNow() ? run.review : null;
    AV.renderReview(ownReview);
    AV.renderProgress(run);
    renderReview(ownMode);
    renderResult(ownMode);
    renderUndoView();
    updateArmState();
  }

  // ---- Undo: the preview in step 2, Undo itself in step 3 ------------------
  // History's Preview undo asks for an undo preview; it is drawn in step 2,
  // the one Preview box, in place of the write's account while it is the
  // preview asked for last (`lastPreview`). Step 3 then holds Arm and Undo
  // in place of Write. Everything here is drawn from `result.undo` on the
  // runner's status and sends no request.

  function node(tag, cls, words) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (words != null) n.textContent = words;
    return n;
  }

  const UNDO_VERDICT = {
    "goes-back": "goes back",
    "went-back": "put back",
    "already-back": "already back",
    "changed-since": "changed since",
    "no-earlier-value": "no earlier value",
    unreadable: "could not be read",
    "did-not-land": "did not land",
  };

  // Rows that are left as they are, or did not land, read as a problem.
  const UNDO_HELD = ["changed-since", "no-earlier-value", "unreadable", "did-not-land"];

  function undoValue(v) {
    if (v === null || v === undefined) return "(none)";
    if (typeof v === "string") return JSON.stringify(v);
    return String(v);
  }

  // What the payload's counts mean to the person reading them. "Stays" is
  // what an undo leaves because the desk has moved on (changed since, or
  // could not be read); "no prior" is a control that had no earlier value to
  // go back to, said apart as an info note.
  function undoCounts(payload) {
    const c = (payload && payload.counts) || {};
    return {
      total: c.total || 0,
      back: c["goes-back"] || 0,
      wentBack: c["went-back"] || 0,
      already: c["already-back"] || 0,
      stays: (c["changed-since"] || 0) + (c.unreadable || 0),
      noPrior: c["no-earlier-value"] || 0,
      didNot: c["did-not-land"] || 0,
    };
  }

  // The verdict of an undo preview: green Ready to undo, yellow N will stay
  // (a partial undo may proceed), red Can't undo (nothing would go back, or
  // the command refused). `state` is for a step's tag, `sev` for the tag in
  // the panel, `tone` for the panel's edge.
  function undoVerdict(view) {
    const payload = view && view.result && view.result.undo;
    const bad = { text: "Can't undo", state: "is-err", sev: "sev-error", tone: "is-err" };
    if (!payload || view.state === "failed") return bad;
    const n = undoCounts(payload);
    if (!n.back) return bad;
    if (n.stays) {
      return { text: n.stays + " will stay", state: "is-warn", sev: "sev-warning", tone: "is-warn" };
    }
    return { text: "Ready to undo", state: "is-ok", sev: "sev-ok", tone: "is-ok" };
  }

  // The Preview box (step 2) is showing the undo preview.
  function undoShown() {
    return lastPreview === "undo" && !!undoView && !!undoView.state && undoView.state !== "idle";
  }

  // Step 3 is Arm and undo: the undo preview is the one shown, or the last
  // run was a confirmed undo and its result is still the news.
  function step3IsUndo() {
    return undoShown() ||
      (run.kind === "undo" && !run.preview && !!run.state && run.state !== "idle");
  }

  // An undo preview can be acted on only while it describes the desk and the
  // newest write it was read for: a write or undo since, another console in
  // the bar, or another newest row, and it is stale -- preview again.
  function undoPreviewCurrent() {
    const v = undoView;
    if (!v || !v.preview || v.state !== "done") return false;
    const payload = v.result && v.result.undo;
    return !!payload && !!payload.journal_id && payload.journal_id === AV.topId() &&
      undoDesk === deskLabel();
  }

  function utcWords(stamp) {
    return String(stamp || "").replace("T", " ").replace(/\.\d+/, "").replace(/\+00:00$/, "");
  }

  function clockWords(epochSeconds) {
    if (!epochSeconds) return "";
    return new Date(epochSeconds * 1000).toISOString().slice(11, 19);
  }

  function lastWord(view) {
    const said = (view.log || []).map((l) => l.trim()).filter(Boolean);
    return said.length ? said[said.length - 1] : "";
  }

  // A strip as the History and the desk name it: its address, and its name
  // where the journal recorded one (a "reset to initialized" row has none).
  function undoStripTag(row) {
    const span = node("span", "strip-tag", row.strip || row.address);
    if (row.strip_name) span.appendChild(node("span", "strip-name", " " + row.strip_name));
    return span;
  }

  function undoTable(heads, rows) {
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const tr = document.createElement("tr");
    heads.forEach((h, i) => tr.appendChild(node("th", i >= heads.length - 2 ? "num" : "", h)));
    thead.appendChild(tr);
    table.appendChild(thead);
    const body = document.createElement("tbody");
    rows.forEach((r) => body.appendChild(r));
    table.appendChild(body);
    const box = node("div", "inset");
    box.appendChild(table);
    return box;
  }

  function subHead(title, count, words) {
    const head = node("div", "sub-head");
    head.appendChild(node("h4", "", title));
    if (count != null) head.appendChild(node("span", "count", String(count)));
    if (words) head.appendChild(node("span", "meta", words));
    return head;
  }

  // What stays as it is: the controls the desk has moved since the write.
  function drawStays(box, rows) {
    box.textContent = "";
    box.hidden = !rows.length;
    if (!rows.length) return;
    box.appendChild(subHead("Stays as it is", rows.length,
      "changed since the write. Undo will not touch it."));
    box.appendChild(undoTable(["Strip", "Control", "Write set", "Desk now"], rows.map((r) => {
      const tr = document.createElement("tr");
      const strip = document.createElement("td");
      strip.appendChild(undoStripTag(r));
      tr.appendChild(strip);
      const control = document.createElement("td");
      control.appendChild(node("span", "readout", r.control || r.address));
      tr.appendChild(control);
      tr.appendChild(node("td", "val num", undoValue(r.written)));
      const now = node("td", "val num stays",
        r.verdict === "unreadable" ? "could not be read" : undoValue(r.now));
      tr.appendChild(now);
      return tr;
    })));
  }

  // Controls the journal holds no earlier value for: said as an info note,
  // naming the strips and controls, not as a refusal.
  function drawNoPrior(box, rows) {
    box.textContent = "";
    box.hidden = !rows.length;
    if (!rows.length) return;
    const head = node("div", "sub-head");
    head.appendChild(node("span", "sev sev-info", "Info"));
    const strips = [];
    const controls = [];
    rows.forEach((r) => {
      if (strips.indexOf(r.strip) < 0) strips.push(r.strip);
      if (r.control && controls.indexOf(r.control) < 0) controls.push(r.control);
    });
    const more = (list, n) => list.slice(0, n).join(", ") + (list.length > n ? " and " + (list.length - n) + " more" : "");
    const words = node("span", "meta");
    words.appendChild(node("b", "", rows.length + " can't be restored"));
    words.appendChild(document.createTextNode(" (" + more(strips, 4) + ": " + more(controls, 3) +
      "). The desk had no earlier value to read, so they stay as the write set them."));
    head.appendChild(words);
    box.appendChild(head);
  }

  // What goes back: one line per control under its strip, folded, with the
  // count on the summary. Open when it is short; long ones show a few
  // strips and a few rows each until "All ... strip by strip" is pressed.
  const BACK_STRIPS = 3;
  const BACK_ROWS = 4;
  let backRows = [];
  let backAll = false;
  let backOpen = null;
  let backAllBtn = null;
  let backHolder = null;

  function drawBackTable() {
    const holder = backHolder;
    if (!holder) return;
    holder.textContent = "";
    const groups = [];
    backRows.forEach((r) => {
      let g = groups.find((x) => x.strip === r.strip);
      if (!g) { g = { strip: r.strip, first: r, rows: [] }; groups.push(g); }
      g.rows.push(r);
    });
    const shownGroups = backAll ? groups : groups.slice(0, BACK_STRIPS);
    const trs = [];
    shownGroups.forEach((g) => {
      const head = document.createElement("tr");
      head.className = "grp";
      const td = document.createElement("td");
      td.colSpan = 3;
      td.appendChild(undoStripTag(g.first));
      td.appendChild(node("span", "meta", " · " + g.rows.length + " control" +
        (g.rows.length === 1 ? "" : "s") + " go back"));
      head.appendChild(td);
      trs.push(head);
      (backAll ? g.rows : g.rows.slice(0, BACK_ROWS)).forEach((r) => {
        const tr = document.createElement("tr");
        const control = document.createElement("td");
        control.appendChild(node("span", "readout", r.control || r.address));
        tr.appendChild(control);
        tr.appendChild(node("td", "val num", undoValue(r.now)));
        tr.appendChild(node("td", "val num", undoValue(r.goes_back_to)));
        trs.push(tr);
      });
      if (!backAll && g.rows.length > BACK_ROWS) {
        const more = document.createElement("tr");
        more.className = "more";
        const td2 = node("td", "", "… and " + (g.rows.length - BACK_ROWS) + " more on this strip");
        td2.colSpan = 3;
        more.appendChild(td2);
        trs.push(more);
      }
    });
    if (!backAll && groups.length > BACK_STRIPS) {
      const rest = groups.slice(BACK_STRIPS).reduce((n, g) => n + g.rows.length, 0);
      const more = document.createElement("tr");
      more.className = "more";
      const td2 = node("td", "", "… and " + (groups.length - BACK_STRIPS) + " more strips (" +
        rest + " more controls)");
      td2.colSpan = 3;
      more.appendChild(td2);
      trs.push(more);
    }
    holder.appendChild(undoTable(["Control", "On the desk now", "Goes back to"], trs));
    if (backAllBtn) {
      backAllBtn.hidden = backAll || (backRows.length <= BACK_ROWS && groups.length <= BACK_STRIPS);
    }
  }

  function drawBack(box, rows) {
    box.textContent = "";
    box.hidden = !rows.length;
    backRows = rows;
    backAll = false;
    if (!rows.length) return;
    const details = document.createElement("details");
    details.id = "undo-back-details";
    details.open = backOpen === null ? rows.length <= 25 : backOpen;
    const summary = document.createElement("summary");
    summary.appendChild(node("h4", "", "Goes back"));
    summary.appendChild(node("span", "count", String(rows.length)));
    const strips = new Set(rows.map((r) => r.strip)).size;
    summary.appendChild(node("span", "meta", "controls on " + strips + " strip" +
      (strips === 1 ? "" : "s") + ": the value on the desk now, and what it goes back to"));
    details.appendChild(summary);
    const holder = node("div", "");
    holder.style.marginTop = "var(--s2)";
    backHolder = holder;
    details.appendChild(holder);
    const all = node("p", "");
    const allBtn = node("button", "btn btn-quiet", "All " + rows.length + " controls, strip by strip →");
    allBtn.type = "button";
    allBtn.addEventListener("click", () => { backAll = true; drawBackTable(); });
    backAllBtn = allBtn;
    all.appendChild(allBtn);
    details.appendChild(all);
    details.addEventListener("toggle", () => { backOpen = details.open; });
    box.appendChild(details);
    drawBackTable();
  }

  // The panel in step 2. The parts that are tables are drawn once per
  // preview (a poll that changes nothing must not close what the person has
  // opened); the tag, the sentence and the notes follow every redraw.
  let undoDrawnKey = null;
  function renderUndoView() {
    const section = el("undo-preview-section");
    const shown = undoShown();
    section.hidden = !shown;
    if (!shown) { undoDrawnKey = null; return; }
    const view = undoView;
    const panel = el("undo-result");
    const payload = view.result && view.result.undo;
    const running = view.state === "running";
    const verdict = running ? { text: "Reading", sev: "", tone: "" } : undoVerdict(view);
    panel.className = "undo-preview" + (verdict.tone ? " " + verdict.tone : "");
    const tag = el("undo-result-state");
    tag.className = "sev big" + (verdict.sev ? " " + verdict.sev : "");
    tag.textContent = verdict.text;
    // The seconds only while it reads: the finished preview says when it read.
    const elapsed = running && view.started_at ? Date.now() / 1000 - view.started_at : null;
    el("undo-result-elapsed").textContent = elapsed != null ? Math.round(elapsed) + " s" : "";
    el("undo-result-elapsed").hidden = elapsed == null;

    // Which write this reverses, and whether it is still the newest one.
    const which = el("undo-result-which");
    const note = el("undo-result-note");
    note.hidden = true;
    which.textContent = "";
    if (payload) {
      which.appendChild(document.createTextNode("Reverses "));
      which.appendChild(node("b", "", payload.kind || "write"));
      which.appendChild(document.createTextNode(
        (payload.timestamp ? ", " + utcWords(payload.timestamp) + " UTC" : "") +
        (AV.topDesk() ? ", on " + AV.topDesk() : "") +
        (payload.change_label ? " — " + payload.change_label : "") +
        ". It is the newest write standing; nothing older is touched."));
      if (!undoPreviewCurrent() && view.state === "done") {
        note.textContent = "This preview is out of date: the newest write on this desk, or the " +
          "console, is not the one it was read for. Press Preview undo again in History.";
        note.hidden = false;
      }
    } else if (!running) {
      which.textContent = lastWord(view) || "The undo could not be read.";
    } else {
      which.textContent = lastWord(view) || "Starting…";
    }

    const key = [view.started_at, view.state, payload ? payload.journal_id : ""].join("|");
    const facts = el("undo-result-facts");
    if (key !== undoDrawnKey) {
      undoDrawnKey = key;
      if (running) backOpen = null;   // a new preview starts with its own fold state
      facts.textContent = "";
      const stays = el("undo-result-stays");
      const info = el("undo-result-info");
      const back = el("undo-result-back");
      if (payload) {
        const n = undoCounts(payload);
        const rows = payload.rows || [];
        fact(facts, n.total, "written by that " + (payload.kind || "write"));
        fact(facts, n.back, "go back");
        if (n.already) fact(facts, n.already, "already back");
        fact(facts, n.stays, "changed since or unreadable");
        fact(facts, n.noPrior, "can't be restored");
        drawStays(stays, rows.filter((r) => r.verdict === "changed-since" || r.verdict === "unreadable"));
        drawNoPrior(info, rows.filter((r) => r.verdict === "no-earlier-value"));
        drawBack(back, rows.filter((r) => r.verdict === "goes-back"));
      } else {
        [stays, info, back].forEach((b) => { b.textContent = ""; b.hidden = true; });
      }
    }
    const line = el("undo-result-line");
    line.textContent = payload && !running
      ? "Read from the desk" + (view.started_at ? " at " + clockWords(view.started_at) + " UTC" : "") +
        "; nothing was written. If anything changes, press Preview undo again in History."
      : "";
    el("undo-result-command").textContent = (view.command || []).join(" ");
    el("undo-result-log").textContent = (view.log || []).join("\n");
    el("undo-result-log-box").open = !payload && !running;
  }

  // Step 3: Arm, then Write or Undo, never both. Under an undo the red button
  // is directly under the Undo header, then one line of the preview's
  // verdict (and a link up to it), or the result of the undo that was sent.
  function renderStepThreeView() {
    const undo = step3IsUndo();
    el("apply-write-section").hidden = undo;
    el("apply-undo-section").hidden = !undo;
    el("apply-step-3-title").textContent = undo ? "Arm and undo" : "Arm and write";
    if (!undo) return;

    const sum = el("undo-sum");
    const showSum = undoShown() && undoView.state !== "running";
    sum.hidden = !showSum;
    if (showSum) {
      const verdict = undoVerdict(undoView);
      const payload = undoView.result && undoView.result.undo;
      const tag = el("undo-sum-tag");
      tag.className = "sev " + verdict.sev;
      tag.textContent = verdict.text;
      let words;
      if (!payload) words = lastWord(undoView) || "The undo could not be read.";
      else {
        const n = undoCounts(payload);
        words = !n.back ? "Nothing would go back."
          : n.back + " control" + (n.back === 1 ? "" : "s") + " go back" +
            (n.stays ? "; " + n.stays + (n.stays === 1 ? " stays" : " stay") + " as it is." : ".");
      }
      el("undo-sum-line").textContent = words;
    }
    renderUndoBanner();
  }

  // After an undo was sent: what it did, under the (now locked) Undo button.
  function renderUndoBanner() {
    const banner = el("undo-banner");
    const sent = run.kind === "undo" && !run.preview && !!run.state && run.state !== "idle" &&
      !undoShown();
    banner.hidden = !sent;
    if (!sent) return;
    const payload = run.result && run.result.undo;
    const head = el("undo-banner-head");
    const line = el("undo-banner-line");
    const box = el("undo-banner-rows-box");
    banner.className = "undo-banner";
    box.hidden = true;
    if (run.state === "running") {
      head.textContent = "Undoing…";
      line.textContent = lastWord(run);
      return;
    }
    if (!payload || run.state === "failed") {
      banner.classList.add(run.exit_code === 2 ? "is-warn" : "is-err");
      head.textContent = run.exit_code === 2 ? "The undo was refused" : "The undo did not finish";
      line.textContent = lastWord(run);
      return;
    }
    const n = undoCounts(payload);
    const rows = payload.rows || [];
    const sub = [];
    const changed = rows.filter((r) => r.verdict === "changed-since");
    if (changed.length) {
      sub.push(changed.length + (changed.length === 1 ? " was" : " were") + " left as it is (changed " +
        "since: " + changed.slice(0, 3).map((r) => (r.strip_name || r.strip) + " " + r.control +
        ", the desk reads " + undoValue(r.now)).join("; ") +
        (changed.length > 3 ? " and " + (changed.length - 3) + " more" : "") + ").");
    }
    const unread = rows.filter((r) => r.verdict === "unreadable").length;
    if (unread) sub.push(unread + " could not be read and " + (unread === 1 ? "was" : "were") + " left.");
    if (n.noPrior) sub.push(n.noPrior + " could not be restored (no earlier value).");
    const bad = n.didNot || payload.aborted;
    if (payload.aborted) {
      sub.push("The desk stopped answering part way (" + (payload.abort_reason || "no reason given") + ").");
    }
    if (n.didNot) sub.push(n.didNot + " did not land.");
    if (!bad) sub.push("Nothing failed to land.");
    head.textContent = n.wentBack + " put back · " + n.wentBack + " read back and confirmed";
    line.textContent = sub.join(" ");
    banner.classList.add(bad ? "is-err" : (n.stays || n.noPrior) ? "is-warn" : "is-ok");
    // Every address the undo decided something about, as the command saw it.
    if (rows.length) {
      box.hidden = false;
      el("undo-banner-rows-label").textContent = "The undo's journal: " + rows.length + " addresses";
      undoBannerRows = rows;
      const list = el("undo-banner-rows");
      list.textContent = "";
      if (box.open) rows.forEach((r) => list.appendChild(undoRow(r, false)));
    }
  }

  // The rows behind a sent undo are drawn on first open, so a 600-address
  // journal costs nothing until it is asked for.
  let undoBannerRows = [];
  el("undo-banner-rows-box").addEventListener("toggle", (ev) => {
    const list = el("undo-banner-rows");
    if (ev.target.open && !list.children.length) {
      undoBannerRows.forEach((r) => list.appendChild(undoRow(r, false)));
    }
  });

  // One row of a sent undo, as the command saw it.
  function undoRow(row, previewing) {
    const box = node("div", "undo-row is-" + row.verdict);
    const strip = node("div", "undo-row-strip", row.strip || row.address);
    if (row.strip_name) strip.appendChild(node("small", "", row.strip_name));
    box.appendChild(strip);
    const what = node("div", "undo-row-what");
    what.appendChild(node("div", "undo-row-control", (row.control || "") + " · " + row.address));
    const values = node("div", "undo-row-values");
    const parts = [["wrote ", row.written], ["desk now ", row.now],
      [row.verdict === "goes-back" || row.verdict === "went-back"
        ? (previewing ? "goes back to " : "put back to ")
        : row.verdict === "already-back" ? "already back at " : "before the write: ",
      row.goes_back_to]];
    parts.forEach((part, i) => {
      if (i) values.appendChild(node("span", "arrow", "→"));
      values.appendChild(document.createTextNode(part[0] + undoValue(part[1])));
    });
    what.appendChild(values);
    box.appendChild(what);
    const held = UNDO_HELD.indexOf(row.verdict) >= 0;
    box.appendChild(node("span", row.verdict === "did-not-land" ? "sev sev-error"
      : held ? "sev sev-warning" : "readout", UNDO_VERDICT[row.verdict] || row.verdict));
    if (row.detail) box.appendChild(node("div", "undo-row-detail", row.detail));
    return box;
  }

  // The tag on step 3's header while it is Arm and undo.
  function undoStepThreeTag() {
    if (undoShown()) {
      if (undoView.state === "running") return ["Reading", "is-live", "is-current"];
      if (undoView.state === "failed") return ["Stopped", "is-err", "is-current"];
      if (armCheckbox.checked && undoPreviewCurrent()) return ["Armed", "is-err", "is-current"];
      return ["Undo previewed", "", "is-current"];
    }
    if (run.state === "running") return ["Undoing", "is-live", "is-current"];
    if (run.state === "failed") return ["Stopped", "is-err", "is-current"];
    const payload = run.result && run.result.undo;
    if (!payload) return ["Refused", "is-warn", "is-current"];
    const n = undoCounts(payload);
    if (payload.aborted || n.didNot) return ["Undone, with problems", "is-err", "is-current"];
    const left = n.stays + n.noPrior;
    return left ? ["Undone · " + left + " not put back", "is-warn", "is-done"]
      : ["Undone", "is-ok", "is-done"];
  }

  const RUN_LABEL = { apply: "Full build", patch: "Patch", undo: "Undo" };
  // A dry run is labelled as one -- "Preview failed", never
  // "Apply failed", after a press of Preview.
  const PREVIEW_LABEL = { apply: "Preview", patch: "Patch preview", undo: "Undo preview" };

  function runLabelFor(kind, preview) {
    return (preview ? PREVIEW_LABEL : RUN_LABEL)[kind];
  }

  // A number that only moves when the server answers is a number that
  // stops when the server does, which is the case it most needs to show.
  setInterval(() => { if (latest.state === "running") renderRun(); }, 250);

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
      // One section per bank (§3): the label, its count in
      // white, and a solid rule above it.
      const bank = document.createElement("div");
      bank.className = "desk-bank";
      const head = document.createElement("h3");
      head.className = "desk-section-title";
      head.textContent = section.title + " ";
      const count = document.createElement("span");
      count.className = "desk-count";
      count.textContent = String(section.count);
      head.appendChild(count);
      bank.appendChild(head);
      const grid = document.createElement("div");
      grid.className = "desk-strips";
      grid.dataset.kind = section.kind;
      section.strips.forEach((strip) => grid.appendChild(stripCell(section, strip, patch)));
      bank.appendChild(grid);
      box.appendChild(bank);
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
    box.hidden = !mine || !(drawing || run.review || run.result) || undoShown();
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

  // An undo preview's findings are its own: they replace the last undo
  // preview's, and leave what the last write said in the dock.
  function producerOf(status) {
    return status.kind === "undo" && status.preview ? "apply-undo-preview" : "apply";
  }

  function publishRunFindings(list, producer) {
    producer = producer || "apply";
    SP.setFindings(SP.findings().filter((f) => f._producer !== producer));
    const findings = (list || []).map((f) => Object.assign({}, f, {
      _producer: producer,
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
    take(status);
    renderRun();
    if (status.state === "running") {
      pollTimer = setTimeout(poll, 1000);
      return;
    }
    pollTimer = null;
    if (status.preview && status.kind !== "undo") {
      reviewedFor = previewIsWritable(run) ? startedFor : null;
    }
    const wrote = !status.preview && status.kind !== "undo" &&
      !!(status.result && status.result.journal_path);
    publishRunFindings(status.findings, producerOf(status));
    await AV.refreshStack();
    if (wrote || (!status.preview && status.kind === "undo")) {
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
    if (kind === "patch") {
      // Armed by the same checkbox, and refused unless the review this
      // page drew is the one the server armed.
      url = "/api/patch/run";
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
    if (!confirmMode) {
      // The Preview box shows the preview asked for last. Asking for the
      // other kind flips it, and the tick given for one action is never left
      // standing for the other.
      const next = kind === "undo" ? "undo" : "write";
      if (next !== lastPreview) armCheckbox.checked = false;
      lastPreview = next;
      if (next === "undo") undoDesk = deskLabel();
    }
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
      take(data);
      AV.setFresh(null);
      // A write has been sent: the tick is spent. The next write -- a
      // second patch, an undo -- is a fresh decision and a fresh tick.
      if (confirmMode) armCheckbox.checked = false;
      publishRunFindings([], producerOf(data));
      renderRun();
      if (!pollTimer) pollTimer = setTimeout(poll, 400);
    } catch (e) {
      showMessage(String(e), true);
      updateArmState();
    }
  }

  previewBtn.addEventListener("click", () => start(false));
  runBtn.addEventListener("click", () => start(true));
  undoRunBtn.addEventListener("click", () => start(true, "undo"));

  // History's Preview undo asks for the undo preview, which is drawn in step 2:
  // the page scrolls up to it and puts focus on the result. The links that
  // say "shown in step 2" and "the preview is in step 2" only scroll.
  function showStepTwo(focusResult) {
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el("apply-step-2").scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
    if (focusResult) {
      const panel = el("undo-result");
      if (!el("undo-preview-section").hidden) panel.focus({ preventScroll: true });
    }
  }
  el("undo-sum-link").addEventListener("click", () => showStepTwo(false));

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

  // History's buttons are drawn with its rows, so one handler on the rows.
  el("journal-stack-rows").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-promote]");
    if (button) {
      promotePreview(button.dataset.promote, button.dataset.label);
      return;
    }
    if (event.target.closest("[data-shown-in]")) {
      showStepTwo(true);
      return;
    }
    const preview = event.target.closest("#undo-preview-btn");
    if (preview && !preview.disabled) {
      showStepTwo(false);
      start(false, "undo").then(() => showStepTwo(true));
    }
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
      src.className = "prop";
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

  // One count (§6): a readout, which is data; or, when the
  // count is a problem, a severity tag in that severity's colour.
  function chip(label, value, cls) {
    const span = document.createElement("span");
    span.className = cls === "is-bad" ? "sev sev-error"
      : cls === "is-warn" ? "sev sev-warning" : "readout";
    span.textContent = label + " " + String(value);
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
    else if (run.kind === "apply") {
      // A full build sends only what the desk did not already hold; say
      // how many it found right, so "written" is not read as the whole plan.
      sub = "Nothing failed to land. The desk now matches the plan." + (c.unchanged
        ? " " + c.unchanged + " " + plural(c.unchanged, "address was", "addresses were") +
          " already right and left alone." : "");
    }
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
      : "The journal: all " + c.total + " addresses, written or already right →";
    el("apply-watch-footer").hidden = !!result.dry_run || run.kind !== "apply";

    // `apply.ApplyResult.summary()`, exactly as the command prints it.
    const summaryEl = el("apply-summary-line");
    summaryEl.textContent = result.summary || "";
    summaryEl.classList.toggle("is-bad", !!result.aborted || !!c.mismatch);

    const chips = el("apply-chips");
    chips.textContent = "";
    chips.appendChild(chip("evaluated", c.total));
    if (result.dry_run) chips.appendChild(chip("would change", c.would_change));
    else {
      chips.appendChild(chip("written", c.written));
      if (c.unchanged) chips.appendChild(chip("already right", c.unchanged));
    }
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
    latest = run;
    undoView = null;
    lastPreview = "write";
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
  setApplyMode(applyMode);
  fetchPreflight();
  AV.refreshStack().then(updateArmState);
  if (latest.state === "running") poll();
  else publishRunFindings(latest.findings, producerOf(latest));
})();
