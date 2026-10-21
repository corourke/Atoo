# Changelog

What changed in each release, newest first.

## 0.2.4 -- 2026-10-21

Fixes from the first runs of the installed 0.2.3, and a faster, clearer Apply.

- **Apply: "Initialize the console first" is a switch.** Under Options, one
  switch (on by default) sets the desk to its initialized state before the
  plan is written, and says what it leaves alone: the desk's network and
  clock, expansion-card setup, meter and RTA display, monitor and solo
  listening. The typed "Disconnect output sockets the plan doesn't use" box
  is gone, and with it the page lock a bad value in that box caused.
  `atoo apply --clean-output-sockets` stops with a plain sentence and exit 2
  for a value that is not `LCL=8,A=48`-shaped, not a traceback.
- **Preview is faster, and is one step.** A preview now reads the desk in one
  "reading the desk" step instead of two, and reads the plan's current values
  by node dump rather than one address at a time (the Compact: about a third
  fewer requests). A figure a preview shows as the current value may be the
  desk's rounded readout; a number whose rounding could change what "would
  change" says is read again exactly. A real apply, its journal and Undo
  always use exact values.
- **Patch: an insert renumbers, add-after does not.** Say "insert",
  "renumber" or "make room" and the channels after the new one move down,
  each rewritten whole, in one undoable scope; "add X after Y" takes the next
  free strip and says so. A new channel is never given an input that does not
  exist on the stage box (an S16 has 16), and a line source on a stage-box
  preamp gets 0 dB unless the conventions or instructions state a gain.
  A strip a change frees is left off, not reset.
- **Patch: an overlong name no longer refuses a paid reply.** A name that is
  only a label is cut to the length it is shown at (48 for a change, 16 for
  an added channel) and the review says so at INFO. A rename in a change is
  length-checked too.
- **Every command that touches a desk or the model says which Atoo ran**
  (its version and where it is installed), warnings appear where the summary
  says they will, and preamp gains are compared on the preamp's own
  2.5 dB steps.
- **Watch hears channels again.** Clip detection now follows every channel
  (the desk keeps one meter stream per connection), the status goes to "off:
  meter data stopped" within a few seconds if the stream stops and recovers
  by itself, and a clip ends only after the level stays below -3 dBFS for
  200 ms.
- **Watch page.** The condition's info icon works on the Demo, is larger and
  blue, and sits in line with the ID; the "Drafted" tag is blue; the verdict
  bar and table headings stay at the top; Hide is a check box at the left of
  the row.
- **Audit and Watch.** A bus's, Main's and Matrix's EQ and a channel's PreSend
  EQ are checked against the plan, and a signal that splits and recombines
  on its way to a Main or Matrix is flagged unless the plan asks for it.
- **Apply: the History table's columns** give the summary the width and size
  the rest to their content.
- **The project page on PyPI links to real pages.** The README's links were
  relative (`docs/user/install.md`), which point at nothing on pypi.org; they
  are now absolute.

## 0.2.3 -- 2026-10-19

The first release on PyPI, with two fixes to the install from the first
test on a stock Mac, and a plain-English explanation of each Watch condition.

- **On PyPI.** The install is now
  `uv tool install --python 3.12 "atoo[ui]"`, with no GitHub address and no
  `git`; the commands `atoo` prints say the same.
- **The install names its Python.** `uv tool install` could choose the
  Python 3.9 that Apple's Command Line Tools put on a Mac and stop, because
  Atoo needs 3.11 or newer. Every install command now says
  `--python 3.12`, so uv uses a 3.12 it has or downloads one. That covers
  [Installing Atoo](docs/user/install.md), the README and the commands
  `atoo` itself prints.
- **`atoo` is on your `PATH` after the install.** On a new Mac account the
  command was not found until `uv tool update-shell; exec zsh`. The install
  page now has that step straight after the install.
