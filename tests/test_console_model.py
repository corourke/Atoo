"""The console model is a declared, load-bearing fact.

The socket counts that decide whether a plan is patchable differ between
the three WING models, and the OSC address tree does not -- it is identical
on all three, because they share a mainboard and firmware. So nothing can
infer the model from a walk; it has to be stated, or heard from the desk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atoo import console_facts as facts

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPanelCounts:
    """From `WING_Remote-Protocols-3.1-03.pdf` pp. 11-12, cross-checked
    against p.4's preamp count."""

    def test_the_full_size_wing_has_eight_local_inputs_and_aux_jacks(self):
        assert facts.input_socket_limit("LCL", "wing-full") == 8
        assert facts.input_socket_limit("AUX", "wing-full") == 8
        assert facts.output_socket_limit("AUX", "wing-full") == 8

    @pytest.mark.parametrize("model", ["wing-rack", "wing-compact"])
    def test_the_rack_and_compact_have_24_local_inputs_and_no_aux_jacks(self, model):
        assert facts.input_socket_limit("LCL", model) == 24
        assert facts.input_socket_limit("AUX", model) == 0
        assert facts.output_socket_limit("AUX", model) == 0

    @pytest.mark.parametrize("model", ["wing-full", "wing-rack", "wing-compact"])
    def test_local_outputs_are_eight_on_every_model(self, model):
        """The asymmetry `console_facts` used to call "a real asymmetry on
        the Compact" is family-wide: it is the inputs that vary."""
        assert facts.output_socket_limit("LCL", model) == 8

    @pytest.mark.parametrize("model", ["wing-full", "wing-rack", "wing-compact"])
    def test_mainboard_groups_are_identical_across_the_family(self, model):
        """AES50, StageCONNECT, AES/EBU and the expansion slot hang off the
        mainboard, which pp. 11-12 describe as shared, so the address-space
        count is also the panel count."""
        for group in ("A", "B", "C", "SC", "AES", "CRD"):
            assert facts.input_socket_limit(group, model) == facts.INPUT_SOCKETS[group]


class TestTheAddressTreeIsNotAPanelInventory:
    """The finding that reopened an earlier change."""

    def test_the_walk_reports_aux_sockets_the_compact_does_not_have(self):
        """`/io/in/AUX/1..8` is in the 2026-09-08 walk of the maintainer's Compact.
        The Compact has no local aux jacks. Both are true: the tree is
        firmware-wide. This is why `INPUT_SOCKETS` must not be used as a
        physical bound."""
        assert facts.INPUT_SOCKETS["AUX"] == 8
        assert facts.input_socket_limit("AUX", "wing-compact") == 0


class TestUnknownIsAHardStop:
    @pytest.mark.parametrize("model", [None, "", "wing-ultra", "compact", "WING-COMPACT"])
    def test_panel_for_refuses_anything_it_cannot_confirm(self, model):
        with pytest.raises(facts.UnknownConsoleModel):
            facts.panel_for(model)

    def test_the_error_names_the_models_it_does_know(self):
        with pytest.raises(facts.UnknownConsoleModel) as exc:
            facts.panel_for("wing-ultra")
        for known in ("wing-full", "wing-rack", "wing-compact"):
            assert known in str(exc.value)


