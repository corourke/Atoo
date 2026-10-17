"""Plan generation: the model proposes, deterministic code disposes.

The other half of the architecture from `verify_plan.py`. Instead of
extracting conventions into an intermediate rules IR and compiling that,
the model is handed the conventions, the input list, the domain knowledge
and the console's real limits together, and produces a plan directly.

Why the boundary moved here: a conventions schema has to model every way a
human might express intent about a show, which is unbounded -- the IR grew
19 times in three days and still drops detail. A plan schema has to model
only what a WING can be set to, which is finite and already walked. Moving
the deterministic layer's job from *derivation* to *validation* converts
an unbounded schema problem into a bounded one.

Nothing here talks to a console. A generated plan is an ordinary plan: it
goes through the same verification, the same human review of the same
diff, and the same readback-proved apply.

Two deliberately separate roles:

  generator -- lays the show out. Sees conventions, input list, domain
               knowledge and the console's real limits, all at once. That
               "all at once" is the point: today's extractor
               runs before the input list exists, so "band, excluding drums"
               has nothing to resolve against.

  resolve   -- (2026-09-30, `conventions_resolve.py`) restates the house
               conventions and the domain knowledge once as cited rules;
               when it is used, the generator and the fix-up read that
               text in place of both, and the critic still reads the raw.

  critic    -- reviews someone else's plan, adversarially, looking for
               omissions first. Separate role and separate call so it is not
               defending its own work; it never sees that a model wrote the
               plan, only that a plan needs checking.

The console section of both prompts is GENERATED from console_facts.py, not
typed here, so the numbers the model is told can never drift from the
numbers the verifier enforces. If they could drift, a passing verify would
stop meaning anything.

What the generator writes is not the plan but a shorter REPLY
(`plan_schema.REPLY_SCHEMA`),
which `reply_expand.expand` turns into the plan inside `generate_plan`
before the plan schema is checked: omitted fields read as null, the
name-keyed sections arrive as arrays, each bus lists its senders once,
and the numbering, the input list's facts and the socket counting are
code's, each announced at INFO. The plan a caller gets is today's plan.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from atoo.ai_provider import AIProvider
from atoo.allocate import allocate_console_indices
from atoo.json_repair import extract_json_object as _extract_json_object, loads_with_repair
from atoo import plan_compat
from atoo.schema_check import validate as validate_schema

from atoo import console_facts as facts
from atoo import diagnostics
from atoo import conventions_audit
from atoo import conventions_text
from atoo import inferred
from atoo import instructed_channels
from atoo import plan_schema
from atoo import reply_expand
from atoo.diagnostics import Diagnostic

_DOMAIN = Path(__file__).parent / "domain" / "knowledge.md"
_DEFAULT_PROMPT_DIR = Path(__file__).parent / "prompts"

# An HTML comment at the top of a prompt file is a note to whoever edits it,
# not something the model should read.
# The note ends at a `-->` that ends its line: the note itself quotes
# `<!-- ... -->` mid-sentence, and stopping at that one leaked the rest of
# the note into every prompt (found 2026-09-28).
_EDITOR_NOTE_RE = re.compile(r"\A\s*<!--.*?-->[ \t]*(?:\n\s*|\Z)", re.S)


def prompt_dir() -> Path:
    """Where prompt files are read from.

    ATOO_PROMPT_DIR points this at a copy, so a prompt variant can be
    tried without editing the packaged one and without a branch -- which is
    the difference between iterating on prompts and being afraid to.
    """
    return Path(os.environ.get("ATOO_PROMPT_DIR") or _DEFAULT_PROMPT_DIR)


def load_prompt(name: str, **substitutions: str) -> str:
    """Read a prompt file, strip its editor note, fill its placeholders.

    A placeholder the caller did not supply is an error rather than being
    left as literal braces in the model's input: a prompt that silently
    ships `{console}` to the model is a prompt that tells it nothing about
    the console, and the resulting plan would look like a model failure.
    """
    path = prompt_dir() / name
    try:
        text = _EDITOR_NOTE_RE.sub("", path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PromptError(f"couldn't read prompt {path}: {exc}") from exc

    wanted = set(re.findall(r"\{(\w+)\}", text))
    missing = wanted - set(substitutions)
    if missing:
        raise PromptError(
            f"{path}: uses placeholder(s) {sorted(missing)} that nothing supplies. "
            f"Available here: {sorted(substitutions)}"
        )
    for key, value in substitutions.items():
        text = text.replace("{" + key + "}", value)
    return text


class PromptError(RuntimeError):
    """A prompt file is missing, unreadable, or uses a placeholder nothing
    fills. Raised rather than warned: every one of those sends the model a
    prompt that is quietly not the prompt anyone wrote."""


def generator_system(console_model: str) -> str:
    return load_prompt("plan_generation.md",
                       console=console_section(console_model),
                       schema=plan_schema.schema_section())


def critic_system() -> str:
    return load_prompt("plan_critique.md")


def console_section(console_model: str) -> str:
    """The console half of the generator prompt, for one specific model.

    This used to render `facts.INPUT_SOCKETS`/`OUTPUT_SOCKETS`
    -- the ADDRESS SPACE -- and call it "sockets that exist". On a Compact
    that told the model `AUX (Aux In (1/4")) 1-8` for jacks the console
    does not have, and the model would duly patch them. This module's own
    contract (see the docstring) is that the numbers the model is told
    cannot drift from the numbers the verifier enforces; since the
    verifier moved to panel counts, so must this.

    A group the model has none of is omitted entirely rather than listed
    as `1-0`: the point is that it does not exist here.
    """
    panel = facts.panel_for(console_model)

    def sockets(table: dict, limit) -> str:
        # Each group is named with the spelling an input list uses, because
        # the code alone is ambiguous: an input list saying "AES50-A 1"
        # against a bare list of "A, AES, ..." invites reading the group as
        # "AES". One model did that on all 19 channels.
        parts = []
        for g in sorted(table):
            n = limit(g, console_model)
            if not n:
                continue
            parts.append(f"{g} ({facts.GROUP_ALIASES[g]}) 1-{n}"
                         if g in facts.GROUP_ALIASES else f"{g} 1-{n}")
        return ", ".join(parts)

    absent = sorted(
        g for g in facts.MODEL_VARIANT_GROUPS
        if not facts.input_socket_limit(g, console_model)
        and not facts.output_socket_limit(g, console_model))
    absent_note = (
        f"\nThis console has NO {', '.join(absent)} sockets at all -- they exist on other\n"
        "WING models. Do not patch anything to them.\n" if absent else "")

    lcl_in = facts.input_socket_limit("LCL", console_model)
    lcl_out = facts.output_socket_limit("LCL", console_model)
    lo_f, hi_f = facts.FADER_DB_RANGE
    lo_h, hi_h = facts.HPF_HZ_RANGE
    return f"""\
