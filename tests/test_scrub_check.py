"""`tools/scrub_check.py`, the public repository's scrub check.

Every planted string is assembled at run time, so this file is not itself
a hit when the check runs over `tests/`.
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "scrub_check.py"
spec = importlib.util.spec_from_file_location("scrub_check", TOOL)
scrub_check = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scrub_check
spec.loader.exec_module(scrub_check)

NAME = "Came" + "ron"
HOME = "/" + "Users/" + NAME.lower() + "/Dev/show/plan.json"
LAN = "192." + "168.1.40"
TEN = "10." + "0.0.7"
SERIAL = "0100" + "ABC" + "0603" + "XYZ"
DEVICE = "WING-PP-" + "12345678"
BAND = "Glass" + "harbor"


def _run(tmp_path, *paths, deny=None, categories=None):
    deny_list = tmp_path / "deny.txt"
    deny_list.write_text("# a comment\n" + (deny or BAND) + "  # trailing\n\n")
    out, err = io.StringIO(), io.StringIO()
    code = scrub_check.run(list(paths) or [tmp_path / "tree"], deny_list,
                           set(categories or scrub_check.CATEGORIES),
                           base=tmp_path, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    (root / "docs").mkdir(parents=True)
    (root / "tests" / "fixtures").mkdir(parents=True)
    return root


def test_a_clean_tree_passes(tree, tmp_path):
    (tree / "docs" / "guide.md").write_text(
        "Point it at 192.0.2.16, the console's address.\n"
        "Saved to /home/user/show/plan.json, or /home/you/show.\n"
        'Firmware 3.1-0, "creator_sn": "NO_SERIAL", version 10.10.10.6.1 is not an address.\n')
    code, out, _ = _run(tmp_path)
    assert code == 0, out
    assert "clean" in out


@pytest.mark.parametrize("planted, category, matched", [
    (f"loaded from {HOME}\n", "home-path", "/Users/" + NAME.lower()),
    ("loaded from /home/" + "jdoe/show/plan.json\n", "home-path", "/home/" + "jdoe"),
    (f"{NAME} asked for this.\n", "name", NAME),
    (f"the desk at {LAN} answered\n", "private-ip", LAN),
    (f"default = \"{TEN}\"\n", "private-ip", TEN),
    ("bridge 172." + "20.0.9 up\n", "private-ip", "172." + "20.0.9"),
    (f"WING,192.0.2.16,FOH,wing-compact,{SERIAL},3.1\n", "serial", SERIAL),
    (f'"creator_name": "{DEVICE}"\n', "serial", DEVICE),
    (f"the {BAND.upper()} show\n", "deny-name", BAND.upper()),
])
def test_a_planted_hit_is_found(tree, tmp_path, planted, category, matched):
    planted_file = tree / "tests" / "fixtures" / "show.plan.json"
    planted_file.write_text("first line\n" + planted)
    code, out, _ = _run(tmp_path)
    assert code == 1
    assert f"tree/tests/fixtures/show.plan.json:2: {category}: {matched}" in out
    assert "tree/" in out.split("By top-level directory")[1]


def test_the_copyright_line_may_name_the_maintainer(tree, tmp_path):
    (tree / "LICENSE").write_text(f"   Copyright 2026 {NAME} O'Rourke\n")
    (tree / "pyproject.toml").write_text(f'authors = [{{ name = "{NAME} O\'Rourke" }}]\n')
    code, out, _ = _run(tmp_path)
    assert code == 0, out


def test_a_name_inside_a_home_path_is_one_hit(tree, tmp_path):
    (tree / "plan.json").write_text(f'"path": "{HOME}"\n')
    code, out, _ = _run(tmp_path)
    assert code == 1
    assert out.count("plan.json:1:") == 1


def test_a_deny_listed_name_is_a_whole_word(tree, tmp_path):
    (tree / "notes.md").write_text("Dornberg and dornish\n")
    code, out, _ = _run(tmp_path, deny="Dorn")
    assert code == 0, out
    (tree / "notes.md").write_text("Dorn on keys\n")
    code, out, _ = _run(tmp_path, deny="Dorn")
    assert code == 1 and "deny-name: Dorn" in out


def test_every_chn_is_reported_as_its_own_category(tree, tmp_path):
    (tree / "Kick.chn").write_text('{"type": "chpreset.11"}\n')
    code, out, _ = _run(tmp_path)
    assert code == 1
    assert "tree/Kick.chn:0: chn:" in out
    assert "chn 1" in out


def test_a_chn_in_the_maintainers_own_set_is_checked_for_everything_else(tree, tmp_path):
    """The own set is not reported as a `.chn`, but a desk's
    own name left in its `creator_name` still is."""
    own = tree / "starter" / "presets"
    own.mkdir(parents=True)
    (own / "Kick.chn").write_text('{"creator_name":"WING-PP-SERIAL01"}\n')
    out = io.StringIO()
    code = scrub_check.run([tree], None, {"chn", "serial"}, base=tmp_path, out=out,
                           err=io.StringIO(), own_presets=(own,))
    assert code == 0, out.getvalue()
    (own / "Kick.chn").write_text(f'{{"creator_name":"{DEVICE}"}}\n')
    code = scrub_check.run([tree], None, {"chn", "serial"}, base=tmp_path, out=out,
                           err=io.StringIO(), own_presets=(own,))
    assert code == 1 and f"tree/starter/presets/Kick.chn:1: serial: {DEVICE}" in out.getvalue()
    assert ": chn:" not in out.getvalue()


REPO = TOOL.parent.parent


def test_the_starter_set_and_the_own_preset_copies_are_clean():
    """The scrub check run for real over what the maintainer's presets
    touch, so a re-export dropped into `starter/presets/` with the desk's
    name still in it fails the suite, not only the launch."""
    out, err = io.StringIO(), io.StringIO()
    code = scrub_check.run([REPO / "starter", *scrub_check.OWN_PRESET_DIRS],
                           scrub_check.DEFAULT_DENY_LIST, set(scrub_check.CATEGORIES),
                           out=out, err=err)
    assert code == 0, out.getvalue()


def test_no_chn_outside_the_own_set_except_under_examples():
    """`examples/` stays in the private repository (the manifest); every
    other `.chn` in the tree is the maintainer's own set."""
    stray = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        rel = Path(dirpath).relative_to(REPO)
        if rel.parts[:1] in (("examples",), (".git",)):
            dirnames[:] = []
            continue
        stray += [rel / f for f in filenames if f.lower().endswith(".chn")
                  and Path(dirpath).resolve() not in {d.resolve() for d in scrub_check.OWN_PRESET_DIRS}]
    assert stray == []


