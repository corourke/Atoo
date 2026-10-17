"""The `--help` text must work from any install.

A pipx install carries `atoo/` and `atoo.starter` and nothing under
`docs/`. Before this, `atoo audit --help` and `atoo watch --help` told the
user to run `atoo audit --state docs/user/demo/audit-demo/...`, a path a
pipx install does not have, and several messages said "see
docs/user/show-bundles.md", a page a pipx user cannot open as a file. The
suite ran from a checkout, where every one of those paths exists, and
could not see it.

Two guards:

* the example commands in `audit --help` and `watch --help` are run, as
  written, in a fresh HOME after `atoo init` -- the only setup the help
  tells the user to do;
* no user-visible string in `atoo/` names a file under `docs/user/`; the
  pointer is a docs-site URL.
"""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

import pytest

import atoo
from atoo.cli import build_parser, main

PACKAGE = Path(atoo.__file__).resolve().parent


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(Path, "home", lambda: h)
    return h


def _example_commands(name: str) -> list[str]:
    """Every indented `atoo ...` line in the subcommand's description, with
    the ones that need a live console left out."""
    _, subparsers = build_parser()
    lines = subparsers[name].description.splitlines()
    return [line.strip() for line in lines
            if line.startswith("  atoo ") and "--console" not in line]


@pytest.mark.parametrize("name", ["audit", "watch"])
def test_the_help_examples_exist(name):
    assert [c for c in _example_commands(name) if "audit-demo" in c], (
        f"`atoo {name} --help` lost its offline examples")


@pytest.mark.parametrize("name", ["audit", "watch"])
def test_every_offline_help_example_runs_as_written(name, home, monkeypatch, capsys):
    """After `atoo init`, and nothing else: the user's shell expands `~`
    (and `atoo` expands it itself where the shell does not)."""
    assert main(["init"]) == 0
    capsys.readouterr()
    for command in _example_commands(name):
        if "my_show_plan.json" in command or "tonight.state.json" in command:
            continue  # placeholders for the user's own files
        argv = shlex.split(command)[1:]
        if name == "watch":
            argv += ["--count", "2", "--interval", "0.01"]
        code = main(argv)
        captured = capsys.readouterr()
        assert code in (0, None), f"`{command}` exited {code}: {captured.err}"
        assert "couldn't read" not in captured.err, command
        assert captured.out.strip(), f"`{command}` printed nothing"


def test_a_tilde_path_is_expanded_by_atoo_when_the_shell_does_not(home, capsys):
    """Windows shells pass `~` through untouched."""
    assert main(["init"]) == 0
    capsys.readouterr()
    code = main(["audit", "--state", "~/Documents/Atoo/audit-demo/audit_demo_state.json",
                 "--plan", "~/Documents/Atoo/audit-demo/audit_demo_plan.json"])
    assert code in (0, None)
    assert "Audit findings" in capsys.readouterr().out


def _user_visible_strings(path: Path):
    """The string constants of a module that are not docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            yield node.lineno, node.value


def test_no_user_visible_string_points_at_a_docs_user_file():
    """A pipx install has no `docs/`: the pointer is the docs site."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for lineno, text in _user_visible_strings(path):
            if re.search(r"docs/user/|audit-demo/audit_demo", text) and "~/Documents" not in text:
                found.append(f"{path.relative_to(PACKAGE).as_posix()}:{lineno}: {text[:80]!r}")
    assert not found, "user-visible text names a file a pipx install does not have:\n" + "\n".join(found)


def test_the_pointers_use_the_docs_site():
    cli = (PACKAGE / "cli.py").read_text(encoding="utf-8")
    for url in ("https://docs.atoo.app/build/show-bundles/",
                "https://docs.atoo.app/build/build-a-show/",
                "https://docs.atoo.app/reference/cli-reference/"):
        assert url in cli