## The console: a {panel['label']}

These are hard limits read off the hardware. A plan that violates any of
them is rejected before it reaches the console, so do not produce one.

Strips and objects:
{chr(10).join(f"  {k}: 1-{v}" for k, v in facts.CAPACITY.items())}

Physical INPUT sockets that exist:
  {sockets(facts.INPUT_SOCKETS, facts.input_socket_limit)}

Physical OUTPUT sockets that exist:
  {sockets(facts.OUTPUT_SOCKETS, facts.output_socket_limit)}
{absent_note}
Note LCL: {lcl_in} inputs but only {lcl_out} outputs. The two are not
interchangeable.

Value domains:
  fader / send level: {lo_f:g} to {hi_f:g} dB. {facts.MINUS_INF_DB:g} is the console's -infinity
                      (fully down / silent). Unity is 0.0.
  high-pass filter:   {lo_h:g} to {hi_h:g} Hz
  head-amp gain:      {facts.HEAD_AMP_GAIN_DB_RANGE[0]:g} to {facts.HEAD_AMP_GAIN_DB_RANGE[1]:g} dB, and ONLY on {', '.join(sorted(facts.PHANTOM_CAPABLE_GROUPS))}
                      sockets. Every other source (USB, a card, a player) has no
                      head amp and no phantom: gain_db stays null there, whatever
                      the conventions say "on each channel" -- one note says so.
  strip name:         at most {facts.NAME_MAX_CHARS} characters. The console truncates; a longer
                      name is not what the operator will see.
  send mode:          "pre" or "post" in a plan.

Every input socket is mono. A stereo channel consumes exactly TWO sockets.
There is no such thing as a stereo input, which is why the input list has
no stereo column: pairing is decided from the conventions and the source
names, not read off the sheet.

{facts.STEREO_PAIR_RULE}"""


def _domain_knowledge() -> str:
    """The prose domain file, verbatim.

    Not a prompt file: it is knowledge about audio that is true regardless
    of who is asking, and it is read by a human as often as by a model.
    Prompts live in prompts/ and are swappable per experiment; this is not.

    Missing is fatal, not substitutable. This text is embedded
    in BOTH the generator and the critic prompt, so a substituted
    parenthetical costs a full model run that lays the show out with no
    audio vocabulary and a critic that cannot see the omission either --
    and the result looks like the model being bad at audio rather than like
    a packaging mistake. Same reasoning, and the same exception, as
    `load_prompt` on an unreadable prompt file.
    """
    try:
        return _DOMAIN.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(
            f"couldn't read the domain knowledge file {_DOMAIN}: {exc}. "
            "It ships with the package (pyproject's package-data 'domain/*.md'); "
            "an install that is missing it would generate every plan without the "
            "audio vocabulary."
        ) from exc


def _category_note(category_table, input_csv: str) -> str | None:
    """What code writes from the resolved conventions' Category table, for
    the categories this input list uses (`category_table.prompt_note`), or
    None when there is no table to apply. An input list that will not
    parse is reported by build; here it just means no note."""
    if category_table is None:
        return None
    from atoo import category_table as ct
    from atoo.input_list import InputListError, parse_input_list

    try:
        rows = parse_input_list(input_csv)
    except InputListError:
        return None
    return ct.prompt_note(category_table, [row.category for row in rows])


def _code_notes(category_table, instructed_strips, input_csv: str) -> str | None:
    """What code writes for the generator, from the resolved conventions:
    the Category table's per-category values (`_category_note`) and the
    strips code builds (`instructed_channels.strips_prompt_note`)."""
    notes = [_category_note(category_table, input_csv)]
    if instructed_strips:
        notes.append(instructed_channels.strips_prompt_note(instructed_strips))
    notes = [n for n in notes if n]
    return "\n\n".join(notes) if notes else None


def _conventions_section(conventions: str, conventions_name: str,
                         instructions: str | None, instructions_name: str | None,
                         resolved: str | None = None, resolved_name: str | None = None,
                         category_note: str | None = None) -> str:
    """The conventions text the model reads, as one or two named layers.

    The show-independent
    conventions file is always brought in, as well as a show's
    instructions if it is present, and content in the instructions file
    overrides the conventions file.

    The precedence is stated **in the prompt**, deliberately, rather than
    resolved by merging the two texts here. That was settled early: a
    structural merge would need this code to understand what each
    sentence means, which is exactly the unbounded problem the move to
    generation took the deterministic boundary away from. Two labelled sections and one rule
    the model can apply is the whole mechanism.

    **Comments are stripped here** (`conventions_text.strip_comments`):
    `<!-- ... -->` is where the engineer keeps notes to himself, and this
    is the one function every prompt -- generator, critic, watchlist --
    embeds the conventions through, so no model sees a comment whichever
    caller built the prompt. Callers pass the file as written; the bytes
    recorded in `meta.conventions_stack` stay whole.

    **`resolved`**, when given, is the resolved conventions
    (`conventions_resolve.prompt_text`): the house conventions and the
    domain knowledge restated once as cited rules, with every open
    question decided. It takes the house file's place here, and the
    caller leaves the domain knowledge out; the instructions layer on top
    of it exactly as they do on the raw file.

    **`category_note`**, with `resolved` only, is `_category_note`: the
    per-category values code writes from the resolved file's Category
    table, so the generator leaves them out unless a channel is an
    exception. In the user message, not the system prompt: it exists only
    when the table does, and the system prompt is at the Ollama limit.
    """
    if instructions:
        instructions = conventions_text.strip_comments(instructions)
    if resolved:
        base = f"""# The engineer's conventions, resolved ({resolved_name or "resolved conventions"})