- **Watch explains each condition.** A small `i` beside a condition's ID
  opens a plain-English sentence for the rule ("Alerts as an error when CH 1
  has its fader below -40 dB."), written from the condition's own fields,
  and it follows the row as you edit it.

## 0.2.2 -- 2026-10-19

The install is shorter, and the first release meant for PyPI.

- **Install with uv.** On a Mac or Linux the install is two commands and
  one new terminal window: the uv installer, then
  `uv tool install "atoo[ui] @ git+https://github.com/corourke/Atoo.git"`.
  uv fetches the Python Atoo needs, so there is no Homebrew, pipx or Python
  step. Homebrew with pipx still works and has a short section of its own.
  [Installing Atoo](docs/user/install.md) walks it. The checkout page now
  has you check the Python version first, which a stock Mac's 3.9 fails.
  `atoo --version` and the "needs the ui extra" hint know about a uv
  install, and say the uv command to fix it.
- **Build and Apply.** A stereo channel's two sockets switch 48V together
  on the desk, so a pair built from two input-list rows now gets one
  value: on if either row wants it, said at INFO with the row that asked.
  A passive ribbon microphone on either side of a powered pair is an
  error; an older plan with two different values is read as on-if-either
  and reported.
- **Watch and the screens.** The Hide button on a Watch row stays in one
  place and is a real touch target on a phone. Text sizes are on the
  guide's scale (11 to 16 pixels), so a few small labels are a pixel
  larger.
- **Source.** The comments and one model-prompt preamble in the public
  code read as explanations; they no longer carry the project's issue
  numbers or the name of a private document.

## 0.2.1 -- 2026-10-18

A small release on 0.2.0, from a first desk test of the installed 0.2.0 and
the first run of the public tests.

- **The public test suite runs.** `pytest` finds the tests when run as a
  bare command, as the public workflow runs it. 0.2.0's first run failed to
  collect them.
- **Audit.** `audit --plan` reads the trim, balance, invert and head-amp
  gain values the plan states, so a show that was just applied no longer
  gets warnings that those values were "unread".
- **Build.** `atoo build --show` takes the console model from the show's
  plan when `--console-model` is not given, and says so. The starter kick
  preset's file is now `Kick In.chn`, as the guide calls it.
- **Apply.** A full apply disconnects the desk's own output sockets that no
  bus, Main or Matrix of the plan is patched to (local outputs 3-8 on a
  Compact, which ship patched to busses and Mains), says which at INFO, and
  Undo puts them back. Before, they stayed as the desk shipped unless
  `--clean-output-sockets` was passed, and the audit called them leftovers.
- **Patch.** The pre-flight reads the show's input list, so
  `reconcile.not-checked` appears only when the show has none. A change that
  switches 48V on a stereo channel switches both sockets, and a change that
  would switch one side alone is refused: the desk does not take it.

## 0.2.0 -- 2026-10-16

Still early. Full applies are proven on one WING Compact; a full-size
WING has been read and watched, and a WING Rack is untested.
[Where it needs work](docs/user/limitations.md) says what is not built
or not yet proven.

- **Python 3.11 or newer.** 0.1.0's package accepted 3.9; this one
  needs 3.11, as the install page already said. A stock Mac's `python3`
  is 3.9: [Installing](docs/user/install.md) step 3 says what to do.
- **Watch calls a clip an ERROR.** When a channel, aux, bus, Main or
  Matrix clips, Watch shows an ERROR for about a minute, restarted by
  each new clip, and says how long the clip lasted where that is known.
  It listens to the desk's meters on a connection of its own and writes
  nothing. A note on the Watch page says whether clip detection is on,
  and why not when it is off.
- **More that Watch and `audit` catch, all from what a read already
  fetches:**
  - a channel or aux in use whose signal reaches no bus, Main or
    Matrix, and one in use with nothing patched to it;
  - a strip fed from an input socket that is muted at the socket, which
    nothing on the strip shows;
  - a feedback loop through a bus, Main or Matrix used as a channel's
    input (an ERROR when every leg is open, a warning when one is
    closed);
  - an AES50 stage box whose link is not OK, or a patch to a port with
    nothing on it;
  - a muted DCA over channels in use;
  - a stereo bus, Main or Matrix patched to one side of its output pair
    only.
- **More of the plan checked against the desk, during the show too.**
  With the show's plan, Watch now says when a planned send is off or has
  changed between pre and post fader, when a planned Main route is off,
  and when a send or route is on that the plan does not have (a click
  or talk mic opened into the PA). `audit --plan`, and Watch, also
  compare 48V and bus width with the plan, and say when talkback misses
  a monitor mix the plan builds. `audit --plan` compares the high-pass,
  hi-cut, tilt and EQ as well.
- **A Virtual soundcheck switch.** A channel on its alternate input, or
  the desk's global alternate switch, is a warning, because no show
  starts that way. With Virtual soundcheck on (the Watch page, or
  `atoo watch --virtual-soundcheck`) they are reported at INFO, every
  strip still named; turned off, anything still on its alternate is a
  warning again at once.
- **Watch conditions** take sends and 48V: `send_on`, `send_db` and
  `send_mode` to a named bus, and `phantom`. A rebuild no longer drafts
  a condition the show's `watch.json` already has.
- **Watch reads more plainly.** The verdict line says where and what,
  each alert row has a Hide button that names its finding, and the
  empty table's sentence follows the console you chose.
- **Apply.**
  - Step 3 is arm and one action: Write, or Undo. The newest run in
    History has Preview undo, which shows in step 2's preview what an
    undo would change before you arm it.
  - A full build writes only the settings that differ from the desk.
    The page now counts everything a write will send, and the write
    says how many it changed and how many were already right. Straight
    after a full build, a preview proposes nothing: a stereo source's
    second socket now takes its gain from the plan.
  - After a rebuild that changed something, Build offers **Apply the
    difference**: it opens Apply with Full build chosen and the preview
    already run, once the desk has been read.
  - Choices are controls, not buttons: Full build or Patch, which
    console, the theme, Flash on new and Virtual soundcheck.
- **Patch.** The browser's Patch is one thing: type a change. Applying
  a rebuilt plan is `atoo amend`. A change whose answer leaves out
  empty sections is read rather than refused, and moving a channel to
  another strip is a move, not a removal and a new channel. A change
  can edit a channel or bus of a show built with presets (rename it, set
  its fader or mute); 0.1.0 refused every such edit. A change can also
  switch 48V and set the mic model on a running strip: the review marks
  a live 48V change, and a passive ribbon microphone left with 48V on is
  refused.
- **Apply and Watch.** The History table stays inside its card on a
  phone-width screen. A stopped watch's "Updated" line clears when the
  show or console changes, and the page no longer logs 404s with no show
  open.
- **Build.** The findings say Stale, not Ready to apply, for a plan
  older than its files. The editors keep Save and Discard at the top.
  The plan check reads a mute or fader the plan leaves unset the way
  the desk will hold it.
- **`atoo --version`** says which copy is running: the version, where
  it runs from and, for a git checkout, its branch and commit. `atoo
  ui` prints the same line and shows it in the page footer. When the
  browser part is not installed, the message names the install that
  works for that copy.
- **`atoo init`** also copies the audit demo files, and the help and
  messages point at [docs.atoo.app](https://docs.atoo.app/).

## 0.1.0 -- 2026-10-13

Early. Tested on one WING Compact; [Where it needs work](docs/user/limitations.md)
says what is not built or not yet proven.

- **The name is Atoo.** The command is `atoo`, with
  `a2` as a short spelling of the same command; the package is `atoo`;
  the environment variables are `ATOO_*`; the settings file is
  `~/.atoo.config` and `atoo init`'s working folder `~/Documents/Atoo`.
  The audit rule ids drop their `SP-` prefix: `SP-R005` is `R005`,
  `SP-CV016` is `CV016`. Nothing reads the old names: rename them.
- **Getting started.** `atoo init` makes a working folder with
  starter house conventions and a preset library (twenty channel
  presets and three bus presets, made on a real WING), and points
  `~/.atoo.config` at them. `atoo init --demo` also copies the
  Demo show there as a show of your own to edit, build and apply.
- **Build.** A model drafts the plan for a show from your input list
  and your house conventions. Code with no model in it checks every
  value against the desk's real limits, and every choice your files did
  not state is announced as an INFO finding. A clean build is quiet: the
  findings split into the choices it made and the build details behind
  them. Channels and busses take presets from your library, an FX bus
  its effect from a bus preset, and an instrument named without its
  kind takes the most common one's preset, said in the notes.
- **Apply.** A preview by default; one explicit arm writes. In the
  browser it is four steps: what will be written, a preview that draws
  the desk as scribble strips with every change outlined, arm and
  write, and the history of writes. Every write is read back from the
  desk, anything that did not land is named, and `undo` reverses one
  run. Long reads and writes say what they are doing as they go. Desk
  reads keep several requests in flight; how much faster that is on a
  real desk has not been measured yet. Patch and amend change only what
  they say, for the setup window; patch finds the show's preset library
  itself.
- **Watch.** A read-only check of the desk on a loop, during the show,
  against your own watch conditions and, with the show's plan, against
  the plan: a route, a mute or an FX bus's effect that has drifted from
  it.
- **In the browser or the terminal.** `atoo ui` for Build, Apply
  and Watch, and every step as a command. A packaged Demo show runs
  with no desk: its Apply previews against a simulated WING, and its
  Watch sees faults come and go.
- **Consoles:** WING Compact, WING and WING Rack. A full apply resets
  the desk to its initialized state first on the Compact and the
  full-size WING; there is no initialized capture of a Rack yet.
