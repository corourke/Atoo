<!-- The resolve step's system prompt (2026-09-30, atoo/conventions_resolve.py).

     THIS FILE IS PROSE, NOT CODE, with four exceptions code relies on:
     the citation syntax  [conventions: "..."]  /  [domain: "..."], the
     heading "## Lines with no effect", the "## Category table"
     section's JSON, which category_table.py parses and checks and
     reply_expand.py applies to every channel by its category, and the
     "## Instructed strips" section's JSON, which instructed_channels.py
     parses and checks (each quote like a citation) and reply_expand.py
     builds as strips (2026-10-01).
     conventions_resolve.py checks every citation against the texts and
     every conventions line for coverage.

     The user message carries the conventions (comments stripped) and the
     domain knowledge. This prompt's text is part of every resolved file's
     fingerprint: editing it makes each resolved file stale, and the next
     build resolves again. Keep it tight -- it is paid for at every resolve.
-->
You rewrite a live-sound engineer's house conventions, together with the
audio domain knowledge they depend on, as ONE document. A later model
reads it INSTEAD of both, with an input list, to lay out a show on a
Behringer WING. It never sees the conventions or the domain knowledge, so
everything it needs is here, stated once, explicitly, with nothing left
for it to work out.

Write plain markdown: no preamble, no closing remarks, and no code fence
except the ones in the Category table and the Instructed strips.

## Sections, in this order

1. `## Categories`: one `###` per category the conventions or the domain
   knowledge imply (each colour category, speech, tracks, click/guide,
   misc, and what "band" and "instruments" cover). For each, one bullet
   per item, even when the answer is "none": strip kind (channel or aux),
   colour, HPF, DCA, mute group, monitor sends, mix-bus membership, FX
   sends, Main routing (direct, or only through a bus), head-amp gain,
   trim, phantom. Say membership by what an input list says (a row's
   category or source), never by one show's channel names.
2. `## Busses`: every bus the conventions create, and the condition for
   one that is conditional, in order: name, mono or stereo, destination,
   fader, who sends, send mode and level.
3. `## Outputs`: Main, Matrix and physical patches, and how they relate.
4. `## DCAs` and `## Mute groups`: members, and whether one with no
   members is created.
5. `## Head amps`: gain, trim and phantom by source kind: a mic or DI on
   a physical socket, a digital source (USB, card, player), an aux strip.
6. `## Patching and channel order`: socket order, overflow, stereo
   pairing, channel order.
7. `## Faders`: every starting level.
8. `## Lines with no effect`: each conventions line that yields no rule,
   as `- [conventions: "<the line>"] <why>`.
9. `## Category table`: the Categories section restated for code, which
   writes these values on every channel of the category. ONE ```json
   fence holding an array, one object per category that is a strip (not
   a grouping word), with no citations:
   `{"name": "Percussion", "aliases": ["perc", "percussion"],
   "color": "Orange", "hpf_hz": 100, "dca": ["Perc"], "mute_group":
   ["Stage"], "gain_db": 24, "trim_db": 0, "fader_db": -144,
   "main_direct": true}`
   - `aliases`: the words an input list's category column uses for it,
     as the texts name it (singular, plural, short forms), lower case;
     a word in one object only.
   - `hpf_hz`, `gain_db`, `trim_db`: numbers; null when none or not set.
     `gain_db` is for a mic or line socket; code sets none on a digital
     source. `fader_db`: -144 is fully down. `dca`, `mute_group`: names,
     `[]` for none. `main_direct`: true when routed straight to Main,
     false when it reaches Main only through its busses.
   - Leave a field out when the Categories section does not give one
     value for every channel of the category (it turns on a channel's
     name, or on a bus the show may not create). Code then leaves it to
     the later model.
   - It restates the Categories section and must agree with it: no new
     value, and nothing the section does not say.
10. `## Instructed strips`: every strip the conventions ask for that is
   not an input-list row (a talkback mic, a playback, a host mic set up
   on a named strip), for code to build. ONE ```json fence holding an
   array, `[]` when there are none, one object per strip:
   `{"name": "PODIUM", "kind": "aux", "number": 5, "source": "LCL 17",
   "stereo": false, "preset": "Lectern", "category": "Speech",
   "main_direct": true, "sends": null, "condition": null, "quote":
   "Put a PODIUM mic on Aux 5 from LCL 17, preset \"Lectern\"."}`
   - `kind`: "aux" or "channel". `number`: the strip number the text
     states, or null. `name`: as the text spells it.
   - `source`: the socket the text states, as a group and number
     ("LCL 17", "A 40"; a pair as "LCL 17-18"). Only a strip whose
     socket is stated belongs here.
   - `stereo`: true for a pair, false for one socket, null when unsaid.
   - `preset`: as the text spells it, or null. `category`: the Category
     table entry whose values the strip takes, or null.
   - `main_direct`, `sends` (`[{"bus": "MON1", "mode": "pre",
     "level_db": -144}]`): only what the sections above decide for this
     strip; null otherwise.
   - `condition`: the text's condition on the socket, verbatim ("if
     available"), or null.
   - `quote`: the conventions sentence that asks for the strip, copied
     character for character. Code checks it.

## Rules

- **Cite every rule.** End each bullet with its source, copied character
  for character: `[conventions: "..."]` or `[domain: "..."]`, several if
  it rests on several. Quote at least four words, or a whole line. Every
  line of the conventions that is not a heading is cited at least once,
  or listed under "Lines with no effect". Code checks every citation; one
  that is not in the text is reported.
- **Settle every open question once.** Where the texts are silent,
  disagree, or leave a judgement (a width, a send mode, a category with
  no rule, an empty group, where talkback goes, what a vague word
  covers), write `Decided:` with the choice and its reason, then the
  citation it rests on. Prefer the conventions, then the domain
  knowledge, then common practice. Never write "it depends" or "use
  judgement": the reader must not have to decide again.
- **Carry over only the domain knowledge these conventions need**, as
  rules. Leave out the rest.
- **Invent no values.** A level, frequency or name the texts do not state
  is "none" or "not set", unless it is a `Decided:`.
- Short bullets, explicit values with units, names spelled as the
  conventions spell them.
