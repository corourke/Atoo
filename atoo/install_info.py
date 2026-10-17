"""Which Atoo is this? Where it runs from, and what to tell someone who
needs the browser UI's extra packages and has none.

Two people ask the same question from two ends. Someone who checks out a
branch to try it needs to see that the ``atoo`` they just ran is that
checkout, and not the copy a package manager installed earlier, which
never follows a ``git checkout``. And someone whose ``atoo ui`` stops for
want of the ``ui`` extra needs the install command that works where they
are: the plain ``pip install`` is refused outright by a Python the
operating system manages, and an installed copy has no checkout to
install from.

``describe()`` reads the answer from the package's own location, once:

- **checkout** -- the package sits beside a ``.git``. The branch, the short
  commit and whether tracked files have uncommitted changes come from one
  ``git status`` call; a machine with no ``git`` (or one that will not say)
  gets a short note instead, never an error.
- **installed** -- under ``site-packages``: a copy made by a package
  manager, which stays as it was installed whatever a clone beside it does.
- **source** -- anywhere else: a source tree with no git history.

Nothing here writes, and nothing needs the network.
"""
from __future__ import annotations

import os
import platform
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from atoo import config

#: Where an installed copy comes from, as the install page spells it.
INSTALL_SOURCE = "git+https://github.com/corourke/Atoo.git"

#: How long ``git`` gets to answer. A version line is not worth a hang.
GIT_TIMEOUT_S = 5.0

_CHECKOUT_DOC = "https://docs.atoo.app/reference/install-from-checkout/"
_INSTALL_DOC = "https://docs.atoo.app/getting-started/install/"


@dataclass(frozen=True)
class InstallInfo:
    """What `describe()` found. ``kind`` is "checkout", "installed" or
    "source"; ``root`` is the directory beside the package when it is a
    project tree (a checkout or an unpacked source tree), else None."""

    version: str
    package_dir: Path
    kind: str
    root: Path | None = None
    branch: str | None = None      # None when detached or unknown
    commit: str | None = None
    dirty: bool | None = None
    git_note: str | None = None    # why the branch is unknown, when it is
    detached: bool = False
    python_path: str = ""
    python_version: str = ""

    def summary(self) -> str:
        """The one line: ``atoo 0.2.0 (running from /x/atoo; branch b, a1b2c3d, clean)``."""
        head = f"atoo {self.version}"
        if self.kind == "installed":
            return f"{head} (installed copy at {_shown(self.package_dir)})"
        where = f"running from {_shown(self.package_dir)}"
        if self.kind != "checkout":
            return f"{head} ({where})"
        if self.git_note:
            return f"{head} ({where}; a git checkout, but {self.git_note})"
        state = "uncommitted changes" if self.dirty else "clean"
        ref = "detached HEAD" if self.detached else f"branch {self.branch}"
        return f"{head} ({where}; {ref}, {self.commit}, {state})"

    def version_text(self) -> str:
        """What ``atoo --version`` prints: the line, and the Python under it."""
        return f"{self.summary()}\nPython {self.python_version} at {_shown(self.python_path)}"

    def payload(self) -> dict:
        """What the web page is sent: the line, and its parts."""
        return {
            "line": self.summary(),
            "version": self.version,
            "kind": self.kind,
            "path": str(self.package_dir),
            "branch": self.branch,
            "detached": self.detached,
            "commit": self.commit,
            "dirty": self.dirty,
            "python": self.python_path,
        }


def _shown(path: Path | str) -> str:
    """``path`` as the line writes it: ``~/...`` under the home directory,
    as the settings file and the docs write paths, so a pasted line carries
    no user name."""
    try:
        return config.config_value_for(Path(path))
    except (RuntimeError, OSError):
        return str(path)


