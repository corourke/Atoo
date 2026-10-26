# Reporting a problem

If something looks wrong, didn't land on the desk, or made no sense,
tell us. A report from your own desk, with its own stage boxes and
firmware, is the most useful kind.

## What to send

On the repository's **Issues** tab, click **New issue**. Choose
**Desk test report** for something you saw on a desk, or **Bug** for
anything else. You can also send the same by email. Tell us:

- Your desk model and firmware (the last field of the `Console:` line
  from `a2 ping`), your laptop, and how you installed Atoo.
- What you ran, what you expected, and what you saw.
- For a write, the line that starts `APPLIED:` and any `MISMATCH` lines
  under it, pasted as text.

## Files that help

Zip up and attach whatever you have of:

- **A reading of the desk.** `atoo audit --console 192.0.2.16
  --dump-state my-desk.state.json` saves one. It holds the desk's names
  and settings, not audio. A reading from before and after a write shows
  exactly what changed.
- **The journal of a write**, and of its undo: the files in your show's
  `journals/` folder.
- **A screenshot** of anything confusing.

Tick **Credit** on the form if you're happy to be thanked by name in the
release notes.