The engineer's standing preferences ({conventions_name}) and the audio
domain knowledge they depend on, restated once as explicit rules. This
replaces both: neither is shown separately. A rule marked "Decided"
settles a question the conventions leave open -- apply it as written;
do not work it out again.

{resolved.strip()}"""
        if category_note:
            base = f"{base}\n\n{category_note.strip()}"
    else:
        conventions = conventions_text.strip_comments(conventions)
        base = f"""# The engineer's conventions ({conventions_name})

These are the engineer's standing preferences, written once and reused
across every show.

{conventions}"""

    if not instructions:
        return base

    return f"""{base}

---

# Instructions for THIS show ({instructions_name})

Show-specific instructions, written for this input list alone.

**Where these two disagree, this section wins.** The conventions above
are the default; anything restated here replaces it for this show. Where
this section is silent, the conventions above still apply in full.

{instructions}"""


def generator_user(conventions: str, input_csv: str, *, conventions_name: str, input_name: str,
                   instructions: str | None = None,
                   instructions_name: str | None = None,
                   resolved: str | None = None, resolved_name: str | None = None,
                   category_table=None, instructed_strips=None) -> str:
    # With the resolved conventions, the domain knowledge is not sent: the
    # part of it these conventions need is restated in the resolved text.
    domain = "" if resolved else f"""# Domain knowledge

{_domain_knowledge()}

---

"""
    return f"""\
{domain}{_conventions_section(conventions, conventions_name, instructions, instructions_name,
                      resolved, resolved_name,
                      _code_notes(category_table, instructed_strips, input_csv)
                      if resolved else None)}

---

# The input list for this show ({input_name})

```csv
{input_csv}
```

---

Lay out this show. Emit the plan JSON and nothing else."""


def _plan_for_prompt(plan: dict) -> dict:
    """`plan`, with `meta.build_log` left out -- the one field of the plan
    that must never reach a model. It is the model's OWN earlier thinking-summary lines, kept
    for a human reviewing a batch of builds later; feeding them back
    would prime a later call with the wording of an earlier one's
    reasoning, which is not what a fresh critic or watchlist pass is for.
    A shallow copy of `plan` and of `meta` -- neither is mutated -- is
    enough, since `build_log` is the only key removed."""
    if not isinstance(plan.get("meta"), dict) or "build_log" not in plan["meta"]:
        return plan
    out = dict(plan)
    meta = dict(plan["meta"])
    del meta["build_log"]
    out["meta"] = meta
    return out


def _with_starting_levels(entry: object) -> object:
    """One plan entry with its `fader` block's unstated fields filled in
    with what `apply` leaves the strip at: unity, unmuted
    (`console_facts.FADER_DEFAULT_DB`, `MUTED_DEFAULT`). An entry with no
    `fader` key (a plan older than the field) is returned as it is."""
    if not isinstance(entry, dict) or "fader" not in entry:
        return entry
    fader = entry["fader"] if isinstance(entry["fader"], dict) else {}
    out = dict(entry)
    out["fader"] = {
        **fader,
        "fader_db": facts.FADER_DEFAULT_DB if fader.get("fader_db") is None else fader["fader_db"],
        "muted": facts.MUTED_DEFAULT if fader.get("muted") is None else fader["muted"],
    }
    return out


def _plan_for_critic(plan: dict) -> dict:
    """The plan as the critic reads it: `_plan_for_prompt`, with every
    strip's starting level and mute shown as the desk will actually hold
    them.

    A null `muted` reads to a model as "nothing was decided", so handed
    one next to a convention that says "unmuted" it asks the engineer to
    worry about a strip that `apply` leaves unmuted anyway. The fields the
    format settles by a default are therefore resolved here, in code, from
    the same constants `apply` writes, and the review is of what the desk
    will hold. A convention the default does not satisfy ("start muted",
    "faders all the way down") still reads as a mismatch against the
    resolved value.
    Everything else the plan leaves null stays null: a colour, an icon, a
    filter, a gain, a preset have no default that satisfies a convention."""
    out = dict(_plan_for_prompt(plan))
    if isinstance(out.get("channels"), list):
        out["channels"] = [_with_starting_levels(c) for c in out["channels"]]
    for section in ("busses", "dcas", "outputs"):
        if isinstance(out.get(section), dict):
            out[section] = {name: _with_starting_levels(entry)
                            for name, entry in out[section].items()}
    return out


def critic_user(conventions: str, input_csv: str, plan: dict, *,
                conventions_name: str, input_name: str,
                instructions: str | None = None,
                instructions_name: str | None = None) -> str:
    return f"""\
# Domain knowledge

{_domain_knowledge()}

---

{_conventions_section(conventions, conventions_name, instructions, instructions_name)}

---

# The input list for this show ({input_name})

```csv
{input_csv}
```

---

# The plan to review

```json
{json.dumps(_plan_for_critic(plan), indent=None)}
```

---

