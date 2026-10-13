"""`atoo init`: a working folder, a starter set, and
three ~/.atoo.config defaults -- and never an overwrite.

Every test runs in a temporary HOME (`$HOME` and `Path.home` both), so
nothing here can touch a real ~/Documents or ~/.atoo.config.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest

from atoo import config, firstrun
from atoo.cli import main


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(Path, "home", lambda: h)
    return h


def _config(home: Path) -> dict:
    return tomllib.loads((home / ".atoo.config").read_text())


def _tree(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in sorted(directory.rglob("*")) if p.is_file()}


def test_init_makes_the_folder_copies_the_starter_set_and_sets_the_config(home, capsys):
    assert main(["init"]) == 0
    folder = home / "Documents" / "Atoo"
    for rel in firstrun.starter_files():
        assert (folder / rel).read_bytes() == (firstrun.STARTER_DIR / rel).read_bytes(), rel
    # No show bundle: which show a user starts with is not ours to guess.
    assert not [p for p in folder.iterdir() if p.is_dir() and p.name != "presets"]
    assert (folder / "presets").is_dir()
    # The Demo show stays in the package: init never copies it.
    assert not (folder / firstrun.DEMO_SHOW_NAME).exists()

    data = _config(home)
    assert data["conventions"]["default"] == "~/Documents/Atoo/conventions.md"
    assert data["presets"]["default"] == "~/Documents/Atoo/presets"
    assert data["workspace"]["default"] == "~/Documents/Atoo"
    # ...and the readers find them.
    assert config.load_default_conventions() == folder / "conventions.md"
    assert config.load_default_presets() == folder / "presets"
    assert config.load_default_workspace() == folder

    out = capsys.readouterr().out
    assert "Working folder: ~/Documents/Atoo (created)" in out
    assert "[workspace] default      set to ~/Documents/Atoo" in out
    assert "atoo ui" in out


def test_the_starter_set_holds_no_built_artifacts():
    """Only the files a person writes: no plans, logs, journals, captures
    or resolved conventions."""
    for rel in firstrun.starter_files():
        name = rel.rsplit("/", 1)[-1]
        assert not name.endswith(".json"), rel
        assert "resolved" not in name and "build-log" not in rel and "journal" not in rel, rel
        assert rel.split("/")[0] in {"README.md", "conventions.md", "presets"}, rel


def test_a_second_run_is_a_no_op_that_says_so(home, capsys):
    assert main(["init"]) == 0
    folder = home / "Documents" / "Atoo"
    before_files = _tree(folder)
    before_config = (home / ".atoo.config").read_bytes()
    capsys.readouterr()

    assert main(["init"]) == 0
    assert _tree(folder) == before_files
    assert (home / ".atoo.config").read_bytes() == before_config
    out = capsys.readouterr().out
    assert "Nothing to do" in out
    assert "created" not in out.replace("(created)", "")


def test_an_existing_config_value_is_kept_and_reported_without_force(home, capsys):
    house = home / "house.md"
    house.write_text("# house\n")
    (home / ".atoo.config").write_text(
        "# my own notes\n[conventions]\ndefault = \"~/house.md\"  # mine\n\n"
        "[console]\ndefault = \"192.0.2.16\"\n")

    assert main(["init"]) == 0
    text = (home / ".atoo.config").read_text()
    assert text.startswith("# my own notes\n[conventions]\ndefault = \"~/house.md\"  # mine\n")
    data = _config(home)
    assert data["conventions"]["default"] == "~/house.md"
    assert data["console"]["default"] == "192.0.2.16"
    assert data["presets"]["default"] == "~/Documents/Atoo/presets"
    out = capsys.readouterr().out
    assert ("[conventions] default    left as ~/house.md -- init would have set "
            "~/Documents/Atoo/conventions.md; --force replaces it") in out


def test_force_replaces_a_config_value_and_keeps_the_rest_of_the_file(home, capsys):
    (home / "house.md").write_text("# house\n")
    (home / ".atoo.config").write_text(
        "# my own notes\n[conventions]\ndefault = \"~/house.md\"\n\n[console]\nport = 2224\n")
    assert main(["init", "--force"]) == 0
    text = (home / ".atoo.config").read_text()
    assert text.startswith("# my own notes\n[conventions]\n"
                           "default = \"~/Documents/Atoo/conventions.md\"\n\n"
                           "[console]\nport = 2224\n")
    assert "(replaced ~/house.md)" in capsys.readouterr().out


def test_a_file_already_there_is_left_alone_even_with_force(home, capsys):
    folder = home / "elsewhere"
    folder.mkdir()
    (folder / "conventions.md").write_text("my own house style\n")
    assert main(["init", "--dir", str(folder)]) == 0
    assert (folder / "conventions.md").read_text() == "my own house style\n"
    assert main(["init", "--dir", str(folder), "--force"]) == 0
    assert (folder / "conventions.md").read_text() == "my own house style\n"
    out = capsys.readouterr().out
    assert "conventions.md               left alone: it is yours" in out
    # --dir is what the config names, written ~/-relative.
    assert _config(home)["workspace"]["default"] == "~/elsewhere"


def test_a_user_edited_starter_file_is_never_replaced(home):
    assert main(["init"]) == 0
    folder = home / "Documents" / "Atoo"
    edited = folder / "conventions.md"
    edited.write_text(edited.read_text() + "\n## Inputs\nMy edit.\n")
    mine = edited.read_bytes()
    assert main(["init", "--force"]) == 0
    assert edited.read_bytes() == mine


def test_force_updates_only_an_untouched_copy_of_an_older_starter_set(home, capsys):
    """An older starter set is simulated: the file holds different bytes,
    and the manifest records exactly those bytes as what init copied."""
    assert main(["init"]) == 0
    folder = home / "Documents" / "Atoo"
    stale = folder / "README.md"
    stale.write_text("# an older starter README\n")
    manifest = folder / firstrun.MANIFEST_NAME
    data = json.loads(manifest.read_text())
    data["files"]["README.md"] = hashlib.sha256(stale.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(data))
    capsys.readouterr()

    assert main(["init"]) == 0
    assert stale.read_text() == "# an older starter README\n"
    assert "an untouched copy of an older starter set -- --force updates it" in (
        capsys.readouterr().out)

    assert main(["init", "--force"]) == 0
    assert stale.read_bytes() == (firstrun.STARTER_DIR / "README.md").read_bytes()
    assert "updated" in capsys.readouterr().out


def test_dir_that_is_a_file_is_refused(home, capsys):
    target = home / "afile"
    target.write_text("x")
    assert main(["init", "--dir", str(target)]) == 1
    assert "is a file, not a folder" in capsys.readouterr().err
    assert not (home / ".atoo.config").exists()


def test_workspace_is_a_known_section():
    assert "workspace" in config.KNOWN_SECTIONS
    assert "[workspace]" in config.__doc__


def test_init_counts_the_starter_presets_on_one_line(home, capsys, tmp_path, monkeypatch):
    """The preset library is one line of counts, channel and bus presets
    alike, rather than a line per file."""
    starter = tmp_path / "starter"
    (starter / "presets").mkdir(parents=True)
    (starter / "README.md").write_text("# readme\n")
    (starter / "conventions.md").write_text("# conventions\n")
    (starter / "presets" / "README.md").write_text("# presets\n")
    (starter / "presets" / "Kick In.chn").write_bytes(b"{}")
    (starter / "presets" / "FX Vox Verb.bus").write_bytes(b"{}")
    monkeypatch.setattr(firstrun, "STARTER_DIR", starter)
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "presets/                     2 presets: 2 created" in out
    assert "FX Vox Verb.bus" not in out


def test_the_starter_set_is_found_in_a_checkout_or_in_the_package():
    """A wheel carries `starter/` as `atoo/starter/`; a checkout and
    an editable install have it beside the package."""
    found = firstrun.starter_dir()
    assert (found / "conventions.md").is_file()
    assert (found / firstrun.DEMO_SHOW_NAME / "plan.json").is_file()
    package = Path(firstrun.__file__).resolve().parent
    assert found in (package / "starter", package.parent / "starter")
    assert firstrun.holds_starter_set(found)


def _fake_starter(root: Path) -> Path:
    for rel in firstrun.STARTER_MARKERS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(f"# {rel}\n")
    return root


def test_a_leftover_starter_folder_inside_the_package_is_passed_over(tmp_path, monkeypatch):
    """A checkout from before an earlier change can still have a
    `atoo/starter/` folder, kept alive after `git pull` by an
    untracked `.DS_Store` or preset. An editable install from it took that
    folder for the starter set: init copied the leftovers and the Demo
    opened `atoo/starter/demo-show`, which is not there. A folder
    that does not hold the set is passed over."""
    leftover = tmp_path / "atoo" / "starter"
    (leftover / "channel_presets").mkdir(parents=True)
    (leftover / ".DS_Store").write_bytes(b"\0")
    (leftover / "channel_presets" / ".DS_Store").write_bytes(b"\0")
    real = _fake_starter(tmp_path / "starter")
    monkeypatch.setattr(firstrun, "starter_candidates", lambda: (leftover, real))
    assert firstrun.starter_dir() == real
    # The packaged copy, when it is whole, comes first.
    _fake_starter(leftover)
    assert firstrun.starter_dir() == leftover


def test_the_candidates_are_the_package_then_beside_it():
    package = Path(firstrun.__file__).resolve().parent
    assert firstrun.starter_candidates() == (package / "starter", package.parent / "starter")


def test_init_with_no_starter_set_writes_nothing_and_says_so(home, capsys, tmp_path,
                                                              monkeypatch):
    """A broken install (no starter set anywhere) is an error, not a
    folder of nothing with a config pointing at files that are not there."""
    empty = tmp_path / "leftover"
    empty.mkdir()
    (empty / ".DS_Store").write_bytes(b"\0")
    monkeypatch.setattr(firstrun, "STARTER_DIR", empty)
    assert main(["init"]) == 1
    captured = capsys.readouterr()
    assert "has no starter set" in captured.err
    assert "Reinstall Atoo" in captured.err
    assert not (home / "Documents").exists()
    assert not (home / ".atoo.config").exists()


def test_init_copies_no_hidden_file(home, tmp_path, monkeypatch):
    """A Mac checkout's `starter/.DS_Store` is not part of the starter set."""
    starter = _fake_starter(tmp_path / "starter")
    (starter / ".DS_Store").write_bytes(b"\0")
    (starter / "presets" / ".DS_Store").write_bytes(b"\0")
    monkeypatch.setattr(firstrun, "STARTER_DIR", starter)
    assert ".DS_Store" not in " ".join(firstrun.starter_files())
    assert main(["init"]) == 0
    folder = home / "Documents" / "Atoo"
    assert not (folder / ".DS_Store").exists()
    assert not (folder / "presets" / ".DS_Store").exists()
    assert (folder / "conventions.md").is_file()