def test_a_binary_file_is_still_searched(tree, tmp_path):
    (tree / "capture.bin").write_bytes(b"\x00\xff\xfe" + LAN.encode() + b"\x00")
    code, out, _ = _run(tmp_path)
    assert code == 1 and f"private-ip: {LAN}" in out


def test_the_deny_list_does_not_report_itself(tmp_path):
    code, out, _ = _run(tmp_path, tmp_path / "deny.txt")
    assert code == 0, out


def test_without_a_deny_list_it_warns_and_checks_the_rest(tree, tmp_path):
    (tree / "notes.md").write_text(f"the {BAND} show\n")
    out, err = io.StringIO(), io.StringIO()
    code = scrub_check.run([tree], tmp_path / "missing.txt", set(scrub_check.CATEGORIES),
                           base=tmp_path, out=out, err=err)
    assert code == 0
    assert "no deny list" in err.getvalue()


def test_category_narrows_the_check(tree, tmp_path):
    (tree / "notes.md").write_text(f"{NAME} at {LAN}\n")
    code, out, _ = _run(tmp_path, categories=["private-ip"])
    assert code == 1
    assert "private-ip" in out and ": name:" not in out


def test_the_cli_exits_non_zero_on_a_hit(tree, tmp_path, capsys):
    (tree / "notes.md").write_text(f"the desk at {LAN}\n")
    assert scrub_check.main([str(tree), "--deny-list", str(tmp_path / "none.txt")]) == 1
    assert LAN in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        scrub_check.main([str(tmp_path / "no-such-dir")])
    assert exc.value.code == 2