Review it. Emit the findings JSON and nothing else."""


# ---------------------------------------------------------------------------
# the two passes
# ---------------------------------------------------------------------------

# One thing the critic pass says is wrong with a plan.
#
# Never blocks an apply on its own: a critic is a model, and the whole
# point is that only deterministic code gates the console. These are for
# the human reading the plan.
#
# The canonical `Diagnostic`, not a fifth private shape. The
# critic's `kind` (omission | intent | invention | contradiction) becomes
# the stable `code` -- "critic.omission" -- which is what this type was
# missing and what a UI filters on. `source="critic"` is what keeps a
# model's opinion visibly distinct from a deterministic finding when both
# are rendered into the same list.
CriticFinding = Diagnostic

#
# `conventions` (FR-6.2, 2026-09-25) is the one kind about the conventions
# TEXT rather than the plan: two statements that disagree with nothing to
# settle them, or something declared that nothing uses. It must quote the
# lines it is about, and `parse_critic_findings` checks each quote is
# really in the conventions or instructions (`conventions_audit.py`) --
# a quote that is not there is downgraded to INFO and says so. It is also
# the kind `info` severity was added to the critic for: "a reasonable
# choice was made", per the judgement-vs-patching rule.
CRITIC_KINDS = ("omission", "intent", "invention", "contradiction", "conventions")


# The plan's top-level keys, used to tell a safe end-of-document repair
# from one that would silently re-nest half the document. From the schema,
# so adding a section cannot leave this behind.
PLAN_TOP_LEVEL = plan_schema.TOP_LEVEL_KEYS


def _json_fragment(raw: str) -> str:
    """The outermost {...} span of a reply, fences and chatter removed."""
    start = raw.find("{")
    end = raw.rfind("}")
    return raw[start:end + 1] if start != -1 and end > start else raw


# The two top-level fields this format asks a generator (never the
# compiler) to fill with "nothing to say" as often as with real content.
_STRING_ARRAY_FIELDS = ("unassigned_inputs", "notes")


def _coerce_string_array_fields(plan: dict) -> list[str]:
    """An unconstrained local model sometimes writes a bare string where
    `notes`/`unassigned_inputs` want an array -- "" for nothing to report
    rather than [], or one string instead of a one-element list. Constrained decoding is the actual guard against this, and
    --no-constrain is the thing that turns it off; without some tolerance
    here that flag just trades an hour-long grammar-slowed run for an
    instant, equally useless schema-violation report. The meaning is
    unambiguous either way, so this fixes it up rather than rejecting it.
    """
    fixes: list[str] = []
    for key in _STRING_ARRAY_FIELDS:
        value = plan.get(key)
        if isinstance(value, str):
            plan[key] = [value] if value.strip() else []
            fixes.append(f"'{key}' was a string, not an array of strings -- wrapped it")
    return fixes


def _tag_model_notes(plan: dict) -> None:
    """Give every entry the model itself wrote in `notes` its provenance
    tag: `{"text": ..., "source": "model"}`, so a reader can
    tell it apart from this project's own repair/allocation notes (tagged
    below, at the point they're created) and from an extraction pass's
    (rules.py). The prompt and GENERATION_SCHEMA both ask the model to
    write this shape directly, with "source" always the literal "model" --
    but a model decoding unconstrained (--no-constrain, or a provider with
    no portable way to constrain it) is not guaranteed to comply, the same
    tolerance an earlier change already needed for `notes` being a bare string
    instead of an array at all. An entry already in the tagged shape is
    left alone; this only upgrades a plain string.

    Called after `_coerce_string_array_fields` (which only fixes `notes`
    itself not being a list) and before schema validation, which is where
    the object shape becomes mandatory."""
    plan["notes"] = [
        n if isinstance(n, dict) else {"text": str(n), "source": "model"}
        for n in plan.get("notes") or []
    ]


class GenerationError(RuntimeError):
    """The model answered but the answer could not be used as a plan.

    Distinct from AIProviderError (no answer at all) for the same reason
    extract.ExtractionError is: they are failures at different layers and
    want different responses from the caller.

    `partial_text` carries whatever there was to look at when this was
    raised -- the raw reply if it never became usable JSON, or the
    parsed-but-schema-invalid plan if it did. Same reasoning as
    AIProviderError's own `partial_text`: a generation can
    cost real money and 40+ minutes, and the failed attempt is the only
    evidence of why. cli.py's existing partial-preservation branch reads
    this attribute generically off any exception, so no caller change is
    needed for it to start saving these too.

    `reply` is the model's reply exactly as it arrived, whenever there was
    one -- what a fix-up round (`fixup_plan`) sends back to the model with
    this error's message. Empty when the failure was not the reply's."""

    def __init__(self, *args, partial_text: str = "", reply: str = ""):
        super().__init__(*args)
        self.partial_text = partial_text
        self.reply = reply


def generate_plan(
    conventions: str,
    input_csv: str,
    *,
    provider: AIProvider,
    conventions_name: str = "<conventions>",
    input_name: str = "<input list>",
    instructions: str | None = None,
    instructions_name: str | None = None,
    constrain: bool = True,
    console_model: str | None = None,
    findings: list | None = None,
    replies: list | None = None,
    resolved: str | None = None,
    resolved_name: str | None = None,
    category_table=None,
    instructed_strips=None,
) -> dict:
    """Conventions + input list + domain knowledge -> a plan.

    The input list is present *here*, which is the point. Today's extractor
    runs before the input list is a factor, so "band, excluding drums"
    has nothing to resolve against -- the list is what defines "band".

    `findings`, when given, collects the INFO diagnostics of what code
    derived on the model's behalf while expanding its reply
    (`reply_expand`): the next free socket it chose, a colour applied
    from the category map. `build` folds them into `meta.build_findings`.

    `replies`, when given, collects the model's reply text as it arrived:
    what a fix-up round (`fixup_plan`) sends back when verify refuses the
    plan. The compact reply, not the expanded plan, because it is the
    smaller of the two and it is the thing the model is asked to rewrite.

    `resolved` (with `resolved_name`) is the resolved conventions text
    (`conventions_resolve.py`): the generator reads it in place of the
    raw conventions and the domain knowledge, and a quote of it is
    accepted wherever a conventions quote is checked.

    `category_table` (a checked `category_table.Table`, with `resolved`)
    is applied by code to every channel by its input-list category, and
    the generator is told so (`_category_note`).

    `instructed_strips` (the resolved file's checked Instructed strips,
    `instructed_channels.Strip`, with `resolved`) are built by code after
    the reply is expanded -- the strips the conventions ask for that are
    not input-list rows (2026-10-01) -- and the generator is told so
    (`instructed_channels.strips_prompt_note`), so it builds none.
    """
    raw = provider.complete(
        system=generator_system(console_model),
        user=generator_user(conventions, input_csv,
                            instructions=instructions,
                            instructions_name=instructions_name,
                            conventions_name=conventions_name, input_name=input_name,
                            resolved=resolved, resolved_name=resolved_name,
                            category_table=category_table,
                            instructed_strips=instructed_strips),
        # Where the provider supports it this makes a malformed or
        # off-schema reply impossible, rather than asking nicely. It does
        # not make the plan correct -- verify_plan still decides that.
        # The REPLY schema, not the plan's: it is what the model is asked
        # to write, and -- unlike the plan's name-keyed maps -- it can be
        # sent to Anthropic's decoder (`reply_expand`).
        response_schema=plan_schema.REPLY_SCHEMA if constrain else None,
        label="generator",
    )
    if replies is not None:
        replies.append(raw)
    return plan_from_reply(raw, input_csv=input_csv, console_model=console_model,
                           findings=findings, conventions=conventions,
                           conventions_name=conventions_name, instructions=instructions,
                           instructions_name=instructions_name,
                           resolved=resolved, resolved_name=resolved_name,
                           category_table=category_table,
                           instructed_strips=instructed_strips)


def plan_from_reply(raw: str, *, input_csv: str, console_model: str | None = None,
                    findings: list | None = None, conventions: str | None = None,
                    conventions_name: str | None = None, instructions: str | None = None,
                    instructions_name: str | None = None, resolved: str | None = None,
                    resolved_name: str | None = None, category_table=None,
                    instructed_strips=None) -> dict:
    """One model reply -> a plan: parse (and end-of-document repair),
    repair and expand the reply, normalise, validate against the plan
    format, allocate, decide the unstated. Raises `GenerationError`, with
    `reply` set to `raw`, when the reply cannot be used.

    Split out of `generate_plan` so a fix-up round's reply (`fixup_plan`)
    goes through exactly the same pipeline as the first reply did -- one
    function, so the two cannot drift."""
    try:
        plan = _extract_json_object(raw)
        repairs: list[str] = []
    except Exception:  # noqa: BLE001
        # A whole generation can cost 40+ minutes on a local model. If the
        # only thing wrong is an unclosed structure at the very end, close
        # it rather than throw the run away -- but see json_repair: a
        # repair that would move an expected top-level key is refused,
        # because a brace missing in the MIDDLE cannot be fixed from the
        # end and the result would be confidently wrong.
        try:
            plan, repairs = loads_with_repair(_json_fragment(raw), expect_keys=PLAN_TOP_LEVEL)
        except Exception as exc:  # noqa: BLE001
            raise GenerationError(
                f"the model's reply did not contain a usable plan: {exc}",
                partial_text=raw, reply=raw,
            ) from exc

    # The reply is shorter than the plan: omitted fields, arrays for the name-keyed maps, and
    # the parts that are arithmetic left to code. Expanded here, before
    # anything below reads it as a plan; an older full-format reply passes
    # through unchanged.
    try:
        # The conventions and instructions go with it: a channel they ask
        # for that is not on the input list is built only when it quotes a
        # line of them stating its socket (`instructed_channels.py`).
        layers = instructed_channels.layers_from_texts(conventions, conventions_name,
                                                       instructions, instructions_name,
                                                       resolved=resolved,
                                                       resolved_name=resolved_name)
        repairs.extend(reply_expand.expand(
            plan, input_csv=input_csv, findings=findings, console_model=console_model,
            layers=layers, category_table=category_table if resolved else None,
            strips=instructed_strips if resolved else None))
    except reply_expand.ReplyError as exc:
        raise GenerationError(str(exc), partial_text=json.dumps(plan, indent=2),
                              reply=raw) from exc

    # An output's and a bus destination's `socket`/`sockets`
    # are `patch`/`patches` now, and the schema asks for the new names. A
    # model that reached for the old ones (an unconstrained provider, a
    # prompt it half-remembers) meant the same thing -- so the plan is
    # written with the new names either way, never refused for it.
    plan = plan_compat.normalise_plan(plan)
    repairs.extend(_coerce_string_array_fields(plan))
    _tag_model_notes(plan)
    # The same courtesy for the generator's `inferred` markers: an entry
    # it wrote without a `by` is its own decision (`by: "model"`), told
    # apart from the fallback's below.
    inferred.tag_model_markers(plan)
    # And a marker naming a field its object has no such value for is
    # prose with nothing to announce -- dropped, and said so, rather than
    # refusing the build (Haiku 4.5's `outputs.Main.inferred`, 2026-09-28).
    repairs.extend(inferred.drop_unmarkable(plan))

    # Validate locally, ALWAYS -- not only when the provider could not
    # constrain decoding. Three paths reach here unconstrained: the
    # OpenAI-compatible provider (which has no portable way to do it),
    # --no-constrain, and any future provider. Trusting the decoder alone
    # would mean the one case that needs checking is the one not checked.
    violations = validate_schema(plan, plan_schema.GENERATION_SCHEMA)
    if violations:
        shown = "\n  ".join(violations[:10])
        more = f"\n  ...and {len(violations) - 10} more" if len(violations) > 10 else ""
        raise GenerationError(
            f"the model's plan does not match the plan format:\n  {shown}{more}",
            partial_text=json.dumps(plan, indent=2), reply=raw,
        )

    # Name-based plan, number-based console. apply needs an index for every
    # DCA, mute group and bus, and allocation is code's job (D11) -- a
    # model asked for it could duplicate one or exceed the console. Tagged
    # "allocation": this is Atoo's own bookkeeping, not
    # something the model said.
    plan.setdefault("notes", []).extend(
        {"text": n, "source": "allocation"}
        for n in allocate_console_indices(plan, console_model=console_model))

    # An error of judgement is not an error of patching: a bus
    # width or send mode the model still left null -- against the prompt,
    # which asks it to decide and mark them -- is decided here by the
    # deterministic fallback and marked `by: "fallback"`, so the plan ON
    # DISK carries the value the desk will be set to. verify_plan turns
    # every marker into an INFO; apply and amend decide the same way for a
    # plan written before this existed (`inferred.with_decisions`).
    inferred.decide_unstated(plan)

    # Record which console this plan was built for, so verifying
    # it later -- by someone who wasn't here, from a file, without the flag
    # -- checks it against the same panel it was allocated against rather
    # than against whatever the next caller happens to assume.
    plan.setdefault("meta", {})["console_model"] = console_model

    if repairs:
        # Surfaced, never silent: the plan's own notes are read by whoever
        # reviews it, and verification still runs over the result. Tagged
        # "repair": these describe what json_repair or
        # _coerce_string_array_fields did to the model's raw reply, not
        # something the model itself said.
        plan.setdefault("notes", []).extend(
            {"text": r, "source": "repair"} for r in repairs)
    return plan


# ---------------------------------------------------------------------------
# the fix-up round
# ---------------------------------------------------------------------------

# When a generated plan fails verify
# with ERRORS -- or the reply fails the format check -- the reply and the
# exact error messages go back to the same model ONCE, for a corrected
# reply. Exactly one round, never a loop: a model that cannot mend a
# named error when shown it will not mend it on the fifth try either, and
# every round costs a generator-sized reply. 0 turns it off.
FIXUP_ROUNDS_ENV = "ATOO_AI_FIXUP_ROUNDS"
FIXUP_ROUNDS_DEFAULT = 1


def fixup_rounds(env=None) -> int:
    """How many fix-up rounds a build may spend: 0 or 1.

    `ATOO_AI_FIXUP_ROUNDS`, default 1. A value that will not parse
    is said and ignored (the default stands), as `cli._env_number` does
    for the console settings; a number above 1 is read as 1 and said so,
    because one round is the design, not a floor."""
    env = os.environ if env is None else env
    raw = str(env.get(FIXUP_ROUNDS_ENV, "") or "").strip()
    if not raw:
        return FIXUP_ROUNDS_DEFAULT
    try:
        n = int(raw)
    except ValueError:
        print(f"{FIXUP_ROUNDS_ENV}={raw!r} is not a whole number -- ignoring it "
              f"({FIXUP_ROUNDS_DEFAULT} fix-up round)", file=sys.stderr)
        return FIXUP_ROUNDS_DEFAULT
    if n > 1:
        print(f"{FIXUP_ROUNDS_ENV}={n}: a build spends at most one fix-up round, "
              "so it is read as 1", file=sys.stderr)
        return 1
    return max(0, n)


def verify_error_lines(verdict) -> list[str]:
    """Verify's ERRORS, one line each, as the fix-up sends them:
    "channels[BassDI].dca: joins DCA 'Band', which the plan never declares
    (reference.dangling)". Warnings and notes are not errors and are never
    sent: they do not stop an apply, and a model asked to "fix" a judgement
    call would only trade one for another."""
    return [f"{d.where}: {d.message} ({d.code})" if d.where else f"{d.message} ({d.code})"
            for d in verdict.errors]


# Verify WARNINGS that go back to the fix-up with its errors. Not
# judgement calls: a strip whose audio reaches no output is a strip nobody
# hears, and on Haiku (smallband, 2026-09-29: the Playback aux sent
# nowhere) it is a routing slip the model mends when it is shown it. A
# plan with only this warning spends the round too. Anything else a
# warning says stays out: the model would only trade one judgement for
# another.
FIXUP_WARNING_CODES = ("routing.channel-reaches-nothing",)


def fixup_warning_lines(verdict) -> list[str]:
    """Verify's warnings in `FIXUP_WARNING_CODES`, one line each, marked as
    warnings so the model knows it may leave one that is meant."""
    return [(f"{d.where}: " if d.where else "") + f"{d.message} ({d.code}; a warning, not a "
            "refusal)" for d in verdict.warnings if d.code in FIXUP_WARNING_CODES]


def fixup_system(console_model: str | None) -> str:
    """The generator's own system prompt, then `plan_fixup.md`.

    The generator's in full, because the corrected reply is held to the
    same format and the same rules as the first -- a fix-up that did not
    know the reply format would write something else. The appendix is
    what is different about this call: here is your reply, here is what
    was refused, return the whole reply, change only what the errors
    require."""
    return (generator_system(console_model) + "\n\n---\n\n"
            + load_prompt("plan_fixup.md"))


def _compact_reply(reply: str) -> str:
    """The reply as the fix-up shows it: re-serialised without whitespace
    when it parses, so an indented reply costs no more than a compact one;
    as it arrived when it does not (the format failure it is being asked
    to mend may be exactly that)."""
    try:
        return json.dumps(_extract_json_object(reply), separators=(",", ":"),
                          ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return _json_fragment(reply).strip()


def fixup_user(conventions: str, input_csv: str, reply: str, errors: list[str], *,
               checker: str, conventions_name: str, input_name: str,
               instructions: str | None = None,
               instructions_name: str | None = None,
               resolved: str | None = None, resolved_name: str | None = None,
               category_table=None, instructed_strips=None) -> str:
    """The fix-up call's user message: the conventions and instructions
    and the input list, as the generator saw them (without the domain
    knowledge, which is about audio, not about these errors; the resolved
    conventions in place of the raw file when the generator read them),
    then the model's own reply and what `checker` refused in it."""
    listed = "\n".join(f"- {e}" for e in errors)
    return f"""\
{_conventions_section(conventions, conventions_name, instructions, instructions_name,
                      resolved, resolved_name,
                      _code_notes(category_table, instructed_strips, input_csv)
                      if resolved else None)}

---

# The input list for this show ({input_name})

```csv
{input_csv}
```

---

# Your reply

```json
{_compact_reply(reply)}
```

---

# What {checker} found in it

{listed}

---

Return the whole corrected reply. Emit the reply JSON and nothing else."""


