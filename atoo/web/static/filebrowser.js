/* The file browser: one modal, used by every "which file?" on the page
 * (a real modal file browser for
 * selecting existing files, or creating a new show directory or a new
 * file).
 *
 * A page cannot see the disk, so each folder is asked of the server,
 * which runs on this same laptop: `GET /api/fs/list` (names, types, sizes
 * and times -- never a file's contents) and `POST /api/fs/mkdir` for New
 * folder. Both answer this machine's own browser only (webui's
 * `_local_only`).
 *
 * Four modes, one dialog:
 *
 *   open-file      pick an existing file (Change file on steps 01-04,
 *                  and on Watch's watch-conditions file)
 *   open-folder    pick an existing folder (the bundle bar's Change...)
 *   create-folder  name a new folder (the bundle bar's New show...)
 *   save-file      name a new file (step 01's New file)
 *
 * The dialog chooses; the CALLER acts. `open(options)` takes an
 * `onChoose(result, dialog)` that runs while the modal is still up, so a
 * refusal from the server (a file already there, a bundle that has its
 * own input.csv) is said inside the modal, next to the thing that caused
 * it, and can be answered there -- `dialog.error(text)` and
 * `dialog.ask(text, buttons)`. It resolves true to close, false to stay.
 *
 * The path field is the fast path, kept on purpose: paste a folder and
 * press Enter to go there, paste a file and press Enter to choose it.
 *
 * Coded against `window.Atoo` (shell.js) for the stale-page banner:
 * the modal will not open on a page that is out of date, and closes if
 * the page goes out of date while it is up. Every write a caller makes
 * from it awaits `Atoo.checkServer()` first.
 */