def _git_state(root: Path) -> dict:
    """Branch, commit and dirtiness of the checkout at ``root``, from one
    ``git status``; or ``{"git_note": why not}``."""
    env = dict(os.environ, LC_ALL="C", GIT_OPTIONAL_LOCKS="0")
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v2", "--branch",
             "--untracked-files=no"],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=GIT_TIMEOUT_S, env=env,
            stdin=subprocess.DEVNULL, check=False)
    except FileNotFoundError:
        return {"git_note": "git is not installed, so the branch is unknown"}
    except (OSError, subprocess.SubprocessError):
        return {"git_note": "git did not answer, so the branch is unknown"}
    if done.returncode != 0:
        return {"git_note": "git would not say which branch"}
    oid = head = None
    dirty = False
    for line in done.stdout.splitlines():
        if line.startswith("# branch.oid "):
            oid = line.split(" ", 2)[2]
        elif line.startswith("# branch.head "):
            head = line.split(" ", 2)[2]
        elif line and not line.startswith("#"):
            dirty = True
    if oid is None or head is None:
        return {"git_note": "git would not say which branch"}
    commit = "no commits yet" if oid == "(initial)" else oid[:7]
    detached = head == "(detached)"
    return {"branch": None if detached else head, "detached": detached,
            "commit": commit, "dirty": dirty}


def describe(package_dir: Path | None = None) -> InstallInfo:
    """Read where this Atoo runs from. ``package_dir`` is for tests; the
    default is the ``atoo`` package that is actually imported."""
    from atoo import __version__

    if package_dir is None:
        package_dir = Path(__file__).resolve().parent
    root = package_dir.parent
    common = dict(
        version=__version__, package_dir=package_dir,
        python_path=sys.executable or "python", python_version=platform.python_version())
    if (root / ".git").exists():
        return InstallInfo(kind="checkout", root=root, **_git_state(root), **common)
    if any(part in ("site-packages", "dist-packages") for part in package_dir.parts):
        return InstallInfo(kind="installed", **common)
    if (root / "pyproject.toml").is_file():
        return InstallInfo(kind="source", root=root, **common)
    return InstallInfo(kind="source", **common)


# ---- the 'ui' extra's missing-package hint -------------------------------

def in_virtualenv() -> bool:
    """Whether this interpreter runs inside a virtual environment, where
    ``pip install`` is allowed. Outside one, a Python the operating system
    manages (Homebrew's, most Linux distributions') refuses it."""
    return sys.prefix != sys.base_prefix


def in_pipx_environment() -> bool:
    """Whether this interpreter is the private environment pipx made."""
    parts = [p.lower() for p in Path(sys.prefix).parts]
    return "venvs" in parts and any(p == "pipx" for p in parts)


def ui_extra_hint(info: InstallInfo | None = None) -> str:
    """What to say when ``atoo ui`` cannot import the browser UI's packages.

    The command that fixes it depends on where Atoo is running: inside a
    virtualenv ``pip install`` works; outside one it is usually refused
    (``externally-managed-environment``), and the way out is a virtualenv
    for a checkout, or a pipx reinstall for an installed copy.
    """
    info = info or describe()
    lead = "the web UI needs the 'ui' extra"
    if in_virtualenv():
        if in_pipx_environment():
            return (f"{lead} -- this copy was installed by pipx without it. Install it again with:\n"
                    f"  pipx install --force \"atoo[ui] @ {INSTALL_SOURCE}\"\n"
                    f"({_INSTALL_DOC})")
        if info.root is not None:
            return f"{lead} -- install it with:\n  python3 -m pip install -e \".[ui]\""
        return (f"{lead} -- install it into this virtual environment with:\n"
                f"  python3 -m pip install \"atoo[ui] @ {INSTALL_SOURCE}\"")

    outside = ("This Python is not inside a virtual environment, where `pip install` is "
               "often refused (`error: externally-managed-environment`)")
    if info.root is not None:
        folder = shlex.quote(str(info.root))   # absolute: a quoted ~ would not expand
        activate = (".venv\\Scripts\\activate" if sys.platform == "win32"
                    else "source .venv/bin/activate")
        return (f"{lead}. {outside}, so make one in the checkout and install into it:\n"
                f"  cd {folder}\n"
                f"  python3 -m venv .venv\n"
                f"  {activate}\n"
                f"  python3 -m pip install -e \".[ui]\"\n"
                f"then run `atoo ui` from that terminal ({_CHECKOUT_DOC}).")
    return (f"{lead}. {outside}, so install Atoo with pipx instead:\n"
            f"  pipx install --force \"atoo[ui] @ {INSTALL_SOURCE}\"\n"
            f"({_INSTALL_DOC})")