def fixup_plan(
    conventions: str,
    input_csv: str,
    reply: str,
    errors: list[str],
    *,
    provider: AIProvider,
    checker: str = "verify",
    conventions_name: str = "<conventions>",
    input_name: str = "<input list>",
    instructions: str | None = None,
    instructions_name: str | None = None,
    constrain: bool = True,
    console_model: str | None = None,
    findings: list | None = None,
    replies: list | None = None,
    resolved: str | None = None,
    resolved_name: str | None = None,
    category_table=None,
    instructed_strips=None,
) -> dict:
    """One fix-up round: `reply` and the `errors` `checker` found in it go
    back to the generator's model, as its own role `fixup` (so the build
    log, `lessons` and the Setup UI's call chips show it with its own
    usage and cost), and the corrected reply goes through the same
    pipeline as the first (`plan_from_reply`).

    The model returns the WHOLE corrected reply, not a patch: the compact
    reply is already the smallest whole form of the plan, the pipeline
    that checks a reply is the one that exists, and a patch format would
    be a new thing for the model to get wrong and for code to apply.

    Raises what `generate_plan` raises: `AIProviderError` (no answer),
    `GenerationError` (an answer that is not a usable plan), and
    `BuildStopped` when the person stops the build during the call."""
    raw = provider.complete(
        system=fixup_system(console_model),
        user=fixup_user(conventions, input_csv, reply, errors, checker=checker,
                        conventions_name=conventions_name, input_name=input_name,
                        instructions=instructions, instructions_name=instructions_name,
                        resolved=resolved, resolved_name=resolved_name,
                        category_table=category_table,
                        instructed_strips=instructed_strips),
        response_schema=plan_schema.REPLY_SCHEMA if constrain else None,
        label="fixup",
    )
    if replies is not None:
        replies.append(raw)
    return plan_from_reply(raw, input_csv=input_csv, console_model=console_model,
                           findings=findings, conventions=conventions,
                           conventions_name=conventions_name, instructions=instructions,
                           instructions_name=instructions_name,
                           resolved=resolved, resolved_name=resolved_name,
                           category_table=category_table,
                           instructed_strips=instructed_strips)


