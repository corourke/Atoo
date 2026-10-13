<!-- Ported from docs/user/STYLE.md in the development repository, where
     the pages are written (see README.md, "Where the pages come from").
     The commands it names run there, not in this site. -->

# How these pages are written

The rules for every page in `docs/user/`, the landing `README.md` and
`atoo/README.md`. Read it before writing or reviewing one.

## Who reads them

A sound engineer first and a programmer second, skimming between other
jobs. They want to know whether the page is for them, and then what to
click or type.

## Every page answers three questions, in this order

1. **Why should I care?** Open with the problem in an engineer's terms,
   in one or two sentences: *"The horn section turns up at 6pm and four
   channels have to go on a desk that is already set up."* Not *"plan
   amendment"*.
2. **Why this, and not what I already use?** Only on the landing page and the
   `why.md` page. Concrete comparisons, no marketing words.
3. **How do I do it?** Numbered steps, the common path first. Say what
   the reader sees when it worked.

## Length

- **Two screens at most.** Past that, split the page by task, or cut what
  the reader can find out from the screen in front of them.
- Edge cases go in a short section at the end, or nowhere.
- No history. No issue numbers, PR numbers, dates or "this used to…" in a
  user page. The reasons and the history belong in `docs/developer/`.
- No people. Do not quote or name anyone; write the rule, not who said it.

## Words

Use these, and only these, for these things:

| Say | Meaning | Not |
|---|---|---|
| **socket** | a physical connector: `LCL 3`, `A 12`, `USB 1` | input, port |
| **patch** | the connection from a socket to a channel | routing (that is signal flow) |
| **channel** | a numbered input channel on the desk | track, input |
| **strip** | the channel's settings as a whole (name, colour, EQ, sends) | channel strip, slot |
| **aux** | one of the desk's aux inputs | aux channel |
| **bus** | a mix bus, monitor or FX | mix, send bus |
| **DCA** | a DCA group | VCA, group |
| **input list** | `input.csv`: what is plugged in | channel list, rider |
| **conventions** | your house rules for setting up a desk, in your words | template, profile |
| **instructions** | `instructions.md`: one show's exceptions to the conventions | notes |
| **plan** | `plan.json`: every value the desk will be given, with its reason | config, scene |
| **show bundle** | one show's folder of files | project, workspace |
| **the desk** / **the console** | the WING itself; either is fine, pick one per page | the board, the mixer |
| **finding** | one line the checks report, with a severity and a code | error, warning (as nouns for all of them) |

Name the console models as **WING Compact**, **WING** (the full-size
desk) and **WING Rack**.

## Describing what the AI does

Be exact, because this audience is rightly sceptical:

- A model **drafts** the plan from your input list and conventions.
- Code **checks** the draft against the desk's real limits and your
  conventions before anything can be written.
- Every value written to the desk is **read back**, and what did not land
  is reported.
- Every choice the model made that you did not state is **announced** as
  an INFO finding, with what it was inferred from.

Never say the AI "does not choose values". It does; the checks are what
make that safe. Never say the model touches the console: it does not.

## Formatting

- UI labels in **bold**, spelled exactly as on screen: **Build plan**,
  **Ping**, **Preview**. Check the screen, not memory.
- Commands, file names, flags and finding codes in `code`.
- Steps are a numbered list. One action per step.
- A screenshot only where it saves words: one per idea, taken by
  `tools/doc_screenshots.py`, never showing a known bug.
- Example data is realistic: a band, a festival changeover, a church. Use
  the shows under [`demo/`](demo/README.md), never a real band's or
  person's name, never a real serial number, and `192.0.2.16` as the
  desk's address.
- Link to the page that explains a thing; do not explain it twice.

## Using the name

The product is Atoo (renamed from ShowProof on 2026-10-13). Say "Atoo" where a sentence needs a
name, and "it" or "the tool" otherwise. Never build a heading, a joke or a
page title around the name.

## Two rules that bind every page

1. **Every worked example is run before it is committed.** Paste the real
   output; never write what you expect it to print. A transcript run on a
   copy under [`demo/`](demo/README.md) is re-run by
   `tests/test_user_docs.py`.
2. **[`cli-reference.md`](cli-reference.md) is generated.** Edit only its
   `<!-- preamble -->` blocks, then run `python3 tools/gen_cli_reference.py`.

## Before you push

```bash
python3 -m pytest -q tests/test_user_docs.py tests/test_cli_reference.py
```

That checks every relative link and anchor in `docs/user/`, the landing
`README.md` and `atoo/README.md`, `CONTRIBUTING.md` and
`SECURITY.md` (including their `../../issues/new?template=…` links into
GitHub, against `.github/ISSUE_TEMPLATE/`), and that every
`atoo …` line in a code block is accepted by the CLI.
