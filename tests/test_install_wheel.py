"""Atoo installed for real, in a fresh virtualenv.

On the maintainer's Mac `atoo init` copied nothing into
``~/Documents/Atoo``, and the Demo show opened
``.../dev/<checkout>/atoo/starter/demo-show`` -- inside his checkout,
at a path that has not existed. The cause was an
editable install from a checkout that still had the pre-#493
``atoo/starter/`` folder (a ``.DS_Store`` or an untracked preset
keeps it alive after ``git pull``), which ``firstrun.starter_dir()`` took
for the starter set because it was a folder.

These tests install the package the two ways a user does -- a built
wheel (what ``pipx install`` does with a path or a git URL), and an
editable install from a checkout that carries that leftover folder -- and
run the installed ``atoo`` command, from outside the repository,
under a temporary HOME:

* ``init`` fills the working folder with the starter set;
* the Demo show resolves inside what was installed (the package, or the
  checkout's own ``starter/``), never the leftover;
* ``atoo verify --show <the Demo>`` works;
* ``init --demo`` copies the Demo out of a wheel install as a writable
  bundle that verifies.

Everything is offline: the venv's own setuptools builds the wheel
(``--no-build-isolation``) and pip installs it with ``--no-index``. A
Python whose venvs carry no setuptools (3.12 and later) skips, and says
so. One venv serves both tests (about 15 seconds together), so they stay
in the default run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The Demo show path, as the installed package resolves it. webui's
# DEMO_SHOW_DIR is exactly this (tests/test_packaging.py asserts so);
# reading it from firstrun keeps the venv free of the [ui] extra.
_DEMO_PATH = ("import atoo.firstrun as f; "
              "print(f.STARTER_DIR / f.DEMO_SHOW_NAME)")


def _run(argv, *, cwd, home, check=True):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ATOO_", "PYTHON", "PIP_", "VIRTUAL_ENV"))}
    env["HOME"] = str(home)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    done = subprocess.run([str(a) for a in argv], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=180)
    if check:
        assert done.returncode == 0, (argv, done.stdout[-2000:], done.stderr[-2000:])
    return done


def _source_copy(dest: Path) -> Path:
    """The files a build reads, copied: building writes build/ and
    *.egg-info beside pyproject.toml, and the suite must not litter the
    checkout."""
    dest.mkdir()
    for name in ("atoo", "starter"):
        shutil.copytree(REPO / name, dest / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy(REPO / name, dest / name)
    return dest


@pytest.fixture(scope="module")
def venv(tmp_path_factory):
    if not (REPO / "pyproject.toml").exists():
        pytest.skip("no pyproject.toml -- not a source checkout")
    root = tmp_path_factory.mktemp("install")
    env_dir = root / "venv"
    made = subprocess.run([sys.executable, "-m", "venv", str(env_dir)],
                          capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip(f"couldn't make a venv here: {made.stderr.strip()[-300:]}")
    bindir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    python = bindir / "python"
    has_setuptools = subprocess.run([str(python), "-c", "import setuptools"],
                                    capture_output=True)
    if has_setuptools.returncode != 0:
        pytest.skip("this Python's venvs carry no setuptools, and the build must stay "
                    "offline (no build isolation)")
    return {"root": root, "python": python, "atoo": bindir / "atoo"}


def _populated(folder: Path) -> None:
    """`init` copied the starter set: conventions, the preset library and
    its README, and not the Demo show."""
    assert (folder / "README.md").is_file()
    assert (folder / "conventions.md").is_file()
    assert (folder / "presets" / "README.md").is_file()
    presets = list((folder / "presets").glob("*.chn")) + list((folder / "presets").glob("*.bus"))
    assert len(presets) >= 3, sorted(p.name for p in (folder / "presets").iterdir())
    assert not (folder / "demo-show").exists()
    assert not list(folder.rglob(".DS_Store"))
    config = (folder.parent.parent / ".atoo.config").read_text(encoding="utf-8")
    assert "conventions.md" in config and "presets" in config


def test_a_wheel_install_fills_the_folder_and_opens_the_demo_from_the_package(venv):
    root, python = venv["root"], venv["python"]
    source = _source_copy(root / "wheel-src")
    dist = root / "dist"
    _run([python, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--no-index",
          "-q", "-w", dist, source], cwd=root, home=root)
    wheels = list(dist.glob("atoo-*.whl"))
    assert len(wheels) == 1, wheels
    _run([python, "-m", "pip", "install", "--no-index", "--no-deps", "-q", "--force-reinstall",
          wheels[0]], cwd=root, home=root)
    shutil.rmtree(source)  # nothing may be read from the source any more

    home = root / "home-wheel"
    home.mkdir()
    out = _run([venv["atoo"], "init"], cwd=home, home=home).stdout
    assert "conventions.md               created" in out
    _populated(home / "Documents" / "Atoo")
    again = _run([venv["atoo"], "init"], cwd=home, home=home).stdout
    assert "Nothing to do" in again

    demo = Path(_run([python, "-c", _DEMO_PATH], cwd=home, home=home).stdout.strip())
    package = Path(_run([python, "-c", "import atoo; print(atoo.__file__)"],
                        cwd=home, home=home).stdout.strip()).parent
    assert demo == package / "starter" / "demo-show"
    assert "site-packages" in demo.parts
    assert (demo / "plan.json").is_file()
    verify = _run([venv["atoo"], "verify", "--show", demo], cwd=home, home=home)
    assert "0 error(s)" in verify.stdout

    # `init --demo` copies that Demo out of the package as a
    # writable bundle beside the starter set, and the copy verifies.
    folder = home / "Documents" / "Atoo"
    out = _run([venv["atoo"], "init", "--demo"], cwd=home, home=home).stdout
    assert "demo-show/plan.json          created" in out
    copy = folder / "demo-show"
    assert sorted(p.name for p in copy.iterdir()) == sorted(p.name for p in demo.iterdir()
                                                            if not p.name.startswith("."))
    assert os.access(copy / "plan.json", os.W_OK)
    verify = _run([venv["atoo"], "verify", "--show", copy], cwd=home, home=home)
    assert "0 error(s), 0 warning(s)" in verify.stdout


def test_an_editable_install_ignores_a_leftover_atoo_starter_folder(venv):
    """The maintainer's case: `pipx install --editable` (or `pip install
    -e`) from a checkout that still has the pre-an earlier change
    `atoo/starter/`, holding only what git does not track."""
    root, python = venv["root"], venv["python"]
    checkout = _source_copy(root / "checkout")
    leftover = checkout / "atoo" / "starter"
    (leftover / "channel_presets").mkdir(parents=True)
    (leftover / ".DS_Store").write_bytes(b"\0")
    (leftover / "channel_presets" / ".DS_Store").write_bytes(b"\0")
    (checkout / "starter" / ".DS_Store").write_bytes(b"\0")  # Finder was here too
    _run([python, "-m", "pip", "install", "--no-build-isolation", "--no-deps", "--no-index",
          "-q", "-e", checkout], cwd=root, home=root)

    home = root / "home-editable"
    home.mkdir()
    out = _run([venv["atoo"], "init"], cwd=home, home=home).stdout
    assert ".DS_Store" not in out
    _populated(home / "Documents" / "Atoo")

    demo = Path(_run([python, "-c", _DEMO_PATH], cwd=home, home=home).stdout.strip())
    assert demo == checkout / "starter" / "demo-show"
    verify = _run([venv["atoo"], "verify", "--show", demo], cwd=home, home=home)
    assert "0 error(s)" in verify.stdout
