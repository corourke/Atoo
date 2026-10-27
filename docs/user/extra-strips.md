# Channels that are not on the input list

The input list is what the band brings. Some channels are yours: a talkback mic, an ambient pair, a click from your own laptop. Nobody puts those on a band's list, so you ask for them in words: in a show's `instructions.md` for one show, or in your house conventions for every show. Either way, **say which socket it comes in on**.

```
## Inputs
Talkback on channel 40, source LCL 12.
```

The build makes that channel, patched from the socket you named (`LCL 12`, `AES50-A 40`, or `A 40`: a bare `A`/`B`/`C` in a sentence is read as that AES50 network). Whatever the sentence does not say is decided and said at INFO (`reply.from-instructions`). If the sentence names one channel (`channel 40`, `ch 40`), the strip goes on that channel, and the other strips are numbered around it. The source is a mic unless the sentence says DI or wireless. Phantom is off unless it says phantom or 48V. The colour is a category the sentence or the name points at, else a talkback category or `misc`, if your conventions colour one.

`verify` reports every such channel, quoting you, so the one strip your list does not have is never a surprise. Asked for like this, in so many words and with its socket, it is a **note**: your own decision, said back to you. It is a **warning** instead when the quote could not be checked against your text, was found only in the [resolved conventions](conventions-reference.md#the-resolved-conventions) (the model's restatement, not your words), is a fragment shorter than four words, states its socket only elsewhere in the line, or the strip was built unpatched (*"if available"*, below):

```bash
atoo verify --show clubdate
```

```
0 error(s), 0 warning(s), 1 note(s)

  [info] channels[Talkback]: ch 40 'Talkback' is not on the input list; built because instructions.md says 'Talkback on channel 40, source LCL 12', on LCL 12 as it states  (reconcile.from-instructions)

APPLICABLE: notes only -- choices made where the conventions were silent.
```

What is still refused:

- **No socket.** "Add a talkback mic" says what, not where. There is nowhere to patch it, so the build stops and asks you to state one.
- **A quote you never wrote.** The build checks the sentence it was built from is really in your conventions or instructions, and so does `verify`, each time. Change the line to `Talkback on channel 40.` and the same plan is refused:

  ```
  1 error(s), 0 warning(s)

    [error] channels[Talkback]: ch 40 'Talkback' is not on the input list, and the instructions it quotes ('Talkback on channel 40, source LCL 12') do not say that -- the plan invented an input that nobody is going to plug in  (reconcile.invented-source)

  BLOCKED: do not apply.
  ```

- **A channel nobody asked for.** One that is on neither the list nor in your words is an invention, as before.

**How the quote is matched.** The quote need not be your whole line, but what it does quote must appear in your text word for word (case and spacing aside), and be at least four words long unless it is a whole line. A fragment like *"source LCL 12"* could come from any sentence, so the build refuses it.

## Strips your conventions ask for

A strip you want at **every** show, written in your house conventions, is built by code rather than by the model, so it is never forgotten. Write the strip, its socket and anything else you want, in one sentence:

```
## Aux strips
- Setup a MUSIC playback on Aux 1, source LCL 23-24.
- Setup TALKBACK on Aux 8, source LCL 22 if available.
```

Code checks each sentence is really in your conventions, as it checks every other quote, and lists the strips in the [resolved conventions](conventions-reference.md#the-resolved-conventions). Every build then makes those strips itself, on the strip and from the socket you named, with the preset you named. Their sockets and strip numbers are held first, so no other channel lands on them. A build lists them up front:

```
INFO instructed strips: 2 in club.resolved.md -- code builds MUSIC (aux 1), TALKBACK (aux 8)
```

What it decided that you did not say is a note: MUSIC is stereo because it takes two sockets, and is taken as a line source. `verify` reports each one, as any strip that is not on your input list: a note when it went on the socket your sentence names, a warning when it did not.

**"If available".** On this show the input list puts Lead Vox on `LCL 22`, which TALKBACK asked for only if it was free. So TALKBACK is built, **unpatched**, and `verify` says why:

```bash
atoo verify --plan plan.json --input input.csv
```

```
0 error(s), 1 warning(s), 2 note(s)

  [warning] channels[TALKBACK]: aux 8 'TALKBACK' is not on the input list; built because club.md says 'Setup TALKBACK on Aux 8, source LCL 22 if available'. Left unpatched (if available): LCL 22 is taken by input list row 'Lead Vox'  (reconcile.from-instructions)

  [info] channels[MUSIC]: linked as a stereo pair -- no convention states it; decided by Atoo's fallback rule: two sockets (LCL 23-24) make one stereo strip  (inferred.channel-stereo)
  [info] channels[MUSIC]: aux 1 'MUSIC' is not on the input list; built because club.md says 'Setup a MUSIC playback on Aux 1, source LCL 23-24', on LCL 23-24 as it states  (reconcile.from-instructions)

APPLICABLE: warnings only.
```

(TALKBACK reaches nothing because these conventions never say where it goes; say "send it to the monitor busses" and it will.) `apply` leaves an unpatched strip's input OFF. Without "if available" the same clash is two sources on one socket, which cannot work, so the plan is refused. With Lead Vox on `LCL 23` instead, MUSIC is built on `LCL 23-24` as asked, and:

```
  [error] channels[MUSIC].patch: aux 1 'MUSIC' is built because club.md says 'Setup a MUSIC playback on Aux 1, source LCL 23-24', on LCL 23 -- which is taken by input list row 'Lead Vox'. Two sources cannot come from one socket  (reconcile.instructed-conflict)
```

An input-list row with the strip's name **is** that strip: a show whose list has a `HOST` row gets that row on the strip and socket your conventions give HOST, not a second HOST. Strips a show's own `instructions.md` asks for are not in the resolved file, which is made from your house conventions alone; the model builds those, as described above. So does a build with `--no-resolve`.

## See also

- [Writing conventions](conventions.md)
- [Writing an input list](input-lists.md)
- [Reading findings](reading-findings.md)

