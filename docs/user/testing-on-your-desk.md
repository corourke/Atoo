# Testing on your desk

Atoo has written full shows to one model of desk. Yours is the
test it has not had. This page is four steps, each safer than the next
one, and you can stop after any of them: a report from step 2 is worth
sending.

**Wanted most:**

- **A WING Rack**, any step. A Rack has never been connected. Above all,
  its **initialized capture** ([below](#a-wing-rack-the-initialized-capture)):
  without one, a full apply cannot reset a Rack first.
- **A full-size WING through step 3.** Full applies, readback and undo
  are proven on a WING Compact only. A full-size WING has been read and
  watched on a real desk.

You need Atoo [installed](install.md), and for steps 2 and 3 a
laptop on the same network as the desk, with its OSC remote on. The
examples use `192.0.2.16` for the desk: type your own.

## 1. No desk (15 minutes)

Nothing here touches a console.

1. Run `atoo ui`, and press **Try the Demo show**.
2. Click through **Build**'s four tiles, then **Apply** (the pre-flight
   reads **0 errors · 0 warnings**), then **Watch** and **Start
   watching**: the simulated desk raises faults that come and go.

[Try the Demo show](demo.md) says what each screen shows. Note anything
you had to guess at.

## 2. Read-only on your desk (15 minutes)

These three never write. They are safe on a desk that is doing a show,
though the first time is better done on one that is not.

1. **Ping**. It sends one message:

   ```bash
   atoo ping --console 192.0.2.16
   ```

   It prints the desk's identity on a `Console:` line, firmware last,
   and a `Detected model:` line. Keep both for the report (blank out the
   serial if you like). `Detected model: not recognised` is a finding in
   itself.

2. **Audit**. It reads the whole desk and checks it against built-in
   rules (a 48V socket nothing is patched to, a DCA at the floor with
   live members, two strips with one name). `--dump-state` keeps what it
   read:

   ```bash
   atoo audit --console 192.0.2.16 --dump-state my-desk.state.json
   ```

   Check each finding against the desk. A finding that is wrong about
   your desk is the most useful thing you can send.

3. **Watch**, for a few minutes. In `atoo ui`, choose your desk
   next to **Console** (**Change…**, **Address**), then **Watch**,
   **Start watching** ([Watch the desk during a show](watch-a-show.md)).
   Pull a DCA that has channels in it to the floor: a row appears, and
   clears when you push it back up.
   From the command line, three readings:

   ```bash
   atoo watch --console 192.0.2.16 --count 3
   ```

To see what an audit prints before you go near a desk, a saved reading
stands in for one (from a clone of the repository):

```
atoo audit --state docs/user/demo/audit-demo/audit_demo_state.json
```

```
Audit findings: 7 warning, 8 info.

[WARNING] C001 Phantom Power On Unpatched Socket
  48V is on for LCL 9 but nothing is patched to it -- no channel, no aux and no user patch.

[WARNING] CH002 DCA Fader Low With Active Members
  DCA 1 "Drums" is at the floor (-20dB or lower) but controls 2 active member(s): CH 1 "Kick", CH 2 "Snare".
  ...
```

## 3. Write, then undo (30 minutes)

**Only on a desk that is not doing a show.** A full apply takes the
whole desk: it resets it to the initialized state (network, clock,
cards and your monitor listening are left alone), unpatches the strips
the plan does not build, then writes the plan
([what a full apply changes](what-apply-changes.md)).

1. **On the desk, save the show that is on it**, to the desk or a USB
   stick. This is your way back if everything else fails.
2. **Copy the Demo show to a folder of your own.** The one Atoo
   ships is read-only.

   ```bash
   atoo init --demo
   ```

   This writes it into your Atoo folder as
   `~/Documents/Atoo/demo-show`, beside the starter conventions and
   presets it was built from, and lists each file it copied. If you have
   run `init` before, it adds only the copy; a `demo-show` already there
   is left alone. (With `init --dir`, the copy is in that folder: use its
   path below.)

3. **Check it against your desk's model**, with nothing contacted:
   `atoo verify --show ~/Documents/Atoo/demo-show --console-model wing-full`
   (or `wing-compact`, `wing-rack`). It should pass, as the Demo show
   does (below).
4. **Keep a reading from before**:
   `atoo audit --console 192.0.2.16 --dump-state before.state.json`.
5. **Preview**. It reads the desk and shows each value now and after,
   and writes nothing:

   ```bash
   atoo apply --show ~/Documents/Atoo/demo-show --console 192.0.2.16
   ```

6. **Write**. `--confirm` is the arm:

   ```bash
   atoo apply --show ~/Documents/Atoo/demo-show --console 192.0.2.16 --confirm
   ```

   Every value is read back. Copy the line that starts `APPLIED:`, and
   any `MISMATCH` lines under it. On a WING Rack, expect a WARNING that
   there is no initialized capture: the plan is written without the
   reset.
7. **Look at the desk.** Names, colours, patch, sends, DCAs: does it
   match the [Demo show](demo.md)?
8. **Undo** the write. Preview first, then arm it:

   ```bash
   atoo undo --show ~/Documents/Atoo/demo-show --console 192.0.2.16
   atoo undo --show ~/Documents/Atoo/demo-show --console 192.0.2.16 --confirm
   ```

9. **Keep a reading from after**:
   `atoo audit --console 192.0.2.16 --dump-state after.state.json`.
   Undo should have put back what the apply changed; the two readings
   show whether it did.
10. **Load your saved show** back onto the desk.

The browser does the same from **Open…** on your copy, then **Apply**:
see [Apply a plan to the desk](apply-to-desk.md).

Step 3 on the copy (it ends `APPLICABLE: notes only`):

```
atoo verify --show ~/Documents/Atoo/demo-show --console-model wing-full
```

```
0 error(s), 0 warning(s), 4 note(s)
  ...
```

### A WING Rack: the initialized capture

If you can spare a Rack for ten minutes, this is the most wanted thing
on the page. Save its show first; this clears the desk.

1. Initialize the Rack from **Setup** on the desk.
2. `atoo audit --console 192.0.2.16 --dump-state rack-initialized.state.json`
3. Save the show (`.snap`) from the desk or WING Edit.
4. Load your own show back.

## 4. Report

Open a **Desk test report** on the repository's **Issues** tab (**New
issue**), or send the same by email. It asks for:

- the desk model, the firmware (the last field of `ping`'s `Console:`
  line), your laptop and how you installed;
- which steps you ran, and **where you stopped, and why**;
- for step 3, the `APPLIED:` line and any `MISMATCH` lines, as text;
- anything that did not land, looked wrong, or made no sense.

Attach, zipped, whatever you have of:

- `my-desk.state.json`, `before.state.json` and `after.state.json`;
- the journals of your write and its undo: the files in
  `~/Documents/Atoo/demo-show/journals/`;
- from a Rack, `rack-initialized.state.json` and the `.snap`;
- a screenshot of anything confusing.

A state file holds the desk's names and settings, not audio. Tick
**Credit** if you are happy to be thanked by name in the release notes.

## See also

- [Limitations](limitations.md): what has and has not been seen on a real desk
- [Apply a plan to the desk](apply-to-desk.md) and [Undo](undo.md): the write and its undo, in full
- [Troubleshooting: the desk](troubleshooting-desk.md)
