"""`--help` says what is true now, in the user's words.

Issue numbers, requirement ids (``FR-4.1``), objective ids (``O2``),
desk-run names (``A11``) and the dates decisions were made belong in code
comments and `docs/developer/`. A user reading `atoo apply --help` has
no use for "an earlier change", and once the repository moves the number will
not even resolve. This reads every command's help -- description, epilog
and every flag's help -- and refuses any of them.
"""

from __future__ import annotations

import re

import pytest

from atoo.cli import build_parser

# What provenance looks like in this project's text. `A\d+` only as a
# word on its own: `A 12` and `AES50-A` are sockets, not desk runs.
PROVENANCE = re.compile(
    r"\bissues? #?\d+"          # An earlier change, an earlier change
    r"|#\d{2,}"                 # An earlier change
    r"|\bN?FR-[\dX]"            # FR-2.2, FR-X.3
    r"|\([OD]\d(?:/O\d)?\b"     # (O2), (O2/O3), (D6
    r"|\bA\d{1,2}\b(?!\s*\d)"   # A11, A22 -- not "A 12"
    r"|\b20\d\d-\d\d-\d\d\b"    # 2026-09-24
    r"|\bmockup\b|\bPOC\b|desk script|the maintainer",
    re.I,
)


def _help_texts() -> list[tuple[str, str]]:
    root, subparsers = build_parser()
    return [("atoo", root.format_help())] + [
        (name, parser.format_help()) for name, parser in subparsers.items()]


HELP_TEXTS = _help_texts()


@pytest.mark.parametrize("name,text", HELP_TEXTS, ids=[name for name, _ in HELP_TEXTS])
def test_help_cites_no_tracker_or_run_names(name, text):
    hits = sorted({m.group(0) for m in PROVENANCE.finditer(text)})
    assert not hits, f"`atoo {name} --help` cites {hits}"
