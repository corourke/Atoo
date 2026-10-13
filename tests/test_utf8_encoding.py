"""Every text read and write in ``atoo/`` names UTF-8.

Python opens a text file in the platform's locale encoding unless told
otherwise -- cp1252 on Windows -- so an accented name or a dash in an
input list, conventions or instructions file is read as garbage there,
and a Save from the browser can write the garbage back.

This is a static scan of the package source: it fails, naming the file
and line, when a new call opens text without ``encoding=``. Binary
opens (a mode containing ``b``) are exempt, as are calls that pass
``encoding`` through ``**kwargs``.

The calls it checks:

- ``open(...)``, ``io.open(...)``, ``os.fdopen(...)`` and
  ``tempfile.NamedTemporaryFile/TemporaryFile/SpooledTemporaryFile(...)``
  in a text mode (``open``'s default is text; the ``tempfile`` ones
  default to binary, so they are flagged only with a text mode);
- ``<path>.open("w")`` and the like -- an ``.open`` attribute call whose
  mode is a text-mode string, which is how ``pathlib.Path.open`` is
  spelled (``webbrowser.open(url)`` and ``opener.open(req)`` take no
  mode string and are not flagged);
- ``<path>.read_text()`` and ``<path>.write_text(...)``;
- ``subprocess.run/check_output/Popen(..., text=True)`` (or
  ``universal_newlines=True``), which decode the child's output in the
  locale encoding too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "atoo"

_TEMPFILE_FUNCS = {"NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"}
_SUBPROCESS_FUNCS = {"run", "check_output", "Popen", "call", "check_call"}


def _kw(call: ast.Call, name: str) -> ast.keyword | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw
    return None


def _has_star_kwargs(call: ast.Call) -> bool:
    return any(kw.arg is None for kw in call.keywords)


def _mode(call: ast.Call, position: int) -> ast.expr | None:
    kw = _kw(call, "mode")
    if kw is not None:
        return kw.value
    if len(call.args) > position:
        return call.args[position]
    return None


def _is_text_mode(mode: ast.expr | None, *, default_text: bool) -> bool:
    if mode is None:
        return default_text
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return "b" not in mode.value
    # A computed mode: assume text, so the call must say its encoding
    # (or be rewritten with a literal mode).
    return True


def _is_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _dotted(func: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def missing_encoding(source: str) -> list[tuple[int, str]]:
    """Return ``(line, call)`` for each text read/write lacking ``encoding=``."""
    return [(node.lineno, name) for node, name in _offending_calls(source)]


def _offending_calls(source: str) -> list[tuple[ast.Call, str]]:
    out: list[tuple[ast.Call, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if _kw(node, "encoding") is not None or _has_star_kwargs(node):
            continue
        name = _dotted(node.func)
        last = name.rsplit(".", 1)[-1]
        flagged = False
        if name in {"open", "io.open"}:
            flagged = _is_text_mode(_mode(node, 1), default_text=True)
        elif name == "os.fdopen":
            flagged = _is_text_mode(_mode(node, 1), default_text=True)
        elif last in _TEMPFILE_FUNCS and name.startswith("tempfile."):
            flagged = _is_text_mode(_mode(node, 0), default_text=False)
        elif last in _SUBPROCESS_FUNCS and name.startswith("subprocess."):
            flagged = _is_true(getattr(_kw(node, "text"), "value", None)) or _is_true(
                getattr(_kw(node, "universal_newlines"), "value", None)
            )
        elif isinstance(node.func, ast.Attribute) and last in {"read_text", "write_text"}:
            flagged = True
        elif isinstance(node.func, ast.Attribute) and last == "open":
            mode = _mode(node, 0)
            flagged = (
                isinstance(mode, ast.Constant)
                and isinstance(mode.value, str)
                and mode.value in {"r", "w", "a", "x", "r+", "w+", "a+", "rt", "wt", "at", "xt"}
            )
        if flagged:
            out.append((node, name or last))
    return out


def test_every_text_read_and_write_in_atoo_names_utf8():
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for line, call in missing_encoding(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(PACKAGE.parent)}:{line}: {call}(...)")
    assert not offenders, (
        "These calls read or write text without encoding=; on Windows they "
        "use cp1252 and garble accented names. Add "
        'encoding="utf-8":\n  ' + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    "src",
    [
        "open(p)",
        "open(p, 'w')",
        "io.open(p, mode='r')",
        "p.read_text()",
        "p.write_text(s)",
        "p.open('w')",
        "os.fdopen(fd, 'w')",
        "tempfile.NamedTemporaryFile('w', delete=False)",
        "subprocess.run(cmd, text=True)",
        "subprocess.check_output(cmd, universal_newlines=True)",
        "open(p, mode)",
    ],
)
def test_scanner_flags_a_text_call_without_encoding(src):
    assert missing_encoding(src), src


@pytest.mark.parametrize(
    "src",
    [
        "open(p, encoding='utf-8')",
        "open(p, 'rb')",
        "open(p, mode='wb')",
        "p.read_text(encoding='utf-8')",
        "p.write_text(s, encoding='utf-8')",
        "p.read_bytes()",
        "p.open('rb')",
        "webbrowser.open(url)",
        "opener.open(req, timeout=5)",
        "link.open()",
        "tempfile.NamedTemporaryFile(delete=False)",
        "subprocess.run(cmd, capture_output=True)",
        "subprocess.run(cmd, text=True, encoding='utf-8')",
        "open(p, **kw)",
    ],
)
def test_scanner_passes_binary_and_explicit_calls(src):
    assert not missing_encoding(src), src


# --- What the encoding is for: an accented name, and Excel's BOM ----------

_LIST = (
    "patch,name,category,type,model,phantom,notes\r\n"
    "LCL 1,Café Vox,vocals,Mic,SM58,FALSE,Ana — lead\r\n"
    "LCL 2,Kick,drums,Mic,Beta 52,FALSE,\r\n"
)


def test_an_accented_input_list_loads_as_written(tmp_path):
    from atoo.input_list import load_input_list

    path = tmp_path / "input.csv"
    path.write_bytes(_LIST.encode("utf-8"))
    rows = load_input_list(str(path))
    assert [r.name for r in rows] == ["Café Vox", "Kick"]
    assert rows[0].notes == "Ana — lead"


def test_a_byte_order_mark_does_not_eat_the_first_column(tmp_path):
    """Excel's "CSV UTF-8" begins with a BOM. Left in, the first header
    reads ``\\ufeffpatch`` and every row's patch silently comes back
    blank."""
    from atoo.input_list import load_input_list, parse_input_list

    path = tmp_path / "input.csv"
    path.write_bytes(b"\xef\xbb\xbf" + _LIST.encode("utf-8"))
    rows = load_input_list(str(path))
    assert [r.patch for r in rows] == ["LCL 1", "LCL 2"]
    assert rows == parse_input_list(_LIST)


def test_promote_reads_the_header_without_the_bom(tmp_path):
    from atoo.promote import _read_input_list

    path = tmp_path / "input.csv"
    path.write_bytes(b"\xef\xbb\xbf" + _LIST.encode("utf-8"))
    header, rows, _text = _read_input_list(path)
    assert header[0] == "patch"
    assert rows[0]["patch"] == "LCL 1"
