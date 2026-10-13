"""`docs/user/cli-reference.md` cannot drift from the CLI.

The maintainer's call was that the reference is generated rather
than hand-written, because the hand-written one drifted: `examples/
README.md` §6 disagreed with `--help` more than once, and nothing
noticed until somebody followed it.

This is the same class of guard as `tests/test_packaging.py` and
`tests/test_webui.py`'s served-asset assertions -- a file the Python
suite would otherwise have no reason to look at. Add a flag to `cli.py`
without regenerating and the first test here fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "docs" / "user" / "cli-reference.md"

sys.path.insert(0, str(REPO / "tools"))


def _generator():
    try:
        import gen_cli_reference
    except ImportError:  # pragma: no cover
        pytest.skip("tools/gen_cli_reference.py not importable")
    return gen_cli_reference


def test_the_committed_reference_is_up_to_date():
    """The whole point. Regenerate and compare -- if this fails, run
    `python3 tools/gen_cli_reference.py` and commit the result."""
    gen = _generator()
    assert TARGET.read_text() == gen.render(), (
        "docs/user/cli-reference.md is stale -- run "
        "`python3 tools/gen_cli_reference.py` and commit it"
    )


def test_every_subcommand_appears():
    """Stated separately from the up-to-date check because it fails with a
    message that names what is missing, which a whole-file diff does not."""
    from atoo.cli import build_parser

    _root, subparsers = build_parser()
    text = TARGET.read_text()
    for name in subparsers:
        assert f"## `atoo {name}`" in text, f"{name} is not in the reference"


def test_every_option_of_every_subcommand_appears():
    """The direction that actually bites: a flag added to one command and
    documented nowhere."""
    from atoo.cli import build_parser

    gen = _generator()
    _root, subparsers = build_parser()
    text = TARGET.read_text()

    missing = []
    for name, parser in subparsers.items():
        for flags, _help in gen._options(parser):
            first = flags.split(",")[0].split("`")[1]
            if f"`{first}`" not in text:
                missing.append(f"{name} {first}")
    assert not missing, f"options absent from the reference: {missing}"


def test_hand_written_preambles_survive_regeneration():
    """The reason the file is not simply overwritten wholesale: argparse
    holds the flags, it does not hold why anyone would use the command.

    Asserted against the committed file's own prose. The earlier version
    replaced every `_Not written yet._` placeholder with one marker
    sentence and asserted every recovered preamble equalled it -- which
    quietly required that *no* command preamble had been written yet. The
    first real one (`ping`) failed it without breaking
    anything, which is the wrong way round for a guard.
    """
    gen = _generator()
    text = TARGET.read_text()
    assert "<!-- preamble:start -->" in text

    written = gen._existing_preambles(text)
    assert written, "no command preamble is hand-written -- has the file been reset?"

    # A placeholder is not prose and is deliberately not carried across:
    # `_existing_preambles` filters it out so an unwritten command keeps
    # showing the placeholder rather than freezing it as content.
    assert all(v.strip() != "_Not written yet._" for v in written.values())

    regenerated = gen.render()
    for name, body in written.items():
        assert body in regenerated, f"{name}'s hand-written preamble was lost"
    assert gen._existing_preambles(regenerated) == written


def test_the_file_says_it_is_generated():
    """So nobody edits a table by hand and loses it on the next run."""
    assert "GENERATED FILE" in TARGET.read_text()[:400]
