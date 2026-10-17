# Troubleshooting

Find the symptom, then go to its page.

| Symptom | Page |
|---|---|
| `atoo` cannot reach the console | [below](#atoo-cannot-reach-the-console) |
| A command exited non-zero and I cannot tell why | [below](#a-command-exited-non-zero-and-i-cannot-tell-why) |
| `atoo: command not found` | [below](#atoo-command-not-found) |
| `build` says "generation failed" | [build](troubleshooting-build.md#build-says-generation-failed) |
| A build seems stuck, or you want to stop it | [build](troubleshooting-build.md#a-build-seems-stuck) |
| `build` says the reply "hit max_tokens and is truncated" | [build](troubleshooting-build.md#build-says-the-reply-hit-max_tokens-and-is-truncated) |
| `verify` says `BLOCKED: do not apply.` | [verify](troubleshooting-verify.md#verify-says-blocked-do-not-apply) |
| `verify` says two objects are on the same physical output | [verify](troubleshooting-verify.md#verify-says-two-objects-are-on-the-same-physical-output) |
| A plan names a preset that cannot be found | [verify](troubleshooting-verify.md#a-plan-names-a-preset-that-cannot-be-found) |
| `apply` or `undo` looks like it has hung | [desk](troubleshooting-desk.md#apply-or-undo-looks-like-it-has-hung) |
| A desk read is slow | [desk](troubleshooting-desk.md#a-desk-read-is-slow) |
| `apply` says a value did not land, but the desk shows it | [desk](troubleshooting-desk.md#apply-says-a-value-did-not-land-but-the-desk-shows-it) |
| `apply` says the console has nothing in a bay | [desk](troubleshooting-desk.md#apply-says-the-console-has-nothing-in-a-bay) |
| `apply` says a socket does not exist on this desk | [desk](troubleshooting-desk.md#apply-says-a-socket-does-not-exist-on-this-desk) |
| `amend` says a socket does not exist on this desk | [desk](troubleshooting-desk.md#amend-says-a-socket-does-not-exist-on-this-desk) |
| `apply` warns that the desk's model has never been measured | [desk](troubleshooting-desk.md#apply-warns-that-the-desks-model-has-never-been-measured) |
| `undo` says "nothing more to undo on this desk" | [desk](troubleshooting-desk.md#undo-says-nothing-more-to-undo-on-this-desk) |
| `audit` or `watch` says `C003` | [audit](troubleshooting-audit.md#audit-or-watch-says-c003) |
| A channel is silent but its patch is right: `C004` | [audit](troubleshooting-audit.md#a-channel-is-silent-but-its-patch-is-right-c004) |
| A channel is on, named and up, but you hear nothing: `R008` | [audit](troubleshooting-audit.md#a-channel-is-on-named-and-up-but-you-hear-nothing-r008) |
| A channel feeds itself and howls, or could: `R009`, `R010` | [audit](troubleshooting-audit.md#a-channel-feeds-itself-and-howls-or-could-r009-r010) |
| A channel is on and named, but nothing is patched to it: `C006` | [audit](troubleshooting-audit.md#a-channel-is-on-and-named-but-nothing-is-patched-to-it-c006) |
| A channel is silent and nothing on it is muted: `C007` | [audit](troubleshooting-audit.md#a-channel-is-silent-and-nothing-on-it-is-muted-c007) |
| A stage box is on the patch but no audio comes from it: `C008`, `C009` | [audit](troubleshooting-audit.md#a-stage-box-is-on-the-patch-but-no-audio-comes-from-it-c008-c009) |
| A whole group of channels is silent and every one is up: `CH004` | [audit](troubleshooting-audit.md#a-whole-group-of-channels-is-silent-and-every-one-is-up-ch004) |
| A bus is heard on one side only, or is not the width the plan says: `R011`, `CV020` | [audit](troubleshooting-audit.md#a-bus-is-heard-on-one-side-only-or-is-not-the-width-the-plan-says-r011-cv020) |
| Trim, gain, a high-pass, hi-cut, tilt or EQ is not what the plan says: `CV008` | [audit](troubleshooting-audit.md#trim-gain-a-high-pass-hi-cut-tilt-or-eq-is-not-what-the-plan-says-cv008) |
| An effect is on the strip but you cannot hear it: `E001`, `E002` | [audit](troubleshooting-audit.md#an-effect-is-on-the-strip-but-you-cannot-hear-it-e001-e002) |
| The band cannot hear talkback: `T001` | [audit](troubleshooting-audit.md#the-band-cannot-hear-talkback-t001) |
| One monitor mix cannot hear talkback: `CV021`, `CV022` | [audit](troubleshooting-audit.md#talkback-that-misses-one-monitor-mix-cv021-cv022) |
| Talkback and a band input on one strip: `CV014` | [audit](troubleshooting-audit.md#talkback-and-a-band-input-on-one-strip-cv014) |
| `audit` or `watch` says rules "could not be checked" | [audit](troubleshooting-audit.md#audit-or-watch-says-rules-could-not-be-checked) |
| `audit` says "No findings" on a console that is visibly wrong | [audit](troubleshooting-audit.md#audit-says-no-findings-on-a-console-that-is-visibly-wrong) |
| `audit` or `watch` reports a duplicate name that is not on the desk | [audit](troubleshooting-audit.md#audit-or-watch-reports-a-duplicate-name-that-is-not-on-the-desk) |
| `audit` or `watch` looks like it has hung | [audit](troubleshooting-audit.md#audit-or-watch-looks-like-it-has-hung) |
| `atoo ui` exits immediately | [ui](troubleshooting-ui.md#it-exits-immediately) |
| The browser page loads but shows nothing | [ui](troubleshooting-ui.md#the-page-loads-but-shows-nothing) |
| In the browser, Build step 04 says Failed | [ui](troubleshooting-ui.md#build-step-04-says-failed) |
| The browser page says it is out of date | [ui](troubleshooting-ui.md#the-page-says-it-is-out-of-date) |
| In the browser, **Write to console** or **Undo newest write** stays locked | [ui](troubleshooting-ui.md#write-to-console-or-undo-newest-write-stays-locked) |
| Another computer can open the browser page, but only to watch | [ui](troubleshooting-ui.md#another-computer-can-open-the-page-but-only-to-watch) |

## `atoo` cannot reach the console

**Start with `atoo ping`.** Every command that talks to a desk opens
the same way, so if `ping` cannot reach it, nothing else will either --
and `ping` tells you that in one round trip instead of after a full
console read:

```
$ atoo ping --console 192.0.2.16
Console: WING,192.0.2.16,FOH,wing-compact,SN12345,3.1-0
Detected model: WING Compact (wing-compact)
```

That is a healthy desk. It reads nothing and writes nothing, so it is
safe to run during a show.

There are two ways it fails, and they have different causes.

**`no reply from 192.0.2.16:2223 -- is the console reachable, and is its
OSC remote enabled?`**

The packets went out and nothing came back. In order of likelihood:

1. **OSC remote control is switched off on the desk.** This is the usual
   one. It is a setting on the console, not on your laptop, and a console
   that is otherwise working normally will sit there silently with it off.
2. **Wrong IP.** The desk states its own address on its network screen.
3. **Something is dropping UDP on port 2223** -- a firewall on your
   laptop, or a network that isolates clients from each other. WING's OSC
   is UDP, so nothing "refuses" the connection; it just vanishes.
4. **A non-default port.** Pass `--port` if the desk was moved off 2223.

**`couldn't reach 192.0.2.16:2223 -- OSError: [Errno 65] No route to
host`**

The network refused to carry the packets at all, which is a different and
usually simpler problem: wrong subnet, wrong address entirely, or the
cable/Wi-Fi is not on the console's network. The message after the dash
comes from the operating system -- `No route to host`, `Connection
refused` and `Network is unreachable` each mean what they say.

**If `ping` succeeds but another command fails**, the problem is not
connectivity, and the rest of this page is where to look.

## A command exited non-zero and I cannot tell why

**The codes are not uniform across commands**, so start from the
[exit-code table in the command reference](cli-reference.md#exit-codes),
which is the canonical statement. The three cases that surprise people:

**`audit` or `watch` exited `1`.** That is not a failure to run; for
those two commands it is *the finding report*. They exit `1` when a rule
or a watch condition reaches error severity, where `build`,
`verify`, `compare` and `apply` use `2` for "ran and found problems".
Read what the command printed — this is a desk with something wrong on
it, not a broken invocation. The split is deliberate: those
two hold no plan, they are read-only readings of a desk, so reporting
something is their ordinary result.

**`audit` or `watch` exited `1` and printed nothing useful.** Then it is
the *other* meaning of `1`: it never started. Check stdout — a run that
could not start writes nothing there and puts its reason on stderr
(`couldn't read state file 'x.json': No such file or directory`), where a
run that found errors writes its findings to stdout. In a cron job that
merges the two streams, look for the `Audit findings:` line: no such
line, no audit happened.

**Something exited `2` and you expected `1`.** `2` is also argparse's own
code for a command line it will not accept — an unknown flag, a value it
cannot parse, a missing required option — and for "no console address"
on `ping`, `apply`, `audit` and `watch`, which kept argparse's code on
purpose.
A `2` with a `usage:` line on stderr is a typo in the command, not a
finding.

**Something exited `1` after `| head`, or after you quit `less`.** The
reader stopped before the output did, so the command stopped too,
quietly. Nothing went wrong but the cut.

## `atoo: command not found`

That is an install problem: see
[When it does not work](install.md#when-it-does-not-work).

## See also

- [Installing Atoo](install.md) — including `command not found` and the extras
- [Command reference](cli-reference.md#exit-codes) — the canonical exit-code table