def test_init_demo_copies_no_hidden_file(home, tmp_path, monkeypatch):
    """Nor is a `.DS_Store` in the Demo show part of the Demo's copy."""
    starter = _fake_starter(tmp_path / "starter")
    (starter / "demo-show" / ".DS_Store").write_bytes(b"\0")
    monkeypatch.setattr(firstrun, "STARTER_DIR", starter)
    assert firstrun.demo_files() == ["plan.json"]
    assert main(["init", "--demo"]) == 0
    demo = home / "Documents" / "Atoo" / "demo-show"
    assert sorted(p.name for p in demo.iterdir()) == ["plan.json"]


# ---- init --demo ---------------------------------------------

def test_init_demo_copies_the_demo_show_whole_and_reports_each_file(home, capsys):
    """A pipx install has no `starter/` to `cp -r` from: `init --demo`
    writes the packaged Demo show into the working folder, as `demo-show/`
    beside the starter conventions and presets, byte for byte, and says
    so file by file."""
    assert main(["init", "--demo"]) == 0
    folder = home / "Documents" / "Atoo"
    demo = folder / firstrun.DEMO_SHOW_NAME
    packaged = firstrun.STARTER_DIR / firstrun.DEMO_SHOW_NAME
    assert firstrun.demo_files()
    assert _tree(demo) == _tree(packaged)
    out = capsys.readouterr().out
    for rel in firstrun.demo_files():
        assert f"  demo-show/{rel}".ljust(31) + "created" in out, rel
    assert "The Demo show's copy is ~/Documents/Atoo/demo-show" in out
    # Not in the manifest: the copy is the user's from the start.
    manifest = json.loads((folder / firstrun.MANIFEST_NAME).read_text())
    assert not [k for k in manifest["files"] if k.startswith("demo-show")]
    # No staging folder left behind.
    assert sorted(p.name for p in folder.iterdir() if p.name.startswith(".")) == [
        firstrun.MANIFEST_NAME]


