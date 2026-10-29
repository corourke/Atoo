# Writing an input list

The CSV that says what is plugged into the desk for one show.

It is the only file that changes every week. Your [conventions](conventions.md) say how you build a show; the input list says what is on stage tonight.

Every example on this page runs from the top of an Atoo checkout, on the touring band's list frozen there under `docs/user/demo/touringband/`. With your own list, use its path instead.

A **socket** is the physical connector on the desk (`LCL 3`, `AES50-A 12`, `USB 47`); a **patch** is the connection between a channel or bus and a socket. So the list's `patch` column says where each source is patched, and what goes in it is a socket.

## The columns

```bash
head -6 docs/user/demo/touringband/input.csv
```

```
socket,name,category,type,model,phantom,notes
AES50-A 1,Kick,drums,Mic,Beta91A,TRUE,
AES50-A 2,Snare,drums,Mic,,FALSE,
AES50-A 3,Tom1,drums,Mic,,FALSE,
AES50-A 4,HH,drums,Mic,,FALSE,
AES50-A 5,FLOOR,drums,Mic,,FALSE,
```

| Column | Required | What it is |
|---|---|---|
| `order` | no | The **band's own** number for this input. It does not set the desk channel. `-` **skips** the row. See [The `order` column](#the-order-column-band-numbers-and-skipping-a-row). |
| `patch` | no | The socket this source is cabled into — `AES50-A 1`, `LCL 3`, `CRD 64`. A column headed `socket`, like the one above, is read the same. Blank is legitimate. See [The `patch` column](#the-patch-column). |
| `name` | **yes** | What it is called — "Kick", "OH L", "Lead Vox". This is what your conventions match on, so name the halves of a pair "Keys L"/"Keys R". |
| `category` | **yes** | The group your conventions sort by: "drums", "band", "vocals", "horns"… Whatever words your own conventions file uses. |
| `type` | **yes** | `Mic`, `DI`, `Instrument`, `Line`, `Wireless`… An open vocabulary, there for your conventions to match against, with one exception: a channel of type `Line` on a head amp does not keep a mic's gain (below the table). |
| `model` | no | "SM58", "Beta 52", "CS2". Blank when it does not matter, which is most DI and line sources. |
| `phantom` | **yes** | `TRUE` / `FALSE`. This is source data, not a policy — it drives the preamp directly. A stereo pair ("OH L"/"OH R") has [one 48V value for both rows](#a-stereo-pair-has-one-48v-value): the desk switches a pair's two sockets together, so it is on if either row says `TRUE`. A stereo source on a single row gets its value on both sockets, with a note saying so. |
| `preset` | no | A preset from your [preset library](presets.md) — "Kick In". It **wins** over the conventions and instructions. Blank leaves it to the conventions. See [The `preset` column](#the-preset-column). |
| `channel`, `dca`, `mute_group` | no | The desk channel (`9`, `Aux 3`), and the DCAs and mute groups the input is in (`BAND; ALL`). A filled cell **wins** over the conventions and instructions, as `preset` does: a build places the channel there and puts it in those DCAs and mute groups. [`atoo capture`](capture.md) writes them from a desk, and a Save in Build's step 04 carries them into the plan. See [below](#the-channel-dca-and-mute_group-columns). |
| `notes` | no | A place for the person holding the sheet. The build's model reads it like the rest of the row, so a note can ask for the row to be [left out](#one-row-per-physical-input); nothing else uses it. |

**Column order does not matter**: every column is read by its header. Atoo writes `order` first when there is one, then `patch`, because it is what you check against the stage box, and `notes` last.

### A `Line` row on a head amp, when your conventions say no gain

If your conventions and instructions state **no** head-amp gain anywhere, a model sometimes still puts a mic's 20 dB on a row of type `Line` (a laptop, a playback feed) patched to a head amp, where it would clip the preamp. The build then gives that channel 0 dB, with an INFO (`reply.line-gain`):

```
channel 'Playback': a Line source on A 16, a head amp, so its gain is 0 dB, not the 20 dB the plan had -- that is a mic's gain, and a line-level feed with it would clip the preamp. Chosen from the source type, because no gain is stated in your conventions or instructions. Say a gain for 'Playback' (say, 'gain 6 dB') if you want another.
```

Where you do state a gain — the Category table's, or any line saying gain, including "set the head-amp gain on each channel to 20dB" — it applies to line sources too, and stands. [Patch](patch.md#the-rules) holds a change to the same rule.

## One row per physical input

Every input socket on a WING is mono. So a row is one mono source, and a **stereo source is two rows**:

```
AES50-A 15,Keys L,keys,DI,,FALSE,
AES50-A 16,Keys R,keys,DI,,FALSE,
```

Whether those two become one linked stereo strip or two mono ones is decided by your conventions, and they can only see what you wrote in `name`. So name the pair so it reads as one.

### Stating a stereo pair: the recipe

1. **Name the two rows the same, ending in `L` and `R`** (or `Left` and `Right`): `Keys L` / `Keys R`, `Playback Left` / `Playback Right`, `OH L` / `OH R`. The side is the last word; everything before it is the same on both rows. `Gtr (stage left)` and `Gtr (stage right)` are two guitars, not a pair.
2. **Put this sentence in your conventions**, word for word:

   ```
   Every L/R pair of inputs becomes one stereo channel.
   ```

   Every such pair on the list becomes one stereo channel, named for what the two rows share (`Keys`), whatever the model wrote; where it had written the pair otherwise, an INFO line says it was paired.
3. **For a pair that stays two mono channels, name it in a sentence of its own**, for example overheads you process separately:

   ```
   Keep OH L and OH R as two mono channels.
   ```

   A sentence that names the pair and says *mono channels* keeps it apart, also said at INFO.

Without a sentence that plain (*"stereo-paired inputs become one stereo channel"* does not say which inputs), pairing is left to the model, and the build says at INFO that it chose. The rule and its exceptions are covered in [Writing conventions](conventions.md#stereo-pairs-are-a-conventions-decision).

The two rows need not state a socket. When they do not, the build pairs them on the next free odd-even pair.

### A stereo pair has one 48V value

The desk switches a stereo channel's two sockets together: write 48V to one and the other reads back already on. So a stereo channel cannot be built with a condenser on one socket and a dynamic on the other. When the two rows disagree, the build gives the pair **one value, on if either row says `TRUE`**, and tells you which row asked, with a note:

> channels[OH]: 48V is on for both sockets of the stereo channel: 'OH L' asks for it and 'OH R' does not, and the desk switches a pair's two sockets together, so the pair takes the value either row wants (split the pair into two mono channels if you want 'OH R' without 48V) (`reply.pair-phantom`)

A condenser left without 48V is silent, and a dynamic given it is unharmed, so "on" is the choice that costs least. If you do want one of them without 48V, keep them as two mono channels. Rows that agree say nothing.

**A passive ribbon on either side of a powered pair is refused**, because 48V destroys the element and switching it off afterwards does not undo that. The refusal names the ribbon's row. This one is from the demo show with `Keys L` made a condenser and `Keys R` a Royer R-121 (a copy of its input list and plan, in `/tmp`):

```bash
sed 's/Keys L,keys,DI,,FALSE/Keys L,keys,DI,,TRUE/; s/Keys R,keys,DI,,FALSE/Keys R,keys,DI,Royer R-121,FALSE/' docs/user/demo/touringband/input.csv > /tmp/ribbon.csv
python3 -c "
import json
plan = json.load(open('docs/user/demo/touringband/plan.json'))
for ch in plan['channels']:
    if ch['name'] == 'Keys L':
        ch['source'].update(phantom=True, pair_phantom=True)
json.dump(plan, open('/tmp/plan-ribbon.json', 'w'), indent=2)"
atoo verify --plan /tmp/plan-ribbon.json --input /tmp/ribbon.csv
```

```
1 error(s), 0 warning(s), 15 note(s)

  [error] channels[Keys L]: 'Royer R-121' (Keys R, the pair's second socket) is a passive ribbon microphone and the plan sends it phantom power -- a stereo channel's two sockets switch 48V together, so the pair takes it if either row wants it -- 48V destroys a ribbon element and undoing the setting does not undo the damage. Split the pair into two mono channels, or set the other row to a source that takes no 48V (phantom FALSE)  (safety.phantom-on-passive-ribbon)

  [info] plan: 'Magenta' is the desk's Pink (11): ...
```

(The first lines; the rest are the demo's usual notes, and the last line is `BLOCKED: do not apply.`)

A plan built before this rule can state two different values for a pair. `atoo verify` reports it as a warning (`phantom.pair-differs`) and `atoo apply` writes the one value, on if either is; rebuild to have the plan say so itself.

**A channel that is yours rather than the band's** (a talkback mic, an ambient pair) does not need a row: ask for it in words, with its socket. See [Channels that are not on the input list](extra-strips.md).

**A row you want left out of the build** takes `-` in its `order` cell ([below](#the-order-column-band-numbers-and-skipping-a-row)). Every other row is built unless something you wrote says to leave it out: the row's `notes` (*"not patched for this event"*), the conventions or the show's instructions. The build checks the model quoted you word for word, and `verify` warns about the row, quoting you (`reconcile.deliberately-unassigned`).

## The `channel`, `dca` and `mute_group` columns

Three optional columns that say where an input sits on the desk: the channel it is on (`1` to `40`, or `Aux 1` to `Aux 8`), and the DCAs and mute groups it is in, each a `;`-separated list of their names. A stereo source's two rows give the same channel.

```
channel,patch,name,category,type,model,phantom,dca,mute_group,notes
9,AES50-A 19,Kick,Drum LEVELS,Mic,,FALSE,Drum LEVELS,ALL,
```

**A filled cell wins** over your conventions and instructions, as the `preset` column does. Each change it makes is a note in the build's report:

- **`channel`** puts the channel on that strip. A channel the conventions had put there takes the strip the moved one left, so nothing is lost and no strip holds two inputs. An aux strip has no high-pass, so a channel moved onto one has none.
- **`dca`** and **`mute_group`** are the channel's whole membership. A name your conventions do not declare is declared, and takes the next free DCA or mute group. A name your conventions spell another way only in capitals or spaces is the same group, and takes your spelling: with `DRUMS` in the list and `Drums` in the conventions, the DCA is named `DRUMS` on every channel in it, and the report says *DCA 'Drums' is named 'DRUMS', as the input list spells it.* Rows that spell one group two ways take the first row's spelling, said once. A Save in Build's step 04 does the same.
- **Two rows naming one strip** are refused, naming them, unless they are a stereo source's two rows (one strip). Where a stereo source's rows name different strips, the first row's wins, and the report names both.
- A blank cell leaves it to the conventions.

[`atoo capture`](capture.md) writes them when it reads a desk you didn't build, and that show's plan agrees with them. Edit them in Build's step 04 and its **Save** carries them into the plan as well ([Editing the sheets](capture.md#editing-the-sheets)). A cell changed anywhere else (a spreadsheet, a text editor) reaches the plan at the next build, or the next Save in step 04. Until then the plan does not follow it, and `atoo verify` warns, rather than let a cell that had no effect look honored. On the show [capture](capture.md) made, with Kick moved to channel 3 in the sheet outside step 04:

```bash
sed -i 's/^9,AES50-A 19,Kick,/3,AES50-A 19,Kick,/' /tmp/shows/church-full-2026-10-24/input.csv
atoo verify --show /tmp/shows/church-full-2026-10-24
```

```
...
  [warning] channels[Kick]: The input list puts Kick on channel 3, but the plan has it on 9: the plan was changed after it was built, or the list after the plan. Rebuild, or Save the input list in Build 04, to apply the cell; or clear the cell if the plan is right  (input-list.column-not-followed)
...
```

A channel the desk does not have (`41`, `Aux 9`) is refused, naming the row.

## Columns you may not have

A file carrying either of these is **refused, not ignored** — the file would otherwise load, the column would have no effect, and the plan would quietly contradict the sheet.

**`ch` or `channel_number`.** The desk channel goes in the `channel` column, above.

```bash
sed '1s/^socket,/ch,socket,/; 2,$s/^/1,/' docs/user/demo/touringband/input.csv > /tmp/with-ch.csv
atoo verify --plan docs/user/demo/touringband/plan.json --input /tmp/with-ch.csv
```

```
couldn't read input list '/tmp/with-ch.csv': input list has column(s) it must not have: 'ch' -- the desk channel goes in the 'channel' column (1-40, or 'Aux 1'-'Aux 8')
```

**No `stereo` column.** Whether "Keys L" and "Keys R" become one strip is a decision, not a property of an input — and it is a decision your conventions already make, usually with an exception attached ("overheads stay mono, they get separate processing"). Stating it per row puts the answer in the one place that cannot see the rule.

## The `patch` column

**A column headed `socket` is read as `patch`**, so a list headed either way loads the same. A new list Atoo writes is headed `patch`; saving an existing file keeps whichever header it already has.

A socket, written `"<group> <number>"`, e.g. `LCL 3`. The groups Atoo recognizes:

| Written | What it is |
|---|---|
| `LCL` | the console's own local XLR inputs |
| `AES50-A` `AES50-B` `AES50-C` | the AES50 stage-box ports — **spelled out**; a bare `A 1` is refused |
| `SC` | StageConnect |
| `USB` | the USB interface |
| `CRD` | the expansion **card** bay |
| `MOD` | the AoIP **module** bay — a different slot from the card |
| `AUX` | the 1/4" aux jacks |
| `USR` | user signals and user patches (see [below](#when-the-cabling-cannot-give-you-an-adjacent-pair)) |
| `AES` | AES/EBU |
| `PLAY` | the player |

The long forms parse too — `Local 3`, `Card 1`, `Module 2`, `User 25`, `StageConnect 4` — and case and hyphens are not significant, so `aes50-a 12` and `AES50-A 12` are the same socket.

Two spellings that look reasonable and are refused on purpose:

- **"SD card" is not `CRD`.** `CRD` is the expansion card bay. The SD card is WING LIVE's storage, which is not an input group at all. What a WING LIVE card *plays back* does arrive on `CRD`, but only when WING LIVE is the card fitted — which is exactly what the words "SD card" do not say.
- **"Dante" is not a group.** Dante is sold both as an expansion card (`CRD`) and as an internal module (`MOD`), so the word does not say which bay it means. Write `CRD n` or `MOD n`.

Anything unrecognized is reported, never guessed at:

```bash
sed 's/^AES50-A 8,TRAX/Dante 3,TRAX/' docs/user/demo/touringband/input.csv > /tmp/dante.csv
atoo verify --plan docs/user/demo/touringband/plan.json --input /tmp/dante.csv
```

```
  [warning] input list[TRAX]: patch 'Dante 3' could not be read as '<group> <number>' -- the plan's patch for this row could not be checked against it  (patch.unparsable-stated-socket)
```

### `CRD` and `MOD` are bays, and a bay can be empty

Both are slots that a card may or may not be fitted into. A plan that patches a channel from an empty bay is refused by `apply` against a desk that has nothing in that slot, rather than written into a channel that would hear nothing — see [What a full apply changes](what-apply-changes.md#expansion-bays-crd-and-mod).

### Leaving the patch blank

Legitimate, and common early in the week when the cabling is not settled. A row with no patch gets a socket chosen for it during the build, and the plan records the difference: `"stated": true` is where *you* said the cable is, `false` is where Atoo put it. `atoo build --pretty` prints the second kind as `Patch: A 1 (auto)`, and `apply` says it again as it writes -- once, naming the strips, since the warning is the same for each (the journal keeps one line per strip). From an apply of a 23-channel show:

```
  - ch 1-23 (23 channels): patch socket was not stated in the input list and was assigned during generation -- verify before trusting this write
```

Which is the whole point of the distinction: a socket you stated can be checked against the stage box, and one that was chosen for you has to be.

## The `order` column: band numbers, and skipping a row

Optional, and first when it is there. A cell holds one of three things:

| In the cell | Means |
|---|---|
| a number, `1` and up | the band's own number for this input — usually the split from their IEM rack, or how they patch their stage box |
| `-` | **skip**: the row stays in the file, and the next build leaves it out |
| nothing | an ordinary row with no band number |

Anything else is refused, naming the row.

**The number does not set the desk channel.** Which strip a source lands on is still your conventions' to compute. The number goes to the model with its row, as data, so your instructions can use it — *"Patch the inputs according to the band's channel order numbers."* Without such a sentence it changes nothing.

**A skipped row is left out of the build entirely.** It is not sent to the model, nothing is built for it, and `verify` does not count it as a missing input. The build says once, at INFO, which rows it left out (`input-list.skipped`). That is what makes it useful for a festival list: keep every band's full list, and switch rows off and on between sets rather than deleting and retyping them.

Here is the touring band's list with an `order` column, and its TRAX row skipped:

```bash
python3 - <<'EOF'
import csv, io, pathlib
rows = list(csv.DictReader(pathlib.Path("docs/user/demo/touringband/input.csv").read_text().splitlines()))
for n, row in enumerate(rows, 1):
    row["order"] = "-" if row["name"] == "TRAX" else str(n)
out = io.StringIO()
w = csv.DictWriter(out, fieldnames=["order"] + [c for c in rows[0] if c != "order"])
w.writeheader(); w.writerows(rows)
pathlib.Path("/tmp/festival.csv").write_text(out.getvalue())
EOF

head -3 /tmp/festival.csv
grep TRAX /tmp/festival.csv
```

```
order,socket,name,category,type,model,phantom,notes
1,AES50-A 1,Kick,drums,Mic,Beta91A,TRUE,
2,AES50-A 2,Snare,drums,Mic,,FALSE,
-,AES50-A 8,TRAX,tracks,Line,,FALSE,
```

The plan was built before TRAX was skipped, so it still has a TRAX channel. `verify` gives a warning (the desk would work, with a strip nobody plugs into; the notes are left out here with `grep`):

```bash
atoo verify --plan docs/user/demo/touringband/plan.json --input /tmp/festival.csv | grep -v '^  \[info\]'
```

```
0 error(s), 1 warning(s), 15 note(s)

  [warning] channels[TRAX]: source 'TRAX' is skipped on the input list ('-' in its order cell), but this plan builds a channel for it -- it was built before the row was skipped  (reconcile.skipped-source)


APPLICABLE: warnings only.
```

A rebuild leaves it out, and the skipped row is not reported missing.

A cell that is neither a number, `-`, nor empty stops the list from loading:

```bash
sed 's/^-,/x,/' /tmp/festival.csv > /tmp/bad-order.csv
atoo verify --plan docs/user/demo/touringband/plan.json --input /tmp/bad-order.csv
```

```
couldn't read input list '/tmp/bad-order.csv': row 21: column 'order' must be the band's input number (1, 2, ...), '-' to skip the row, or blank -- got 'x'
```

A skipped row is still checked like any other — switching it back on should never turn up an error nobody saw — with one exception: it may share its name with a row that is on, so two bands' `Kick` rows can sit in one list with one of them skipped. A list with **every** row skipped has nothing to build, and is refused.

In the browser, Build step 02's **Order** cell has a **Skip** box: tick it and the cell reads `-` and the row dims; untick it and the number comes back. On a read-only show a skipped row's Order cell reads **SKIP**.

## The `preset` column

Optional. A value names a preset in your [preset library](presets.md), matched as a name in your conventions is ([how forgiving that is](presets.md#naming-one-and-how-forgiving-the-match-is)), so `kick in` finds **Kick In**. Like a stated patch, **the list wins** over the conventions, and the build notes it at INFO when it replaces a different preset. A name the library has not got is a `preset.unknown` warning, and the strip is built without it.

Of a stereo pair's two rows, one naming the preset is enough. If they name different ones, the **first** row's wins (the row the channel is named from), and `verify` warns `preset.input-list-pair-disagrees`.

`verify` warns when a channel's preset is not the one its row states (`preset.contradicts-input-list`): a warning, not an error, because the desk works either way. Here is the Kick row given a preset, checked against a plan built before the list said so (the notes are left out with `grep`):

```bash
python3 - <<'EOF'
import csv, io, pathlib
rows = list(csv.DictReader(pathlib.Path("docs/user/demo/touringband/input.csv").read_text().splitlines()))
rows[0]["preset"] = "kick in"
out = io.StringIO()
w = csv.DictWriter(out, fieldnames=list(rows[1].keys()) + ["preset"])
w.writeheader(); w.writerows(rows)
pathlib.Path("/tmp/with-preset.csv").write_text(out.getvalue())
EOF

head -2 /tmp/with-preset.csv
atoo verify --plan docs/user/demo/touringband/plan.json --input /tmp/with-preset.csv --presets starter/presets | grep -v '^  \[info\]'
```

```
socket,name,category,type,model,phantom,notes,preset
AES50-A 1,Kick,drums,Mic,Beta91A,TRUE,,kick in
0 error(s), 1 warning(s), 15 note(s)

  [warning] channels[Kick].processing.preset: plan names no preset, but the input list's preset column states 'kick in' for 'Kick' -- the list wins over the conventions, so this plan was edited by hand or built before the list said so  (preset.contradicts-input-list)


APPLICABLE: warnings only.
```

A rebuild puts the starter preset **Kick In** on the Kick channel. In the browser, Build step 02's **Preset** column offers your library's names.

## A stereo pair needs two adjacent sockets, odd first

`LCL 15`+`LCL 16`, never `LCL 7`+`LCL 12` and never `LCL 2`+`LCL 3`.

This is the desk's routing hardware, not an Atoo rule: a WING forms a stereo pair only from consecutive `[odd, even]` sockets. It is a constraint on the **cabling**, so it is cheapest to fix while writing the list. `verify` refuses a plan that patches a pair the other way round:

```bash
python3 - <<'EOF'
import json, pathlib
plan = json.loads(pathlib.Path("docs/user/demo/touringband/plan.json").read_text())
for c in plan["channels"]:
    if c["name"] == "Keys L":
        c["patch"]["sockets"] = [16, 17]   # the pair as cabled: even first
    if c["name"] == "OH":
        c["patch"]["sockets"] = [21]       # OH moves off 17 to make room
pathlib.Path("/tmp/even-first.plan.json").write_text(json.dumps(plan, indent=1))
csv_text = pathlib.Path("docs/user/demo/touringband/input.csv").read_text()
csv_text = csv_text.replace("AES50-A 17,OH", "AES50-A 21,OH")
csv_text = csv_text.replace("AES50-A 15,Keys L", "AES50-A 16,Keys L")
csv_text = csv_text.replace("AES50-A 16,Keys R", "AES50-A 17,Keys R")
pathlib.Path("/tmp/even-first.csv").write_text(csv_text)
EOF

atoo verify --plan /tmp/even-first.plan.json --input /tmp/even-first.csv
```

```
1 error(s), 0 warning(s), 15 note(s)

  [error] channels[Keys L].patch: A 16+17 cannot be a stereo pair -- the pair starts on 16, an even socket (a pair always starts on an odd one). The console's routing hardware forms a stereo pair only from consecutive [odd, even] sockets, so this patch cannot be made as written  (patch.stereo-pair-not-odd-even)
  ...
BLOCKED: do not apply.
```

Exit code 2. That plan was edited by hand. A **build** from the same list does not stop here: it patches the pair through the desk's user patches, below.

## When the cabling cannot give you an adjacent pair

The two halves land on `LCL 4` and `LCL 5`, or on different stage boxes, or on two playback tracks 32 apart on one card. The desk's own way round this is a **user patch**: two consecutive slots of its `USR` group, from USR 25 to USR 56 and odd first, each taking one input socket as it is. The channel is patched to the two slots as an ordinary pair.

**The build does this for you.** When the two rows of a pair state sockets the desk cannot pair, the build makes one stereo channel, patched to the first free pair of user patch slots, each slot taking its row's socket. It says so at INFO:

*'Keys L' (LCL 4) and 'Keys R' (LCL 5) can't be one stereo pair as cabled -- the pair starts on 4, an even socket (a pair always starts on an odd one) -- so 'Keys' is patched through user patch USR 25-26, which take LCL 4 and LCL 5*

- **Two rows named as one pair are one pair**, `Keys L` and `Keys R` (or `Left` and `Right`), even when the model built them as two mono channels because of their sockets. The build joins them into one stereo channel named `Keys` and says so at INFO: *'Keys L' and 'Keys R' are one L/R pair by their names, so they are one stereo channel 'Keys': the reply left them as two mono channels, though only their sockets kept them apart, and code pairs those through user patch slots.* Two such rows on sockets the desk can pair directly are left as the model built them.
- **`atoo build` prints these notes** under *Stereo pairs*, as well as keeping them in the plan.
- **The build summary** shows the patch as `USR 25-26 (LCL 4 + LCL 5)`.
- **Phantom power and gain** are set on the two sockets, `LCL 4` and `LCL 5`, not on the slots.
- **The slots your `user.csv` names** are left alone ([User signals and patches](capture.md#user-signals-and-patches-usercsv)).
- **A pair the desk can form directly** (`LCL 3` and `LCL 4`) stays a direct patch.
- **With no pair of slots free**, the two rows are built as two mono channels, with an INFO saying why.

A plan can also state slots by hand, in its top-level `user_sources` section. `verify` checks them, including the odd-first rule, which is not bypassed anywhere, and checks each row's stated socket against the socket its slot takes.

`apply` writes each slot (what it takes, and its name) before the channel that patches it, and sets both slots of a stereo pair to stereo; Undo puts them back. How a pair set this way sounds at the strip has not yet been checked on a desk.

## Checking a list before the desk exists

There is no `atoo check-input-list`; the input list is checked wherever it is used. The two useful moments:

- **`atoo build`** reads it first, so a malformed file stops the run before a model call is spent.
- **`atoo verify --plan p.json --input list.csv`** reconciles a built plan against it: every input became a channel, no channel was invented ([unless you asked for it](extra-strips.md)), phantom power is safe for the microphones named, every stated socket matches what the plan patched, and every stated preset is the one the plan names. Without `--input`, `verify` says out loud that it checked none of that (`reconcile.not-checked`) rather than passing quietly. `atoo patch` and `atoo amend` with `--show` read the show's `input.csv` for the same reason; a typed change is held to it more loosely than a rebuild (see [Patch](patch.md)).
- **`atoo ui`**, Build step 02, shows the list as an editable table. Save rewrites only the rows you changed and will not write over an edit made in another program since the page read the file. Name, Category and Type are required; Save asks once before writing a list that will not load. Rows can be added, and moved by dragging or with Alt+↑ / Alt+↓. See [Build a show](build-a-show.md). On a read-only show, the [Demo](demo.md), the table is plain text: no boxes to type in, no handles or row buttons, and **Save** and **Discard changes** (at the top of the table, as in the other editors) are locked with *Locked: the Demo show is read-only* beside them.

## See also

- [Writing conventions](conventions.md) — the other half, and the file that decides what happens to these rows
- [The command line](quickstart.md) — an input list through to a proven desk
- [Show bundles](show-bundles.md) — where `input.csv` lives for one show
- [Channels that are not on the input list](extra-strips.md) — talkback, playback and the strips you add at every show
