# Connect to your desk and try the CLI

This page walks you through an initial connection to your desk, and gives you a brief tour of the Atoo command line interface (CLI). You will go through four steps, each one doing a little
more than the last: connect, read, write and undo. You can stop after any step.

[Try the Demo show](demo.md) first: it is the same screens, with no
desk. You need a laptop on the same network as the desk. The examples use
`192.0.2.16` as the desk's address; use your own desk's IP address.

If you are testing a branch from a clone, first check [which atoo you
are running](install-from-checkout.md#4-which-atoo-am-i-running).

## 1. Before you start

1. **Find the desk's address.** On the desk, it is in **Setup**, under
   the network settings. If you are not at the desk, WING-EDIT on a
   laptop on the same network shows the address of each desk it finds.
2. **Save the show that is on the desk.** Press **Library**, then
   **Snap**, then **Save**; set **Scope** to **All** and press **Save**.
   This is your way back if anything goes wrong.
3. **Ping it.** This sends one message and writes nothing:

   ```bash
   a2 ping --console 192.0.2.16
   ```

   ```
   Console: WING,192.0.2.16,FOH,wing-compact,SN12345,3.1-0
   Detected model: WING Compact (wing-compact)
   ```

   Keep both lines in case you [report a problem](reporting.md); blank
   out the serial number if you like. (`a2` is the short spelling of
   `atoo`; use whichever you prefer.)

   If nothing answers, you'll see:

   ```
   no reply from 192.0.2.16:2223 -- is the console reachable, and is its OSC remote enabled?
   ```

   [Troubleshooting: the desk](troubleshooting-desk.md) covers what to
   check.

To avoid typing the IP address every time, save it once: see [Configuring
Atoo](configuration.md#the-console).

## 2. Read-only on your desk

Neither of these exercises writes anything to the desk.

1. **Audit the desk.**

   It reads the whole desk and checks it against
   the built-in rules, such as 48V on a socket nothing is patched to, a
   DCA at the floor with live channels in it, or two strips with the
   same name. `--dump-state` saves what it read to a file:

   ```bash
   atoo audit --console 192.0.2.16 --dump-state my-desk.state.json
   ```

   Check each finding against the desk.

2. **Watch it for a few minutes.**

   Run `atoo watch` from the command line. This command takes three readings:

   ```bash
   atoo watch --console 192.0.2.16 --count 3
   ```

Every rule that `watch` can report is in the [Rules reference](rules-reference.md).

## 3. Write a show plan, then undo

**Only on a desk that is not running a show.** A full apply takes over
the whole desk: it resets it, unpatches what the plan doesn't use, then
writes the plan. Your network, clock, cards and monitor listening are
left alone (See: [what a full apply changes](what-apply-changes.md)).

1. **Make sure you have saved the desk's show** ([step
   1](#1-before-you-start)).

2. **Make your own copy of the Demo show.** The one built into Atoo
   can't be changed.

   ```bash
   atoo init --demo
   ```

   The copy goes in your Atoo folder as `~/Documents/Atoo/demo-show`.

3. **Check it against your desk's model.** This contacts nothing. Use
   `wing-full`, `wing-compact` or `wing-rack`:

   ```bash
   atoo verify --show ~/Documents/Atoo/demo-show --console-model wing-full
   ```

   ```
   0 error(s), 0 warning(s), 4 note(s)
     ...
   ```

   It should end with `APPLICABLE: notes only`.

4. **Preview the write.** This reads the desk and lists what the plan will write:

   ```bash
   atoo apply --show ~/Documents/Atoo/demo-show --console 192.0.2.16
   ```

   If no errors, continue on to actually apply the show to the desk.

5. **Write it.** The `--confirm` option allows the write and read back:

   ```bash
   atoo apply --show ~/Documents/Atoo/demo-show --console 192.0.2.16 --confirm
   ```

   Every value is read back afterwards. Look at the line that starts
   `APPLIED:` and note any `MISMATCH` lines under it.

6. **Look at the desk.** Do the names, colours, patch, sends and DCAs
   match the [Demo show](demo.md)?

7. **Undo the write.** Preview it first, then add `--confirm`:

   ```bash
   atoo undo --show ~/Documents/Atoo/demo-show --console 192.0.2.16
   atoo undo --show ~/Documents/Atoo/demo-show --console 192.0.2.16 --confirm
   ```

8. **Load your saved show** back onto the desk.

## Next

Set up your desk, conventions and presets once in [Configuring
Atoo](configuration.md), then [set up an AI provider](ai-provider.md) so you can build your own shows.

## See also

- [Apply a plan to the desk](apply-to-desk.md) and [Undo](undo.md): the write and its undo, in full
- [Troubleshooting: the desk](troubleshooting-desk.md)
