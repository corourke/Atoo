"""Which Atoo is this: `atoo --version`, the start-up line, the page's
footer, and the 'ui' extra's hint, which depends on where Atoo runs.

The checkout cases build a small git repository in a temp directory, so
nothing here reads this repository's own state or the examples/ folder.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from atoo import install_info
from atoo.cli import main

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _home_elsewhere(tmp_path_factory, monkeypatch):
    """The line writes paths under the home directory as `~/...`; keep the
    temp folders these tests use out of it so they compare as written."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path_factory.mktemp("home")))


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", "-C", str(root), *args],
        check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path):
    """A project tree with a package folder, one commit, on branch `feature`."""
    root = tmp_path / "work tree"
    (root / "atoo").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (root / "atoo" / "__init__.py").write_text("")
    _git(root, "init", "-q", "-b", "feature")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "first")
    return root


def _head(root: Path) -> str:
    return subprocess.run(["git", "-C", str(root), "rev-parse", "--short=7", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


# ---- describe(): the four places Atoo can be running from ----------------

@needs_git
def test_a_clean_checkout_names_its_branch_and_commit(checkout):
    info = install_info.describe(checkout / "atoo")
    assert info.kind == "checkout"
    assert info.branch == "feature"
    assert info.commit == _head(checkout)
    assert info.dirty is False
    line = info.summary()
    assert line.startswith("atoo ")
    assert f"running from {checkout / 'atoo'}; branch feature, {_head(checkout)}, clean" in line


@needs_git
def test_a_changed_tracked_file_makes_the_checkout_dirty(checkout):
    (checkout / "pyproject.toml").write_text("[project]\nname = 'changed'\n")
    info = install_info.describe(checkout / "atoo")
    assert info.dirty is True
    assert info.summary().endswith(f"branch feature, {_head(checkout)}, uncommitted changes)")


@needs_git
def test_a_detached_head_is_said_so(checkout):
    _git(checkout, "checkout", "-q", "--detach")
    info = install_info.describe(checkout / "atoo")
    assert info.detached and info.branch is None
    assert f"detached HEAD, {_head(checkout)}, clean" in info.summary()


def test_an_installed_copy_has_no_git_and_says_where_it_is(tmp_path):
    package = tmp_path / "pipx" / "venvs" / "atoo" / "lib" / "python3.12" / "site-packages" / "atoo"
    package.mkdir(parents=True)
    info = install_info.describe(package)
    assert info.kind == "installed"
    assert info.summary() == f"atoo {info.version} (installed copy at {package})"
    assert "branch" not in info.summary()


def test_a_folder_that_is_not_a_git_checkout_just_says_where_it_runs_from(tmp_path):
    package = tmp_path / "unpacked" / "atoo"
    package.mkdir(parents=True)
    info = install_info.describe(package)
    assert info.kind == "source"
    assert info.summary() == f"atoo {info.version} (running from {package})"


def test_a_checkout_on_a_machine_without_git_says_so_quietly(tmp_path, monkeypatch):
    package = tmp_path / "clone" / "atoo"
    package.mkdir(parents=True)
    (tmp_path / "clone" / ".git").mkdir()

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(install_info.subprocess, "run", no_git)
    info = install_info.describe(package)
    assert info.kind == "checkout"
    assert info.branch is None and info.commit is None
    line = info.summary()
    assert f"running from {package}; a git checkout, but git is not installed" in line
    assert "Traceback" not in line


def test_a_git_that_will_not_answer_is_not_an_error(tmp_path, monkeypatch):
    package = tmp_path / "clone" / "atoo"
    package.mkdir(parents=True)
    (tmp_path / "clone" / ".git").mkdir()
    monkeypatch.setattr(
        install_info.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 128, "", "fatal: not a git repository"))
    assert "a git checkout, but git would not say which branch" in install_info.describe(
        package).summary()


@needs_git
def test_a_repository_with_no_commit_yet_still_reports(tmp_path):
    root = tmp_path / "fresh"
    (root / "atoo").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    info = install_info.describe(root / "atoo")
    assert info.branch == "main"
    assert info.commit == "no commits yet"


def test_the_real_package_is_described_without_arguments():
    info = install_info.describe()
    assert info.package_dir == Path(install_info.__file__).resolve().parent
    assert info.summary().startswith(f"atoo {info.version} (")


def test_a_path_under_the_home_directory_is_written_with_a_tilde(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    package = tmp_path / "Atoo" / "atoo"
    package.mkdir(parents=True)
    info = install_info.describe(package)
    assert info.summary() == f"atoo {info.version} (running from ~/Atoo/atoo)"
    assert info.payload()["path"] == str(package)    # the page keeps the full path


# ---- atoo --version -------------------------------------------------------

def test_version_prints_the_line_and_the_python_and_exits_zero(capsys):
    assert main(["--version"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == install_info.describe().summary()
    assert re.fullmatch(r"Python \d+\.\d+\.\d+\S* at .+", out[1])
    assert len(out) == 2


def test_version_needs_no_command_and_runs_nothing_else(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert main(["--version"]) == 0
    assert list(tmp_path.iterdir()) == []


# ---- atoo ui: the start-up line and the footer -----------------------------

def test_ui_starts_with_the_same_line_version_prints(stub_ui_server, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert main(["ui", "--port", "0", "--no-browser"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == install_info.describe().summary()
    assert out[1].startswith("Atoo: http://")


def test_the_page_carries_the_line_and_the_script_shows_it():
    from conftest import require_fastapi_testclient
    testclient = require_fastapi_testclient()
    from atoo.webui import create_app

    with testclient.TestClient(create_app()) as client:
        page = client.get("/").text
        script = client.get("/static/shell.js").text
        styles = client.get("/static/styles.css").text
    blob = re.search(r'<script id="initial-shell" type="application/json">(.*?)</script>',
                     page, re.S)
    assert blob, "the start-up data is embedded in the page"
    install = json.loads(blob.group(1))["install"]
    assert install["line"] == install_info.describe().summary()
    assert install["kind"] in ("checkout", "installed", "source")
    assert 'id="about-line"' in page
    # The script reads exactly the field the server sends.
    assert "startup.install" in script and 'el("about-line")' in script
    assert ".about-line" in styles


def test_the_footer_shows_in_the_real_page_in_the_dark_theme(tmp_path, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    import os
    chromium = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(chromium).exists():
        pytest.skip(f"no Chromium at {chromium} (set ATOO_TEST_CHROMIUM)")
    from atoo.webui import create_app

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                                     " localStorage.setItem('atoo.theme', 'dark'); } catch (e) {}")
                page.goto(f"http://127.0.0.1:{port}/")
                footer = page.locator("#about-line")
                footer.wait_for(state="visible")
                assert footer.inner_text() == install_info.describe().summary()
                # Dark is the primary look: the line is dimmed text on the page
                # background, not the text colour and not invisible.
                colours = page.evaluate(
                    "(() => { const s = getComputedStyle(document.getElementById('about-line'));"
                    " return [s.color, getComputedStyle(document.body).backgroundColor]; })()")
                assert colours[0] != colours[1]
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# ---- the 'ui' extra's hint: one per situation -------------------------------

def _hint(monkeypatch, tmp_path, *, venv: bool, kind: str, pipx: bool = False,
          uv_tool: bool = False, uv_venv: bool = False) -> str:
    """The hint in a given situation. ``kind`` is "checkout" or "installed".
    ``uv_tool`` is the environment `uv tool install` makes (it holds a
    `uv-receipt.toml`); ``uv_venv`` one `uv venv` made (its `pyvenv.cfg`
    names uv, and that is all)."""
    if kind == "checkout":
        root = tmp_path / "my clone"
        package = root / "atoo"
        package.mkdir(parents=True)
        (root / "pyproject.toml").write_text("")
    else:
        package = tmp_path / "lib" / "python3.12" / "site-packages" / "atoo"
        package.mkdir(parents=True)
    base = tmp_path / "base-python"
    if uv_tool:
        venv = True
        prefix = tmp_path / "uv-env" / "atoo"
        prefix.mkdir(parents=True)
        (prefix / "pyvenv.cfg").write_text("home = /usr/bin\nuv = 0.11.32\n")
        (prefix / "uv-receipt.toml").write_text('[tool]\nrequirements = [{ name = "atoo" }]\n')
    elif uv_venv:
        venv = True
        prefix = tmp_path / "venv"
        prefix.mkdir(parents=True)
        (prefix / "pyvenv.cfg").write_text("home = /usr/bin\nuv = 0.11.32\n")
    elif venv:
        prefix = (tmp_path / "pipx" / "venvs" / "atoo") if pipx else (tmp_path / "venv")
    else:
        prefix = base
    monkeypatch.setattr(install_info.sys, "prefix", str(prefix))
    monkeypatch.setattr(install_info.sys, "base_prefix", str(base))
    monkeypatch.setattr(install_info.sys, "platform", "darwin")
    monkeypatch.setattr(install_info, "_git_state", lambda root: {"git_note": "x"})
    return install_info.ui_extra_hint(install_info.describe(package))


def test_outside_a_virtualenv_a_checkout_is_told_to_make_one(monkeypatch, tmp_path):
    hint = _hint(monkeypatch, tmp_path, venv=False, kind="checkout")
    assert hint.startswith("the web UI needs the 'ui' extra")
    assert "not inside a virtual environment" in hint
    assert "externally-managed-environment" in hint
    lines = hint.splitlines()
    steps = [line.strip() for line in lines if line.startswith("  ")]
    assert steps[0] == f"cd '{tmp_path / 'my clone'}'"      # quoted: the folder has a space
    assert steps[1:] == ["python3 -m venv .venv",
                         "source .venv/bin/activate",
                         'python3 -m pip install -e ".[ui]"']
    assert "https://docs.atoo.app/reference/install-from-checkout/" in hint


def test_inside_a_virtualenv_a_checkout_keeps_the_one_line_pip_hint(monkeypatch, tmp_path):
    hint = _hint(monkeypatch, tmp_path, venv=True, kind="checkout")
    assert hint == ("the web UI needs the 'ui' extra -- install it with:\n"
                    '  python3 -m pip install -e ".[ui]"')


def test_outside_a_virtualenv_an_installed_copy_is_pointed_at_uv(monkeypatch, tmp_path):
    hint = _hint(monkeypatch, tmp_path, venv=False, kind="installed")
    assert "externally-managed-environment" in hint
    assert 'uv tool install --force "atoo[ui] @ git+' in hint
    assert "pipx" not in hint
    assert " -e " not in hint
    assert not [line for line in hint.splitlines() if line.startswith("  ") and "pip " in line]
    assert "https://docs.atoo.app/getting-started/install/" in hint


def test_a_pipx_copy_is_reinstalled_with_the_extra(monkeypatch, tmp_path):
    hint = _hint(monkeypatch, tmp_path, venv=True, kind="installed", pipx=True)
    assert "installed by pipx without it" in hint
    assert 'pipx install --force "atoo[ui] @ git+' in hint
    assert "pip install" not in hint


def test_a_virtualenv_that_is_not_pipx_installs_the_extra_into_itself(monkeypatch, tmp_path):
    hint = _hint(monkeypatch, tmp_path, venv=True, kind="installed")
    assert 'python3 -m pip install "atoo[ui] @ git+' in hint
    assert " -e " not in hint


def test_a_uv_tool_copy_is_reinstalled_with_the_extra_by_uv(monkeypatch, tmp_path):
    hint = _hint(monkeypatch, tmp_path, venv=True, kind="installed", uv_tool=True)
    assert "installed by uv without it" in hint
    assert 'uv tool install --force "atoo[ui] @ git+https://github.com/corourke/Atoo.git"' in hint
    assert "pipx" not in hint and "pip install" not in hint   # a tool environment has no pip
    assert "https://docs.atoo.app/getting-started/install/" in hint


def test_an_editable_uv_tool_install_is_reinstalled_from_its_checkout(monkeypatch, tmp_path):
    hint = _hint(monkeypatch, tmp_path, venv=True, kind="checkout", uv_tool=True)
    steps = [line.strip() for line in hint.splitlines() if line.startswith("  ")]
    assert steps == [f"cd '{tmp_path / 'my clone'}'",
                     'uv tool install --force --editable ".[ui]"']
    assert "pip install" not in hint and "pipx" not in hint


def test_a_checkouts_uv_venv_is_not_a_tool_environment_and_keeps_the_pip_hint(
        monkeypatch, tmp_path):
    """`uv venv` writes `uv = ...` into pyvenv.cfg just as `uv tool install`
    does; only the tool environment has a receipt, and only it lacks pip."""
    hint = _hint(monkeypatch, tmp_path, venv=True, kind="checkout", uv_venv=True)
    assert hint == ("the web UI needs the 'ui' extra -- install it with:\n"
                    '  python3 -m pip install -e ".[ui]"')


def test_every_environment_gets_its_own_command(monkeypatch, tmp_path_factory):
    """One line per environment: uv tool, pipx, a checkout's virtualenv and
    the system Python, each told the command that works there."""
    def line(**kw):
        hint = _hint(monkeypatch, tmp_path_factory.mktemp("env"), **kw)
        return [l.strip() for l in hint.splitlines() if l.startswith("  ")][-1]

    assert line(venv=True, kind="installed", uv_tool=True).startswith("uv tool install --force ")
    assert line(venv=True, kind="installed", pipx=True).startswith("pipx install --force ")
    assert line(venv=True, kind="checkout") == 'python3 -m pip install -e ".[ui]"'
    assert line(venv=False, kind="installed").startswith("uv tool install --force ")


@pytest.mark.parametrize("situation", [
    dict(venv=True, kind="installed", uv_tool=True),
    dict(venv=True, kind="installed", pipx=True),
    dict(venv=True, kind="installed"),
    dict(venv=False, kind="installed"),
])
def test_once_atoo_is_on_pypi_the_commands_name_the_plain_package(
        monkeypatch, tmp_path, situation):
    """`INSTALL_SOURCE` is the one line that changes."""
    monkeypatch.setattr(install_info, "INSTALL_SOURCE", "")
    hint = _hint(monkeypatch, tmp_path, **situation)
    assert '"atoo[ui]"' in hint and "git+" not in hint and "@" not in hint


def test_a_uv_tool_environment_is_told_from_the_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(install_info.sys, "prefix", str(tmp_path))
    assert not install_info.in_uv_tool_environment()
    (tmp_path / "uv-receipt.toml").write_text("")
    assert install_info.in_uv_tool_environment()
    assert not install_info.in_pipx_environment()


def test_uv_tool_copy_says_installed_copy_at_its_path(tmp_path):
    package = (tmp_path / "uv-env" / "atoo" / "lib" / "python3.12" / "site-packages" / "atoo")
    package.mkdir(parents=True)
    info = install_info.describe(package)
    assert info.kind == "installed"
    assert info.summary() == f"atoo {info.version} (installed copy at {package})"


# ---- the advice to reinstall, in the words of whatever installed this copy ---

def _advice(monkeypatch, tmp_path, **kw) -> str:
    _hint(monkeypatch, tmp_path, **kw)      # sets the environment
    return install_info.reinstall_advice(install_info.describe(tmp_path / "lib" / "python3.12"
                                                              / "site-packages" / "atoo"))


def test_a_uv_tool_copy_is_told_to_reinstall_with_uv(monkeypatch, tmp_path):
    advice = _advice(monkeypatch, tmp_path, venv=True, kind="installed", uv_tool=True)
    assert advice == ('`uv tool install --force --reinstall '
                      '"atoo[ui] @ git+https://github.com/corourke/Atoo.git"`')


def test_a_pipx_copy_is_told_to_reinstall_with_pipx(monkeypatch, tmp_path):
    advice = _advice(monkeypatch, tmp_path, venv=True, kind="installed", pipx=True)
    assert advice == "`pipx reinstall atoo`, or from a checkout `pipx install --force --editable .`"


def test_an_unrecognised_install_hears_uv_first_and_pipx_after(monkeypatch, tmp_path):
    advice = _advice(monkeypatch, tmp_path, venv=False, kind="installed")
    assert advice.startswith('`uv tool install --force --reinstall "atoo[ui] @ git+')
    assert advice.endswith("with pipx, `pipx reinstall atoo`")


def test_init_with_no_starter_set_names_the_installer_that_made_this_copy(
        monkeypatch, tmp_path, capsys):
    from atoo import firstrun
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    empty = tmp_path / "leftover"
    empty.mkdir()
    monkeypatch.setattr(firstrun, "STARTER_DIR", empty)
    prefix = tmp_path / "uv-env" / "atoo"
    prefix.mkdir(parents=True)
    (prefix / "uv-receipt.toml").write_text("")
    monkeypatch.setattr(install_info.sys, "prefix", str(prefix))
    assert main(["init"]) == 1
    err = capsys.readouterr().err
    assert "Reinstall Atoo (`uv tool install --force --reinstall" in err
    assert "pipx" not in err


def test_windows_activates_the_virtualenv_its_own_way(monkeypatch, tmp_path):
    root = tmp_path / "clone"
    (root / "atoo").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    monkeypatch.setattr(install_info.sys, "prefix", "base")
    monkeypatch.setattr(install_info.sys, "base_prefix", "base")
    monkeypatch.setattr(install_info.sys, "platform", "win32")
    monkeypatch.setattr(install_info, "_git_state", lambda root: {"git_note": "x"})
    hint = install_info.ui_extra_hint(install_info.describe(root / "atoo"))
    assert ".venv\\Scripts\\activate" in hint
    assert "source .venv" not in hint


def test_ui_prints_the_hint_and_exits_one_when_the_packages_are_missing(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", None)   # import raises ImportError
    monkeypatch.setattr(install_info, "ui_extra_hint", lambda info=None: "THE HINT")
    assert main(["ui", "--port", "0"]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "THE HINT"
    assert captured.out == ""
