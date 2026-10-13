"""The suite cannot see a packaging mistake unless something builds a wheel.

An earlier change, and the same blind spot `tests/test_webui.py`'s served-asset
assertion exists for. Every test in this repo runs against an editable
install, where `Path(__file__).parent / "domain" / "knowledge.md"` resolves
against the checkout and is always present. In a built distribution it is
present only if a `package-data` glob names it -- and for the whole life of
`atoo/domain/knowledge.md` so far, none did. 979 green tests said
nothing, because none of them was looking at a wheel.

Two cheap assertions plus one real build:

  * every glob in `[tool.setuptools.package-data]` matches a file (a glob
    that matches nothing is either a typo or, as with `domain/*.json`, a
    line that outlived the files it was written for);
  * every non-`.py` file under `atoo/` is matched by some glob (the
    direction that actually bites -- a new data file nobody listed);
  * a wheel built from this tree contains them.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

import atoo

PACKAGE = Path(atoo.__file__).parent
REPO = PACKAGE.parent
PYPROJECT = REPO / "pyproject.toml"
#: The starter set: the repository's top-level `starter/`,
#: installed as the package `atoo.starter`.
STARTER = REPO / "starter"

# Non-.py files under atoo/ that are deliberately NOT shipped. Keep
# this list short and justified: anything on it is a file a wheel install
# does not have, so if code ever reads one, that read fails in the field
# and passes here.
NOT_SHIPPED = {
    # Developer documentation -- read by a person in the checkout, never by
    # the package at runtime.
    "README.md",
}


def package_data_globs() -> list[str]:
    if not PYPROJECT.exists():  # running against a non-editable install
        pytest.skip("no pyproject.toml next to the package -- not a source checkout")
    data = tomllib.loads(PYPROJECT.read_text())
    return data["tool"]["setuptools"]["package-data"]["atoo"]


def starter_data_globs() -> list[str]:
    """The package-data globs of `atoo.starter`, relative to
    `starter/` -- after checking pyproject maps that package there."""
    if not PYPROJECT.exists():
        pytest.skip("no pyproject.toml next to the package -- not a source checkout")
    data = tomllib.loads(PYPROJECT.read_text())["tool"]["setuptools"]
    assert data["package-dir"]["atoo.starter"] == "starter"
    assert "atoo.starter" in data["packages"]
    return data["package-data"]["atoo.starter"]


def test_no_starter_data_glob_is_dead_and_every_starter_file_is_shipped():
    """The same two checks for the starter set, which lives outside the
    package directory in the repository."""
    globs = starter_data_globs()
    for glob in globs:
        assert list(STARTER.glob(glob)), f"starter package-data glob {glob!r} matches no file"
    matched = {path for glob in globs for path in STARTER.glob(glob)}
    for path in sorted(STARTER.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        assert path in matched, f"starter/{path.relative_to(STARTER).as_posix()} is in no wheel"


def test_no_package_data_glob_is_dead():
    """A glob matching nothing is the shape of the #101 bug: `domain/*.json`
    stayed in the list after #98 deleted the last .json in that directory,
    and read as "domain files are handled" while handling none."""
    for glob in package_data_globs():
        assert list(PACKAGE.glob(glob)), (
            f"package-data glob {glob!r} matches no file under {PACKAGE} -- either the "
            "files it was written for are gone (delete the line) or it is a typo"
        )


def test_every_data_file_in_the_package_is_shipped():
    """The direction that bites: a file added to atoo/ that no glob
    names is absent from every wheel, and the code reading it degrades in
    the field only."""
    globs = package_data_globs()
    matched = {path for glob in globs for path in PACKAGE.glob(glob)}
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_dir() or path.suffix == ".py" or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(PACKAGE).as_posix()
        if relative in NOT_SHIPPED:
            continue
        assert path in matched, (
            f"{relative} is in the package but no package-data glob matches it, so no "
            f"wheel contains it. Add a glob in pyproject.toml, or add it to this "
            f"test's NOT_SHIPPED with a reason. Globs today: {globs}"
        )


def test_a_built_wheel_actually_contains_the_domain_knowledge(tmp_path):
    """The assertion the other two approximate. `_domain_knowledge()` is
    embedded in both the generator and the critic prompt; a wheel without
    this file plans every show with no audio vocabulary."""
    if not PYPROJECT.exists():
        pytest.skip("no pyproject.toml next to the package -- not a source checkout")

    # Built from a COPY: the backend writes build/ and *.egg-info next to
    # pyproject.toml, and a test suite should not litter the checkout.
    source = tmp_path / "src"
    source.mkdir()
    shutil.copytree(PACKAGE, source / "atoo",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(STARTER, source / "starter",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        if (REPO / name).exists():
            shutil.copy(REPO / name, source / name)

    out = tmp_path / "dist"
    out.mkdir()
    build = subprocess.run(
        [sys.executable, "-c",
         "import sys; from setuptools import build_meta; "
         "build_meta.build_wheel(sys.argv[1])", str(out)],
        cwd=source, capture_output=True, text=True,
    )
    if build.returncode != 0:
        pytest.skip(f"couldn't build a wheel here: {build.stderr.strip()[-300:]}")

    # The backend logs to stdout, so find the artifact rather than parsing it.
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel in {out}, found {wheels}"
    wheel = wheels[0]
    names = zipfile.ZipFile(wheel).namelist()
    assert "atoo/domain/knowledge.md" in names, (
        f"the built wheel has no domain knowledge file. Non-.py files in it: "
        f"{[n for n in names if not n.endswith('.py') and '.dist-info' not in n]}"
    )
    assert "atoo/prompts/plan_generation.md" in names
    # `atoo init`'s starter set: every file of it, since a
    # wheel missing one makes `init` hand a new user a partial folder.
    from atoo import firstrun
    missing = [rel for rel in firstrun.starter_files()
               if f"atoo/starter/{rel}" not in names]
    assert not missing, f"the built wheel lacks starter-set files: {missing}"
    # The demo show: the UI's Demo opens it, so a wheel
    # without it has a Demo that opens nothing.
    missing = [rel for rel in _demo_files() if f"atoo/starter/{rel}" not in names]
    assert not missing, f"the built wheel lacks demo-show files: {missing}"


def _demo_files() -> list[str]:
    from atoo.webui import DEMO_ROOT
    return sorted(p.relative_to(DEMO_ROOT).as_posix() for p in DEMO_ROOT.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts)


def test_the_demo_show_is_package_data():
    """Every file of the demo show -- its input list,
    instructions, plan and watch.json, beside the starter conventions it
    is built from -- is matched by a package-data glob, and the UI reads
    it from the starter set."""
    pytest.importorskip("fastapi")
    from atoo import firstrun
    from atoo.webui import DEMO_CONVENTIONS, DEMO_PRESETS, DEMO_ROOT, DEMO_SHOW_DIR
    matched = {path for glob in starter_data_globs() for path in STARTER.glob(glob)}
    files = _demo_files()
    assert {"conventions.md", "demo-show/input.csv", "demo-show/instructions.md",
            "demo-show/plan.json", "demo-show/watch.json"} <= set(files)
    for rel in files:
        assert STARTER / rel in matched, rel
    # One copy of each: the Demo is the starter set's show.
    assert DEMO_ROOT == firstrun.STARTER_DIR
    assert DEMO_SHOW_DIR.parent == DEMO_CONVENTIONS.parent == DEMO_PRESETS.parent == DEMO_ROOT


def test_the_starter_set_is_package_data_and_not_read_from_examples():
    """`init` copies from the starter set, which the
    package-data globs cover, and never from `examples/` -- a wheel
    install has no `examples/`. The set is the repository's
    top-level `starter/`, not a folder inside the package."""
    from atoo import firstrun
    matched = {path for glob in starter_data_globs() for path in STARTER.glob(glob)}
    files = firstrun.starter_files()
    assert {"README.md", "conventions.md", "presets/README.md"} <= set(files)
    assert not any(f.startswith(firstrun.DEMO_SHOW_NAME + "/") for f in files)
    for rel in files:
        assert STARTER / rel in matched, rel
    assert firstrun.STARTER_DIR == STARTER
    assert not (PACKAGE / "starter").exists() and not (PACKAGE / "demo").exists()
    assert "examples" not in (PACKAGE / "firstrun.py").read_text().split('"""', 2)[2]


def test_the_initialized_captures_are_package_data():
    """A full apply resets the desk from the model's
    initialized capture and the leaf type table, both read from the
    package -- never from `examples/` or `docs/`, which a wheel has not."""
    from atoo import initialize
    globs = package_data_globs()
    matched = {path for glob in globs for path in PACKAGE.glob(glob)}
    files = [initialize.LEAF_TYPES_FILE] + [f for f, _s in initialize.CAPTURES.values()]
    for name in files:
        assert initialize.CAPTURE_DIR / name in matched, name
    assert initialize.CAPTURE_DIR == PACKAGE / "initialized"
    source = (PACKAGE / "initialize.py").read_text()
    assert "Path(__file__).parent / \"initialized\"" in source
    assert "examples/" not in "".join(
        line for line in source.splitlines() if "open(" in line or "read_text(" in line)