def critique_plan(
    conventions: str,
    input_csv: str,
    plan: dict,
    *,
    provider: AIProvider,
    conventions_name: str = "<conventions>",
    input_name: str = "<input list>",
    instructions: str | None = None,
    instructions_name: str | None = None,
) -> list[CriticFinding]:
    """A second model pass, in a separate role, over a plan it did not write.

    Defence in depth against the one failure mode that review cannot catch:
    an input that silently became no channel. The deterministic verifier
    checks that exactly, in `_check_reconciliation`; this catches the softer
    version -- a rule in the conventions that the plan quietly did not
    follow, which no deterministic check can see.

    Separate call and separate role on purpose, so it is not defending its
    own work. A critic that fails never stops the build -- but it says so:
    "no findings" and "never ran" are the same empty list and opposite
    facts, and a silent failure reads as a clean bill of health from a pass
    that did not happen.
    """
    try:
        raw = provider.complete(
            system=critic_system(),
            user=critic_user(conventions, input_csv, plan,
                             instructions=instructions,
                             instructions_name=instructions_name,
                             conventions_name=conventions_name, input_name=input_name),
            label="critic",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"critic pass did not run: {exc}", file=sys.stderr)
        return []

    try:
        out = parse_critic_findings(
            raw, layers=conventions_audit.layers_for(
                conventions, conventions_name, instructions, instructions_name))
    except Exception as exc:  # noqa: BLE001
        print(f"critic pass replied, but not with findings JSON ({exc}). "
              f"First 200 characters: {raw[:200]!r}", file=sys.stderr)
        return []

    if not out:
        print("critic pass ran and found nothing.", file=sys.stderr)
    return out


