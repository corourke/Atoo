# Security

## The desk's network is the security boundary

Atoo talks to a WING over OSC, on UDP port 2223. **The WING's OSC
has no password and no encryption.** Anything that can send a packet to
the desk can change any setting on it, and read every one: Atoo,
WING Edit, a phone app, or anyone else's laptop on that network. That
is how the desk works, not something Atoo adds or can fix.

So keep the desk on a network you control:

- **Its own network, or a crew-only one.** Not the venue's guest Wi-Fi,
  and not a network the audience or other acts can join.
- **A password on the wireless access point** that tablets and phones
  use to mix, given to the crew only.
- **Never reachable from the internet.** No port forwarding to the desk,
  and no remote-access tunnel left open after a show.

Atoo itself:

- **Writes only when you arm it.** `apply`, `patch`, `amend` and `undo`
  preview by default and write only with `--confirm`, or the browser's
  arming checkbox; every write is journalled and can be undone.
- **`atoo ui` answers only this laptop** unless you start it with
  `--host`. With `--host`, another machine on that network can open
  the page and watch, with no login. Building, applying, saving and
  browsing files still answer only the laptop it runs on.
- **Keeps your model's API key out of files.** The key is read from an
  environment variable, never from `~/.atoo.config` or a show's
  folder, so a shared show cannot carry it.

## Reporting a problem

If you find a way Atoo could write to a desk it was not asked to,
expose files or a key, or let another machine do more than watch,
please report it privately: on the repository's **Security** tab,
choose **Report a vulnerability**. Please do not open a public issue
for it.

We aim to reply within a week. Fixes go into the next release, and the
release notes credit you, if you want that.

Problems with the WING's own OSC, such as its lack of authentication,
are Behringer's to fix, and are not vulnerabilities in Atoo.

## Supported versions

The latest release. Atoo is pre-1.0, and fixes are not backported.
