/* The shell: one page, three modes.
 *
 * Phase 1 of version H is the chrome every later phase hangs off; phase 2
 * added Build's three file tiles at the bottom of this file. Step 04 --
 * running the build and drawing the plan -- is setup.js, loaded after
 * this file and coded against `window.Atoo`. Three things live in
 * the chrome because they are shared:
 *
 *   * the bundle bar    -- one show bundle across Build, Apply and Watch
 *   * the console readout + Ping  -- one console, one round trip, and
 *                          the one place its address is changed
 *   * the findings dock -- a finding raised in Build is the reason you
 *                          would not press Apply, so it stays on screen;
 *                          and it is the ONE place findings are listed
 *                         , each said once, every INFO
 *                          folded under a toggle and grouped by code
 *
 * Vanilla JS, no build step, no CDN (atoo/webui.py's own docstring
 * says why: a laptop at FOH with LAN reach to a console and nothing else).
 *
 * WHAT LATER PHASES CODE AGAINST is `window.Atoo` at the bottom of
 * this file. Nothing else here is a contract.
 */
(() => {
  "use strict";

  // Must stay identical to atoo.diagnostics.SEVERITY_ORDER -- three
  // rungs, and that is the whole list. A fourth above `error` existed
  // until 2026-09-23 and was dropped because nothing ever emitted one; a
  // rung with no members here would be a dock section that never fills.
  // tests/test_webui.py asserts this file against Python's own ladder,
  // because the Python suite cannot otherwise see it.
  const SEVERITY_ORDER = { error: 0, warning: 1, info: 2 };
  const SEVERITY_LABEL = { error: "Error", warning: "Warning", info: "Info" };
  const MODES = ["build", "apply", "watch"];

  const el = (id) => document.getElementById(id);

  // ---- startup state ------------------------------------------------
  // Embedded by webui.py's `_embed_startup_json`, in the document before
  // this script tag, so the bundle name and the console address are on
  // screen at first paint rather than a moment after it. A value that
  // appears late is a value someone can act on before it settles.
  function readStartup() {
    const tag = el("initial-shell");
    if (!tag) return {};
    try {
      return JSON.parse(tag.textContent) || {};
    } catch (e) {
      return {};
    }
  }

  const startup = readStartup();
  let bundle = startup.bundle || null;
  // The ONE console -- mutable since the 2026-09-24 decision that
  // the address is editable in this bar (and nowhere else). Replaced
  // wholesale by what `POST /api/console` answers, never patched here.
  let consoleDefaults = startup.console || {};
  // The working folder `atoo init` made ([workspace] default), or "". Every file-browser start falls back to it while no
  // bundle is open; with one open, the bundle's own folder wins.
  const workspace = startup.workspace || "";

  // ---- which copy of Atoo this is -------------------------------------
  // The footer line, from the server's start-up data; hidden when the
  // server sent none. Its tooltip adds the Python the server runs on.
  (function showAboutLine() {
    const info = startup.install;
    const line = el("about-line");
    if (!line || !info || !info.line) return;
    line.textContent = info.line;
    if (info.python) line.title = "Python: " + info.python;
    line.hidden = false;
  })();

  // ---- mode switching -------------------------------------------------
  // Client-side, and recorded in the URL fragment: a reload, a bookmark
  // and the browser's Back button all keep the mode you were in. Nothing
  // is fetched on a switch, so switching costs nothing and loses nothing.

  let currentMode = "build";
  // Fired with the new mode's name on every switch INTO a mode (not on a
  // re-activation of the one already showing). Watch uses it to re-read
  // watch.json, which a build on this same page may have just drafted
  // into.
  const modeListeners = [];

  function activateMode(name) {
    if (MODES.indexOf(name) === -1) return;
    const changed = name !== currentMode;
    currentMode = name;
    MODES.forEach((id) => {
      const panel = el("mode-" + id);
      const nav = el("nav-" + id);
      const active = id === name;
      if (panel) {
        panel.hidden = !active;
        panel.classList.toggle("is-active", active);
      }
      if (nav) {
        nav.classList.toggle("page-nav-active", active);
        if (active) nav.setAttribute("aria-current", "page");
        else nav.removeAttribute("aria-current");
      }
    });
    // The Watch page has no need of the findings
    // sidebar: those findings are all for build or apply. Watch has its
    // own findings table; the dock is hidden there and comes back with
    // Build or Apply.
    const dockCol = el("dock-col");
    if (dockCol) dockCol.hidden = name === "watch";
    if (location.hash !== "#" + name) {
      history.replaceState(null, "", "#" + name);
    }
    if (changed) {
      modeListeners.forEach((fn) => {
        try { fn(name); } catch (e) { /* one listener must not stop the rest */ }
      });
    }
  }

  function modeFromHash() {
    const raw = (location.hash || "").replace(/^#/, "");
    return MODES.indexOf(raw) === -1 ? "build" : raw;
  }

  MODES.forEach((id) => {
    const nav = el("nav-" + id);
    if (nav) nav.addEventListener("click", () => activateMode(id));
  });
  window.addEventListener("hashchange", () => activateMode(modeFromHash()));

  // ---- segmented controls ------------------------------------------------
  // A chooser among two to four exclusive options (Apply mode, Which
  // console, Theme): a `.seg` radiogroup holding `.seg-opt` buttons with
  // `role="radio"` and a `data-value`. One tab stop, on the selected
  // option; the arrows (with wrap) move AND select, Home and End jump to
  // the ends, and a click selects. `onChange(value)` fires when the choice
  // changes by the user; `select(value)` sets it silently. A locked group
  // (`.is-locked`, `aria-disabled`, each option disabled) ignores the
  // keys and clicks. Returns { value, select, lock }.
  function wireSeg(group, onChange) {
    if (!group) return null;
    const opts = Array.prototype.slice.call(group.querySelectorAll('[role="radio"]'));
    const isLocked = () => group.getAttribute("aria-disabled") === "true";
    function value() {
      const on = opts.find((o) => o.getAttribute("aria-checked") === "true");
      return on ? on.dataset.value : null;
    }
    function select(v) {
      opts.forEach((o) => {
        const on = o.dataset.value === v;
        o.setAttribute("aria-checked", on ? "true" : "false");
        o.tabIndex = on ? 0 : -1;
      });
    }
    function pick(o) {
      if (isLocked() || o.disabled) return;
      const changed = value() !== o.dataset.value;
      select(o.dataset.value);
      o.focus();
      if (changed && onChange) onChange(o.dataset.value);
    }
    function lock(on) {
      group.classList.toggle("is-locked", !!on);
      if (on) group.setAttribute("aria-disabled", "true");
      else group.removeAttribute("aria-disabled");
      opts.forEach((o) => { o.disabled = !!on; });
    }
    opts.forEach((o, i) => {
      o.addEventListener("click", () => pick(o));
      o.addEventListener("keydown", (ev) => {
        let j = null;
        if (ev.key === "ArrowRight" || ev.key === "ArrowDown") j = (i + 1) % opts.length;
        else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") j = (i - 1 + opts.length) % opts.length;
        else if (ev.key === "Home") j = 0;
        else if (ev.key === "End") j = opts.length - 1;
        if (j === null) return;
        ev.preventDefault();
        pick(opts[j]);
      });
    });
    select(value());
    return { value: value, select: select, lock: lock };
  }

  // ---- theme -------------------------------------------------------------
  // Auto (follows the system), Light or Dark, chosen directly. Kept in this
  // browser's storage (a per-viewer convenience); shell.html's head script
  // applies it before first paint. It changes how the page looks, nothing
  // else, so the stale-page banner leaves it working. Dark is the default
  // with nothing saved, so Auto is saved as "auto".
  const THEME_KEY = "atoo.theme";
  function currentTheme() {
    const t = document.documentElement.dataset.theme;
    return t === "light" || t === "dark" ? t : "auto";
  }
  const themeSeg = wireSeg(el("theme-seg"), (choice) => {
    if (choice === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = choice;
    try {
      localStorage.setItem(THEME_KEY, choice);
    } catch (e) { /* not kept; the page still switches */ }
  });
  if (themeSeg) themeSeg.select(currentTheme());

  // ---- popups ----------------------
  // Any button with `data-popup="<id>"` opens that `.sp-popup` over a
  // scrim; `data-popup-close`, Escape and a click on the scrim close it.
  // One at a time. Focus goes to the popup's own button, and back after.

  const popupScrim = el("popup-scrim");
  let popupReturn = null;

  function openPopup(id) {
    const popup = el(id);
    if (!popupScrim || !popup) return;
    popupScrim.querySelectorAll(".sp-popup").forEach((p) => { p.hidden = p !== popup; });
    popupReturn = document.activeElement;
    popupScrim.hidden = false;
    const first = popup.querySelector("[data-popup-close]") || popup;
    if (first.focus) first.focus();
  }

  function closePopup() {
    if (!popupScrim || popupScrim.hidden) return;
    popupScrim.hidden = true;
    if (popupReturn && popupReturn.focus) popupReturn.focus();
    popupReturn = null;
  }

  document.addEventListener("click", (ev) => {
    const target = ev.target && ev.target.closest ? ev.target : null;
    if (!target) return;
    const opener = target.closest("[data-popup]");
    if (opener) {
      ev.preventDefault();
      openPopup(opener.dataset.popup);
      return;
    }
    if (target.closest("[data-popup-close]") || target === popupScrim) closePopup();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && popupScrim && !popupScrim.hidden) closePopup();
  });

  // The Demo popup, once per browser: shown the first time the Demo show is
  // open, and from the chip after that. Remembered in this browser only; a
  // private window sees it again, which is harmless.
  const DEMO_POPUP_KEY = "atoo.demoPopupSeen";
  let demoPopupShown = false;
  function showDemoPopupOnce() {
    if (demoPopupShown) return;
    demoPopupShown = true;
    let seen = false;
    try { seen = localStorage.getItem(DEMO_POPUP_KEY) === "1"; } catch (e) { seen = false; }
    if (seen) return;
    try { localStorage.setItem(DEMO_POPUP_KEY, "1"); } catch (e) { /* not kept */ }
    openPopup("demo-popup");
  }

  // ---- the bundle bar -------------------------------------------------

  const bundleName = el("bundle-name");
  const bundleMessage = el("bundle-message");
  const bundleReadOnly = el("bundle-readonly");
  const demoChip = el("demo-chip");
  const noShowNotice = el("no-show-notice");

  // The open bundle is the packaged, read-only demo show.
  function isDemoShow() {
    return !!(bundle && bundle.demo);
  }

  const bundleListeners = [];
  // Bumped on every bundle change made from THIS tab, and counted while one
  // is in flight -- the stale-page check below ignores an answer that
  // started before the change (see `checkServer`).
  let bundleEpoch = 0;
  let bundleOpening = 0;

  function showBundleMessage(text, isError) {
    if (!bundleMessage) return;
    bundleMessage.textContent = text || "";
    bundleMessage.hidden = !text;
    bundleMessage.classList.toggle("panel-message-error", !!isError);
  }

  function renderBundle() {
    // The packaged demo show is read-only. The bar says so,
    // and `is-demo-show` on the body dims every control that would write
    // (styles.css; the click guard below swallows a keyboard press on
    // one). The server refuses all of them anyway -- this is the courtesy,
    // not the guard. What the Demo is, and what works in it,
    // is a popup shown once, and the bar's chip opens it again.
    const demo = isDemoShow();
    document.body.classList.toggle("is-demo-show", demo);
    if (bundleReadOnly) bundleReadOnly.hidden = !demo;
    if (demoChip) demoChip.hidden = !demo;
    if (demo) showDemoPopupOnce();
    if (noShowNotice) noShowNotice.hidden = !!bundle;
    if (!bundle) {
      bundleName.textContent = "none";
      bundleName.classList.add("is-empty");
      return;
    }
    bundleName.textContent = demo ? bundle.name : bundle.name + "/";
    bundleName.classList.remove("is-empty");
    bundleName.title = bundle.directory;

    // The "Also in this bundle" strip that listed the remaining fixed
    // filenames is gone (the UI does not need it). Each file the page
    // uses is shown by the step that reads it.
  }

  // Change... and New show... open the file browser (filebrowser.js). Before it, each was a path box under the bar; the
  // dialog keeps that fast path in its own path field.

  // The folder a path is in, as the page shows it -- display only: the
  // server is always handed a whole path, never one this page built.
  function parentOf(path) {
    const files = window.AtooFiles;
    return files ? files.splitPath(path).folder : "";
  }

  // Opens (or, with `create`, makes and opens) a bundle. Resolves null on
  // success and the server's sentence on a refusal, so the dialog that
  // asked can say it where the operator is looking.
  async function openBundleAt(directory, create) {
    showBundleMessage("");
    // While this tab's own open is in flight the server's bundle moves
    // before this page's does, and the stale-page check must not read
    // that gap as another tab having opened one (see `checkServer`).
    bundleEpoch += 1;
    bundleOpening += 1;
    try {
      const r = await fetch("/api/bundle/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ directory: directory, create: !!create }),
      });
      const data = await r.json();
      if (!r.ok) return data.error || "couldn't open that folder";
      // Opening another show leaves Demo: the server says
      // which console that left in the bar.
      const desk = data.console;
      delete data.console;
      bundle = data;
      bundleEpoch += 1;
      renderBundle();
      if (desk) setConsole(desk);
      // `created` is the server telling us whether "New show..." actually
      // started something, or adopted a folder that was already there.
      // Saying so is the difference between a fresh bundle and someone
      // else's show quietly reopened.
      if (create && !data.created) {
        showBundleMessage(
          "That folder already existed -- opened it rather than starting a new show.",
          false
        );
      } else if (create) {
        showBundleMessage("Created the show bundle " + data.directory + " -- it is empty. " +
          "Choose an input list on step 02 (it is copied in), and instructions on step 03.",
          false);
      }
      bundleListeners.forEach((fn) => {
        try { fn(bundle); } catch (e) { /* one listener must not stop the rest */ }
      });
      return null;
    } catch (e) {
      return String(e);
    } finally {
      bundleOpening -= 1;
    }
  }

  function openBundleDialog() {
    const files = window.AtooFiles;
    if (!files) return;
    files.open({
      mode: "open-folder",
      kind: "folders",
      title: "Open a show bundle",
      note: "Pick the show's folder -- the one that holds (or will hold) input.csv, " +
        "instructions.md and plan.json. Folders tagged “show bundle” already hold some.",
      // The open bundle's folder, with the bundle highlighted: the next
      // show is usually its sibling.
      start: bundle ? parentOf(bundle.directory) : workspace,
      select: bundle ? bundle.name : "",
      confirmLabel: "Open",
      newFolder: false,
      onChoose: async (result, dialog) => {
        if (!(await checkServer())) return true;
        const error = await openBundleAt(result.path, false);
        if (error) { dialog.error(error); return false; }
        return true;
      },
    });
  }

  function openNewShowDialog() {
    const files = window.AtooFiles;
    if (!files) return;
    files.open({
      mode: "create-folder",
      kind: "folders",
      title: "New show",
      note: "Choose where the show's folder goes and name it. It starts empty; an input " +
        "list you then open on step 02 is copied into it.",
      start: bundle ? parentOf(bundle.directory) : workspace,
      nameLabel: "New show folder",
      confirmLabel: "Create show",
      onChoose: async (result, dialog) => {
        if (result.exists) {
          // A name that is already a folder here is someone's show, or
          // something else entirely: opening it is a choice, not a default.
          const answer = await dialog.ask(
            "There is already " + (result.exists.type === "dir" ? "a folder" : "a file") +
            " called " + result.name + " here." +
            (result.exists.type === "dir" ? " Open it as the show instead of creating a new one?" : ""),
            result.exists.type === "dir"
              ? [{ id: "open", label: "Open " + result.name + "/", primary: true },
                 { id: "cancel", label: "Pick another name" }]
              : [{ id: "cancel", label: "Pick another name", primary: true }]
          );
          if (answer !== "open") return false;
        }
        if (!(await checkServer())) return true;
        const error = await openBundleAt(result.path, true);
        if (error) { dialog.error(error); return false; }
        return true;
      },
    });
  }

  el("bundle-change-btn").addEventListener("click", openBundleDialog);
  el("bundle-new-btn").addEventListener("click", openNewShowDialog);

  // ---- the console readout, its editor, and Ping -------------------------
  // One round trip, nothing read, safe mid-show -- `atoo ping`
  //  behind a button. The address is resolved once by the
  // server at startup (ATOO_CONSOLE / ~/.atoo.config [console]) and the page SAYS SO rather than presenting a
  // value nobody typed as one someone did.
  //
  // It is EDITABLE HERE AND NOWHERE ELSE, because one plan may be applied
  // to more than one console (a primary Compact and a backup Rack, say).
  // One address,
  // used by Ping, Apply, Patch, Undo and Watch alike. After an edit its
  // provenance reads "set here" -- the converse of the rule. The server
  // refuses an edit while any write is running (a write never switches
  // desks part way through), and apply.js greys the button meanwhile.
  //
  // DEMO is chosen in the same editor, beside the address (it
  // is just called 'Demo', and the IP address area in the status header
  // reflects this, with no need to repeat the IP
  // address). The server's console is then `{demo: true, address: null}`:
  // the bar reads "Demo" and nothing else, Ping is off (there is no desk to
  // ask), Watch runs on the demo rig, and every write screen refuses for
  // want of an address -- closed by default.
  //
  // Demo is the DEMO SHOW too: the
  // server opens the packaged, read-only demo show in the same request
  // and answers with it (`bundle`, `bundle_changed`), so this page redraws
  // the bar and every mode from one reply. An address chosen while Demo is
  // open leaves it -- the server reopens the show that was open before
  // Demo, or none -- and opening or creating a show leaves it too
  // (`openBundleAt` takes the console the server hands back).

  // Must match webui.CONSOLE_SET_HERE and webui.DEMO_CONSOLE_LABEL.
  const CONSOLE_SET_HERE = "set here";
  const DEMO_LABEL = "Demo";

  const consoleAddress = el("console-address");
  const consoleSource = el("console-source");
  const consoleChangeBtn = el("console-change-btn");
  const consoleEdit = el("console-bar-edit");
  const consoleEditAddress = el("console-edit-address");
  const consoleEditPort = el("console-edit-port");
  const consoleSetBtn = el("console-set-btn");
  const consoleKindDesk = el("console-kind-desk");
  const consoleKindDemo = el("console-kind-demo");
  // Address or Demo: a segmented control; renderConsoleKind follows the choice.
  const consoleKindSeg = wireSeg(el("console-kind-seg"), () => renderConsoleKind());
  const isDemoKind = () => !!consoleKindSeg && consoleKindSeg.value() === "demo";
  const consoleEditHint = el("console-edit-hint");
  const consoleDemoHint = el("console-demo-hint");
  const consoleMessage = el("console-message");
  const pingPill = el("ping-pill");
  const pingDetail = el("ping-detail");
  const pingLock = el("ping-lock");
  const pingBtn = el("ping-btn");
  const consoleListeners = [];
  const pingListeners = [];
  let consoleLock = "";   // why the console cannot change right now, or ""
  // The last real address the bar held, so choosing Address again after
  // Demo starts from it rather than from an empty box.
  let lastDesk = consoleDefaults.address ? Object.assign({}, consoleDefaults) : null;

  function consoleLabel(desk) {
    if (desk && desk.demo) return DEMO_LABEL;
    return desk && desk.address ? desk.address + ":" + (desk.port || 2223) : "";
  }

  // "from ATOO_CONSOLE", "from ~/.atoo.config [console]", or
  // "set here" -- the words every write screen repeats beside the desk it
  // names (apply.js calls this through window.Atoo).
  function consoleProvenance(desk) {
    if (!desk || !desk.address || !desk.address_source) return "";
    return desk.address_source === CONSOLE_SET_HERE ? "set here"
      : "from " + desk.address_source;
  }

  function renderConsole() {
    const address = consoleDefaults.address;
    const demo = !!consoleDefaults.demo;
    consoleAddress.textContent = demo ? DEMO_LABEL
      : address ? consoleLabel(consoleDefaults) : "not set";
    consoleAddress.classList.toggle("is-empty", !address && !demo);
    consoleAddress.classList.toggle("is-demo", demo);
    if (demo) {
      // "Demo" says it all: no address, and no provenance beside it.
      consoleSource.textContent = "";
      consoleSource.hidden = true;
    } else if (address && consoleDefaults.address_source === CONSOLE_SET_HERE) {
      // Typed into the bar itself: the bar needs no label to say so.
      // Write screens still say "set here".
      consoleSource.textContent = "";
      consoleSource.hidden = true;
    } else if (address && consoleDefaults.address_source) {
      consoleSource.textContent = consoleProvenance(consoleDefaults);
      consoleSource.classList.toggle("is-set-here",
        consoleDefaults.address_source === CONSOLE_SET_HERE);
      consoleSource.hidden = false;
    } else if (address) {
      // Resolved, but from the built-in default -- a value nobody chose
      // has no provenance worth showing (cli.resolve_console_defaults
      // sends null for exactly that case).
      consoleSource.hidden = true;
    } else {
      consoleSource.textContent = "";
      consoleSource.hidden = true;
    }
    // A Ping that would do nothing is locked, and says why;
    // its answer tag has nothing to say until then.
    const pingReason = pingLockReason();
    pingBtn.disabled = !!pingReason;
    pingBtn.title = pingReason;
    pingLock.textContent = pingReason;
    pingLock.hidden = !pingReason;
    pingPill.hidden = !!pingReason;
    pingDetail.hidden = !!pingReason || !pingDetail.textContent;
    consoleChangeBtn.disabled = !!consoleLock;
    consoleChangeBtn.title = consoleLock || "Change the console Ping, Apply, Patch, Undo " +
      "and Watch use";
    consoleSetBtn.disabled = !!consoleLock;
  }

  // Why Ping cannot be pressed now, or "" when it can.
  function pingLockReason() {
    if (consoleDefaults.demo) return "the Demo has no desk to ping";
    if (!consoleDefaults.address) return "no console set. Choose one with Change\u2026";
    return "";
  }

  function showConsoleMessage(text) {
    consoleMessage.textContent = text || "";
    consoleMessage.hidden = !text;
  }

  // Address or Demo: Demo greys the address and port out and swaps the
  // hint, so what "Use this console" will do is on screen before it is
  // pressed.
  function renderConsoleKind() {
    const demo = isDemoKind();
    consoleEditAddress.disabled = demo;
    consoleEditPort.disabled = demo;
    if (consoleEditHint) consoleEditHint.hidden = demo;
    if (consoleDemoHint) consoleDemoHint.hidden = !demo;
  }

  function openConsoleEdit() {
    if (consoleLock) return;
    const from = consoleDefaults.demo ? (lastDesk || {}) : consoleDefaults;
    consoleEditAddress.value = from.address || "";
    consoleEditPort.value = from.port || consoleDefaults.port || 2223;
    consoleKindSeg.select(consoleDefaults.demo ? "demo" : "desk");
    renderConsoleKind();
    showConsoleMessage("");
    consoleEdit.classList.add("is-open");
    if (consoleDefaults.demo && consoleKindDemo) {
      consoleKindDemo.focus();
    } else {
      consoleEditAddress.focus();
      consoleEditAddress.select();
    }
  }

  function closeConsoleEdit() {
    consoleEdit.classList.remove("is-open");
    showConsoleMessage("");
  }

  async function submitConsoleEdit() {
    let body;
    if (isDemoKind()) {
      body = { demo: true };
    } else {
      const address = (consoleEditAddress.value || "").trim();
      if (!address) {
        showConsoleMessage("Type the console's address -- an IP such as 203.0.113.50.");
        return;
      }
      body = { address: address };
      const port = parseInt(consoleEditPort.value, 10);
      if (Number.isFinite(port)) body.port = port;
    }
    consoleSetBtn.disabled = true;
    // Demo, in or out, moves the server's bundle too -- the
    // same gap `openBundleAt` guards, for the stale-page check.
    bundleEpoch += 1;
    bundleOpening += 1;
    try {
      const r = await fetch("/api/console", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) {
        // 409 while a write is running; 400 for an address that is not one.
        showConsoleMessage(data.error || "couldn't change the console");
        return;
      }
      // Choosing Demo opens the demo show, and an address
      // leaves it (back to the show open before Demo, or none). The
      // answer carries the bundle; every mode redraws from it.
      const changed = !!data.bundle_changed;
      const opened = data.bundle || null;
      delete data.bundle;
      delete data.bundle_changed;
      if (changed) {
        bundle = opened;
        bundleEpoch += 1;
        renderBundle();
        // The demo notice under the bar says what Demo is; a message from
        // before the change no longer applies either way.
        showBundleMessage("");
      }
      setConsole(data);
      closeConsoleEdit();
      if (changed) {
        bundleListeners.forEach((fn) => {
          try { fn(bundle); } catch (e) { /* one listener must not stop the rest */ }
        });
      }
    } catch (e) {
      showConsoleMessage(String(e));
    } finally {
      bundleOpening -= 1;
      consoleSetBtn.disabled = !!consoleLock;
    }
  }

  // The server's answer is the truth; every mode that names a desk hears
  // about it here and redraws. A different desk has not been pinged.
  function setConsole(data) {
    const before = consoleLabel(consoleDefaults);
    consoleDefaults = data || {};
    if (consoleDefaults.address) lastDesk = Object.assign({}, consoleDefaults);
    renderConsole();
    if (consoleLabel(consoleDefaults) !== before) {
      // A different desk has not been pinged. With nothing to ping (no
      // address, or the Demo) the tag is hidden and the lock says why.
      setPingPill("Not pinged", "");
      pingPill.title = "";
    }
    consoleListeners.forEach((fn) => fn(Object.assign({}, consoleDefaults)));
  }

  consoleChangeBtn.addEventListener("click", openConsoleEdit);
  consoleSetBtn.addEventListener("click", submitConsoleEdit);
  // The no-show notice's button is Console: Change... -> Demo.
  const tryDemoBtn = el("try-demo-btn");
  if (tryDemoBtn && consoleKindSeg) {
    tryDemoBtn.addEventListener("click", () => {
      consoleKindSeg.select("demo");
      submitConsoleEdit();
    });
  }
  el("console-cancel-btn").addEventListener("click", closeConsoleEdit);
  [consoleEditAddress, consoleEditPort, consoleKindDesk, consoleKindDemo].forEach((input) => {
    if (!input) return;
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); submitConsoleEdit(); }
      if (ev.key === "Escape") { ev.preventDefault(); closeConsoleEdit(); }
    });
  });

  // The Ping answer: a state tag -- `is-ok` on an answer,
  // `is-err` on a failure, neutral before one -- and, beside it in meta
  // type, what the desk said or why it did not answer.
  function setPingPill(word, state, detail) {
    pingPill.textContent = word;
    pingPill.className = "state" + (state ? " " + state : "");
    pingDetail.textContent = detail || "";
    pingDetail.hidden = !detail || pingPill.hidden;
  }

  async function runPing() {
    setPingPill("Pinging…", "");
    pingBtn.disabled = true;
    try {
      const r = await fetch("/api/ping", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await r.json();
      if (!r.ok) {
        setPingPill("Failed", "is-err", data.error || "ping failed");
        return;
      }
      if (!data.ok) {
        // A desk that did not answer is a 200 with ok:false -- the
        // question was asked and the answer was no. It reads as a red
        // tag and its sentence, not as a broken page.
        setPingPill("No reply", "is-err", data.error || "no reply");
        return;
      }
      // What the desk said about itself, in the order `atoo ping`
      // prints it: the model it states (the evidence `apply`
      // cross-checks a plan against), the address, the round trip.
      const parts = [];
      if (data.model_label) parts.push(data.model_label);
      else parts.push("model not recognised");
      parts.push(data.address + ":" + data.port);
      if (data.elapsed_ms != null) parts.push(Math.round(data.elapsed_ms) + " ms");
      setPingPill("Answered", "is-ok", parts.join(" · "));
      pingPill.title = (data.identity || []).join(", ");
      // The server now knows this desk's serial; the journal stack can
      // say which rows it wrote.
      pingListeners.forEach((fn) => fn(data));
    } catch (e) {
      setPingPill("Failed", "is-err", String(e));
    } finally {
      pingBtn.disabled = !!pingLockReason();
    }
  }

  pingBtn.addEventListener("click", runPing);

  // ---- the stale-page banner ---------------------------------------------
  // From a desk session, 2026-09-24: A19's script started `atoo ui`
  // on one bundle copy, A20's stopped it and started another on the same
  // port and a DIFFERENT copy, and the tab A19 had opened kept showing
  // A19's journal stack against A20's server. Harmless as a display; not
  // harmless if its Apply button still worked.
  //
  // So the page knows which server process drew it -- `instance`, random
  // per process, embedded at first paint -- and which bundle it shows, and
  // checks both against `GET /api/status` every few seconds while visible,
  // whenever the tab comes back into view, and before every write
  // (`checkServer`, which apply.js and setup.js await). A different
  // instance is a restarted server; a different bundle is another tab's
  // "Open bundle". Either way the page is out of date.
  //
  // A BANNER, NOT A SILENT RELOAD. A reload throws away whatever was typed
  // (a rebuild path, an --allow-strip, a watch rule half-edited) and swaps
  // what is on screen without saying why -- and the reason is the whole
  // point: the server may now be pointed at a different show. The banner
  // is sticky, in the danger colours, and turns off every control that
  // writes or runs; text fields stay readable so anything typed can be
  // copied first. The server refuses a stale write on its own (409, webui
  // `_stale_bundle`) -- this is the courtesy, that is the guard.

  const pageInstance = startup.instance || null;
  const staleBanner = el("stale-banner");
  const staleDetail = el("stale-banner-detail");
  let stale = null;   // null, or {kind, message} once the page is out of date
  const staleListeners = [];

  function sameDirectory(a, b) {
    const norm = (p) => (p || "").replace(/[\\/]+$/, "");
    return norm(a) === norm(b);
  }

  function markStale(kind, message) {
    if (stale) return;
    stale = { kind: kind, message: message };
    staleDetail.textContent = message;
    staleBanner.hidden = false;
    document.body.classList.add("is-stale-page");
    if (window.AtooFiles) window.AtooFiles.close();
    closeConsoleEdit();
    staleListeners.forEach((fn) => {
      try { fn(Object.assign({}, stale)); } catch (e) { /* one listener must not stop the rest */ }
    });
  }

  function describeBundle(directory) {
    return directory ? directory : "no show bundle";
  }

  // Resolves true while the page is current. A server that cannot be
  // reached says nothing either way (it may be restarting); the next
  // answer decides.
  async function checkServer() {
    if (stale) return false;
    const epoch = bundleEpoch;
    let status;
    try {
      const r = await fetch("/api/status", { cache: "no-store" });
      if (!r.ok) return !stale;
      status = await r.json();
    } catch (e) {
      return !stale;
    }
    if (stale) return false;
    const shown = bundle ? bundle.directory : null;
    if (pageInstance && status.instance && status.instance !== pageInstance) {
      markStale("restart",
        "The Atoo server behind this page was restarted since the page was drawn" +
        (sameDirectory(status.bundle, shown) ? "" :
          ", and it now has " + describeBundle(status.bundle) + " open where this page shows " +
          describeBundle(shown)) +
        ". The plan, pre-flight, History and runs on this page are from before, so " +
        "every button that writes or runs is off. Reload to see what the server holds now " +
        "-- copy anything you typed first.");
    } else if (epoch === bundleEpoch && !bundleOpening && "bundle" in status &&
               !sameDirectory(status.bundle, shown)) {
      markStale("bundle",
        "The server now has " + describeBundle(status.bundle) + " open -- opened from " +
        "another tab or window -- but this page still shows " + describeBundle(shown) +
        ". Every button that writes or runs is off until you reload.");
    }
    return !stale;
  }

  // A keyboard "click" on a dimmed control still fires; swallow it here,
  // before any mode's own handler runs, whatever `disabled` says.
  document.addEventListener("click", (ev) => {
    if (!stale) return;
    const target = ev.target && ev.target.closest
      ? ev.target.closest("button, select, input[type=checkbox], input[type=radio]") : null;
    if (!target || target.closest("[data-stale-ok]")) return;
    if (!target.closest("#bundle-chrome, .layout-main")) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
  }, true);

  // The same swallow for the demo show's write controls --
  // dimmed by styles.css (`body.is-demo-show`), refused by the server,
  // and a keyboard press on one stops here with the reason on screen.
  // The lock stops edits, never reading: a table lists its editing buttons
  // by name (`.wc-remove`, the Drafted tag), never "every button in it", or
  // a read-only control (Watch's info icon) is swallowed with them.
  const DEMO_LOCKED = [
    "#change-conventions", "#new-conventions", "#change-input-list", "#change-instructions",
    "#new-instructions", "#instr-create-btn", "#conv-save-btn", "#instr-save-btn",
    "#conv-example-insert", "#instr-example-insert", "#conv-replace-default",
    "#input-save-btn", "#input-add-row", "#input-table input", "#input-table button",
    "#input-table select", "#plan-input-save-btn", "#plan-browse-btn", "#run-build-btn",
    "#plan-rebuild-btn", "#status-rebuild-btn", "#apply-arm-checkbox",
    "#apply-run-btn", "#undo-preview-btn", "#undo-run-btn", "#promote-confirm-btn",
    "#wc-change-btn", "#wc-new-btn", "#wc-save-btn", "#wc-add-btn", "#wc-table input",
    "#wc-table select", "#wc-table .wc-remove", "#wc-table button.wc-source-drafted",
  ].join(", ");
  function demoLocked(target) {
    return isDemoShow() && target && target.closest ? target.closest(DEMO_LOCKED) : null;
  }
  // A locked control does not answer with a red line under the
  // bar. Apply's say what is locked under the control itself (apply.js);
  // anywhere else, the press opens the Demo popup -- what works here, and
  // what is switched off.
  document.addEventListener("click", (ev) => {
    if (!demoLocked(ev.target)) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    openPopup("demo-popup");
  }, true);
  ["beforeinput", "keydown"].forEach((type) => {
    document.addEventListener(type, (ev) => {
      if (!demoLocked(ev.target)) return;
      if (type === "keydown" && (ev.key === "Tab" || ev.key === "Escape")) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      openPopup("demo-popup");
    }, true);
  });

  el("stale-reload-btn").addEventListener("click", () => location.reload());

  setInterval(() => {
    if (document.visibilityState === "visible") checkServer();
  }, 3000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkServer();
  });
  window.addEventListener("focus", () => { checkServer(); });
  // A tab restored from the browser's back/forward cache runs no script
  // again -- this is the only sign it was away.
  window.addEventListener("pageshow", () => { checkServer(); });

  // ---- the findings dock ----------------------------------------------
  // Renders atoo.diagnostics.Diagnostic dicts (`to_dict()`) and only
  // those, so the UI is a client against the same engine rather than a
  // second renderer with its own opinions about severity (D9, FR-X.15b).
  //
  // One UI-only key is added on top of that wire shape, and later phases
  // attach it: `jumps`, a list of {label, mode, target} -- `target` a CSS
  // selector on this page, `mode` the mode to switch to first. A
  // Diagnostic has no idea where on a screen its cause is shown, so the
  // layer that renders the cause is the layer that says.

  const dockCol = el("dock-col");
  const dockTab = el("dock-tab");
  const dockActiveList = el("dock-active-list");
  const dockActiveEmpty = el("dock-active-empty");
  const dockResolved = el("dock-resolved");
  const dockResolvedList = el("dock-resolved-list");

  let findings = [];

  function severityRank(severity) {
    const rank = SEVERITY_ORDER[severity];
    return rank == null ? 99 : rank;
  }

  function jumpTo(jump) {
    if (jump.mode) activateMode(jump.mode);
    if (!jump.target) return;
    requestAnimationFrame(() => {
      const target = document.querySelector(jump.target);
      if (!target) return;
      if (target.tagName === "DETAILS") target.open = true;
      // A jump onto a Build tile has to open the step behind it. Without
      // this the tab flashes and the panel underneath is still the one
      // you were on -- a jump link that lands you where you cannot see
      // the cause is worse than no link at all.
      if (target.dataset && target.dataset.step) activateStep(target.dataset.step);
      // A row with more behind a disclosure (step 04's table) opens it:
      // the step that drew the row listens for this and says how.
      // The jump itself rides along as `detail`: a step's text editor
      // reads `detail.find`, the line a finding quotes, and selects it.
      target.dispatchEvent(new CustomEvent("atoo:jump", { bubbles: true, detail: jump }));
      target.scrollIntoView({ block: "center" });
      target.classList.add("jump-flash");
      setTimeout(() => target.classList.remove("jump-flash"), 1200);
    });
  }

  // ---- one line per finding -------------------------------
  // The design was approved on 2026-10-11, as shown.
  // Each finding is ONE line -- where it is, the way the desk names it,
  // and its claim -- clamped to two at the dock's 300 px; a click opens
  // the explanation, the Fix, the code, the source and the jump links.
  //
  // WHERE: the server's `strip` ("CH 23 Crowd", `finding_groups.
  // label_strips`, which has the plan), else the message's own
  // "ch 23 'Crowd'" prefix, else the `where` in plainer words: the name
  // inside `channels[...]`, a file's own name, "Plan" or "Apply".
  //
  // CLAIM: a producer's own short `title` -- the critic's `claim`, an audit
  // rule's name -- else the message up to its first
  // colon, semicolon or " -- ", with the strip prefix taken off, and
  // the "'s" after it ("pre-insert: V-REV goes into FX5"). A
  // critic finding that predates the claim has none and is cut at its
  // first sentence as well, and at twelve words.

  const BANK_WORDS = { ch: "CH", channel: "CH", aux: "AUX", bus: "BUS", mtx: "MTX",
    main: "MAIN", dca: "DCA" };
  const STRIP_PREFIX =
    /^(ch|aux|bus|mtx|main|dca|channel)\s+(\d+)(?![\w-])(?:\s*\(\s*'?([^)']*)'?\s*\)|\s+'([^']*)')?:?\s*/i;
  // "ch 8-40, aux 1-8: not in this plan, ..." -- several ranges of strips.
  const RANGE_PREFIX = /^((?:ch|aux|bus|mtx|main|dca)\s+\d+(?:-\d+)?(?:,\s*(?:(?:ch|aux|bus|mtx|main|dca)\s+)?\d+(?:-\d+)?)*):\s+/i;
  const PLAN_PATH = /^([A-Za-z_][\w.]*)\[([^[\]]+)\]/;
  const DESK_KINDS = ["channels", "busses", "outputs", "dcas", "mute_groups"];
  const CLAIM_CUT = /:\s|;\s?|\s--\s/g;
  const CRITIC_CUT = /:\s|;\s?|\s--\s|\.\s/g;
  const CRITIC_WORDS = 12;
  // What is left of "bus 7 ('Vox Verb')'s pre-insert: ..." once the
  // strip prefix is off.
  const POSSESSIVE = /^'s\s+/;
  // INFO codes that say how the reply was read -- build
  // plumbing -- shown in their own closed fold. `finding_groups`
  // decides; the page reads the list. Never an ERROR or a WARNING.
  const BUILD_DETAILS = new Set(startup.build_detail_codes || []);

  function stripOf(finding) {
    if (finding.strip) return finding.strip;
    const range = RANGE_PREFIX.exec(finding.message || "");
    if (range && /[-,]/.test(range[1])) {
      return range[1].replace(/\b(ch|aux|bus|mtx|main|dca)\b/gi, (w) => BANK_WORDS[w.toLowerCase()]);
    }
    const m = STRIP_PREFIX.exec(finding.message || "");
    if (!m) return "";
    const name = m[3] || m[4];
    return BANK_WORDS[m[1].toLowerCase()] + " " + m[2] + (name ? " " + name : "");
  }

  function whereOf(finding) {
    const strip = stripOf(finding);
    if (strip) return strip;
    const where = String(finding.where || "").trim();
    if (!where) return finding.source === "apply" ? "Apply" : "Plan";
    const path = PLAN_PATH.exec(where);
    if (path) return path[2] + where.slice(path[0].length);
    // A grouped entry's "ch 1-22 (22 channels)" (the critic's own free
    // text is left as it wrote it).
    const bank = /^(ch|aux|bus|mtx|main|dca)\b/i.exec(where);
    if (bank && finding.source !== "critic") {
      return BANK_WORDS[bank[1].toLowerCase()] + where.slice(bank[0].length);
    }
    // A file: its own name ("sixpiece/plan.json" -> "plan.json").
    if (/^\S+[\\/]\S+$/.test(where) || /^\S+\.(json|md|csv|txt)$/i.test(where)) {
      return where.split(/[\\/]/).pop();
    }
    return where.charAt(0).toUpperCase() + where.slice(1);
  }

  // A finding about a strip (or several) rather than a file: these come
  // first among the things to check.
  function isDesk(finding) {
    if (stripOf(finding)) return true;
    const path = PLAN_PATH.exec(String(finding.where || ""));
    if (path && DESK_KINDS.indexOf(path[1].split(".").pop()) !== -1) return true;
    return Array.isArray(finding.members) && finding.members.some((m) => !!stripOf(m));
  }

  // [claim, the rest of the message after it].
  function splitClaim(finding) {
    const critic = finding.source === "critic";
    let text = String(finding.message || "");
    const range = RANGE_PREFIX.exec(text);
    text = range && /[-,]/.test(range[1]) ? text.slice(range[0].length) : text.replace(STRIP_PREFIX, "");
    // "sixpiece/plan.json is older than its inputs" under "plan.json":
    // the line has already said where.
    const where = String(finding.where || "").trim();
    if (where && text.startsWith(where + " ")) text = text.slice(where.length + 1);
    if (finding.title) return [finding.title, String(finding.message || "")];
    // "bus 7 ('Vox Verb')'s pre-insert: V-REV goes into FX5
    // -- ...". The "'s" belongs to the strip the line already names; what
    // it owns ("pre-insert") leads the claim, and is one word, so the
    // cut below passes over its colon.
    text = text.replace(POSSESSIVE, "");
    // The first separator that leaves a claim of two words or more: "A:
    // the reply chose the group ..." is not cut after "A".
    let cut = null;
    for (const m of text.matchAll(critic ? CRITIC_CUT : CLAIM_CUT)) {
      if (text.slice(0, m.index).trim().split(/\s+/).length >= 2) { cut = m; break; }
    }
    let claim = cut ? text.slice(0, cut.index) : text;
    let rest = cut ? text.slice(cut.index + cut[0].length) : "";
    if (critic) {
      const words = claim.split(/\s+/);
      if (words.length > CRITIC_WORDS) {
        claim = words.slice(0, CRITIC_WORDS).join(" ") + " …";
        rest = String(finding.message || "");
      }
    }
    return [claim.trim() || String(finding.message || ""), rest.trim()];
  }
  function claimOf(finding) { return splitClaim(finding)[0]; }

  // Rows whose details are open, by a key that survives a redraw (a
  // tick redraws the dock); not kept across reloads.
  const openRows = {};
  function rowKey(finding) {
    return [finding.severity, finding.code || "", finding.where || "", finding.source || "",
      String(finding.message || "").slice(0, 80)].join("\u0000");
  }

  // Each jump is a quiet button: brass words, 13px,
  // and the brass focus ring every `.btn` has.
  function jumpLinks(jumps) {
    const links = document.createElement("div");
    links.className = "dock-item-links";
    jumps.forEach((jump) => {
      const a = document.createElement("a");
      a.className = "btn btn-quiet dock-jump";
      a.href = jump.target || "#";
      a.textContent = (jump.label || "Go there") + " →";
      a.addEventListener("click", (ev) => { ev.preventDefault(); jumpTo(jump); });
      links.appendChild(a);
    });
    return links;
  }

  function para(cls, text) {
    const p = document.createElement("p");
    p.className = cls;
    p.textContent = text;
    return p;
  }

  // `row` is one line the dock draws: `entries` (see `dockEntries`) --
  // one, or several that say the same thing about different strips --
  // and, for several, the `where` and `claim` the line reads.
  function findingElement(row) {
    const entries = row.entries;
    const first = entries[0];
    const finding = first.finding;
    const severity = SEVERITY_ORDER[finding.severity] == null ? "info" : finding.severity;
    const grouped = entries.length > 1;

    const li = document.createElement("li");
    li.className = "dock-item";
    li.dataset.sev = severity;
    li.dataset.key = String(first.index);
    if (finding.code) li.dataset.code = finding.code;
    if (row.advice) li.classList.add("is-advice");

    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "dock-item-check";
    check.setAttribute("aria-label", "Mark addressed");
    check.addEventListener("change", () => {
      entries.forEach((entry) => {
        entry.finding._resolved = check.checked;
        entry.twins.forEach((twin) => { twin._resolved = check.checked; });
      });
      // Ticking moves the row between the lists, so the dock is redrawn
      // and this very checkbox replaced. Keyboard focus would land back
      // on <body> without the argument -- a tab order that resets every
      // time you tick something is a tab order nobody uses twice.
      renderFindings(first.index);
    });
    check.checked = entries.every((entry) => !!entry.finding._resolved);
    li.appendChild(check);

    const details = document.createElement("details");
    details.className = "dock-row";
    const key = rowKey(finding) + (grouped ? "\u0000group" : "");
    details.open = !!openRows[key];
    details.addEventListener("toggle", () => { openRows[key] = details.open; });

    const summary = document.createElement("summary");
    const line = document.createElement("span");
    line.className = "dock-line";
    // The severity, as a word, in the shared tint tag.
    const sev = document.createElement("span");
    sev.className = "sev sev-" + severity;
    sev.textContent = severity === "error" ? "Error" : (severity === "warning" ? "Warning" : "Info");
    line.appendChild(sev);
    line.appendChild(document.createTextNode(" "));
    const [claim, rest] = splitClaim(finding);
    const where = document.createElement("span");
    where.className = "dock-where";
    where.textContent = grouped ? row.where : whereOf(finding);
    line.appendChild(where);
    line.appendChild(document.createTextNode(" "));
    const claimEl = document.createElement("span");
    claimEl.className = "dock-claim";
    claimEl.textContent = grouped ? row.claim : claim;
    line.appendChild(claimEl);
    summary.appendChild(line);
    const chevron = document.createElement("span");
    chevron.className = "chevron";
    chevron.textContent = "▸";
    summary.appendChild(chevron);
    details.appendChild(summary);

    const body = document.createElement("div");
    body.className = "dock-item-body";
    if (grouped) {
      const members = document.createElement("ul");
      members.className = "dock-members";
      entries.forEach((entry) => {
        const m = document.createElement("li");
        m.className = "dock-member";
        m.dataset.key = String(entry.index);
        const b = document.createElement("b");
        b.textContent = whereOf(entry.finding);
        m.appendChild(b);
        const [mClaim, mRest] = splitClaim(entry.finding);
        m.appendChild(document.createTextNode(" " + (mRest || mClaim)));
        members.appendChild(m);
      });
      body.appendChild(members);
    } else {
      // The whole message, as the producer wrote it -- unless the line
      // above already said all of it.
      const message = String(finding.message || "");
      if (message && (rest || finding.title || message !== claim)) {
        body.appendChild(para("dock-item-text", message));
      }
    }
    // `fix` is what the engineer can change; `issue` means they cannot,
    // and this is ours. Diagnostic draws that distinction on purpose
    //  and a dock that flattened it would undo the whole point.
    if (grouped) {
      [...new Set(entries.map((entry) => entry.finding.fix).filter(Boolean))]
        .forEach((fix) => body.appendChild(para("dock-item-fix", "Fix: " + fix)));
    } else if (finding.fix) {
      body.appendChild(para("dock-item-fix", "Fix: " + finding.fix));
    }
    if (finding.issue != null) {
      body.appendChild(para("dock-item-limitation",
        "Not something you can fix in your conventions file — issue #" + finding.issue));
    }
    const foot = document.createElement("div");
    foot.className = "dock-item-foot";
    if (finding.code) {
      const code = document.createElement("span");
      code.className = "readout dock-code";
      code.textContent = finding.code;
      foot.appendChild(code);
    }
    if (finding.source) {
      // A fact about the finding: the property tag (§6).
      const src = document.createElement("span");
      src.className = "prop";
      src.textContent = finding.source;
      foot.appendChild(src);
    }
    const seen = {};
    const jumps = [];
    entries.forEach((entry) => entry.jumps.forEach((j) => {
      const k = (j.mode || "") + "\u0000" + (j.target || "") + "\u0000" + (j.find || "");
      if (!seen[k]) { seen[k] = true; jumps.push(j); }
    }));
    if (jumps.length) foot.appendChild(jumpLinks(jumps));
    body.appendChild(foot);
    details.appendChild(body);
    li.appendChild(details);
    li.id = "finding-" + (finding.code ? finding.code.replace(/[^A-Za-z0-9_-]/g, "-") : first.index);
    return li;
  }
  // ---- what the dock shows: one row per finding, said once ------------
  //
  // All the findings go to the
  // sidebar, with no duplication. Two passes can
  // say the same thing: step 04's plan carries the verify its build ran,
  // and Apply's pre-flight runs that verify again on the same plan.json;
  // the build and its verify each announce the preset values a plan
  // carries (`preset.expanded`). A finding with the same severity, code
  // and `where` as one from a DIFFERENT origin -- another producer, or
  // another `source` (build, verify, critic) -- is the same finding: it
  // is shown once, in the words of whichever came last (the newest
  // reading), with the jump links of both. One origin's own repeats are
  // never merged: the critic says two different things about
  // Ambient/EKIT, and both are shown.

  // Index into `findings` -> the index of the row it is shown under.
  let shownAt = {};

  function dockEntries() {
    const byKey = {};
    const entries = [];
    shownAt = {};
    findings.forEach((finding, index) => {
      const key = [finding.severity, finding.code || "", finding.where || ""].join("\u0000");
      const prior = byKey[key];
      const origin = (finding._producer || "") + "/" + (finding.source || "");
      if (prior && prior.origins.indexOf(origin) === -1) {
        prior.twins.push(prior.finding);
        prior.finding = finding;
        prior.index = index;
        prior.origins.push(origin);
        return;
      }
      const entry = { finding, index, order: index, twins: [], origins: [origin] };
      // An origin's own repeat is its own row; only a second origin
      // saying the same thing is folded into the first one's row.
      if (!prior) byKey[key] = entry;
      entries.push(entry);
    });
    entries.forEach((entry) => {
      const seen = {};
      entry.jumps = [];
      [entry.finding].concat(entry.twins).forEach((finding) => {
        (Array.isArray(finding.jumps) ? finding.jumps : []).forEach((j) => {
          const k = (j.mode || "") + "\u0000" + (j.target || "") + "\u0000" + (j.find || "");
          if (seen[k]) return;
          seen[k] = true;
          entry.jumps.push(j);
        });
      });
      entry.resolved = !!entry.finding._resolved;
      shownAt[entry.index] = entry.index;
      entry.twins.forEach((t) => { shownAt[findings.indexOf(t)] = entry.index; });
    });
    return entries;
  }

  // How many items a row stands for: a grouped entry (FR-X.15c) is its
  // `members`, anything else is one.
  function itemCount(finding) {
    return Array.isArray(finding.members) && finding.members.length ? finding.members.length : 1;
  }

  // ---- the dock's sections --------------------------------
  //
  //   the verdict      Ready to apply / Stale / Blocked, and three counts
  //   To check         errors, then warnings; desk before files
  //   Advice           the critic's warnings: a second model's opinion,
  //                    still WARNING and counted, never blocking Apply
  //   Choices          every INFO but build details, folded
  //   Build details    the plumbing, a second closed fold
  //
  // The words for a code ("3 strips: built from instructions.md, ...")
  // come from `finding_groups.CODE_SUMMARIES`, in the startup data.
  const CODE_WORDS = startup.finding_codes || {};
  const INFO_OPEN_KEY = "atoo.dock.infoOpen";
  const DETAILS_OPEN_KEY = "atoo.dock.detailsOpen";
  const dockVerdict = el("dock-verdict");
  const dockCheck = el("dock-check");
  const dockAdvice = el("dock-advice");
  const dockAdviceList = el("dock-advice-list");
  const dockInfo = el("dock-info");
  const dockInfoList = el("dock-info-list");
  const dockDetails = el("dock-details");
  const dockDetailsList = el("dock-details-list");

  // A fold's open state, kept per viewer (a private window throws).
  function rememberFold(details, key) {
    if (!details) return;
    try { details.open = localStorage.getItem(key) === "1"; } catch (e) { details.open = false; }
    details.addEventListener("toggle", () => {
      try { localStorage.setItem(key, details.open ? "1" : "0"); } catch (e) { /* not kept */ }
    });
  }
  rememberFold(dockInfo, INFO_OPEN_KEY);
  rememberFold(dockDetails, DETAILS_OPEN_KEY);

  function codeSummary(code, count) {
    const words = CODE_WORDS[code] || ["note", "notes", code || "uncoded"];
    return count + " " + (count === 1 ? words[0] : words[1]) + ": " + words[2];
  }

  // Several entries that say one thing about different strips are one
  // row (three "built from instructions.md" warnings become
  // "3 strips ..."), listing each strip inside. `keyOf` says which may
  // share a row; they do only when the code has words of its own or
  // every one makes the same claim -- a row must never hide a value
  // behind a summary nobody wrote.
  function gather(entries, keyOf) {
    const rows = [];
    const buckets = {};
    entries.forEach((entry) => {
      const key = keyOf(entry.finding);
      if (key != null && buckets[key]) { buckets[key].entries.push(entry); return; }
      const row = { entries: [entry] };
      if (key != null) buckets[key] = row;
      rows.push(row);
    });
    const out = [];
    rows.forEach((row) => {
      if (row.entries.length < 2) { out.push(row); return; }
      const code = row.entries[0].finding.code || "";
      const claims = new Set(row.entries.map((entry) => claimOf(entry.finding)));
      if (!CODE_WORDS[code] && claims.size !== 1) {
        row.entries.forEach((entry) => out.push({ entries: [entry] }));
        return;
      }
      const count = row.entries.reduce((n, entry) => n + itemCount(entry.finding), 0);
      const words = CODE_WORDS[code];
      row.where = count + " " + (words ? words[1] : "strips");
      row.claim = words ? words[2] : [...claims][0];
      out.push(row);
    });
    return out;
  }

  // A rebuild's change nobody asked for is one row per strip, always:
  // three strips with the same "gain 20 -> 26 dB"
  // are three things to check, not one.
  const NEVER_GATHERED = new Set(["rebuild.unasked-change"]);
  const checkKey = (f) => (isDesk(f) && !(f.members && f.members.length) && !NEVER_GATHERED.has(f.code)
    ? [f.severity, f.code || "", f.source || "", f.fix || "", f.title || ""].join("\u0000") : null);
  const infoKey = (f) => (f.code ? f.code : null);

  function bySeverity(a, b) {
    return severityRank(a.finding.severity) - severityRank(b.finding.severity) || a.order - b.order;
  }

  // The plan's freshness, as Build last read it; null before the first
  // read or with no bundle (`build` is declared further down the file).
  function planState() {
    try {
      const fresh = ((buildPending || build) || {}).plan_freshness;
      return fresh && fresh.state ? fresh.state : null;
    } catch (e) {
      return null;
    }
  }

  // What a stale plan is stale against, in the engineer's words: the
  // files `plan_freshness` named as changed ("the input list and the
  // conventions"). The Apply screen says it the same way (`SP.stalePlanWhat`).
  const STALE_SLOT_WORDS = {
    conventions: "the conventions",
    input_list: "the input list",
    instructions: "the instructions",
  };
  function stalePlanWhat(freshness) {
    const words = [];
    ((freshness && freshness.reasons) || []).forEach((reason) => {
      const w = STALE_SLOT_WORDS[reason.slot];
      if (w && words.indexOf(w) < 0) words.push(w);
    });
    if (!words.length) return "An input";
    const joined = words.length > 1 ? words.slice(0, -1).join(", ") + " and " + words[words.length - 1] : words[0];
    return joined.charAt(0).toUpperCase() + joined.slice(1);
  }

  let lastCounts = null;
  function renderVerdict(counts) {
    if (counts) lastCounts = counts;
    counts = lastCounts;
    if (!dockVerdict || !counts) return;
    const state = planState();
    const hasPlan = !!state && state !== "none";
    dockVerdict.textContent = "";
    dockVerdict.hidden = !hasPlan && counts.rows === 0;
    if (dockVerdict.hidden) return;
    const blocked = counts.errors > 0;
    // A plan older than the files it was built from is not ready to apply:
    // it does not include the edit. The same freshness the Plan tile reads
    // (`plan_freshness`), so the tile and the verdict cannot disagree.
    const stale = hasPlan && (state === "stale" || !!counts.stale);
    // A large severity tag leads -- green Ready to apply, yellow Stale,
    // red Blocked -- and with no plan yet a neutral grey No plan yet (blue
    // is information only). The left edge follows. Errors come first: a
    // plan that cannot be applied says so before it says it is old.
    const verdict = blocked ? "blocked" : (stale ? "stale" : (hasPlan ? "ok" : "none"));
    dockVerdict.dataset.state = verdict;
    const head = document.createElement("div");
    head.className = "dock-verdict-head";
    const badge = document.createElement("span");
    badge.className = "sev big " + { blocked: "sev-error", stale: "sev-warning", ok: "sev-ok", none: "sev-none" }[verdict];
    badge.textContent = { blocked: "Blocked", stale: "Stale", ok: "Ready to apply", none: "No plan yet" }[verdict];
    head.appendChild(badge);
    const sub = document.createElement("span");
    sub.className = "meta dock-verdict-sub";
    // A warning reads beside the verdict --
    // "Ready to apply · 1 to check" -- and never blocks Apply. A rebuild's
    // change nobody asked for is one of them.
    sub.textContent = blocked ? counts.errors + " error" + (counts.errors === 1 ? "" : "s")
      : (counts.check ? "· " + counts.check + " to check" : "no errors");
    head.appendChild(sub);
    dockVerdict.appendChild(head);
    const lines = document.createElement("ul");
    lines.className = "dock-verdict-lines";
    // A count is bold white when it is not zero, and dim when it is.
    [[counts.check, "to check"], [counts.advice, "advice from the critic"],
      [counts.choices, "notes on choices the build made"]].forEach(([n, words]) => {
      const li = document.createElement("li");
      if (!n) li.className = "is-zero";
      const b = document.createElement("b");
      b.textContent = String(n);
      li.appendChild(b);
      li.appendChild(document.createTextNode(" " + words));
      lines.appendChild(li);
    });
    dockVerdict.appendChild(lines);
    // Said ONCE, here, rather than after every build and critic note.
    // A state tag, the sentence beside it in meta type, and Rebuild as a
    // quiet button (§6: a tag holds a word, never a sentence).
    if (stale) {
      const note = document.createElement("p");
      note.className = "dock-verdict-stale";
      // The badge above already says Stale; under Blocked the tag does.
      if (verdict !== "stale") {
        const tag = document.createElement("span");
        tag.className = "state is-warn";
        tag.textContent = "Stale";
        note.appendChild(tag);
      }
      const words = document.createElement("span");
      words.className = "meta";
      words.textContent = stalePlanWhat((buildPending || build || {}).plan_freshness) +
        " changed since the last build: rebuild before applying. " +
        "The build's and the critic's notes are as built.";
      note.appendChild(words);
      const rebuild = { label: "Rebuild", mode: "build", target: "#tab-plan" };
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-quiet dock-jump";
      btn.textContent = "Rebuild";
      btn.addEventListener("click", () => jumpTo(rebuild));
      note.appendChild(btn);
      dockVerdict.appendChild(note);
    }
  }

  function fill(list, rows, advice) {
    if (!list) return;
    list.textContent = "";
    rows.forEach((row) => {
      row.advice = advice;
      list.appendChild(findingElement(row));
    });
  }

  function renderFindings(refocusKey) {
    dockActiveList.textContent = "";
    dockResolvedList.textContent = "";

    const entries = dockEntries();
    const active = entries.filter((entry) => !entry.resolved);
    const isInfo = (entry) => severityRank(entry.finding.severity) >= SEVERITY_ORDER.info;
    const isAdvice = (entry) => !isInfo(entry) && entry.finding.source === "critic";
    // Desk findings before file findings, within a severity; otherwise
    // in the order the engine produced them, so ticking one never
    // shuffles its peers.
    const check = active.filter((entry) => !isInfo(entry) && !isAdvice(entry)).sort((a, b) =>
      severityRank(a.finding.severity) - severityRank(b.finding.severity)
      || (isDesk(a.finding) ? 0 : 1) - (isDesk(b.finding) ? 0 : 1) || a.order - b.order);
    const advice = active.filter(isAdvice).sort(bySeverity);
    const infos = active.filter(isInfo).sort(bySeverity);
    const details = infos.filter((entry) => BUILD_DETAILS.has(entry.finding.code));
    const choices = infos.filter((entry) => !BUILD_DETAILS.has(entry.finding.code));

    // Each section's count is the rows it draws: six
    // journal notes gathered into one "6 notes" row count once, as they
    // are seen -- not twelve beside seven rows. The row says how many it
    // stands for.
    const checkRows = gather(check, checkKey);
    const adviceRows = advice.map((entry) => ({ entries: [entry] }));
    const choiceRows = gather(choices, infoKey);
    const detailRows = gather(details, infoKey);
    fill(dockActiveList, checkRows, false);
    fill(dockAdviceList, adviceRows, true);
    fill(dockInfoList, choiceRows, false);
    fill(dockDetailsList, detailRows, false);
    entries.filter((entry) => entry.resolved).forEach((entry) => {
      const node = findingElement({ entries: [entry] });
      node.classList.add("is-resolved");
      dockResolvedList.appendChild(node);
    });

    if (dockCheck) dockCheck.hidden = check.length === 0;
    if (dockAdvice) dockAdvice.hidden = advice.length === 0;
    if (dockInfo) dockInfo.hidden = choices.length === 0;
    if (dockDetails) dockDetails.hidden = details.length === 0;
    const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
    setText("dock-check-count", String(checkRows.length));
    setText("dock-advice-count", String(adviceRows.length));
    setText("dock-info-count", String(choiceRows.length));
    setText("dock-details-count", String(detailRows.length));

    const resolved = entries.length - active.length;
    // The badge counts what needs a look -- errors and warnings, the
    // critic's included -- not every row; in rows, as the
    // sections below it count.
    const needsLook = checkRows.length + adviceRows.length;
    const counts = {
      rows: active.length,
      errors: entries.filter((entry) => entry.finding.severity === "error"
        && entry.finding.source !== "critic").length,
      check: checkRows.length, advice: adviceRows.length, choices: choiceRows.length,
      stale: active.some((entry) => !!entry.finding.stale),
    };
    renderVerdict(counts);
    dockActiveEmpty.hidden = active.length > 0 || (!!planState() && planState() !== "none");
    dockResolved.hidden = resolved === 0;
    el("dock-resolved-count").textContent = String(resolved);
    // The count badge: neutral grey at 0, red with any
    // error, yellow with warnings only. Never brass.
    const tone = counts.errors > 0 ? "is-err" : (needsLook > 0 ? "is-warn" : "is-zero");
    ["dock-title-count", "dock-tab-count"].forEach((id) => {
      const badge = el(id);
      badge.textContent = String(needsLook);
      badge.classList.remove("is-zero", "is-warn", "is-err");
      badge.classList.add(tone);
    });

    if (refocusKey != null) {
      const moved = document.querySelector(
        '.dock-item[data-key="' + refocusKey + '"] .dock-item-check'
      );
      if (moved) moved.focus();
    }
    findingsListeners.forEach((fn) => {
      try { fn(findings.slice()); } catch (e) { /* one listener must not stop the rest */ }
    });
  }

  // What the dock shows, one object per row (a finding two producers
  // published is one row, as the newest of them): what step 04's per-row
  // badges and its summary line count, so they count what you can see.
  function shownFindings() {
    return dockEntries().map((entry) => entry.finding);
  }

  // Fired with the list every time the dock is redrawn -- a producer
  // replaced its findings, or one was ticked: step 04's per-row badges
  // recount from it.
  const findingsListeners = [];

  // The other way round from a jump link: a badge on a row (step 04)
  // points at its findings in the dock. `list` holds the dock's own
  // objects (from `findings()`); each is scrolled to and flashed, the
  // first one centred, the dock opened first if it was collapsed -- and
  // every fold it sits in with it (Choices, Build details, Addressed, a
  // row of several strips), when that is where the finding is. A row of
  // several strips flashes the strip's own line inside it.
  function showFindings(list) {
    dockEntries();
    const wanted = (Array.isArray(list) ? list : [list]).map((f) => shownAt[findings.indexOf(f)])
      .filter((i) => i != null);
    if (!wanted.length) return false;
    if (dockCol.classList.contains("is-collapsed")) toggleDock();
    let first = null;
    wanted.forEach((index) => {
      const li = document.querySelector('#findings-dock .dock-member[data-key="' + index + '"]')
        || document.querySelector('#findings-dock .dock-item[data-key="' + index + '"]');
      if (!li) return;
      for (let fold = li.parentElement.closest("details"); fold;
        fold = fold.parentElement && fold.parentElement.closest("details")) {
        fold.open = true;
      }
      if (!first) first = li;
      li.classList.remove("jump-flash");
      // Restart the flash on a second click.
      void li.offsetWidth;
      li.classList.add("jump-flash");
      setTimeout(() => li.classList.remove("jump-flash"), 1600);
    });
    if (first) first.scrollIntoView({ block: "center" });
    return !!first;
  }

  // Opens the dock on its first finding -- the "in Findings" link on step
  // 04's and Apply's one-line summaries.
  function revealDock() {
    if (dockCol.classList.contains("is-collapsed")) toggleDock();
    const body = document.querySelector("#findings-dock .dock-body");
    if (body) body.scrollTop = 0;
    dockCol.scrollIntoView({ block: "nearest" });
  }
  function toggleDock() {
    const collapsed = dockCol.classList.toggle("is-collapsed");
    dockTab.setAttribute("aria-expanded", String(!collapsed));
  }

  // Focus follows the control that replaces the one pressed (the jump
  // links call toggleDock too, and keep their own focus).
  dockTab.addEventListener("click", () => { toggleDock(); el("dock-collapse-btn").focus(); });
  el("dock-collapse-btn").addEventListener("click", () => { toggleDock(); dockTab.focus(); });

  function setFindings(list) {
    findings = (Array.isArray(list) ? list : []).map((f) => Object.assign({}, f));
    renderFindings();
  }

  function addFindings(list) {
    (Array.isArray(list) ? list : [list]).forEach((f) => findings.push(Object.assign({}, f)));
    renderFindings();
  }

  // ---- Build steps 01-03: the three file tiles -------------------------
  // Version H, phase 2. The three files `atoo build` reads, each on
  // its own tile with its derived path and a state badge, each shown
  // read-only, and step 03 drawing the two conventions layers with an
  // `overrides house` / `adds to house` tag per section.
  //
  // Nothing here compiles anything. `GET /api/build/sources` reads three
  // files and answers; `POST /api/build/sources/load` points one tile at
  // a different path. Every finding reading them produced goes into the
  // shared dock above, with a jump link back to the tile that raised it.

  const BUILD_SLOTS = ["conventions", "input_list", "instructions"];
  // Step 04's tile and panel are setup.js's: it reads the bundle's own
  // plan.json and runs the build that writes it.
  const STEPS = ["conventions", "input_list", "instructions", "plan"];
  const STEP_LABEL = {
    conventions: "01 Conventions",
    input_list: "02 Input list",
    instructions: "03 Instructions",
    plan: "04 Plan",
  };
  // The tile's state tag (`.state`):
  // Loaded is green, Stale yellow, Missing red, Not set neutral grey.
  // `stale` is the only one the server cannot answer -- it is a
  // comparison between two reads (see `absorb` below).
  const STATE_BADGE = {
    loaded: { text: "Loaded", cls: "is-ok" },
    missing: { text: "Missing", cls: "is-err" },
    notset: { text: "Not set", cls: "" },
    stale: { text: "Stale", cls: "is-warn" },
  };

  const slotId = (slot) => slot.replace(/_/g, "-");

  let build = startup.build || null;
  // A newer read that has NOT been put on screen. Replacing what someone
  // is reading, without their asking, is how a person ends up quoting a
  // section that is no longer in the file -- so a changed file marks the
  // tile Stale and waits for Reload.
  let buildPending = null;
  let staleSlots = [];
  let currentStep = "conventions";
  // Which steps have unsaved changes: steps 01 and 03
  // once their editor's text differs from the file, step 02 once a cell
  // has been changed. A step being edited is not redrawn by a re-read.
  const editingStep = { conventions: false, instructions: false, input_list: false };

  // Whether step 02 has an input list on screen. Save, Discard and the
  // read-only reason are in the block header, which is always there, so
  // they are tied to this rather than to the rows' toolbar.
  let inputListLoaded = false;
  // Fired with the build payload whenever it is re-read -- setup.js draws
  // the plan's Stale badge and Rebuild button from `plan_freshness`.
  const buildListeners = [];
  // The dock's verdict says Ready to apply only once a plan is there, and
  // Stale instead while the plan is older than its files.
  buildListeners.push(() => renderVerdict());
  // Fired whenever step 02's rows change -- an edit, a row added or
  // removed, a redraw after Save or Discard -- with where the change came
  // from ("input-list", or "plan" for an edit made through step 04).
  // Step 04's table draws its Input cells from these same rows
  // (`window.Atoo.inputEditor`), so the two views are one editor.
  const inputListeners = [];
  // Fired when a build on step 04 has written a new plan.json (setup.js
  // calls `planBuilt()`): Apply re-reads its pre-flight, whose findings
  // were about the plan the build replaced.
  const planBuiltListeners = [];
  let inputKeySeq = 0;
  // The input list's `order` column (FR-1.1, 2026-10-09): the
  // band's own input number, `-` for skip (the row stays in the file and
  // the next build leaves it out), or blank. input_list.SKIP_MARK.
  const SKIP_MARK = "-";

  function buildSource(slot) {
    return (build && build[slot]) || null;
  }

  // What makes two reads of the same file different. `state` is in here
  // as well as mtime/size because "the file was deleted" is a change a
  // timestamp cannot report.
  function stamp(source) {
    if (!source) return "none";
    // `sha256` too: two saves inside one mtime tick
    // with the same size are still two different files.
    return [source.path, source.state, source.mtime, source.size, source.sha256].join("|");
  }

  // ---- steps ------------------------------------------------------------

  function activateStep(step) {
    if (STEPS.indexOf(step) === -1) return;
    // The bundle bar's message is about what was just done ("Created
    // .../instructions.md, empty..."): moving to another step is moving
    // on from it, so the message does not stay up.
    if (step !== currentStep) showBundleMessage("");
    currentStep = step;
    STEPS.forEach((name) => {
      const tab = el("tab-" + slotId(name));
      const panel = el("panel-" + slotId(name));
      const active = name === step;
      if (tab) {
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
      }
      if (panel) {
        panel.hidden = !active;
        panel.classList.toggle("is-active", active);
      }
    });
  }

  STEPS.forEach((step) => {
    const tab = el("tab-" + slotId(step));
    if (!tab) return;
    tab.addEventListener("click", () => activateStep(step));
    tab.addEventListener("keydown", (ev) => {
      // A key pressed on a button INSIDE the tile (Change file, Rebuild
      // plan) is that button's, not the tab's: taking Enter here would
      // swallow the button's own click.
      if (ev.target !== tab) return;
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        activateStep(step);
        return;
      }
      const delta = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
      if (!delta) return;
      ev.preventDefault();
      const next = STEPS[(STEPS.indexOf(step) + delta + STEPS.length) % STEPS.length];
      activateStep(next);
      const nextTab = el("tab-" + slotId(next));
      if (nextTab) nextTab.focus();
    });
  });

  // ---- the tiles --------------------------------------------------------

  function renderTile(slot) {
    const source = buildSource(slot);
    const badge = el("badge-" + slotId(slot));
    const hint = el("hint-" + slotId(slot));
    if (!badge || !hint) return;

    const stale = staleSlots.indexOf(slot) !== -1;
    // instructions.md is optional: a bundle without
    // one is Not set, neutral, never a red Missing.
    let key = stale ? "stale" : (source ? source.state : "notset");
    if (slot === "instructions" && key === "missing") key = "notset";
    const state = STATE_BADGE[key] || STATE_BADGE.notset;
    badge.textContent = state.text;
    badge.className = "state" + (state.cls ? " " + state.cls : "");

    // The derived path, exactly as the server composed it -- the page
    // never joins a folder and a filename itself, because a path the
    // browser built and a path the server would open are two chances to
    // disagree about a separator.
    hint.textContent = (source && source.display_path) || "not set";
    hint.title = (source && source.path) || "";

    // A tile whose file produced an ERROR says so on the tile. H's badge
    // vocabulary has no rung for "loaded, and wrong" -- the file did
    // load -- so the tile itself carries the mark and the dock carries
    // the reason.
    const tab = el("tab-" + slotId(slot));
    if (tab) {
      tab.classList.toggle(
        "has-error",
        ((source && source.findings) || []).some((f) => f.severity === "error")
      );
    }

    // The file's findings, counted on its own tile (the
    // status line's one "N findings" for all three files moved onto the
    // tiles). Nothing is shown at zero; the dock holds the findings.
    const count = el("findings-" + slotId(slot));
    if (count) {
      const list = (source && source.findings) || [];
      count.hidden = !list.length;
      count.textContent = list.length + " finding" + (list.length === 1 ? "" : "s");
      count.title = list.length ? "Listed in the Findings panel" : "";
    }

    // What this tile still needs: a file not there yet is a
    // to-do said here, beside Change file / New file -- never a finding
    // in the dock, until Build is pressed without it (`source.missing`
    // is then what `POST /api/build/run` refuses with).
    const todo = el("todo-" + slotId(slot));
    if (todo) {
      todo.textContent = (source && source.todo) || "";
      todo.title = todo.textContent;
      todo.hidden = !(source && source.todo);
    }

    const banner = el("stale-" + slotId(slot));
    if (banner) banner.hidden = !stale;
  }

  // ---- `<!-- ... -->` comments: shown, and marked as not read -----------
  //
  // The build strips every HTML comment from the conventions and
  // instructions before a model sees them (`conventions_text.py`): they
  // are the engineer's notes to himself. The page still shows the file as
  // written -- a view that hides part of the file is not the file -- but
  // each comment is a dimmed `.md-comment` span saying so on hover.
  // `segments` is the server's cut ([{text, comment}], concatenating back
  // to the text exactly), so what the page marks is what the build strips.
  // A payload from a server older than this has no segments; the plain
  // text is shown instead, unmarked, rather than nothing.
  const COMMENT_TITLE = "comment -- not read by the build";

  function renderMarked(target, segments, fallbackText) {
    target.textContent = "";
    if (!Array.isArray(segments)) {
      target.textContent = fallbackText || "";
      return;
    }
    segments.forEach((seg) => {
      if (seg.comment) {
        const span = document.createElement("span");
        span.className = "md-comment";
        span.title = COMMENT_TITLE;
        span.textContent = seg.text;
        target.appendChild(span);
      } else {
        target.appendChild(document.createTextNode(seg.text));
      }
    });
  }

  // ---- 01 Conventions ----------------------------------------------------

  function renderConventions() {
    const source = buildSource("conventions");
    const file = el("conv-house-file");
    if (file) {
      file.textContent = (source && source.display_path) || "not set";
      file.title = (source && source.path) || "";
    }
    // Where that file came from: "recorded in touringband/plan.json"
    // when the bundle's plan names the file it was built from, else the
    // config default or a typed path. `display_origin` is absent from an
    // older server, so the span stays empty rather than
    // printing "undefined".
    const origin = el("conv-house-origin");
    if (origin) {
      origin.textContent = source && source.display_origin
        ? "(" + source.display_origin + ")" : "";
    }
    renderTextEditor("conventions", source,
      "No house conventions file yet: choose one with Change file on the tile, "
      + "or start an empty one with New file.");
  }

  // ---- 02 Input list -----------------------------------------------------

  function renderInputList() {
    const source = buildSource("input_list");
    const wrap = el("input-table-wrap");
    const body = el("input-rows");
    const empty = el("input-empty");
    if (!wrap || !body || !empty) return;

    const pre = el("input-source");
    if (pre) pre.textContent = (source && source.text) || "";
    // A table with unsaved changes is not redrawn under the operator.
    if (editingStep.input_list) return;

    body.textContent = "";
    inputColumns = (source && source.columns) || INPUT_COLUMNS;
    // The table is the editor. It is drawn from `records` --
    // every row as written, read leniently -- so a list the engine's
    // loader refuses (`source.rows` is null, and the dock says which row)
    // can still be shown and fixed here. A server older than this sends
    // no records; the validated rows are drawn instead.
    const loaded = !!(source && source.state === "loaded");
    const records = (source && source.records)
      || ((source && source.rows) || []).map((row, i) => ({ line: i, values: stringValues(row) }));
    records.forEach((record) => body.appendChild(inputRow(record.line, record.values)));
    fillInputOptions(records);
    loadPresetOptions();
    markInputProblems();

    wrap.hidden = !loaded;
    const table = el("input-table");
    if (table) table.classList.toggle("is-readonly", inputReadOnly());
    const addRow = el("input-add-row");
    if (addRow) addRow.hidden = inputReadOnly();
    const toolbar = el("input-edit-toolbar");
    if (toolbar) toolbar.hidden = !loaded;
    inputListLoaded = loaded;
    empty.hidden = loaded && records.length > 0 && !!(source && source.rows);
    if (!loaded) {
      empty.textContent = "No input list. It is input.csv inside the show bundle.";
    } else if (!source.rows) {
      empty.textContent = records.length
        ? "This input list does not load as it stands -- the finding in the Findings panel names the "
          + "row. Fix it here and Save."
        : "This input list has no rows the loader can read -- the finding in the Findings panel says why.";
    } else if (!records.length) {
      empty.textContent = "This input list has no rows. + Add row, then Save.";
    }
    setInputDirty(false);
    notifyInput("input-list");
  }

  // ---- 03 Instructions, and the conventions stack ------------------------

  function renderStack() {
    const list = el("conv-stack");
    if (!list) return;
    list.textContent = "";
    const stack = (build && build.stack) || [];
    if (!stack.length) {
      const li = document.createElement("li");
      li.textContent = "No conventions layers -- a build needs at least the house file.";
      list.appendChild(li);
      return;
    }
    // Exactly what `atoo build` prints, and exactly what it writes
    // into the plan at `meta.conventions_stack`: worst precedence first,
    // path then where it came from.
    stack.forEach((layer, index) => {
      const li = document.createElement("li");
      const num = document.createElement("span");
      num.className = "stack-num";
      num.textContent = index + 1 + ".";
      li.appendChild(num);

      const path = document.createElement("code");
      // The short form, with the absolute path -- the one the plan
      // records at `meta.conventions_stack` -- on the title.
      path.textContent = layer.display_path || layer.path;
      path.title = layer.path;
      li.appendChild(path);

      const source = document.createElement("span");
      source.title = layer.source;
      source.textContent = "(" + (layer.display_source || layer.source) + ")"
        + (index === stack.length - 1 && stack.length > 1 ? " — this file, and it wins" : "");
      li.appendChild(source);

      list.appendChild(li);
    });
  }

  function renderInstructions() {
    const source = buildSource("instructions");
    renderStack();
    renderTextEditor("instructions", source,
      "No instructions.md in this bundle, so the house conventions apply in full.");
    // New file on the tile, and "Create instructions.md" under the empty message --
    // only when there is a bundle to write it into and it has none. The
    // server refuses to overwrite regardless; hiding it is the courtesy.
    const canCreate = !!(bundle && source && source.state === "missing");
    const tileBtn = el("new-instructions");
    if (tileBtn) tileBtn.hidden = !canCreate;
    const row = el("instr-create-row");
    if (row) row.hidden = !canCreate;
    const house = el("house-conv-source");
    const conventions = buildSource("conventions");
    if (house) {
      renderMarked(house, conventions && conventions.text_segments,
                   (conventions && conventions.text) || "");
    }
  }

  // ---- the status line ---------------------------------------------------

  function renderBuildStatus() {
    const rows = buildSource("input_list");
    // A skipped row (`-` in order) is in the file but not in the build:
    // the tile counts what the next build reads, and says how many are off.
    const all = rows && rows.rows ? rows.rows : null;
    const skippedCount = all ? all.filter((r) => String(r.order || "").trim() === SKIP_MARK).length : 0;
    const count = all ? all.length - skippedCount : null;
    const rowsEl = el("status-rows");
    if (rowsEl) rowsEl.textContent = count == null ? "—" : String(count);
    const skippedEl = el("status-skipped");
    if (skippedEl) {
      skippedEl.hidden = !skippedCount;
      skippedEl.textContent = skippedCount ? " · " + skippedCount + " skipped" : "";
    }
    // Step 02's block header carries the same count in its notation: every row in the file, then how many are skipped.
    const countNote = el("input-count-note");
    if (countNote) {
      countNote.textContent = all
        ? " · " + all.length + " row" + (all.length === 1 ? "" : "s")
          + (skippedCount ? " · " + skippedCount + " skipped" : "")
        : "";
    }

    const layers = ((build && build.stack) || []).length;
    const layersEl = el("status-layers");
    if (layersEl) {
      // On step 03's tile, where "layers" needs no
      // qualifier; the title says it in full. A count, not a state, so it
      // is meta text like 02's "16 input rows".
      layersEl.textContent = "";
      const count = document.createElement("strong");
      count.textContent = String(layers);
      layersEl.appendChild(count);
      layersEl.appendChild(document.createTextNode(" layer" + (layers === 1 ? "" : "s")));
      layersEl.title = layers + " conventions layer" + (layers === 1 ? "" : "s") +
        ": the house conventions, then this show's instructions -- each overrides the one above it";
    }

    // Each file's findings count is drawn on its own tile (renderTile),
    // moved the status line's readouts onto the tiles.
  }

  // ---- findings ----------------------------------------------------------

  function buildFindings() {
    const out = [];
    BUILD_SLOTS.forEach((slot) => {
      const source = buildSource(slot);
      ((source && source.findings) || []).forEach((finding) => {
        out.push(Object.assign({}, finding, {
          // UI-only, and added here rather than in Python for the reason
          // the dock's own comment gives: a Diagnostic has no idea where
          // on a screen its cause is shown.
          jumps: [{ label: STEP_LABEL[slot], mode: "build", target: "#tab-" + slotId(slot) }],
          _producer: "build",
        }));
      });
    });
    return out;
  }

  // Replaces this producer's findings and leaves everybody else's alone.
  // Phase 2 is the only thing filling the dock today; stamping them means
  // the phase that adds a second producer does not have to come back and
  // untangle one list from another.
  function publishBuildFindings() {
    const others = findings.filter((finding) => finding._producer !== "build");
    setFindings(others.concat(buildFindings()));
  }

  function renderBuild() {
    BUILD_SLOTS.forEach(renderTile);
    renderConventions();
    renderInputList();
    renderInstructions();
    publishBuildFindings();
    renderBuildStatus();
    renderEditControls();
  }

  // ---- reading, and noticing a file that changed underneath --------------

  function absorb(payload) {
    build = payload;
    buildPending = null;
    staleSlots = [];
    renderBuild();
    notifyBuild();
  }

  function notifyBuild() {
    buildListeners.forEach((fn) => {
      try { fn(buildPending || build); } catch (e) { /* one listener must not stop the rest */ }
    });
  }

  function applyPending() {
    // Reload is the operator choosing the file on disk over what is on
    // screen -- including an edit in progress on that step, whose
    // warning (and Save's 409) said so first.
    staleSlots.forEach((slot) => { editingStep[slot] = false; });
    if (buildPending) absorb(buildPending);
    renderEditControls();
  }

  async function refreshBuild(force) {
    let payload;
    try {
      const r = await fetch("/api/build/sources");
      payload = await r.json();
      if (!r.ok) return;
    } catch (e) {
      return;
    }
    if (force || !build) {
      absorb(payload);
      return;
    }
    const changed = BUILD_SLOTS.filter((slot) => stamp(payload[slot]) !== stamp(build[slot]));
    if (!changed.length) {
      absorb(payload);
      return;
    }
    buildPending = payload;
    staleSlots = changed;
    BUILD_SLOTS.forEach(renderTile);
    // The text on screen waits for Reload; the plan's staleness does not: an edit made in another editor is exactly the one
    // the plan tile has to own up to.
    notifyBuild();
  }

  // Coming back to the tab is when a file is most likely to have changed:
  // you went to your editor, changed instructions.md, and came back. No
  // polling -- a page that re-read three files every few seconds would be
  // doing it for nothing, all night, for the one time it matters.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshBuild(false);
  });
  window.addEventListener("focus", () => refreshBuild(false));

  BUILD_SLOTS.forEach((slot) => {
    const reload = el("reload-" + slotId(slot));
    if (reload) reload.addEventListener("click", applyPending);
  });

  // ---- "Change file": the file browser ---------------------
  //
  // Each tile's Change file opens the modal (filebrowser.js) on the kind
  // of file that step reads. What choosing does depends on the step:
  //
  //   01 Conventions  the house file is used WHERE IT IS --
  //                   `POST /api/build/sources/load`, a pointer for this
  //                   session, exactly as before.
  //   02, 03          a file from outside the open bundle is COPIED into it
  //                   as input.csv / instructions.md (the program
  //                   copies the input list into the
  //                   bundle and notifies the user that it has done so) --
  //                   `POST /api/bundle/adopt`. One already there is never
  //                   replaced without asking, in the modal: replace / keep
  //                   the bundle's / cancel. With no bundle open there is
  //                   nothing to copy into, and the file is used where it is.
  //   Watch's file    the same copy, as watch.json ("if we
  //                   change to a new file or create a new one, it goes
  //                   into the bundle"). watch.js calls `adoptAsking`
  //                   through `window.Atoo.adoptIntoBundle`, so the
  //                   question it asks is this one, word for word.

  const SLOT_DIALOG = {
    conventions: { kind: "md", title: "Open a house conventions file" },
    input_list: { kind: "csv", title: "Open an input list", file: "input.csv" },
    instructions: { kind: "md", title: "Open show instructions", file: "instructions.md" },
  };

  // Where a dialog for this slot opens: on the file the tile shows, with it
  // highlighted, if there is one; else the open bundle's folder; else
  // wherever this kind of dialog was last, or home (filebrowser.js).
  function slotStart(slot) {
    const source = buildSource(slot);
    if (source && source.state === "loaded" && source.path) return source.path;
    if (slot !== "conventions" && bundle) return bundle.directory;
    return workspace;
  }

  // Put a tile-changing answer on screen: the payload is `_build_payload`
  // (plus the copy's own keys), exactly what `GET /api/build/sources` sends.
  function absorbChoice(slot, data) {
    // The step shows the file just chosen. Any edit that was open on it
    // was discarded knowingly (`chooseSlotFile` asked first), so the step
    // is redrawn rather than left showing the old text over the new file.
    editingStep[slot] = false;
    if (slot === "input_list") setInputDirty(false);
    absorb(data);
    renderEditControls();
    activateStep(slot);
    showBundleMessage(data.message || "", false);
    // The copy's provenance -- which file it came from -- as an INFO in
    // the dock, where it stays while this bundle is open.
    if (data.finding) {
      addFindings([Object.assign({}, data.finding, {
        jumps: [{ label: STEP_LABEL[slot], mode: "build", target: "#tab-" + slotId(slot) }],
        _producer: "bundle-copy",
      })]);
    }
  }

  async function loadSlotPointer(slot, path, dialog) {
    const r = await fetch("/api/build/sources/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot: slot, path: path }),
    });
    const data = await r.json();
    if (!r.ok) { dialog.error(data.error || "couldn't load that file"); return false; }
    absorbChoice(slot, data);
    return true;
  }

  async function adoptIntoBundle(slot, path, replace) {
    const r = await fetch("/api/bundle/adopt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slot: slot, path: path, replace: !!replace,
        // FR-6.11: this writes into a bundle, so it names the one this page
        // shows; the server refuses (409, `stale`) if that is not the one
        // it has open.
        expected_bundle: bundle ? bundle.directory : null,
      }),
    });
    return { ok: r.ok, status: r.status, data: await r.json() };
  }

  // The file each copy-in slot lands as; must match webui._ADOPT_SLOT_FILES.
  const ADOPT_FILES = {
    input_list: "input.csv", instructions: "instructions.md", watch: "watch.json",
  };

  function aOrAn(name) {
    return /^[aeiou]/i.test(name || "") ? "an" : "a";
  }

  // Copy `result.path` into the open bundle as `slot`'s file, asking in the
  // dialog before replacing one that is there. `hooks.keep(path)` loads the
  // bundle's own file when the answer is "Keep the bundle's" (resolving
  // true once it has); `hooks.absorb(data)` puts a successful copy's
  // answer on screen. Resolves as `onChoose` does: true closes the dialog.
  async function adoptAsking(slot, result, dialog, hooks) {
    if (!(await checkServer())) return true;
    let answer = await adoptIntoBundle(slot, result.path, false);
    if (answer.status === 409 && answer.data.exists) {
      const there = answer.data.exists;
      const chosen = answer.data.chosen || {};
      const file = ADOPT_FILES[slot];
      const describe = (f) => (f.size !== null && f.size !== undefined ? f.size + " bytes" : "") +
        (f.mtime ? ", changed " + new Date(f.mtime * 1000).toLocaleString() : "");
      const choice = await dialog.ask(
        bundle.name + "/ already has " + aOrAn(file) + " " + file + " (" + describe(there) +
        "). Replace it with " + (chosen.display_path || result.path) + " (" + describe(chosen) +
        ")? The one it replaces is kept as backups/" + file + ".bak.",
        [
          { id: "replace", label: "Replace the bundle's " + file, primary: true },
          { id: "keep", label: "Keep the bundle's" },
          { id: "cancel", label: "Cancel" },
        ]
      );
      if (choice === "cancel") return false;   // back to the browser, to pick again
      if (choice === "keep") {
        const kept = await hooks.keep(there.path);
        if (kept) {
          showBundleMessage("Kept " + there.display_path + "; " +
            (chosen.display_path || result.path) + " was not copied.", false);
        }
        return kept;
      }
      if (!(await checkServer())) return true;
      answer = await adoptIntoBundle(slot, result.path, true);
    }
    if (answer.status === 409 && answer.data.stale) {
      markStale("bundle", answer.data.error);
      return true;
    }
    if (!answer.ok) { dialog.error(answer.data.error || "couldn't copy that file"); return false; }
    hooks.absorb(answer.data);
    return true;
  }

  async function chooseSlotFile(slot, result, dialog) {
    // Unsaved edits on this step (the editors) are the
    // operator's work: opening another file replaces what the step shows,
    // so say so before doing it.
    if (editingStep[slot]) {
      const go = await dialog.ask(
        STEP_LABEL[slot] + " has changes on this page that are not saved. Opening " +
        (result.name || result.path) + " puts that file on the step and throws them away " +
        "-- Cancel and Save them first if you want them.",
        [
          { id: "discard", label: "Open it and discard my changes", primary: true },
          { id: "cancel", label: "Cancel" },
        ]
      );
      if (go !== "discard") return false;
    }
    if (slot === "conventions" || !bundle) return loadSlotPointer(slot, result.path, dialog);
    return adoptAsking(slot, result, dialog, {
      keep: (path) => loadSlotPointer(slot, path, dialog),
      absorb: (data) => absorbChoice(slot, data),
    });
  }

  function openSlotDialog(slot) {
    const files = window.AtooFiles;
    const spec = SLOT_DIALOG[slot];
    if (!files || !spec) return;
    activateStep(slot);
    let note;
    if (slot === "conventions") {
      note = "The house file lives outside the show bundle and is used where it is -- " +
        "nothing is copied. For this session only; New file can make one your default.";
    } else if (bundle) {
      note = "A file from outside " + bundle.name + "/ is copied into it as " + spec.file +
        " -- the bundle keeps its own copy, and edits to the original will not reach it.";
    } else {
      note = "No show bundle is open, so this file is used where it is. Open or create a " +
        "bundle first to keep a copy with the show.";
    }
    files.open({
      mode: "open-file",
      kind: spec.kind,
      title: spec.title,
      note: note,
      start: slotStart(slot),
      confirmLabel: "Open",
      onChoose: (result, dialog) => chooseSlotFile(slot, result, dialog),
    });
  }

  BUILD_SLOTS.forEach((slot) => {
    const change = el("change-" + slotId(slot));
    if (change) {
      change.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openSlotDialog(slot);
      });
    }
  });

  // ---- "New file" (step 01) and "New instructions.md" (step 03) ----------
  // There was no way to introduce either file from
  // the page. Both create an EMPTY file (the templated new conventions and
  // instructions files are suggestions only: the template is the Example
  // beside each editor), and never over a
  // file that exists. They write files only; nothing here goes near a
  // console.
  //
  // Step 01's opens the file browser in its naming mode: pick
  // the folder (or make one with New folder), name the file, and tick the
  // one checkbox if it should become the default. The server's refusals
  // are the -- never over a file, `.md` only, a folder that exists --
  // and each is said inside the dialog. Step 03's needs no dialog: its
  // place is fixed, the open bundle's instructions.md.

  // The path the replace button would name as the default, after New file
  // found a different one already in ~/.atoo.config.
  let replaceDefaultPath = null;

  function configInfo() {
    return (build && build.config) || {};
  }

  function showConventionsCreated(text, previous, path) {
    const note = el("conv-created");
    const span = el("conv-created-text");
    const replace = el("conv-replace-default");
    if (!note || !span) return;
    span.textContent = text || "";
    note.hidden = !text;
    replaceDefaultPath = previous ? path : null;
    if (replace) {
      replace.hidden = !previous;
      replace.textContent = previous
        ? "Replace " + previous + " with this file as the default" : "Replace the default";
    }
  }

  // What ~/.atoo.config says today, said before anyone ticks the box.
  function defaultNote(info) {
    const where = info.display_path || "~/.atoo.config";
    return info.conventions_default
      ? where + " names " + info.conventions_default + " as your default now. Ticking this "
        + "does not replace it -- you will be asked separately."
      : info.exists
        ? where + " names no conventions default yet; ticking this adds one, and changes "
          + "nothing else in it."
        : "There is no " + where + " yet; ticking this creates it with just this default.";
  }

  function openNewConventionsDialog() {
    const files = window.AtooFiles;
    if (!files) return;
    activateStep("conventions");
    const info = configInfo();
    const suggestion = info.new_conventions_suggestion || "~/atoo-rules-house.md";
    const parts = files.splitPath(suggestion);
    files.open({
      mode: "save-file",
      kind: "md",
      title: "New house conventions file",
      note: "An empty file -- the Example beside the editor is there to copy from. It lives " +
        "outside the show bundle, and is never written over an existing file.",
      start: parts.folder || "~",
      name: parts.name,
      nameLabel: "File name (.md)",
      confirmLabel: "Create",
      // Unticked every time: writing to someone's config file is a choice
      // they make in this dialog, not one a previous visit made for them.
      check: {
        label: "Make it my default in " + (info.display_path || "~/.atoo.config"),
        note: defaultNote(info),
        checked: false,
      },
      onChoose: async (result, dialog) => {
        if (!(await checkServer())) return true;
        const r = await fetch("/api/build/conventions/new", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: result.path, make_default: !!result.checked }),
        });
        const data = await r.json();
        if (!r.ok) { dialog.error(data.error || "couldn't create that file"); return false; }
        absorb(data);
        activateStep("conventions");
        showBundleMessage("");
        const written = data.config_write || null;
        showConventionsCreated(
          data.message,
          written && written.status === "kept" ? written.previous : null,
          data.created && data.created.path
        );
        return true;
      },
    });
  }

  async function replaceDefault() {
    if (!replaceDefaultPath) return;
    try {
      const r = await fetch("/api/config/conventions-default", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: replaceDefaultPath, replace: true }),
      });
      const data = await r.json();
      if (!r.ok) {
        showConventionsCreated(data.error || "couldn't change the default", null, null);
        return;
      }
      absorb(data);
      showConventionsCreated(data.message, null, null);
    } catch (e) {
      showConventionsCreated(String(e), null, null);
    }
  }

  async function createInstructions() {
    showBundleMessage("");
    if (!(await checkServer())) return;
    try {
      const r = await fetch("/api/build/instructions/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // It writes into the bundle, so it names the one this page shows
        // (FR-6.11); a stale page is refused with a 409.
        body: JSON.stringify({ expected_bundle: bundle ? bundle.directory : null }),
      });
      const data = await r.json();
      if (!r.ok) {
        if (r.status === 409 && data.stale) { markStale("bundle", data.error); return; }
        showBundleMessage(data.error || "couldn't create instructions.md", true);
        return;
      }
      absorb(data);
      activateStep("instructions");
      showBundleMessage(data.message || "");
    } catch (e) {
      showBundleMessage(String(e), true);
    }
  }

  const newConventionsBtn = el("new-conventions");
  if (newConventionsBtn) {
    newConventionsBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openNewConventionsDialog();
    });
  }
  const replaceDefaultBtn = el("conv-replace-default");
  if (replaceDefaultBtn) replaceDefaultBtn.addEventListener("click", replaceDefault);
  ["new-instructions", "instr-create-btn"].forEach((id) => {
    const button = el(id);
    if (button) {
      button.addEventListener("click", (ev) => {
        ev.stopPropagation();
        createInstructions();
      });
    }
  });

  // ---- "View source" -----------------------------------------------------

  // Step 02 only: steps 01 and 03 ARE their source (one editor each,
  // with no sections view), so they have nothing to toggle.
  [
    ["input-source-toggle-btn", "input-source", "input-table-wrap"],
  ].forEach(([buttonId, preId, viewId]) => {
    const button = el(buttonId);
    const pre = el(preId);
    const view = el(viewId);
    if (!button || !pre || !view) return;
    button.addEventListener("click", () => {
      const showing = pre.hidden;
      pre.hidden = !showing;
      view.hidden = showing;
      button.textContent = showing ? "View table" : "View source";
    });
  });

  const houseToggle = el("house-conv-toggle-btn");
  if (houseToggle) {
    houseToggle.addEventListener("click", () => {
      const pre = el("house-conv-source");
      if (!pre) return;
      pre.hidden = !pre.hidden;
      houseToggle.textContent = pre.hidden ? "View house file" : "Hide house file";
    });
  }

  // ---- Editing: steps 01 and 03, step 02 -------
  //
  // These files are also edited in other editors, so this page is a second
  // editor of a file that is the user's, and it behaves like one:
  //
  //   * Steps 01 and 03 are one editor each over the whole file, headings
  //     and comments as written (there is no
  //     sections view); Save sends the editor's text and the server
  //     writes it in the file's own line ending. Step 02's Save sends only
  //     the rows that changed, spliced into the file
  //     (atoo/source_edit.py). A save with no change writes nothing.
  //   * Save carries the hash of the bytes the page read. If the file
  //     changed on disk since, the server refuses (409) and the page says
  //     so and offers Reload -- the other edit is never written over.
  //   * Save carries the bundle the page shows (FR-6.11), and every Save
  //     and Rebuild button goes off with the stale-page banner.
  //   * The HOUSE file (step 01) is edited the same way as step 03's
  //     instructions (it was once read-only until
  //     "Edit house style" was chosen). While it has unsaved
  //     changes, a warning names the blast radius: every show that names
  //     the file builds from it.
  //   * New file writes an EMPTY file. The example beside each editor is
  //     a suggestion: Insert puts it -- or the part
  //     of it selected -- at the cursor, and only Save writes it.
  //
  // Watch conditions are edited on the Watch page and nowhere else;
  // there is no watch editor here.

  const EDITOR = {
    conventions: {
      text: "conv-text", empty: "conv-empty", save: "conv-save-btn",
      cancel: "conv-cancel-btn", note: "conv-save-note",
      noteText: "conv-save-text", reload: "conv-save-reload",
      example: "conv-example", exampleText: "conv-example-text",
      insert: "conv-example-insert",
      placeholder: "This file is empty. Write your house style here, in plain English -- "
        + "or open Example below and insert it, whole or in part.",
    },
    instructions: {
      text: "instr-text", empty: "instr-empty", save: "instr-save-btn",
      cancel: "instr-cancel-btn", note: "instr-save-note",
      noteText: "instr-save-text", reload: "instr-save-reload",
      example: "instr-example", exampleText: "instr-example-text",
      insert: "instr-example-insert",
      placeholder: "This file is empty. Write only what differs for this show -- "
        + "or open Example below and insert it, whole or in part.",
    },
  };
  const INPUT_TYPES = ["Mic", "DI", "Instrument", "Line", "Wireless"];
  // input_list.CANONICAL_COLUMNS, in the order the table draws them.
  // `patch` was `socket` before the rename (a file may still be headed
  // that way; the server names the column `patch` in `values` either way,
  // and a Save writes it back under the file's own header).
  const INPUT_COLUMNS = ["order", "patch", "name", "category", "type", "model", "phantom", "preset", "notes"];
  const PATCH_COLUMNS = ["patch", "socket"];
  // What the server says the columns are (`source.columns`), else those.
  let inputColumns = INPUT_COLUMNS;
  // The order step 02's table DRAWS them in: the
  // patch last, just before the row's ✕. The data keeps its own column
  // names and order; only the table moves.
  function inputDisplayColumns() {
    const patch = inputColumns.filter((c) => PATCH_COLUMNS.indexOf(c) !== -1).slice(0, 1);
    return inputColumns.filter((c) => PATCH_COLUMNS.indexOf(c) === -1).concat(patch);
  }

  function bundleDirectory() {
    return bundle ? bundle.directory : null;
  }

  function showSaveNote(slot, text, kind, offerReload) {
    if (slot === "input_list") {
      // One editor, two views (step 02's table and step 04's Input
      // columns): what a Save did is said in both.
      [{ note: "input-save-note", noteText: "input-save-text", reload: "input-save-reload" },
       { note: "plan-input-save-note", noteText: "plan-input-save-text",
         reload: "plan-input-save-reload" }].forEach((ids) => showNoteIn(ids, text, kind, offerReload));
      return;
    }
    showNoteIn(EDITOR[slot], text, kind, offerReload);
  }

  function showNoteIn(ids, text, kind, offerReload) {
    const note = el(ids.note);
    const span = el(ids.noteText);
    const reload = el(ids.reload);
    if (!note || !span) return;
    span.textContent = text || "";
    note.hidden = !text;
    note.className = "save-note" + (kind ? " is-" + kind : "");
    if (reload) reload.hidden = !offerReload;
  }

  function canEdit(slot) {
    const source = buildSource(slot);
    // Nothing on the demo show is editable.
    return !!(source && source.state === "loaded") && !stale && !isDemoShow();
  }

  function renderEditControls() {
    Object.keys(EDITOR).forEach((slot) => {
      const ids = EDITOR[slot];
      const editing = editingStep[slot];
      // Save and Discard only once the editor differs from the file.
      [ids.save, ids.cancel].forEach((id) => {
        const node = el(id);
        if (node) node.hidden = !editing;
      });
      const save = el(ids.save);
      if (save) save.disabled = !!stale;
      const box = el(ids.text);
      if (box) box.readOnly = !canEdit(slot);
      const insert = el(ids.insert);
      if (insert) insert.disabled = !canEdit(slot);
    });
    // Step 01's own furniture: the badge and the warning are up for as
    // long as the house file has unsaved changes.
    const badge = el("conv-ro-badge");
    if (badge) {
      badge.textContent = "Editing house style";
      badge.className = "state is-warn";
      badge.hidden = !editingStep.conventions;
    }
    const warning = el("conv-edit-warning");
    if (warning) warning.hidden = !editingStep.conventions;
    const who = el("conv-edit-bundle");
    if (who) who.textContent = bundle ? bundle.name : "this show";
    const instrBadge = el("instr-edit-badge");
    if (instrBadge) instrBadge.hidden = !editingStep.instructions;
  }

  // ---- the one editor per step (steps 01 and 03) --------------------------

  // Draw a step's editor from the payload: the file's text, exactly as
  // read, in the box -- unless the box has unsaved changes, which a
  // re-read (window focus, another step's Save) must never throw away. A
  // file that changed underneath is still noticed: the tile goes Stale,
  // and Save says so.
  function renderTextEditor(slot, source, missingMessage) {
    const ids = EDITOR[slot];
    const box = el(ids.text);
    const empty = el(ids.empty);
    const loaded = !!(source && source.state === "loaded");
    if (box) {
      box.hidden = !loaded;
      box.placeholder = ids.placeholder;
      if (!editingStep[slot]) {
        box.value = loaded ? (source.text || "") : "";
        box.dataset.original = box.value;
      }
      box.rows = Math.min(40, Math.max(14, box.value.split("\n").length + 2));
    }
    if (empty) {
      empty.hidden = loaded;
      empty.textContent = loaded ? "" : missingMessage;
    }
    // The example: shown beside a file there is to insert it into, and
    // opened when that file is empty -- the moment it is most use. Never
    // written anywhere by the page on its own.
    const example = el(ids.example);
    const exampleText = el(ids.exampleText);
    const text = (build && build.examples && build.examples[slot]) || "";
    if (exampleText) exampleText.textContent = text;
    if (example) {
      example.hidden = !loaded || !text;
      if (loaded && box && !box.value) example.open = true;
    }
  }

  // Unsaved changes are whatever the box says that the file did not.
  function noteTextChange(slot) {
    const box = el(EDITOR[slot].text);
    const dirty = !!box && box.value !== box.dataset.original;
    if (dirty === editingStep[slot]) return;
    editingStep[slot] = dirty;
    if (dirty) showSaveNote(slot, "");
    renderEditControls();
  }

  // Discard: the box goes back to the file as the page last read it.
  function stopEditing(slot) {
    editingStep[slot] = false;
    showSaveNote(slot, "");
    if (slot === "conventions") renderConventions();
    else renderInstructions();
    renderEditControls();
  }

  // The part of the example selected on the page, if the selection is
  // inside it -- else "" (Insert then inserts the whole example).
  function exampleSelection(slot) {
    const pre = el(EDITOR[slot].exampleText);
    const sel = window.getSelection ? window.getSelection() : null;
    if (!pre || !sel || sel.isCollapsed || !sel.rangeCount) return "";
    if (!pre.contains(sel.anchorNode) || !pre.contains(sel.focusNode)) return "";
    return sel.toString();
  }

  // Insert the example (or the selected part of it) at the editor's
  // cursor, replacing whatever the editor has selected. It is then an
  // unsaved change like any typed one: Discard takes it back out, and
  // nothing reaches the file until Save.
  function insertExample(slot) {
    const ids = EDITOR[slot];
    const box = el(ids.text);
    const pre = el(ids.exampleText);
    if (!box || !pre || box.hidden || box.readOnly) return;
    const text = exampleSelection(slot) || pre.textContent || "";
    if (!text) return;
    const start = box.selectionStart == null ? box.value.length : box.selectionStart;
    const end = box.selectionEnd == null ? start : box.selectionEnd;
    box.setRangeText(text, start, end, "end");
    box.rows = Math.min(40, Math.max(14, box.value.split("\n").length + 2));
    box.focus();
    noteTextChange(slot);
  }

  // Where `quote` is in `text`, as [start, end], or null: exactly, then
  // allowing for what a model does to a quote -- surrounding quote marks
  // and an ellipsis, different whitespace or case, dropped `*`/`_`
  // emphasis (the tolerance `conventions_audit.normalise` checks with).
  function findQuote(text, quote) {
    let q = String(quote || "").trim()
      .replace(/^["'“‘]+|["'”’]+$/g, "")
      .replace(/^(\.\.\.|…)\s*|\s*(\.\.\.|…)$/g, "").trim();
    if (!q) return null;
    const at = text.indexOf(q);
    if (at !== -1) return [at, at + q.length];
    const words = q.split(/\s+/).map((w) => w.replace(/[*_`]/g, "")).filter(Boolean)
      .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (!words.length) return null;
    const match = new RegExp(words.join("[\\s*_`]+"), "i").exec(text);
    return match ? [match.index, match.index + match[0].length] : null;
  }

  // A finding's jump into this editor (setup.js, FR-6.2) carries the line
  // it quotes: select it, and scroll the box to it. A quote the file no
  // longer holds still lands on the editor -- the finding's own text says
  // what it quoted.
  function selectQuote(slot, quote) {
    const box = el(EDITOR[slot].text);
    if (!box || box.hidden) return;
    const range = findQuote(box.value, quote);
    if (!range) return;
    box.focus({ preventScroll: true });
    box.setSelectionRange(range[0], range[1]);
    const line = box.value.slice(0, range[0]).split("\n").length - 1;
    const height = parseFloat(getComputedStyle(box).lineHeight) || 16;
    box.scrollTop = Math.max(0, (line - 3) * height);
  }

  async function saveText(slot) {
    const source = buildSource(slot);
    const save = el(EDITOR[slot].save);
    const box = el(EDITOR[slot].text);
    if (!source || !save || !box) return;
    save.disabled = true;
    if (!(await checkServer())) {
      showSaveNote(slot, "Nothing was saved: this page is out of date -- see the banner. Copy "
        + "what you typed before reloading.", "error", false);
      return;
    }
    try {
      const r = await fetch("/api/build/sections/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slot: slot,
          expected_path: source.path,
          expected_sha256: source.sha256,
          expected_bundle: bundleDirectory(),
          // Step 01 is the house file: the warning naming every show it
          // builds is on screen whenever it has changes to save.
          house_confirmed: slot === "conventions" && editingStep.conventions,
          text: box.value,
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        if (data.stale === "bundle") markStale("bundle", data.error);
        showSaveNote(slot, data.error || "couldn't save", "error", data.stale === "file");
        save.disabled = !!stale;
        return;
      }
      editingStep[slot] = false;
      showBundleMessage("");
      absorb(data);
      renderEditControls();
      showSaveNote(slot, data.message || "Saved.", data.saved && data.saved.changed ? "ok" : "", false);
    } catch (e) {
      showSaveNote(slot, String(e), "error", false);
      save.disabled = !!stale;
    }
  }

  // Reload after a refused save: the file as it is on disk now, and the
  // editor's unsaved text dropped -- the note that offered it said so.
  async function reloadAfterConflict(slot) {
    editingStep[slot] = false;
    showSaveNote(slot, "");
    await refreshBuild(true);
    renderEditControls();
  }

  Object.keys(EDITOR).forEach((slot) => {
    const ids = EDITOR[slot];
    const box = el(ids.text);
    if (box) {
      box.addEventListener("input", () => noteTextChange(slot));
      box.addEventListener("atoo:jump", (ev) => {
        if (ev.detail && ev.detail.find) selectQuote(slot, ev.detail.find);
      });
    }
    const cancel = el(ids.cancel);
    if (cancel) cancel.addEventListener("click", () => stopEditing(slot));
    const save = el(ids.save);
    if (save) save.addEventListener("click", () => saveText(slot));
    const reload = el(ids.reload);
    if (reload) reload.addEventListener("click", () => reloadAfterConflict(slot));
    const insert = el(ids.insert);
    if (insert) {
      // Pressing the button must not clear the selection it is about to
      // insert, so it never takes the mouse-down.
      insert.addEventListener("mousedown", (ev) => ev.preventDefault());
      insert.addEventListener("click", () => insertExample(slot));
    }
  });

  // The Insert button says which it will do: the selected part of the
  // example, or all of it.
  document.addEventListener("selectionchange", () => {
    Object.keys(EDITOR).forEach((slot) => {
      const insert = el(EDITOR[slot].insert);
      if (insert) {
        insert.textContent = exampleSelection(slot) ? "Insert selected text" : "Insert whole example";
      }
    });
  });

  // ---- step 02's table ----------------------------------------------------

  function stringValues(row) {
    const out = {};
    Object.keys(row || {}).forEach((key) => {
      const value = row[key];
      out[key] = key === "phantom" && typeof value === "boolean"
        ? (value ? "TRUE" : "FALSE") : (value == null ? "" : String(value));
    });
    return out;
  }

  // What an input list's phantom cell says -- input_list.py's spellings.
  function phantomOn(raw) {
    const text = String(raw || "").trim().toLowerCase();
    if (["true", "1", "yes"].indexOf(text) !== -1) return true;
    if (["false", "0", "no"].indexOf(text) !== -1) return false;
    return null;
  }

  // Step 02's Notes cell: a small icon, filled when
  // the row has a note and hollow when not, with the note as its tooltip.
  // Clicking it opens #note-dialog. The note itself is still an <input>
  // with `data-col="notes"` -- hidden -- so collectRows, inputRowsNow,
  // setInputCell and Discard treat it exactly as they treat every other
  // cell: the popup is a bigger box for typing into the same place.
  const NOTE_ICON_EMPTY = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    + '<path d="M3.5 1.5h6l3 3v10h-9z" fill="none" stroke="currentColor" stroke-width="1.3" '
    + 'stroke-linejoin="round"/><path d="M9.5 1.5v3h3" fill="none" stroke="currentColor" '
    + 'stroke-width="1.3" stroke-linejoin="round"/></svg>';
  const NOTE_ICON_FILLED = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    + '<path d="M3.5 1.5h6l3 3v10h-9z" fill="currentColor" stroke="currentColor" stroke-width="1.3" '
    + 'stroke-linejoin="round"/><path d="M5.5 7.5h5M5.5 10h5M5.5 12.5h3" class="note-lines" '
    + 'stroke-width="1.2" stroke-linecap="round"/></svg>';

  function syncNoteButton(td) {
    const input = td && td.querySelector('[data-col="notes"]');
    const button = td && td.querySelector(".note-btn");
    if (!input || !button) return;
    const text = input.value || "";
    const has = text.trim() !== "";
    button.classList.toggle("has-note", has);
    button.innerHTML = has ? NOTE_ICON_FILLED : NOTE_ICON_EMPTY;
    button.title = has ? text : "Add a note";
    button.setAttribute("aria-label", has ? "Edit note: " + text : "Add a note");
  }

  function notesCell(value, isNew) {
    const td = document.createElement("td");
    td.className = "col-notes";
    const input = document.createElement("input");
    input.type = "hidden";
    input.dataset.col = "notes";
    input.dataset.original = isNew ? "" : value;
    input.value = value || "";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-icon note-btn";
    button.addEventListener("click", () => openNoteDialog(td));
    td.appendChild(input);
    td.appendChild(button);
    syncNoteButton(td);
    return td;
  }

  let noteTarget = null;  // the Notes <td> #note-dialog is editing
  // Where focus goes back to when it closes: the icon that opened it --
  // step 02's own, or step 04's (`inputEditor.editNote`).
  let noteReturn = null;

  function openNoteDialog(td, returnTo) {
    const dialog = el("note-dialog");
    const box = el("note-dialog-text");
    const input = td.querySelector('[data-col="notes"]');
    if (!dialog || !box || !input) return;
    noteTarget = td;
    noteReturn = returnTo || null;
    const tr = td.closest("tr");
    const name = tr && tr.querySelector('[data-col="name"]');
    el("note-dialog-title").textContent = "Notes" + (name && name.value ? " — " + name.value : "");
    box.value = input.value;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
  }

  function closeNoteDialog(keep) {
    const dialog = el("note-dialog");
    const td = noteTarget;
    noteTarget = null;
    if (dialog && dialog.open) dialog.close();
    if (!td) return;
    const input = td.querySelector('[data-col="notes"]');
    const box = el("note-dialog-text");
    if (keep && input && box && box.value !== input.value) {
      input.value = box.value;
      input.dataset.touched = "1";
      syncNoteButton(td);
      setInputDirty(true);
      markInputProblems();
      notifyInput("input-list");
    }
    const back = noteReturn;
    noteReturn = null;
    // Step 04 redraws its row on the edit, so its icon is found again by
    // the row it belongs to.
    const again = back && !document.contains(back) && back.dataset && back.dataset.noteKey
      ? document.querySelector('[data-note-key="' + back.dataset.noteKey + '"]') : null;
    const button = (back && document.contains(back)) ? back : (again || td.querySelector(".note-btn"));
    if (button && document.contains(button) && button.offsetParent !== null) button.focus();
  }

  // Step 04's Notes: the same icon, the same popup, the same hidden cell.
  function editNote(key, returnTo) {
    const tr = inputRowElement(key);
    const td = tr && tr.querySelector("td.col-notes");
    if (!td) return false;
    openNoteDialog(td, returnTo);
    return true;
  }

  function noteIcon(text) {
    return String(text || "").trim() ? NOTE_ICON_FILLED : NOTE_ICON_EMPTY;
  }

  (function wireNoteDialog() {
    const dialog = el("note-dialog");
    if (!dialog) return;
    // Step 04 opens it too, while step 02's panel (where shell.html
    // writes it) is hidden -- and a dialog inside a display:none panel
    // never shows. So it lives at the top of the page.
    document.body.appendChild(dialog);
    el("note-dialog-ok").addEventListener("click", () => closeNoteDialog(true));
    el("note-dialog-cancel").addEventListener("click", () => closeNoteDialog(false));
    // Esc: the browser's own `cancel` on a modal <dialog>.
    dialog.addEventListener("cancel", (ev) => { ev.preventDefault(); closeNoteDialog(false); });
    // Enter is a new line (the textarea's own); Ctrl/Cmd+Enter is OK.
    el("note-dialog-text").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault();
        closeNoteDialog(true);
      }
    });
    // A click on the backdrop (outside the box) is Cancel.
    dialog.addEventListener("click", (ev) => { if (ev.target === dialog) closeNoteDialog(false); });
  })();

  // Step 02's Patch cell: a filled patch is a badge,
  // like step 04's patch chips; an empty one is a quiet "+ add". Clicking
  // either edits it in place -- Enter, ✓ or leaving the box commits, Esc
  // cancels. A commit is checked by GET /api/build/validate-patch (the
  // input list's own parser and the console model's range, never a second
  // grammar here) and a value that cannot be a socket is refused inline,
  // with the reason, and not written into the row. As with Notes, the
  // value itself lives in a hidden <input data-col="patch"> -- so
  // collectRows, inputRowsNow, setInputCell and Discard see an ordinary
  // cell -- and a valid edit marks the row dirty like any other edit.
  function syncPatchBadge(td) {
    const input = td && td.querySelector("input[data-col]");
    const badge = td && td.querySelector(".patch-badge");
    if (!input || !badge) return;
    const value = (input.value || "").trim();
    badge.classList.toggle("is-empty", !value);
    badge.textContent = value || "+ add";
    badge.title = value
      ? "Patched to " + value + " -- click to change it"
      : "No patch: the build chooses a socket, and says so. Click to set one, e.g. LCL 3 or AES50-A 12.";
    badge.setAttribute("aria-label", value ? "Patch " + value + ", edit" : "Add a patch");
  }

  // The console model the check uses: step 04's choice, which is seeded
  // from the plan on screen. None chosen checks the address space.
  function patchModel() {
    const select = el("run-console-model");
    return select ? select.value : "";
  }

  // A patch being checked when Save is pressed (the Save click is what
  // blurred the box): Save waits for the verdict, so the edit is in it.
  let pendingPatchChecks = [];

  function patchCell(column, value, isNew) {
    const td = document.createElement("td");
    td.className = "col-sock";
    const input = document.createElement("input");
    input.type = "hidden";
    input.dataset.col = column;
    input.dataset.original = isNew ? "" : value;
    input.value = value || "";
    const badge = document.createElement("button");
    badge.type = "button";
    badge.className = "patch-badge";
    const editor = document.createElement("span");
    editor.className = "patch-editor";
    editor.hidden = true;
    const box = document.createElement("input");
    box.type = "text";
    box.className = "socket-input patch-edit-input";
    box.setAttribute("aria-label", "patch");
    box.title = "Where this input is patched: the socket it is plugged into, e.g. "
      + "LCL 3 or AES50-A 12. Leave it empty and the build chooses one, and says so.";
    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = "btn-icon patch-edit-ok";
    ok.textContent = "✓";
    ok.title = "Keep this patch (Enter)";
    ok.setAttribute("aria-label", "Keep this patch");
    const error = document.createElement("span");
    error.className = "patch-edit-error";
    error.setAttribute("role", "alert");
    error.hidden = true;
    editor.appendChild(box);
    editor.appendChild(ok);
    td.appendChild(input);
    td.appendChild(badge);
    td.appendChild(editor);
    td.appendChild(error);
    syncPatchBadge(td);

    let committing = false;
    function open() {
      box.value = input.value;
      error.hidden = true;
      error.textContent = "";
      badge.hidden = true;
      editor.hidden = false;
      box.focus();
      box.select();
    }
    function close(focusBadge) {
      editor.hidden = true;
      badge.hidden = false;
      error.hidden = true;
      box.classList.remove("is-invalid");
      if (focusBadge) badge.focus();
    }
    async function commit(focusBadge) {
      if (committing || editor.hidden) return;
      const typed = box.value.trim();
      if (typed === (input.value || "").trim()) { close(focusBadge); return; }
      committing = true;
      let settle;
      pendingPatchChecks.push(new Promise((resolve) => { settle = resolve; }));
      let verdict = null;
      try {
        const r = await fetch("/api/build/validate-patch?value=" + encodeURIComponent(typed)
          + "&model=" + encodeURIComponent(patchModel()));
        verdict = await r.json();
        if (!r.ok) verdict = { ok: false, error: verdict.error || "could not check this patch" };
      } catch (e) {
        verdict = { ok: false, error: "could not check this patch: " + e };
      }
      committing = false;
      settle();
      if (!verdict.ok) {
        // Refused: the row keeps what it had; the box keeps what was typed.
        error.textContent = verdict.error || "not a socket";
        error.hidden = false;
        box.classList.add("is-invalid");
        if (focusBadge) box.focus();
        return;
      }
      const spelled = verdict.patch == null ? typed : verdict.patch;
      if (spelled !== input.value) {
        input.value = spelled;
        input.dataset.touched = "1";
        setInputDirty(true);
        markInputProblems();
        notifyInput("input-list");
      }
      syncPatchBadge(td);
      close(focusBadge);
    }
    badge.addEventListener("click", open);
    // ✓ must not lose to the box's own blur, which would commit first.
    ok.addEventListener("mousedown", (ev) => ev.preventDefault());
    ok.addEventListener("click", () => commit(true));
    box.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); commit(true); }
      else if (ev.key === "Escape") { ev.preventDefault(); close(true); }
    });
    box.addEventListener("input", () => { error.hidden = true; box.classList.remove("is-invalid"); });
    box.addEventListener("blur", () => {
      // Leaving the box commits -- unless it is showing a refusal, which
      // stays up until it is fixed or Esc'd.
      if (!box.classList.contains("is-invalid")) commit(false);
    });
    return td;
  }

  // Step 02's Order cell: the band's number, and a Skip box beside it.
  // Ticking Skip writes `-` into the cell (and remembers the number it
  // replaced, to put back on untick); typing `-` ticks it. The row is
  // dimmed while it is skipped. The box has no data-col: the cell's
  // <input data-col="order"> is the value Save sends, like every cell.
  function orderCell(value, isNew) {
    const td = document.createElement("td");
    td.className = "col-order";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "order-input";
    input.dataset.col = "order";
    input.dataset.original = isNew ? "" : value;
    input.value = value || "";
    input.inputMode = "numeric";
    input.setAttribute("aria-label", "Band order number");
    input.title = "The band's own number for this input (their IEM split or stage-box "
      + "order). It does not set the desk channel. '-' skips the row.";
    const label = document.createElement("label");
    label.className = "skip-toggle";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "skip-box";
    box.setAttribute("aria-label", "Skip this row in the next build");
    label.title = "Skip: the row stays in input.csv and the next build leaves it out";
    label.appendChild(box);
    label.appendChild(document.createTextNode("Skip"));
    td.appendChild(input);
    td.appendChild(label);
    const changed = () => {
      input.dataset.touched = "1";
      syncSkip(td.closest("tr"));
      setInputDirty(true);
      markInputProblems();
      notifyInput("input-list");
    };
    box.addEventListener("change", () => {
      if (box.checked) {
        if (input.value.trim() !== SKIP_MARK) input.dataset.number = input.value.trim();
        input.value = SKIP_MARK;
      } else {
        input.value = input.dataset.number || "";
      }
      changed();
    });
    input.addEventListener("input", changed);
    return td;
  }

  // A row's skip state, drawn: the box ticked and the row dimmed.
  function syncSkip(tr) {
    if (!tr) return;
    const input = tr.querySelector('[data-col="order"]');
    const skipped = !!input && input.value.trim() === SKIP_MARK;
    const box = tr.querySelector(".skip-box");
    if (box) box.checked = skipped;
    tr.classList.toggle("row-skipped", skipped);
  }

  // The columns the loader refuses a row without (input_list.py).
  const REQUIRED_INPUT_COLUMNS = ["name", "category", "type"];

  function inputCell(column, value, isNew) {
    if (column === "order") return orderCell(value, isNew);
    if (column === "notes") return notesCell(value, isNew);
    if (PATCH_COLUMNS.indexOf(column) !== -1) return patchCell(column, value, isNew);
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.dataset.col = column;
    input.dataset.original = isNew ? "" : value;
    if (column === "phantom") {
      td.className = "col-phantom";
      input.type = "checkbox";
      input.checked = phantomOn(value) === true;
      input.title = phantomOn(value) === null && !isNew && value
        ? "The file says " + JSON.stringify(value) + ", which is not TRUE or FALSE -- tick or untick to fix it"
        : "Phantom power (48V)";
      input.setAttribute("aria-label", "Phantom power");
    } else {
      input.type = "text";
      input.value = value || "";
      input.setAttribute("aria-label", column);
      if (REQUIRED_INPUT_COLUMNS.indexOf(column) !== -1) {
        // A new row says which cells it needs before Save,
        // not one finding per Save afterwards. markInputProblems outlines
        // the empty ones.
        input.placeholder = "required";
        input.setAttribute("aria-required", "true");
      }
      if (column === "type") {
        input.setAttribute("list", "input-type-options");
      } else if (column === "category") {
        input.setAttribute("list", "input-category-options");
      } else if (column === "preset") {
        td.className = "col-preset";
        input.setAttribute("list", "input-preset-options");
        input.placeholder = "none";
        input.title = "A preset from the preset library. It wins over the conventions and "
          + "instructions, as a stated patch does. Leave it empty and the conventions decide.";
      }
    }
    input.addEventListener(column === "phantom" ? "change" : "input", () => {
      input.dataset.touched = "1";
      setInputDirty(true);
      markInputProblems();
      notifyInput("input-list");
    });
    td.appendChild(input);
    return td;
  }

  // A cell is an input
  // only when it can be edited and saved. On a read-only show (the Demo)
  // step 02's table is text: no inputs, no drag handle, no move, insert
  // or remove buttons. Each cell still carries its value in a hidden
  // <input data-col> -- what markInputProblems, inputRowsNow and
  // collectRows read -- so nothing downstream needs a second path.
  function inputReadOnly() {
    return isDemoShow();
  }

  function readOnlyInputCell(column, value) {
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.type = "hidden";
    input.dataset.col = column;
    input.dataset.original = value;
    input.value = value;
    td.appendChild(input);
    const text = String(value || "").trim();
    const show = (node) => td.appendChild(node);
    const prop = (word) => {
      const tag = document.createElement("span");
      tag.className = "prop";
      tag.textContent = word;
      return tag;
    };
    if (column === "order") {
      td.className = "col-order";
      if (text === SKIP_MARK) {
        const tag = prop("Skip");
        tag.title = "Skip: the row stays in input.csv and the next build leaves it out";
        show(tag);
      } else {
        show(document.createTextNode(text));
      }
    } else if (column === "phantom") {
      td.className = "col-phantom";
      const on = phantomOn(value);
      input.checked = on === true;
      if (on === true) show(prop("48V"));
      else if (on === null && text) show(document.createTextNode(text));
    } else if (PATCH_COLUMNS.indexOf(column) !== -1) {
      td.className = "col-sock";
      if (text) {
        const chip = document.createElement("span");
        chip.className = "readout";
        chip.textContent = text;
        show(chip);
      }
    } else if (column === "notes") {
      td.className = "col-notes col-notes-text";
      td.title = text;
      show(document.createTextNode(text));
    } else {
      if (column === "preset") td.className = "col-preset";
      else if (column === "name") td.className = "col-name";
      show(document.createTextNode(text));
    }
    return td;
  }

  function readOnlyInputRow(line, values) {
    const tr = document.createElement("tr");
    tr.dataset.line = line == null ? "" : String(line);
    tr.dataset.key = String(++inputKeySeq);
    inputDisplayColumns().forEach((column) => {
      const v = values || {};
      const value = column === "patch" && v.patch == null ? v.socket : v[column];
      tr.appendChild(readOnlyInputCell(column, value == null ? "" : String(value)));
    });
    syncSkip(tr);
    return tr;
  }

  function inputRow(line, values, isNew) {
    if (!isNew && inputReadOnly()) return readOnlyInputRow(line, values);
    const tr = document.createElement("tr");
    tr.dataset.line = line == null ? "" : String(line);
    // A handle that survives an edit to every cell: step 04 addresses a
    // row by it (`inputEditor.set(key, ...)`).
    tr.dataset.key = String(++inputKeySeq);
    tr.appendChild(moveCell(tr));
    inputDisplayColumns().forEach((column) => {
      const v = values || {};
      // A payload from before the rename names the patch `socket`.
      const value = column === "patch" && v.patch == null ? v.socket : v[column];
      tr.appendChild(inputCell(column, value || "", !!isNew));
    });
    const td = document.createElement("td");
    td.className = "col-remove";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn-icon";
    remove.title = "Remove row";
    remove.setAttribute("aria-label", "Remove row");
    remove.textContent = "✕";
    remove.addEventListener("click", () => {
      tr.remove();
      setInputDirty(true);
      markInputProblems();
      notifyInput("input-list");
    });
    // Insert: a blank row directly BELOW this one.
    // "+ Add row" under the table still adds one at the end.
    const insert = document.createElement("button");
    insert.type = "button";
    insert.className = "btn-icon insert-row-btn";
    insert.title = "Insert a blank row below this one";
    insert.setAttribute("aria-label", "Insert a row below");
    insert.textContent = "+";
    insert.addEventListener("click", () => insertInputRow(tr));
    td.appendChild(insert);
    td.appendChild(remove);
    tr.appendChild(td);
    syncSkip(tr);
    return tr;
  }

  // A blank row after `after` (or at the end, when null), focused on its
  // Name, unsaved until Save -- as "+ Add row" has always made one.
  function insertInputRow(after) {
    const body = el("input-rows");
    if (!body) return null;
    const tr = inputRow(null, {}, true);
    if (after && after.parentNode === body) body.insertBefore(tr, after.nextSibling);
    else body.appendChild(tr);
    el("input-table-wrap").hidden = false;
    setInputDirty(true);
    markInputProblems();
    notifyInput("input-list");
    const first = tr.querySelector('[data-col="name"]');
    if (first) first.focus();
    return tr;
  }

  // Reordering: drag a row by its handle, or move
  // it with the up/down buttons, or Alt+Up / Alt+Down from anywhere in
  // the row -- so it is never mouse-only. The order on screen is the
  // order Save writes (`collectRows` sends the rows as they stand); the
  // channel numbers are still the conventions' to compute.
  function moveCell(tr) {
    const td = document.createElement("td");
    td.className = "col-move";
    const handle = document.createElement("span");
    handle.className = "drag-handle";
    handle.textContent = "\u283F";
    handle.title = "Drag to move this row (or Alt+Up / Alt+Down)";
    handle.setAttribute("aria-hidden", "true");
    // The row is draggable only while the handle is held, so text in its
    // cells can still be selected with the mouse.
    handle.addEventListener("mousedown", () => { tr.draggable = true; });
    handle.addEventListener("mouseup", () => { tr.draggable = false; });
    const up = document.createElement("button");
    up.type = "button";
    up.className = "btn-icon move-btn move-up";
    up.textContent = "\u25B2";
    up.title = "Move this row up (Alt+Up)";
    up.setAttribute("aria-label", "Move row up");
    up.addEventListener("click", () => moveInputRow(tr, -1, up));
    const down = document.createElement("button");
    down.type = "button";
    down.className = "btn-icon move-btn move-down";
    down.textContent = "\u25BC";
    down.title = "Move this row down (Alt+Down)";
    down.setAttribute("aria-label", "Move row down");
    down.addEventListener("click", () => moveInputRow(tr, 1, down));
    const stack = document.createElement("span");
    stack.className = "move-stack";
    stack.appendChild(up);
    stack.appendChild(down);
    td.appendChild(handle);
    td.appendChild(stack);
    return td;
  }

  function inputRowsMoved() {
    setInputDirty(true);
    markInputProblems();
    notifyInput("input-list");
  }

  // One place up (-1) or down (+1). `focus` is put back after the move,
  // since moving a node can drop the focus it held.
  function moveInputRow(tr, step, focus) {
    const body = tr && tr.parentNode;
    if (!body) return false;
    const target = step < 0 ? tr.previousElementSibling : tr.nextElementSibling;
    if (!target) return false;
    if (step < 0) body.insertBefore(tr, target);
    else body.insertBefore(tr, target.nextSibling);
    if (focus && document.contains(focus)) focus.focus();
    inputRowsMoved();
    return true;
  }

  (function wireRowMoves() {
    const body = el("input-rows");
    if (!body) return;
    body.addEventListener("keydown", (ev) => {
      if (!ev.altKey || (ev.key !== "ArrowUp" && ev.key !== "ArrowDown")) return;
      const tr = ev.target.closest && ev.target.closest("#input-rows tr");
      if (!tr) return;
      ev.preventDefault();
      moveInputRow(tr, ev.key === "ArrowUp" ? -1 : 1, ev.target);
    });
    // The dragged row moves as the pointer crosses the middle of another,
    // so what is seen while dragging is where it lands.
    let dragged = null;
    let startIndex = -1;
    const indexOf = (tr) => Array.prototype.indexOf.call(body.children, tr);
    body.addEventListener("dragstart", (ev) => {
      const tr = ev.target.closest && ev.target.closest("#input-rows tr");
      if (!tr || !tr.draggable) return;
      dragged = tr;
      startIndex = indexOf(tr);
      tr.classList.add("row-dragging");
      if (ev.dataTransfer) {
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", tr.dataset.key || "");
      }
    });
    body.addEventListener("dragover", (ev) => {
      if (!dragged) return;
      ev.preventDefault();
      const tr = ev.target.closest && ev.target.closest("#input-rows tr");
      if (!tr || tr === dragged) return;
      const box = tr.getBoundingClientRect();
      const below = ev.clientY > box.top + box.height / 2;
      body.insertBefore(dragged, below ? tr.nextSibling : tr);
    });
    body.addEventListener("drop", (ev) => { if (dragged) ev.preventDefault(); });
    body.addEventListener("dragend", () => {
      if (!dragged) return;
      const tr = dragged;
      dragged = null;
      tr.classList.remove("row-dragging");
      tr.draggable = false;
      if (indexOf(tr) !== startIndex) inputRowsMoved();
    });
  })();

  function fillInputOptions(records) {
    const types = INPUT_TYPES.slice();
    const categories = [];
    (records || []).forEach((record) => {
      const v = record.values || {};
      if (v.type && types.indexOf(v.type) === -1) types.push(v.type);
      if (v.category && categories.indexOf(v.category) === -1) categories.push(v.category);
    });
    [["input-type-options", types], ["input-category-options", categories]].forEach(([id, list]) => {
      const node = el(id);
      if (!node) return;
      node.textContent = "";
      list.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        node.appendChild(option);
      });
    });
  }

  // Step 02's Preset chooser: the preset library's
  // names, from GET /api/build/presets -- `ui --presets`, else the
  // [presets] default, the library a build uses. A <datalist>, not a
  // <select>, so a name is still free text: with no library configured,
  // and for a preset the library has not got yet (verify says
  // preset.unknown, a warning, and the strip is built without it).
  let presetLibrary = null;
  async function loadPresetOptions() {
    let state = presetLibrary;
    if (!state) {
      try {
        const r = await fetch("/api/build/presets");
        state = r.ok ? await r.json() : null;
      } catch (e) {
        state = null;
      }
      if (!state) return;
      presetLibrary = state;
    }
    const node = el("input-preset-options");
    if (node) {
      node.textContent = "";
      (state.names || []).forEach((name) => {
        const option = document.createElement("option");
        option.value = name;
        node.appendChild(option);
      });
    }
    const note = el("input-preset-note");
    if (!note) return;
    let text = "";
    if (!state.configured) {
      text = "No preset library is configured, so the Preset column has nothing to offer; "
        + "type a name and it is saved as written. Start `atoo ui --presets DIR`, or set "
        + "[presets] default in ~/.atoo.config, to choose from one.";
    } else if (state.error && !(state.names || []).length) {
      text = "The preset library at " + state.library + " could not be read (" + state.error
        + "); the Preset column takes a name as free text.";
    } else if (state.error) {
      text = "Preset library " + state.library + ": " + state.error + ".";
    }
    note.textContent = text;
    note.hidden = !text;
  }

  // Marked on the row, and each empty required cell outlined; the loader's own verdict still arrives as a finding after Save
  // (input-list.invalid). Save asks once before writing a list these
  // marks say will not load -- see saveInputList.
  function markInputProblems() {
    const seen = {};
    document.querySelectorAll("#input-rows tr").forEach((tr) => {
      const value = (col) => ((tr.querySelector('[data-col="' + col + '"]') || {}).value || "").trim();
      const problems = [];
      REQUIRED_INPUT_COLUMNS.forEach((col) => {
        const cell = tr.querySelector('[data-col="' + col + '"]');
        const empty = !value(col);
        if (empty) problems.push(col + " is required");
        if (cell) {
          cell.classList.toggle("is-required-empty", empty);
          cell.setAttribute("aria-invalid", empty ? "true" : "false");
        }
      });
      const order = value("order");
      const skipped = order === SKIP_MARK;
      if (order && !skipped && !/^[0-9]+$/.test(order)) {
        problems.push("order is the band's input number, '-' to skip, or blank");
      } else if (/^0+$/.test(order)) {
        problems.push("order starts at 1");
      }
      const name = value("name");
      // A skipped row may share an included row's name (input_list.py).
      if (name && !skipped) {
        if (seen[name]) problems.push("another row is also named " + JSON.stringify(name));
        seen[name] = true;
      }
      tr.classList.toggle("row-invalid", problems.length > 0);
      tr.title = problems.join("; ");
    });
  }

  // What the rows on screen would fail the loader on, one entry per row,
  // numbered as the loader numbers them (the header is row 1, and Save
  // writes the rows in screen order).
  function inputProblemSummary() {
    const out = [];
    document.querySelectorAll("#input-rows tr").forEach((tr, i) => {
      if (!tr.classList.contains("row-invalid")) return;
      const name = ((tr.querySelector('[data-col="name"]') || {}).value || "").trim();
      out.push("row " + (i + 2) + (name ? " (" + name + ")" : "") + ": " + tr.title);
    });
    return out;
  }

  // The problems Save last warned about. Pressing Save again with the same
  // problems saves anyway: a half-typed list is still the operator's to
  // keep.
  let unloadableWarned = "";

  function setInputDirty(dirty) {
    editingStep.input_list = !!dirty;
    if (!dirty) unloadableWarned = "";
    // Step 02's controls and step 04's: one unsaved state, shown twice.
    ["input-dirty-badge", "plan-input-dirty-badge"].forEach((id) => {
      const badge = el(id);
      if (badge) badge.hidden = !dirty;
    });
    // A Save/Discard pair with nothing to save is hidden, not locked: it
    // comes up with the Unsaved changes tag, as steps 01 and 03's do.
    // Step 04's only where its Input
    // cells are the editable list.
    const planTable = el("plan-channels-table");
    const planEditable = !!(planTable && planTable.dataset.editable === "1");
    ["input-save-btn", "plan-input-save-btn"].forEach((id) => {
      const save = el(id);
      if (save) save.disabled = !dirty || !!stale;
    });
    ["input-discard-btn", "plan-input-discard-btn"].forEach((id) => {
      const discard = el(id);
      if (discard) discard.disabled = !dirty;
    });
    // A read-only show keeps the pair up, locked, with the
    // reason beside it: the table says it cannot be edited, in words.
    const locked = inputReadOnly();
    ["input-save-btn", "input-discard-btn"].forEach((id) => {
      const node = el(id);
      if (node) node.hidden = !inputListLoaded || (!dirty && !locked);
    });
    const lockReason = el("input-lock-reason");
    if (lockReason) lockReason.hidden = !inputListLoaded || !locked;
    ["plan-input-save-btn", "plan-input-discard-btn"].forEach((id) => {
      const node = el(id);
      if (node) node.hidden = !dirty || !planEditable;
    });
  }

  function notifyInput(origin) {
    inputListeners.forEach((fn) => {
      try { fn(origin); } catch (e) { /* one listener must not stop the rest */ }
    });
  }

  function inputRowElement(key) {
    return document.querySelector('#input-rows tr[data-key="' + String(key) + '"]');
  }

  // Step 02's rows as they stand on screen, unsaved edits included --
  // what step 04 draws its Input cells from.
  function inputRowsNow() {
    return Array.prototype.map.call(document.querySelectorAll("#input-rows tr"), (tr) => {
      const values = {};
      const original = {};
      tr.querySelectorAll("[data-col]").forEach((input) => {
        const column = input.dataset.col;
        values[column] = column === "phantom" ? input.checked : input.value;
        original[column] = input.dataset.original || "";
      });
      return {
        key: tr.dataset.key,
        line: tr.dataset.line === "" ? null : Number(tr.dataset.line),
        values: values,
        original: original,
        problems: tr.title || "",
      };
    });
  }

  // An edit made in step 04 is made HERE, on step 02's own input -- so it
  // is the same edit, collected by the same `collectRows`, saved by the
  // same `saveInputList`, and step 02 shows it before anyone saves.
  function setInputCell(key, column, value) {
    const tr = inputRowElement(key);
    const input = tr && tr.querySelector('[data-col="' + column + '"]');
    if (!input) return false;
    if (column === "phantom") input.checked = !!value;
    else input.value = value == null ? "" : String(value);
    if (column === "notes") syncNoteButton(input.closest("td"));
    if (PATCH_COLUMNS.indexOf(column) !== -1) syncPatchBadge(input.closest("td"));
    if (column === "order") syncSkip(tr);
    input.dataset.touched = "1";
    setInputDirty(true);
    markInputProblems();
    notifyInput("plan");
    return true;
  }

  function removeInputRow(key) {
    const button = inputRowElement(key) && inputRowElement(key).querySelector(".col-remove button");
    if (button) button.click();
  }

  function discardInputList() {
    editingStep.input_list = false;
    showSaveNote("input_list", "");
    renderInputList();
  }

  // The table as Save sends it: every row in order; an existing row names
  // its line and only the cells that changed, a new row sends them all.
  function collectRows() {
    return Array.prototype.map.call(document.querySelectorAll("#input-rows tr"), (tr) => {
      const isNew = tr.dataset.line === "";
      const values = {};
      tr.querySelectorAll("[data-col]").forEach((input) => {
        const column = input.dataset.col;
        if (column === "phantom") {
          const was = phantomOn(input.dataset.original);
          if (isNew || (input.dataset.touched && input.checked !== was)) {
            values.phantom = input.checked ? "TRUE" : "FALSE";
          }
        } else if (isNew || input.value !== input.dataset.original) {
          values[column] = input.value;
        }
      });
      return { line: isNew ? null : Number(tr.dataset.line), values: values };
    });
  }

  async function saveInputList() {
    const source = buildSource("input_list");
    const save = el("input-save-btn");
    if (!source || !save) return;
    if (pendingPatchChecks.length) {
      const waiting = pendingPatchChecks;
      pendingPatchChecks = [];
      await Promise.all(waiting);
    }
    // A list the marks say will not load is not written on
    // the first press. The note says what each row lacks and the first
    // empty required cell takes the cursor; a second Save with the same
    // problems writes it as it stands.
    markInputProblems();
    const problems = inputProblemSummary();
    const summary = problems.join("; ");
    if (problems.length && summary !== unloadableWarned) {
      unloadableWarned = summary;
      const shown = problems.length > 3
        ? problems.slice(0, 3).join("; ") + "; and " + (problems.length - 3) + " more row(s)"
        : summary;
      showSaveNote("input_list", "Not saved yet: the input list would not load as it stands -- "
        + shown + ". Fill in the outlined cells, or press Save again to save it anyway.",
        "warn", false);
      const first = Array.prototype.find.call(
        document.querySelectorAll("#input-rows .is-required-empty"), (c) => c.offsetParent !== null);
      if (first) first.focus();
      return;
    }
    unloadableWarned = "";
    save.disabled = true;
    if (!(await checkServer())) {
      showSaveNote("input_list", "Nothing was saved: this page is out of date -- see the "
        + "banner. Copy what you typed before reloading.", "error", false);
      return;
    }
    try {
      const r = await fetch("/api/build/input-list/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_path: source.path,
          expected_sha256: source.sha256,
          expected_bundle: bundleDirectory(),
          rows: collectRows(),
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        if (data.stale === "bundle") markStale("bundle", data.error);
        showSaveNote("input_list", data.error || "couldn't save", "error", data.stale === "file");
        save.disabled = !!stale;
        return;
      }
      editingStep.input_list = false;
      showBundleMessage("");
      absorb(data);
      const loads = !!(data.input_list && data.input_list.rows);
      showSaveNote("input_list", data.message || "Saved.",
        data.saved && data.saved.changed ? (loads ? "ok" : "warn") : "", false);
    } catch (e) {
      showSaveNote("input_list", String(e), "error", false);
      save.disabled = !!stale;
    }
  }

  const addRowBtn = el("input-add-row");
  if (addRowBtn) {
    addRowBtn.addEventListener("click", () => insertInputRow(null));
  }
  const inputSaveBtn = el("input-save-btn");
  if (inputSaveBtn) inputSaveBtn.addEventListener("click", saveInputList);
  const inputDiscardBtn = el("input-discard-btn");
  if (inputDiscardBtn) inputDiscardBtn.addEventListener("click", discardInputList);
  const inputReload = el("input-save-reload");
  if (inputReload) inputReload.addEventListener("click", () => reloadAfterConflict("input_list"));
  // Step 04's Save / Discard / Reload beside its table are these same
  // three, not a second path to input.csv.
  const planInputSave = el("plan-input-save-btn");
  if (planInputSave) planInputSave.addEventListener("click", saveInputList);
  const planInputDiscard = el("plan-input-discard-btn");
  if (planInputDiscard) planInputDiscard.addEventListener("click", discardInputList);
  const planInputReload = el("plan-input-save-reload");
  if (planInputReload) planInputReload.addEventListener("click", () => reloadAfterConflict("input_list"));

  // The stale-page banner went up: nothing on this page may save now. The
  // CSS already dims and unpoints these; `disabled` is the second lock.
  staleListeners.push(() => {
    Object.keys(EDITOR).forEach((slot) => {
      const save = el(EDITOR[slot].save);
      if (save) save.disabled = true;
      const box = el(EDITOR[slot].text);
      if (box) box.readOnly = true;
      const insert = el(EDITOR[slot].insert);
      if (insert) insert.disabled = true;
    });
    ["input-save-btn", "input-add-row", "plan-input-save-btn"].forEach((id) => {
      const node = el(id);
      if (node) node.disabled = true;
    });
  });

  // ---- the step-to-step walk H designs the pipeline around ---------------
  [
    ["next-to-input-list", "input_list"],
    ["next-to-instructions", "instructions"],
    ["next-to-plan", "plan"],
  ].forEach(([buttonId, step]) => {
    const button = el(buttonId);
    if (button) button.addEventListener("click", () => activateStep(step));
  });

  // A different show is a different input list and a different
  // instructions.md, so everything Build is holding is re-read from the
  // server rather than patched -- including the two tile overrides, which
  // the server drops on the same event.
  bundleListeners.push(() => {
    // The New file report was about the last show's step 01; opening a
    // bundle drops the file it pointed at, so the report goes with it.
    showConventionsCreated("", null, null);
    // What was copied into the LAST bundle is that bundle's story.
    setFindings(findings.filter((finding) => finding._producer !== "bundle-copy"));
    refreshBuild(true);
  });

  // ---- first paint -----------------------------------------------------
  renderBundle();
  renderConsole();
  setFindings(startup.findings || []);
  renderBuild();
  activateStep("conventions");
  activateMode(modeFromHash());

  // ---- the contract later phases code against --------------------------
  window.Atoo = {
    activateMode: activateMode,
    // The segmented control's behaviour (see wireSeg): Apply mode uses it.
    wireSeg: wireSeg,
    currentMode: () => currentMode,
    // The findings dock. `list` is atoo.diagnostics.Diagnostic
    // dicts, each optionally carrying a `jumps` list (see above).
    setFindings: setFindings,
    addFindings: addFindings,
    clearFindings: () => setFindings([]),
    findings: () => findings.slice(),
    // What the dock shows, one object per row (a finding two
    // passes published is shown once) -- for counting what is visible.
    shownFindings: shownFindings,
    // True for a finding the dock folds under Build details rather than
    // Choices (Apply's pre-flight line counts by those folds).
    isBuildDetail: (f) => !!f && f.severity === "info" && BUILD_DETAILS.has(f.code),
    // Open the dock (step 04's and Apply's "in Findings" link).
    revealDock: revealDock,
    // A jump link's own handler (`{mode, target}`), for a page's in-text
    // links: step 04's "Changed since the last build" list.
    jumpTo: jumpTo,
    // Fired with the dock's list whenever it is redrawn; and the dock's
    // own findings (objects from `findings()`) scrolled to and flashed.
    onFindingsChange: (fn) => { if (typeof fn === "function") findingsListeners.push(fn); },
    showFindings: showFindings,
    // The open show bundle, exactly as GET /api/bundle answers, or null.
    // `onBundleChange` fires when the operator opens a different one --
    // the signal a mode needs to throw away whatever it had loaded.
    bundle: () => bundle,
    // The [workspace] default folder, or "" -- where the file
    // browser starts while no bundle is open.
    workspace: () => workspace,
    onBundleChange: (fn) => { if (typeof fn === "function") bundleListeners.push(fn); },
    // Called with the mode's name each time the page switches INTO a
    // different mode (nav click, fragment change, a jump link).
    onModeChange: (fn) => { if (typeof fn === "function") modeListeners.push(fn); },
    // The ONE console, as the server last sent it -- resolved at startup
    // or set in the bar since. The shell never writes to a desk, and Ping
    // is the only contact it makes; changing the address is done only in
    // the bar, through `POST /api/console`.
    console: () => Object.assign({}, consoleDefaults),
    consoleLabel: consoleLabel,
    consoleProvenance: consoleProvenance,
    // Fired with the new console after an edit in the bar.
    onConsoleChange: (fn) => { if (typeof fn === "function") consoleListeners.push(fn); },
    // Fired with `/api/ping`'s answer after a desk replied.
    onPing: (fn) => { if (typeof fn === "function") pingListeners.push(fn); },
    // apply.js sets a reason while a write runs, and "" when it ends: the
    // Change button is disabled meanwhile. The server refuses the edit
    // regardless (409) -- this is the courtesy, that is the guard.
    setConsoleLock: (reason) => {
      consoleLock = reason || "";
      if (consoleLock) closeConsoleEdit();
      renderConsole();
    },
    ping: runPing,
    // Copy a file chosen in the file browser into the open bundle, asking
    // before replacing one that is there -- Build's own flow, for Watch's
    // watch.json. See `adoptAsking`.
    adoptIntoBundle: adoptAsking,
    // The bundle bar's message line, under the bar.
    showBundleMessage: showBundleMessage,
    // A popup by id: `data-popup` buttons do this themselves.
    openPopup: openPopup,
    // Steps 01-03's findings, about the three source files, put back in
    // the dock from the last read: setup.js empties the dock when a build
    // starts and calls this when it ends.
    publishBuildFindings: publishBuildFindings,
    // The stale-page banner (see above). `isStale()` is true once the
    // server behind the page restarted or opened another bundle;
    // `checkServer()` asks now and resolves true while the page is current
    // -- every write awaits it first; `markStale` is for a mode that
    // learns it from a 409 (`stale: "bundle"`); `onStale` fires once.
    isStale: () => !!stale,
    checkServer: checkServer,
    markStale: (message) => markStale("bundle", message || "The server refused a write from this page as out of date."),
    onStale: (fn) => { if (typeof fn === "function") staleListeners.push(fn); },
    // Build's three source files, as `GET /api/build/sources` last
    // answered. `planFreshness()` is its `plan_freshness` --
    // is the bundle's plan.json still what these files would build --
    // including a re-read not yet put on screen, because a file edited
    // in another program makes the plan stale before anyone presses
    // Reload. `onBuildChange` fires with the payload on every re-read;
    // `refreshBuild()` re-reads now (setup.js, after a build lands).
    buildSources: () => buildPending || build,
    planFreshness: () => ((buildPending || build) || {}).plan_freshness || null,
    stalePlanWhat: stalePlanWhat,
    onBuildChange: (fn) => { if (typeof fn === "function") buildListeners.push(fn); },
    refreshBuild: () => refreshBuild(false),
    // Step 04's build wrote a new plan.json: setup.js calls `planBuilt()`,
    // and each `onPlanBuilt` listener re-reads what it held about the old
    // one (see `planBuiltListeners`).
    onPlanBuilt: (fn) => { if (typeof fn === "function") planBuiltListeners.push(fn); },
    planBuilt: () => planBuiltListeners.forEach((fn) => {
      try { fn(); } catch (e) { /* one listener must not stop the rest */ }
    }),
    activateStep: activateStep,
    // Step 02's input-list editor, for step 04's Input columns: the rows
    // as they stand (unsaved edits included), an edit made on step 02's
    // own cell, and step 02's own Save and Discard. `available()` is
    // whether there is an editable input.csv in this bundle at all.
    inputEditor: {
      available: () => canEdit("input_list") && !!el("input-rows"),
      rows: inputRowsNow,
      set: setInputCell,
      remove: removeInputRow,
      // Step 04's Notes icon: `noteIcon(text)` is step 02's own svg,
      // filled or hollow, and `editNote(key, button)` opens step 02's own
      // #note-dialog on that row's Notes cell -- one popup, one save path.
      noteIcon: noteIcon,
      editNote: editNote,
      save: saveInputList,
      discard: discardInputList,
      dirty: () => !!editingStep.input_list,
      onChange: (fn) => { if (typeof fn === "function") inputListeners.push(fn); },
    },
  };
  // ---- pop-up help -------------------------------------------
  //
  // Build's blocks of instructions are not in the layout any more: each is
  // a `.help-pop` -- a "?" button and the same text in a `.help-popover`
  // it opens. Delegated from the document, so help drawn later (setup.js's
  // plan table) works with no wiring of its own. One open at a time; the
  // button toggles it, Escape closes it and puts focus back on the
  // button, and a click anywhere else closes it. The popover is
  // position: fixed, placed from the button's rectangle, because the
  // tiles row and the step panels both clip what overflows them.

  let openHelp = null;

  function closeHelp(refocus) {
    if (!openHelp) return;
    const { button, pop } = openHelp;
    openHelp = null;
    pop.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (refocus) button.focus();
  }

  function placeHelp(button, pop) {
    const r = button.getBoundingClientRect();
    const margin = 8;
    const width = Math.min(340, window.innerWidth - 2 * margin);
    pop.style.width = width + "px";
    let left = r.left + r.width / 2 - width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));
    pop.style.left = left + "px";
    const below = r.bottom + 6;
    const height = pop.offsetHeight;
    const top = below + height > window.innerHeight - margin && r.top - 6 - height > margin
      ? r.top - 6 - height : below;
    pop.style.top = top + "px";
  }

  function openHelpFor(button) {
    const pop = el(button.getAttribute("aria-controls"));
    if (!pop) return;
    closeHelp(false);
    pop.hidden = false;
    placeHelp(button, pop);
    button.setAttribute("aria-expanded", "true");
    openHelp = { button: button, pop: pop, hover: false };
  }

  document.addEventListener("click", (ev) => {
    const button = ev.target && ev.target.closest ? ev.target.closest(".help-btn") : null;
    if (button) {
      // A "?" inside a Build tile is not a click on the tile.
      ev.stopPropagation();
      if (openHelp && openHelp.button === button && openHelp.hover) openHelp.hover = false;
      else if (openHelp && openHelp.button === button) closeHelp(false);
      else openHelpFor(button);
      return;
    }
    if (openHelp && !openHelp.pop.contains(ev.target)) closeHelp(false);
  }, true);
  // A "?" marked `data-hover-open` also opens on hover (a pointer resting
  // on it), and closes when the pointer leaves unless it was clicked open.
  document.addEventListener("mouseover", (ev) => {
    const button = ev.target && ev.target.closest ? ev.target.closest(".help-btn[data-hover-open]") : null;
    if (!button || (openHelp && openHelp.button === button)) return;
    openHelpFor(button);
    openHelp.hover = true;
  });
  document.addEventListener("mouseout", (ev) => {
    const button = ev.target && ev.target.closest ? ev.target.closest(".help-btn[data-hover-open]") : null;
    if (button && openHelp && openHelp.button === button && openHelp.hover) closeHelp(false);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && openHelp) {
      ev.preventDefault();
      closeHelp(true);
    }
  });
  window.addEventListener("resize", () => closeHelp(false));
  window.addEventListener("scroll", (ev) => {
    if (openHelp && !openHelp.pop.contains(ev.target)) closeHelp(false);
  }, true);

  // First check straight away: a tab restored by the browser after the
  // server restarted must not wait three seconds to say so.
  checkServer();
})();