def test_the_demo_copy_verifies_and_its_plan_reads_current(home, capsys):
    """The copy is an ordinary bundle: `verify --show` passes it, and its
    plan -- whose paths are bundle-relative -- finds the copied
    starter conventions and reads as current, as the Setup page computes
    it (`plan_freshness.assess_bundle`)."""
    from atoo import bundle, plan_freshness

    assert main(["init", "--demo"]) == 0
    demo = home / "Documents" / "Atoo" / "demo-show"
    capsys.readouterr()
    assert main(["verify", "--show", str(demo)]) == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out
    show = bundle.load(demo)
    plan = json.loads(show.plan.read_text(encoding="utf-8"))
    fresh = plan_freshness.assess_bundle(plan, show)
    assert fresh["state"] == "current", fresh
    assert not fresh["reasons"] and not fresh["unknown"]


def test_an_existing_demo_show_is_left_whole_even_with_force(home, capsys):
    """Never overwrite: a `demo-show` already in the folder -- an earlier
    copy the tester has edited, or anything else by that name -- is left
    as it is and reported, with or without --force."""
    folder = home / "Documents" / "Atoo"
    (folder / "demo-show").mkdir(parents=True)
    (folder / "demo-show" / "input.csv").write_text("name\nMy kick\n", encoding="utf-8")
    assert main(["init", "--demo", "--force"]) == 0
    assert _tree(folder / "demo-show") == {"input.csv": b"name\nMy kick\n"}
    out = capsys.readouterr().out
    assert "demo-show/                   left alone: a demo-show folder is already here" in out
    # ...and a second run over a real copy is a no-op that says so.
    assert main(["init", "--demo"]) == 0
    assert "Nothing to do" in capsys.readouterr().out


def test_even_an_empty_demo_show_folder_is_left_alone(home, capsys):
    """Anything by that name is the user's: an empty folder too (a rename
    would quietly replace one, so the check is made first)."""
    folder = home / "Documents" / "Atoo"
    (folder / "demo-show").mkdir(parents=True)
    assert main(["init", "--demo"]) == 0
    assert list((folder / "demo-show").iterdir()) == []
    assert "left alone: a demo-show folder is already here" in capsys.readouterr().out


def test_a_failed_demo_copy_leaves_no_half_bundle(home, capsys, monkeypatch):
    """The copy is staged and renamed into place: a write that fails
    leaves no `demo-show/` to be mistaken for the Demo, and says why."""
    real = firstrun.shutil.copyfile
    calls = []

    def flaky(src, dst, *a, **kw):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(firstrun.shutil, "copyfile", flaky)
    assert main(["init", "--demo"]) == 1
    folder = home / "Documents" / "Atoo"
    assert not (folder / "demo-show").exists()
    assert not [p for p in folder.iterdir() if "demo-show" in p.name]
    assert "couldn't copy the Demo show to demo-show/: No space left on device" in \
        capsys.readouterr().err