(() => {
  "use strict";

  const el = (id) => document.getElementById(id);
  const SP = window.Atoo || null;

  const modal = el("fb-modal");
  if (!modal) return;
  const dialogBox = modal.querySelector(".fb-dialog");
  const titleEl = el("fb-title");
  const noteEl = el("fb-note");
  const pathInput = el("fb-path");
  const crumbs = el("fb-crumbs");
  const list = el("fb-list");
  const emptyEl = el("fb-empty");
  const countsEl = el("fb-counts");
  const hiddenBox = el("fb-hidden");
  const allBox = el("fb-all");
  const allRow = el("fb-all-row");
  const newFolderBtn = el("fb-newfolder-btn");
  const newFolderRow = el("fb-newfolder");
  const newFolderName = el("fb-newfolder-name");
  const nameRow = el("fb-name-row");
  const nameLabel = el("fb-name-label");
  const nameInput = el("fb-name");
  const checkRow = el("fb-check-row");
  const checkBox = el("fb-check");
  const checkLabel = el("fb-check-label");
  const checkNote = el("fb-check-note");
  const askBox = el("fb-ask");
  const askText = el("fb-ask-text");
  const askButtons = el("fb-ask-buttons");
  const errorEl = el("fb-error");
  const selectionEl = el("fb-selection");
  const confirmBtn = el("fb-confirm");

  // Sticky: the file chooser uses the
  // location in the file system last used. The folder the last file or
  // folder was CHOSEN from is where every dialog opens next -- whichever
  // button opened it, across reloads and server restarts. Kept in this
  // browser's storage, a per-viewer convenience: an unavailable storage
  // (a private window) only means the dialog opens where the button says.
  const STICKY_KEY = "atoo.fileChooser.lastFolder";
  function stickyFolder() {
    try { return window.localStorage.getItem(STICKY_KEY) || ""; } catch (e) { return ""; }
  }
  function rememberFolder(path) {
    if (!path) return;
    try { window.localStorage.setItem(STICKY_KEY, path); } catch (e) { /* not kept */ }
  }

  let opts = null;          // the options of the dialog that is up, or null
  let listing = null;       // the last good `GET /api/fs/list` answer
  let failedParent = null;  // after a failed listing: where Up goes
  let highlighted = -1;     // index into listing.entries
  let busy = false;
  let resolveOpen = null;
  let askResolve = null;
  let returnFocus = null;
  let requestSeq = 0;

  function fmtSize(bytes) {
    if (bytes === null || bytes === undefined) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function fmtTime(mtime) {
    if (!mtime) return "";
    const d = new Date(mtime * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " +
      pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function sep() { return (listing && listing.sep) || "/"; }

  // A name typed into the dialog, as a path. An absolute one (or one from
  // home) is taken as it is -- the paste-a-whole-path fast path -- and
  // anything else lands in the folder on screen.
  function joinPath(folder, name) {
    if (!name) return folder;
    if (name.charAt(0) === "/" || name.charAt(0) === "~" || /^[A-Za-z]:[\\/]/.test(name)) return name;
    if (!folder) return name;
    const s = sep();
    return folder.charAt(folder.length - 1) === s ? folder + name : folder + s + name;
  }

  function splitPath(path) {
    const s = sep();
    const text = String(path || "").replace(/[\\/]+$/, "");
    const at = Math.max(text.lastIndexOf("/"), text.lastIndexOf(s));
    if (at < 0) return { folder: "", name: text };
    return { folder: at === 0 ? text.charAt(0) : text.slice(0, at), name: text.slice(at + 1) };
  }

  function showError(text) {
    errorEl.textContent = text || "";
    errorEl.hidden = !text;
  }

  // `busy`: a choice is being acted on. `loading`: a folder is being
  // listed -- the primary button waits for it, because "the folder on
  // screen" is what it acts on, and mid-navigation that is two folders.
  // An Enter pressed meanwhile is kept and acted on when the listing lands.
  let loading = false;
  let confirmQueued = false;

  function setBusy(on) {
    busy = !!on;
    modal.classList.toggle("is-busy", busy);
    confirmBtn.disabled = busy || loading;
  }

  function setLoading(on) {
    loading = !!on;
    confirmBtn.disabled = busy || loading;
    if (!loading && confirmQueued) {
      confirmQueued = false;
      confirm();
    }
  }

  function kindForRequest() {
    if (!opts) return "any";
    if (allBox.checked && opts.kind !== "folders") return "any";
    return opts.kind || "any";
  }

  function entryMatches(entry) {
    if (!opts) return false;
    if (entry.type === "dir") return true;
    if (entry.type !== "file") return false;
    return opts.mode === "open-file" || opts.mode === "save-file";
  }

  // ---- drawing a folder ---------------------------------------------------

  function renderCrumbs(path) {
    crumbs.textContent = "";
    if (!path) return;
    const s = sep();
    const parts = path.split(s);
    let acc = "";
    parts.forEach((part, i) => {
      if (i === 0) {
        acc = part === "" ? s : part;
      } else {
        if (!part) return;
        acc = acc.charAt(acc.length - 1) === s ? acc + part : acc + s + part;
      }
      const target = acc;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "fb-crumb";
      b.textContent = i === 0 ? (part === "" ? s : part) : part;
      b.title = target;
      b.addEventListener("click", () => load(target));
      if (i > 0) {
        const gap = document.createElement("span");
        gap.className = "fb-crumb-sep";
        gap.textContent = "›";
        gap.setAttribute("aria-hidden", "true");
        crumbs.appendChild(gap);
      }
      crumbs.appendChild(b);
    });
  }

  function entryRow(entry, index) {
    const li = document.createElement("li");
    li.className = "fb-row fb-" + entry.type;
    li.setAttribute("role", "option");
    li.id = "fb-row-" + index;
    li.dataset.index = String(index);
    if (entry.type === "broken" || (entry.type === "file" && !entryMatches(entry))) {
      li.classList.add("is-disabled");
      li.setAttribute("aria-disabled", "true");
    }

    const icon = document.createElement("span");
    icon.className = "fb-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = entry.type === "dir" ? "▸" : entry.type === "broken" ? "×" : "·";
    li.appendChild(icon);

    const name = document.createElement("span");
    name.className = "fb-name";
    name.textContent = entry.name + (entry.type === "dir" ? "/" : "");
    li.appendChild(name);

    // Always present, so every row has the same five grid cells.
    const tags = document.createElement("span");
    tags.className = "fb-tags";
    li.appendChild(tags);
    if (entry.symlink) {
      const link = document.createElement("span");
      link.className = "fb-tag";
      link.textContent = entry.type === "broken" ? "broken link" : "link";
      link.title = entry.target ? "→ " + entry.target : "points at nothing that exists";
      tags.appendChild(link);
    }
    if (entry.bundle) {
      const tag = document.createElement("span");
      tag.className = "fb-tag fb-tag-bundle";
      tag.textContent = "show bundle";
      tag.title = "Already holds input.csv, instructions.md or plan.json";
      tags.appendChild(tag);
    }

    const size = document.createElement("span");
    size.className = "fb-size";
    size.textContent = entry.type === "file" ? fmtSize(entry.size) : "";
    li.appendChild(size);

    const time = document.createElement("span");
    time.className = "fb-time";
    time.textContent = fmtTime(entry.mtime);
    li.appendChild(time);

    li.addEventListener("click", () => highlight(index));
    li.addEventListener("dblclick", () => activate(index));
    return li;
  }

  function renderListing() {
    list.textContent = "";
    const entries = listing ? listing.entries : [];
    entries.forEach((entry, i) => list.appendChild(entryRow(entry, i)));
    if (!entries.length) {
      const nothingAtAll = listing && !listing.other_files && !listing.hidden_count;
      emptyEl.textContent = nothingAtAll ? "This folder is empty."
        : opts && opts.kind === "folders" ? "No folders here."
          : listing && listing.other_files && !allBox.checked
            ? "Nothing here that this dialog opens -- tick Show all files to see the rest."
            : "Nothing here but hidden files -- tick Show hidden to see them.";
      emptyEl.hidden = false;
    } else {
      emptyEl.hidden = true;
    }
    const bits = [];
    if (listing && listing.other_files) {
      bits.push(listing.other_files + " other file" + (listing.other_files === 1 ? "" : "s") +
        (opts && opts.kind === "folders" ? "" : " not shown"));
    }
    if (listing && listing.hidden_count) {
      bits.push(listing.hidden_count + " hidden");
    }
    if (listing && listing.truncated) bits.push("list cut short -- type a path to go further");
    countsEl.textContent = bits.join(" · ");
    renderSelection();
  }

  function highlight(index, scroll) {
    const entries = listing ? listing.entries : [];
    if (index < 0 || index >= entries.length) index = -1;
    highlighted = index;
    Array.prototype.forEach.call(list.children, (li, i) => {
      const on = i === index;
      li.classList.toggle("is-highlighted", on);
      li.setAttribute("aria-selected", String(on));
    });
    if (index >= 0) {
      list.setAttribute("aria-activedescendant", "fb-row-" + index);
      if (scroll !== false && list.children[index] && list.children[index].scrollIntoView) {
        list.children[index].scrollIntoView({ block: "nearest" });
      }
      // In the two naming modes, picking a file puts its name in the box
      // -- the quickest way to name a new file after an old one.
      const entry = entries[index];
      if (opts && opts.mode === "save-file" && entry && entry.type === "file") {
        nameInput.value = entry.name;
      }
    } else {
      list.removeAttribute("aria-activedescendant");
    }
    renderSelection();
  }

  function highlightedEntry() {
    return listing && highlighted >= 0 ? listing.entries[highlighted] : null;
  }

  // The primary button says exactly what it will do -- "Open touringband/"
  // rather than "Open" -- because in a folder chooser "the folder I am in"
  // and "the folder I have highlighted" are both reasonable readings.
  function renderSelection() {
    if (!opts) return;
    const entry = highlightedEntry();
    const here = listing ? listing.display_path : "";
    let label = opts.confirmLabel || "Open";
    let line = "";
    if (opts.mode === "open-folder") {
      if (entry && entry.type === "dir") {
        label = (opts.confirmLabel || "Open") + " " + entry.name + "/";
        line = "Double-click or Enter opens the folder to look inside.";
      } else if (listing) {
        label = (opts.confirmLabel || "Open") + " this folder";
        line = here;
      }
    } else if (opts.mode === "open-file") {
      if (entry && entry.type === "file" && entryMatches(entry)) {
        line = entry.name + " · " + fmtSize(entry.size) + " · " + fmtTime(entry.mtime);
      } else if (entry && entry.type === "dir") {
        label = "Open folder";
      } else {
        line = "Pick a file, or type a path above.";
      }
    } else {
      const name = (nameInput.value || "").trim();
      line = name ? joinPath(here, name) : "Type a name below.";
    }
    confirmBtn.textContent = label;
    selectionEl.textContent = line;
  }

  async function load(path, extra) {
    if (!opts) return false;
    const seq = ++requestSeq;
    const typedAtStart = pathInput.value;
    const params = new URLSearchParams();
    if (path) params.set("path", path);
    params.set("kind", kindForRequest());
    if (hiddenBox.checked) params.set("hidden", "true");
    if (extra && extra.base) params.set("base", extra.base);
    showError("");
    setLoading(true);
    let data;
    let ok = false;
    try {
      const r = await fetch("/api/fs/list?" + params.toString(), { cache: "no-store" });
      data = await r.json();
      ok = r.ok;
    } catch (e) {
      data = { error: "could not reach the Atoo server" };
    }
    if (seq !== requestSeq || !opts) return null;   // superseded by a newer request: not a failure
    // Settled once this function has drawn what it got (see `finally`
    // below): the queued Enter must act on THIS folder, not the last.
    try {
      return drawListing(data, ok, extra, typedAtStart);
    } finally {
      setLoading(false);
    }
  }

  function drawListing(data, ok, extra, typedAtStart) {
    if (!ok) {
      // Said where the listing would be, with the way out beside it: Up
      // goes to the folder above the one that failed.
      failedParent = data.parent || (listing && listing.path) || null;
      list.textContent = "";
      emptyEl.textContent = data.error || "couldn't list that folder";
      emptyEl.hidden = false;
      emptyEl.classList.add("is-error");
      countsEl.textContent = "";
      highlighted = -1;
      // Nothing on screen to act on: the primary button must not quietly
      // use the folder shown before the one that failed.
      listing = null;
      renderCrumbs(failedParent || "");
      renderSelection();
      return false;
    }
    emptyEl.classList.remove("is-error");
    failedParent = null;
    listing = data;
    // Unless someone typed into the box while this was in flight: a slow
    // answer must not overwrite a path being typed or pasted.
    // The box is also left alone while it has focus, unless this listing is
    // the one it asked for (Enter or Go): someone is in it.
    if (pathInput.value === typedAtStart &&
        ((extra && extra.fromPath) || document.activeElement !== pathInput)) {
      pathInput.value = data.path;
    }
    renderCrumbs(data.path);
    renderListing();
    const want = (extra && extra.select) || data.selected;
    const index = want ? data.entries.findIndex((e) => e.name === want) : -1;
    highlight(index);
    return data;
  }

  function goUp() {
    const target = failedParent || (listing && listing.parent);
    if (target) load(target);
  }

  // ---- choosing ------------------------------------------------------------

  async function choose(result) {
    if (!opts || busy) return;
    showError("");
    if (SP && SP.isStale && SP.isStale()) { close(null); return; }
    const full = Object.assign({ checked: !!checkBox.checked, listing: listing }, result);
    // The folder on screen when something was chosen: for a file, its
    // folder; for a show folder, the folder that holds the shows.
    const chosenFrom = listing && listing.path;
    if (!opts.onChoose) { rememberFolder(chosenFrom); close(full); return; }
    setBusy(true);
    let done = false;
    try {
      done = await opts.onChoose(full, api);
    } catch (e) {
      showError(String(e));
      done = false;
    } finally {
      setBusy(false);
    }
    if (done && opts) { rememberFolder(chosenFrom); close(full); }
  }

  function activate(index) {
    const entry = listing && listing.entries[index];
    if (!entry || !opts) return;
    if (entry.type === "dir") { load(entry.path); return; }
    if (entry.type === "file" && entryMatches(entry)) {
      if (opts.mode === "open-file") choose({ path: entry.path, name: entry.name });
      else if (opts.mode === "save-file") { nameInput.value = entry.name; nameInput.focus(); renderSelection(); }
    }
  }

  function confirm() {
    if (!opts || busy) return;
    if (loading) { confirmQueued = true; return; }
    const entry = highlightedEntry();
    const here = listing ? listing.path : null;
    if (opts.mode === "open-file") {
      if (entry && entry.type === "dir") { load(entry.path); return; }
      if (entry && entry.type === "file" && entryMatches(entry)) {
        choose({ path: entry.path, name: entry.name });
        return;
      }
      showError("Pick a file first -- or type its path in the box at the top and press Enter.");
      return;
    }
    if (opts.mode === "open-folder") {
      if (entry && entry.type === "dir") { choose({ path: entry.path, name: entry.name }); return; }
      if (here) choose({ path: here, name: splitPath(here).name });
      return;
    }
    // create-folder / save-file: the name box.
    const name = (nameInput.value || "").trim();
    if (!name) {
      showError(opts.mode === "create-folder" ? "Give the new show's folder a name."
        : "Give the new file a name.");
      nameInput.focus();
      return;
    }
    if (!here && name.charAt(0) !== "/" && name.charAt(0) !== "~") {
      showError("Open a folder to put it in first.");
      return;
    }
    const path = joinPath(here, name);
    const existing = listing && listing.entries.find((e) => e.name === name);
    choose({ path: path, name: name, exists: existing || null });
  }

  // Enter in the path box: go there. The box already naming the folder on
  // screen means "this one", so paste-Enter-Enter opens a folder, and a
  // pasted FILE path is chosen on the first Enter.
  async function submitPath() {
    const typed = (pathInput.value || "").trim();
    if (!typed) return;
    if (listing && typed.replace(/[\\/]+$/, "") === listing.path.replace(/[\\/]+$/, "")) {
      if (opts.mode === "open-folder") { highlight(-1); confirm(); }
      else if (opts.mode !== "open-file") nameInput.focus();
      return;
    }
    const data = await load(typed, { base: listing ? listing.path : null, fromPath: true });
    if (data && data.selected && opts) {
      const entry = data.entries.find((e) => e.name === data.selected);
      const path = joinPath(data.path, data.selected);
      if (opts.mode === "open-file") {
        // Typed by hand, so the filter does not second-guess it: the
        // server reads whatever it is and says what it found.
        choose({ path: path, name: data.selected });
      } else if (opts.mode === "save-file") {
        nameInput.value = data.selected;
        renderSelection();
        nameInput.focus();
      } else if (!entry) {
        highlight(-1);
      }
    }
  }

  // ---- New folder -----------------------------------------------------------

  function openNewFolder() {
    newFolderRow.hidden = false;
    newFolderName.value = "";
    newFolderName.focus();
  }

  function closeNewFolder() {
    newFolderRow.hidden = true;
  }

  async function createFolder() {
    const name = (newFolderName.value || "").trim();
    if (!name) { showError("Give the new folder a name."); newFolderName.focus(); return; }
    if (!listing) { showError("Open a folder to put it in first."); return; }
    if (busy) return;
    if (SP && SP.checkServer && !(await SP.checkServer())) { close(null); return; }
    setBusy(true);
    let data;
    let ok = false;
    try {
      const r = await fetch("/api/fs/mkdir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: name, base: listing.path }),
      });
      data = await r.json();
      ok = r.ok;
    } catch (e) {
      data = { error: "could not reach the Atoo server" };
    } finally {
      setBusy(false);
    }
    if (!ok) { showError(data.error || "couldn't create that folder"); return; }
    closeNewFolder();
    await load(data.created);
    showError("");
    if (selectionEl) selectionEl.textContent = data.message || "";
  }

  // ---- asking, inside the modal --------------------------------------------

  function ask(text, buttons) {
    return new Promise((resolve) => {
      askResolve = resolve;
      askText.textContent = text || "";
      askButtons.textContent = "";
      (buttons || []).forEach((spec, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn btn-sm " + (spec.primary ? "btn-primary" : "btn-secondary");
        b.textContent = spec.label;
        b.dataset.answer = spec.id;
        b.addEventListener("click", () => finishAsk(spec.id));
        askButtons.appendChild(b);
        if (i === 0) setTimeout(() => b.focus(), 0);
      });
      askBox.hidden = false;
      modal.classList.add("is-asking");
    });
  }

  function finishAsk(answer) {
    if (!askResolve) return;
    const resolve = askResolve;
    askResolve = null;
    askBox.hidden = true;
    modal.classList.remove("is-asking");
    resolve(answer);
  }

  const api = {
    error: showError,
    ask: ask,
    reload: () => (listing ? load(listing.path) : null),
    listing: () => listing,
  };

  // ---- opening and closing ---------------------------------------------------

  function close(result) {
    if (!opts) return;
    if (askResolve) finishAsk("cancel");
    opts = null;
    modal.hidden = true;
    document.body.classList.remove("has-modal");
    const resolve = resolveOpen;
    resolveOpen = null;
    if (returnFocus && returnFocus.focus) {
      try { returnFocus.focus(); } catch (e) { /* the opener may be gone */ }
    }
    returnFocus = null;
    if (resolve) resolve(result || null);
  }

  /* options:
   *   mode          "open-file" | "open-folder" | "create-folder" | "save-file"
   *   kind          "md" | "csv" | "json" | "folders" | "any"  (what files to offer)
   *   title, note   the heading and one line under it
   *   start         a folder, or a file (its folder opens with it highlighted)
   *   select        a name to highlight in `start`
   *   confirmLabel  the primary button's word
   *   nameLabel, name   the name box (create-folder, save-file)
   *   check         {label, note, checked} -- one checkbox, returned as result.checked
   *   onChoose(result, dialog)  -> true to close; see the file comment
   * Resolves with the chosen result, or null if the dialog was dismissed. */
  function open(options) {
    if (SP && SP.isStale && SP.isStale()) return Promise.resolve(null);
    if (opts) close(null);
    opts = Object.assign({ mode: "open-file", kind: "any" }, options || {});
    listing = null;
    failedParent = null;
    highlighted = -1;
    loading = false;
    confirmQueued = false;
    returnFocus = document.activeElement;

    titleEl.textContent = opts.title || "Choose a file";
    noteEl.textContent = opts.note || "";
    noteEl.hidden = !opts.note;
    const naming = opts.mode === "create-folder" || opts.mode === "save-file";
    nameRow.hidden = !naming;
    nameLabel.textContent = opts.nameLabel || (opts.mode === "create-folder" ? "Folder name" : "File name");
    nameInput.value = opts.name || "";
    allRow.hidden = opts.kind === "folders" || opts.kind === "any";
    allBox.checked = false;
    hiddenBox.checked = false;
    newFolderBtn.hidden = opts.newFolder === false;
    closeNewFolder();
    checkRow.hidden = !opts.check;
    checkBox.checked = !!(opts.check && opts.check.checked);
    checkLabel.textContent = (opts.check && opts.check.label) || "";
    checkNote.textContent = (opts.check && opts.check.note) || "";
    checkNote.hidden = !(opts.check && opts.check.note);
    askBox.hidden = true;
    modal.classList.remove("is-asking");
    showError("");
    list.textContent = "";
    pathInput.value = "";
    crumbs.textContent = "";
    countsEl.textContent = "";
    emptyEl.hidden = true;
    setBusy(false);

    modal.hidden = false;
    document.body.classList.add("has-modal");
    // The last folder used wins; the button's own start (the bundle's
    // folder, the current file) is the first-time default, and the fallback
    // when the remembered folder has gone. Its highlight still applies when
    // the remembered folder is the one it names.
    const sticky = stickyFolder();
    const fallback = opts.start || "";
    const start = sticky || fallback;
    const parentOf = (p) => String(p || "").replace(/[\\/]+$/, "").replace(/[\\/][^\\/]*$/, "");
    let select = opts.select;
    if (sticky && fallback && sticky !== fallback) {
      select = parentOf(fallback) === sticky.replace(/[\\/]+$/, "")
        ? String(fallback).replace(/^.*[\\/]/, "") : (opts.select && fallback === sticky ? opts.select : undefined);
    }
    load(start, { select: select }).then((data) => {
      // A start that is not there (a folder deleted or renamed since)
      // falls back to the button's own start, then to home, rather than
      // an empty dialog.
      if (data !== false || !opts || listing) return;
      if (start === sticky && fallback && fallback !== sticky) {
        load(fallback, { select: opts.select }).then((again) => {
          if (again === false && opts && !listing) load("");
        });
      } else if (start) {
        load("");
      }
    });
    setTimeout(() => {
      if (!opts) return;
      (naming ? nameInput : list).focus();
      if (naming && nameInput.value) {
        const dot = nameInput.value.lastIndexOf(".");
        nameInput.setSelectionRange(0, dot > 0 && opts.mode === "save-file" ? dot : nameInput.value.length);
      }
    }, 0);
    return new Promise((resolve) => { resolveOpen = resolve; });
  }

  // ---- keyboard ---------------------------------------------------------------

  list.addEventListener("keydown", (ev) => {
    const entries = listing ? listing.entries : [];
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (!entries.length) return;
      const step = ev.key === "ArrowDown" ? 1 : -1;
      const start = highlighted < 0 ? (step > 0 ? -1 : entries.length) : highlighted;
      highlight(Math.min(entries.length - 1, Math.max(0, start + step)));
    } else if (ev.key === "Home" || ev.key === "End") {
      ev.preventDefault();
      if (entries.length) highlight(ev.key === "Home" ? 0 : entries.length - 1);
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      if (highlighted >= 0) activate(highlighted);
      else confirm();
    } else if (ev.key === "Backspace" || (ev.key === "ArrowLeft" && ev.altKey) ||
               (ev.key === "ArrowUp" && ev.altKey)) {
      ev.preventDefault();
      goUp();
    } else if (ev.key === "ArrowRight") {
      const entry = highlightedEntry();
      if (entry && entry.type === "dir") { ev.preventDefault(); load(entry.path); }
    } else if (ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      // Type-to-find: the first entry after the highlight starting with
      // that letter, the way every file manager does it.
      const ch = ev.key.toLowerCase();
      for (let k = 1; k <= entries.length; k++) {
        const i = (highlighted + k) % entries.length;
        if (entries[i].name.toLowerCase().charAt(0) === ch) { highlight(i); break; }
      }
    }
  });

  pathInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); submitPath(); }
    else if (ev.key === "ArrowDown") { ev.preventDefault(); list.focus(); if (highlighted < 0) highlight(0); }
  });
  nameInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); confirm(); }
  });
  nameInput.addEventListener("input", renderSelection);
  newFolderName.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); ev.stopPropagation(); createFolder(); }
  });

  // Escape backs out one layer at a time: the question, then the New
  // folder row, then the dialog. Tab stays inside the dialog.
  // On the document, captured, rather than on the dialog: focus can still
  // be on the button that opened it for a moment, and Escape must work
  // from there too -- and must not reach the page's own Escape handlers.
  document.addEventListener("keydown", (ev) => {
    if (!opts || ev.key !== "Escape") return;
    ev.preventDefault();
    ev.stopPropagation();
    if (askResolve) { finishAsk("cancel"); return; }
    if (!newFolderRow.hidden) { closeNewFolder(); newFolderBtn.focus(); return; }
    close(null);
  }, true);
  modal.addEventListener("keydown", (ev) => {
    if (!opts) return;
    if (ev.key === "Tab") {
      const focusable = Array.prototype.filter.call(
        dialogBox.querySelectorAll("button, input, [tabindex='0']"),
        (node) => !node.disabled && node.offsetParent !== null
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    }
  });
  // A click on the backdrop, outside the dialog, dismisses it -- unless a
  // question is up, which has to be answered by a button.
  modal.addEventListener("mousedown", (ev) => {
    if (ev.target === modal && !askResolve && !busy) close(null);
  });

  el("fb-up").addEventListener("click", goUp);
  el("fb-home").addEventListener("click", () => load(""));
  el("fb-go").addEventListener("click", submitPath);
  el("fb-close").addEventListener("click", () => close(null));
  el("fb-cancel").addEventListener("click", () => close(null));
  confirmBtn.addEventListener("click", confirm);
  hiddenBox.addEventListener("change", () => { if (listing) load(listing.path); });
  allBox.addEventListener("change", () => { if (listing) load(listing.path); });
  newFolderBtn.addEventListener("click", openNewFolder);
  el("fb-newfolder-create").addEventListener("click", createFolder);
  el("fb-newfolder-cancel").addEventListener("click", closeNewFolder);

  // The page going out of date takes the dialog with it: everything it
  // could do next is a write, or leads to one.
  if (SP && SP.onStale) SP.onStale(() => close(null));

  // ---- Browse... beside the one remaining path box ---------------------------
  // Step 04's tile Change file (its path box is hidden now) gets a button
  // that fills the box and presses the box's own Load, so the load itself
  // is the mode's code, unchanged. Watch's watch-conditions file had one
  // too until an earlier change made it a bundle file: watch.js now opens this
  // dialog itself and copies the choice in, as Build's steps 02/03 do.
  function browseInto(buttonId, inputId, loadId, spec) {
    const button = el(buttonId);
    const input = el(inputId);
    const loadBtn = el(loadId);
    if (!button || !input || !loadBtn) return;
    button.addEventListener("click", (ev) => {
      // Step 04's Change file sits on its tile: open the dialog without
      // the click also counting as a click on the tile.
      ev.stopPropagation();
      const bundle = SP && SP.bundle ? SP.bundle() : null;
      open({
        mode: "open-file",
        kind: "json",
        title: spec.title,
        note: spec.note,
        start: (input.value || "").trim() ||
          (bundle ? bundle.directory : (SP && SP.workspace ? SP.workspace() : "")),
        confirmLabel: "Load",
        onChoose: (result) => {
          input.value = result.path;
          loadBtn.click();
          return true;
        },
      });
    });
  }
  browseInto("plan-browse-btn", "plan-path", "plan-load-btn", {
    title: "Open a plan",
    note: "Read-only: the plan is shown on step 04, and nothing is copied or written.",
  });

  window.AtooFiles = {
    open: open,
    close: () => close(null),
    isOpen: () => !!opts,
    joinPath: joinPath,
    splitPath: splitPath,
  };
})();