def _critic_claim(claim: object) -> str:
    """The critic's `claim`, on one line: whitespace collapsed, a trailing
    full stop dropped (it is a headline). Anything but a string is no
    claim."""
    if not isinstance(claim, str):
        return ""
    return " ".join(claim.split()).rstrip(".")


def parse_critic_findings(raw: str, *,
                          layers: "list[conventions_audit.Layer] | None" = None,
                          ) -> list[CriticFinding]:
    """One model reply -> `CriticFinding`s, or a raised exception.

    Split out of `critique_plan` so that a harness which calls the
    provider itself -- a timing harness that times the critic
    pass separately and archives its raw reply -- does not have to repeat
    the severity coercion, and cannot drift from it. `critique_plan`
    swallows every failure and returns `[]`; this raises, which is what
    lets a caller tell "ran and found nothing" from "never ran".

    `layers` is the conventions text the plan was built from. When given,
    a `conventions` finding's `quotes` are checked against it
    (`conventions_audit.check_critic_finding`): all found keeps the
    finding and names its section; any not found downgrades it to INFO,
    saying so. Without it (a harness with no text to hand) the finding is
    passed through unchecked.
    """
    findings = _extract_json_object(raw).get("findings", [])
    out: list[CriticFinding] = []

    def _critic_severity(severity: str) -> "diagnostics.Severity":
        # The critic is a model reading the plan; whether the desk CAN work
        # is code's call (verify), so the critic's worst is WARNING
        # (a "confirm LCL 20/22 are wired" note once came
        # back as ERROR). It never blocked an apply -- it only looked as if
        # it did.
        if severity not in tuple(s.value for s in diagnostics.Severity):
            return diagnostics.Severity.WARNING
        coerced = diagnostics.coerce_severity(severity)
        return diagnostics.Severity.WARNING if coerced == diagnostics.Severity.ERROR else coerced

    for f in findings:
        if not isinstance(f, dict):
            continue
        kind = str(f.get("kind", "unknown"))
        severity = str(f.get("severity", "warning"))
        finding = Diagnostic(
            # A model wrote this severity, so it is coerced rather than
            # trusted: anything it invents outside the vocabulary lands on
            # `warning`, which is the same "never blocks an apply"
            # treatment the whole critic stream already gets.
            severity=_critic_severity(severity),
            code=f"critic.{kind}",
            where=str(f.get("where", "?")),
            # The critic's one-line `claim` ("Keys bus created,
            # but there is only one keyboard") is the finding's `title`,
            # and `message` is the reasoning under it -- a 60-word
            # paragraph with the claim buried mid-way was the problem.
            # A reply without a claim still reads: `title` stays empty.
            title=_critic_claim(f.get("claim")),
            message=str(f.get("message", "")),
            category=kind,
            source="critic",
        )
        if kind == "conventions" and layers is not None:
            quotes = f.get("quotes")
            if isinstance(quotes, str):
                quotes = [quotes]
            finding = conventions_audit.check_critic_finding(
                finding, quotes if isinstance(quotes, list) else [], layers)
        out.append(finding)
    return out


