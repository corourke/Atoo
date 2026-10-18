"""O6 operator interface: a local web UI over `atoo`'s own engine.

**One page.** `/` is the **shell** -- mockup version H's one page with
three modes, Build | Apply | Watch. Build is whole:
the chrome -- the mode nav, the bundle bar with its console readout and
Ping, and the findings dock -- then **Build's three file tiles**,
`01 Conventions`, `02 Input list`, `03 Instructions`, each showing its
file with whatever findings reading it produced (a file not there yet is
a to-do on its tile, and an ERROR only when Build is pressed without it) -- and each editable in
place, the house file only behind "Edit house
style..." -- and **step 04
Plan**, which runs `atoo build` in a worker thread, reports it
running / done / failed -- with a live readout of the model call it is in
(`BuildRun`'s `progress`) -- renders the plan with `setup.js`'s renderers and
puts its verify and critic findings in the dock -- the one place the
page lists findings. `/setup`, the
read-only plan viewer, was retired when step 04 landed:
step 04 is that viewer, plus the build. **Apply is built**:
the pre-flight verify, a dry-run preview, an arm-to-write checkbox and the
journal view. **Watch moved in**: FR-6.4's alert table, the
connect panel and the watch-rules editor, which until then were a page of
their own at `/` while the shell lived at `/app`. That page is retired,
the shell took its URL, and `/app` redirects to `/` so a bookmark still
lands.

**One endpoint writes to a console, and only when armed.** Everything
else reads: the watch loop reads, `POST /api/ping` makes exactly one
identity round trip (FR-X.16 -- one datagram, nothing else read, which is
what makes it safe mid-show), and `GET /api/apply/preflight` verifies a
plan without contacting anything. `POST /api/apply/run` is the one that
can write, and it runs `atoo apply` -- the command, in a worker
thread, with every gate that command has -- so the browser and a terminal
cannot write differently. It writes only when the request carries BOTH
`confirm` and `arm`; `arm` is the screen's "Arm"
checkbox and `confirm` is the button, and either alone previews. That is
`--confirm`, and there is exactly one of it, on exactly one screen
(`OPTIONS-H.md`). `POST /api/build/run` writes to *disk* -- the bundle's
`plan.json`, and the watchlist it drafts into `watch.json` -- exactly as
`atoo build --show` does, because it is that command. Three more
write to disk and only to disk (2026-09-25): step 01's New file
(`POST /api/build/conventions/new`) and step 03's
(`POST /api/build/instructions/new`) each create an EMPTY file, never
over an existing file (the example text beside each editor is a
suggestion the page inserts only when asked, never written by these), and `POST /api/config/conventions-default` -- or
New file's own checkbox -- changes the one `[conventions] default` line
of `~/.atoo.config` (`config.set_default_conventions`). And two
save the files a build reads:
`POST /api/build/sections/save` and `POST /api/build/input-list/save`
write the one file a Build step shows -- steps 01 and 03 the whole
file as the editor holds it, step 02 only the rows that changed
(`source_edit`) -- and refuse a stale page and a file changed on
disk since the page read it. Every Build payload says whether the
bundle's plan is still what its inputs would build (`plan_freshness`).
The file browser adds two more: `POST /api/fs/mkdir`
makes one empty folder, and `POST /api/bundle/adopt` copies a file the
operator chose into the open bundle as its `input.csv` /
`instructions.md` / `watch.json`, never over one that is there without
being asked. Watch's watch-conditions file is a bundle file like those
two: Change file copies one in, `POST
/api/watch-conditions/new` makes an empty one there, and Save with no
path writes the bundle's.
Those two, the read-only `GET /api/fs/list`, and every endpoint that
opens a path the request names, answer this machine's own
browser only (`_local_only`), and every write endpoint refuses a
request a browser marks as coming from another web page
(`_refuse_cross_site_writes`).

**Runs with no internet access.** Every asset this module serves
(`web/static/*`) is a local file with no CDN script/stylesheet/font
reference -- the target machine is a laptop at FOH with LAN access to a
console and nothing else. `fastapi`/`uvicorn` are a real dependency (the
engine itself still has none, `pyproject.toml`'s `[ui]` extra), installed
once from wherever the laptop normally gets packages; nothing at runtime
reaches outside localhost.

**Single session, like the CLI.** FR-6.7's "session-based" scope means
one watch loop live at a time -- starting a new one (a different console,
or switching to Demo) stops whatever was running, the same
posture as opening a second `atoo watch` on top of a first. Any
number of browser tabs may connect to `/ws/watch` and see the same feed;
there is no per-tab watch state.

**Demo needs no console, and is a whole show.** Demo is a choice in the
bundle bar's console editor, beside the address: `POST
/api/console` with `demo`. It opens the packaged demo
show (`DEMO_SHOW_DIR`, `starter/demo-show/`) in the same request, and
the two always go together -- there is no Demo console on any other
show, and an address, or opening or creating a show, leaves both
(`before_demo` holds what Demo replaced). The bar then reads "Demo show"
read-only and "Demo", with no address anywhere on the page; Build shows
the demo's files and plan, step 01 its own packaged house conventions
(`DEMO_CONVENTIONS`), never the user's; Watch runs on
`demo_provider_factory` with the demo's `watch.json`; Ping says there is
no desk to ping. **Apply previews, and never writes**: a
Full build or Patch preview runs the real command on a scratch copy of
the demo show, against the simulated WING `demo_desk.DemoDesk` answers
on localhost (the initialized Compact capture with `before.json` laid
over it), so the preview read is the same code a desk gets; a write --
Apply or Patch with `confirm` -- is refused before anything starts
(`_demo_write_refusal`), and Undo refuses too,
because a write with nowhere to go must not look like one that landed.
A typed change needs a model, which the Demo does not bring: with none
configured, a Demo Patch preview is refused and the page says so at
INFO. **The demo show is immutable**: every write endpoint refuses it
with a `403` (`_refuse_demo`), and any path inside the packaged demo
folder whatever show is open (`_inside_demo`); the page's greyed
controls are a courtesy. Its plan is rebuilt, with no model, only in the
development repository, by its Demo-show builder.
`web/demo_states/before.json` -- the clean WING Compact rig the demo
show describes, as if its plan had been applied -- is the fixed base.
On top of it, `_DEMO_ISSUES`
(below) is a bank of independent single-issue mutations, each a real,
already-defined `audit.py` finding expressed as a handful of address
overrides. `demo_provider_factory` randomly arms and clears a few of them
on each read, so the alert table behaves like a live show rather than a
two-frame flip-book: issues appear and clear at random, never all at once,
never the same way twice, and never past `len(_DEMO_ISSUES)` -- there is
no way for the shown set to duplicate or grow unbounded.

**Startup config is embedded, not fetched.** `--show`'s bundle, the
resolved console address, Build's three already-read source files and
`--plan`'s plan reach `/` as one `<script type="application/json">`
blob spliced into the page by `_embed_startup_json` -- in the document
before the page's own script runs, so the values are on screen at first
paint. The console address
 is seeded from `ATOO_CONSOLE` / `~/.atoo.config`'s
`[console]` section via `cli.resolve_console_defaults()`, and the page
**says where a seeded value came from** rather than presenting it as
something the operator typed.

**One console, editable in the bundle bar and nowhere else** (FR-6.9,
2026-09-24): one plan may be applied to more than one console, say a
primary Compact and a backup Rack. `POST /api/console` changes it without a restart, and Ping,
Apply, Patch, Undo and Watch all read `app.state.console_defaults`. It is
refused while a write runs (`console_lock`), a confirmed write naming a
different desk than the bar holds is refused (`expected_console`), and a
patch review is keyed on the console too. After an edit the provenance is
`CONSOLE_SET_HERE`.

**A stale page cannot write** (FR-6.11; from a desk session,
2026-09-24: a tab kept open across a server restart onto a different
bundle copy kept showing the old show). The desk check above guards WHICH
desk; this guards WHAT is written. Every confirmed apply, patch and undo
carries what the page reviewed -- the bundle it shows, and the plan's
sha256, the patch review's id or the journal-stack top -- and is refused
(409, `stale`) when any differs from what the server would act on or is
missing (`_stale_bundle` and the checks beside it). And each server
process has a random `instance` id, embedded at first paint and answered
by `GET /api/status` with the open bundle, so the page can see that the
server behind it is not the one that drew it and say so before anyone
presses anything.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import random
import re
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import anyio
import anyio.abc
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from atoo import report as report_module
from atoo import build_log as build_log_module
from atoo import bundle, config, console_facts, firstrun, install_info
from atoo import input_list as input_list_module
from atoo import conventions_ref
from atoo import conventions_text
from atoo import plan_diff
from atoo import finding_groups
from atoo import fsbrowse

from atoo import plan_freshness
from atoo import source_edit
from atoo.audit import (AuditRule, ConsoleState, DEFAULT_RULES, Finding,
                             coverage_caveat, position_label, read_console_state,
                             strip_label)
from atoo.diagnostics import Diagnostic, Severity
from atoo.metering import ClipStatus, ClipTracker
from atoo.watch import (WatchEvent, WatchNote, finding_key, present_findings,
                        virtual_soundcheck_note, watch)

_STATIC_DIR = Path(__file__).parent / "web" / "static"
_DEMO_DIR = Path(__file__).parent / "web" / "demo_states"

#: The demo show: a packaged, read-only show bundle that
#: matches the Demo console's rig. It lives in the starter set
#: (`firstrun.STARTER_DIR`: the repository's top-level `starter/`,
#: packaged as `atoo.starter`), so `DEMO_ROOT` is that
#: set, holding the show (`demo-show/`) beside the starter conventions and
#: presets it was built from -- one copy of each. Every file under it is
#: refused to every write endpoint (`_inside_demo`). It is changed only in
#: the development repository, by its Demo-show builder.
DEMO_ROOT = firstrun.STARTER_DIR
DEMO_SHOW_DIR = DEMO_ROOT / firstrun.DEMO_SHOW_NAME
DEMO_CONVENTIONS = DEMO_ROOT / "conventions.md"
#: The demo show's own preset library, the starter's: the
#: `.chn` files its conventions name, read instead of the user's library while the demo
#: show is open, as its conventions are. The development repository's
#: Demo-show builder expands them into the plan; until they are there the plan names
#: presets it carries no values for, and verify says so once
#: (`preset.no-library`), never per strip against an unrelated library.
DEMO_PRESETS = DEMO_ROOT / firstrun.PRESETS_NAME
#: What the bundle bar names the demo show.
DEMO_SHOW_LABEL = "Demo show"


def _inside_demo(path: "str | Path | None") -> bool:
    """Whether `path` is the demo show's folder or anything under it --
    the packaged files no endpoint may write."""
    if path is None or not str(path).strip():
        return False
    try:
        resolved = Path(path).expanduser().resolve()
        root = DEMO_ROOT.resolve()
    except (OSError, RuntimeError):
        return False
    return resolved == root or root in resolved.parents


def is_demo_show(show: "bundle.Bundle | None") -> bool:
    """Whether the open bundle is the packaged demo show."""
    if show is None:
        return False
    try:
        return show.directory.resolve() == DEMO_SHOW_DIR.resolve()
    except OSError:
        return False

# WING Compact's own fixed object counts (atoo/cli.py's
# _add_console_read_arguments defaults) -- what a live read requests when
# the UI's connect form doesn't override them.
#
# `bulk=True` is the CLI's default too: A11 found the
# node-dump read agreeing with the per-leaf one on every value, at ~5s a
# pass against ~2 minutes. Spelled out here rather than inherited,
# because `read_console_state`'s own default stays per-leaf (its
# docstring says why) and the Watch page must not read the desk more
# slowly than `atoo watch` does. `ConnectRequest.per_leaf` is the
# opt-out, as `--per-leaf` is on the command line.
_DEFAULT_READ_KWARGS = dict(channels=40, aux=8, buses=16, mains=4, matrices=8, dcas=16, mute_groups=8,
                            bulk=True)

#: `address_source` / `port_source` for a value typed into the bundle bar.
#: The bar shows provenance for every address; after an edit the
#: provenance is "set here", and every write screen repeats it.
CONSOLE_SET_HERE = "set here"

#: What the bar names the demo console: "Just call it 'Demo'".
#: The console dict for it is `{"demo": True, "address": None, ...}` and
#: carries NO address. Apply and Patch refuse a write to it first,
#: armed or not (`_demo_write_refusal`), and preview
#: against the simulated WING; an endpoint that does not know the Demo
#: finds no address and refuses it as it refuses "no console".
DEMO_CONSOLE_LABEL = "Demo"
#: How the page names the Demo's simulated desk when a preview reads it.
from atoo.demo_desk import DEMO_DESK_WORDS  # noqa: E402


def _plan_counts(plan: "dict | None") -> dict:
    """What Apply's step 1 counts in a plan: its channels
    (and auxes), busses, mains, matrices, DCAs, mute groups, and the
    distinct sockets it patches, in and out."""
    plan = plan if isinstance(plan, dict) else {}
    channels = [c for c in plan.get("channels") or [] if isinstance(c, dict)]
    outputs = [o for o in (plan.get("outputs") or {}).values() if isinstance(o, dict)]
    busses = [b for b in (plan.get("busses") or {}).values() if isinstance(b, dict)]
    sockets: set = set()

    def add(patch: object, way: str) -> None:
        if isinstance(patch, dict) and isinstance(patch.get("group"), str):
            for n in patch.get("sockets") or []:
                sockets.add((way, patch["group"], n))

    for c in channels:
        add(c.get("patch"), "in")
    for b in busses:
        add((b.get("destination") or {}).get("patch"), "out")
    for o in outputs:
        add(o.get("patch"), "out")
    return {
        "channels": sum(1 for c in channels if (c.get("bank") or "ch") == "ch"),
        "aux": sum(1 for c in channels if c.get("bank") == "aux"),
        "busses": len(busses),
        "mains": sum(1 for o in outputs if o.get("kind") == "main"),
        "matrices": sum(1 for o in outputs if o.get("kind") == "matrix"),
        "dcas": len(plan.get("dcas") or {}),
        "mute_groups": len(plan.get("mute_groups") or {}),
        "sockets": len(sockets),
    }


def _patch_model_state() -> "tuple[bool, str | None]":
    """Can a typed change be compiled here? `(True, None)`, or `(False,
    why)`. A typed change is one model call (`atoo patch`), and a
    model needs configuring (`ai_provider.provider_from_env`); nothing is
    contacted to answer this."""
    from atoo.ai_provider import AIProviderError, provider_from_env

    try:
        provider_from_env()
    except AIProviderError as exc:
        text = str(exc)
        if "API key" in text:
            return False, ("no API key: set ANTHROPIC_API_KEY (or ATOO_AI_API_KEY) before "
                           "starting `atoo ui`, or ATOO_AI_PROVIDER=ollama for a "
                           "local model")
        return False, text
    return True, None

_CONSOLE_ADDRESS_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")


def _console_label(console: dict) -> str:
    """`address:port` -- how the page names a desk, and what a write's
    `expected_console` is compared against. The demo console is "Demo"."""
    if console.get("demo"):
        return DEMO_CONSOLE_LABEL
    return f"{(console.get('address') or '').strip()}:{console.get('port') or 2223}"


def _demo_console(current: "dict | None") -> dict:
    """The Demo console: no address, so nothing can be written to it --
    a write is refused (`_demo_write_refusal`), and a preview reads the
    simulated WING instead. The port and timeout in force
    are kept beside it, so choosing an address again starts from them."""
    updated = dict(current or {})
    updated["demo"] = True
    updated["address"] = None
    updated["address_source"] = CONSOLE_SET_HERE
    updated.setdefault("port", 2223)
    updated.setdefault("port_source", None)
    updated.setdefault("timeout", 1.0)
    updated.setdefault("timeout_source", None)
    return updated


StateProvider = Callable[[], ConsoleState]
ProviderFactory = Callable[[], tuple[StateProvider, "Callable[[], None] | None"]]


class ConnectRequest(BaseModel):
    # pydantic evaluates these annotations at class-definition time (even
    # under `from __future__ import annotations`), so they spell optional
    # fields `Optional[X]` rather than `X | None`, in every model below.
    # "console": the bundle bar's (or `console`, a scripted override).
    # An earlier change removed "demo": Demo is chosen in the bar, with the show.
    source: str = "console"
    console: Optional[str] = None
    port: int = 2223
    timeout: float = 1.0
    interval: float = 2.0
    input_sockets: Optional[str] = None
    output_sockets: Optional[str] = None
    # An optional watch-conditions file (FR-6.5), loaded and
    # validated the same way `atoo watch --watch-conditions` already
    # does on the CLI side -- see `/api/watch/start` below. None (the
    # default) is today's existing behavior: built-in structural rules
    # only, no operator-authored conditions.
    watch_conditions_path: Optional[str] = None
    # The same way back `atoo watch --per-leaf` offers.
    # Absent (the default) reads by node dump; the connect form does not
    # send it, so it is for a scripted client diagnosing a desk that
    # misbehaves under node dumps.
    per_leaf: bool = False
    # Read names at Start and then every this many readings,
    # as `atoo watch --name-refresh` does. Absent (what the page
    # sends): `watch.DEFAULT_NAME_REFRESH`, or 1 with `per_leaf`. The
    # page has no control for it; 1 reads names every reading.
    name_refresh: Optional[int] = None
    # The Virtual soundcheck switch as it stands at Start: channels on their
    # alternate input (C004) and the global alternate switch (C005) are
    # reported at INFO. Absent (False) is the default every Start begins
    # from; nothing is remembered between watches.
    virtual_soundcheck: bool = False


class VirtualSoundcheckRequest(BaseModel):
    on: bool


class PlanLoadRequest(BaseModel):
    # Same annotation style as ConnectRequest above (`Optional[X]`, not
    # `X | None`), even though this field happens not to need one.
    path: str


class WatchConditionsLoadRequest(BaseModel):
    # Mirrors PlanLoadRequest exactly -- same "path-based load" shape
    # the design (setup-ui-design.md §7) asks every artifact
    # endpoint to share.
    path: str


class BundleOpenRequest(BaseModel):
    # Mockup version H's bundle bar: `Show bundle: touringband/  [Change...]
    # [New show...]`. Both buttons POST here; `create` is what tells them
    # apart. Same annotation style as every model above.
    directory: str
    create: bool = False


class BuildSourceLoadRequest(BaseModel):
    # Version H's per-tile "Change file" affordance (Build steps 01-03).
    # `slot` is one of `_BUILD_SLOTS` below -- the three files a build
    # reads -- and `path` is what to read instead of the derived default.
    # Same annotation style as every model above.
    slot: str
    path: str


class NewConventionsRequest(BaseModel):
    # Step 01's "New file" (2026-09-25): write a blank house conventions
    # file at `path` -- never over an existing one -- and point step 01 at
    # it. `make_default` is the row's own checkbox, and only ever ADDS a
    # `[conventions] default` to ~/.atoo.config: a different default
    # already there is reported, never replaced (see
    # `ConventionsDefaultRequest` for the explicit replace).
    path: str
    make_default: bool = False


class ConventionsDefaultRequest(BaseModel):
    # Make an existing file the `[conventions] default` in
    # ~/.atoo.config. `replace` must be set to change a default that
    # names a different file: without it that is a 409 saying what is there.
    path: str
    replace: bool = False


class SectionsSaveRequest(BaseModel):
    """Save on Build step 01 (house conventions) or step 03 (instructions)
    -- Same annotation style as every model above.

    `slot` is "conventions" or "instructions"; the FILE is whatever that
    step shows, resolved by the server -- the page never sends a path to
    write. `expected_path` and `expected_sha256` are the file the page
    read and the hash of the bytes it read (`_build_source_payload`'s
    `path` and `sha256`): a save is refused (409, `stale: "file"`) when
    either no longer matches, so an edit made in another editor since is
    never written over. `expected_bundle` is the show bundle the page
    shows (FR-6.11), refused when it is not the one the server has open.

    `text` is the whole file, as the step's one editor holds it (there is no
    sections view) -- written as given, in the file's own
    line ending (`source_edit.replace_text`). The path keeps its old name
    ("sections") because it is an API; there are no sections any more.

    `house_confirmed` says the save was meant for the HOUSE file -- it is
    outside the bundle and every show that names it builds from it, so a
    save to it is refused without it. The page sends it while step 01 is
    being edited, with the warning naming that blast radius on screen
    (step 01 is edited like step 03, no gate)."""

    slot: str
    expected_path: Optional[str] = None
    expected_sha256: Optional[str] = None
    expected_bundle: Optional[str] = None
    house_confirmed: bool = False
    # The whole file, as the step's editor holds it. Required: a request
    # without it is refused rather than read as "no change".
    text: Optional[str] = None


class InputListSaveRequest(BaseModel):
    """Save on Build step 02 -- an earlier change. `rows` is the table, in order:
    `{line, values}` with `line` the record's position in the file
    (`_build_source_payload`'s `records`) or null for a new row, and
    `values` the canonical columns the operator changed (all of them for
    a new row). The staleness fields are `SectionsSaveRequest`'s. Same
    annotation style as every model above."""

    expected_path: Optional[str] = None
    expected_sha256: Optional[str] = None
    expected_bundle: Optional[str] = None
    rows: list[dict] = []


class BuildStopRequest(BaseModel):
    # Build step 04's Stop button. `expected_bundle` is the show bundle the
    # page shows, checked exactly as `POST /api/build/run` checks it: named,
    # it must be the one the server has open.
    expected_bundle: Optional[str] = None


class BuildRunRequest(BaseModel):
    # Build step 04's Run button: `atoo build --show DIR` with the
    # two things the page chooses. `console_model` is not optional to the
    # build -- an unstated model is a hard stop there -- and it
    # is Optional here only so a request that forgot it gets that refusal
    # in Atoo's words rather than FastAPI's 422. Same
    # annotation style as every model above.
    console_model: Optional[str] = None
    critic: bool = False
    # The show bundle the page shows (FR-6.11). A build writes plan.json
    # into the bundle the SERVER has open, so a page showing another is
    # refused (409, `stale: "bundle"`). Absent is allowed here, unlike a
    # console write: a build writes nothing a rebuild cannot replace, and
    # a script that never saw a page has no stale view to guard against.
    expected_bundle: Optional[str] = None


class ApplyRunRequest(BaseModel):
    """Apply's Preview and Apply-to-console buttons.

    **Two booleans, on purpose.** `confirm` is the button that was
    pressed; `arm` is the "Arm" checkbox beside it.
    `--confirm` is passed to `atoo apply` only when **both** are
    true, so a request that reaches here with the button but not the
    checkbox is refused rather than quietly downgraded -- a write asked
    for without the arming control is a bug somewhere, and a silent
    preview would hide it. Preview sends neither and is always available.

    There is no console field here and none on the screen. There is ONE
    console, in the bundle bar -- resolved at startup (FR-X.17)
    and editable there -- and a second place to type
    an address is a second chance to write to the wrong desk.

    `expected_console` is not a way to choose one. It is the desk the page
    is SHOWING, as `address:port`, and a confirmed write whose page shows a
    different desk than the bar now holds is refused (409): a tab left
    open while the address was changed in another must not write to a desk
    it does not name. Absent, nothing is compared -- a scripted client that
    never saw a page has no stale view to guard against.

    **What the page reviewed** (from a desk session, 2026-09-24: a tab
    kept open across a server restart onto a different bundle copy).
    `expected_bundle` is the show bundle directory the page shows, and
    `expected_plan_sha256` the sha256 of the `plan.json` its pre-flight
    verified (`GET /api/apply/preflight`'s `plan_sha256`). A confirmed
    write is refused (409) when either differs from what the server would
    write -- and, unlike `expected_console`, when either is ABSENT: a
    confirmed write that cannot say which show and which plan it was
    reviewed against is a page from before this guard existed, which is
    exactly the stale tab it is for. See `_stale_bundle`.

    Same annotation style as every model above.
    """

    confirm: bool = False
    arm: bool = False
    skip_verify: bool = False
    clean_output_sockets: Optional[str] = None
    expected_console: Optional[str] = None
    expected_bundle: Optional[str] = None
    expected_plan_sha256: Optional[str] = None


class PromoteRequest(BaseModel):
    """The Patch screen's "Keep this in the show" --
    `atoo patch --show DIR --promote REF`. `ref` is the journal entry's
    id, as the stack row carries it. Without `confirm` it previews; with
    it, it appends to the bundle's instructions.md and input.csv. It writes
    the show's FILES, never the console, so it needs no arming -- and it is
    a Setup write, so it answers this laptop's own browser only."""

    ref: str
    confirm: bool = False


class PatchRunRequest(BaseModel):
    """The Patch screen's Preview change and Write the change buttons
    -- `atoo patch --show DIR` with a typed change.

    **The same two booleans and the same one checkbox as Apply's write.**
    `change` is the text the engineer typed. A preview
    compiles it (one model call) and reads the desk; the server keeps the
    change set that preview compiled, and a confirmed write hands the
    command THAT change set (`--change-set`), never a fresh compile -- a
    second model call could answer differently, and the write must be the
    change the page showed. So the write is refused (409) unless the text,
    the plan on the desk, `allow_strips` and the console are all the ones
    the last clean preview reviewed, and `expected_review_id` names that
    review.

    Same annotation style as every model above.
    """

    confirm: bool = False
    arm: bool = False
    change: str = ""
    allow_strips: list[str] = []
    expected_console: Optional[str] = None
    expected_bundle: Optional[str] = None
    expected_review_id: Optional[str] = None


class UndoRunRequest(BaseModel):
    """The journal stack's Undo buttons (on the stack):
    `atoo undo --show DIR`, which pops the newest write still
    standing. An undo is a write, so it is armed by the same one checkbox
    as every other write on this page -- `confirm` without `arm` is
    refused, exactly as for an apply. Same annotation style as
    every model above.

    The command pops the newest write **on the desk it reaches** (per-desk
    journal history), which is the bundle bar's console.
    `expected_console` and `expected_bundle` are `ApplyRunRequest`'s, and
    `expected_undo_id` is the journal-stack entry the page shows as the
    one Undo reverses (`GET /api/journals`' row with `is_top`) -- required
    on a confirmed undo, and refused (409) when a write recorded since has
    made a different entry the top."""

    confirm: bool = False
    arm: bool = False
    expected_console: Optional[str] = None
    expected_bundle: Optional[str] = None
    expected_undo_id: Optional[str] = None


class PingRequest(BaseModel):
    # Every field optional: the bundle bar's Ping button sends `{}` and
    # means "the console in the bar" -- resolved at startup
    # (ATOO_CONSOLE / ~/.atoo.config [console]) or set there
    # since (`POST /api/console`). A value sent here overrides that for
    # this one round trip and is not remembered; the page itself never
    # sends one -- there is one console on it, and it is the bar's.
    console: Optional[str] = None
    port: Optional[int] = None
    timeout: Optional[float] = None


class ConsoleSetRequest(BaseModel):
    """The bundle bar's console edit: editable in the bundle bar only,
    because one plan may be applied to more than one console, say a
    primary Compact and a backup Rack.

    `port` omitted keeps the port in force. There is no timeout here: it is
    how long to wait for a reply, not which desk, and it stays what the
    startup configuration said. Same annotation style as every
    model above."""

    address: Optional[str] = None
    port: Optional[int] = None
    # The demo console is chosen on the same dialog as the IP
    # address, and called 'Demo'. `demo` opens the packaged demo show AND
    # sets the Demo console, as one action -- there is no Demo console on
    # any other show. `address` and `port` are ignored when it is set.
    demo: bool = False


class WatchConditionsSaveRequest(BaseModel):
    # `watch_conditions` is the editor table's rows, in the exact
    # `{id, description, channel, field, operator, value, severity}` shape
    # `atoo.watch_conditions._REQUIRED_KEYS` requires -- validated
    # against that module's own loader before anything is written to
    # disk (see `_load_watch_conditions_from_path`'s sibling validation
    # path in `api_watch_conditions_save` below).
    #
    # `path` absent is "the open bundle's watch.json": the
    # file goes with the bundle, so an editor with nothing loaded yet
    # saves into it rather than asking for a path.
    path: Optional[str] = None
    watch_conditions: list[dict]


class WatchConditionsCheckRequest(BaseModel):
    # The editor table's rows, checked one by one with
    # `watch_conditions.row_problems` -- the loader's own rules -- so the
    # table can refuse a malformed target or value inline, before Save.
    watch_conditions: list


# ---- The file browser and copy-into-bundle ----------
# Same annotation style as every model above.

class FsMkdirRequest(BaseModel):
    # The file browser's New folder: `path` is the new folder, absolute or
    # relative to `base` -- the folder the dialog is showing.
    path: str
    base: Optional[str] = None


class BundleAdoptRequest(BaseModel):
    # Copy a file the operator chose into the open bundle as its
    # `input.csv` or `instructions.md`. `replace` is the
    # modal's "Replace the bundle's" answer, sent only after a 409 said
    # what is there. `expected_bundle` is FR-6.11's: this writes into a
    # bundle, so it must say which one the page showed.
    slot: str
    path: str
    replace: bool = False
    expected_bundle: Optional[str] = None


class NewInstructionsRequest(BaseModel):
    # Step 03's New file writes into the bundle, so -- like every other
    # write from the page into a bundle -- it names the bundle it saw.
    expected_bundle: Optional[str] = None


class NewWatchConditionsRequest(BaseModel):
    # Watch's New file: an empty watch.json in the open
    # bundle, the way step 03's New file makes an empty instructions.md --
    # and, for the same reason, naming the bundle the page showed.
    expected_bundle: Optional[str] = None


def _parse_socket_counts(spec: str | None) -> dict:
    if not spec:
        return {}
    counts: dict[str, int] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        group, _, count = part.partition("=")
        counts[group.strip()] = int(count.strip())
    return counts


def _finding_to_dict(f: Finding) -> dict:
    return {
        "rule_id": f.rule_id,
        "severity": f.severity.value,
        "category": f.category,
        "title": f.title,
        "detail": f.detail,
        "addresses": list(f.addresses),
    }


_STRIP_BASE = re.compile(r"^(/(?:ch|aux|bus|main|mtx|dca|mgrp)/\d+)(?:/|$)")
_SOCKET = re.compile(r"^/io/(?:in|out)/([A-Za-z0-9-]+)/(\d+)(?:/|$)")


def finding_strip(f: Finding, state: "ConsoleState | None") -> "str | None":
    """What the Watch table's "Where" column shows for `f`:
    the strip it is about, as the desk names it -- `CH 6 "Bass DI"`, the
    label the finding's own detail uses (`audit.strip_label`) -- from the
    finding's addresses. Several strips: their positions (`CH 3, CH 4`).
    No strip but a socket: the socket (`LCL 9`). Neither: None, and the
    page shows a dash. Sent by the server so the page never has to parse
    it back out of the detail text."""
    bases: list[str] = []
    sockets: list[str] = []
    for address in f.addresses:
        m = _STRIP_BASE.match(address)
        if m:
            if m.group(1) not in bases:
                bases.append(m.group(1))
            continue
        s = _SOCKET.match(address)
        if s:
            socket = f"{s.group(1)} {s.group(2)}"
            if socket not in sockets:
                sockets.append(socket)
    if len(bases) == 1:
        return strip_label(state, bases[0]) if state is not None else position_label(bases[0])
    if bases:
        return ", ".join(position_label(b) for b in bases)
    if sockets:
        return ", ".join(sockets)
    return None


def _note_to_dict(note: WatchNote) -> dict:
    """A watch note for the status line under the Watch
    header: the finding's fields, plus its short form."""
    return {**_finding_to_dict(note), "group": note.group, "summary": note.summary}


class _WatchPresenter:
    """Turns each `WatchEvent` into the frame the Watch page reads, the
    way the page shows it (`watch.present_findings`): the alert table's
    findings in `all_findings`, with a built-in folded under the
    condition that caught the same fault in that finding's `also`, and the session's notes in `notes`.

    Stateful, one per session: `new_findings` and `cleared_findings` are
    the difference between what the TABLE showed last reading and shows
    now, so a built-in that folds under a condition leaves the table as
    cleared and comes back as new when the condition stops firing --
    which `watch()`'s own difference, over every finding, cannot say."""

    def __init__(self, notes: "list[WatchNote] | None" = None) -> None:
        self._previous: "dict | None" = None
        # Notes about the session that no reading carries -- the console
        # window a live watch reads with -- added to every
        # frame's own.
        self._notes = list(notes or [])

    def payload(self, event: WatchEvent, caveat: str | None = None,
                state: "ConsoleState | None" = None) -> dict:
        """`caveat` is `audit.coverage_caveat` for the state this
        event was read from -- one line, or None when the read covered
        everything its rules need. `state` is the reading
        itself, which names each row's strip (`finding_strip`).

        It rides on the event rather than being fetched separately because
        the Watch page has exactly one channel, and a caveat that arrives out
        of band arrives after the finding it qualifies. **A field the page
        must read**: since an earlier change R002/R005 stand down on a read with no
        output patch in it, and a page that shows the shorter list with no
        note cannot be told apart from a page showing a clean desk -- the
        exact FR-4.2 failure this issue is about, in the one place
        `atoo/web/static/` the Python suite cannot see."""
        shown = present_findings(event.all_findings)

        def row(f: Finding) -> dict:
            out = _finding_to_dict(f)
            out["strip"] = finding_strip(f, state)
            also = shown.folded.get(finding_key(f))
            if also:
                out["also"] = [_finding_to_dict(g) for g in also]
            return out

        current = {finding_key(f): row(f) for f in shown.alerts}
        previous, self._previous = self._previous, current
        if previous is None:
            new: list[dict] = []
            cleared: list[dict] = []
        else:
            new = [d for key, d in current.items() if key not in previous]
            cleared = [d for key, d in previous.items() if key not in current]
        return {
            "type": "event",
            "iteration": event.iteration,
            "baseline": event.iteration == 0,
            "at": event.at,
            "coverage_caveat": caveat,
            "all_findings": list(current.values()),
            "new_findings": new,
            "cleared_findings": cleared,
            "notes": [_note_to_dict(n) for n in [*shown.notes, *self._notes]],
        }


def _load_demo_base() -> dict:
    return json.loads((_DEMO_DIR / "before.json").read_text(encoding="utf-8"))


def _embed_startup_json(html: str, tag_id: str, payload: object, script_src: str) -> str:
    """Splice a `<script type="application/json">` blob into a page so
    its own script finds it already there on first paint.

    This is how startup config reaches the page in this UI -- `--plan`, the
    bundle and the resolved console address, all to `/` -- rather
    than a fetch the page makes after load. Two details, both learned the
    hard way here:

    * **`</` is escaped.** A value containing that substring would
      otherwise close the `<script>` tag early and put the rest of the
      JSON into the document as markup.
    * **The blob goes BEFORE the page's own `<script src>`, not before
      `</body>`.** Both sit at the end of the document, and a plain
      (non-deferred) `<script src>` runs the moment the parser reaches
      it -- before any later tag exists. Inserting after it meant
      `setup.js`'s `getElementById("initial-plan")` found nothing, for
      every plan, 100% of the time, and the plan silently never
      rendered. Document order, not `</body>` proximity, is what
      actually matters.

    The `</body>` fallback only fires if the expected `<script src>` tag
    is not in the page at all -- a page whose script moved, where "after
    everything" is the best guess left.
    """
    text = json.dumps(payload).replace("</", "<\\/")
    tag = f'<script id="{tag_id}" type="application/json">{text}</script>\n'
    script_tag = f'<script src="{script_src}"></script>'
    if script_tag in html:
        return html.replace(script_tag, tag + script_tag)
    return html.replace("</body>", tag + "</body>")


def _load_plan_from_path(path: str) -> tuple[dict | None, str | None]:
    """A compiled plan.json file, the same shape `atoo build`
    produces -- returns (plan, None) on success, or (None, message) on
    failure. Same OSError/JSONDecodeError shape as `cli.py`'s own
    `_load_plan_file`, but returns the message instead of printing to
    stderr: this is reached from `POST /api/plan/load`, a
    browser request, not a CLI failure path -- the caller turns the
    message into a JSON error body."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except OSError as exc:
        return None, f"couldn't read plan file {path!r}: {exc.strerror}"
    except json.JSONDecodeError as exc:
        return None, f"plan file {path!r} is not valid JSON: {exc}"


#: A finding code that was renamed, old -> new, so a plan.json built
#: before the rename shows the code the docs and the dock filter now use.
RENAMED_CODES = {"output.no-socket": "output.no-patch"}


def _plan_finding(raw: dict, source: str) -> dict:
    """One finding a plan carries in `meta`, as the dock's wire shape.

    `meta.verify_findings` and `meta.critic_findings` already ARE
    `Diagnostic.to_dict()` dicts for any plan built, so
    this mostly passes them through. What it adds is for the plan.json
    files already on someone's disk, which the page must still open:

    * the critic's `kind` became `category` -- read either;
    * an older critic finding has no `code`, and gets the
      `critic.<category>` one it was later given;
    * `critical` was a severity until 2026-09-23 and is `error` now;
    * `output.no-socket` is `output.no-patch`;
    * `source` is filled in from the block the finding was found in, so
      the dock can say verify or critic for a plan that never said so.
    """
    finding = dict(raw)
    # Renamed: what is missing is the patch, not the socket.
    if finding.get("code") in RENAMED_CODES:
        finding["code"] = RENAMED_CODES[finding["code"]]
    if not finding.get("category") and finding.get("kind"):
        finding["category"] = finding["kind"]
    finding.pop("kind", None)
    if finding.get("severity") == "critical":
        finding["severity"] = "error"
    finding.setdefault("source", source)
    if not finding.get("code"):
        finding["code"] = f"{source}.{finding.get('category') or 'finding'}"
    return finding


def _plan_findings(plan: "dict | None", fresh_verify: "list[dict] | None" = None) -> list[dict]:
    """The verify, critic and build findings of a plan, as dock findings.

    **Verify's are `fresh_verify` when the caller has them**: `verify_plan`
    run now, as `atoo apply` runs it. A plan
    built before `output.no-patch` became a WARNING kept showing the old
    ERROR -- and the old wording -- because the dock read the
    `meta.verify_findings` the build recorded, and verify's rules had
    changed since. Verify costs no model call, so the dock asks it again.
    Without `fresh_verify` (no bundle open, or the fresh run failed) they
    are the recorded ones. The critic's and the build's own findings
    (`meta.critic_findings`, `meta.build_findings`) are always the
    recorded ones: re-asking them costs a model call."""
    meta = (plan or {}).get("meta") or {}
    if fresh_verify is not None:
        out = [_plan_finding(f, "verify") for f in fresh_verify]
    else:
        verify = meta.get("verify_findings") or {}
        # `info` (decided values, unused declarations) and `build_findings`
        # (FR-6.2's quote-checked conventions audit) since 2026-09-25; a
        # plan built before then has neither key, which reads as none.
        out = [_plan_finding(f, "verify")
               for f in list(verify.get("errors") or []) + list(verify.get("warnings") or [])
               + list(verify.get("info") or [])]
    out += [_plan_finding(f, "critic") for f in meta.get("critic_findings") or []]
    out += [_plan_finding(f, "build") for f in meta.get("build_findings") or []]
    out += _rebuild_findings(plan)
    # One dock item per distinct message (FR-X.15c): twenty-two channels
    # whose preset lost the same high-pass to the plan are one item, with
    # a `members` list the page turns into a jump link per row. The plan's
    # own `meta` is untouched -- this is the reading list, not the record.
    # The dock is the ONE place these are listed; step 04
    # draws only a line counting them. Each names its strip
    # the way the desk does ("CH 23 Crowd"), in a UI-only `strip` key.
    return finding_groups.label_strips(finding_groups.group_dicts(out), plan)


#: A rebuild's change to a strip nothing it is made from changed.
REBUILD_UNASKED = "rebuild.unasked-change"

_DIFF_WHERE = {"channels": "channels", "busses": "busses", "outputs": "outputs",
               "dcas": "dcas", "mute_groups": "mute_groups"}


def _rebuild_findings(plan: "dict | None") -> list[dict]:
    """One WARNING per strip this rebuild changed although nothing it is
    made from changed (`meta.changes_since_previous`, `plan_diff`): the
    model rewrote it. It counts under "to check" in
    the Findings panel, one per change, and never blocks Apply -- the plan
    may still be right. A change the edit asked for is INFO and stays in
    step 04's "Changed since the last build" list only: the dock is for
    what needs a look."""
    meta = (plan or {}).get("meta") or {}
    changes = meta.get(plan_diff.CHANGES_KEY)
    if not isinstance(changes, dict):
        return []
    against = changes.get("against")
    if not isinstance(against, str) or not against:
        against = "plan.previous.json"
    strips = changes.get("strips")
    if not isinstance(strips, list):
        return []
    out = []
    for strip in strips:
        if not isinstance(strip, dict) or strip.get("severity") != plan_diff.WARNING:
            continue
        label = str(strip.get("label") or "a strip")
        summary = str(strip.get("summary") or strip.get("kind") or "changed")
        finding = {
            "severity": "warning",
            "code": REBUILD_UNASKED,
            "source": "rebuild",
            # The dock's one line: the strip is named beside it (`strip`).
            "title": "Not asked for: " + summary.replace(" -> ", " \u2192 "),
            "message": (f"{label}: {summary}, against {against}. Nothing in the input list or "
                        "the conventions about it changed -- the model rewrote it. The plan "
                        "may still be right; check it."),
            "fix": "Check the strip; if the old value was right, say so in the instructions and rebuild.",
        }
        name = _diff_strip_name(plan, strip)
        collection = strip.get("collection")
        collection = _DIFF_WHERE.get(collection) if isinstance(collection, str) else None
        if name and collection:
            finding["where"] = f"{collection}[{name}]"
        out.append(finding)
    return out


def _diff_strip_name(plan: "dict | None", strip: dict) -> "str | None":
    """The plan name a change's label ("CH 6 Bass DI") is about: a channel
    by its slot, anything else by the longest name its label ends with."""
    plan = plan or {}
    collection = strip.get("collection")
    # A removed strip is not in this plan: no row to name (as the page's
    # `changeRowId`), or "CH 6 Bass DI" would land on a channel named "DI".
    if strip.get("kind") == plan_diff.REMOVED or not isinstance(collection, str):
        return None
    slot = strip.get("slot")
    channels = plan.get("channels") if isinstance(plan.get("channels"), list) else []
    if collection == "channels" and isinstance(slot, list) and len(slot) == 2:
        for ch in channels:
            if (isinstance(ch, dict) and (ch.get("bank") or "ch") == slot[0]
                    and ch.get("channel") == slot[1] and ch.get("name")):
                return ch["name"]
    if collection == "channels":
        names = [c.get("name") for c in channels if isinstance(c, dict)]
    else:
        names = list(plan[collection].keys()) if isinstance(plan.get(collection), dict) else []
    names = [n for n in names if isinstance(n, str)]
    label = str(strip.get("label") or "")
    hits = [n for n in names if n and (label == n or label.endswith(" " + n))]
    return max(hits, key=len) if hits else None


def _patch_key(raw: object) -> "str | None":
    """ "AES50-A 4" -> "A 4"; None for a blank or unparseable cell."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    parsed = input_list_module.parse_socket_spec(raw)
    return f"{parsed[0]} {parsed[1]}" if parsed else None


def _patch_values(values: dict, column: str) -> dict:
    """A record's `values` with its patch column under the name `patch`
    -- `column` is the name the file's header uses for it."""
    if column == input_list_module.PATCH_COLUMN:
        return values
    return {(input_list_module.PATCH_COLUMN if key == column else key): value
            for key, value in values.items()}


def _channel_display(plan: "dict | None") -> list[dict]:
    """What step 04's table says about each channel that the plan does
    not state in so many words -- one entry per `plan["channels"]`, in
    the same order, alongside the plan and never written into it.

    * `sockets`: the patch as an input list spells it ("AES50-A 4"), and
      `patch_keys` ("A 4") -- the key the page joins a channel to its
      input-list row by, the same `_patch_key` each record carries
      (`_build_payload`), so the page never parses a socket. Called
      `socket_keys`.
    * `name_home`: where `apply` writes the channel's name. On a WING
      with `clink` on (the factory setting) that is the input SOCKET, and
      the strip inherits it -- the reason "Kick" is written to
      `/io/in/A/1/name` and not `/ch/1/name`. From
      `apply.source_name_link`, the rule the write itself uses.
    * `colour`: the desk's own 1..18 index for the stated colour (or the
      plan's `col`), and its name -- `index` None for a colour the desk
      does not have, which `apply` leaves unwritten.
    * `label`: the desk number step 04's first column draws -- "3", or
      "Aux 3" on the aux bank (`apply.desk_label`).

    Read-only, derived, and tolerant: a channel too malformed to say any
    of this gets `{}` rather than failing the page that has to show it.
    """
    # Imported here rather than at module top: apply.py is the writer, and
    # this is the one question the web layer asks it.
    from atoo import apply as apply_module

    channels = (plan or {}).get("channels") or []
    try:
        shared = apply_module._shared_source_sockets(plan or {})
    except (AttributeError, TypeError):
        shared = {}
    out: list[dict] = []
    for channel in channels:
        entry: dict = {}
        if not isinstance(channel, dict):
            out.append(entry)
            continue
        patch = channel.get("patch") or {}
        group = patch.get("group")
        sockets = [s for s in (patch.get("sockets") or []) if isinstance(s, int)]
        if isinstance(group, str) and sockets:
            entry["sockets"] = [input_list_module.format_socket(group, s) for s in sockets]
            entry["patch_keys"] = [f"{group} {s}" for s in sockets]
            linked, why = apply_module.source_name_link(group, sockets, shared)
            bank = channel.get("bank") if channel.get("bank") in ("ch", "aux") else "ch"
            strip = f"/{bank}/{channel.get('channel')}"
            entry["name_home"] = {
                "linked": linked,
                "addresses": ([f"/io/in/{group}/{s}/name" for s in sockets] if linked
                              else [f"{strip}/name"]),
                "strip": strip,
                "why": why,
                "shared_with": shared.get((group, sockets[0]), []),
            }
        number = channel.get("channel")
        if isinstance(number, int) and not isinstance(number, bool):
            bank = channel.get("bank") if channel.get("bank") in ("ch", "aux") else "ch"
            entry["label"] = apply_module.desk_label("channel", number, bank)
        col = channel.get("col")
        if not isinstance(col, int):
            col = console_facts.colour_index(channel.get("color"))
        if channel.get("color") is not None or col is not None:
            entry["colour"] = {
                "stated": channel.get("color"),
                "index": col,
                "name": console_facts.COLOUR_NAMES.get(col) if col is not None else None,
            }
        out.append(entry)
    return out


def _bus_display(plan: "dict | None") -> dict:
    """Step 04's bus table, the part the plan does not spell out: each
    bus's desk `number` -- from `apply.bus_indices`, the map every
    `/bus/{n}` write is addressed by -- its desk `label` ("B3") and its
    `colour`, the 1..18 index apply writes to `/bus/{n}/col` -- `col`, or
    the stated name `color` resolved through the desk's palette
    (`apply.bus_col`) -- with the desk's name for it and the `stated` name;
    `None` when the plan states none, which apply leaves unwritten. A
    stated name the desk lacks keeps `stated` with a null `index`, the
    shape a channel's unwritable colour takes, so the chip's tooltip says
    it is not written. Keyed by bus name; a bus with no usable index gets
    `{}`."""
    from atoo import apply as apply_module

    busses = (plan or {}).get("busses")
    if not isinstance(busses, dict):
        return {}
    numbers = apply_module.bus_indices({"busses": busses})
    out: dict = {}
    for name, entry in busses.items():
        number = numbers.get(name)
        if number is None:
            out[name] = {}
            continue
        col = apply_module.bus_col(entry) if isinstance(entry, dict) else None
        colour_name = console_facts.COLOUR_NAMES.get(col) if col is not None else None
        stated = entry.get("color") if isinstance(entry, dict) else None
        colour = None
        if colour_name:
            colour = {"index": col, "name": colour_name, "stated": stated}
        elif stated:
            colour = {"index": None, "name": None, "stated": stated}
        out[name] = {
            "number": number,
            "label": apply_module.desk_label("bus", number),
            "colour": colour,
        }
    return out


def _output_display(plan: "dict | None") -> dict:
    """Step 04's output table: each Main or Matrix's desk `label` ("M1",
    "MX1"), from the `kind` and `index` apply writes `/main/{n}` and
    `/mtx/{n}` by. `colour` is always `None`: the plan schema has no
    colour for a Main or a Matrix and apply writes none, so the page
    draws a neutral chip. An output the plan does not identify
    (kind/index missing -- apply warns and writes nothing) gets `{}`."""
    from atoo import apply as apply_module

    outputs = (plan or {}).get("outputs")
    if not isinstance(outputs, dict):
        return {}
    out: dict = {}
    for name, entry in outputs.items():
        kind = entry.get("kind") if isinstance(entry, dict) else None
        index = entry.get("index") if isinstance(entry, dict) else None
        if kind in ("main", "matrix") and isinstance(index, int) and not isinstance(index, bool):
            out[name] = {"kind": kind, "index": index,
                         "label": apply_module.desk_label(kind, index), "colour": None}
        else:
            out[name] = {}
    return out


def _plan_with_resolved_build_log(plan: "dict | None", path: "str | None") -> "dict | None":
    """`plan`, with `meta.build_log` filled in for the API response when
    the plan on disk only carries the pointer (`meta.build_log_file`,
    each build now writes its own file under
    `builds/`, `atoo/build_log.py`). Setup step 04's fold
    (`setup.js`'s `renderBuildLog`) reads `meta.build_log` and does not
    need to know a pointer exists at all, so this is where that
    indirection is resolved -- never by mutating `plan` itself (this
    returns a shallow copy; `app.state.plan` is untouched). A plan with
    an inline `meta.build_log` already (built before this shipped) is
    returned as-is; the fold reads that exactly as before."""
    if not isinstance(plan, dict) or not path:
        return plan
    meta = plan.get("meta")
    if not isinstance(meta, dict) or "build_log_file" not in meta or "build_log" in meta:
        return plan
    resolved = build_log_module.resolve(plan, Path(path).parent)
    if resolved is None:
        return plan
    out_meta = dict(meta)
    out_meta["build_log"] = resolved
    out = dict(plan)
    out["meta"] = out_meta
    return out


def _previous_generated_at(plan: "dict | None", path: "str | None") -> "str | None":
    """`meta.generated_at` of the plan a rebuild replaced -- the file its
    `changes_since_previous` names, beside `path` -- or None."""
    changes = ((plan or {}).get("meta") or {}).get(plan_diff.CHANGES_KEY)
    if not path or not isinstance(changes, dict):
        return None
    try:
        previous = json.loads((Path(path).parent / bundle.PLAN_PREVIOUS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    at = (previous.get("meta") or {}).get("generated_at") if isinstance(previous, dict) else None
    return at if isinstance(at, str) else None


def _plan_payload(plan: "dict | None", path: "str | None",
                  fresh_verify: "list[dict] | None" = None) -> dict:
    """`GET /api/plan`'s body: the plan, where it came from, and the
    findings it carries -- the three things step 04 draws -- plus
    `channel_display` (`_channel_display`), what the table says about
    each channel that is derived rather than stated -- and
    `bus_display`/`output_display` (`_bus_display`, `_output_display`),
    the same for the bus and output tables: the desk number and colour
    each row's chip draws."""
    plan = _plan_with_resolved_build_log(plan, path)
    return {"path": path, "plan": plan, "findings": _plan_findings(plan, fresh_verify),
            "channel_display": _channel_display(plan),
            "bus_display": _bus_display(plan),
            "output_display": _output_display(plan)}


# How many records of a COLLAPSED journal group travel to the page. The
# expanded ones -- mismatch and unreadable, the `flagged` list -- are never
# sampled: those are the rows somebody has to read. A 631-address apply is three or four of
# those and six hundred boring ones, and the boring ones are shown as a
# count with a sample behind a disclosure, exactly as version H draws it.
_APPLY_GROUP_SAMPLE = 250

# The first words of `apply.ApplyResult.summary()`'s aborted branch. See
# `_apply_abort_reason`.
_APPLY_ABORT_PREFIX = "ABORTED: lost the connection to the console ("


def _stop_duration(seconds: float) -> str:
    from atoo.progress import fmt_duration

    return fmt_duration(seconds)


def _apply_abort_reason(log: "list[str]") -> "str | None":
    """Why an apply stopped early, read back out of the run's own output.

    `apply_plan` puts `aborted`/`abort_reason` on its result and
    `ApplyResult.summary()` prints them, but `_write_journal` does not
    record them -- so a journal read back off disk cannot tell a run that
    lost the desk half way from one that finished. The command said it out
    loud, and the run's log is that command's own stdout, so this reads it
    there rather than inventing a second channel for it.

    Coupled to one literal in `apply.py`, and pinned: the test builds a
    genuinely aborted `ApplyResult`, calls its real `summary()`, and
    feeds the result to this function.
    """
    for line in log:
        line = line.rstrip()
        if line.startswith(_APPLY_ABORT_PREFIX) and line.endswith(")."):
            return line[len(_APPLY_ABORT_PREFIX):-2]
    return None


def _apply_group(key: str, label: str, records: list) -> dict:
    return {
        "key": key,
        "label": label,
        "count": len(records),
        "records": records[:_APPLY_GROUP_SAMPLE],
    }


def _write_records(journal: dict) -> list:
    """A journal's rows as `apply.WriteRecord`s -- so `would_change` is the
    engine's own comparison, never a second one."""
    from atoo.apply import WriteRecord

    return [
        WriteRecord(
            address=row.get("address", ""),
            description=row.get("description", ""),
            value_type=row.get("value_type", "s"),
            method=row.get("method"),
            ack=row.get("ack"),
            prior_value=row.get("prior_value"),
            intended_value=row.get("intended_value"),
            readback_value=row.get("readback_value"),
            status=row.get("status", ""),
            timestamp=row.get("timestamp", ""),
            readback_source=row.get("readback_source"),
            # A value its selector's change forces to be written is a write
            # even when it already reads the plan's value; without this a
            # preview's "will change" left those out and the write that
            # followed sent more than the page had said.
            forced_by=row.get("forced_by"),
        )
        for row in journal.get("writes") or []
    ]


def _apply_payload(journal: dict, journal_path: "str | None",
                   abort_reason: "str | None") -> dict:
    """One apply run, as the journal view renders it.

    The journal on disk is the source, because it is the artifact the run
    actually produced -- rendering anything else would be rendering a
    second account of the same run. It is turned back into a real
    `ApplyResult` here for one reason: **`summary()` is reused verbatim
    rather than paraphrased.** The page prints the string this method
    returns, the same string `atoo apply` prints in a terminal, so
    the two can never word the same run differently.

    `would_change` is computed HERE, never in the browser: it is
    `_values_equal`, which is type-aware and carries the stepped-parameter
    tolerance for floats. A JS reimplementation with `!==`
    would overstate a preview by exactly the three addresses that started
    that issue.
    """
    from atoo.apply import ApplyResult

    writes = _write_records(journal)
    result = ApplyResult(
        dry_run=bool(journal.get("dry_run")),
        writes=writes,
        journal_path=journal_path,
        warnings=list(journal.get("warnings") or []),
        aborted=abort_reason is not None,
        abort_reason=abort_reason,
        replies_discarded=int(journal.get("replies_discarded") or 0),
        replies_used=int(journal.get("replies_used") or 0),
        scope=journal.get("scope"),
    )

    def record(w) -> dict:
        return {
            "address": w.address,
            "description": w.description,
            "status": w.status,
            "value_type": w.value_type,
            "method": w.method,
            "ack": w.ack,
            "prior_value": w.prior_value,
            "intended_value": w.intended_value,
            "readback_value": w.readback_value,
            "readback_source": w.readback_source,
            "would_change": w.would_change,
        }

    unreadable = [w for w in writes if w.status in ("unreadable", "unreadable_skipped")]
    flagged = [record(w) for w in result.mismatches] + [record(w) for w in unreadable]

    if result.dry_run:
        previews = [w for w in writes if w.status == "dry_run"]
        groups = [
            _apply_group("would_change", "would change",
                         [record(w) for w in previews if w.would_change]),
            _apply_group("unchanged", "already correct -- no write needed",
                         [record(w) for w in previews if not w.would_change]),
        ]
    else:
        groups = [
            _apply_group("match", "matched",
                         [record(w) for w in writes if w.status == "match"]),
            _apply_group("skipped_no_change", "unchanged -- skipped, nothing sent",
                         [record(w) for w in writes if w.status == "skipped_no_change"]),
        ]

    return {
        "dry_run": result.dry_run,
        # None for a preview: a dry run's journal is a scratch file this
        # server deletes, and `atoo undo` refuses one anyway. Naming
        # a path that is already gone would be worse than naming none.
        "journal_path": journal_path if not result.dry_run else None,
        # `ApplyResult.summary()`, verbatim -- see this function's docstring.
        "summary": result.summary(),
        "aborted": result.aborted,
        "abort_reason": result.abort_reason,
        # Grouped for reading (FR-X.15c): "ch 1-23 (23 channels): patch
        # socket was not stated ..." once, not twenty-three times. The
        # journal on disk keeps one line per strip.
        "warnings": finding_groups.group_lines(result.warnings),
        # Surfaced in its own right as well as inside `summary()`: a desk
        # that duplicates datagrams is the condition that made the
        # 2026-09-21 journal worthless, and a run that says nothing about
        # it cannot be told from one where it did not happen.
        "replies_discarded": result.replies_discarded,
        "replies_used": result.replies_used,
        "scope": result.scope,
        # What `apply.check_desk_model` said about the desk against this
        # plan -- the cross-model INFO or the unmeasured-model WARNING --
        # read back from the journal, so the dock says it too. Absent
        # from a journal written before it existed, and from a same-model
        # run, which has nothing to say.
        "model_check": journal.get("model_check"),
        "desk": journal.get("desk"),
        "counts": {
            "total": len(writes),
            "would_change": len([w for w in writes
                                 if w.status == "dry_run" and w.would_change]),
            "written": len(result.changed),
            # Looked at in the write and already as the plan says: not sent,
            # and the part of a write's total that "written" leaves out.
            "unchanged": len([w for w in writes if w.status == "skipped_no_change"]),
            "mismatch": len(result.mismatches),
            "unreadable": len(unreadable),
            "cleaned": len(result.cleaned),
        },
        "flagged": flagged,
        "groups": [g for g in groups if g["count"]],
    }


def _apply_findings(payload: dict, address: str) -> list[dict]:
    """What one apply run puts in the shared findings dock.

    The journal view already draws every mismatch and every unreadable
    address in full, so the dock gets **one finding per class, not one
    per address** -- six hundred dock items would bury the build findings
    the dock exists to keep on screen.

    A clean real apply still says something, because "it landed, here is
    the journal, and here is what reverses it" is exactly what an engineer
    who has just written to a desk wants to read.
    """
    counts = payload["counts"]
    findings = []
    check = payload.get("model_check") or {}
    if check.get("message") and check.get("severity") in ("info", "warning"):
        findings.append(Diagnostic(
            severity=Severity(check["severity"]),
            code=check.get("code") or "apply.desk-model",
            message=check["message"],
            where="Apply", source="apply",
        ).to_dict())
    if counts["mismatch"]:
        addresses = [r["address"] for r in payload["flagged"] if r["status"] == "mismatch"]
        shown = ", ".join(addresses[:5]) + (", …" if len(addresses) > 5 else "")
        findings.append(Diagnostic(
            severity=Severity.ERROR, code="apply.mismatch",
            message=f"{counts['mismatch']} parameter(s) did not land: the console reads "
                    f"back something other than what was written ({shown}).",
            where="Apply", source="apply",
            fix="each one is expanded in the journal below with what was intended and what "
                "the desk reports. Re-running the apply retries only the addresses that "
                "are still wrong.",
        ).to_dict())
    if counts["unreadable"]:
        findings.append(Diagnostic(
            severity=Severity.WARNING, code="apply.unreadable",
            message=f"{counts['unreadable']} address(es) could not be read before writing, "
                    "so they were skipped: a write with no known prior value is a write "
                    "that cannot be reversed.",
            where="Apply", source="apply",
            fix="expanded in the journal below. A desk that answers slowly often reads "
                "clean on a second run.",
        ).to_dict())
    # The journal's own warnings and notes (already grouped, FR-X.15c),
    # which Apply's result panel listed under "Warnings and notes" until
    # an earlier change made the dock the one place findings are read.
    for line in payload.get("warnings") or []:
        text = str(line)
        note = text.startswith("INFO ")
        findings.append(Diagnostic(
            severity=Severity.INFO if note else Severity.WARNING,
            code="apply.journal-note" if note else "apply.journal-warning",
            message=text[5:] if note else text,
            where="Apply", source="apply",
        ).to_dict())
    if not payload["dry_run"] and payload.get("journal_path"):
        findings.append(Diagnostic(
            severity=Severity.INFO, code="apply.journalled",
            message=f"{counts['written']} address(es) written to {address}, each recorded "
                    f"with the value it had before this run in {payload['journal_path']}. "
                    f"`atoo undo {payload['journal_path']}` reverses this run.",
            where="Apply", source="apply",
        ).to_dict())
    return findings


# `--allow-strip`'s own grammar (`cli._valid_strip_label`), checked here
# BEFORE the value goes anywhere near an argv. The command checks it too;
# this copy exists because a value the server splices into a command line
# has to be known to be a strip label first, not merely refused later.
_STRIP_LABEL_RE = re.compile(r"^(ch|aux):[1-9][0-9]{0,2}$")


def _object_base(address: str) -> str:
    """`/ch/21/eq/1/g` -> `/ch/21`; `/io/in/A/5/name` -> `/io/in/A/5`.
    What the withheld set is grouped by on the page: an engineer reads
    "ch 7: 23 addresses left alone", not 600 addresses."""
    parts = address.strip("/").split("/")
    depth = 4 if parts and parts[0] == "io" else 2
    return "/" + "/".join(parts[:depth])


def _withheld_groups(addresses: list) -> list[dict]:
    groups: dict[str, int] = {}
    for address in addresses:
        base = _object_base(str(address))
        groups[base] = groups.get(base, 0) + 1
    return [{"base": base, "count": count} for base, count in groups.items()]


def _patch_findings(review: "dict | None", payload: "dict | None",
                    address: str) -> list[dict]:
    """What one patch puts in the findings dock, on top of the journal's
    own (`_apply_findings`). The review is drawn in full on the screen; the
    dock gets the things that STOP it, and the proof if it failed -- one
    finding per class, never one per strip. A change is refused for reasons
    a rebuild never is -- a reference to something that does not exist --
    and the words say so."""
    findings: list[dict] = []
    where = "Apply · Patch"
    if review is not None:
        blocked = [c for c in review.get("changes", [])
                   if c.get("kind") in ("renumbered", "unplaceable", "refused")]
        if blocked:
            findings.append(Diagnostic(
                severity=Severity.ERROR, code="patch.blocked",
                message="This change is refused, and nothing was written: "
                        + "; ".join(c.get("line", "").strip() for c in blocked),
                where=where, source="patch",
                fix="a change is refused whole when any part of it cannot be written -- an "
                    "object that is not there (a bus, DCA or mute group neither on the desk "
                    "nor added by it, a channel to drop that is not there), a field a "
                    "running object does not carry, or a value out of range. Each line "
                    "above says which; say the change again without it, or add the missing "
                    "object in the same change.",
            ).to_dict())
        # Apply's pre-flight, asked of the change. The refusal is the
        # command's own text; its last line names the socket and the
        # channel on its own, so the dock carries that line and the review
        # panel carries the whole of it.
        preflight = review.get("preflight") or {}
        if preflight.get("refusal"):
            lines = [line for line in preflight["refusal"].splitlines() if line.strip()]
            findings.append(Diagnostic(
                severity=Severity.ERROR,
                code=preflight.get("refusal_code") or "patch.preflight",
                message=lines[-1] if lines else preflight["refusal"],
                where=where, source="patch",
                fix="the review's pre-flight panel lists every socket, or every verify "
                    "error, in full.",
            ).to_dict())
        if review.get("collisions"):
            findings.append(Diagnostic(
                severity=Severity.ERROR, code="patch.collision",
                message=f"{len(review['collisions'])} address(es) in this change's scope are "
                        "also written by the applied plan -- the scope is wrong, so it "
                        "refused rather than writing.",
                where=where, source="patch",
            ).to_dict())
        proof = review.get("proof") or {}
        if proof.get("moved"):
            findings.append(Diagnostic(
                severity=Severity.ERROR, code="patch.moved",
                message=f"{len(proof['moved'])} address(es) belonging to strips this change "
                        "does not own CHANGED across the write -- the failure the untouched-strip "
                        "proof's before/after read exists to catch.",
                where=where, source="patch",
                fix="the run log names each one with its before and after values.",
            ).to_dict())
    if payload is not None:
        findings.extend(_apply_findings(payload, address))
    return findings


def _undo_payload(data: dict, bundle_dir: Path) -> dict:
    """`result.undo`: one undo run, preview or confirmed, as the page draws
    it -- `atoo undo --result-json`'s own data (per-address rows, counts and
    one word for the whole run), plus which journal row it reverses.

    The rows are sent whole: the page sees every address the run decided
    something about, not the last 200 lines of the log."""
    from atoo import journal_stack

    source = str(data.get("source_journal") or "")
    entry = None
    try:
        entry = journal_stack.find(bundle_dir, source) if source else None
    except (journal_stack.JournalStackError, OSError):
        entry = None
    return {
        **data,
        # The row of History this reverses, so the page can say which one
        # and can tell when the stack has moved on from it.
        "journal_id": entry.id if entry is not None else Path(source).name,
        "kind": entry.kind if entry is not None else None,
        "timestamp": entry.timestamp if entry is not None else None,
        "change_label": (journal_stack.change_label(entry.change)
                         if entry is not None and entry.change else None),
    }


def _undo_findings(payload: "dict | None") -> list[dict]:
    """What a confirmed undo that did not put everything back says in the
    findings dock. A preview says all it has to under its own button."""
    if payload is None or payload.get("dry_run"):
        return []
    counts = payload.get("counts") or {}
    outcome = payload.get("outcome")
    if outcome == "did-not-land":
        return [Diagnostic(
            severity=Severity.ERROR, code="undo.did-not-land",
            message=f"{counts.get('did-not-land', 0)} reversal(s) did not land: the desk "
                    "does not read back the value that was sent.",
            where="Apply · History", source="undo",
            fix="the History panel lists each address with the value on the desk now.",
        ).to_dict()]
    if outcome == "partly-undone":
        held = (counts.get("changed-since", 0) + counts.get("unreadable", 0)
                + counts.get("no-earlier-value", 0))
        return [Diagnostic(
            severity=Severity.WARNING, code="undo.partial",
            message=f"The undo put back what it could, and left {held} address(es) as they "
                    "are: changed since the write, unreadable, or with no earlier value "
                    "recorded.",
            where="Apply · History", source="undo",
            fix="the History panel lists each one with the value on the desk now.",
        ).to_dict()]
    return []


def _watch_condition_ids(path: Path) -> set:
    """Every condition id in a watch-conditions file, or the empty set
    when there is no file or it will not read. Only ever used to tell
    which conditions a build just ADDED -- a before/after comparison, so
    an unreadable file simply means "nothing was there to compare"."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(document, dict):
        return set()
    return {c.get("id") for c in document.get("watch_conditions") or [] if isinstance(c, dict)}


def _drafted_watchlist_finding(path: Path, before: set, display: str) -> "dict | None":
    """OPTIONS-H point 3: Build has no watch step, and a bundle build
    DRAFTS `watch.json` -- so the build says so, in the dock, with a
    jump link that opens Watch.

    Worked out from the file rather than from the words `build` printed:
    the conditions marked `"source": "drafted"` that were not in the file
    before this run are the ones it added. None when it added nothing,
    because a finding that says "0 drafted" is noise.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    added = [
        c.get("id") for c in (document.get("watch_conditions") or [])
        if isinstance(c, dict) and c.get("source") == "drafted" and c.get("id") not in before
    ]
    if not added:
        return None
    return Diagnostic(
        severity=Severity.INFO, code="build.watchlist-drafted",
        message=f"{len(added)} condition(s) drafted into {display} ({', '.join(added)}). "
                'They are marked "source": "drafted" and merged, never written over the '
                "top -- nothing watches until you start a watch session.",
        where="watch conditions", source="build",
    ).to_dict()


def _file_sha256(path: Path) -> "str | None":
    """The sha256 of a file's bytes, or None when it cannot be read. What
    `GET /api/apply/preflight` reports as `plan_sha256`, and what a
    confirmed apply's `expected_plan_sha256` is compared against."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _bundle_payload(show: "bundle.Bundle") -> dict:
    """One open show bundle, as the shell page's bundle bar reads it.

    The bar shows the directory's own name (`touringband/`) and **every
    file hint under it is derived from that one value** -- `input.csv`,
    `plan.json` and the rest are fixed names (`atoo.bundle.SLOTS`), never separately
    chosen, which is exactly why version H
    replaced four path inputs with one. So the browser is sent the derived
    paths rather than left to join strings itself: a path the page
    composed and a path the server would open are two chances to disagree
    about a separator.

    `present` is answered per slot, not up front, for `bundle.py`'s own
    reason: `plan.json` is absent until the first build, and that absence
    does not make the directory less of a bundle.
    """
    demo = is_demo_show(show)
    return {
        "directory": str(show.directory),
        "name": DEMO_SHOW_LABEL if demo else (show.directory.name or str(show.directory)),
        # The packaged demo show. The bar reads "(read-only)",
        # and every write endpoint refuses it -- this flag is the page's
        # courtesy, the server's refusals are the guard.
        "demo": demo,
        "read_only": demo,
        "slots": [
            {"slot": slot, "path": str(show.path(slot)), "present": show.has(slot)}
            for slot in bundle.SLOTS
        ],
        "present": list(show.present()),
        "missing": list(show.missing()),
    }


# ----------------------------------------------------------------------
# Build steps 01-03: the three files a build reads (mockup version H,
# phase 2).
#
# `atoo build` reads exactly three texts -- the house conventions
# file, the input list and, if the bundle has one, `instructions.md` --
# and the shell's three tiles are those three files and nothing else.
# Step 04 (running the build) is a later phase; nothing below compiles,
# writes or talks to a console.
# ----------------------------------------------------------------------

# The slot keys the browser uses, in H's 01/02/03 order. `input_list` and
class _RunJournal:
    """Where a run the page starts leaves its journal, and how the page
    finds THIS run's journal afterwards.

    A confirmed run in a bundle writes a new entry into `journals/`, named
    for the desk it reaches -- the command chooses the name once the desk
    has answered, so the page cannot name it in advance (there
    is no fixed top-level `apply-journal.json` any more). So the page
    passes no `--journal`, remembers which entries were there before, and
    afterwards reads the one new entry of this kind. A run the gate
    refused adds no entry, so it draws no result -- which is the false
    proof the old mtime comparison was guarding against, now answered by
    the stack itself.

    A preview names a file in a scratch directory the caller deletes:
    `atoo undo` refuses a dry-run journal, so keeping one would only
    be a file that looks reversible and is not."""

    def __init__(self, show, kind: str, confirmed: bool, scratch: str | None):
        from atoo import journal_stack

        self._stack = journal_stack
        self.show, self.kind, self.confirmed = show, kind, confirmed
        if confirmed:
            self.argv: list[str] = []
            self._before = {e.id for e in journal_stack.entries(show.directory)}
            self._path: Path | None = None
        else:
            self._path = Path(scratch) / f"preview.{kind}-journal.json"
            self.argv = ["--journal", str(self._path)]

    def read(self) -> "tuple[str | None, dict | None]":
        """(the path, the parsed journal) of this run's journal, or
        (None, None) when the run wrote none."""
        path = self._path
        if self.confirmed:
            new = [e for e in self._stack.entries(self.show.directory)
                   if e.id not in self._before and e.kind == self.kind]
            path = new[-1].path if new else None
        if path is None:
            return None, None
        try:
            return str(path), json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, None


# `instructions` are bundle slots (`bundle.INPUT_LIST` / `.INSTRUCTIONS`);
# `conventions` deliberately is NOT -- the house conventions file lives
# OUTSIDE the bundle, which is the whole reason step 01 is
# drawn with a "House" tag and its own path.
_BUILD_SLOTS = ("conventions", "input_list", "instructions")

# The two Build slots that are bundle files, and so the two a file chosen
# from elsewhere is copied INTO the bundle as. The house
# conventions file is not one: it lives outside the bundle by design,
# and its tile's Change file stays a pointer.
_BUILD_SLOT_FILES = {"input_list": bundle.INPUT_LIST, "instructions": bundle.INSTRUCTIONS}

#: Every file `POST /api/bundle/adopt` copies into a bundle: Build's two,
#: and Watch's watch-conditions file (the
#: `watch.json` file always goes with the current bundle, handled
#: consistently with the other files).
_ADOPT_SLOT_FILES = {**_BUILD_SLOT_FILES, "watch": bundle.WATCH_CONDITIONS}


def _a_or_an(filename: str) -> str:
    """ "an input.csv", "a watch.json" -- the article a file's name takes."""
    return "an" if filename[:1].lower() in "aeiou" else "a"


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.expanduser().resolve() == b.expanduser().resolve()
    except (OSError, RuntimeError):
        return False

# The canonical headings, from the artifact-formats reference --
# used ONLY to lay out the example files below. Nothing reads a heading:
# a conventions file is Markdown prose that the model reads whole
# (`generate._conventions_section`), with or without headings, and the
# Setup page edits it as one text (there is no sections view, since the
# section headers aren't really used).
# tests/test_webui.py checks this list against that document.
CANONICAL_CONVENTION_SECTIONS = (
    "Inputs", "Channels", "Processing", "DCAs",
    "Mute Groups", "Busses", "Outputs", "Watch",
)


# ---- Example files: a suggestion beside steps 01 and 03 ------------------
#
# The templated new conventions and instructions files are provided as
# suggestions only. New file creates an EMPTY
# file; this text is shown beside the editor under "Example", and reaches
# a file only when the engineer presses Insert (whole, or the part of it
# he selected) and then Save. No endpoint writes it (the build payload's
# `example` key carries it to the page, read-only).
#
# **Headings and comments, and not one rule.** The build reads everything
# in these files that is NOT inside an HTML comment
# (`conventions_text.strip_comments`), so an example line -- "Drums get a
# high-pass at 80Hz" -- inserted whole would not be an example: it would
# be built into the next show, by someone who never wrote it. So every
# line of the examples that is not a heading is inside a comment saying
# what KIND of statement belongs there. `tests/test_webui.py` strips the
# comments and headings and asserts nothing is left.

# What each canonical heading is FOR -- a description, never an example.
# The wording is fixed, verbatim: the examples carry it as
# the comment under each heading.
CONVENTION_SECTION_NOTES = {
    "Inputs": "Describe the input categories, input patching order, color coding, "
              "and gain/phantom defaults.",
    "Channels": "Channel strip ordering, stereo/mono patching, colors, which inputs "
                "go on an aux channel.",
    "Processing": "Default channel strip processing including filtering, EQ, named "
                  "presets, starting fader and mute.",
    "DCAs": "Name the DCAs and what will be controlled by each.",
    "Mute Groups": "Name the mute groups, and what is controlled by each.",
    "Busses": "Describe the mix, monitor, and FX busses: who sends to each, send mode "
              "and level, mono or stereo, and where each one is sent.",
    "Outputs": "Describe all outputs from the desk, main, matrices and physical "
               "output sockets.",
    "Watch": "Alerts to be generated.",
}

_CONVENTIONS_PREAMBLE = """<!--
Your house conventions: what you always do with whatever is plugged in,
in plain English, reused for every show. Everything outside these
comment markers is read as your conventions when a plan is built.

Comments like this one are NOT read by the build -- it strips them
before anything sees the file. Use them for notes to yourself: a
reminder, a reason, a rule you have switched off for now. The ones
below only describe what belongs under each heading.

The headings are a suggestion for keeping the file readable. The build
reads the whole file as one text, with or without them; keep the ones
you use and delete the rest.
-->"""

_INSTRUCTIONS_PREAMBLE = """<!--
How THIS show differs from your house conventions. Only what differs
belongs here: where this file is silent, the house conventions apply in
full, and where the two disagree, this file wins.

Comments like this one are NOT read by the build, so they are the place
for notes to yourself about this show. The headings below are the ones
the example house conventions use; the build reads this file as one text,
with or without them. Keep only what you need.
-->"""


def _example(title: str, preamble: str) -> str:
    parts = [f"# {title}", "", preamble, ""]
    for name in CANONICAL_CONVENTION_SECTIONS:
        parts += [f"## {name}", f"<!-- {CONVENTION_SECTION_NOTES[name]} -->", ""]
    return "\n".join(parts)


def conventions_example(filename: str) -> str:
    """The example house conventions file step 01 offers beside its
    editor, titled ``filename``: a comment saying what the file is, and
    the canonical eight headings with a one-line comment each. No rules.
    A suggestion only -- nothing writes it to disk."""
    return _example(filename, _CONVENTIONS_PREAMBLE)


def instructions_example(show_name: str) -> str:
    """The example ``instructions.md`` step 03 offers beside its editor
    for the show bundle ``show_name``: the same headings as
    `conventions_example`, and a comment saying that only what differs
    belongs here. No rules. A suggestion only -- nothing writes it."""
    return _example(f"{bundle.INSTRUCTIONS} -- {show_name}", _INSTRUCTIONS_PREAMBLE)


# The file name step 01's "New file" offers: `artifact-formats.md` §2's
# `atoo-rules-<description>.md`, in the home directory, where a house
# file reused across shows belongs (not in any one bundle).
DEFAULT_NEW_CONVENTIONS = "~/atoo-rules-house.md"


def _new_conventions_suggestion() -> str:
    """`DEFAULT_NEW_CONVENTIONS`, or `~/atoo-rules-house-2.md` and so
    on when that is taken -- a suggestion that New file would refuse is
    not a suggestion. The refusal still stands if one appears meanwhile."""
    stem = DEFAULT_NEW_CONVENTIONS[:-len(".md")]
    for n in range(1, 100):
        candidate = DEFAULT_NEW_CONVENTIONS if n == 1 else f"{stem}-{n}.md"
        if not config.expand_home(candidate).exists():
            return candidate
    return DEFAULT_NEW_CONVENTIONS


def _display_path(path: Path, show: "bundle.Bundle | None") -> str:
    """The path as version H writes it on a tile: `touringband/input.csv`
    for a file in the open bundle, `~/house-rules.md` for one under the
    home directory, and the plain path for anything else.

    Short on purpose -- the tile is narrow and the folder was chosen once,
    in the bundle bar. The absolute path travels alongside as `path` and
    the page puts it on the element's `title`, so nothing is hidden.

    A file of the packaged demo is `Demo show/input.csv`, not the path into
    the installed package: the demo's conventions file sits
    beside its show folder, and both are the demo's.
    """
    if _inside_demo(path):
        try:
            resolved = Path(path).resolve()
            root = (DEMO_SHOW_DIR if DEMO_SHOW_DIR.resolve() in resolved.parents
                    else DEMO_ROOT).resolve()
            return f"{DEMO_SHOW_LABEL}/{resolved.relative_to(root).as_posix()}"
        except (OSError, ValueError):
            pass
    if show is not None:
        try:
            return f"{show.directory.name or show.directory}/{path.relative_to(show.directory)}"
        except ValueError:
            pass
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _read_text_source(path: "Path | None") -> tuple[str | None, str | None]:
    """A text file for one of the three tiles: (text, error message).

    `(None, None)` means "there is nothing at that path", which is an
    ordinary state a tile draws as **Missing** -- not an error. A path
    that is there but cannot be read comes back with a message the caller
    turns into a finding.
    """
    if path is None or not path.is_file():
        return None, None
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, f"couldn't read {path}: {exc.strerror}"
    except UnicodeDecodeError as exc:
        return None, f"{path} is not text this can read: {exc}"


def _raw_text(path: "Path | None") -> "str | None":
    """A file's text exactly as its bytes say -- no newline translation,
    unlike `Path.read_text`, which reads ``\\r\\n`` as ``\\n``. What a Save
    splices into, so a CRLF file stays CRLF. None when unreadable."""
    if path is None:
        return None
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _input_list_payload(path: "Path | None", text: str | None,
                        show: "bundle.Bundle | None" = None) -> tuple[list[dict] | None, "Diagnostic | None"]:
    """The input list's rows, or the one finding that says why not.

    `atoo.input_list.parse_input_list` does every bit of the
    reading -- the required columns, the forbidden ones, the boolean
    spellings, the row/column a failure is in. A second CSV reader here
    would be a second opinion about what a valid input list is, and the
    two would drift the first time FR-1.1 moved.

    A file that will not parse is a **finding, not an exception**: the
    page still draws its tile, the dock says what is wrong and where, and
    the operator fixes the row. `InputListError` already names the row
    and column, so the message is passed through rather than reworded.

    Its `where` is the file as the tile names it (`fest/input.csv`), not
    the absolute path: a finding is what a user
    pastes when asking for help, and the home folder is not its business.
    """
    from atoo.input_list import CANONICAL_COLUMNS, InputListError, parse_input_list

    if text is None:  # nothing at that path -- an ordinary "Missing" tile
        return None, None
    try:
        # Every row, the skipped ones too (`-` in `order`): the editor shows
        # and saves the whole file, and a skipped row is dimmed, not hidden.
        rows = parse_input_list(text, include_skipped=True)
    except InputListError as exc:
        return None, Diagnostic(
            severity=Severity.ERROR,
            code="input-list.invalid",
            message=str(exc),
            where=_display_path(path, show) if path else "input list",
            fix="correct the row this names, then press Reload on the Input list tile",
            source="build",
        )
    return [
        {column: getattr(row, column) for column in CANONICAL_COLUMNS}
        for row in rows
    ], None


def _resolved_conventions_status(path: Path, text: str):
    """Step 01's word on the resolved conventions beside this file
    (`conventions_resolve.py`, 2026-09-30): `({path, display_path, state,
    reason}, an INFO finding)` when there is a resolved file, None when
    there is none (the next build makes it, and says so) or it cannot be
    judged. "fresh" means the next build reads it in place of the
    conventions and the domain knowledge; "stale" that it resolves again
    first, with one model call."""
    from atoo import conventions_resolve, generate

    try:
        state = conventions_resolve.freshness(path, text)
    except (generate.PromptError, OSError):
        return None
    if state.state == "missing":
        return None
    off = "" if conventions_resolve.enabled() else (
        f" Resolving is off here ({conventions_resolve.RESOLVE_ENV}=0), so a build reads the "
        "raw conventions.")
    if state.fresh:
        message = (f"Resolved conventions: {state.path.name} is fresh -- a build reads it in "
                   f"place of this file and the domain knowledge.{off}")
    else:
        message = (f"Resolved conventions: {state.path.name} is {state.state} "
                   f"({state.reason}) -- the next build resolves again first, with one extra "
                   f"model call.{off}")
    return ({"path": str(state.path), "display_path": state.path.name, "state": state.state,
             "reason": state.reason},
            Diagnostic(severity=Severity.INFO, code="build.resolved-conventions",
                       message=message, where="conventions", source="build",
                       fix=f"read {state.path.name} beside this file; `atoo resolve` "
                           "makes it again"))


def _build_source_payload(
    slot: str, *, path: "Path | None", origin: str, show: "bundle.Bundle | None",
) -> dict:
    """One Build tile (01 Conventions, 02 Input list, 03 Instructions):
    where its file is, whether it is there, what is in it, and whatever
    findings reading it produced.

    `state` is H's badge vocabulary and is answered here for two of its
    three values -- `loaded` and `missing`. The third, **stale**, is the
    browser's to decide and cannot be answered from one request: it means
    "this file changed on disk after the page read it", which is a
    comparison between two reads. `mtime`/`size` travel in every payload
    so the page can make it.

    **A file that is simply not there yet is a to-do, not a finding**
    (2026-10-02: a new show's dock filling with
    errors is premature). Such a slot carries `todo`, one
    line the tile shows beside its Change file / New file buttons, and --
    for the two files a build cannot run without -- `missing`, the ERROR
    `POST /api/build/run` refuses with when Build is pressed. Neither is
    in `findings`, so neither reaches the dock on open or create. A file
    that IS there and is wrong (unreadable, a CSV the loader refuses)
    stays a finding, exactly as before.
    """
    findings: list[Diagnostic] = []
    missing: "Diagnostic | None" = None
    todo: "str | None" = None
    text, read_error = _read_text_source(path)
    present = text is not None

    if path is None:
        state = "notset"
    elif present:
        state = "loaded"
    else:
        state = "missing"

    payload: dict = {
        "slot": slot,
        "path": str(path) if path else None,
        "display_path": _display_path(path, show) if path else None,
        "origin": origin,
        "state": state,
        "present": present,
        "text": text,
        "mtime": path.stat().st_mtime if present and path else None,
        "size": path.stat().st_size if present and path else None,
        # The bytes the page was shown. A Save sends it
        # back as `expected_sha256`, and is refused (409) when the file on
        # disk no longer hashes to it -- an edit made in another editor
        # since the page read the file is never written over.
        "sha256": _file_sha256(path) if present and path else None,
    }

    if read_error is not None:
        # There IS a file and it could not be read -- a different state
        # from "there is no file", and the only one of the two that is
        # somebody's mistake rather than an ordinary empty slot.
        findings.append(Diagnostic(
            severity=Severity.ERROR, code=f"build.{slot.replace('_', '-')}-unreadable",
            message=read_error, where=str(path), source="build",
            fix="check the file's permissions and that it is text, not a binary",
        ))

    if slot in ("conventions", "instructions") and text is not None:
        # The file as written, cut into read and comment runs (step 03's
        # "View house file" marks each comment as not read); and what
        # reading its comments found -- an `<!--` that
        # never closes is read as written, and says so here, in the same
        # words `atoo build` prints.
        payload["text_segments"] = [seg.to_dict() for seg in conventions_text.segments(text)]
        findings.extend(conventions_text.comment_findings(text, path.name))

    if slot == "conventions":
        if path is None:
            todo = "No house conventions file yet: New file, or Change file to use one."
            missing = (Diagnostic(
                severity=Severity.ERROR, code="build.no-conventions",
                message="No house conventions file. It is your standing house style, "
                        "reused across every show, so it lives outside the show bundle "
                        "-- a build cannot run without one.",
                where="conventions",
                fix="press New file on this tile to start an empty one, or Change file to "
                    f"use one you have; or name one in "
                    f"{config.config_path()}'s [conventions] section",
                source="build",
            ))
        elif not present and read_error is None:
            todo = (f"{path.name} is not there. Change file, New file, or correct "
                    f"{_display_path(config.config_path(), None)}.")
            missing = (Diagnostic(
                severity=Severity.ERROR, code="build.conventions-missing",
                message=f"No file at {path} -- the house conventions file named in "
                        f"{config.config_path()}'s [conventions] section is not there.",
                where=str(path),
                fix="correct the path in that config file, press Change file on this tile, "
                    "or New file to start an empty one",
                source="build",
            ))
        elif present:
            resolved = _resolved_conventions_status(path, text)
            if resolved is not None:
                payload["resolved"], finding = resolved
                findings.append(finding)

    elif slot == "input_list":
        rows, row_finding = _input_list_payload(path, text, show)
        payload["rows"] = rows
        payload["columns"] = list(input_list_module.CANONICAL_COLUMNS)
        # Step 02's editor reads the file leniently: every
        # record as written, by the header's own column names, with its
        # position in the file -- so a list the loader refuses can still
        # be shown and the row the finding names can be fixed on the
        # page. `rows` above stays the engine's validated reading.
        if text is not None:
            header, records, _end = source_edit.read_records(_raw_text(path) or text)
            payload["header"] = header
            # `patch_key` ("A 4", or None when the cell does not parse):
            # what step 04 joins a row to a plan channel by -- the same key
            # `_channel_display` gives each channel's patch. `socket_key`
            # .
            #
            # `values` always calls the patch column `patch`, whatever the
            # file's header says (`socket` in a list written before the rename):
            # the page knows one name, and a Save maps it back onto the
            # header the file has (`source_edit.splice_input_list`), so
            # the header is never rewritten. `header` stays as written.
            column = input_list_module.patch_column(header)
            payload["records"] = [
                {"line": i, "values": _patch_values(record.values, column),
                 "patch_key": _patch_key(record.values.get(column))}
                for i, record in enumerate(records)
            ]
        else:
            payload["header"], payload["records"] = [], []
        if row_finding is not None:
            findings.append(row_finding)
        if not present and read_error is None:
            todo = ("No input list yet: Change file copies one into the show."
                    if path else "Open or create a show first.")
            missing = (Diagnostic(
                severity=Severity.ERROR, code="build.input-list-missing",
                message=(f"No {bundle.INPUT_LIST} at {_display_path(path, show)}."
                         if path else "No show bundle open, so there is no input list.")
                + " It is the one file a build cannot do without: it is what is plugged in.",
                where=_display_path(path, show) if path else "input list",
                fix="open a bundle that has one, or press Change file on this tile",
                source="build",
            ))

    elif slot == "instructions":
        if not present and read_error is None:
            # Optional, and so not a finding at all: the
            # `build.no-instructions` INFO this was until 2026-10-02 said
            # the same thing to the dock on every new show. No per-show
            # text means the house conventions apply in full; the tile
            # says so, quietly.
            todo = ("Optional. Without one, the house conventions apply in full."
                    if path else "Open or create a show first.")

    payload["findings"] = [f.to_dict() for f in findings]
    payload["todo"] = todo
    payload["missing"] = missing.to_dict() if missing is not None else None
    return payload


def _read_bundle_plan(show: "bundle.Bundle | None") -> dict | None:
    """The open bundle's `plan.json`, parsed, or None.

    Read here only for the conventions file it records. A plan
    that will not parse is not this function's to report -- step 04 and
    the plan loader already say so -- so it reads as "no record" and the
    tile falls back to the config default exactly as before.
    """
    if show is None:
        return None
    path = show.optional(bundle.PLAN)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _recorded_conventions_findings(
    recorded: dict, recorded_path: "Path | None", how: "str | None", *,
    shown: "Path | None", from_plan: bool, config_conventions: "Path | None",
    plan_display: str, show: "bundle.Bundle",
) -> list[Diagnostic]:
    """Every way the conventions file on the tile differs from the one the
    bundle's plan records. An inferred value that
    does not announce itself is the defect, so each fallback says so.

    * **recorded file gone** -- WARNING. The tile falls back (to the
      config default, or to a typed path), and the plan can no longer be
      rebuilt as built: what is on screen is not what made it.
    * **found only by its absolute path** -- INFO. The bundle moved and
      the house file did not; the right file is shown, but the recorded
      relative path is now wrong and the next build rewrites it.
    * **edited since the build** (sha256 differs) -- INFO, not WARNING.
      It is the same file, and editing the house file is the ordinary
      way an engineer changes a show: the tile shows what the next build
      will use, and nothing about the desk is wrong. Worth knowing --
      the plan on disk no longer follows from the text on screen -- but
      not worth a WARNING on every show after every conventions tweak.
    * **plan's file differs from the config's** -- INFO naming both, so
      nobody reads the tile believing it is today's house default.
    * **a typed path differs from the plan's file** -- INFO, the same
      disagreement from the other side.
    """
    findings: list[Diagnostic] = []
    recorded_name = (recorded.get("bundle_relative_path")
                     or recorded.get("absolute_path") or recorded.get("path"))
    if recorded_path is None:
        instead = (f"showing {_display_path(shown, show)} instead" if shown is not None
                   else "and there is no other conventions file to show")
        findings.append(Diagnostic(
            severity=Severity.WARNING, code="build.recorded-conventions-missing",
            message=(f"{plan_display} was built from {recorded_name}"
                     + (f" ({recorded.get('absolute_path')})"
                        if recorded.get("absolute_path") not in (None, recorded_name) else "")
                     + f", which is no longer there -- {instead}. This plan cannot be "
                       "rebuilt as it was built."),
            where="conventions",
            fix="put the file back where the plan says it was, or press Change file on "
                "this tile; the next build records whichever file it uses",
            source="build",
        ))
        return findings

    if how == "absolute":
        findings.append(Diagnostic(
            severity=Severity.INFO, code="build.recorded-conventions-moved",
            message=(f"{plan_display} records its conventions file as "
                     f"{recorded.get('bundle_relative_path')} relative to the bundle, which "
                     f"is not there; found it at its recorded absolute path {recorded_path} "
                     "instead. The bundle has probably moved without it."),
            where="conventions",
            fix="nothing to do if this is the right file -- the next build records the "
                "path relative to where the bundle is now",
            source="build",
        ))

    recorded_hash = recorded.get("sha256")
    if recorded_hash and conventions_ref.same_file(shown, recorded_path):
        current = conventions_ref.file_sha256(recorded_path)
        if current is not None and current != recorded_hash:
            findings.append(Diagnostic(
                severity=Severity.INFO, code="build.recorded-conventions-edited",
                message=(f"{recorded_path.name} has been edited since {plan_display} was "
                         "built from it. This tile shows the file as it is now, which is "
                         "what the next build will use -- not the text that produced the "
                         "plan on disk."),
                where=str(recorded_path),
                fix="rebuild (step 04) if the edit should reach this show",
                source="build",
            ))

    if from_plan and config_conventions is not None \
            and not conventions_ref.same_file(recorded_path, config_conventions):
        findings.append(Diagnostic(
            severity=Severity.INFO, code="build.conventions-from-plan",
            message=(f"Showing {_display_path(recorded_path, show)}, the conventions file "
                     f"{plan_display} was built from -- not "
                     f"{_display_path(config_conventions, None)}, which "
                     f"{_display_path(config.config_path(), None)} names as the house "
                     "default. A build from this page uses the file shown."),
            where="conventions",
            fix="press Change file on this tile to build this show against the config's "
                "file instead",
            source="build",
        ))
    elif not from_plan and shown is not None \
            and not conventions_ref.same_file(shown, recorded_path):
        findings.append(Diagnostic(
            severity=Severity.INFO, code="build.conventions-not-plan",
            message=(f"Showing {shown}, typed into this tile -- not "
                     f"{_display_path(recorded_path, show)}, the conventions file "
                     f"{plan_display} was built from."),
            where="conventions",
            fix=f"to build against the plan's file, press Change file and give it "
                f"{recorded_path} -- a typed conventions path lasts the session, across "
                "bundles, because the house file is the same for every show",
            source="build",
        ))
    return findings


def _build_payload(
    show: "bundle.Bundle | None", conventions_path: "str | None", overrides: dict,
) -> dict:
    """Build steps 01-03, whole: three tiles, the conventions stack and
    every finding reading those three files produced.

    One payload rather than three endpoints because it is one screen's
    worth of state and the three files are small -- and because the
    conventions stack is a fact about *two* of them at once, so a page
    that fetched them separately would have to recombine them.

    `stack` is `meta.conventions_stack`'s shape, key for key
    (`cli.build_cmd`): `{path, role, source}`, worst precedence first.
    Same list, same order, same words -- so what the page shows and what
    a built plan records cannot disagree. Each entry also carries
    `conventions_ref.layer_record`'s `absolute_path`,
    `bundle_relative_path` and `sha256`, as a plan built since an earlier change does.

    **Which conventions file step 01 shows.** A path typed into
    the tile's Change file box wins; then the file the bundle's
    `plan.json` records at `meta.conventions_stack` (resolved relative to
    the bundle, then by its absolute path); then the config default. So
    a bundle built against `house-A.md` opens showing `house-A.md`, not
    whatever the config names today -- and a Run from the page rebuilds
    against it. Every fallback and disagreement is a finding on the tile
    (`_recorded_conventions_findings`); a plan from before an earlier change records
    no resolvable path and opens exactly as it always did.
    """
    # The demo show reads its own packaged house conventions,
    # never the user's -- `~/.atoo.config` plays no part, and nothing
    # can be overridden (every tile is read-only).
    demo = is_demo_show(show)
    if demo:
        conventions_path = str(DEMO_CONVENTIONS)
        overrides = {slot: None for slot in _BUILD_SLOTS}
    # Where each tile's file is, in the order `cli.build_cmd` resolves
    # them. An override is a path the operator typed into a tile's
    # "Change file" box and it wins, exactly as `--conventions` wins over
    # the config default on the command line.
    config_conventions = Path(conventions_path).expanduser() if conventions_path else None
    bundle_plan = _read_bundle_plan(show) if show else None
    recorded = conventions_ref.recorded_conventions(bundle_plan) if show else None
    recorded_path, recorded_how = (
        conventions_ref.resolve_recorded(recorded, show.directory) if recorded else (None, None)
    )
    if overrides.get("conventions"):
        conventions = Path(overrides["conventions"]).expanduser()
    elif recorded_path is not None:
        conventions = recorded_path
    else:
        conventions = config_conventions
    from_plan = not overrides.get("conventions") and recorded_path is not None
    input_list = Path(overrides["input_list"]) if overrides.get("input_list") \
        else (show.path(bundle.INPUT_LIST) if show else None)
    instructions = Path(overrides["instructions"]) if overrides.get("instructions") \
        else (show.path(bundle.INSTRUCTIONS) if show else None)

    plan_display = f"{show.directory.name or show.directory}/{bundle.PLAN}" if show else None
    if overrides.get("conventions"):
        conventions_origin, conventions_display_origin = "loaded here", "loaded here"
    elif from_plan:
        conventions_origin = f"recorded in {show.plan}"
        conventions_display_origin = f"recorded in {plan_display}"
    else:
        conventions_origin = f"{config.config_path()} [conventions]"
        conventions_display_origin = f"{_display_path(config.config_path(), None)} [conventions]"
    if demo:
        conventions = DEMO_CONVENTIONS
        conventions_origin = conventions_display_origin = \
            "the demo show's own house conventions (packaged, read-only)"
    bundle_origin = f"show bundle {show.directory}" if show else "no show bundle open"

    sources = {
        "conventions": _build_source_payload(
            "conventions", path=conventions, origin=conventions_origin, show=show),
        "input_list": _build_source_payload(
            "input_list", path=input_list,
            origin="loaded here" if overrides.get("input_list") else bundle_origin, show=show),
    }
    sources["conventions"]["display_origin"] = conventions_display_origin
    if recorded is not None and not demo:
        extra = _recorded_conventions_findings(
            recorded, recorded_path, recorded_how, shown=conventions, from_plan=from_plan,
            config_conventions=config_conventions, plan_display=plan_display, show=show,
        )
        sources["conventions"]["findings"].extend(f.to_dict() for f in extra)
    sources["instructions"] = _build_source_payload(
        "instructions", path=instructions,
        origin="loaded here" if overrides.get("instructions") else bundle_origin,
        show=show)

    # `path`, `role` and `source` are `meta.conventions_stack`'s three keys
    # and carry exactly what `cli.build_cmd` would write. `display_*` are
    # UI-only additions alongside them, never instead of them: a tile is
    # narrow and an absolute path under a long home directory wraps to
    # three lines, so the page shows the short form and keeps the real one
    # on the element's title.
    stack = []
    if conventions is not None:
        stack.append({
            "path": str(conventions), "role": "conventions",
            "source": conventions_origin,
            **conventions_ref.layer_record(conventions, show.directory if show else None),
            "display_path": _display_path(conventions, show),
            "display_source": conventions_display_origin,
        })
    if sources["instructions"]["present"]:
        stack.append({
            "path": str(instructions), "role": "instructions",
            "source": sources["instructions"]["origin"],
            **conventions_ref.layer_record(instructions, show.directory if show else None),
            "display_path": sources["instructions"]["display_path"],
            "display_source": "loaded here" if overrides.get("instructions")
            else f"show bundle {show.directory.name or show.directory}",
        })

    # What ~/.atoo.config says right now, read fresh -- for step 01's
    # "New file" row, which offers to make the new file the default and
    # has to say what that would replace BEFORE anyone ticks the box.
    configured = config.conventions_default_setting()
    config_info = {
        "path": str(config.config_path()),
        "display_path": _display_path(config.config_path(), None),
        "exists": config.config_path().is_file(),
        "conventions_default": configured,
        "new_conventions_suggestion": _new_conventions_suggestion(),
    }

    # Is the bundle's plan.json still what these three files
    # would build? By content -- the sha256s the plan recorded against the
    # files as they are now (`plan_freshness`). The plan tile, the status
    # line and the Rebuild button are drawn from this; a plan too old to
    # have recorded a file is "unknown", never "stale".
    freshness = plan_freshness.assess(
        bundle_plan, conventions=conventions, instructions=instructions,
        input_list=input_list, display=lambda p: _display_path(p, show))
    freshness["plan_path"] = str(show.plan) if show and bundle_plan is not None else None

    return {
        **sources,
        "slots": list(_BUILD_SLOTS),
        # The demo show -- every tile read-only, Build refused.
        "read_only": demo,
        "stack": stack,
        "plan_freshness": freshness,
        # The example text steps 01 and 03 show beside their editors
        # ("templates as suggestions only"). Read-only:
        # it reaches a file only when the engineer presses Insert and then
        # Save, and no endpoint writes it (`conventions_example`).
        "examples": {
            "conventions": conventions_example(
                conventions.name if conventions is not None
                else Path(DEFAULT_NEW_CONVENTIONS).name),
            "instructions": instructions_example(
                (show.directory.name or str(show.directory)) if show else "this show"),
        },
        "config": config_info,
        "findings": [
            finding
            for slot in _BUILD_SLOTS
            for finding in sources[slot]["findings"]
        ],
    }


def _load_watch_conditions_from_path(path: str) -> tuple[list[dict] | None, str | None]:
    """A watch-conditions JSON file (FR-6.5), validated via
    `atoo.watch_conditions.load_watch_conditions` -- returns
    (conditions, None) on success, or (None, message) on failure. Same
    OSError/WatchConditionsError split as `cli.py`'s own
    `_load_watch_conditions_file`, but returns the message instead of
    printing to stderr -- this is reached from a browser request (`GET /api/watch-conditions`'s startup path, `POST
    /api/watch-conditions/load`, `POST /api/watch/start`), never a CLI
    failure path. The single place this module validates a
    watch-conditions path, reused by all three call sites above rather
    than duplicated per endpoint."""
    from atoo.watch_conditions import WatchConditionsError, load_watch_conditions

    try:
        return load_watch_conditions(path), None
    except WatchConditionsError as exc:
        return None, str(exc)
    except OSError as exc:
        return None, f"couldn't read watch-conditions file {path!r}: {exc.strerror}"


def _bundle_watch_conditions(show: "bundle.Bundle") -> "tuple[list[dict] | None, str | None]":
    """The open bundle's `watch.json`, loaded and validated, as
    `(conditions, path)` -- or `(None, None)` when the bundle has none or
    it will not load. What `atoo ui --show` puts in Watch's rules
    editor at startup (`cli._fill_from_bundle`), and so what opening a
    different bundle from the page puts there too: the rules
    on screen are the open show's, the same way step 04's plan is."""
    if not show.has(bundle.WATCH_CONDITIONS):
        return None, None
    path = str(show.path(bundle.WATCH_CONDITIONS))
    conditions, _error = _load_watch_conditions_from_path(path)
    return (conditions, path) if conditions is not None else (None, None)


def _reload_drafted_watch_conditions(state, watch_path: Path) -> None:
    """After a bundle build: re-read the watchlist it may have drafted into, if that file is the one Watch's editor has loaded -- or
    if the editor has none loaded, which is how a show's FIRST drafted
    watchlist reaches it.

    Without this the server kept serving the file as it was before the
    build, and on one page that is a trap rather than a
    staleness: the editor shows the old rows, a Save writes them back,
    and every condition the build just drafted is gone -- with its id
    still in the file's `drafted` list, so the next build does not
    re-propose it either. A watch-conditions file the operator pointed
    the editor at by hand, somewhere else, is left alone."""
    current = state.watch_conditions_path
    if current is not None and Path(current).resolve() != watch_path.resolve():
        return
    conditions, _error = _load_watch_conditions_from_path(str(watch_path))
    if conditions is not None:
        state.watch_conditions, state.watch_conditions_path = conditions, str(watch_path)


# Each entry is a self-contained "issue": a handful of address overrides
# that, applied on top of the clean base rig, trip exactly the audit
# finding(s) named in the comment -- nothing else. Verified independently
# (every issue alone, and all of them at once) to produce exactly its
# named finding(s) with no incidental side effects, so `demo_provider_factory`
# can activate any subset in any combination with no interaction between
# them. One is Severity.ERROR (main_not_patched), so the demo shows the
# full severity range and not just warning/info -- matrix_orphan was the
# second until R003 became a WARNING
# (2026-09-23).
_DEMO_ISSUES: dict[str, dict[str, object]] = {
    # C001 Phantom Power On Unpatched Socket (warning) -- LCL 9, which
    # nothing in the Demo show uses.
    "phantom_unpatched": {"/io/in/LCL/9/vph": 1},
    # L001 Send On But Near-Silent (warning) -- Snare's send to Drums.
    "near_silent_send": {"/ch/2/send/5/lvl": -105.0},
    # L002 Active Strip Fader At Floor (info) -- the Drums mix bus (bus
    # 5), which also trips the show's own `mix-bus-fader-low` watch
    # condition. Not a channel: the Demo's conventions start every channel
    # fader at the floor, so the clean rig already has them there.
    "fader_at_floor": {"/bus/5/fdr": -144.0},
    # N001 Duplicate Channel/Aux Names (warning) -- BV Keys renamed to
    # the other backing vocal's name.
    "duplicate_names": {"/ch/12/name": "BV Gtr"},
    # C002 Shared Physical Input (info) -- Gtr 2 repatched onto Gtr 1's
    # socket, AES50-A 8.
    "shared_input": {"/ch/8/in/conn/in": 8},
    # CH001 Channel Not In Any DCA, x2 (info) -- the backing vocals drop
    # out of the Vocals DCA and keep their Vocals mute group. The Band DCA's
    # members (ch 6-9) are never touched, so `dca_closed` below always has
    # something to complain about.
    "dca_membership_dropped": {"/ch/11/tags": "#M2", "/ch/12/tags": "#M2"},
    # CH002 DCA Fader Low With Active Members (warning) -- the Band DCA,
    # which also trips the show's own `band-dca-open` watch condition.
    "dca_closed": {"/dca/2/fdr": -144.0},
    # CH003 Mute Group Active, Silencing Routed Members (info) -- the
    # Band mute group pressed with the band on stage.
    "mute_group_active": {"/mgrp/1/mute": 1},
    # The show's own `lead-vox-unmuted` watch condition (error) -- Lead Vox
    # (ch 10) muted. No built-in rule calls a muted channel a fault; the
    # show's watch.json does, which is the point of having one, and so
    # (at WARNING) does CV017, Muted Against Plan, which
    # Watch adds from the Demo show's plan.
    "lead_vox_muted": {"/ch/10/mute": 1},
    # R001 Bus No Inputs + R002 Bus No Output (warning x2) -- a new,
    # named bus with nothing patched to or from it (the show uses 1-7).
    "orphan_bus": {"/bus/8/name": "FX", "/bus/8/fdr": 0.0, "/bus/8/mute": 0},
    # R005 Main Not Patched (error), plus R002 Bus No Output (warning)
    # for each of the three busses that feed it -- Main 1 keeps its active
    # routes (bus/5-7/main/1/on, in the base rig) but loses both of its
    # physical output sockets (LCL 1 and 2, the Demo show's PA).
    "main_not_patched": {"/io/out/LCL/1/grp": None, "/io/out/LCL/2/grp": None},
    # R003 Matrix Orphan (warning) -- a physical output patched from a
    # Matrix with no channel/bus ever sending to it.
    "matrix_orphan": {"/io/out/LCL/3/grp": "MTX", "/io/out/LCL/3/in": 1},
    # CV015 FX Bus Effect Contradicts Plan (warning) -- the
    # Vox Verb bus's insert switched off, so its V-REV is bypassed. Watch
    # adds the rule from the Demo show's plan; E003 says it at INFO too.
    "vox_verb_bypassed": {"/bus/7/preins/on": 0},
}


#: The Demo's simulated clips: which strips (all in the Demo
#: rig), how often a read brings one, and what its status note says.
DEMO_CLIP_STRIPS = ("/ch/10", "/ch/1", "/bus/5", "/bus/6", "/main/1")
DEMO_CLIP_CHANCE = 0.2
DEMO_CLIP_STATUS = ClipStatus(
    True, "simulated",
    "The Demo has no console to listen to, so it simulates an occasional clip on one strip. "
    "A strip that clips again inside the minute restarts its timer, as it would on a desk.")


def demo_provider_factory(rng: Optional[random.Random] = None) -> tuple[StateProvider, None]:
    """A live-feeling demo over the bundled `before.json` rig: each read,
    randomly arms or clears one `_DEMO_ISSUES` entry against a running
    `active` set, rather than replaying two fixed frames forever (which is
    what used to dump every finding at once and then repeat the identical
    dump/clear on every single interval, indefinitely). `active` is a set
    keyed by issue name, so nothing can appear twice, and it can never hold
    more than `len(_DEMO_ISSUES)` entries -- bounded by construction, not
    by convention.

    `rng` is injectable so a test can seed it; real callers (this module's
    own `/api/watch/start`) leave it out and get real randomness -- unless
    `ATOO_DEMO_SEED` is set, which makes the faults the same run after
    run, so a screenshot script can retake a shot of Watch running
    and get the same picture.
    """
    if rng is None:
        seed = os.environ.get("ATOO_DEMO_SEED")
        rng = random.Random(seed) if seed else random.Random()
    base = _load_demo_base()
    names = list(_DEMO_ISSUES)
    active: set[str] = set()
    first_call = True
    # The Demo has no meters, so it simulates an occasional clip
    # on one of a few strips, through the same tracker a live watch uses --
    # a clip that clips again inside the minute restarts its timer, which
    # the finding's sentence shows. Its own random stream, so the Demo's
    # faults above come in the same order as ever for a given seed.
    seed = os.environ.get("ATOO_DEMO_SEED")
    clip_rng = random.Random(f"{seed}-clips") if seed else random.Random()
    clip_tracker = ClipTracker()

    def provider() -> ConsoleState:
        nonlocal first_call
        # The very first read is `watch()`'s baseline (iteration 0, not
        # alerted on) -- leave `active` empty for it so the demo always
        # starts from the same clean, legible "nothing wrong yet" rig
        # `before.json` itself represents, exactly like a real console
        # before an operator has touched anything.
        first_call_was = first_call
        if not first_call and rng.random() < 0.6:
            name = rng.choice(names)
            active.symmetric_difference_update({name})
        first_call = False

        if not first_call_was and clip_rng.random() < DEMO_CLIP_CHANCE:
            clip_tracker.observe(time.monotonic(), {clip_rng.choice(DEMO_CLIP_STRIPS)})
        values = dict(base)
        for name in active:
            values.update(_DEMO_ISSUES[name])
        return ConsoleState(values, clips=clip_tracker.snapshot(time.monotonic()),
                            clip_status=DEMO_CLIP_STATUS)

    return provider, None


class ConsoleUnreachable(Exception):
    """Raised by `console_provider_factory` when the initial identity
    check gets no reply -- mirrors `atoo.cli._open_console`'s own
    check, so a bad IP fails immediately with a clear reason rather than
    surfacing as a silent, permanently-empty watch loop."""


def console_provider_factory(
    ip: str,
    *,
    port: int = 2223,
    timeout: float = 1.0,
    read_kwargs: dict | None = None,
    start_name_addresses: list[str] | None = None,
    name_refresh: int = 1,
    plan: dict | None = None,
    clip_detection: bool = True,
) -> tuple[StateProvider, Callable[[], None]]:
    """`clip_detection`: also listen to the console's meters
    for clips (`atoo.metering`), which adds L003 and one INFO to every
    reading. It opens a native connection on the console's port 2222 on a
    thread of its own; if that cannot be had, Watch says so at INFO and
    carries on.

    `start_name_addresses` (`watch_conditions.start_name_addresses`):
    names a scoped watch target needs that the poll does not read -- a
    Main's or a Matrix's -- read ONCE, into the first state only.

    `name_refresh`: read the polled names on the first
    reading and every this many after it, carrying the last ones read in
    between (`watch.refreshing_names`). 1 reads them every reading.

    `plan`: the open show's plan, whose output patches widen
    the socket groups read beyond the desk's own panel -- what `audit
    --plan` and `atoo watch` read too."""
    from atoo.console import WingConsole

    console = WingConsole(ip, port=port, timeout=timeout)
    identity = console.identity()
    if identity is None:
        console.close()
        raise ConsoleUnreachable(f"no reply from {ip}:{port} -- is the console reachable, and is its OSC remote enabled?")

    kwargs = dict(_DEFAULT_READ_KWARGS)
    kwargs.update(read_kwargs or {})
    # An earlier change, and the same derivation `cli._console_read_kwargs` does:
    # without it the Watch page audits the same desk differently from the
    # terminal, because a request that states no socket counts would read
    # no physical sockets at all and four rules would go quiet in the
    # browser only. The open show's plan is passed too,
    # as `audit --plan` passes it: the model's panel alone read LCL 1-8 on
    # a Compact and called six wedges on AES50-A unrouted. (The
    # read's second pass also follows any AES50 port with a device on it.)
    from atoo.audit import socket_groups_to_read
    from atoo import console_facts

    derived_in, derived_out = socket_groups_to_read(
        console_facts.model_from_identity(identity.args), plan)
    kwargs["input_sockets"] = kwargs.get("input_sockets") or derived_in
    kwargs["output_sockets"] = kwargs.get("output_sockets") or derived_out

    from atoo.audit import console_read_plan
    from atoo.watch import refreshing_names

    provider = refreshing_names(
        lambda names: read_console_state(console, names=names, **kwargs),
        console_read_plan(**{k: v for k, v in kwargs.items() if k != "bulk"}),
        name_refresh)

    if start_name_addresses:
        from atoo.watch_conditions import console_name_reader, read_names_at_start

        provider = read_names_at_start(provider, console_name_reader(console),
                                       list(start_name_addresses))
    closer = console.close
    if clip_detection:
        from atoo.metering import with_clip_detection

        provider, stop_listening = with_clip_detection(provider, ip)

        def closer() -> None:
            stop_listening()
            console.close()

    return provider, closer


class WatchSession:
    """Owns at most one live `watch()` loop, running in a background
    thread (the loop's own `sleep` blocks, so it can't run on the async
    event loop), and fans its events out to every subscribed WebSocket.

    A fresh subscriber immediately gets the most recent payload (if any)
    replayed to it, so a browser tab that connects mid-session sees the
    current alert table right away instead of an empty one until the next
    poll.

    Stop forgets that payload, and Start and Stop each announce a
    `status` to every subscriber. A stopped session's last event,
    replayed to a page opened afterwards, read as a session still
    running: Start disabled and the pill on Watching while `/api/status`
    said `running: false` (found checking an earlier change in Chromium).
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_payload: dict | None = None
        self.running = False
        self.label = ""
        self.error: str | None = None
        # The rules the running loop audits with, and the watch-conditions
        # file they came from (None: built-in rules only). Held as one
        # list object that `watch()` re-reads every cycle, so Save can
        # swap a new watch list in without restarting
        # (2026-10-01): see `replace_rules`.
        self.rules: list[AuditRule] | None = None
        self.watch_path: str | None = None
        # The Virtual soundcheck switch: while on, the loop's C004 and C005
        # report at INFO (`audit.virtual_soundcheck_rules`) and a note says
        # so. Every Start begins from the request's value (off by default)
        # and a stopped session forgets it. `_base_rules` are the rules as
        # built, which the switch is applied to and lifted from.
        self.virtual_soundcheck = False
        self._base_rules: list[AuditRule] | None = None

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.add(q)
        if self._last_payload is not None:
            loop.call_soon_threadsafe(q.put_nowait, self._last_payload)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def status(self) -> dict:
        return {"running": self.running, "label": self.label, "error": self.error,
                "virtual_soundcheck": self.virtual_soundcheck}

    def _effective_rules(self, base: list[AuditRule]) -> list[AuditRule]:
        """`base` as the loop audits with it: C004 and C005 at INFO while
        Virtual soundcheck is on."""
        from atoo.audit import virtual_soundcheck_rules

        return virtual_soundcheck_rules(base) if self.virtual_soundcheck else list(base)

    def set_virtual_soundcheck(self, on: bool) -> bool:
        """Turn Virtual soundcheck on or off in the running loop. The next
        cycle audits with the C004 and C005 the switch calls for, so turning
        it off makes a strip still on its alternate a WARNING again at that
        pass. False (and nothing changed) when no watch is running: the
        switch is chosen at Start."""
        if not self.running or self.rules is None:
            return False
        self.virtual_soundcheck = bool(on)
        self.rules[:] = self._effective_rules(self._base_rules or self.rules)
        self._announce()
        return True

    def start(
        self, loop: asyncio.AbstractEventLoop, provider_factory: ProviderFactory, interval: float,
        label: str, rules: list[AuditRule] | None = None,
        notes: "list[WatchNote] | None" = None,
        virtual_soundcheck: bool = False,
    ) -> None:
        """Stop whatever's running (FR-6.7: one session at a time), then
        start a new loop. `provider_factory` is called ON THE BACKGROUND
        THREAD, not here -- opening a console is itself a blocking socket
        call, and must not block the event loop that's about to answer
        this HTTP request.

        `rules` is threaded straight through to `watch()`'s
        own `rules=` extension point -- None (the default) means
        `watch()` falls back to its own default, `audit.DEFAULT_RULES`,
        exactly today's existing behavior. `/api/watch/start` passes
        `DEFAULT_RULES + build_watch_rules(conditions)` when the request
        names a watch-conditions file, the same combination
        `cli.watch_cmd` already builds on the CLI side.

        `notes` are session notes every frame carries beside the
        reading's own -- the console window a live watch reads with,
        when `ATOO_CONSOLE_WINDOW` changed it.

        `virtual_soundcheck` is the switch as the page had it at Start."""
        self._halt()
        self._stop.clear()
        self._base_rules = list(DEFAULT_RULES) if rules is None else list(rules)
        self.virtual_soundcheck = bool(virtual_soundcheck)
        rules = self._effective_rules(self._base_rules)
        self.rules = rules
        self.label = label
        self.error = None
        self.running = True
        self._loop = loop
        # Before the thread starts, so every tab hears "running" ahead of
        # the session's first event -- a page that last heard "not
        # running" drops events until it does.
        self._announce()
        self._thread = threading.Thread(target=self._run, args=(provider_factory, interval, rules,
                                                                  notes), daemon=True)
        self._thread.start()

    def replace_rules(self, rules: list[AuditRule], watch_path: str) -> bool:
        """Swap a newly saved watch list into the running loop (a watcher
        should pick up the new list). The next cycle audits with it; the session, its console
        and its baseline are kept, so a removed condition's findings clear
        and a new one's arrive as new, as any change would.

        Only when the save is to the file this session watches, or the
        session watches none (a list started empty and saved for the first
        time). False when nothing was swapped. A scoped name on a Main or
        a Matrix added this way has no name to resolve against -- those
        are read once, at Start -- and says so in its WARNING."""
        if not self.running or self.rules is None:
            return False
        if self.watch_path is not None and self.watch_path != watch_path:
            return False
        self._base_rules = list(rules)
        self.rules[:] = self._effective_rules(self._base_rules)
        self.watch_path = watch_path
        return True

    def stop(self) -> None:
        self._halt()
        self._announce()

    def _halt(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=5)
        self._thread = None
        self.running = False
        # Off again for the next Start: a switch left on must not carry a
        # forgotten Virtual soundcheck into a live show.
        self.virtual_soundcheck = False
        # After the join, so the stopped loop cannot write it back. A
        # stopped session's last event is not news to anyone: a page
        # opened (or a socket reconnecting) after Stop must not be handed
        # it, or it shows the old findings and believes Watch is running.
        self._last_payload = None

    def _announce(self) -> None:
        """Tell every open tab what `/api/status` now says. Not kept for
        replay: a new subscriber gets the same thing first, from the
        socket handler."""
        self._send({"type": "status", **self.status()})

    def _run(self, provider_factory: ProviderFactory, interval: float,
             rules: list[AuditRule] | None = None,
             notes: "list[WatchNote] | None" = None) -> None:
        try:
            provider, closer = provider_factory()
        except Exception as exc:
            self.error = str(exc)
            self.running = False
            self._broadcast({"type": "error", "error": self.error})
            return

        # `watch()` yields findings, not the state they came
        # from, and the coverage caveat is a fact about the state. Rather
        # than widen `WatchEvent` -- a shape `webui.py` and the Watch page
        # both consume -- the provider is wrapped to keep the last reading
        # to hand, which is what `cli.watch_cmd` does for the same reason.
        latest: list[ConsoleState] = []

        def tracking_provider() -> ConsoleState:
            state = provider()
            latest[:] = [state]
            return state

        presenter = _WatchPresenter(notes)
        try:
            for event in watch(tracking_provider, rules=rules, interval=interval,
                               sleep=self._stop.wait, session_notes=self._session_notes):
                self._broadcast(presenter.payload(
                    event, coverage_caveat(latest[0]) if latest else None,
                    latest[0] if latest else None))
                if self._stop.is_set():
                    break
        except Exception as exc:
            # A console that answered the identity check but then drops
            # mid-session (network hiccup, powered off) surfaces here --
            # reported to the UI rather than dying silently in a thread
            # nothing is watching.
            self.error = str(exc)
            self._broadcast({"type": "error", "error": self.error})
        finally:
            if closer is not None:
                closer()
            self.running = False
            self.virtual_soundcheck = False

    def _session_notes(self) -> list[WatchNote]:
        """The notes about the watch itself that the switches call for,
        read every cycle."""
        return [virtual_soundcheck_note()] if self.virtual_soundcheck else []

    def _broadcast(self, payload: dict) -> None:
        self._last_payload = payload
        self._send(payload)

    def _send(self, payload: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        loop = self._loop
        if loop is None:
            return
        for q in subscribers:
            try:
                loop.call_soon_threadsafe(q.put_nowait, payload)
            except RuntimeError:
                # The event loop this session started against is gone
                # (app shutting down mid-broadcast) -- nothing left to
                # deliver to, and not this background thread's job to
                # crash over it.
                pass


class _ThreadRoutedStream:
    """`sys.stdout`/`sys.stderr` for the length of one build: writes made
    by the build's own thread go to `sink`, everybody else's go where they
    always went.

    `contextlib.redirect_stdout` would not do. It swaps the process-wide
    stream, so every other thread in the server -- a watch loop, uvicorn
    -- would have its output captured into the build's log for as long as
    the build ran. Routing on the writing thread keeps the build's words
    in the build's log and nobody else's.
    """

    def __init__(self, fallback, owner: int, sink: Callable[[str], None]) -> None:
        self._fallback = fallback
        self._owner = owner
        self._sink = sink

    def write(self, text: str) -> int:
        if threading.get_ident() == self._owner:
            self._sink(text)
            return len(text)
        return self._fallback.write(text)

    def flush(self) -> None:
        if threading.get_ident() != self._owner:
            self._fallback.flush()

    def isatty(self) -> bool:
        # A page is not a terminal. A model call's in-place `\r` progress
        # line checks this and falls back to sparse plain lines, which is
        # what a log shown in a <pre> wants.
        return False

    def for_current_thread(self):
        """What a write from THIS thread would reach, as a stream that
        keeps reaching it from any thread (`progress._resolve_stream`).

        A model call's progress ticker writes from a thread of its own,
        which this router would otherwise send to the server's console:
        the build's progress lines would vanish from the build's log."""
        if threading.get_ident() == self._owner:
            return _SinkStream(self._sink)
        return self._fallback

    def __getattr__(self, name):
        return getattr(self._fallback, name)


class _SinkStream:
    """A write-only stream into a build's log, from whichever thread."""

    def __init__(self, sink: Callable[[str], None]) -> None:
        self._sink = sink

    def write(self, text: str) -> int:
        self._sink(text)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


# A stopped build says what it changed by comparing the bundle before and
# after, rather than by trusting the command's own account: the sentence
# "Nothing was written" on the page is checked, not assumed. Bounded, so a
# bundle with a very large journal history cannot make Run slow.
_FINGERPRINT_MAX_FILES = 2000
_FINGERPRINT_MAX_BYTES = 32 * 1024 * 1024


def _bundle_fingerprint(directory: "Path | None") -> "dict[str, str] | None":
    """{relative path: sha256} for every file under `directory`, or None
    when there is no directory or it is too big to fingerprint.
    `builds/` is left out ON PURPOSE: a stop now writes
    its OWN log file there, deliberately (`cli._write_build_log`'s
    `STOPPED`), and that is not what "did a stop leave the desk
    untouched" is asking about -- `plan.json`, `watch.json`, and
    everything else this build might have written are what matter."""
    if directory is None:
        return None
    out: dict[str, str] = {}
    try:
        for path in sorted(Path(directory).rglob("*")):
            if not path.is_file():
                continue
            if build_log_module.DIRNAME in path.relative_to(directory).parts:
                continue
            if len(out) >= _FINGERPRINT_MAX_FILES or path.stat().st_size > _FINGERPRINT_MAX_BYTES:
                return None
            out[path.relative_to(directory).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    except OSError:
        return None
    return out


def _fingerprint_changes(before: "dict | None", after: "dict | None") -> "list[str] | None":
    """The files that were added, changed or removed -- None when either
    side could not be taken."""
    if before is None or after is None:
        return None
    return sorted(name for name in set(before) | set(after)
                  if before.get(name) != after.get(name))


# The last this-many lines of build output are kept for the page. A build
# on a local model can print a line per phase for forty minutes; the page
# needs the recent ones to tell "working" from "stuck", not all of them.
_BUILD_LOG_LINES = 200


class BuildRun:
    """At most one `atoo build`, running in a worker thread, and what
    it has said so far (Build step 04).

    **It is the command, not a copy of it.** `_run` calls `cli.main` with
    the argv the page's Run button stands for -- `build --show DIR
    --conventions PATH --console-model M [--critic]` -- so what the browser
    builds and what a terminal builds cannot drift apart: the same bundle
    resolution, the same verifier, the same `meta` block, the same
    watchlist draft. A second pipeline here would be a second opinion
    about what a build is.

    **A build is not instant, and a page that cannot be told apart from a
    hung one gets reloaded.** So `status()` answers `running` / `done` /
    `failed` with the elapsed time and the build's own output, line by
    line, as it arrives. `done` covers exit 0 AND exit 2 -- the plan was
    written and verify found errors in it, which the dock then shows;
    `failed` is every exit that wrote no plan.

    **And the log alone was not enough**: a build needs progress shown while
    it runs. A model call is minutes of
    silence; the log said "sending" and then nothing until the call
    ended. So `status()` also carries `progress` -- which model call the
    build is in (generator, critic, watchlist), its stage, how long it has
    run and the tokens so far -- fed by `progress.ModelCallProgress`
    through a listener registered for the build's own thread.

    **And it can be stopped**, in case things go haywire. `stop()` fires the run's
    `progress.StopSignal`, which shuts the model call's connection from the
    stopping thread -- so it ends a call blocked in the silent thinking
    stretch as surely as one that is writing, and the spend stops with it.
    The build then ends in `stopped`, never `failed`, with one sentence
    (`progress.stopped_message`) whose claim about the bundle is CHECKED:
    the bundle is fingerprinted when the run starts and again when it
    ends, and the sentence names whatever differs.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._partial = ""
        self.state = "idle"
        # The run's Stop, and what a stop found when the run ended.
        self._stop_signal = None
        self._guard_dir: "Path | None" = None
        self._fingerprint: "dict | None" = None
        self.stopped: "dict | None" = None
        self.command: list[str] | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.exit_code: int | None = None
        self.error: str | None = None
        self.log: list[str] = []
        self.findings: list[dict] = []
        # The model call in flight (or the last one), and every one that
        # has ended -- `progress.ModelCallProgress` snapshots, delivered by
        # `_on_model_progress` from the provider's own ticker. Read-only
        # to the page: nothing about progress can start, stop or change a
        # build.
        self._model_call: dict | None = None
        self._model_calls: list[dict] = []

    @property
    def running(self) -> bool:
        return self.state == "running"

    def forget(self) -> bool:
        """Back to `idle`, dropping the last run's log and findings -- what
        opening a different show does (the last show's
        `build.failed` stayed in the new show's dock, and came back on
        every reload). A run still in flight is left alone and says
        False: it is writing into the bundle it started in, and its end
        is its own to report."""
        if self.running:
            return False
        self.__init__()
        return True

    def status(self) -> dict:
        with self._lock:
            log = list(self.log) + ([self._partial] if self._partial else [])
            end = self.finished_at if self.finished_at is not None else time.time()
            return {
                "state": self.state,
                "command": list(self.command) if self.command else None,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_s": round(end - self.started_at, 1) if self.started_at else None,
                "exit_code": self.exit_code,
                "error": self.error,
                "log": log[-_BUILD_LOG_LINES:],
                "findings": list(self.findings),
                "progress": self._progress_payload(),
                # Stop: requested (while it lands) and the end state's
                # sentence once it has.
                "stop_requested": bool(self._stop_signal is not None
                                       and self._stop_signal.stopped),
                "stopped": dict(self.stopped) if self.stopped else None,
            }

    def _on_model_progress(self, event: dict) -> None:
        """The listener `_run` registers for the build's thread: one call
        per `ModelCallProgress` start, tick (every 0.5s) and end. It only
        stores; `status()` shapes."""
        snap = {k: v for k, v in event.items() if k != "event"}
        with self._lock:
            self._model_call = snap
            if event.get("event") == "end":
                self._model_calls.append(snap)

    def _progress_payload(self) -> dict | None:
        """`progress` in `GET /api/build/status`: the model call the build
        is in, and how far it has got. None until the first model call
        starts (and for any run that makes none -- an apply). Called with
        the lock held.

        `elapsed_s` of a call in flight is worked out now, from the wall
        clock, rather than taken from the last tick: the tick is the one
        thing that stops if the provider wedges, and the elapsed time is
        exactly what has to keep moving then."""
        cur = self._model_call
        if cur is None:
            return None
        live = cur.get("stage") in ("waiting", "thinking", "writing") and self.state == "running"
        elapsed = cur.get("elapsed_s")
        if live and cur.get("started_at"):
            elapsed = round(time.time() - cur["started_at"], 1)
        return {
            "phase": cur.get("label") or "",
            "model": cur.get("model") or "",
            "effort": cur.get("effort") or "",
            "stage": cur.get("stage"),
            "started_at": cur.get("started_at"),
            "elapsed_s": elapsed,
            "thinking_tokens": cur.get("thinking_tokens"),
            "output_tokens": cur.get("output_tokens"),
            "thinking_chars": cur.get("thinking_chars"),
            "output_chars": cur.get("output_chars"),
            "thinking_streamed": cur.get("thinking_streamed"),
            "thinking_seen": cur.get("thinking_seen"),
            "streams": cur.get("streams"),
            "estimated": cur.get("estimated"),
            "input_tokens": cur.get("input_tokens"),
            "total_output_tokens": cur.get("total_output_tokens"),
            # The live view: the tail of the model's text (at most
            # `progress.TAIL_CHARS`), the latest line of its thinking where
            # the provider streams any, and the outline of the JSON it is
            # writing (`stream_outline`). Kept to the call in flight -- the
            # finished calls below carry only their numbers.
            "tail": cur.get("tail") or "",
            "thinking_line": cur.get("thinking_line") or "",
            "outline": cur.get("outline"),
            "calls": [
                {k: call.get(k) for k in ("label", "model", "effort", "stage", "elapsed_s",
                                          "input_tokens", "output_tokens",
                                          "thinking_tokens", "total_output_tokens")}
                for call in self._model_calls
            ],
        }

    def _write(self, text: str) -> None:
        # `\r` rewrites the current line on a terminal; here it starts it
        # again, so a progress counter reads as its latest value rather
        # than as every value it ever had, run together.
        with self._lock:
            for i, chunk in enumerate(text.split("\n")):
                if i:
                    self.log.append(self._partial)
                    self._partial = ""
                if "\r" in chunk:
                    self._partial = chunk.rsplit("\r", 1)[1]
                else:
                    self._partial += chunk
            del self.log[:-_BUILD_LOG_LINES]

    def start(self, argv: list[str], finish: Callable[[int], list[dict]],
              guard_dir: "Path | None" = None) -> bool:
        """Start `atoo <argv>` in a worker thread. False (and nothing
        started) when one is already running. `finish(exit_code)` runs in
        that thread once the command returns, and whatever findings it
        returns are the run's own. `guard_dir` is the directory a stop's
        sentence reports on (the show bundle), fingerprinted now."""
        from atoo.progress import StopSignal

        with self._lock:
            if self.state == "running":
                return False
            self._stop_signal = StopSignal()
            self._guard_dir = guard_dir
            self.stopped = None
            self.state = "running"
            self.command = ["atoo", *argv]
            self.started_at = time.time()
            self.finished_at = None
            self.exit_code = None
            self.error = None
            self.log = []
            self._partial = ""
            self.findings = []
            self._model_call = None
            self._model_calls = []
        # Outside the lock: hashing a bundle is file I/O, and status() must
        # never wait on it.
        self._fingerprint = _bundle_fingerprint(guard_dir)
        threading.Thread(target=self._run, args=(argv, finish), daemon=True).start()
        return True

    def stop(self) -> bool:
        """Stop the running command. False when nothing is running (or the
        stop was already asked for). Returns at once: the socket is shut
        here, and the run reaches `stopped` in its own thread moments
        later."""
        with self._lock:
            if self.state != "running" or self._stop_signal is None:
                return False
            signal = self._stop_signal
        return signal.stop()

    def _run(self, argv: list[str], finish: Callable[[int], list[dict]]) -> None:
        from atoo import cli
        from atoo.progress import BuildStopped, model_progress_listener, stop_scope

        me = threading.get_ident()
        saved = sys.stdout, sys.stderr
        sys.stdout = _ThreadRoutedStream(saved[0], me, self._write)
        sys.stderr = _ThreadRoutedStream(saved[1], me, self._write)
        code = 1
        error = None
        try:
            # The structured channel, beside the log: the build runs in
            # THIS thread, in-process, so every model call it makes can
            # hand its progress straight to this runner -- no log line to
            # scrape, no file to poll. Registered for this thread only
            # (a context variable), so a watch loop's narration call in
            # another thread is never mistaken for the build's.
            with model_progress_listener(self._on_model_progress), \
                    stop_scope(self._stop_signal):
                code = cli.main(argv)
        except BuildStopped:
            # A command that does not report a stop itself (`build` does,
            # and exits 130): the same end state.
            code = 130
        except SystemExit as exc:  # argparse refusing the argv
            code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:  # noqa: BLE001 -- reported, never a dead thread
            error = f"{type(exc).__name__}: {exc}"
            self._write(f"\n{error}\n")
        finally:
            if sys.stdout is not saved[0] and isinstance(sys.stdout, _ThreadRoutedStream):
                sys.stdout = saved[0]
            if sys.stderr is not saved[1] and isinstance(sys.stderr, _ThreadRoutedStream):
                sys.stderr = saved[1]

        signal = self._stop_signal
        stopped = (signal is not None and signal.stopped and error is None
                   and code not in (0, 2))
        stop_report = None
        if stopped:
            from atoo.progress import stopped_message

            changed = _fingerprint_changes(self._fingerprint,
                                           _bundle_fingerprint(self._guard_dir))
            after = (signal.requested_at or time.time()) - (self.started_at or time.time())
            if changed is None:
                # Could not fingerprint: say only what cannot be wrong.
                message = (f"Stopped by you after {_stop_duration(after)}. The model call "
                           "was ended; the bundle could not be checked for changes.")
            else:
                message = stopped_message(after, changed)
            stop_report = {"message": message, "after_s": round(after, 1),
                           "changed": changed}
            # A plan that landed before the stop (the stop hit the
            # watchlist draft) is the plan on disk: show it.
            if changed and any(name.endswith("plan.json") for name in changed):
                code_for_finish = 0
            else:
                code_for_finish = None
        try:
            if stopped:
                findings = finish(code_for_finish) if code_for_finish is not None else []
            else:
                findings = finish(code) if error is None else []
        except Exception as exc:  # noqa: BLE001
            error = error or f"{type(exc).__name__}: {exc}"
            findings = []
        with self._lock:
            if self._partial:
                self.log.append(self._partial)
                self._partial = ""
            self.exit_code = code
            self.error = error
            self.finished_at = time.time()
            if stopped:
                self.state = "stopped"
                self.stopped = stop_report
            else:
                self.state = "done" if error is None and code in (0, 2) else "failed"
            if self.state == "failed":
                findings = [self._failure_finding()] + findings
            self.findings = findings

    def _failure_finding(self) -> dict:
        """The one finding a failed build puts in the dock: the last thing
        it said, which is where `build` says why (`generation failed: ...`,
        `input list error in input.csv: ...`). The last line that is not indented,
        because `build` indents the detail under a reason -- `  the 1,204
        characters that did arrive are in ...` -- and the reason is what
        the dock needs. The whole log stays on step 04."""
        said = [line.rstrip() for line in self.log if line.strip() and not line[:1].isspace()]
        message = self.error or (said[-1] if said else "the build stopped without a word")
        return Diagnostic(
            severity=Severity.ERROR, code="build.failed",
            message=f"The build did not produce a plan (exit {self.exit_code}): {message}",
            where="04 Plan", source="build",
            fix="read the build log on step 04. A build needs a model: "
                "ATOO_AI_PROVIDER chooses one (Claude by default, which needs ANTHROPIC_API_KEY) "
                "-- see https://docs.atoo.app/troubleshooting/troubleshooting/",
        ).to_dict()


class ApplyRun(BuildRun):
    """At most one `atoo apply`, running in a worker thread -- the
    Apply screen's half.

    **The same runner Build step 04 uses**, and deliberately so: one
    place that knows how to run an Atoo command in a thread, route
    only that thread's output into a log, and report it running / done /
    failed with the elapsed time. Three things differ, and only three.

    * It carries **`result`** -- the journal view's payload
      (`_apply_payload`), set by the run's own `finish` callback once the
      command has returned and the journal it wrote has been read back.
    * A failure says what an apply failure is, not what a build failure
      is, and it tells an abort (the desk stopped answering part way
      through, with writes already made) apart from a run that never
      started.
    * `done` covers exit 0 and exit 2 exactly as it does for a build, and
      for the same reason: exit 2 here is the **refusal gate** doing its
      job, or a readback mismatch. The command ran and found problems.
      Exit 1 is the command not running at all.

    It is `atoo apply` -- the command, with every gate that command
    has: the pre-flight `verify_plan` refusal, the console-model
    cross-check, the empty-expansion-bay stop, the journal
    in the bundle. A second apply path in this file would be
    a second opinion about when it is safe to write to a desk.
    """

    def __init__(self) -> None:
        super().__init__()
        self.result: dict | None = None
        # This runner is also Patch's and Undo's. ONE runner for every
        # command that can write, so two writes to a desk can never be in
        # flight from this server at once -- a patch cannot start while an
        # apply is still landing, and an undo cannot pop a stack a patch is
        # about to push onto.
        self.kind = "apply"
        # A patch's review (`amend.review_payload`), read back from the
        # command's own `--review-json`. None for any other kind.
        self.review: dict | None = None
        # A preview (no --confirm) or a write. A preview that fails says
        # "Preview failed", never "the apply did not run".
        self.preview = False
        # Which desk the run reads or writes, as the page names it: the
        # bar's `address:port`, or the Demo's simulated WING.
        self.on: str | None = None

    def status(self) -> dict:
        base = super().status()
        # Stop is Build's (`POST /api/build/stop`); nothing stops a write to
        # a desk part way, so these runs do not carry its fields.
        base.pop("stop_requested", None)
        base.pop("stopped", None)
        # Copies, taken under the lock `publish` sets them
        # under. The response is serialized after this returns, on another
        # thread from the run's; handing it the run's own dicts let a
        # finish still filling one in break the serialization ("dictionary
        # changed size during iteration").
        with self._lock:
            result, review = copy.deepcopy(self.result), copy.deepcopy(self.review)
            kind, preview, on = self.kind, self.preview, self.on
        return {**base, "result": result, "kind": kind,
                "review": review, "preview": preview, "on": on}

    def publish(self, **fields) -> None:
        """Set `review` and/or `result` for the page to read, under the
        lock `status` copies them under. A finish publishes a
        dict only once it is complete, and never changes it afterwards."""
        unknown = set(fields) - {"review", "result"}
        if unknown:
            raise TypeError(f"publish() takes review and result, not {sorted(unknown)}")
        with self._lock:
            for name, value in fields.items():
                setattr(self, name, value)

    def start(self, argv: list[str], finish: Callable[[int], list[dict]],
              kind: str = "apply", preview: bool = False, on: "str | None" = None) -> bool:
        with self._lock:
            if self.state == "running":
                return False
            # Cleared before the thread exists, so `status()` can never
            # show the previous run's journal beside this one's "running".
            self.result = None
            self.review = None
            self.kind = kind
            self.preview = preview
            self.on = on
        return super().start(argv, finish)

    _PREVIEW_LABEL = {"apply": "Preview", "patch": "Patch preview",
                      "undo": "Undo preview"}

    def _failure_finding(self) -> dict:
        if self.preview:
            # A dry run that failed names the dry run, and says
            # that nothing was written.
            said = [line.rstrip() for line in self.log
                    if line.strip() and not line[:1].isspace()]
            message = self.error or (said[-1] if said else "it stopped without a word")
            label = self._PREVIEW_LABEL.get(self.kind, "Preview")
            return Diagnostic(
                severity=Severity.ERROR, code="preview.failed",
                message=f"{label} failed (exit {self.exit_code}): {message} "
                        "Nothing was written.",
                where="Apply", source=self.kind,
                fix="read the run log on the Apply screen -- it is the command's own "
                    "output, word for word.",
            ).to_dict()
        if self.kind != "apply":
            said = [line.rstrip() for line in self.log
                    if line.strip() and not line[:1].isspace()]
            message = self.error or (said[-1] if said else f"the {self.kind} stopped "
                                                           "without a word")
            return Diagnostic(
                severity=Severity.ERROR, code=f"{self.kind}.failed",
                message=f"The {self.kind} did not run (exit {self.exit_code}): {message}",
                where="Apply", source=self.kind,
                fix=f"read the run log on the Apply screen -- it is `atoo "
                    f"{self.kind}`'s own output, word for word.",
            ).to_dict()
        aborted = _apply_abort_reason(self.log)
        if aborted is not None:
            return Diagnostic(
                severity=Severity.ERROR, code="apply.aborted",
                message=f"The console stopped answering part way through this apply "
                        f"({aborted}). The addresses evaluated before that point are in "
                        f"the journal; nothing after it was attempted.",
                where="Apply", source="apply",
                fix="check the network to the desk and run it again -- an apply skips any "
                    "address already at the planned value, so a second run finishes what "
                    "the first one started rather than rewriting it.",
            ).to_dict()
        said = [line.rstrip() for line in self.log if line.strip() and not line[:1].isspace()]
        message = self.error or (said[-1] if said else "the apply stopped without a word")
        return Diagnostic(
            severity=Severity.ERROR, code="apply.failed",
            message=f"The apply did not run (exit {self.exit_code}): {message}",
            where="Apply", source="apply",
            fix="read the run log on the Apply screen -- it is `atoo apply`'s own "
                "output, word for word.",
        ).to_dict()


def _preset_library_state(explicit: "str | None") -> dict:
    """The preset library a build from this page would use, and its names:
    `explicit` (`atoo ui --presets`), else `[presets] default` in
    ~/.atoo.config -- `cli._resolve_preset_library`'s order.

    `{"configured", "library", "source", "names", "error"}`. `names` is
    sorted and de-duplicated (two files may share a name; `verify` says
    which one wins). Nothing configured is `configured: false` and no
    error; a path that is not a directory, or a library that will not
    read, is `configured: true` with `error` saying why and no names."""
    from atoo.presets import PresetError, load_preset

    chosen, source = explicit, "--presets"
    if not chosen:
        default = config.load_default_presets()
        if default is None:
            return {"configured": False, "library": None, "source": None, "names": [],
                    "error": None}
        chosen, source = str(default), f"[presets] default in {config.config_path()}"
    out = {"configured": True, "library": str(chosen), "source": source, "names": [],
           "error": None}
    path = Path(chosen)
    if not path.is_dir():
        out["error"] = f"{path} {'is a file, not a directory' if path.is_file() else 'does not exist'}"
        return out
    names, unreadable = set(), []
    for file_path in sorted(path.glob("*.chn")):
        try:
            names.add(load_preset(file_path).name)
        except (PresetError, OSError, ValueError):
            unreadable.append(file_path.name)   # verify names it; the list still helps
    out["names"] = sorted(names, key=str.casefold)
    if unreadable:
        out["error"] = f"{len(unreadable)} file(s) could not be read: {', '.join(unreadable)}"
    return out


def create_app(
    initial_plan: dict | None = None, initial_plan_path: str | None = None,
    initial_watch_conditions_path: str | None = None,
    initial_console: dict | None = None,
    initial_bundle: str | None = None,
    initial_findings: list[dict] | None = None,
    initial_conventions: str | None = None,
    initial_presets: str | None = None,
    initial_workspace: str | None = None,
) -> FastAPI:
    """Builds the FastAPI app. `atoo.webui` itself imports fastapi at
    module level -- only `atoo ui` (`atoo.cli.ui_cmd`) imports
    *this module*, guarded by the same lazy-import posture `apply_cmd`/
    `audit_cmd` use for `atoo.console`, so `atoo build` and
    every other command still needs nothing from the `ui` extra.

    `initial_plan`/`initial_plan_path`: the plan Build step
    04 shows until a build replaces it, already loaded and parsed by the caller (`cli.py`'s `ui_cmd`
    uses `_load_plan_file`, so a bad `--plan` path is caught and reported
    before the server ever starts, not silently swallowed here). Both
    default to None -- Watch mode's routes/behavior are unaffected
    either way, and a plan can always be loaded later via
    `POST /api/plan/load`.

    `initial_watch_conditions_path`: Watch mode's
    watch-conditions panel starting path, parallel to `initial_plan_path`
    above but -- unlike the plan case -- taking only the path, not a
    pre-parsed value: `cli.py`'s `ui_cmd` already validates this path with
    its own `_load_watch_conditions_file` before ever calling here (same
    fail-fast posture as `--plan`), and this constructor loads it again
    via `_load_watch_conditions_from_path` to populate `app.state`. A
    failure here (the file changing or vanishing in the gap between that
    check and this call -- `ui_cmd`'s own check already ruled out every
    other failure mode) degrades to "nothing loaded" rather than raising,
    matching every other artifact's None-is-fine posture; the browser can
    always load a corrected path afterward via
    `POST /api/watch-conditions/load`.

    `initial_console`: `cli.resolve_console_defaults()`'s
    dict -- the address/port/timeout a command that names no console
    would use, each with the origin it came from. It is **where the bundle
    bar's console starts** -- the one address every desk-facing endpoint
    here uses -- and `POST /api/console` replaces it for the rest of the
    session (FR-6.9); nothing is written back to the config file.

    The origins travel with the values on purpose, and the page shows
    them. The CLI's whole guard against a stale `export ATOO_CONSOLE`
    is its `Using console 192.0.2.16 from ATOO_CONSOLE` line on
    stderr, and a pre-filled text box is *more* prone to that mistake,
    not less: the operator sees an address and assumes they typed it.
    A value nobody typed has to say so on screen.

    None (the default) is today's behavior exactly: an empty IP box, port
    2223, and no provenance line. `create_app()` resolves nothing itself
    -- `ui_cmd` does the resolving, the same way it loads `--plan` before
    calling here, so this module keeps its "no CLI imports" posture.

    `initial_bundle` (mockup version H): the show bundle
    directory `--show` named, or None. It is the single piece of state the
    shell page at `/` shares across all three of its modes, because one
    bundle is what Build compiles, Apply writes and Watch watches -- see
    `_bundle_payload`. A directory that is not usable as a bundle
    degrades to None rather than raising, the same posture
    `initial_watch_conditions_path` has: `cli.ui_cmd` has already
    validated `--show` and reported it, so anything left here is the file
    system changing underneath us, and the browser can open a corrected
    one via `POST /api/bundle/open` without a restart.

    `initial_findings` (same mockup): the shell's findings dock, seeded at
    first paint. A list of `Diagnostic.to_dict()` dicts and nothing else
    -- the dock is a renderer for the one diagnostic type every layer of
    this codebase already produces (`atoo.diagnostics`, FR-X.15b),
    not a second vocabulary. `cli.ui_cmd` never populates it: what fills
    the dock is the page itself -- Build's tile findings, and step 04's
    plan and build findings, each added by the step that raised them. The
    parameter is the contract, and a dock nothing can put anything into
    cannot be tested.

    `initial_conventions` (same mockup, phase 2): the **house conventions
    file** -- Build step 01. It is the one of the three build inputs that
    is not a bundle slot, because house style is reused across every show
    and so lives outside the bundle. `cli.ui_cmd` resolves
    it from `~/.atoo.config`'s `[conventions]` default, the same
    fallback `build` uses when no `--conventions` is given, and passes
    the path here; `atoo ui` has no `--conventions` flag of its own,
    so the config default and the page's own "Change file" are the two
    ways to name one. None (the default) is an honest state and the page
    draws it: step 01 reads **Not set**, with a finding saying a build
    cannot run without one.

    `initial_presets`: `atoo ui --presets DIR`,
    the preset library step 02's Preset chooser lists and a build started
    from the page is given. None falls back to `~/.atoo.config`'s
    `[presets] default` -- `_preset_library_state`, the same order
    `cli._resolve_preset_library` uses.

    `initial_workspace`: the working folder `atoo init`
    made -- `~/.atoo.config`'s `[workspace] default`, resolved by
    `cli.ui_cmd` and passed only when no `--show` was given. It rides in
    the first-paint blob as `workspace`, and the page's file browser
    starts there (Open..., New show..., and each Build step's Change
    file) for as long as no bundle is open. None is the old behaviour:
    the browser starts in the home folder."""
    app = FastAPI(title="Atoo Watch", docs_url=None, redoc_url=None)
    session = WatchSession()
    app.state.session = session
    app.state.plan = initial_plan
    app.state.plan_path = initial_plan_path

    initial_watch_conditions = None
    if initial_watch_conditions_path is not None:
        initial_watch_conditions, _error = _load_watch_conditions_from_path(initial_watch_conditions_path)
        if initial_watch_conditions is None:
            initial_watch_conditions_path = None
    app.state.watch_conditions = initial_watch_conditions
    app.state.watch_conditions_path = initial_watch_conditions_path
    app.state.console_defaults = initial_console or {}

    initial_show = None
    if initial_bundle is not None:
        try:
            initial_show = bundle.load(initial_bundle)
        except bundle.BundleError:
            initial_show = None
    app.state.bundle = initial_show
    app.state.findings = list(initial_findings or [])
    app.state.conventions_path = initial_conventions
    app.state.workspace = initial_workspace
    app.state.presets_path = initial_presets
    # Per-tile "Change file" overrides (version H, Build steps 01-03).
    # Empty means "use the derived path" -- the bundle's fixed filename,
    # or the house conventions file `ui_cmd` resolved. A value here is a
    # path the operator typed into a tile, and it wins for this session
    # only, exactly as `--conventions` wins over the config default on the
    # command line. Nothing is written back to the config file.
    app.state.build_overrides = {slot: None for slot in _BUILD_SLOTS}
    # Build step 04: the one build this server may be running.
    build_run = BuildRun()
    app.state.build_run = build_run
    # Apply: the one apply this server may be running, and
    # the only thing here that can write to a console.
    apply_run = ApplyRun()
    app.state.apply_run = apply_run
    # What the last clean patch preview reviewed (`_patch_key`) -- and so
    # the only change a write may be armed for.
    app.state.patch_reviewed = None
    # Patch: the change set the last clean patch preview
    # compiled -- what a confirmed write hands the command, so the write is
    # the change the page showed and not a second model call's.
    app.state.patch_change_set = None
    # The bundle bar's console is editable, and it is
    # the ONE console every desk-facing endpoint uses. `console_lock` makes
    # "which desk" and "is a write running" one question: each write
    # endpoint reads the console and starts its run while holding it, and
    # `POST /api/console` checks the runner and changes the console while
    # holding it -- so a write can never start against one desk while the
    # bar is being moved to another, and the bar can never move while a
    # write is running.
    app.state.console_lock = threading.Lock()
    # What the last Ping of the bar's console heard -- the desk's own `/?`
    # reply, serial included -- so the journal listing can say which rows
    # were written to the desk on the line. Cleared on every edit: an
    # identity heard at the old address says nothing about the new one.
    app.state.console_identity = None
    # Which server process this is: random at startup, never persisted.
    # The page learns it at first paint (the embedded startup blob) and
    # watches `GET /api/status` for it; a different value means the server
    # behind the page was restarted -- possibly on a different bundle, which
    # is how an A19 tab came to show A19's journal stack against A20's
    # server (2026-09-24). The page then stops offering writes until it is
    # reloaded (shell.js, "the stale-page banner").
    app.state.instance_id = secrets.token_hex(8)
    # Which copy of Atoo this server is, read once when it starts: the
    # start-up message and the page's footer say the same line.
    app.state.install = install_info.describe().payload()
    # Demo is the demo show and the Demo console together, and
    # nothing else. `before_demo` is what choosing Demo replaced -- the
    # bundle and the console -- so leaving Demo can put back whichever of
    # them the way out did not choose anew. None while Demo is not open.
    app.state.before_demo = None
    if is_demo_show(initial_show):
        # `atoo ui --show` naming the packaged demo show is Demo.
        app.state.before_demo = {"bundle": None, "console": dict(app.state.console_defaults)}
        app.state.console_defaults = _demo_console(app.state.console_defaults)

    def _demo_refusal(action: str) -> JSONResponse:
        # 403, not 400: the request is well-formed and would succeed on any
        # other show. `demo` lets the page say it in its own words.
        return JSONResponse(
            {"error": f"the demo show is read-only -- {action} is refused, and nothing was "
                      "written. It changes only in Atoo's own repository. To work on a "
                      "show of your own, open or create one in the bundle bar (Change… or "
                      "New show…), or choose a console address.",
             "demo": True},
            status_code=403,
        )

    def _refuse_demo(action: str, *paths) -> "JSONResponse | None":
        """Every write endpoint's guard: refused while the demo
        show is open, and for any path inside the packaged demo folder
        whatever is open -- the page's disabled controls are a courtesy,
        this is the guard."""
        if is_demo_show(app.state.bundle) or any(_inside_demo(p) for p in paths):
            return _demo_refusal(action)
        return None

    def _open_show(show: "bundle.Bundle") -> None:
        """Make `show` the open bundle, and drop everything that belonged
        to the last one -- `POST /api/bundle/open` and choosing Demo both
        end here."""
        app.state.bundle = show
        # A different show is a different input list and a different
        # instructions.md, so whatever was typed into those two tiles for
        # the last show is dropped rather than carried over -- a tile
        # still pointing at the previous bundle's input.csv while the
        # bundle bar names a new folder is the worst of both.
        #
        # The conventions override goes too. It used
        # to survive, on the grounds that the house file lives outside the
        # bundle and is the same for every show -- but since
        # an earlier change a bundle's plan records the house file it was built
        # from, and a path typed for the LAST show would override that
        # record for this one. The new show opens on the file its
        # plan.json names, else the config's.
        app.state.build_overrides["input_list"] = None
        app.state.build_overrides["instructions"] = None
        app.state.build_overrides["conventions"] = None
        # And the plan is the new show's, for the same reason: step 04
        # showing the last show's plan under this show's name is the one
        # outcome worse than showing none. Its `plan.json` if it has one
        # -- what `atoo ui --show` loads at startup -- else nothing.
        app.state.plan, app.state.plan_path = None, None
        if show.has(bundle.PLAN):
            plan, _error = _load_plan_from_path(str(show.plan))
            if plan is not None:
                app.state.plan, app.state.plan_path = plan, str(show.plan)
        # Watch's rules too, for the same reason: the editor
        # offering the last show's watch.json under this show's name
        # would Save the last show's rules into the wrong conversation.
        # Watch mode re-reads `GET /api/watch-conditions` on this change.
        app.state.watch_conditions, app.state.watch_conditions_path = (
            _bundle_watch_conditions(show))
        # And the last build and the last apply were the last show's: their logs and findings would otherwise come back
        # in this show's dock at every page load. One still running is
        # left to finish (`BuildRun.forget`).
        build_run.forget()
        apply_run.forget()

    def _close_show() -> None:
        """No bundle open -- what leaving Demo comes back to when nothing
        was open before it."""
        app.state.bundle = None
        for slot in _BUILD_SLOTS:
            app.state.build_overrides[slot] = None
        app.state.plan, app.state.plan_path = None, None
        app.state.watch_conditions, app.state.watch_conditions_path = None, None
        build_run.forget()
        apply_run.forget()

    def _stop_watch_for_demo_change() -> None:
        # A watch belongs to the show and the desk it was started on. Demo
        # in or out changes both, so a running watch stops rather than
        # carry on reading a rig the bar no longer names.
        if session.running:
            session.stop()

    def _leave_demo_console() -> None:
        """Opening or creating another show leaves Demo: the console goes
        back to the one Demo replaced (or none). Called with no Demo open,
        it does nothing."""
        if not (app.state.console_defaults or {}).get("demo"):
            app.state.before_demo = None
            return
        restored = dict(((app.state.before_demo or {}).get("console")) or {})
        restored.pop("demo", None)
        app.state.console_defaults = restored
        app.state.console_identity = None
        app.state.before_demo = None
        _stop_watch_for_demo_change()

    def _no_console_error() -> JSONResponse:
        if (app.state.console_defaults or {}).get("demo"):
            # Demo has no desk behind it, so there is nothing
            # to write to -- and a write that "succeeded" against nothing
            # would be a lie told at the one moment it matters. 
            # a Full build or Patch PREVIEW reads the simulated rig
            # (`_demo_preview`); everything that reaches here is a write,
            # an undo, or a preview the Demo cannot run.
            return JSONResponse(
                {"error": "the console is Demo, a simulated desk: the Demo show can preview "
                          "against it, but writing and Undo are switched off, and nothing "
                          "was written. To write to a real desk, open a show of your own "
                          "and choose a console address in the bundle bar (Console: "
                          "Change…).",
                 "demo": True},
                status_code=400,
            )
        return JSONResponse(
            {"error": "no console address -- type one into the Console field in the bundle "
                      "bar, or set ATOO_CONSOLE / ~/.atoo.config's [console] "
                      "section before starting `atoo ui`. The bundle bar shows the one "
                      "in force."},
            status_code=400,
        )

    def _on_demo() -> bool:
        """The bar's console is Demo, with the Demo show open (they always
        go together)."""
        return bool((app.state.console_defaults or {}).get("demo")) \
            and is_demo_show(app.state.bundle)

    def _demo_write_refusal() -> JSONResponse:
        """In the Demo, Preview reads the simulated rig, and a
        write -- armed or not -- is refused before anything starts."""
        return JSONResponse(
            {"error": "Writing is switched off in the Demo show: its desk is simulated, so "
                      "nothing was written. Choose a console address in the bundle bar "
                      "(Console: Change…) to write to a real desk.",
             "demo": True},
            status_code=403,
        )

    def _demo_preview(kind: str):
        """A Demo preview's bundle and desk: a scratch copy of
        the packaged Demo show, so nothing a command does on a preview can
        reach the package, and the simulated WING (`demo_desk.DemoDesk`)
        answering on localhost. Returns `(show, desk, cleanup)`; the
        caller's `finish` (or its start failure) calls `cleanup`."""
        import tempfile

        from atoo.demo_desk import DemoDesk

        scratch = Path(tempfile.mkdtemp(prefix=f"atoo-demo-{kind}-"))
        desk = None

        def cleanup() -> None:
            if desk is not None:
                desk.close()
            shutil.rmtree(scratch, ignore_errors=True)

        try:
            copy_dir = scratch / DEMO_SHOW_DIR.name
            shutil.copytree(DEMO_SHOW_DIR, copy_dir)
            desk = DemoDesk()
            return bundle.load(copy_dir), desk, cleanup
        except BaseException:
            # Nothing else would close the socket or remove the copy.
            cleanup()
            raise

    def _stale_page(expected: "str | None", confirmed: bool) -> "JSONResponse | None":
        """A confirmed write from a page showing a different desk than the
        bar now holds. Previews are not refused -- they write nothing, and
        the run log names the desk they read."""
        if not confirmed or expected is None:
            return None
        current = _console_label(app.state.console_defaults or {})
        if expected.strip() == current:
            return None
        return JSONResponse(
            {"error": f"this page names {expected.strip()} as the desk to write to, but the "
                      f"console in the bundle bar is now {current}. Nothing was written -- "
                      "reload the page, check which desk you mean, and arm the write again."},
            status_code=409,
        )

    def _refuse_stale(message: str, what: str) -> JSONResponse:
        # `stale` names what the page was wrong about -- "bundle", "plan",
        # "review" or "undo" -- so the page can redraw that one thing (or,
        # for "bundle", put up its stale-page banner) rather than only print
        # the sentence.
        return JSONResponse({"error": message, "stale": what}, status_code=409)

    def _stale_bundle(expected: "str | None", show, confirmed: bool) -> "JSONResponse | None":
        """A confirmed write from a page showing a different show bundle
        than the one this server would write -- the server was restarted on
        another bundle under an open tab, or another tab opened one.

        **Absent is refused, not waved through** -- the opposite of
        `_stale_page`'s posture for `expected_console`, on purpose. The tab
        this guard exists for was a page loaded
        before the server behind it restarted; a page served before this
        field existed is that tab by construction, and it sends none. A
        script that writes through this API knows the bundle it started
        the server on (`GET /api/bundle` answers it) and names it, as a
        person names `--show` on the command line. Previews are never
        refused: they write nothing."""
        if not confirmed:
            return None
        current = str(show.directory)
        if not (expected or "").strip():
            return _refuse_stale(
                "this write does not say which show bundle it was reviewed against "
                "(`expected_bundle`) -- a page loaded before this server started, or a script "
                f"that has not named one. The server has {current} open. Nothing was written "
                "-- reload the page, check what it shows, and arm the write again.", "bundle")
        try:
            same = Path(expected.strip()).expanduser().resolve() == show.directory.resolve()
        except OSError:
            same = False
        if same:
            return None
        return _refuse_stale(
            f"this page shows the show bundle {expected.strip()}, but the server now has "
            f"{current} open -- it was restarted on another bundle, or another tab opened "
            "one. Nothing was written -- reload the page, check which show you mean, and arm "
            "the write again.", "bundle")

    def _build_in_flight(confirmed: bool) -> "JSONResponse | None":
        """A confirmed write while Build step 04 is running: the build ends
        by replacing plan.json, so no check of what plan.json holds now
        says what the write would read a moment later."""
        if not confirmed or not build_run.running:
            return None
        return JSONResponse(
            {"error": "a build is running, and it replaces plan.json when it finishes -- "
                      "wait for it, read what it built, and arm the write again. Nothing "
                      "was written."},
            status_code=409,
        )

    @app.middleware("http")
    async def _no_static_caching(request, call_next):
        # This page and its assets change as this prototype does -- a
        # browser that caches shell.js/styles.css/shell.html without
        # revalidating would keep showing an old bug (or an old fix) after
        # a `git pull` until a manual hard-refresh, on a page whose whole
        # job is showing what's true *right now*. ETag-based revalidation
        # (StaticFiles computes one for everything under /static) keeps
        # this cheap -- a 304 on every unchanged load, a real fetch only
        # when the file actually changed. `/` is assembled per request (it
        # splices its startup JSON into the file on disk) so it carries no
        # ETag and always re-sends; it is one small HTML document from
        # localhost, and a page that served a stale plan or a stale
        # console address would be worse.
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/app", include_in_schema=False)
    def shell_moved():
        # The shell lived here until an earlier change moved it to `/`. A
        # redirect rather than a 404 because bookmarks, shell history and
        # docs already read point at `/app` -- including `/app#apply`,
        # which lands on `/#apply`: a browser keeps the fragment across a
        # redirect whose Location has none. 307, not 301: a permanent
        # redirect is cached by the browser, and one cached while this
        # branch was checked out would send `/app` to `/` on an older
        # checkout too, where `/` was a different page.
        return RedirectResponse("/", status_code=307)

    @app.get("/")
    def shell_page():
        # Mockup version H's shell: ONE page carrying
        # three modes -- Build, Apply, Watch -- that switch client-side
        # under shared chrome. It moved here from `/app`,
        # when Watch moved in and the old standalone Watch page at `/`
        # was retired; `/setup` -- the plan viewer -- went, when
        # step 04 took its renderer.
        #
        # Everything the first paint needs rides in as one embedded blob
        # rather than a handful of fetches. First paint is the reason: a
        # bundle name and a console address that appear a moment after
        # the page does are values someone can act on before they settle
        # -- and the console address seeds Watch's IP box, where a
        # value that fills in after the box is on screen is one an
        # operator can start typing into and then watch get overwritten.
        html = (_STATIC_DIR / "shell.html").read_text(encoding="utf-8")
        html = _embed_startup_json(
            html, "initial-shell",
            {
                # Which server process drew this page -- compared against
                # `GET /api/status`'s `instance` for as long as it is open.
                "instance": app.state.instance_id,
                "install": app.state.install,
                "bundle": _bundle_payload(app.state.bundle) if app.state.bundle else None,
                "build": _build_payload(
                    app.state.bundle, app.state.conventions_path, app.state.build_overrides,
                ),
                "console": app.state.console_defaults,
                # The watch-conditions file the server holds, or null: with
                # no show open, Watch asks for one only when this says there
                # is one (or the page has loaded one itself).
                "watch_conditions_path": app.state.watch_conditions_path,
                # Where the file browser starts while no
                # bundle is open -- `[workspace] default`, or null.
                "workspace": app.state.workspace,
                "findings": app.state.findings,
                # The words for the dock's INFO rows, one per
                # code -- `finding_groups.CODE_SUMMARIES`, so the page has
                # no table of its own to drift from it.
                "finding_codes": {code: list(words) for code, words
                                  in finding_groups.CODE_SUMMARIES.items()},
                # The INFO codes, and the plan-note sources,
                # that are build details -- how the reply was read, shown
                # apart from the choices. `finding_groups` decides; the
                # page only reads the lists.
                "build_detail_codes": sorted(finding_groups.BUILD_DETAIL_CODES),
                "detail_note_sources": sorted(finding_groups.DETAIL_NOTE_SOURCES),
                # Build step 04: the plan on screen at first paint, and
                # whatever build is running or last ran -- a reload
                # mid-build must land on "running", not on a blank step.
                "plan": _plan_payload_now(app.state.plan, app.state.plan_path)
                if app.state.plan is not None else None,
                "run": build_run.status(),
                # Apply: same reasoning as `run` above --
                # a reload part way through an apply must land on
                # "running" with the log, not on a blank Apply screen
                # that invites someone to press the button again.
                "apply": apply_run.status(),
                # The Run button's model choices, from the one table
                # `build --console-model` itself takes its choices from.
                "console_models": [
                    {"id": model, "label": console_facts.CONSOLE_MODELS[model]["label"]}
                    for model in sorted(console_facts.CONSOLE_MODELS)
                ],
            },
            "/static/shell.js",
        )
        return HTMLResponse(html)

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/api/status")
    def api_status():
        # The watch session's state, plus the two things every mode of the
        # page checks to know it is still talking to the server it was
        # drawn by: this process's `instance` id, and the bundle it has
        # open. shell.js polls this; a change in either puts up the
        # stale-page banner.
        return {**session.status(),
                "instance": app.state.instance_id,
                "bundle": str(app.state.bundle.directory) if app.state.bundle else None}

    @app.get("/api/plan")
    def api_plan():
        # No plan loaded (no `--plan` at startup, and no successful
        # `POST /api/plan/load` yet) -- a 404 with a small, documented
        # body the frontend checks for, not a bare 404 with no shape.
        if app.state.plan is None:
            return JSONResponse({"error": "no plan loaded"}, status_code=404)
        return _plan_payload_now(app.state.plan, app.state.plan_path)

    @app.post("/api/plan/load")
    def api_plan_load(req: PlanLoadRequest, request: Request):
        # The in-browser equivalent of restarting `atoo ui` with a
        # new `--plan` -- read-only (this only ever opens the path for
        # reading), and returns a clean JSON error body rather than
        # raising, so a bad path or invalid JSON is a 400, not a 500.
        refusal = _local_only(request) or _refuse_demo("loading another plan")
        if refusal is not None:
            return refusal
        plan, error = _load_plan_from_path(req.path)
        if error is not None:
            return JSONResponse({"error": error}, status_code=400)
        app.state.plan = plan
        app.state.plan_path = req.path
        return _plan_payload_now(app.state.plan, app.state.plan_path)

    @app.get("/api/bundle")
    def api_bundle():
        # No bundle open (no `--show` at startup, and no successful
        # `POST /api/bundle/open` yet) -- a 404 with a small, documented
        # body, the same shape `GET /api/plan` and
        # `GET /api/watch-conditions` answer with. Not an empty-object
        # 200: "no bundle" and "a bundle with nothing in it" are
        # different states and the bundle bar renders them differently.
        if app.state.bundle is None:
            return JSONResponse({"error": "no show bundle open"}, status_code=404)
        return _bundle_payload(app.state.bundle)

    @app.post("/api/bundle/open")
    def api_bundle_open(req: BundleOpenRequest, request: Request):
        # The in-browser equivalent of restarting `atoo ui` with a
        # different `--show` -- version H's `Change...` button. Read-only
        # unless `create` is set, and a clean JSON error body rather than
        # a raised exception, same as `POST /api/plan/load`.
        #
        # `create` is the `New show...` button, and it makes a DIRECTORY,
        # never a file: `atoo build --show new-show/` on a folder
        # holding only `input.csv` is the first thing anyone does, and
        # `bundle.load` accepts an empty directory precisely so that
        # works. Pointing `New show...` at a directory that already exists
        # is not refused -- it opens it, and says `created: false` so the
        # page can tell the operator it adopted something rather than
        # starting clean. Silently reporting a fresh bundle over someone
        # else's show is the outcome worth spending a boolean to avoid.
        refusal = _local_only(request)
        if refusal is not None:
            return refusal
        target = Path(req.directory).expanduser()
        if _inside_demo(target):
            # The demo show is Demo, chosen in the console
            # dialog, and the two always go together -- opened here it
            # would be the demo show on a real desk.
            return JSONResponse(
                {"error": "that is Atoo's packaged demo show -- choose Demo in the "
                          "bundle bar's console dialog (Console: Change…) to open it",
                 "demo": True},
                status_code=400,
            )
        created = False
        if req.create and not target.exists():
            try:
                target.mkdir(parents=True)
            except OSError as exc:
                return JSONResponse(
                    {"error": f"couldn't create show bundle directory {req.directory!r}: "
                              f"{exc.strerror}"},
                    status_code=400,
                )
            created = True

        try:
            show = bundle.load(target)
        except bundle.BundleError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Opening or creating another show leaves Demo.
        _leave_demo_console()
        _open_show(show)
        # The console rides along: leaving Demo changed it, and the bar
        # redraws from this rather than asking again.
        return {**_bundle_payload(show), "created": created,
                "console": dict(app.state.console_defaults or {})}

    # ---- Build steps 01-03 (version H, phase 2) ------------------------

    @app.get("/api/build/sources")
    def api_build_sources():
        # The three files a build reads, whole: each tile's path, state
        # and contents, the two-layer conventions stack, and every
        # finding reading them produced.
        #
        # **There is no 404 here, and that is deliberate** -- unlike
        # `GET /api/plan` and `GET /api/bundle`, which answer "nothing
        # loaded" with a documented 404 body because there is genuinely
        # nothing to render. Three tiles are this screen's own furniture
        # and they are always drawn; "Missing" is one of the three states
        # version H gives them, not an absence of an answer. A 404 here
        # would make an empty bundle indistinguishable from a broken
        # endpoint, and the page would have to invent the tiles anyway.
        return _build_payload(
            app.state.bundle, app.state.conventions_path, app.state.build_overrides,
        )

    @app.get("/api/build/validate-patch")
    def api_build_validate_patch(value: str = "", model: Optional[str] = None):
        # Step 02's Patch cell, checked before it goes into the row
        # . Read-only: it reads nothing
        # from disk and writes nothing. The verdict is
        # `input_list.check_patch` -- the input list's own parser and
        # `console_facts`' bound, not a second grammar in the browser.
        # Always 200 with `ok` true or false; a 400 only for a model this
        # project does not know.
        model = (model or "").strip() or None
        try:
            return input_list_module.check_patch(value, model)
        except console_facts.UnknownConsoleModel:
            return JSONResponse(
                {"error": f"unknown console model {model!r} -- one of "
                          f"{', '.join(sorted(console_facts.CONSOLE_MODELS))}"},
                status_code=400,
            )

    @app.get("/api/build/presets")
    def api_build_presets():
        # Step 02's Preset chooser: the names in the
        # preset library a build would use -- `ui --presets`, else the
        # `[presets] default` in ~/.atoo.config. Read-only. Always
        # 200: no library configured, or one that cannot be read, is a
        # state the column shows (it still takes free text), not an error.
        return _preset_library_state(app.state.presets_path)

    @app.post("/api/build/sources/load")
    def api_build_sources_load(req: BuildSourceLoadRequest, request: Request):
        # A tile's "Change file". Read-only -- this only ever opens a path
        # for reading -- and a clean JSON error body rather than a raised
        # exception, same as `POST /api/plan/load`.
        #
        # Two failures are told apart on purpose, and the split is the
        # one the judgement-vs-patching rule draws:
        #
        # * **A path that is not there, or cannot be read, is a 400.** The
        #   operator typed something wrong, and quietly replacing a
        #   working file with an empty "Missing" tile would lose what they
        #   had for a typo.
        # * **A file that is there and will not parse is a 200**, with the
        #   parse failure as a finding in the dock. That is the file's
        #   content being wrong, which is exactly what this screen is for
        #   showing -- refusing it would leave the operator with an error
        #   toast and no way to look at what they just pointed at.
        # Change file on the demo show, or a tile pointed at a
        # packaged demo file from another show (which Save would then
        # write), is refused.
        refusal = _local_only(request) or _refuse_demo("Change file", req.path)
        if refusal is not None:
            return refusal
        if req.slot not in _BUILD_SLOTS:
            return JSONResponse(
                {"error": f"unknown build source {req.slot!r} -- "
                          f"known: {', '.join(_BUILD_SLOTS)}"},
                status_code=400,
            )
        target = Path(req.path).expanduser()
        if not target.is_file():
            return JSONResponse(
                {"error": f"no file at {req.path!r}"
                          + (" -- that is a directory" if target.is_dir() else "")},
                status_code=400,
            )
        try:
            target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return JSONResponse(
                {"error": f"couldn't read {req.path!r}: {exc}"}, status_code=400,
            )

        # The bundle's own file, chosen by path (the file browser's "Keep
        # the bundle's", or someone browsing into the bundle): that is no
        # override at all, and saying so keeps step 03 buildable -- `build`
        # refuses an instructions override that is not the bundle's file.
        show = app.state.bundle
        own = show.path(_BUILD_SLOT_FILES[req.slot]) if (
            show is not None and req.slot in _BUILD_SLOT_FILES) else None
        if own is not None and _same_file(target, own):
            app.state.build_overrides[req.slot] = None
        else:
            app.state.build_overrides[req.slot] = str(target)
        return _build_payload(
            app.state.bundle, app.state.conventions_path, app.state.build_overrides,
        )

    # ---- Creating a blank conventions / instructions file (2026-09-25) --
    # Without these there is no way to introduce either one except by creating
    # a file outside the UI and manually adding it to either the user
    # preferences or an environment variable or the show bundle.
    #
    # These write FILES -- a new, empty Markdown file, and on request one line
    # of ~/.atoo.config -- and never a console; they are nowhere near
    # Apply's run endpoints and share nothing with them. Each one refuses
    # to overwrite anything, and every refusal is a JSON error, not a 500.

    def _new_file_target(raw: str) -> "tuple[Path | None, JSONResponse | None]":
        text = (raw or "").strip()
        if not text:
            return None, JSONResponse({"error": "give a path for the new file"},
                                      status_code=400)
        if any(ord(ch) < 32 for ch in text):
            return None, JSONResponse({"error": "that path has a control character in it"},
                                      status_code=400)
        target = config.expand_home(text)
        if not target.is_absolute():
            target = Path.cwd() / target
        if target.suffix.lower() != ".md":
            return None, JSONResponse(
                {"error": f"{text!r} does not end in .md -- a conventions file is Markdown "
                          f"(e.g. {DEFAULT_NEW_CONVENTIONS})"},
                status_code=400,
            )
        if target.exists():
            what = "a folder" if target.is_dir() else "a file"
            return None, JSONResponse(
                {"error": f"there is already {what} at {_display_path(target, None)} -- "
                          "nothing was written. Pick a new name, or press Change file to "
                          "use the one that is there."},
                status_code=409,
            )
        if not target.parent.is_dir():
            return None, JSONResponse(
                {"error": f"there is no folder {_display_path(target.parent, None)} -- "
                          "nothing was written. Create the folder first, or pick a path in "
                          "one that exists."},
                status_code=400,
            )
        return target, None

    def _write_new(target: Path, text: str) -> "JSONResponse | None":
        # "x": create, and fail if anything got there first -- the check
        # above and this write are two moments, and the second one is the
        # one that must never overwrite.
        try:
            with open(target, "x", encoding="utf-8") as handle:
                handle.write(text)
        except FileExistsError:
            return JSONResponse(
                {"error": f"there is already a file at {_display_path(target, None)} -- nothing "
                          "was written"},
                status_code=409,
            )
        except OSError as exc:
            return JSONResponse(
                {"error": f"couldn't write {target}: {exc.strerror}"}, status_code=400,
            )
        return None

    @app.post("/api/build/conventions/new")
    def api_build_conventions_new(req: NewConventionsRequest, request: Request):
        # Step 01's "New file". Creates an EMPTY house conventions file
        # (the template is a suggestion only -- it is
        # `conventions_example`, shown beside the editor, and written only
        # if the engineer inserts it and saves), and points step 01 at it for this session, exactly as Change file
        # would. `make_default` also names it in ~/.atoo.config --
        # adding a default, never replacing a different one.
        refusal = _local_only(request) or _refuse_demo("New file", req.path)
        if refusal is not None:
            return refusal
        target, refusal = _new_file_target(req.path)
        if refusal is not None:
            return refusal
        refusal = _write_new(target, "")
        if refusal is not None:
            return refusal

        app.state.build_overrides["conventions"] = str(target)
        display = _display_path(target, None)
        messages = [f"Created {display}, empty, and step 01 now shows it. Write your house "
                    "style in the editor -- the Example beside it is there to copy from."]
        config_write = None
        if req.make_default:
            try:
                config_write = config.set_default_conventions(target)
            except config.ConfigWriteError as exc:
                config_write = {"status": "refused", "config_path": str(config.config_path()),
                                "value": config.config_value_for(target), "previous": None,
                                "message": str(exc)}
            if config_write["status"] in ("created", "added", "unchanged"):
                # The session's own idea of the config default follows the
                # file: opening another bundle falls back to it from now on.
                app.state.conventions_path = str(target)
            messages.append(config_write["message"])
        else:
            messages.append(f"{_display_path(config.config_path(), None)} was not changed; "
                            "this file is used for this session only.")
        return {
            **_build_payload(app.state.bundle, app.state.conventions_path,
                             app.state.build_overrides),
            "created": {"slot": "conventions", "path": str(target), "display_path": display},
            "config_write": config_write,
            "message": " ".join(messages),
        }

    @app.post("/api/config/conventions-default")
    def api_config_conventions_default(req: ConventionsDefaultRequest, request: Request):
        # Name an existing file as ~/.atoo.config's [conventions]
        # default, changing nothing else in that file. A different default
        # already there is a 409 unless `replace` is set -- which the page
        # sends only from a button that names the file being replaced.
        refusal = (_local_only(request)
                   or _refuse_demo("changing the default conventions file", req.path))
        if refusal is not None:
            return refusal
        target = config.expand_home((req.path or "").strip())
        if not target.is_absolute():
            target = Path.cwd() / target
        if not target.is_file():
            return JSONResponse({"error": f"no file at {req.path!r}"}, status_code=400)
        try:
            result = config.set_default_conventions(target, replace=req.replace)
        except config.ConfigWriteError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if result["status"] == "kept":
            return JSONResponse({"error": result["message"], "config_write": result},
                                status_code=409)
        app.state.conventions_path = str(target)
        return {
            **_build_payload(app.state.bundle, app.state.conventions_path,
                             app.state.build_overrides),
            "config_write": result,
            "message": result["message"],
        }

    @app.post("/api/build/instructions/new")
    def api_build_instructions_new(request: Request,
                                   req: Optional[NewInstructionsRequest] = None):
        refusal = _setup_only(request) or _refuse_demo("New file")
        if refusal is not None:
            return refusal
        # Step 03's New file (and its panel's "New instructions.md"): an
        # EMPTY one in the open bundle, never over one that is there. The
        # template is a suggestion only (`instructions_example`, beside the
        # editor). The
        # bundle's own file is the only one `atoo build` reads, so a
        # step 03 pointed elsewhere by Change file is pointed back at it.
        #
        # It writes into the bundle, so it names the bundle the page
        # showed (`expected_bundle`, FR-6.11): a tab left
        # open across a restart onto another show must not drop a blank
        # instructions.md into a show it is not showing. Absent is refused,
        # as for every other write from the page into a bundle.
        show = app.state.bundle
        if show is None:
            return JSONResponse(
                {"error": f"no show bundle open -- {bundle.INSTRUCTIONS} lives in one. Open "
                          "a bundle (or New show…) first."},
                status_code=400,
            )
        stale = _stale_bundle(req.expected_bundle if req else None, show, True)
        if stale is not None:
            return stale
        target = show.path(bundle.INSTRUCTIONS)
        if target.exists():
            return JSONResponse(
                {"error": f"{show.directory.name or show.directory} already has an "
                          f"{bundle.INSTRUCTIONS} -- nothing was written"},
                status_code=409,
            )
        refusal = _write_new(target, "")
        if refusal is not None:
            return refusal
        app.state.build_overrides["instructions"] = None
        display = _display_path(target, show)
        return {
            **_build_payload(show, app.state.conventions_path, app.state.build_overrides),
            "created": {"slot": "instructions", "path": str(target), "display_path": display},
            # The wording, less the headings a new file no longer
            # gets (2026-09-28).
            "message": f"Created {display}, empty. Instructions override conventions: "
                       "include only what differs for this show. The Example beside the "
                       "editor is there to copy from.",
        }

    # ---- The file browser, and copying a file into the bundle ----------
    # a real modal file browser
    # for selecting existing files, or creating a new show directory or a
    # new file. A page cannot see the disk, so the modal
    # (web/static/filebrowser.js) asks for one folder at a time here. The
    # listing and the folder it may create are `atoo/fsbrowse.py`.
    #
    # "If I create a new show in the UI, and then open an input
    # list from somewhere, the program should copy the input list into the
    # bundle and notify the user that it has done so." That is
    # `POST /api/bundle/adopt`, below.

    def _local_only(request: Request,
                    what: str = "the file browser, and anything that opens a file by path,"
                    ) -> "JSONResponse | None":
        """The file browser, and every endpoint that opens a path the
        request names, answers this laptop's own browser only. See
        fsbrowse's docstring: `--host` may put the page on the venue LAN,
        and a second machine there must not be able to page through this
        one's disk -- nor have it read, or write, a file at a path of its
        choosing. The Host check is the DNS-rebinding half.

        A Watch page opened from a phone names no path of its own, so it
        keeps working; see `_local_only_unless_loaded` for the one path it
        does send back."""
        client = request.client.host if request.client else None
        if not fsbrowse.client_is_local(client):
            return JSONResponse(
                {"error": f"{what} "
                          "answers only a browser on this machine "
                          f"(this request came from {client or 'an unknown address'}) -- "
                          "open Atoo on the laptop it is running on"},
                status_code=403,
            )
        if not fsbrowse.host_is_local(request.headers.get("host")):
            return JSONResponse(
                {"error": f"{what} "
                          "answers only when the page is opened as "
                          "http://127.0.0.1 or http://localhost -- this request named "
                          f"{request.headers.get('host') or 'no host'}"},
                status_code=403,
            )
        return None

    def _local_only_unless_loaded(request: Request, path: str) -> "JSONResponse | None":
        """`_local_only`, except for the watch-conditions file the server
        already holds. The Watch page sends that path back on Start and on
        Save (it is what the panel shows after a load), so a phone on the
        LAN watching the show must not be refused for it: the server chose
        that file, not the phone. Any other path is `_local_only`'s."""
        if app.state.watch_conditions_path is not None and path == app.state.watch_conditions_path:
            return None
        return _local_only(request)

    def _watch_bundle_file() -> "dict | None":
        """The open bundle's watch.json, as Watch's file row needs it: where it is, its name under the bundle, and whether
        it exists -- New file is offered only when it does not, as step
        03's is for instructions.md. None with no bundle open."""
        show = app.state.bundle
        if show is None:
            return None
        target = show.path(bundle.WATCH_CONDITIONS)
        return {"path": str(target),
                "display_path": _display_path(target, show),
                "present": target.is_file()}

    def _watch_payload() -> dict:
        """`GET /api/watch-conditions`'s answer, which every endpoint that
        changes Watch's file answers with too: the file in use, its
        conditions, and the bundle's own watch.json (`_watch_bundle_file`)."""
        return {"path": app.state.watch_conditions_path,
                "watch_conditions": app.state.watch_conditions,
                "bundle_file": _watch_bundle_file()}

    def _setup_only(request: Request) -> "JSONResponse | None":
        """Every write the Setup side makes -- to the console (apply, patch,
        undo) or to the show's files (build, the editors) -- answers
        this laptop's own browser only. `--host` puts the page
        on the venue LAN so a phone can Watch; a second
        machine there watches, it does not change the desk. Arming is a
        request field, so without this any machine that could reach the
        page could write. Watch's own controls (the console address, ping,
        start/stop) are not Setup writes and still answer the LAN."""
        return _local_only(request, "writing to the console or the show's files")

    @app.middleware("http")
    async def _refuse_cross_site_writes(request, call_next):
        # Every endpoint that writes is a POST, and a web page on some
        # other site that the operator has open in the same browser can
        # make a POST to 127.0.0.1:8420 without any help from us. Nothing stopped that but an accident of FastAPI:
        # a JSON body model only parses `Content-Type: application/json`,
        # which a cross-site page cannot send without a CORS preflight this
        # server never answers. An endpoint with no body at all -- step
        # 03's New file was one -- had not even that.
        #
        # So a write from a browser must come from this page's own origin.
        # Browsers say where a request came from; scripts (curl, the test
        # suite) send neither header and are not browsers, so they pass.
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            site = (request.headers.get("sec-fetch-site") or "").lower()
            origin = request.headers.get("origin")
            refused = None
            if site and site not in ("same-origin", "none"):
                refused = f"it came from another site (Sec-Fetch-Site: {site})"
            elif origin is not None:
                host = request.headers.get("host") or ""
                if origin.rstrip("/") not in (f"http://{host}", f"https://{host}"):
                    refused = f"it came from {origin}, not from this page ({host})"
            if refused:
                return JSONResponse(
                    {"error": f"refused a write from another web page -- {refused}. "
                              "Atoo's own page is the only page that may change "
                              "anything here. Nothing was written."},
                    status_code=403,
                )
        return await call_next(request)

    @app.get("/api/fs/list")
    def api_fs_list(request: Request, path: Optional[str] = None, kind: str = "any",
                    hidden: bool = False, base: Optional[str] = None):
        # One folder: names, types, sizes and mtimes -- never a file's
        # contents. A path that is a FILE lists its folder with the file
        # `selected`. A folder that is not there or cannot be read is a 400
        # the modal shows in place of the listing, with `parent` so it can
        # offer a way back up; never a 500.
        refusal = _local_only(request)
        if refusal is not None:
            return refusal
        try:
            return fsbrowse.list_directory(path, kind=kind, show_hidden=hidden, base=base)
        except fsbrowse.ListingError as exc:
            parent = None
            try:
                parent = str(fsbrowse.resolve_path(path, Path(base) if base else None).parent)
            except fsbrowse.ListingError:
                pass
            return JSONResponse({"error": str(exc), "parent": parent}, status_code=400)

    @app.post("/api/fs/mkdir")
    def api_fs_mkdir(req: FsMkdirRequest, request: Request):
        # The modal's New folder: one folder, in one that exists, never over
        # anything. Answers the new folder's listing, so the modal opens it.
        refusal = _local_only(request)
        if refusal is not None:
            return refusal
        # Never inside the packaged demo show. Anywhere else is
        # fine, demo open or not -- New show... from the demo is how out.
        candidates = [req.path]
        if req.base:
            candidates.append(str(Path(req.base).expanduser() / req.path))
        if any(_inside_demo(c) for c in candidates):
            return _demo_refusal("New folder")
        try:
            created = fsbrowse.make_folder(req.path, base=req.base)
        except FileExistsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except fsbrowse.ListingError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        listing = fsbrowse.list_directory(str(created), kind="folders")
        return {**listing, "created": str(created),
                "message": f"Created the folder {fsbrowse.display_path(created)}."}

    @app.post("/api/bundle/adopt")
    def api_bundle_adopt(req: BundleAdoptRequest, request: Request):
        # An input list or instructions file chosen from
        # outside the open bundle is COPIED in, as the bundle's own
        # input.csv / instructions.md, and the page says so. Watch's watch-conditions file goes the same way, as the
        # bundle's watch.json (slot `watch`) -- the same copy, the same
        # `.bak`, the same INFO -- and is validated BEFORE it is copied:
        # a file Watch could not load must not displace one it can. A show bundle
        # is meant to hold its show, and `atoo build` reads
        # instructions only from the bundle -- a step 03 pointed elsewhere
        # could not be built at all.
        #
        # * The bundle has no such file: copy it, never over anything.
        # * It has one, byte-identical: nothing to copy; step shows it.
        # * It has a different one: 409, saying what is there, unless
        #   `replace` -- the modal's "Replace the bundle's". The one it
        #   replaces is kept as `backups/<name>.bak` -- in a folder, since
        #   only plan files and the hand-authored inputs sit at a bundle's
        #   top level.
        #
        # The house conventions file is refused: it stays outside the
        # bundle on purpose.
        refusal = _local_only(request) or _refuse_demo("Change file")
        if refusal is not None:
            return refusal
        if req.slot not in _ADOPT_SLOT_FILES:
            why = (" -- the house conventions file stays outside the bundle on purpose; "
                   "Change file on step 01 points at it instead" if req.slot == "conventions"
                   else "")
            return JSONResponse(
                {"error": f"{req.slot!r} is not a file a bundle holds a copy of"
                          f"{why}. One of: {', '.join(_ADOPT_SLOT_FILES)}"},
                status_code=400,
            )
        show = app.state.bundle
        if show is None:
            return JSONResponse(
                {"error": "no show bundle open to copy it into -- open one (or New show…) "
                          "first"},
                status_code=400,
            )
        stale = _stale_bundle(req.expected_bundle, show, True)
        if stale is not None:
            return stale

        filename = _ADOPT_SLOT_FILES[req.slot]
        try:
            source = fsbrowse.resolve_path(req.path)
        except fsbrowse.ListingError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not source.is_file():
            return JSONResponse(
                {"error": f"no file at {req.path!r}"
                          + (" -- that is a folder" if source.is_dir() else "")},
                status_code=400,
            )
        try:
            data = source.read_bytes()
            data.decode("utf-8")
        except UnicodeDecodeError:
            return JSONResponse(
                {"error": f"{fsbrowse.display_path(source)} is not a text file -- nothing "
                          "was copied"},
                status_code=400,
            )
        except OSError as exc:
            return JSONResponse(
                {"error": f"couldn't read {fsbrowse.display_path(source)}: "
                          f"{exc.strerror or exc}"},
                status_code=400,
            )

        target = show.path(filename)
        bundle_name = show.directory.name or str(show.directory)
        target_display = f"{bundle_name}/{filename}"
        source_display = fsbrowse.display_path(source)

        watch_conditions = None
        if req.slot == "watch":
            from atoo.watch_conditions import WatchConditionsError, parse_watch_conditions
            try:
                watch_conditions = parse_watch_conditions(data.decode("utf-8"),
                                                          source=source_display)
            except WatchConditionsError as exc:
                return JSONResponse(
                    {"error": f"{exc} -- nothing was copied into {target_display}"},
                    status_code=400,
                )

        def answer(copied: bool, message: str, **extra) -> dict:
            if req.slot == "watch":
                # Watch's answer is `GET /api/watch-conditions`'s shape:
                # the bundle's file, now the one Watch is using.
                app.state.watch_conditions = watch_conditions
                app.state.watch_conditions_path = str(target)
                payload = _watch_payload()
            else:
                app.state.build_overrides[req.slot] = None
                payload = _build_payload(show, app.state.conventions_path,
                                         app.state.build_overrides)
            result = {**payload, "copied": copied, "slot": req.slot,
                      "source": str(source), "target": str(target),
                      "target_display": target_display, "message": message, **extra}
            if copied:
                # Provenance, where a person will see it: the dock. It
                # lives as long as the page does -- the bundle has no
                # manifest to record it in.
                result["finding"] = Diagnostic(
                    severity=Severity.INFO, code="bundle.copied-in",
                    message=message, where=target_display, source="ui",
                    line=str(source),
                ).to_dict()
            return result

        if _same_file(source, target):
            return answer(False, f"That is {target_display} itself -- the bundle's own copy; "
                                 "nothing was copied.")

        if target.exists() or target.is_symlink():
            try:
                existing = target.read_bytes()
            except OSError:
                existing = None
            if existing == data:
                return answer(False, f"{target_display} already holds exactly what "
                                     f"{source_display} holds -- nothing was copied.")
            if not req.replace:
                try:
                    st = target.stat()
                    there = {"path": str(target), "display_path": target_display,
                             "size": st.st_size, "mtime": st.st_mtime}
                except OSError:
                    there = {"path": str(target), "display_path": target_display,
                             "size": None, "mtime": None}
                st_src = source.stat()
                return JSONResponse(
                    {"error": f"{bundle_name} already has {_a_or_an(filename)} {filename} -- "
                              "replace it with "
                              f"{source_display}, or keep the bundle's? Nothing was copied.",
                     "exists": there,
                     "chosen": {"path": str(source), "display_path": source_display,
                                "size": st_src.st_size, "mtime": st_src.st_mtime}},
                    status_code=409,
                )

        backup = None
        tmp = target.with_name(f".{filename}.atoo-copy-{secrets.token_hex(4)}")
        try:
            with open(tmp, "xb") as handle:
                handle.write(data)
            shutil.copymode(source, tmp)
            if target.exists():
                backup = target.parent / bundle.BACKUPS / (filename + ".bak")
                backup.parent.mkdir(exist_ok=True)
                shutil.copy2(target, backup)
                os.replace(tmp, target)
            else:
                # Never over a file that appeared since the check above:
                # a hard link fails if the name is taken, where a rename
                # would not.
                try:
                    os.link(tmp, target)
                except FileExistsError:
                    return JSONResponse(
                        {"error": f"{target_display} appeared while copying -- nothing was "
                                  "copied; try again"},
                        status_code=409,
                    )
                except OSError:
                    with open(target, "xb") as handle:
                        handle.write(data)
                finally:
                    if tmp.exists():
                        tmp.unlink()
        except FileExistsError:
            return JSONResponse(
                {"error": f"{target_display} appeared while copying -- nothing was copied; "
                          "try again"},
                status_code=409,
            )
        except OSError as exc:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            return JSONResponse(
                {"error": f"couldn't copy into {target_display}: {exc.strerror or exc}"},
                status_code=400,
            )

        message = (f"Copied {source_display} into {target_display} -- the bundle now owns "
                   "its copy; edits to the original won't reach it.")
        if backup is not None:
            message += (f" The {filename} it replaced was kept as "
                        f"{bundle_name}/{bundle.BACKUPS}/{backup.name}.")
        return answer(True, message, replaced=backup is not None,
                      backup=str(backup) if backup is not None else None)

    # ---- Editing the three files a build reads ----
    # Save on step 01 (the house conventions, behind "Edit house
    # style..."), step 03 (instructions.md) and step 02 (input.csv). Each
    # writes ONE file -- the one that step shows, resolved here, never a
    # path from the request -- and only the bytes that changed
    # (`source_edit`). Three refusals come first, all 409s that write
    # nothing: the page is stale (FR-6.11), the page read a different
    # file, or the file changed on disk since the page read it (these files are
    # also edited in other editors). They write files only; nothing here
    # goes near a console.

    save_lock = threading.Lock()

    def _stale_editor(expected: "str | None", show, nothing: str) -> "JSONResponse | None":
        """A save (or a build) from a page showing a different show bundle
        than the server has open -- `_stale_bundle`'s check, in a save's
        words. A page with no bundle open sends none, and matches a server
        with none."""
        text = (expected or "").strip()
        if show is None:
            if not text:
                return None
            return _refuse_stale(
                f"this page shows the show bundle {text}, but the server has no bundle open "
                f"now -- it was restarted, or another tab closed it. {nothing} -- reload the "
                "page (copy anything you typed first).", "bundle")
        if not text:
            return _refuse_stale(
                "this save does not say which show bundle the page shows "
                f"(`expected_bundle`). The server has {show.directory} open. {nothing} -- "
                "reload the page (copy anything you typed first).", "bundle")
        try:
            same = Path(text).expanduser().resolve() == show.directory.resolve()
        except OSError:
            same = False
        if same:
            return None
        return _refuse_stale(
            f"this page shows the show bundle {text}, but the server now has "
            f"{show.directory} open -- it was restarted on another bundle, or another tab "
            f"opened one. {nothing} -- reload the page (copy anything you typed first).",
            "bundle")

    def _changed_on_disk(slot: str, source: dict, req) -> "JSONResponse | None":
        """The file the page read is not the file on disk now: another
        path, or other bytes. Never written over."""
        label = source.get("display_path") or source.get("path") or slot
        if not (req.expected_sha256 or "").strip():
            return JSONResponse(
                {"error": f"this save does not say which version of {label} the page read "
                          "(`expected_sha256`), so it cannot tell whether the file changed "
                          "since. Nothing was saved -- reload the file and edit again.",
                 "stale": "file", "slot": slot}, status_code=409)
        if req.expected_path and source.get("path") and \
                not conventions_ref.same_file(req.expected_path, source["path"]):
            return JSONResponse(
                {"error": f"this page read {req.expected_path}, but that step now shows "
                          f"{source['path']}. Nothing was saved -- reload it.",
                 "stale": "file", "slot": slot}, status_code=409)
        if source.get("sha256") != req.expected_sha256.strip():
            return JSONResponse(
                {"error": f"{label} changed on disk after this page read it -- edited in "
                          "another program, or saved from another tab. Nothing was saved, so "
                          "that edit is kept. Your changes are still in the boxes: copy what "
                          "you need, press Reload to read the file as it is now, and make them "
                          "again.",
                 "stale": "file", "slot": slot,
                 "current_sha256": source.get("sha256")}, status_code=409)
        return None

    def _outside_bundle(slot: str, source: dict, show) -> "JSONResponse | None":
        """Step 02 and 03 edit the bundle's own input.csv and
        instructions.md. A tile pointed at another file by Change file is
        not edited from here."""
        own = show.path(bundle.INPUT_LIST if slot == "input_list" else bundle.INSTRUCTIONS) \
            if show is not None else None
        if own is not None and conventions_ref.same_file(source.get("path"), own):
            return None
        return JSONResponse(
            {"error": f"this step is showing {source.get('path') or 'no file'}, not the show "
                      f"bundle's own {own.name if own else 'file'} -- the page edits only the "
                      "bundle's files. Reopen the bundle to drop the Change file override, or "
                      "edit that file in your own editor."},
            status_code=400)

    def _write_text(path: Path, text: str) -> "JSONResponse | None":
        try:
            # Bytes, not text mode: text mode would translate "\n" to the
            # platform's line ending and undo the splice's care.
            path.write_bytes(text.encode("utf-8"))
        except OSError as exc:
            return JSONResponse({"error": f"couldn't write {path}: {exc.strerror}"},
                                status_code=400)
        return None

    def _rows_summary(summary: dict) -> dict:
        # `source_edit.splice_input_list`'s account, under names that do not
        # collide with `saved.changed` (a boolean: was the file written).
        return {"rows_changed": summary["changed"], "rows_added": summary["added"],
                "rows_removed": summary["removed"], "columns_added": summary["columns_added"]}

    def _payload_after_save(saved: dict, message: str) -> dict:
        return {**_build_payload(app.state.bundle, app.state.conventions_path,
                                 app.state.build_overrides),
                "saved": saved, "message": message}

    @app.post("/api/build/sections/save")
    def api_build_sections_save(req: SectionsSaveRequest, request: Request):
        refusal = _setup_only(request) or _refuse_demo("Save")
        if refusal is not None:
            return refusal
        if req.slot not in ("conventions", "instructions"):
            return JSONResponse(
                {"error": f"this saves conventions or instructions, not "
                          f"{req.slot!r}"}, status_code=400)
        if req.text is None:
            return JSONResponse(
                {"error": "a save sends the whole file as `text` -- nothing was saved"},
                status_code=400)
        show = app.state.bundle
        refusal = _stale_editor(req.expected_bundle, show, "Nothing was saved")
        if refusal is not None:
            return refusal
        if req.slot == "conventions" and not req.house_confirmed:
            return JSONResponse(
                {"error": "a save to the house conventions file must say it means the house "
                          "file (house_confirmed) -- every show that names it builds from it. "
                          "Nothing was saved."},
                status_code=400)
        with save_lock:
            sources = _build_payload(show, app.state.conventions_path, app.state.build_overrides)
            source = sources[req.slot]
            if not source.get("present"):
                return JSONResponse(
                    {"error": f"there is no {req.slot} file to save into -- "
                              + ("New file on the tile starts an empty one."
                                 if req.slot == "conventions" or show is not None
                                 else "open a show bundle first.")},
                    status_code=400)
            if req.slot == "instructions":
                refusal = _outside_bundle("instructions", source, show)
                if refusal is not None:
                    return refusal
            refusal = _changed_on_disk(req.slot, source, req)
            if refusal is not None:
                return refusal
            path = Path(source["path"])
            if _inside_demo(path):
                # A config default naming the packaged demo conventions.
                return _demo_refusal("Save")
            original = _raw_text(path)
            if original is None:
                return JSONResponse({"error": f"couldn't read {path} as UTF-8 text"},
                                    status_code=400)
            text, changed = source_edit.replace_text(original, req.text)
            label = source.get("display_path") or str(path)
            if not changed:
                return _payload_after_save(
                    {"slot": req.slot, "path": str(path), "changed": False},
                    f"Nothing to save -- {label} already says that. The file was not touched.")
            refusal = _write_text(path, text)
            if refusal is not None:
                return refusal
        return _payload_after_save(
            {"slot": req.slot, "path": str(path), "changed": True},
            f"Saved {label}"
            + (" -- every show that names this house file builds from it now."
               if req.slot == "conventions" else "."))

    @app.post("/api/build/input-list/save")
    def api_build_input_list_save(req: InputListSaveRequest, request: Request):
        refusal = _setup_only(request) or _refuse_demo("Save")
        if refusal is not None:
            return refusal
        show = app.state.bundle
        refusal = _stale_editor(req.expected_bundle, show, "Nothing was saved")
        if refusal is not None:
            return refusal
        if show is None:
            return JSONResponse({"error": "no show bundle open -- input.csv lives in one"},
                                status_code=400)
        with save_lock:
            sources = _build_payload(show, app.state.conventions_path, app.state.build_overrides)
            source = sources["input_list"]
            if not source.get("present"):
                return JSONResponse(
                    {"error": f"there is no {bundle.INPUT_LIST} in this bundle to save into"},
                    status_code=400)
            refusal = _outside_bundle("input_list", source, show)
            if refusal is not None:
                return refusal
            refusal = _changed_on_disk("input_list", source, req)
            if refusal is not None:
                return refusal
            path = Path(source["path"])
            original = _raw_text(path)
            if original is None:
                return JSONResponse({"error": f"couldn't read {path} as UTF-8 text"},
                                    status_code=400)
            try:
                text, summary = source_edit.splice_input_list(original, req.rows)
            except source_edit.EditError as exc:
                return JSONResponse({"error": f"{exc}. Nothing was saved.", "stale": "file",
                                     "slot": "input_list"}, status_code=409)
            label = source.get("display_path") or str(path)
            if text == original:
                return _payload_after_save(
                    {"slot": "input_list", "path": str(path), "changed": False,
                     **_rows_summary(summary)},
                    f"Nothing to save -- {label} already says that. The file was not touched.")
            refusal = _write_text(path, text)
            if refusal is not None:
                return refusal
        parts = []
        if summary["changed"]:
            parts.append(f"{len(summary['changed'])} row(s) changed")
        if summary["added"]:
            parts.append(f"{summary['added']} added")
        if summary["removed"]:
            parts.append(f"{summary['removed']} removed")
        if summary["columns_added"]:
            parts.append("column(s) added: " + ", ".join(summary["columns_added"]))
        payload = _payload_after_save(
            {"slot": "input_list", "path": str(path), "changed": True, **_rows_summary(summary)},
            f"Saved {label}: " + (", ".join(parts) or "rows reordered") + ".")
        # Written as asked, and read back by the engine's own loader: a row
        # it refuses is an ERROR in the dock (`input-list.invalid`, naming
        # the row), not a refusal to save. Say so with the save, too.
        if payload["input_list"].get("rows") is None:
            payload["message"] += (" The input list does not load as it stands -- the "
                                   "finding in the Findings panel names the row; a build refuses it "
                                   "until it is fixed.")
        return payload

    # ---- Build step 04 (version H, phase 3) -----------------

    @app.post("/api/build/run")
    def api_build_run(req: BuildRunRequest, request: Request):
        # The demo show's plan is built in the development
        # repository (its Demo-show builder), never here.
        refusal = _setup_only(request) or _refuse_demo("Build")
        if refusal is not None:
            return refusal
        # `atoo build --show DIR` behind a button, in a worker thread
        # -- see `BuildRun`. This answers at once with `running`; the page
        # polls `GET /api/build/status` for the rest.
        #
        # Every refusal below is a request that cannot become the build
        # the page is showing, said before a model call is spent on it.
        # Anything past these is the build's own to report, in its own
        # words, as a failed run with a finding -- never as a 500.
        if build_run.running:
            return JSONResponse({"error": "a build is already running"}, status_code=409)
        show = app.state.bundle
        if show is None:
            return JSONResponse(
                {"error": "no show bundle open -- a build writes its plan into one"},
                status_code=400,
            )
        if (req.expected_bundle or "").strip():
            refusal = _stale_editor(req.expected_bundle, show, "Nothing was built")
            if refusal is not None:
                return refusal
        models = sorted(console_facts.CONSOLE_MODELS)
        if req.console_model not in console_facts.CONSOLE_MODELS:
            # An unstated model is a hard stop in `build`, and
            # not a judgement call to make here -- a Full's 8 local inputs
            # and a Compact's 24 are a patch that lands or one that cannot.
            return JSONResponse(
                {"error": ("no console model chosen" if not req.console_model
                           else f"unknown console model {req.console_model!r}")
                          + f" -- one of: {', '.join(models)}"},
                status_code=400,
            )
        sources = _build_payload(show, app.state.conventions_path, app.state.build_overrides)
        conventions = sources["conventions"]
        # `build` reads `instructions.md` from the bundle and nowhere else
        # -- it has no flag for another file. A tile pointed elsewhere
        # would build from one text while the page showed another, and
        # `meta.conventions_stack` would record the one nobody saw.
        override = app.state.build_overrides.get("instructions")
        if override and Path(override) != show.path(bundle.INSTRUCTIONS):
            return JSONResponse(
                {"error": f"step 03 is showing {override}, but `atoo build` reads "
                          f"instructions only from the bundle's own "
                          f"{bundle.INSTRUCTIONS} -- choose it again with step 03's "
                          "Change file, which copies it into the bundle, or reopen the "
                          "bundle to drop the override"},
                status_code=400,
            )
        # A file that is not there is a to-do on its tile until
        # Build is pressed; HERE it becomes the ERROR, in the dock
        # (`findings`), with the tile's own words. A file that is there but
        # unreadable already has its finding in the dock, so adds nothing.
        refused = [sources[slot] for slot in ("conventions", "input_list")
                   if not sources[slot]["present"]]
        if refused:
            names = {"conventions": "no house conventions file (step 01)",
                     "input_list": "no input list (step 02)"}
            return JSONResponse(
                {"error": "Nothing was built: "
                          + " and ".join(names[s["slot"]] for s in refused)
                          + " -- see Findings.",
                 "findings": [s["missing"] for s in refused if s.get("missing")]},
                status_code=400,
            )

        argv = ["build", "--show", str(show.directory),
                "--conventions", conventions["path"],
                "--console-model", req.console_model]
        if app.state.build_overrides.get("input_list"):
            argv += ["--input", app.state.build_overrides["input_list"]]
        if app.state.presets_path:
            argv += ["--presets", app.state.presets_path]
        if req.critic:
            argv.append("--critic")

        watch_path = show.path(bundle.WATCH_CONDITIONS)
        watch_before = _watch_condition_ids(watch_path)
        watch_display = f"{show.directory.name or show.directory}/{bundle.WATCH_CONDITIONS}"

        def finish(code: int) -> list[dict]:
            # Runs in the build's thread once `build` returns. The plan
            # it wrote becomes the plan on screen -- unless the operator
            # opened a different show meanwhile, in which case it is that
            # show's plan.json on disk and nobody else's business.
            # Whatever the outcome, the page shows what is on disk now: the
            # build moved the old plan.json aside as it started, so a
            # failed or stopped build leaves none,
            # and a refusal before that left the old one where it was.
            if not show.plan.is_file():
                return []
            plan, error = _load_plan_from_path(str(show.plan))
            if plan is None:
                raise RuntimeError(error)
            if app.state.bundle is not None and app.state.bundle.directory == show.directory:
                app.state.plan, app.state.plan_path = plan, str(show.plan)
                _reload_drafted_watch_conditions(app.state, watch_path)
            drafted = _drafted_watchlist_finding(watch_path, watch_before, watch_display)
            return [drafted] if drafted else []

        if not build_run.start(argv, finish, guard_dir=show.directory):
            return JSONResponse({"error": "a build is already running"}, status_code=409)
        # The plan this build replaces is no longer current: stop serving
        # it the moment the build starts (`finish` loads whatever is on
        # disk when it ends).
        if app.state.plan_path and Path(app.state.plan_path) == show.plan:
            app.state.plan, app.state.plan_path = None, None
        return build_run.status()

    @app.post("/api/build/stop")
    def api_build_stop(request: Request, req: Optional[BuildStopRequest] = None):
        """Step 04's Stop: end the running build, and the model call in it.

        A Setup write -- it changes what lands in the show's
        files, by making sure nothing does -- so it answers this laptop's
        own browser only, and a page showing another bundle is refused
        exactly as `POST /api/build/run` refuses it. It answers at once;
        the page polls `GET /api/build/status` until `state` is `stopped`,
        which carries `stopped.message`."""
        refusal = _setup_only(request)
        if refusal is not None:
            return refusal
        if req is not None and (req.expected_bundle or "").strip():
            refusal = _stale_editor(req.expected_bundle, app.state.bundle, "Nothing was stopped")
            if refusal is not None:
                return refusal
        if not build_run.running:
            # The build ended on its own first (or was never started): the
            # page's next poll of `GET /api/build/status` says how.
            return JSONResponse({"error": "no build is running -- nothing to stop"},
                                status_code=409)
        build_run.stop()
        return build_run.status()

    @app.get("/api/build/status")
    def api_build_status():
        # Always a 200: `idle` before any build, then `running`, then
        # `done` or `failed` -- a state, never an absence of one.
        return build_run.status()

    # ---- Apply (mockup version H) --------------------------
    # The one screen in Atoo that writes to a console, and the one
    # place in this file that can. Three endpoints: the pre-flight verify
    # the screen shows before anything else, the run, and its status.

    def _verify_as_apply(plan: dict, plan_path: "str | None"):
        """`verify_plan` as `atoo apply --show DIR` runs it on this
        plan: the bundle's input list, the preset library, and the
        conventions/instructions layers its strips are checked against.
        The Apply pre-flight's verdict, and the dock's verify findings
        (`_plan_payload_now`)."""
        from atoo.verify_plan import verify_plan

        show = app.state.bundle
        # `apply --show DIR` fills `--input` from the bundle, so this
        # checks what the command will check. Without a list, three
        # checks -- every input became a channel, no channel was
        # invented, phantom is safe for the mics in use -- do not run,
        # and `verify_plan` says so rather than looking clean.
        rows = None
        if show is not None and show.path(bundle.INPUT_LIST).is_file():
            try:
                rows = input_list_module.load_input_list(str(show.path(bundle.INPUT_LIST)))
            except (OSError, input_list_module.InputListError):
                rows = None

        presets = None
        default_presets = app.state.presets_path or config.load_default_presets()
        if is_demo_show(show):
            # The demo show is checked against its own packaged
            # presets, never the user's library -- an unrelated library
            # would call every preset it names unknown.
            default_presets = DEMO_PRESETS if any(DEMO_PRESETS.glob("*.chn")) else None
        if default_presets is not None and Path(default_presets).is_dir():
            from atoo.presets import PresetLibrary

            presets = PresetLibrary(Path(default_presets))

        # The texts a channel built from the conventions or instructions
        # is checked against, as `apply --show DIR` finds them.
        from atoo import instructed_channels
        layers = instructed_channels.layers_from_plan(
            plan, show.directory if show is not None else
            (Path(plan_path).parent if plan_path else None),
            show.optional(bundle.INSTRUCTIONS) if show is not None else None)
        return verify_plan(plan, rows, presets=presets, layers=layers)

    def _plan_payload_now(plan: "dict | None", plan_path: "str | None") -> dict:
        """`_plan_payload`, with verify's findings asked again now when the
        plan is the open bundle's own plan.json -- where the input list
        and instructions it was built from are at hand. Anything else (a
        `--plan` file, a plan with no bundle) shows what it recorded."""
        show = app.state.bundle
        fresh, verdict = None, None
        if plan is not None and show is not None and plan_path == str(show.plan):
            try:
                result = _verify_as_apply(plan, plan_path)
                fresh = [f.to_dict() for f in result.findings]
                # Step 04's BLOCKED/OK badge, from the same run. It read
                # `meta.verify_at_generation` -- the build-time verdict --
                # and so said "BLOCKED, 1 error" beside a dock with no
                # error in it.
                verdict = report_module.verify_at_generation_status(verify_result=result)
            except Exception:  # noqa: BLE001 -- the recorded findings are the fallback
                fresh, verdict = None, None
        payload = _plan_payload(plan, plan_path, fresh)
        # What step 04's "Plan:" line prints: short, as the tiles write it. The absolute `path` stays for the title and the
        # file field.
        payload["display_path"] = (_display_path(Path(plan_path), show)
                                   if plan_path else None)
        # When the plan this one replaced was built (the Build
        # output line: "It replaced plan.previous.json, built 03:33").
        payload["previous_generated_at"] = _previous_generated_at(plan, plan_path)
        if verdict is not None:
            payload["verify_now"] = verdict
        # A build note about OH L+R's sockets stayed
        # after channels were moved on the input list -- true of the
        # plan as built, no longer of the show. The build's and the
        # critic's notes are not asked again (a model call), so when the
        # plan is older than its inputs each is marked `stale`: about the
        # plan as built. Verify's are fresh and are not marked. The dock's verdict says so ONCE ("the build's and the
        # critic's notes are as built"); the 25-word sentence that was
        # appended to every one of them is gone.
        if fresh is not None:
            try:
                freshness = _build_payload(
                    show, app.state.conventions_path, app.state.build_overrides)["plan_freshness"]
            except Exception:  # noqa: BLE001 -- unmarked is the fallback
                freshness = None
            if (freshness or {}).get("state") == plan_freshness.STALE:
                for finding in payload["findings"]:
                    if finding.get("source") in ("build", "critic", "rebuild"):
                        finding["stale"] = True
        return payload

    @app.get("/api/apply/preflight")
    def api_apply_preflight():
        """`verify_plan` against the plan Apply is about to write.

        **Fresh, never the plan's own `meta.verify_findings`.** Those are
        what the build said about itself at build time; `atoo apply`
        re-verifies before a single packet goes out and refuses on any
        ERROR (`cli.apply_cmd`'s "The gate"), and the screen has to show
        the gate it is actually standing behind. A plan built clean and
        then hand-edited would otherwise read as clean here.

        **It verifies the bytes on disk, not the plan in memory.**
        `atoo apply --show DIR` opens `DIR/plan.json` and verifies
        what it finds there; this server may be holding a copy read at
        startup or written by an earlier build. Edit the file in an editor
        and the two diverge -- the block would read clean while the
        command refused, which is worse than not drawing the block at
        all. So the bundle's own plan.json wins here, and the loaded plan
        is the fallback for a session that has no bundle open.

        Read-only: nothing is contacted, and this is safe to call as
        often as the page likes. It is a `GET` for that reason.
        """
        show = app.state.bundle
        plan, plan_path = app.state.plan, app.state.plan_path
        plan_sha256 = None
        if show is not None and show.plan.is_file():
            plan_sha256 = _file_sha256(show.plan)
            from_disk, error = _load_plan_from_path(str(show.plan))
            if error is not None:
                return JSONResponse(
                    {"error": f"{error} -- `atoo apply` reads this file and would "
                              "refuse it too"},
                    status_code=400,
                )
            plan, plan_path = from_disk, str(show.plan)
        if plan is None:
            return JSONResponse(
                {"error": "no plan loaded -- build one on Build step 04, or open a "
                          "show bundle that has a plan.json"},
                status_code=404,
            )

        verdict = _verify_as_apply(plan, plan_path)
        # Which input list that verdict checked against, for the screen.
        input_path = None
        if show is not None and show.path(bundle.INPUT_LIST).is_file():
            try:
                input_list_module.load_input_list(str(show.path(bundle.INPUT_LIST)))
                input_path = str(show.path(bundle.INPUT_LIST))
            except (OSError, input_list_module.InputListError):
                input_path = None
        findings = [f.to_dict() for f in verdict.findings]
        warnings = len(verdict.warnings)
        # A bundle plan built before an edit to one of its three
        # inputs says so here, as a WARNING -- announced, never blocking:
        # applying the plan as built is a choice an engineer may make. The
        # inputs compared are the ones Build shows, so the pre-flight and
        # the Plan tile's Stale badge cannot disagree.
        freshness = None
        if show is not None and plan_path == str(show.plan):
            freshness = _build_payload(
                show, app.state.conventions_path, app.state.build_overrides)["plan_freshness"]
            stale = plan_freshness.stale_diagnostic(
                freshness, f"{show.directory.name or show.directory}/{bundle.PLAN}")
            if stale is not None:
                findings.append(stale.to_dict())
                warnings += 1
        # An earlier change, decision 7: the changes and amends standing on the
        # bar's desk are not in plan.json, so a full apply replaces them --
        # said here, as a WARNING, before anyone arms it. The same finding
        # `atoo apply` prints (`journal_stack.replaced_changes_diagnostic`).
        if show is not None and plan_path == str(show.plan):
            from atoo import journal_stack

            replaced = journal_stack.replaced_changes_diagnostic(show.directory, _bar_desk())
            if replaced is not None:
                findings.append(replaced.to_dict())
                warnings += 1
        # 2026-10-02: what a full apply writes beyond the plan's own strips
        # -- every strip it does not build unpatched, talkback's assign --
        # said before anyone arms it, at INFO. The same lines the run's
        # own journal carries (`apply.full_apply_notes`).
        from atoo import apply as apply_module
        from atoo import initialize as init_module
        from atoo.verify_plan import resolve_console_model

        # The model a Ping heard at the bar's address, else the plan's own
        # (the run itself uses the desk's answer).
        model = (_bar_desk() or {}).get("model") or resolve_console_model(plan)
        for code, note in apply_module.full_apply_notes(plan, model):
            findings.append(Diagnostic(
                severity=Severity.INFO, code=code,
                message=note.removeprefix("INFO "), where="Apply", source="apply",
            ).to_dict())
        # The reset to initialized that comes first. The desk is
        # not read here, so the count is an upper bound.
        code, note = init_module.preflight_note(plan, model)
        warn = note.startswith("WARNING ")
        findings.append(Diagnostic(
            severity=Severity.WARNING if warn else Severity.INFO, code=code,
            message=note.removeprefix("WARNING ").removeprefix("INFO "),
            where="Apply", source="apply",
        ).to_dict())
        if warn:
            warnings += 1
        return {
            "plan_path": plan_path,
            # The bytes this verdict is about. The page sends it back as a
            # confirmed apply's `expected_plan_sha256`, so a plan.json
            # rebuilt or edited after the page read this is refused rather
            # than written unread. None when no bundle plan was read.
            "plan_sha256": plan_sha256,
            "input_path": input_path,
            "checked_input_list": input_path is not None,
            "errors": len(verdict.errors),
            "warnings": warnings,
            "ok": verdict.ok,
            # One item per distinct message (FR-X.15c), as `apply` prints
            # it in a terminal; `errors`/`warnings` above stay one per
            # finding, and a grouped item's `members` keep each one.
            "findings": finding_groups.label_strips(finding_groups.group_dicts(findings), plan),
            # `plan_freshness.assess`'s answer for this plan, or None when
            # the plan is not the open bundle's.
            "plan_freshness": freshness,
            # Step 1's counts, and whether Patch can compile a
            # typed change here (a model is configured) -- the Demo says
            # at INFO when it cannot, and previews Full build only.
            "plan_counts": _plan_counts(plan),
            "patch_model": dict(zip(("ready", "why"), _patch_model_state())),
        }

    @app.post("/api/apply/run")
    def api_apply_run(req: ApplyRunRequest, request: Request):
        refusal = _setup_only(request)
        if refusal is not None:
            return refusal
        # Under the console lock, so the desk this run is started against
        # is the desk in the bar at the moment it starts, and stays so.
        with app.state.console_lock:
            return _apply_run_locked(req)

    def _apply_run_locked(req: ApplyRunRequest):
        """`atoo apply --show DIR` behind the Preview and Apply
        buttons, in a worker thread -- see `ApplyRun`.

        **`--confirm` is passed only when the request carries BOTH
        `confirm` and `arm`**, and a `confirm` without an `arm` is refused
        outright rather than quietly downgraded to a preview. The checkbox
        is the arming control (FR-X.2), the button is the intent, and a
        request with one and not the other did not come from this screen.

        Every refusal below is a request that cannot become an apply, said
        before a packet is sent. Everything past them is the command's own
        to report, in its own words -- including the refusal gate, which
        is `atoo apply`'s and is not repeated here.
        """
        import shutil
        import tempfile

        if req.confirm and _on_demo():
            # First, armed or not -- "tick Arm" would only lead
            # to this refusal.
            return _demo_write_refusal()
        if apply_run.running:
            return JSONResponse({"error": "an apply is already running"}, status_code=409)
        if req.confirm and not req.arm:
            # FR-X.2. The one guard in this file that stands between a
            # button and a live desk.
            return JSONResponse(
                {"error": 'not armed -- tick "Arm" (step 3, beside the write button) first. That checkbox '
                          "is `--confirm`, and nothing is written without it."},
                status_code=400,
            )
        show = app.state.bundle
        if show is None:
            return JSONResponse(
                {"error": "no show bundle open -- Apply writes the bundle's own plan.json"},
                status_code=400,
            )
        if not show.plan.is_file():
            return JSONResponse(
                {"error": f"{show.directory.name or show.directory}/{bundle.PLAN} does not "
                          "exist yet -- build it on Build step 04"},
                status_code=400,
            )
        defaults = app.state.console_defaults or {}
        address = (defaults.get("address") or "").strip()
        demo = _on_demo()
        if not address and not demo:
            # There is no console field on this screen, by design: the one
            # console is the bundle bar's, shown there with where it came
            # from and editable there.
            return _no_console_error()
        confirmed = bool(req.confirm and req.arm)
        stale = (_stale_page(req.expected_console, confirmed)
                 or _stale_bundle(req.expected_bundle, show, confirmed)
                 or _build_in_flight(confirmed))
        if stale is not None:
            return stale
        if confirmed:
            # The plan this page's pre-flight verified must be the plan the
            # command is about to open. Absent is refused, as for the bundle.
            actual = _file_sha256(show.plan)
            expected = (req.expected_plan_sha256 or "").strip().lower()
            where = f"{show.directory.name or show.directory}/{bundle.PLAN}"
            if not expected:
                return _refuse_stale(
                    f"this write does not say which {where} it verified "
                    "(`expected_plan_sha256` -- the `plan_sha256` the pre-flight answers). "
                    "Nothing was written -- reload the page, read the pre-flight, and arm the "
                    "write again.", "plan")
            if expected != actual:
                return _refuse_stale(
                    f"this page's pre-flight verified {where} at sha256 {expected[:12]}, but "
                    f"the file is now {(actual or 'unreadable')[:12]} -- it was rebuilt or "
                    "edited since. Nothing was written -- run the pre-flight again, read what "
                    "it says about the plan there now, and arm the write again.", "plan")
        if req.clean_output_sockets:
            try:
                _parse_socket_counts(req.clean_output_sockets)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

        if confirmed:
            # A full build rewrites the desk, so any patch preview taken
            # before it no longer describes it.
            app.state.patch_reviewed = None
        # The page has to read back the records it is about to draw: a
        # real apply's is the new entry in the bundle's journals/, a
        # preview's a scratch file this server deletes once read
        # (`_RunJournal`).
        scratch = None if confirmed else tempfile.mkdtemp(prefix="atoo-preview-")
        run_show, demo_cleanup = show, None
        if demo:
            # The Demo previews against its simulated WING,
            # through the same command, on a copy of the Demo show.
            run_show, demo_desk, demo_cleanup = _demo_preview("apply")
            address = "127.0.0.1"
            console_flags = ["--console", address, "--port", str(demo_desk.port)]
            on = DEMO_DESK_WORDS
        else:
            console_flags = ["--console", address]
            if defaults.get("port"):
                console_flags += ["--port", str(defaults["port"])]
            if defaults.get("timeout"):
                console_flags += ["--timeout", str(defaults["timeout"])]
            on = _console_label(defaults)
        run_journal = _RunJournal(run_show, "apply", confirmed, scratch)

        argv = ["apply", "--show", str(run_show.directory), *console_flags]
        argv += run_journal.argv
        if confirmed:
            argv.append("--confirm")
        if req.skip_verify:
            argv.append("--skip-verify")
        if req.clean_output_sockets:
            argv += ["--clean-output-sockets", req.clean_output_sockets]

        def finish(code: int) -> list[dict]:
            # Runs in the apply's thread once `apply` has returned. The
            # journal is only THIS RUN'S when the run got as far as
            # touching an address: the refusal gate, a socket the desk's
            # model does not have and an unfitted bay all stop before that, and each
            # has already said why in the log. A bundle that already holds
            # the journal of its last apply must not have it drawn as this
            # run's -- hence reading only an entry this run added.
            plan_now = None
            try:
                journal_path, journal = run_journal.read()
                plan_now, _error = _load_plan_from_path(str(run_show.plan))
            finally:
                if scratch is not None:
                    shutil.rmtree(scratch, ignore_errors=True)
                if demo_cleanup is not None:
                    demo_cleanup()
            if journal is None:
                apply_run.publish(result=None)
                return []
            payload = _apply_payload(
                journal,
                journal_path if confirmed else None,
                _apply_abort_reason(apply_run.status()["log"]),
            )
            # The desk as this plan leaves it, as scribble
            # strips, with the strips the write changes marked.
            from atoo import desk_view

            payload["drawing"] = desk_view.full_build_desk(plan_now, [
                {"address": w.address, "status": w.status, "would_change": w.would_change}
                for w in _write_records(journal)])
            apply_run.publish(result=payload)
            return _apply_findings(payload, DEMO_CONSOLE_LABEL if demo else address)

        if not apply_run.start(argv, finish, preview=not confirmed, on=on):
            # `finish` never runs, so nothing else will remove the scratch
            # directory made above -- a preview refused for concurrency
            # would otherwise leave one behind on every press.
            if scratch is not None:
                shutil.rmtree(scratch, ignore_errors=True)
            if demo_cleanup is not None:
                demo_cleanup()
            return JSONResponse({"error": "an apply is already running"}, status_code=409)
        return apply_run.status()

    @app.get("/api/apply/status")
    def api_apply_status():
        # Always a 200: `idle` before any apply, then `running`, then
        # `done` or `failed` -- a state, never an absence of one, and the
        # same shape `GET /api/build/status` answers with plus `result`.
        return apply_run.status()

    def _console_argv() -> "list[str] | JSONResponse":
        defaults = app.state.console_defaults or {}
        address = (defaults.get("address") or "").strip()
        if not address:
            return _no_console_error()
        argv = ["--console", address]
        if defaults.get("port"):
            argv += ["--port", str(defaults["port"])]
        if defaults.get("timeout"):
            argv += ["--timeout", str(defaults["timeout"])]
        return argv

    def _review_id(key: "tuple | None") -> "str | None":
        """A short name for one `_patch_key`: what a writable preview's
        review carries as `review_id`, and what a confirmed write's
        `expected_review_id` must equal."""
        if key is None:
            return None
        return hashlib.sha256(repr(key).encode()).hexdigest()[:16]

    # ---- Patch: a typed change ------------------------------
    # `atoo patch --show DIR` behind the same buttons, the same one
    # arming checkbox and the same runner -- see `PatchRunRequest`. The
    # review is the command's own `--review-json`; the one thing this adds is keeping the change set a preview compiled,
    # so the write is that change set and not a second model call's.

    def _patch_key(show, text: str, change_set: "dict | None", allow: list[str],
                   console: str = "") -> "tuple | None":
        """What a patch preview reviewed: the plan on the desk, the journal
        stack, the strips opened by hand and the console, plus the change
        text and the compiled change set. A write is armed only for a key
        equal to the last clean preview's."""
        import hashlib

        from atoo import journal_stack

        try:
            stack = tuple(e.id for e in journal_stack.entries(show.directory))
            plan = (show.plan.stat().st_mtime_ns,
                    hashlib.sha256(show.plan.read_bytes()).hexdigest()) \
                if show.plan.is_file() else (None, None)
        except (OSError, journal_stack.JournalStackError):
            return None
        compiled = hashlib.sha256(json.dumps(change_set, sort_keys=True).encode()).hexdigest() \
            if change_set is not None else None
        return ("patch", str(show.directory), text.strip(), compiled, *plan,
                tuple(sorted(allow)), console, stack)

    @app.post("/api/patch/run")
    def api_patch_run(req: PatchRunRequest, request: Request):
        refusal = _setup_only(request)
        if refusal is not None:
            return refusal
        with app.state.console_lock:
            return _patch_run_locked(req)

    def _patch_run_locked(req: PatchRunRequest):
        """Preview a typed change, or -- armed, after a clean preview of this
        exact change -- write the change set that preview compiled. Every
        refusal here is said before the model or the desk is contacted."""
        import shutil
        import tempfile

        if req.confirm and _on_demo():
            return _demo_write_refusal()     # first, armed or not
        if apply_run.running:
            return JSONResponse({"error": f"a {apply_run.kind} is already running -- "
                                          "one write at a time from this page"},
                                status_code=409)
        if req.confirm and not req.arm:
            return JSONResponse(
                {"error": 'not armed -- tick "Arm" (step 3, beside the write button) first. That checkbox '
                          "is `--confirm`, and nothing is written without it."},
                status_code=400,
            )
        show = app.state.bundle
        if show is None:
            return JSONResponse(
                {"error": "no show bundle open -- a change is recorded in a bundle's journal, "
                          "which is also where the plan on the desk is read from"},
                status_code=400,
            )
        text = (req.change or "").strip()
        if not text:
            return JSONResponse(
                {"error": "type the change first -- what to add, what to drop, e.g. "
                          "\"trumpet, sax and trombone on A 21-23, Horns DCA\""},
                status_code=400,
            )
        allow = [a.strip() for a in req.allow_strips if a.strip()]
        for label in allow:
            if not _STRIP_LABEL_RE.match(label):
                return JSONResponse(
                    {"error": f"--allow-strip {label!r}: expected a strip label like "
                              "'ch:20' or 'aux:3'"},
                    status_code=400,
                )
        demo = _on_demo()
        if demo:
            # A typed change is compiled by a model, and the
            # Demo brings none of its own. Said before anything starts.
            model_ready, model_why = _patch_model_state()
            if not model_ready:
                return JSONResponse(
                    {"error": "a typed change is compiled by a model, and none is set up "
                              f"here ({model_why}). Nothing was read or written. The Demo "
                              "can still preview a Full build.", "demo": True},
                    status_code=400,
                )
            console_argv = ["--console", "127.0.0.1"]
        else:
            console_argv = _console_argv()
            if isinstance(console_argv, JSONResponse):
                return console_argv

        confirmed = bool(req.confirm and req.arm)
        stale = (_stale_page(req.expected_console, confirmed)
                 or _stale_bundle(req.expected_bundle, show, confirmed)
                 or _build_in_flight(confirmed))
        if stale is not None:
            return stale
        console_label = _console_label(app.state.console_defaults)
        change_set = app.state.patch_change_set if confirmed else None
        key = _patch_key(show, text, change_set, allow, console_label)
        if confirmed and (change_set is None or key is None
                          or key != app.state.patch_reviewed):
            return JSONResponse(
                {"error": "preview this change first -- the write is only armed for the "
                          "exact change the last preview reviewed (same text, same plan on "
                          "the desk, same --allow-strip, same console), and that preview has "
                          "to have found something to write and nothing refused"},
                status_code=409,
            )
        if confirmed and (req.expected_review_id or "").strip() != _review_id(key):
            return _refuse_stale(
                "the review on this page is not the one the write is armed for -- "
                + ("this request does not name one (`expected_review_id`)"
                   if not (req.expected_review_id or "").strip()
                   else "a later preview (from another tab) replaced it")
                + ". Nothing was written -- preview the change again, read it, and arm "
                "the write again.", "review")

        scratch = tempfile.mkdtemp(prefix="atoo-patch-")
        review_path = Path(scratch) / "review.json"
        text_path = Path(scratch) / "change.txt"
        text_path.write_text(text + "\n", encoding="utf-8")
        run_show, demo_cleanup, on = show, None, console_label
        if demo:
            # A copy of the Demo show, read on the simulated WING.
            run_show, demo_desk, demo_cleanup = _demo_preview("patch")
            console_argv = ["--console", "127.0.0.1", "--port", str(demo_desk.port)]
            on = DEMO_DESK_WORDS
        run_journal = _RunJournal(run_show, "patch", confirmed, scratch)

        argv = ["patch", "--show", str(run_show.directory), "--change-file", str(text_path),
                *console_argv, *run_journal.argv, "--review-json", str(review_path)]
        argv += [f"--allow-strip={label}" for label in allow]
        # The library `ui --presets` named, as Build passes it: a change's
        # new strips take their presets from the same one.
        if app.state.presets_path:
            argv += ["--presets", app.state.presets_path]
        if confirmed:
            set_path = Path(scratch) / "change-set.json"
            set_path.write_text(json.dumps(change_set, indent=2), encoding="utf-8")
            argv += ["--change-set", str(set_path), "--confirm"]
            # One preview arms one write.
            app.state.patch_reviewed = None
            app.state.patch_change_set = None

        address = console_argv[1]

        def finish(code: int) -> list[dict]:
            try:
                try:
                    review = json.loads(review_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    review = None
                journal_path, journal = run_journal.read()
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
                if demo_cleanup is not None:
                    demo_cleanup()
            if review is not None:
                review["withheld_groups"] = _withheld_groups(review.get("withheld") or [])
            compiled = ((review or {}).get("change") or {}).get("change_set")
            # Not for the Demo: its writes are refused, so a
            # preview there arms nothing -- no review recorded, no review id.
            if (not confirmed and not demo and code == 0 and review is not None
                    and compiled is not None and not review.get("blocked")
                    and not review.get("collisions") and review.get("to_write")):
                reviewed = _patch_key(show, text, compiled, allow, console_label)
                app.state.patch_reviewed = reviewed
                app.state.patch_change_set = compiled
                review["review_id"] = _review_id(reviewed)
            # Complete before it is published, never touched after: a status poll may be serializing it already.
            apply_run.publish(review=review)
            payload = None
            if journal is not None:
                payload = _apply_payload(
                    journal, journal_path if confirmed else None,
                    _apply_abort_reason(apply_run.status()["log"]))
            apply_run.publish(result=payload)
            return _patch_findings(review, payload,
                                   DEMO_CONSOLE_LABEL if demo else address)

        if not apply_run.start(argv, finish, kind="patch", preview=not confirmed, on=on):
            shutil.rmtree(scratch, ignore_errors=True)
            if demo_cleanup is not None:
                demo_cleanup()
            return JSONResponse({"error": f"a {apply_run.kind} is already running -- "
                                          "one write at a time from this page"},
                                status_code=409)
        return apply_run.status()

    # ---- Keep a change in the show --------------------

    @app.post("/api/patch/promote")
    def api_patch_promote(req: PromoteRequest, request: Request):
        """Preview, or with `confirm` write, the promotion of one recorded
        change: `promote.promotion` and `promote.write`, the functions the
        CLI's `--promote` calls, so the page and the terminal say the same
        thing. plan.json is never touched."""
        refusal = _setup_only(request) or _refuse_demo("promoting a change")
        if refusal is not None:
            return refusal
        from atoo import journal_stack, promote

        show = app.state.bundle
        if show is None:
            return JSONResponse({"error": "no show bundle open"}, status_code=400)
        try:
            result = promote.promotion(show.directory, req.ref)
        except (promote.PromoteError, journal_stack.JournalStackError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        written: list[str] = []
        if req.confirm and not result.already:
            try:
                written = promote.write(show.directory, result)
            except OSError as exc:
                return JSONResponse({"error": str(exc)}, status_code=500)
        return {"label": result.label, "already": result.already,
                "summary": result.summary(), "infos": result.infos,
                "rows": len(result.rows), "written": written,
                "confirmed": bool(req.confirm)}

    # ---- The journal stack, drawn on Apply ------------------

    @app.get("/api/journals")
    def api_journals():
        """The open bundle's journal stack, newest first -- `journal_stack.
        listing()`, one index read, no journal parsed. The row marked
        `is_top` is the one `atoo undo --show` would reverse."""
        from atoo import journal_stack

        show = app.state.bundle
        if show is None:
            return {"bundle": None, "entries": []}
        desk = _bar_desk()
        try:
            rows = journal_stack.listing(show.directory, desk)
        except (journal_stack.JournalStackError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {
            "bundle": str(show.directory),
            # The desk the listing was drawn for -- the bar's console, with
            # the identity its last Ping heard -- or null with no console.
            "desk": desk,
            "desk_label": journal_stack.describe_desk(desk) if desk else None,
            "entries": [
                {"id": e.id, "kind": e.kind, "timestamp": e.timestamp,
                 "summary": e.summary, "mismatches": e.mismatches, "writes": e.writes,
                 "undo_of": e.undo_of, "undone_by": e.undone_by, "is_top": e.is_top,
                 "path": str(e.path), "desk": e.desk,
                 "serial": e.serial, "address": e.address,
                 "desk_label": journal_stack.describe_desk(e.desk) if e.desk else None,
                 "on_this_desk": e.on_this_desk,
                 # A patch's change -- `{"number", "name", "text"}` -- so the
                 # stack reads as a list of changes. None for
                 # every other kind.
                 "change": e.change,
                 "change_label": (journal_stack.change_label(e.change)
                                  if e.change else None)}
                for e in rows
            ],
        }

    def _bar_desk() -> "dict | None":
        """The bar's console as the journal stack records a desk: its
        address and port, plus the serial its last Ping heard when that
        Ping was of this same address. Without a Ping the address alone,
        which `journal_stack.same_desk` falls back to -- so the listing
        is right for a desk at its recorded address before anyone has
        pinged it, and exact (serial) once they have. `atoo undo`
        itself always asks the desk, so the button never depends on this."""
        from atoo import journal_stack

        defaults = app.state.console_defaults or {}
        address = (defaults.get("address") or "").strip()
        if not address:
            return None
        port = defaults.get("port") or 2223
        heard = app.state.console_identity or {}
        identity = (heard.get("identity")
                    if heard.get("address") == address and heard.get("port") == port else None)
        return journal_stack.desk_from_identity(identity, address, port)

    @app.post("/api/undo/run")
    def api_undo_run(req: UndoRunRequest, request: Request):
        refusal = _setup_only(request)
        if refusal is not None:
            return refusal
        with app.state.console_lock:
            return _undo_run_locked(req)

    def _undo_run_locked(req: UndoRunRequest):
        """`atoo undo --show DIR`: preview, or -- armed -- reverse the
        newest write on the stack **on the bar's desk** (per-desk history:
        the command asks the desk who it is and pops that desk's newest).
        The stack's own guards (never reach underneath a later write, never
        reverse another desk's -- by serial, with no override anywhere) are
        the command's; there is no `--out-of-order` here, on purpose."""
        if apply_run.running:
            return JSONResponse({"error": f"a {apply_run.kind} is already running -- "
                                          "one write at a time from this page"},
                                status_code=409)
        if req.confirm and not req.arm:
            return JSONResponse(
                {"error": 'not armed -- tick "Arm" (step 3, beside the write button) first. An undo writes '
                          "to the console too, and that checkbox is `--confirm`."},
                status_code=400,
            )
        show = app.state.bundle
        if show is None:
            return JSONResponse({"error": "no show bundle open -- undo walks back that "
                                          "bundle's journal stack"}, status_code=400)
        console_argv = _console_argv()
        if isinstance(console_argv, JSONResponse):
            return console_argv
        confirmed = bool(req.confirm and req.arm)
        stale = (_stale_page(req.expected_console, confirmed)
                 or _stale_bundle(req.expected_bundle, show, confirmed))
        if stale is not None:
            return stale
        if confirmed:
            # The entry the page shows as the one Undo reverses must still be
            # the top of the stack for the bar's desk -- the same listing the
            # page drew (`GET /api/journals`). The command asks the desk who
            # it is and keeps its own per-desk guards; this makes sure what
            # the page SHOWED is still what the server sees.
            from atoo import journal_stack

            try:
                top = journal_stack.top(show.directory, _bar_desk())
            except (journal_stack.JournalStackError, OSError) as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            expected = (req.expected_undo_id or "").strip()
            if not expected:
                return _refuse_stale(
                    "this undo does not say which write it means to reverse "
                    "(`expected_undo_id` -- the journal-stack row marked top). Nothing was "
                    "written -- reload the page, read the journal stack, and arm the undo "
                    "again.", "undo")
            if top is None or top.id != expected:
                now = (f"the newest write on this desk is now {top.id} ({top.kind})"
                       if top is not None else "nothing on this desk's stack is left to undo")
                return _refuse_stale(
                    f"this page shows {expected} as the write Undo reverses, but {now} -- "
                    "something was written or undone since, from another tab or a terminal. "
                    "Nothing was written -- reload the journal stack, read it, and arm the "
                    "undo again.", "undo")
        import shutil
        import tempfile

        scratch = tempfile.mkdtemp(prefix="atoo-undo-")
        result_path = Path(scratch) / "undo.json"
        argv = ["undo", "--show", str(show.directory), *console_argv,
                "--result-json", str(result_path)]
        if confirmed:
            argv.append("--confirm")
            app.state.patch_reviewed = None

        def finish(code: int) -> list[dict]:
            try:
                try:
                    data = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = None
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
            payload = _undo_payload(data, show.directory) if data is not None else None
            # Complete before it is published, never touched after.
            apply_run.publish(result={"undo": payload} if payload is not None else None)
            return _undo_findings(payload)

        if not apply_run.start(argv, finish, kind="undo",
                               on=_console_label(app.state.console_defaults),
                               preview=not confirmed):
            shutil.rmtree(scratch, ignore_errors=True)
            return JSONResponse({"error": f"a {apply_run.kind} is already running -- "
                                          "one write at a time from this page"},
                                status_code=409)
        return apply_run.status()

    @app.post("/api/ping")
    def api_ping(req: PingRequest):
        # `atoo ping` (FR-X.16) behind a button: ONE OSC
        # round trip, nothing else read, socket closed. Safe mid-show, and
        # that is the whole reason it is the only console contact this
        # shell makes -- version H puts it in the bundle bar so no mode
        # has to ask for a console cold.
        #
        # `atoo.console.ping` is the same three steps `cli._open_console`
        # performs (identity, the issue-an earlier change socket-error check, the model
        # the desk states for itself), as a value rather than printed
        # lines; see its own comment for why the CLI cannot simply call it
        # yet.
        #
        # Two failures, two status codes, deliberately. A request naming
        # no console at all is a 400 -- the page asked a question it had
        # no address for, which is a client mistake. A desk that does not
        # answer is a **200 with `ok: false`**: the endpoint did its job
        # and the answer is no. Rendering those the same way would make an
        # unreachable console look like a broken page.
        from atoo.console import ping as console_ping

        defaults = app.state.console_defaults or {}
        if defaults.get("demo") and not req.console:
            # Demo is not a desk, so there is nothing to ping --
            # and answering "ok" for a round trip nobody made would make
            # the pill a lie. A 400, like a request naming no console.
            return JSONResponse(
                {"error": "the console is Demo -- there is no desk to ping",
                 "demo": True},
                status_code=400,
            )
        address = (req.console or defaults.get("address") or "").strip()
        if not address:
            return JSONResponse(
                {"error": "no console address -- type one into the Console field in the "
                          "bundle bar, or set ATOO_CONSOLE / ~/.atoo.config's "
                          "[console] section"},
                status_code=400,
            )
        port = req.port if req.port is not None else defaults.get("port") or 2223
        timeout = req.timeout if req.timeout is not None else defaults.get("timeout") or 1.0

        # `address_source` travels with the answer: the
        # page must be able to say an address nobody typed came from
        # somewhere. A typed override has no provenance to show, so it
        # reports None rather than inheriting the seed's.
        source = None if req.console else defaults.get("address_source")
        result = console_ping(address, port=port, timeout=timeout)
        if result.ok and not req.console and req.port is None:
            # The bar's own desk answered: remember who it said it was, so
            # the journal listing can tell its rows apart by serial rather
            # than by address alone (`_bar_desk`). Keyed on the address and
            # port it was heard at, so an edit makes it stale by itself.
            app.state.console_identity = {"address": address, "port": port,
                                          "identity": list(result.identity)}
        return {**result.to_dict(), "address_source": source}

    # ---- The bundle bar's console -------------------

    @app.get("/api/console")
    def api_console():
        """The console in the bar: `cli.resolve_console_defaults()`'s shape,
        `{address, address_source, port, port_source, timeout,
        timeout_source}`, as resolved at startup or set here since. `{}`
        when nothing named one. Every desk-facing endpoint on this server
        uses exactly this."""
        return dict(app.state.console_defaults or {})

    @app.post("/api/console")
    def api_console_set(req: ConsoleSetRequest):
        """Change the one console -- Ping, Apply, Patch, Undo and Watch all
        use it -- without restarting `atoo ui`.

        **Refused (409) while any write is running.** One runner,
        `apply_run`, carries apply, patch and undo, and a write must never
        change desks part way through: the command has the address in its
        argv already, but the page would name the new desk beside a run
        still landing on the old one, and the journal it records would sit
        under a bar that no longer names the desk it wrote to. Checked
        under `console_lock`, the same lock every write endpoint starts its
        run under, so there is no gap between the check and the change.

        The provenance becomes `set here` (`CONSOLE_SET_HERE`) -- the
        rule that an address nobody typed on this page must say where it
        came from is kept by the converse: one typed here says so. The
        timeout is left as the startup configuration set it.

        `demo` sets the Demo console instead: no address.
        Ping says there is no desk to ping; Apply and Patch preview against
        the simulated WING (`demo_desk.DemoDesk`) and refuse every write,
        armed or not (`_demo_write_refusal`); Undo refuses; and
        Watch runs on `demo_provider_factory`. The port and timeout in
        force are kept beside it, so choosing an address again starts from
        them.

        **Demo is the demo show** (2026-10-01): `demo`
        also opens the packaged, read-only demo show (`DEMO_SHOW_DIR`), as
        one action, and an address chosen while it is open leaves it --
        the show that was open before Demo comes back (or none, if there
        was none or it is gone). Either way a running watch stops: it was
        reading the other desk. The answer is the console, plus `bundle`
        (the open bundle's payload, or None) and `bundle_changed`, so the
        page redraws the bar and every mode from one reply."""
        if not req.demo:
            address = (req.address or "").strip()
            if not _CONSOLE_ADDRESS_RE.match(address):
                return JSONResponse(
                    {"error": f"{req.address!r} is not a console address -- an IP address "
                              "such as 203.0.113.50, or a host name"},
                    status_code=400,
                )
            if req.port is not None and not 1 <= req.port <= 65535:
                return JSONResponse({"error": f"port {req.port} is out of range (1-65535)"},
                                    status_code=400)
        with app.state.console_lock:
            if apply_run.running:
                current = _console_label(app.state.console_defaults or {})
                return JSONResponse(
                    {"error": f"{'an' if apply_run.kind[:1] in 'aeiou' else 'a'} "
                              f"{apply_run.kind} is running against {current} -- the "
                              "console cannot change until it finishes. A write never "
                              "switches desks part way through."},
                    status_code=409,
                )
            current = dict(app.state.console_defaults or {})
            was_demo = bool(current.get("demo"))
            bundle_changed = False
            if req.demo:
                updated = _demo_console(current)
                if not was_demo or not is_demo_show(app.state.bundle):
                    try:
                        show = bundle.load(DEMO_SHOW_DIR)
                    except bundle.BundleError as exc:
                        return JSONResponse(
                            {"error": f"the demo show could not be opened: {exc}"},
                            status_code=500)
                    if app.state.before_demo is None:
                        app.state.before_demo = {"bundle": app.state.bundle,
                                                 "console": current}
                    _stop_watch_for_demo_change()
                    _open_show(show)
                    bundle_changed = True
            else:
                if was_demo:
                    # The console Demo replaced is the starting point --
                    # its port, timeout and their provenance.
                    current = dict(((app.state.before_demo or {}).get("console")) or current)
                updated = dict(current)
                updated.pop("demo", None)
                updated["address"] = address
                if req.port is not None:
                    updated["port"] = req.port
                    updated["port_source"] = CONSOLE_SET_HERE
                updated["address_source"] = CONSOLE_SET_HERE
                updated.setdefault("port", 2223)
                updated.setdefault("port_source", None)
                updated.setdefault("timeout", 1.0)
                updated.setdefault("timeout_source", None)
                if was_demo or is_demo_show(app.state.bundle):
                    # Leaving Demo: the show that was open before it.
                    previous = (app.state.before_demo or {}).get("bundle")
                    app.state.before_demo = None
                    _stop_watch_for_demo_change()
                    reopened = None
                    if previous is not None:
                        try:
                            reopened = bundle.load(previous.directory)
                        except bundle.BundleError:
                            reopened = None
                    if reopened is not None:
                        _open_show(reopened)
                    else:
                        _close_show()
                    bundle_changed = True
            app.state.console_defaults = updated
            app.state.console_identity = None
        return {**updated,
                "bundle": _bundle_payload(app.state.bundle) if app.state.bundle else None,
                "bundle_changed": bundle_changed}

    @app.get("/api/watch-conditions")
    def api_watch_conditions():
        # No watch-conditions file loaded (no `--watch-conditions` at
        # startup, and no successful `POST /api/watch-conditions/load`
        # yet) -- a 404 with a small, documented body, same shape as
        # `GET /api/plan`'s "no plan loaded".
        if app.state.watch_conditions is None:
            return JSONResponse({"error": "no watch-conditions file loaded",
                                 "bundle_file": _watch_bundle_file()}, status_code=404)
        return _watch_payload()

    @app.post("/api/watch-conditions/load")
    def api_watch_conditions_load(req: WatchConditionsLoadRequest, request: Request):
        # The in-browser equivalent of restarting `atoo ui` with a
        # new `--watch-conditions` -- read-only, and returns a clean JSON
        # error body rather than raising, so a bad path or a
        # WatchConditionsError is a 400, not a 500. Same shape as
        # `POST /api/plan/load`.
        refusal = _local_only(request) or _refuse_demo("Change file")
        if refusal is not None:
            return refusal
        conditions, error = _load_watch_conditions_from_path(req.path)
        if error is not None:
            return JSONResponse({"error": error}, status_code=400)
        app.state.watch_conditions = conditions
        app.state.watch_conditions_path = req.path
        return _watch_payload()

    @app.post("/api/watch-conditions/check")
    def api_watch_conditions_check(req: WatchConditionsCheckRequest):
        # The Watch editor's inline check. Pure -- reads and
        # writes nothing, so it needs no local-only guard. One entry per
        # row, in order: `{"channel"|"field"|"value": reason}` for each
        # cell that is wrong, plus `canonical` (the target's display
        # spelling, `CH 10`) when the channel parses. The rules are
        # `watch_conditions`' own, so the table and the loader cannot
        # drift apart the way WC_FIELDS once did.
        from atoo.watch_conditions import row_problems

        return {"rows": [row_problems(row) for row in req.watch_conditions]}

    @app.post("/api/watch-conditions/save")
    def api_watch_conditions_save(req: WatchConditionsSaveRequest, request: Request):
        # Validate BEFORE writing anything -- construct the exact
        # `{"watch_conditions": [...]}` document shape
        # `atoo.watch_conditions.parse_watch_conditions` expects and
        # run the table's rows through the same validation
        # `POST /api/watch-conditions/load` uses, so a bad row (a
        # duplicate id the client-side check missed, an operator/value
        # incompatibility, ...) never reaches disk half-written.
        from atoo.watch_conditions import (
            DRAFTED_KEY, WatchConditionsError, canonical_target, parse_watch_conditions,
        )

        # The demo show's watch.json, or any file in the
        # packaged demo folder, is never written.
        refusal = _refuse_demo("Save", req.path)
        if refusal is not None:
            return refusal
        if not (req.path or "").strip():
            # No path is the open bundle's watch.json -- the
            # file goes with the bundle. With no bundle open there is
            # nowhere it belongs, as for step 03's instructions.md.
            if app.state.bundle is None:
                return JSONResponse(
                    {"error": f"no show bundle open -- {bundle.WATCH_CONDITIONS} lives in "
                              "one. Open a bundle (or New show…) first, or Change file "
                              "to pick a watch-conditions file to save into."},
                    status_code=400,
                )
            req = req.model_copy(update={
                "path": str(app.state.bundle.path(bundle.WATCH_CONDITIONS))})
            refusal = _local_only(request)
        else:
            refusal = _local_only_unless_loaded(request, req.path)
        if refusal is not None:
            return refusal

        # A position target is written in its one display
        # spelling (`ch10` -> `CH 10`); a name is left exactly as typed.
        rows = [
            dict(row, channel=canonical_target(row["channel"]))
            if isinstance(row, dict) and isinstance(row.get("channel"), str) else row
            for row in req.watch_conditions
        ]
        document: dict = {"watch_conditions": rows}
        # Carry forward the bookkeeping the table cannot see.
        # `drafted` records every id a build has ever proposed, and it is
        # the only thing that makes DELETING a drafted condition stick --
        # drop it here and the next `build --show` cheerfully re-adds
        # everything the operator just removed in this very editor. The
        # table round-trips the per-row `source` key on its own (watch.js
        # copies whole condition objects), but a top-level key is invisible
        # to it, which is exactly the blind spot a Python test cannot see.
        try:
            previous = json.loads(Path(req.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
        if isinstance(previous, dict) and previous.get(DRAFTED_KEY):
            document[DRAFTED_KEY] = previous[DRAFTED_KEY]

        text = json.dumps(document, indent=2) + "\n"
        try:
            validated = parse_watch_conditions(text, source=req.path)
        except WatchConditionsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        try:
            Path(req.path).write_text(text, encoding="utf-8")
        except OSError as exc:
            return JSONResponse(
                {"error": f"couldn't write watch-conditions file {req.path!r}: {exc.strerror}"},
                status_code=400,
            )

        app.state.watch_conditions = validated
        app.state.watch_conditions_path = req.path
        from atoo.watch_conditions import build_watch_rules
        reloaded = session.replace_rules(
            _with_plan_rules(DEFAULT_RULES + build_watch_rules(validated)), req.path)
        return {**_watch_payload(), "watch_reloaded": reloaded}

    @app.post("/api/watch-conditions/new")
    def api_watch_conditions_new(request: Request,
                                 req: Optional[NewWatchConditionsRequest] = None):
        # Watch's New file: an empty watch.json in the open
        # bundle, never over one that is there -- step 03's New file, for
        # Watch's file. Its place is fixed, so there is no dialog. "Empty"
        # is the smallest file Watch loads: `{"watch_conditions": []}`,
        # the built-in structural rules only until rows are added.
        refusal = _local_only(request) or _refuse_demo("New file")
        if refusal is not None:
            return refusal
        show = app.state.bundle
        if show is None:
            return JSONResponse(
                {"error": f"no show bundle open -- {bundle.WATCH_CONDITIONS} lives in one. "
                          "Open a bundle (or New show…) first."},
                status_code=400,
            )
        stale = _stale_bundle(req.expected_bundle if req else None, show, True)
        if stale is not None:
            return stale
        target = show.path(bundle.WATCH_CONDITIONS)
        name = show.directory.name or str(show.directory)
        if target.exists():
            return JSONResponse(
                {"error": f"{name} already has {_a_or_an(bundle.WATCH_CONDITIONS)} "
                          f"{bundle.WATCH_CONDITIONS} -- nothing was written"},
                status_code=409,
            )
        refusal = _write_new(target, json.dumps({"watch_conditions": []}, indent=2) + "\n")
        if refusal is not None:
            return refusal
        app.state.watch_conditions = []
        app.state.watch_conditions_path = str(target)
        display = f"{name}/{bundle.WATCH_CONDITIONS}"
        return {
            **_watch_payload(),
            "created": {"slot": "watch", "path": str(target), "display_path": display},
            "message": f"Created {display}, empty -- Watch uses only the built-in rules "
                       "until you add a condition and Save.",
        }

    def _open_plan_dict() -> dict | None:
        """The open bundle's plan, parsed; None without one or when it
        will not parse (Build reports a broken plan.json, not Watch)."""
        show = app.state.bundle
        if show is None or not show.plan.is_file():
            return None
        try:
            plan = json.loads(show.plan.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return plan if isinstance(plan, dict) else None

    def _with_plan_rules(rules: list[AuditRule]) -> list[AuditRule]:
        """`rules` bound to the open bundle's plan (`audit.with_plan_rules`):
        L002 quiet on a fader the plan puts at the floor,
        then CV015, CV016 and CV017, and the sends and routes against the plan (CV006,
        CV007, CV018). `rules` as they are without a bundle or a plan."""
        from atoo.audit import with_plan_rules

        show = app.state.bundle
        if show is None or not show.plan.is_file():
            return list(rules)
        return with_plan_rules(rules, show.plan)

    @app.post("/api/watch/start")
    async def api_start(req: ConnectRequest, request: Request):
        # async def, not sync -- FastAPI runs a sync path operation in a
        # worker thread pool, where there's no event loop for
        # asyncio.get_running_loop() to find. WatchSession.start's own
        # blocking work (opening a console) happens later, inside the
        # background thread it spawns, so nothing here blocks this loop.
        loop = asyncio.get_running_loop()

        # An optional watch-conditions file, loaded and
        # validated up front (same as a bad console IP -- a JSON error
        # response here, before any session starts, not a crash and not a
        # silently-ignored file) and turned into extra AuditRules layered
        # on top of the built-in structural rules, exactly the
        # `DEFAULT_RULES + build_watch_rules(conditions)` combination
        # `cli.watch_cmd` already builds for `--watch-conditions`.
        rules: list[AuditRule] | None = None
        # A scoped target on a Main or a Matrix (`MAIN PA`) needs names the
        # poll never reads: read once at Start, by the console's provider.
        start_names: list[str] = []
        if req.watch_conditions_path:
            from atoo.watch_conditions import build_watch_rules, start_name_addresses

            refusal = _local_only_unless_loaded(request, req.watch_conditions_path)
            if refusal is not None:
                return refusal

            conditions, error = _load_watch_conditions_from_path(req.watch_conditions_path)
            if error is not None:
                return JSONResponse({"error": error}, status_code=400)
            rules = DEFAULT_RULES + build_watch_rules(conditions)
            start_names = start_name_addresses(conditions)
        # The open show's plan: an FX bus's effect (CV015),
        # a channel cut off from every planned route (CV016), a
        # mute the plan does not have (CV017), and L002 quiet
        # on a fader the plan itself puts at the floor.
        rules = _with_plan_rules(rules if rules is not None else DEFAULT_RULES)

        # The page sends `console` and means the bundle bar's,
        # and when the bar holds Demo that IS the demo -- Watch follows the
        # bar, as Ping and Apply do. The bar holds Demo
        # only while the demo show is open, so there is no Demo watch on
        # any other show: `source: "demo"` is gone, and a scripted client
        # chooses Demo as the page does (`POST /api/console` with `demo`).
        bar_is_demo = bool((app.state.console_defaults or {}).get("demo"))
        if req.source == "demo":
            return JSONResponse(
                {"error": "there is no Demo source -- Demo is the demo show, chosen in the "
                          "bundle bar's console dialog (POST /api/console with demo). Watch "
                          "then follows the bar with source \"console\"."},
                status_code=400)
        if req.source == "console" and not req.console and bar_is_demo:
            session.start(loop, demo_provider_factory, req.interval, DEMO_CONSOLE_LABEL,
                          rules=rules, virtual_soundcheck=req.virtual_soundcheck)
            session.watch_path = req.watch_conditions_path or None
            return session.status()
        if req.source == "console":
            # The bundle bar's console, like every other desk-facing
            # endpoint here -- the page sends none
            # (one console field, in the bar). A `console` in the request
            # is a scripted client's override and brings its own port and
            # timeout with it.
            if not req.console:
                defaults = app.state.console_defaults or {}
                bar_address = (defaults.get("address") or "").strip()
                if not bar_address:
                    return JSONResponse(
                        {"error": "no console address -- type one into the Console field "
                                  "in the bundle bar"},
                        status_code=400)
                req = req.model_copy(update={
                    "console": bar_address,
                    "port": int(defaults.get("port") or 2223),
                    "timeout": float(defaults.get("timeout") or 1.0),
                })
            read_kwargs = {
                "input_sockets": _parse_socket_counts(req.input_sockets),
                "output_sockets": _parse_socket_counts(req.output_sockets),
                "bulk": not req.per_leaf,
            }

            # Passed only when there is something to read, so a factory
            # written before scoped names (a test's stand-in) still fits.
            extra = {"start_name_addresses": start_names} if start_names else {}
            # The open show's plan names the output sockets it
            # patches, which the desk's panel alone does not cover.
            open_plan = _open_plan_dict()
            if open_plan is not None:
                extra["plan"] = open_plan

            # Names at Start and every N readings, as
            # `atoo watch` does; every reading with per_leaf.
            from atoo.watch import DEFAULT_NAME_REFRESH

            name_refresh = (req.name_refresh if req.name_refresh is not None
                            else 1 if req.per_leaf else DEFAULT_NAME_REFRESH)
            if name_refresh < 1:
                return JSONResponse({"error": "name_refresh must be 1 or more"},
                                    status_code=400)

            def factory():
                return console_provider_factory(
                    req.console, port=req.port, timeout=req.timeout, read_kwargs=read_kwargs,
                    name_refresh=name_refresh, **extra,
                )

            # What `atoo watch` prints about the window, the
            # page shows as a session note. The Demo's rig is not read over
            # the network, so it has no window to speak of.
            from atoo.watch import window_note

            window = window_note()
            session.start(loop, factory, req.interval, f"{req.console}:{req.port}", rules=rules,
                          notes=[window] if window is not None else None,
                          virtual_soundcheck=req.virtual_soundcheck)
            session.watch_path = req.watch_conditions_path or None
            return session.status()
        return JSONResponse({"error": f"unknown source {req.source!r}"}, status_code=400)

    @app.post("/api/watch/stop")
    def api_stop():
        session.stop()
        return session.status()

    @app.post("/api/watch/virtual-soundcheck")
    def api_virtual_soundcheck(req: VirtualSoundcheckRequest):
        # The Virtual soundcheck switch, changed while a watch runs. Before
        # Start it rides the Start request instead, so a press with no
        # watch running changes nothing and says so.
        if not session.set_virtual_soundcheck(req.on):
            return JSONResponse(
                {"error": "no watch is running -- Virtual soundcheck is chosen when you start "
                          "watching"}, status_code=409)
        return session.status()

    @app.websocket("/ws/watch")
    async def ws_watch(websocket: WebSocket):
        await websocket.accept()
        loop = asyncio.get_running_loop()
        queue = session.subscribe(loop)

        async def pump():
            while True:
                payload = await queue.get()
                await websocket.send_text(json.dumps(payload))

        async def until_closed():
            # The page never sends on this socket (a frame that arrives is
            # ignored), so this returns when it CLOSES -- a tab shut, or uvicorn's own close
            # on SIGTERM/SIGINT. Without it the handler sat in
            # `queue.get()` forever, and uvicorn's shutdown waits for every
            # handler to finish: one Watch page opened once kept the
            # server alive through `kill`.
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass

        async def then_end(tg: anyio.abc.TaskGroup, part: Callable) -> None:
            # Whichever half finishes first ends the other. A disconnect is
            # caught here rather than around the group, which would wrap it
            # in an ExceptionGroup (and `except*` needs Python 3.11).
            try:
                await part()
            except WebSocketDisconnect:
                pass
            tg.cancel_scope.cancel()

        # An anyio task group, not bare asyncio tasks: the server cancels a
        # handler through anyio's cancel scope, and a cancel landing while
        # hand-rolled asyncio tasks were still being torn down escaped the
        # handler instead of ending it (a CancelledError out of the
        # TestClient's close, under load).
        try:
            await websocket.send_text(json.dumps({"type": "status", **session.status()}))
            async with anyio.create_task_group() as tg:
                tg.start_soon(then_end, tg, pump)
                tg.start_soon(then_end, tg, until_closed)
        except WebSocketDisconnect:
            pass
        finally:
            session.unsubscribe(queue)

    return app
