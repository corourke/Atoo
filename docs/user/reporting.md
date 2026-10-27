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
- A screenshot of anything confusing.

## Send your show folder, zipped

The most useful thing you can send is the show folder itself, zipped,
with a reading of the desk inside it. Do this **right after the Build or
Apply you are reporting**, before you build, apply, undo or change
anything else, so the folder and the reading show the moment it went
wrong.

### 1. Find the show folder

Each show is a folder in your Atoo folder, which is `Documents/Atoo` in
your home folder unless you chose another. `atoo ui` prints it as
`Working folder:` when it starts, and the show's name is in the Show
bundle bar at the top of the page.

The folder holds the show's files: `input.csv`, `plan.json`,
`watch.json`, and after an Apply its `journals/` folder, the record of
every write and undo.

### 2. Save a reading of the desk into it

Open a terminal, go to your Atoo folder, and read the desk into the show
folder. Use your desk's address and your show's folder name. The quotes
are needed when the name has a space in it:

```
cd ~/Documents/Atoo
atoo audit --console 192.0.2.16 --show "Demo show" --dump-state "Demo show/desk-reading.state.json"
```

On Windows, in PowerShell, the first line is `cd ~\Documents\Atoo`.

It reads the desk and writes nothing to it. When the reading is saved it
says so:

```
Saved 67 addresses to Demo show/desk-reading.state.json. ...
```

That number is much larger on a real desk. An audit of the desk against
the show follows; you can leave it, or paste it into your report. The
reading holds the desk's names and settings, not audio.

If you built with no desk connected, skip this step.

### 3. Zip the folder

- **Mac:** in Finder, Control-click (or right-click) the show folder and
  choose **Compress "Demo show"**. `Demo show.zip` appears next to it.
- **Windows:** in File Explorer, right-click the show folder and choose
  **Send to** > **Compressed (zipped) folder**. On Windows 11 it is
  under **Show more options**, or choose **Compress to** > **ZIP File**.
  `Demo show.zip` appears next to it.

Attach the zip to your report: to the issue (drag it onto the comment
box), to your email, or to the tester form if you were sent one.

**What the zip holds.** Your show's files, the desk reading, and the
journals of any writes. A journal records the network address and the
serial number of the desk it wrote to, so Undo writes back to the same
desk. No audio, and nothing from outside the show folder.

Tick **Credit** on the form if you're happy to be thanked by name in the
release notes.
