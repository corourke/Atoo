# Watch conditions: your own alerts

The built-in rules know what a WING should look like; they do not know
your show. A watch condition is a line you write about *this* rig — the
Kick stays on LCL 5, the PA is never muted, the Band DCA stays up — and
Watch checks it on every pass. Conditions are deterministic structured
JSON, not prose and not a model: the runtime path has no AI in it at
all. This page is the file format, used both by **Watch** in the browser
and by `atoo watch`.

Every transcript on this page runs against a captured state file, with
no console attached. [`atoo init`](install.md#3-first-run-atoo-init-then-atoo-ui) copies
the captures into your Atoo folder, as `audit-demo/` (run it again if
yours was made before they existed; it adds what is missing and touches
nothing you have changed):

```bash
cd ~/Documents/Atoo/audit-demo
```

```json
{
  "watch_conditions": [
    {
      "id": "kick-on-lcl5",
      "description": "Kick must stay patched to LCL 5",
      "channel": "Kick",
      "field": "patch",
      "operator": "==",
      "value": "LCL 5",
      "severity": "error"
    }
  ]
}
```

```bash
atoo watch --state-sequence audit_demo_state.json --watch-conditions one.watch.json --count 1
```

The fixture's Kick is on LCL 1, so the condition is violated and fires at
the severity the file itself asked for:

```
[2026-09-22T06:09:37+00:00] baseline -- 12 finding(s) already present:
Audit findings: 1 error, 7 warning, 4 info.

[ERROR] WATCH:kick-on-lcl5 Kick must stay patched to LCL 5
  CH 1 "Kick" is patched to LCL 1 -- Kick must stay patched to LCL 5.

... the 11 structural findings
```

It is reported alongside the built-in rules, not instead of them: 11
structural findings plus your one, sorted by severity, so your condition
leads.

**The line says which strip, what it is, and your description** —
`CH 1 "Kick" is patched to LCL 1 -- Kick must stay patched to LCL 5.` —
and nothing else: not the condition's id, operator or value. So write the description as the rule you want kept, in your
own words; it is the half of the sentence that says what should be true.

**A condition you wrote correctly about a rig that is set up correctly
produces nothing at all.** That silence is the feature, and it is why
these are worth writing for the handful of things that would ruin a show
rather than for everything you can think of.

**In Watch, each condition has a small *i* beside its ID** that says the
condition in plain English, for example *"Alerts as a warning when any DCA
from 1 to 5 is muted."* A condition states what should be true, and the
sentence says when the alert fires, so it reads the other way round.
It is made from the condition's cells (never from its description), covers
every field, operator, range, name and bus, and says how the alert names
the strip. A condition the file format would refuse has no sentence.
[Watch a show](watch-a-show.md#3-say-what-matters-tonight-watch-conditions)
shows where it is.

## The field vocabulary

| field | value | operators |
|---|---|---|
| `fader_db` | a number | `==` `!=` `<` `<=` `>` `>=` |
| `muted` | `true` / `false` | `==` `!=` |
| `dca` | a DCA **name**, e.g. `"Drums"` | `==` `!=` |
| `mute_group` | a mute-group **name** | `==` `!=` |
| `patch` | a socket, e.g. `"LCL 3"` | `==` `!=` |
| `send_on` | `true` / `false`, with a `bus` | `==` `!=` |
| `send_db` | a number, with a `bus` | `==` `!=` `<` `<=` `>` `>=` |
| `send_mode` | `"pre"`, `"post"` or `"group"`, with a `bus` | `==` `!=` |
| `phantom` | `true` / `false` | `==` `!=` |

The last four are [sends and 48V](#sends-and-48v). Only the two levels,
`fader_db` and `send_db`, have an ordering worth comparing, so only they
take `<` and friends. The rest ask a yes/no question: **`==` asserts it holds,
`!=` asserts it does not.** `"field": "dca", "operator": "!=", "value":
"Drums"` fires when the channel *is* in the Drums DCA.

`severity` is one of `info`, `warning` or `error`, and it is yours to
set — the condition fires at whatever level you said it mattered.

Four rules about names:

- **`channel` is matched by name, case-insensitively**, across the
  channels and auxes. A name that matches no live channel, or two, is
  skipped for that pass rather than guessed at. A strip can also be named
  by its position, or by its kind and its name (`BUS Drums`) -- see the
  next two sections.
- **Groups are matched by name, never by index**, the same way. A
  condition about a DCA called `FX` on a rig whose only `FX` is a *bus*
  says nothing, rather than claiming a violation it could not check.
- **The names matched are the last ones read.** A live watch reads names
  at Start and every fifth pass (see
  [Names are read at Start and refreshed](watch.md#names-are-read-at-start-and-refreshed)),
  so a channel renamed mid-show is matched under its new name from the
  next refresh.
- **A socket is written exactly the way an input list's `patch` column
  writes it** — `AES50-A 12`, `LCL 3`, `AES 1`, `CRD 64`. One vocabulary,
  not a second one invented for this field. `AES 1` (AES/EBU) and
  `AES50-A 1` are different sockets, which is why the network letter is
  spelled out.

**A condition that could never fire is refused when the file loads**,
rather than sitting quietly in your show file being silently useless.
Ask for a socket a WING Compact does not have and you are told so, with
every group and its range, before a single read happens:

```
bad.watch.json: watch_conditions[0] ('kick-on-lcl99'): field 'patch' value 'LCL 99' is not a socket this console could have -- write it the way an input list's patch column does, e.g. "AES50-A 12", "LCL 3", "AES 1", "SC 24"; known groups: AES50-A 1..48, AES 1..2, AUX 1..8, AES50-B 1..48, AES50-C 1..48, CRD 1..64, LCL 1..24, MOD 1..64, OSC 1..2, PLAY 1..4, SC 1..32, USB 1..48, USR 1..56
```

Same for an operator the field cannot support:

```
bad-op.watch.json: watch_conditions[0] ('kick-dca-gt'): field 'dca' asks a yes/no question and only supports ['!=', '=='] ('==' asserts it holds, '!=' asserts it does not), not '>'
```

Both exit `1` without reading anything.

## By position, range or kind

`channel` can name a strip by where it is on
the desk rather than by what it is called -- which is the only way to
reach a strip nobody has named, and the only way to reach a bus, a DCA, a
Main or a Matrix at all:

| You write | It means |
|---|---|
| `CH 10` (or `CHN 10`, `CHAN 10`) | channel 10 |
| `AUX 3`, `BUS 3`, `MAIN 1`, `DCA 14` | that aux, bus, Main or DCA |
| `MTX 3` (or `MATRIX 3`) | matrix 3 |
| `DCA 10-16` | DCAs 10 to 16, both ends included |
| `ALL AUX`, `ALL MAIN`, ... | every strip of that kind the console has |

Case does not matter and the space is optional: `ch10`, `Ch 10` and
`CH 10` are the same target, and the Watch editor and Save write it back
as `CH 10`. `DCA 10-16` and `ALL AUX` are written that way too.

A range or `ALL` condition is checked on **each strip it covers**, and
each strip that breaks it is its own finding, citing the strip's
position and its name when it has one. Saved as `positions.watch.json`:

```json
{
  "watch_conditions": [
    {
      "id": "busses-trimmed",
      "description": "Every bus stays at or below -5 dB",
      "channel": "ALL BUS",
      "field": "fader_db",
      "operator": "<=",
      "value": -5,
      "severity": "warning"
    },
    {
      "id": "drum-dca-up",
      "description": "The drum DCAs are never pulled right down",
      "channel": "DCA 1-4",
      "field": "fader_db",
      "operator": ">",
      "value": -60,
      "severity": "error"
    }
  ]
}
```

```bash
atoo watch --state-sequence audit_demo_state.json --watch-conditions positions.watch.json --count 1
```

The fixture has three busses at 0 dB and one DCA at the floor, so the
baseline has four findings of yours among the structural ones. The three
busses break the same condition in the same way, so they are one entry,
with the count in brackets:

```
[ERROR] WATCH:drum-dca-up The drum DCAs are never pulled right down
  DCA 1 "Drums" has its fader at -144 dB -- The drum DCAs are never pulled right down.

[WARNING] WATCH:busses-trimmed Every bus stays at or below -5 dB (3)
  BUS 1 "Drums", BUS 2 "Monitor 1", BUS 3 "FX"
  Each has its fader at 0 dB -- Every bus stays at or below -5 dB.
```

DCAs 2 to 4 are not in the fixture at all, so they say nothing: a strip
that was never read is skipped, as an unmatched name is. A Main's and a
Matrix's name is not read, so a finding about one reads `MAIN 1`.

Things to know:

- **A position always wins.** Text that reads as a position, range or
  `ALL` form *is* that form, even if some channel happens to be named
  `CH 10`. When one is, each pass also reports an `info` finding saying
  the condition is watching the position, not that channel. A kind word
  followed by a name is a [kind and a name](#by-kind-and-name), and
  anything else is a name, as before.
- **Which fields a kind takes.** Every field works on a channel or an
  aux. A bus, Main, Matrix or DCA takes `muted` and `fader_db` only:
  only channels and auxes have an input `patch`; a DCA cannot be in a DCA
  or a mute group; and a bus, Main or Matrix can be, but `watch` does not
  read their tags, so the condition could never fire.
- **`Main` on its own means `MAIN 1`**, the main L/R. An `info` finding
  says so: *'Main' read as MAIN 1 (the main L/R) -- write MAIN 1 to make
  it explicit*. The Watch screen's table rewrites the cell to `MAIN 1` and
  shows the same note under it, not in red. No other kind has a
  default, so `BUS`, `AUX`, `CH`, `DCA` and `MTX` on their own are
  refused.
- **What is refused when the file loads** -- each is a condition no
  console could satisfy: a malformed target (`CH`, `BUS -`, `DCA 3-`), a
  position the WING does not have (`CH 41`, `MAIN 5`, `DCA 17`), a
  backwards range (`DCA 16-10`), and a field the kind does not have.

```
bad-target.watch.json: watch_conditions[0] ('spare-muted'): 'channel' 'CH 41': CH 41 does not exist -- a WING has CH 1-40
```

```
bad-field.watch.json: watch_conditions[0] ('dca-patched'): field 'patch' does not apply to DCA 1: a DCA has no input patch -- DCA conditions take 'muted' or 'fader_db'
```

The Watch screen's conditions table checks each row against the same
rules as you type: a cell it would refuse is outlined in red with the
reason under it, and Save refuses until it is fixed.

Nothing here costs an extra console read: every bus, Main, Matrix and
DCA's mute and fader were already part of each pass, and every bus and
DCA's name part of each name refresh.

## By kind and name

A kind word followed by a name
means **the one strip of that kind with that name**. It reaches a bus,
DCA, Main or Matrix by name, which a name alone never does:

| You write | It means |
|---|---|
| `BUS Drums` | the bus named Drums |
| `DCA Vocals` | the DCA named Vocals |
| `AUX Tracks` | the aux named Tracks |
| `CH Kick` | the channel named Kick |
| `MAIN PA`, `MTX Delay` | the Main named PA, the Matrix named Delay |

The kind words are the ones positions use (`CH`/`CHN`/`CHAN`, `AUX`,
`BUS`, `MAIN`, `MTX`/`MATRIX`, `DCA`). The kind word is written back in
capitals (`bus drums` is saved as `BUS drums`). The name keeps your
spelling and matches regardless of case.

**The name is looked up once, when Watch starts.** Its position is what
gets watched after that. Every pass checks `BUS 1`, not "whichever bus
is called Drums now", so watching by name adds no reads to each pass.
The baseline says what each name matched, as an `info` finding. If
someone renames or moves the strip after Start, Watch carries on
watching the position it found; stop and start Watch to look the name up
again.

A Main's and a Matrix's names are not part of a normal pass, so a
`MAIN` or `MTX` name makes Watch read those names once, at Start, and
never again. A capture played with `--state-sequence` has none of them,
so there a `MAIN` or `MTX` name gets a warning that no name could be read.

Saved as `scoped.watch.json`:

```json
{
  "watch_conditions": [
    {
      "id": "drum-bus-trimmed",
      "description": "The drum bus stays at or below -5 dB",
      "channel": "BUS Drums",
      "field": "fader_db",
      "operator": "<=",
      "value": -5,
      "severity": "warning"
    },
    {
      "id": "drum-dca-up",
      "description": "The drum DCA is never pulled right down",
      "channel": "DCA Drums",
      "field": "fader_db",
      "operator": ">",
      "value": -60,
      "severity": "error"
    },
    {
      "id": "horns-unmuted",
      "description": "The horn bus is never muted",
      "channel": "BUS Horns",
      "field": "muted",
      "operator": "==",
      "value": false,
      "severity": "error"
    }
  ]
}
```

```bash
atoo watch --state-sequence audit_demo_state.json --watch-conditions scoped.watch.json --count 1
```

The fixture has a bus *and* a DCA named Drums, so each condition looks
only at strips of its own kind. It has no bus named Horns. Among the
structural findings, the baseline has these lines of yours:

```
[ERROR] WATCH:drum-dca-up The drum DCA is never pulled right down
  DCA 1 "Drums" has its fader at -144 dB -- The drum DCA is never pulled right down.

[WARNING] WATCH:drum-bus-trimmed The drum bus stays at or below -5 dB
  BUS 1 "Drums" has its fader at 0 dB -- The drum bus stays at or below -5 dB.

[WARNING] WATCH:horns-unmuted The horn bus is never muted
  BUS Horns matches no BUS at Start -- none is named 'Horns' -- so the condition 'horns-unmuted' is not watched. It is tried again the next time Watch starts.

[INFO] WATCH:drum-bus-trimmed The drum bus stays at or below -5 dB
  BUS Drums resolved to BUS 1 at Start; a rename or move after Start is not followed until Watch restarts.

[INFO] WATCH:drum-dca-up The drum DCA is never pulled right down
  DCA Drums resolved to DCA 1 at Start; a rename or move after Start is not followed until Watch restarts.
```

Things to know:

- **On the Watch screen these lines are not table rows.** The INFO
  resolutions and the not-watched warnings go on the **This watch** line
  under the table (*Resolved at Start: BUS Drums → BUS 1, DCA Drums → DCA
  1*); the table keeps what is wrong on the desk.
- **A name that matches two strips of its kind is not watched.** It gets
  a warning naming every position it matched. Write the position you
  mean instead.
- **The kind and name wins over a channel named the same.** If a channel
  is literally called `BUS Drums`, the condition still watches the bus
  named Drums, and an `info` finding says so. To watch that channel,
  write `CH BUS Drums` or its position.
- **A channel whose name begins with a kind word** -- "Main Vox" -- is
  written `CH Main Vox`. Plain `Main Vox` means the Main named Vox.
- **A digit after the kind word is a position**, so `BUS 2 Track` is
  refused rather than read as a bus named "2 Track":

  ```
  bad-scoped.watch.json: watch_conditions[0] ('track-bus-up'): 'channel' 'BUS 2 Track' begins like a position but is not a well-formed one (a name after a kind word cannot begin with a number) -- to watch that strip, write its position, BUS 2
  ```

- **Fields follow the kind**, as for positions: `patch` on `DCA Vocals`
  is refused.

## Sends and 48V

Some rules are about one show's sends and its 48V, which the built-in rules
cannot know: *the click stays on in every in-ear mix*, *Kick stays at or
below -6 dB in the drummer's mix*, *48V stays on for the overheads*. Four
fields say them.

| field | value | operators | about |
|---|---|---|---|
| `send_on` | `true` / `false` | `==` `!=` | the strip's send to the bus is switched on |
| `send_db` | a number, in dB | `==` `!=` `<` `<=` `>` `>=` | the level of that send |
| `send_mode` | `"pre"`, `"post"` or `"group"` | `==` `!=` | whether that send is pre- or post-fader |
| `phantom` | `true` / `false` | `==` `!=` | 48V on the socket the strip is patched to |

The three `send_` fields need one more key, **`bus`**: where the send goes.
It is written the way `channel` is.

| You write | It means |
|---|---|
| `Drums`, `BUS Drums` | the bus named Drums |
| `BUS 5` | bus 5 |
| `BUS 5-8`, `ALL BUS` | each of those busses |
| `MTX 3` | a send to Matrix 3 |
| `MAIN 1` | the strip's route to Main 1 (a route has a switch and nothing else, so only `send_on` takes it) |

A bus is matched by name against the names last read, case-insensitively,
so a rename is picked up at the next refresh; a name that matches no bus,
or two, says nothing that pass. A Main's and a Matrix's names are not read,
so those are written by position. Only a channel or an aux has sends of
this kind, and `bus` goes on the three `send_` fields and nowhere else. The
loader refuses a missing `bus` or one on another field, a bus that does not
exist, and a field the bus's kind cannot take, before Watch reads anything.

Saved as `sends.watch.json`:

```json
{
  "watch_conditions": [
    {
      "id": "drums-mix-has-kick-and-snare",
      "description": "Kick and Snare stay in the Drums mix",
      "channel": "CH 1-2",
      "field": "send_on",
      "bus": "BUS Drums",
      "operator": "==",
      "value": true,
      "severity": "error"
    },
    {
      "id": "kick-level-in-drums",
      "description": "Kick stays at or below -6 dB in the Drums mix",
      "channel": "Kick",
      "field": "send_db",
      "bus": "BUS Drums",
      "operator": "<=",
      "value": -6,
      "severity": "warning"
    },
    {
      "id": "playback-out-of-drums",
      "description": "Playback stays out of the Drums mix",
      "channel": "Playback",
      "field": "send_on",
      "bus": "Drums",
      "operator": "==",
      "value": false,
      "severity": "error"
    }
  ]
}
```

```bash
atoo watch --state-sequence audit_demo_state.json --watch-conditions sends.watch.json --count 1
```

Among the structural findings, the baseline has two lines of yours. Kick and
Snare both have their send to Drums on, so the first condition says nothing:

```
[ERROR] WATCH:playback-out-of-drums Playback stays out of the Drums mix
  CH 7 "Playback" has its send to BUS 1 "Drums" switched on -- Playback stays out of the Drums mix.

...
[WARNING] WATCH:kick-level-in-drums Kick stays at or below -6 dB in the Drums mix
  CH 1 "Kick" has its send to BUS 1 "Drums" at 0 dB -- Kick stays at or below -6 dB in the Drums mix.
```

**One finding per strip that breaks it.** A range on `channel` gives each
strip its own finding, and a range on `bus` lists the busses that break the
condition inside one finding (*has its sends to BUS 5 "IEM 1" and BUS 6 "IEM
2" switched off*). A send that was not read is skipped, so a strip with some
of its sends unread is judged on the rest. `send_db` compares the level
whether or not the send is switched on, so *stays on* and *stays above -10*
are two conditions.

**`phantom` is the 48V on the socket the strip is patched to** and, for a
stereo source, the socket after it: each must satisfy the condition, and the
finding names the one that does not. It has nothing to say for a strip that
is not patched, one patched from a card, USB or another group with no
48V, one on its alternate input, or one whose 48V was not read. Save this
small capture as `condenser.state.json`:

```json
{
  "/ch/1/name": "OH L", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
  "/ch/2/name": "OH R", "/ch/2/in/conn/grp": "LCL", "/ch/2/in/conn/in": 2,
  "/ch/3/name": "Piano", "/ch/3/in/conn/grp": "LCL", "/ch/3/in/conn/in": 3,
  "/io/in/LCL/1/vph": 1, "/io/in/LCL/2/vph": 0, "/io/in/LCL/3/vph": 1
}
```

and these conditions as `phantom.watch.json`:

```json
{
  "watch_conditions": [
    {
      "id": "overheads-48v",
      "description": "48V stays on for the overheads",
      "channel": "CH 1-2",
      "field": "phantom",
      "operator": "==",
      "value": true,
      "severity": "error"
    },
    {
      "id": "piano-no-48v",
      "description": "The piano never gets 48V",
      "channel": "Piano",
      "field": "phantom",
      "operator": "==",
      "value": false,
      "severity": "error"
    }
  ]
}
```

```bash
atoo watch --state-sequence condenser.state.json --watch-conditions phantom.watch.json --count 1
```

```
...
[ERROR] WATCH:overheads-48v 48V stays on for the overheads
  CH 2 "OH R" has 48V off at LCL 2 -- 48V stays on for the overheads.

[ERROR] WATCH:piano-no-48v The piano never gets 48V
  CH 3 "Piano" has 48V on at LCL 3 -- The piano never gets 48V.
...
```

These cost no extra console read: a strip's sends, its Main routes, its
patch and each socket's 48V and width are part of every pass already. The
**Watch screen's** conditions table has the same four fields, with the
**Bus** box under the Field for the `send_` ones.

## Conditions most shows want

A handful of mistakes ruin a show, and the same handful turns up at most
gigs. The [Demo show](demo.md)'s `watch.json` carries a set worth
starting from. **A rule about a kind of strip is one condition on a
range**, not one per strip: the report still names every strip that
breaks it, by number and by its name on the desk.

| Watch for | Condition | Severity |
|---|---|---|
| the PA muted | `MAIN 1`, `muted` `==` `false` | error |
| the PA fader pulled down | `MAIN 1`, `fader_db` `>=` `-40` | error |
| a monitor or in-ear mix muted | `BUS 1-4`, `muted` `==` `false` | error |
| a mix or FX bus muted or at the floor | `BUS 5-7`: `muted` `==` `false`, and `fader_db` `>=` `-40` | error |
| a DCA muted or pulled down | `DCA 1-5`: `muted` `==` `false`, and `fader_db` `>=` `-30` | error for the mute, warning for the fader |
| the one channel the room hears | `Lead Vox`, `muted` `==` `false` | error |
| the click in every in-ear mix | `Click`, `send_on` `==` `true`, `bus` `BUS 5-8` | error |
| a monitor send kept pre-fader | `CH 1-8`, `send_mode` `==` `"pre"`, `bus` `BUS 1-4` | warning |
| 48V on the condensers | `CH 5-6`, `phantom` `==` `true` | error |

Write each description as the rule and nothing more (*No DCA is muted.*):
the report adds the strip and what was read, as in
`DCA 2 "Band" has its fader at -144 dB -- No DCA fader is below -30 dB.`

Here is the start of a house set, as a file of your own,
`house.watch.json`:

```json
{
  "watch_conditions": [
    {"id": "pa-muted", "description": "The PA stays unmuted.", "channel": "MAIN 1", "field": "muted", "operator": "==", "value": false, "severity": "error"},
    {"id": "pa-fader-low", "description": "The PA fader stays above -40 dB.", "channel": "MAIN 1", "field": "fader_db", "operator": ">=", "value": -40, "severity": "error"},
    {"id": "monitor-muted", "description": "No monitor bus is muted.", "channel": "BUS 1-2", "field": "muted", "operator": "==", "value": false, "severity": "error"},
    {"id": "dca-muted", "description": "No DCA is muted.", "channel": "DCA 1-8", "field": "muted", "operator": "==", "value": false, "severity": "error"},
    {"id": "dca-fader-low", "description": "No DCA fader is below -30 dB.", "channel": "DCA 1-8", "field": "fader_db", "operator": ">=", "value": -30, "severity": "warning"}
  ]
}
```

On the captured rig, only the DCA fader fires: DCA 1 is at the floor.

```bash
atoo watch --state-sequence audit_demo_state.json --watch-conditions house.watch.json --count 1
```

```
...
[WARNING] WATCH:dca-fader-low No DCA fader is below -30 dB.
  DCA 1 "Drums" has its fader at -144 dB -- No DCA fader is below -30 dB.
...
```

**Leave out what the built-in rules already watch**, or each fault comes
up twice. Some of those rules run only when Watch has the show's plan
(`--show`, or the Watch screen with a show open); the example above has
none, so they did not run there:

- **A channel patched from a bus, Main or Matrix that sends back to it**
  is `R009` (an error), or `R010` while one step of the loop is off or at
  the floor. No condition is needed for it.
- **A stage box whose link drops** is `C008` (an error, when a channel or
  output depends on the port) or `C009` (a warning: in error
  with nothing patched to it); a port reading `UPD` is `C010` (information
  only: the desk flags the stage box's firmware as older than it expects,
  and audio still passes). No condition is needed for it.
- **A channel that reaches no output** is `CV016`, with the plan.
  Without it, no built-in rule covers a channel that reaches nothing, so
  write `muted` `==` `false` on the channel that matters.
- **A send switched off or flipped to post-fader, a Main route that is
  wrong, or a send or route that is on and not in the plan** are `CV006`,
  `CV007` and `CV018`, with the plan. They cover the plan's sends and Main
  routes, so a condition for them would say the same thing twice.
- **A condenser with its 48V off, or 48V on where the plan has none** is
  `CV019`, with the plan. Without it, `C001` covers only 48V on a socket
  nothing is patched to, and a `phantom` condition is the way to say which
  channels must have it.
- **Something muted that the plan leaves unmuted** is `CV017`, with
  the plan, at WARNING. If you always watch with the plan, write a mute
  condition only where the mute should be an ERROR, as the PA and the
  lead vocal are above; the table's WARNING mute rows, the FX bus and
  the wedge, are for watching without it.
- **A DCA at -20 dB or lower with live strips in it** is `CH002`. A
  DCA fader condition still earns its place when you want your own
  threshold and severity. A send left on at -100 dB is `L001`.
- **A DCA muted with live strips in it** is `CH004`, a note; with the plan,
  a DCA it lists is `CV017`'s. A condition on the DCA's `muted` is for when
  you want it as a warning or an error.
- **48V on an empty socket, two strips with one name** are `C001` and
  `N001`. **An effect bypassed on an FX bus** is `CV015`, with the
  plan.

Where one of your conditions and a built-in rule both fire, Watch in the
browser shows them as one row, yours
([Read the table](watch-a-show.md#2-read-the-table)). What the plan's
rules catch is in [Watching from the command line](watch.md).

## Where the file comes from

In precedence order, first one wins:

1. `--watch-conditions PATH`
2. `watch.json` in the [show bundle](show-bundles.md) named by `--show`
3. a standing house file, `[watch_conditions] default` in
   [the config file](configuration.md#the-config-file)

A bundle build also **drafts** a starting `watch.json` for you, which you
then edit — see [Show bundles](show-bundles.md#a-build-writes-back-into-the-bundle).

## See also

- [Watching from the command line](watch.md) — `atoo watch`
- [Watch the desk during a show](watch-a-show.md) — the **Watch conditions** editor in the browser
- [Show bundles](show-bundles.md) — where `watch.json` lives
