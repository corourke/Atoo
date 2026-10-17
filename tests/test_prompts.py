"""Prompts are files you edit, not Python constants you patch.

The loop this serves: change a prompt, re-run, compare. If that requires
editing a .py file, keeping a branch, or remembering which constant held
which paragraph, it does not happen often enough to be useful.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from atoo import generate

PROMPTS = Path(generate.__file__).parent / "prompts"


def test_both_prompts_load_and_nothing_is_left_unfilled():
    """An unfilled `{console}` reaching the model is a prompt that says
    nothing about the console, and the resulting bad plan would look like
    a model failure rather than a plumbing one."""
    for text in (generate.generator_system("wing-compact"), generate.critic_system()):
        assert text.strip()
        assert re.findall(r"\{[A-Za-z_]+\}", text) == []


def test_the_console_facts_are_generated_not_typed():
    """The generator prompt and the verifier must agree on the hardware.
    They do so by construction: the prompt's console section is rendered
    from console_facts, the same module verify_plan enforces."""
    from atoo import console_facts as facts

    prompt = generate.generator_system("wing-compact")
    assert f"LCL (Local / LCL) 1-{facts.INPUT_SOCKETS['LCL']}" in prompt
    assert str(facts.CAPACITY["ch"]) in prompt
    # ...and the file on disk must NOT contain them, or they can drift
    raw = (PROMPTS / "plan_generation.md").read_text()
    assert "{console}" in raw
    assert "LCL (Local / LCL) 1-24" not in raw


def test_the_editor_note_is_not_sent_to_the_model():
    raw = (PROMPTS / "plan_generation.md").read_text()
    assert raw.lstrip().startswith("<!--")
    assert "<!--" not in generate.generator_system("wing-compact")
    assert "THIS FILE IS PROSE" not in generate.generator_system("wing-compact")


def test_the_whole_editor_note_is_stripped_not_just_its_first_half():
    """The note quotes `<!-- ... -->` mid-sentence, and until 2026-09-28
    the stripper stopped at that quoted `-->`: the rest of the note, and a
    bare `-->`, opened every generator prompt. The rendered prompt must
    begin with the prose, and nothing the note says may reach the model."""
    rendered = generate.generator_system("wing-compact")
    assert rendered.startswith("You lay out live-sound shows")
    assert "-->" not in rendered
    assert "INVENTED, on purpose" not in rendered


def _shingles(text: str, n: int = 6) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def test_the_prompt_does_not_quote_the_engineers_own_conventions():
    """Rules 4a and 4c used to illustrate themselves with sentences copied
    verbatim from an engineer's conventions file, and a build log showed
    the model stopping to work out why its prompt was quoting its own
    conventions back at it. The examples are invented now.

    This asserts on the SHIPPED prompt only; the conventions
    (`tests/fixtures/engineer-conventions.md`, a real engineer's file) are
    read as data and nothing about their contents is asserted."""
    conventions = Path(__file__).parent / "fixtures" / "engineer-conventions.md"
    shared = _shingles(generate.generator_system("wing-compact")) & _shingles(
        conventions.read_text())
    assert not shared, (
        "the generator prompt quotes the engineer's conventions verbatim: "
        + "; ".join(sorted(shared)))


def test_a_prompt_directory_can_be_swapped(tmp_path, monkeypatch):
    """The actual lever: a variant without a branch."""
    variant = tmp_path / "prompts"
    variant.mkdir()
    (variant / "plan_generation.md").write_text(
        "<!-- note -->\nBe extremely terse.\n\n{console}\n")
    (variant / "plan_critique.md").write_text("Find omissions.\n")

    monkeypatch.setenv("ATOO_PROMPT_DIR", str(variant))
    assert generate.generator_system("wing-compact").startswith("Be extremely terse.")
    assert "AES50-A" in generate.generator_system("wing-compact")   # still gets real facts
    assert generate.critic_system().strip() == "Find omissions."


def test_a_missing_prompt_file_says_which_one(tmp_path, monkeypatch):
    monkeypatch.setenv("ATOO_PROMPT_DIR", str(tmp_path))
    with pytest.raises(generate.PromptError, match="plan_generation.md"):
        generate.generator_system("wing-compact")


def test_an_unfillable_placeholder_is_refused(tmp_path, monkeypatch):
    """Silently shipping `{tempo}` to the model would be worse than
    stopping: the prompt would read as gibberish at exactly one point and
    nothing would say why."""
    variant = tmp_path / "prompts"
    variant.mkdir()
    (variant / "plan_generation.md").write_text("Lay out {tempo} shows.\n{console}\n")
    monkeypatch.setenv("ATOO_PROMPT_DIR", str(variant))

    with pytest.raises(generate.PromptError) as exc:
        generate.generator_system("wing-compact")
    assert "tempo" in str(exc.value)
    assert "console" in str(exc.value)      # names what WAS available


def test_the_shipped_prompts_still_say_the_things_that_matter():
    """Guard rails against an edit that quietly drops a rule the rest of
    the pipeline depends on."""
    gen = generate.generator_system("wing-compact")
    for essential in (
        "unassigned_inputs",        # the omission contract
        "match an input list row",  # the invention contract
        "provenance",               # why each decision was made
        "16 characters",            # the console's name limit
    ):
        assert essential in gen, f"the generator prompt no longer mentions {essential!r}"

    crit = generate.critic_system()
    assert "OMISSIONS FIRST" in crit
    assert "findings" in crit


def test_socket_groups_are_named_the_way_an_input_list_spells_them():
    """A bare group list of "A, AES, B, C" against an input list that says
    "AES50-A 1" invites reading the group as "AES" -- which exists (AES/EBU,
    2 sockets) and is wrong. qwen2.5:14b made exactly that substitution on
    all 19 channels of touringband; the verifier caught every one, but the
    prompt had never given it what it needed."""
    prompt = generate.generator_system("wing-compact")
    assert "A (AES50-A)" in prompt
    assert "AES (AES/EBU)" in prompt


def test_the_module_bay_is_named_in_the_prompt_now_that_it_is_known():
    """An earlier change, settled 2026-09-21. `MOD` was rendered bare while its identity
    was unconfirmed, because a guessed label in this prompt becomes a
    guessed patch. It is confirmed now -- the AoIP module bay, a different
    slot from the expansion card (PDF pp.10/256, `/$syscfg.opt_mod`) -- so
    the model is told, the same way it is told what CRD is. The two must
    stay distinguishable: both are 64 sockets, and a prompt that names
    only one invites the substitution `test_socket_groups_are_named...`
    above is about."""
    prompt = generate.generator_system("wing-compact")
    assert "MOD (AoIP module: Dante/WSG)" in prompt
    assert "CRD (expansion card)" in prompt


def test_a_missing_domain_knowledge_file_raises_rather_than_substituting(monkeypatch, tmp_path):
    """The domain file is embedded in both prompts, so the old
    `(no domain knowledge file found)` fallback bought nothing: the run
    continued, laid out the whole show without the audio vocabulary, and
    the only sign was a parenthetical inside a prompt nobody reads at
    runtime. On a wheel install (where the file was genuinely absent until
    The package-data fix) that was every run."""
    monkeypatch.setattr(generate, "_DOMAIN", tmp_path / "gone" / "knowledge.md")
    for build in (
        lambda: generate.generator_user("conventions", "name\n", conventions_name="c.md", input_name="i.csv"),
        lambda: generate.critic_user("conventions", "name\n", {}, conventions_name="c.md", input_name="i.csv"),
    ):
        with pytest.raises(generate.PromptError) as exc:
            build()
        assert "knowledge.md" in str(exc.value)      # names the path it wanted
        assert "package-data" in str(exc.value)      # and why it might be absent


def test_the_domain_knowledge_reaches_both_prompts_verbatim():
    """The condition the test above protects: when the file IS there, its
    text is in the generator's input and the critic's, not summarised.
    It rides the USER message, not the system prompt -- which is why
    `generator_system()` would not have noticed it missing."""
    domain = (Path(generate.__file__).parent / "domain" / "knowledge.md").read_text()
    sample = next(line for line in domain.splitlines() if len(line.strip()) > 40)
    assert sample in generate.generator_user(
        "conventions", "name\n", conventions_name="c.md", input_name="i.csv")
    assert sample in generate.critic_user(
        "conventions", "name\n", {}, conventions_name="c.md", input_name="i.csv")


def test_the_prompt_teaches_the_panel_not_the_address_tree():
    """An earlier change, and this module's own contract: "the numbers the model is
    told can never drift from the numbers the verifier enforces. If they
    could drift, a passing verify would stop meaning anything."

    The prompt used to render `console_facts.INPUT_SOCKETS` -- the OSC
    address space -- under the heading "Physical INPUT sockets that
    exist". On a Compact that advertised eight aux jacks the console does
    not have, so the model would patch them and the verifier would reject
    the result.
    """
    compact = generate.console_section("wing-compact")
    assert "WING Compact" in compact
    assert "AUX" not in compact.split("Value domains")[0].replace(
        "This console has NO AUX sockets at all", ""), (
        "a Compact has no local aux jacks -- the prompt must not offer them "
        "as patchable sockets"
    )
    assert "NO AUX sockets at all" in compact
    assert "24 inputs but only 8 outputs" in compact

    full = generate.console_section("wing-full")
    assert "full-size console" in full
    assert 'AUX (Aux In (1/4")) 1-8' in full, "a full-size WING really has them"
    assert "8 inputs but only 8 outputs" in full


def test_the_prompt_refuses_to_render_for_an_unknown_console():
    """Fails before a model call is spent, not after."""
    from atoo.console_facts import UnknownConsoleModel

    with pytest.raises(UnknownConsoleModel):
        generate.console_section("not-a-real-console")

def test_the_prompt_states_the_stereo_pairing_rule_the_verifier_enforces():
    """The verifier refuses a stereo pair that is not
    [odd, even] and consecutive; a prompt that does not say so lets the
    model produce one, and the plan is then rejected after a model call
    has been spent on it. Both read `console_facts.STEREO_PAIR_RULE`, so
    this asserts the wiring, not a copy of the words."""
    from atoo import console_facts as facts

    # An earlier change made the prompt per-model; the pairing rule is not (it is a
    # property of the desk's routing hardware), so it must appear for
    # every model rather than only the one this test happens to pick.
    for model in ("wing-compact", "wing-full", "wing-rack"):
        assert facts.STEREO_PAIR_RULE in generate.generator_system(model), model
    prompt = generate.generator_system("wing-compact")
    # ...and it must not be typed into the prompt file, where it could
    # drift away from the rule verify_plan applies.
    assert "must start on an" not in (PROMPTS / "plan_generation.md").read_text()


def test_the_prompts_spell_out_the_bus_width_tri_state():
    """`mono` is a nullable boolean, and null-vs-false is
    exactly the tri-state a model gets wrong. The old schema prose said
    only "state true only when the conventions explicitly ask for a mono
    bus", which gives a model no reason ever to write `false` and reads as
    "otherwise leave it null" -- so `examples/conventions.md`'s "These are
    stereo busses" reached both shipped plans as null, and "these will all
    be MONO busses" did too, which made them unapplicable.

    Cheap, and it runs on every suite. Whether the model then actually
    obeys is tests/test_prompt_fidelity.py, which costs a real model
    call and is skipped by default."""
    from atoo import plan_schema

    # The field's own three states live in the GENERATED schema prose, not
    # typed into the prompt file, so they cannot drift from the schema the
    # decoder and verify_plan share.
    schema = plan_schema.schema_section()
    # Since 2026-09-25 the third state is gone for this field: an unstated
    # width is DECIDED and marked, never null (the
    # judgement-vs-patching rule, rule 4b). What an earlier change was about -- a
    # stated false read as silence -- still has to be spelled out.
    assert "false is as stated as true" in schema
    assert "never\n                                      null (rule 4b)" in schema
    # ...and a width stated over a list governs the whole list, which is
    # how a conventions file actually says it.
    assert "A width in a HEADING applies to every bus" in " ".join(schema.split())

    # The prompt's own half: rule 4 tells the model to leave an unstated
    # value null, and nothing used to pull the other way.
    gen = generate.generator_system("wing-compact")
    assert "BUT A VALUE THE CONVENTIONS *DID* STATE MUST REACH THE PLAN" in gen
    assert "Null in that field is a CLAIM" in gen

    # The critic is the second chance to catch a dropped stated fact, and
    # a plan that left one null looks honest rather than wrong.
    crit = generate.critic_system()
    assert "A stated fact the plan left null belongs here" in crit
    assert "Check that they were." in crit


def test_rule_4_keeps_its_teeth_and_the_carve_out_is_named_and_narrow():
    """"An error of judgement is not an error of patching":
    a bus width, a send's pre/post, a mix bus's route to Main and a stereo
    pairing are DECIDED where the conventions are silent, and announced.
    Everything else keeps rule 4 -- null, never a plausible guess. Both
    halves have to survive an edit: a prompt that loses the carve-out
    blocks plans again, one that loses the limit starts inventing EQ."""
    gen = generate.generator_system("wing-compact")
    assert "DO NOT GUESS A VALUE THE CONVENTIONS DID NOT STATE" in gen
    assert "except the four in rule 4b" in gen
    assert "FOUR FIELDS ARE DECIDED, NEVER NULL -- AND EACH DECISION SAYS SO" in gen
    assert "This is the whole exception; no other field is decided this way." in gen
    # A socket is where a cable is: the carve-out never reaches it.
    assert "Never a physical socket" in gen
    # The marker the decision announces itself with, named where the
    # model reads the fields...
    from atoo import plan_schema
    schema = " ".join(plan_schema.schema_section().split())
    for field in ("mono", "mode", "stereo"):
        assert f'[{{"field": "{field}", "basis": "..."}}]' in schema, field
    # ...and the four fields the prompt names are the four the schema allows.
    assert set(sum(plan_schema.INFERABLE_FIELDS.values(), ())) == {
        "mono", "destination", "stereo", "mode"}

    # The knowledge file no longer teaches that a width is unknowable.
    assert "not inferable from what the bus is for" not in gen
    user = generate.generator_user("c", "name\nKick\n", conventions_name="c.md",
                                   input_name="i.csv")
    assert "the decision is said out loud" in user

    # The critic must not report a marked decision as an invention.
    crit = generate.critic_system()
    assert 'A decided value marked "inferred" is correct' in crit


def test_both_prompts_ask_for_the_conventions_audit_with_quotes():
    """FR-6.2, folded into the build. The generator reports conflicts and
    unused declarations in `conventions_audit`; the critic has a
    `conventions` kind and an `info` severity. Both must say that the
    instructions overriding the house file is NOT a conflict, and both
    must ask for verbatim quotes, which code then checks."""
    gen = generate.generator_system("wing-compact")
    assert '"conventions_audit"' in gen
    assert "Instructions overriding the house file is\n     the design, never a conflict" in gen
    assert "copied exactly from the text and are checked" in gen

    crit = generate.critic_system()
    assert '"conventions"' in crit and '"info"' in crit
    assert "overriding the house conventions is the design, NEVER a conflict" in crit
    assert '"quotes"' in crit
    assert "conventions" in generate.CRITIC_KINDS


def test_a_parenthetical_is_read_as_part_of_its_sentence_and_background_is_not_built():
    """"Let's at least instruct the AI to be wary of
    things in parentheses." The same file uses them for rules ("(L/R,
    Left/Right)", "(but not drums)", a compressor's settings) and for
    notes to himself ("(We will EQ this ...)"). The generator acts on the
    first kind, builds and asks nothing about the second, and says how it
    read one it could not place -- announced, never silent.
    The critic gets the matching sentence, so a background parenthetical
    is not reported as an unbuilt convention."""
    gen = " ".join(generate.generator_system("wing-compact").split())
    assert "A PARENTHETICAL IS PART OF ITS SENTENCE" in gen
    assert '"(L/R, Left/Right)" defines what counts as a pair' in gen
    assert '"(but not drums)" excludes channels' in gen
    assert "it is background: build nothing from it and ask nothing about it in \"notes\"" in gen
    assert "say in \"notes\" how you read it" in gen
    # Comments never reach the model, so the prompt does not talk about them.
    assert "<!--" not in gen

    crit = " ".join(generate.critic_system().split())
    assert "is background, not a convention the plan failed to build" in crit


def test_comments_in_the_conventions_never_reach_any_prompt():
    """`<!-- ... -->` is where the engineer keeps notes the build must not
    act on. `_conventions_section` is the one place
    every prompt embeds the conventions through -- generator, critic,
    watchlist -- so a comment in either layer reaches none of them."""
    house = "## Outputs\n- Main feeds Matrix 1. <!-- NOTE-HOUSE: EQ for the recording -->\n"
    show = "## Busses\n<!--\nNOTE-SHOW: ask the drummer\n-->\n- Four wedges.\n"
    rendered = [
        generate.generator_user(house, "name\nKick\n", conventions_name="c.md",
                                input_name="i.csv", instructions=show,
                                instructions_name="instructions.md"),
        generate.critic_user(house, "name\nKick\n", {}, conventions_name="c.md",
                             input_name="i.csv", instructions=show,
                             instructions_name="instructions.md"),
        generate.watchlist_user({}, house, conventions_name="c.md", instructions=show,
                                instructions_name="instructions.md"),
    ]
    for user in rendered:
        assert "NOTE-HOUSE" not in user and "NOTE-SHOW" not in user
        assert "- Main feeds Matrix 1.\n" in user
        assert "## Busses\n- Four wedges." in user


def test_what_the_format_settles_is_said_once_so_no_run_re_deliberates_it():
    """Build lessons, 2026-09-27 (docs/developer/build-lessons-2026-09-27.md).
    Two festival builds from identical inputs spent their thinking on the
    same questions, and the critic flagged two of them on both runs. Each
    is a fact about the desk or the format, not the engineer's taste, so
    it is stated where both models read it:

    - a head amp exists only on the physical mic/line inputs -- the
      generated console section names exactly `PHANTOM_CAPABLE_GROUPS`,
      the set apply writes `.g` to, and the knowledge file (which the
      critic also reads) says a digital source has none;
    - a listed send is applied switched ON, so "mute off" needs no field;
    - a one-row channel is mono by construction and carries no marker,
      which is what the Kick reference channel already does;
    - an input row with no socket is the generator's to place -- rule 4's
      never-guess list names OUTPUT sockets, not input ones.
    """
    from atoo import console_facts as facts
    from atoo import plan_schema

    gen = " ".join(generate.generator_system("wing-compact").split())
    groups = ", ".join(sorted(facts.PHANTOM_CAPABLE_GROUPS))
    assert f"and ONLY on {groups} sockets" in gen
    assert "gain_db stays null there" in gen

    user = " ".join(generate.generator_user(
        "c", "name\nKick\n", conventions_name="c.md", input_name="i.csv").split())
    assert "has no head amp and no phantom" in user
    crit = " ".join(generate.critic_system().split())
    assert "its `gain_db` is rightly null" in crit

    assert "A listed send is applied switched ON (unmuted)" in gen
    assert "applied switched on (unmuted)" in crit

    assert "A channel made from ONE input row is mono by construction" in gen
    example = plan_schema.EXAMPLE_CHANNEL
    assert example["source"]["stereo"] is False
    assert len(example["patch"]["sockets"]) == 1
    assert "inferred" not in example

    assert "A row with NO patch is yours to place" in gen
    assert "output sockets -- except the four in rule 4b" in gen
    assert "physical sockets -- except the four" not in gen


def test_the_knowledge_file_has_no_unfinished_line():
    """A dangling fragment in the knowledge file is sent to both models on
    every build and read as something to interpret."""
    text = (Path(generate.__file__).parent / "domain" / "knowledge.md").read_text()
    for paragraph in text.split("\n\n"):
        assert paragraph.count('"') % 2 == 0, f"unbalanced quote: {paragraph!r}"


def test_the_critic_is_told_its_two_haiku_false_positives_2026_09_29():
    """Haiku's festival critic reported 13 ERRORS that rows whose notes say
    'not patched for this event' were built -- the instructions say to
    ignore that note. Its smallband critic reported channels with no route
    to Main whose audio reaches Main through a mix bus, and kept doing so
    after being told how a channel reaches Main -- so routing moved to
    code (`routing.channel-misses-main`, the maintainer 2026-09-29) and the
    critic is told it is not its job."""
    crit = " ".join(generate.critic_system().split())
    assert "Both override the input list's notes." in crit
    assert "is correct, not an omission or an invention" in crit
    assert ("Whether channels and busses reach Main or an output is checked by code, "
            "so do not report on routing.") in crit


def test_the_critic_is_no_longer_asked_to_check_routing():
    """Routing is checked by code, not the critic.
    The prompt no longer explains how a channel reaches Main, nor lists
    routing among the rules to check or a bus feeding nothing among the
    contradictions -- and it is no larger than before the change (5558
    characters), plus the short `claim` field and the paragraph
    asking for it (5900 since 2026-10-11), plus the sentence that a
    preset taken for an unqualified instrument is not an invention (6000
    since 2026-10-13), plus the paragraph saying a strip's starting fader and
    mute are shown as the desk will hold them (6600)."""
    crit = " ".join(generate.critic_system().split())
    assert "A channel reaches Main by" not in crit
    assert "no route to Main" not in crit
    assert "Rules about routing" not in crit
    assert "a bus feeding nothing" not in crit
    assert len(generate.critic_system()) <= 6600


def test_the_change_prompt_chooses_an_unqualified_instruments_preset_and_says_so():
    """"sax" with presets for alto and baritone came back
    with no preset and a question ("Sax type ... not stated, so no preset
    was assigned"): a strip with none of its processing, against the
    INFO principle. The prompt the model is sent -- not just the file --
    tells it to take the most common kind and say so in `notes`, which
    `patch` prints at INFO, naming the alternative."""
    from atoo import patch as patch_engine

    prompt = patch_engine.change_system("wing-compact")
    assert "A PRESET IS CHOSEN, NEVER LEFT UNSET FOR WANT OF A QUALIFIER" in prompt
    assert "a sax with no qualifier is an alto (A Sax)" in prompt
    assert "say 'baritone sax' for B" in prompt
    # Rule 6's "stays null, with the question in notes" no longer covers it.
    assert "except a\n   preset, which rule 9 decides" in prompt


def test_the_build_prompt_chooses_an_unqualified_instruments_preset_and_says_so():
    """An earlier change, the build half. An input list row
    saying just "Sax", with presets in the conventions for alto and
    baritone, left `processing.preset` null under rule 4: a strip with none
    of its processing, against the INFO principle. The prompt the
    model is sent tells it to take the most common kind and say so in
    "notes", naming the alternative -- and rule 4 no longer covers it."""
    gen = generate.generator_system("wing-compact")
    assert "4d. A PRESET IS CHOSEN, NEVER LEFT UNSET FOR WANT OF A QUALIFIER" in gen
    assert "a sax with no qualifier is an alto\n   (A Sax)" in gen
    assert "'Baritone sax' for B Sax." in gen
    # A row that states its preset keeps it.
    assert "A row's own `preset` value (rule 3) wins." in gen
    # Rule 4 hands the preset to 4d rather than leaving it null...
    assert "except the four in rule 4b and a preset rule 4d\n   decides." in gen
    assert 'A preset has its own rule, 4d, announced in "notes" instead.' in gen
    # ...and the critic does not report the announced choice as invented.
    crit = " ".join(generate.critic_system().split())
    assert ('Nor a preset taken for an instrument named without its kind '
            '("Sax" as A Sax) that the notes announce.') in crit
