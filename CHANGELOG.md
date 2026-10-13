# Changelog

What changed in each release, newest first.

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
