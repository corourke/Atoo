# Where Atoo needs work

What it cannot do yet, what has not been proven on a real desk, and
where it is rough. Read this before you rely on it for a show.

## It is early

One engineer has used it so far, on their own desks and shows. It has
not yet met yours. Keep a saved show file on the desk as your fallback,
as you would with any new tool.

## Not yet seen on a real desk

Shipped, and checked against a simulated WING, but not yet run against
a real one:

- **The four-step Apply screen.** Its preview, the desk drawn as
  scribble strips, a write and Undo from the browser have run only on a
  simulated WING, so the strip colours (approximations of the WING's
  eighteen) and the names a real desk reads back are unchecked. The same
  writes from the command line have been proven on a WING Compact.
- **Several reads in flight at once.** Desk reads now keep 8 requests on
  the wire. How much faster that is on a real desk, and whether a desk
  drops requests when several arrive together, has not been measured;
  `ATOO_CONSOLE_WINDOW=1` puts back one at a time
  ([A desk read is slow](troubleshooting-desk.md#a-desk-read-is-slow)).
- **A fresh build of the Demo since its findings were quietened.** The
  quieter findings were checked by replaying an earlier build without a
  model; a new build with a real model has not been run since.

## Consoles

- **Behringer WING only**: the Compact, the full-size WING and the Rack.
  No other console, the X32 and M32 included.
- **Full applies have been proven on a WING Compact.** A full-size WING
  has been read and watched on a real desk. A WING Rack has not yet been
  connected at all: its sockets come from Behringer's documentation, and
  a full apply cannot reset a Rack to its initialized state first (it
  says so with a WARNING).
- **It cannot recall the desk's own scenes, snapshots or libraries.**
  Those cannot be reached over the network. Your channel presets are
  written as ordinary values instead ([Using channel presets](presets.md)),
  and that has been checked on a WING Compact.

## Building a plan

- **A build needs your own AI API key**, which you pay for. Atoo is
  built and tested on Claude. A local model through Ollama can be set
  up, but local models have not worked well so far. A build takes
  minutes, and a large show costs more than a small one ([Choosing the model](configuration.md#choosing-the-model)).
- **The plan is only as good as your conventions.** Where they are
  silent, it makes the usual choice and says so at INFO, folded under
  **Choices** in the Findings panel. Stating more in your conventions
  shortens that list.
- **A model can still get things wrong in ways the checks cannot see**:
  a send level that is legal but not what you wanted. The checks catch
  what the desk cannot do, not what you would not do. Read the plan.

## Writing to the desk

- **A full apply is for setting up**, not for a desk in use: it writes
  every fader. For a running show use [Patch](patch-a-show.md), and only
  in the setup window, not mid-show.
- **Undo reaches back five writes** per show. Beyond that, put the desk
  right with a full apply or a patch.
- **Some parameters may refuse a value without saying why.** A readback
  mismatch is reported, but the list of parameters that do this has not
  been measured yet.

## Watching a show

- **Watch is the least tested part.** It has run on a real Compact, but
  not yet through a whole show. Expect noise: a desk can show many
  findings at once, and some built-in checks fire on choices you made on
  purpose. Your own watch conditions are the most useful part today.
- **Names are re-read about every 30 seconds**, so a renamed channel can
  take that long to be recognised, and a Main or Matrix name only at
  **Start watching**.

## The browser UI

- **Tested in Chromium-based browsers.** Firefox and Safari have not been
  checked. At phone width only the Watch screen has been checked, in
  Chromium, and not on a real phone.
- **It runs on one laptop.** Another machine on the network can watch,
  but nothing else ([Troubleshooting](troubleshooting-ui.md#another-computer-can-open-the-page-but-only-to-watch)).
- **The screens are busy.** There is a lot of explanatory text. The
  Findings panel folds the build's notes away, but a typical plan still
  carries many of them.

## Your laptop

Tested on macOS and Linux with Python 3.11 or newer. Windows has not
been tried: [Installing](install.md#windows) says what to expect.

## Telling us

Found something wrong, or something this page should say? Open an issue
on the repository with what you ran, what you expected, and what you
saw.

## See also

- [Testing on your desk](testing-on-your-desk.md): how to check it on yours, and what to send back
- [FAQ](faq.md)
- [Troubleshooting](troubleshooting.md)
