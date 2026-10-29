# Reporting a problem

If something looks wrong, didn't land on the desk, or made no sense, tell us. A ZIP'd show bundle that has been applied to your desk is the most useful kind of feedback.

## What to send

On the repository's **Issues** tab, click **New issue**. Choose **Desk test report** for something you saw on a desk, or **Bug** for anything else. Send us your show folder if you can. If not, be sure to tell us:

- Your desk model and firmware (the last field of the `Console:` line from `a2 ping`), your laptop, and how you installed Atoo.
- What you ran, what you expected, and what you saw.
- For a write, the line that starts `APPLIED:` and any `MISMATCH` lines under it, pasted as text.
- A screenshot of anything confusing.

## Send your show folder, zipped

The most useful thing you can send is the show folder itself, zipped, with a reading of the desk inside it. Do this **right after the Build or Apply you are reporting**, before you build, apply, undo or change anything else, so the folder and the reading show the moment it went wrong.

### 1. Find the show folder

Each show is a folder in your Atoo folder, which is `Documents/Atoo` in your home folder unless you chose another location. `atoo ui` prints it as `Working folder:` when it starts, and the show's name is in the Show bundle bar at the top of the page.

The folder holds the show's files: `input.csv`, `plan.json`, `watch.json`, and after an Apply its `journals/` folder, the record of every write and undo.

### 2. Save a reading of the desk into it

Open a terminal, go to your Atoo folder, and read the desk into the show folder. Use your desk's address and your show's folder name; here it is `demo-show`, the copy of the built-in demo show that `atoo init --demo` makes. If the name has a space in it, put it in quotes (`"Sunday service"`):

```
cd ~/Documents/Atoo
atoo audit --console 192.0.2.16 --show demo-show --dump-state demo-show/desk-reading.state.json
```

On Windows, in PowerShell, the first line is `cd ~\Documents\Atoo`.

It reads the desk and writes nothing to it. When the reading is saved it says so:

```
Saved 6309 addresses to demo-show/desk-reading.state.json. The file does not record the model (wing-compact): replay it with --plan so the audit knows which desk it came from.
```

An audit of the desk against the show follows; you can leave it, or paste it into your report. The reading holds the desk's names and settings, not audio, and not the desk's address or serial number.

If you built with no desk connected, skip this step.

### 3. Zip the folder

- **Mac:** in Finder, Control-click (or right-click) the show folder and choose **Compress "demo-show"**. `demo-show.zip` appears next to it.
- **Windows:** in File Explorer, right-click the show folder and choose **Send to** > **Compressed (zipped) folder**. On Windows 11 it is under **Show more options**, or choose **Compress to** > **ZIP File**. `demo-show.zip` appears next to it.
- **Linux:** in your file manager, right-click the show folder and choose **Compress**, or in a terminal, from the folder that holds it, run `zip -r demo-show.zip demo-show`. `demo-show.zip` appears next to it.

Attach the zip to your report: to the issue (drag it onto the comment box), to your email, or to the tester form if you were sent one.

**What the zip holds.** Your show's files, the desk reading, `plan.json`, the build logs in `builds/`, and the journals of any writes.