def watchlist_system() -> str:
    # The vocabulary comes from watch_conditions itself rather than being
    # retyped here. The Watch editor (app.js then, watch.js now) kept its
    # own copy of this list and drifted from the Python side twice; a prompt is just as capable of telling a model about a
    # field the validator will then reject.
    from atoo import watch_conditions as wc

    return load_prompt(
        "watchlist_draft.md",
        fields=", ".join(f"`{f}`" for f in sorted(wc._ALLOWED_FIELDS)),
        operators=", ".join(f"`{o}`" for o in sorted(wc._OPERATORS)),
        severities=", ".join(f"`{s.value}`" for s in diagnostics.Severity),
    )


def watchlist_user(plan: dict, conventions: str, *, conventions_name: str,
                   instructions: str | None = None,
                   instructions_name: str | None = None) -> str:
    return f"""\
{_conventions_section(conventions, conventions_name, instructions, instructions_name)}

---

# The plan, already built and verified

```json
{json.dumps(_plan_for_prompt(plan), indent=None)}
```

---

Draft the watchlist for this show. Emit the JSON object and nothing else."""


def draft_watch_conditions(
    plan: dict,
    conventions: str,
    *,
    provider: AIProvider,
    conventions_name: str = "<conventions>",
    instructions: str | None = None,
    instructions_name: str | None = None,
) -> list[dict] | None:
    """Propose a watchlist for a plan that has already been built.

    A third pass, after generate and critic, asking a different question
    from either: not "is this plan right" but "what, on this show, is worth
    an alert if it moves".

    **Never fails a build.** A plan that built fine plus a watchlist that
    did not draft is a warning, not a non-zero exit -- the plan is the
    deliverable and the watchlist is a convenience. Every failure path here
    prints why and returns None, which the caller distinguishes from `[]`
    ("ran, and this show warrants nothing"), the same "no findings and never
    ran are opposite facts" split `critique_plan` makes.

    **Nothing reaches disk unvalidated.** Every drafted condition goes
    through `_validate_condition` -- the same deterministic check that
    guards a hand-written file -- so this adds no new trust boundary (D11).
    A condition with an invented field or severity is
    rejected here, not written out and discovered mid-show. It is rejected ALONE (`salvage_drafted_conditions`): a key no
    condition has is dropped, a condition still unusable is left out,
    and each is said at INFO; the rest of the draft is kept.
    """
    from atoo.watch_conditions import WatchConditionsError, salvage_drafted_conditions

    try:
        raw = provider.complete(
            system=watchlist_system(),
            user=watchlist_user(plan, conventions, conventions_name=conventions_name,
                                instructions=instructions, instructions_name=instructions_name),
            label="watchlist",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"watch-conditions draft did not run: {exc}", file=sys.stderr)
        return None

    try:
        document = _extract_json_object(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"watch-conditions draft replied, but not with JSON ({exc}). "
              f"First 200 characters: {raw[:200]!r}", file=sys.stderr)
        return None

    try:
        # Each condition held to the standard a hand-written file is, by
        # the same function; what fails is left out ALONE.
        conditions, notes = salvage_drafted_conditions(document, source="<watch-conditions draft>")
    except WatchConditionsError as exc:
        print(f"watch-conditions draft was not usable, so none was written: {exc} -- "
              "watch.json is kept as it was", file=sys.stderr)
        return None
    for note in notes:
        print(f"INFO watch-conditions draft: {note}", file=sys.stderr)
    if not conditions and document["watch_conditions"]:
        # Every condition refused: that is "no usable draft" (None), not
        # "ran and proposed nothing" ([]).
        print(f"watch-conditions draft was not usable: none of its "
              f"{len(document['watch_conditions'])} condition(s) could be used, so none was "
              "written -- watch.json is kept as it was", file=sys.stderr)
        return None
    return conditions