class TestModelFromIdentity:
    """WING answers `/?` with WING,<ip>,<name>,<model>,<serial>,<firmware>,
    so the desk states its own model."""

    def test_the_real_walks_identity_string_is_understood(self):
        """Verbatim from `wing-compact-raw-walk-20260908.json`."""
        identity = ["WING,192.0.2.16,WING-PP-SERIAL01,wing-compact,"
                    "SERIAL00000001,3.1-0-g9f314617:release"]
        assert facts.model_from_identity(identity) == "wing-compact"

    def test_an_already_split_reply_works_too(self):
        assert facts.model_from_identity(
            ["WING", "192.0.2.16", "Fake", "wing-rack", "SN", "3.1-0"]) == "wing-rack"

    @pytest.mark.parametrize("identity", [
        None, [], ["WING,192.0.2.16,Fake,wing-ultra,SN,3.1-0"], ["garbage"],
        # The alias table must not become a pattern. These are
        # the shapes a "strip the suffix"/"prefix match" rule would happily
        # resolve, and every one of them is a token nobody has read off a
        # desk -- so every one of them is still None.
        ["WING,192.0.2.16,Fake,wing-racksize,SN,3.1-0"],
        ["WING,192.0.2.16,Fake,wing-compactsize,SN,3.1-0"],
        ["WING,192.0.2.16,Fake,wing-fullsizeXL,SN,3.1-0"],
        ["WING,192.0.2.16,Fake,fullsize,SN,3.1-0"],
    ])
    def test_an_unrecognised_or_absent_model_is_none_not_a_guess(self, identity):
        assert facts.model_from_identity(identity) is None

    def test_the_full_size_desks_own_spelling_resolves(self):
        """An earlier change, verbatim from the capture's `identity` field:
        `archive/examples/console-runs/2026-09-23-1921/A17-wing-full.json`.

        The first console other than the maintainer's Compact this project has
        seen. It calls itself `wing-fullsize`; `CONSOLE_MODELS` is keyed
        `wing-full`, and before the alias table this returned None -- which
        left `apply`/`audit`/`watch` not knowing what desk they were on.
        """
        identity = ["WING,192.0.2.148,WING-CCC,wing-fullsize,"
                    "SERIAL00000002,3.1-0-g9f314617:release"]
        assert facts.model_from_identity(identity) == "wing-full"

    def test_that_string_is_the_one_the_desk_actually_sent(self):
        """Ties the test above to the evidence rather than to a memory of
        it. The capture is irreplaceable hardware output and is never
        regenerated, so if these two ever disagree it is the test that is
        wrong."""
        import json

        capture = (REPO_ROOT / "tests" / "fixtures" / "console-runs" / "2026-09-23-1921"
                   / "A17-wing-full.json")
        measured = json.loads(capture.read_text())["identity"]
        assert measured == ("WING,192.0.2.148,WING-CCC,wing-fullsize,"
                            "SERIAL00000002,3.1-0-g9f314617:release")
        assert facts.model_from_identity([measured]) == "wing-full"

    def test_our_own_key_still_resolves_off_the_wire(self):
        """The alias must not displace the canonical spelling: whatever a
        desk that answers `wing-full` is, it is still a full-size."""
        assert facts.model_from_identity(
            ["WING", "192.0.2.16", "Fake", "wing-full", "SN", "3.1-0"]) == "wing-full"

    def test_every_alias_resolves_to_a_model_we_actually_know(self):
        for token, model in facts.IDENTITY_MODEL_ALIASES.items():
            assert model in facts.CONSOLE_MODELS, token
            # An alias for a key we already have would shadow nothing but
            # would mean the tables disagree about what that token means.
            assert token not in facts.CONSOLE_MODELS, token
            assert facts.model_from_identity([token]) == model

    def test_the_alias_does_not_leak_into_the_cli_choices(self):
        """The constraint: `--console-model wing-full` is a
        documented choice and is in the generated `cli-reference.md`. The
        desk's spelling is translated at the identity boundary only, so
        the flag's choices stay exactly the keys of `CONSOLE_MODELS` and
        the reference does not move.
        """
        import argparse

        from atoo import cli

        ap = argparse.ArgumentParser()
        cli._add_console_model_argument(ap)
        action = next(a for a in ap._actions if a.dest == "console_model")
        assert sorted(action.choices) == sorted(facts.CONSOLE_MODELS)
        assert "wing-full" in action.choices
        assert ap.parse_args(["--console-model", "wing-full"]).console_model == (
            "wing-full")
        for token in facts.IDENTITY_MODEL_ALIASES:
            assert token not in action.choices


class TestExpansionBays:
    """The same lesson as this file's own subject, one layer
    down: the address tree answers `/io/in/{CRD,MOD}/1..64` whether or not
    there is hardware in the slot, so the 64s in `INPUT_SOCKETS` are an
    address space. Unlike the panel counts, the desk states this one --
    which is why it needs no `--console-model` equivalent, only a read.
    """

    def test_both_bays_map_to_the_address_that_answers_for_them(self):
        assert facts.EXPANSION_BAY_ADDRESSES == {
            "CRD": "/cards/$type",
            "MOD": "/$syscfg/opt_mod",
        }

    def test_the_model_variant_groups_are_a_different_problem(self):
        """LCL/AUX vary by panel and the desk states no inventory for
        them -- that is the flag. Mixing the two sets up would either
        refuse a Compact's local inputs or read a bay off a model name."""
        assert not (facts.EXPANSION_BAY_ADDRESSES.keys() & facts.MODEL_VARIANT_GROUPS)

    def test_none_is_an_empty_bay(self):
        assert facts.bay_is_empty("NONE")

    @pytest.mark.parametrize("reported", ["WLIVE", "WDANTE", "WMADI", "WDWSG",
                                          "DANTE", "WSG", "ACOM"])
    def test_every_named_card_or_module_is_a_fitted_bay(self, reported):
        assert not facts.bay_is_empty(reported)

    @pytest.mark.parametrize("reported", [
        None,                 # the address did not answer
        "",                   # answered with nothing
        "WSOMETHINGNEW",      # a card from a firmware newer than this table
        0, 1, [],             # not a string at all
    ])
    def test_anything_that_is_not_the_word_none_is_not_an_empty_bay(self, reported):
        """The asymmetry is deliberate: a caller refuses an apply on the
        strength of this answer, so it may only say "empty" when the desk
        said so in as many letters. Guessing the other way would refuse a
        plan over a card nobody has taught this table about yet."""
        assert not facts.bay_is_empty(reported)

    def test_the_desk_does_not_refuse_the_patch_itself(self):
        """The measurement the whole of an earlier change rests on
        (`archive/examples/console-runs/2026-09-21/A8_patch_test.txt`). If this
        ever becomes False the check in `apply` is redundant, not wrong --
        but nothing should quietly assume the desk started refusing."""
        assert facts.UNFITTED_BAY_PATCH_IS_ACCEPTED is True
