"""~/.atoo.config tests.

`atoo/config.py` is deliberately small and side-effect free except
for printing one stderr line when a config file exists but can't be used
-- see that module's docstring for why every failure mode short-circuits
to None (treated exactly like "no config file") rather than raising.
`tests/test_cli.py` covers how `build()` wires this into the auto-detect
fallback; these tests cover the module in isolation.
"""

from pathlib import Path

from atoo.config import (
    CONFIG_FILENAME, config_path, load_console_defaults, load_default_conventions,
    load_default_watch_conditions,
)


def test_config_path_is_under_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert config_path() == tmp_path / CONFIG_FILENAME


def test_no_config_file_returns_none_silently(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert load_default_conventions() is None
    assert capsys.readouterr().err == ""


def test_valid_config_returns_the_default_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    conventions = tmp_path / "house.md"
    conventions.write_text("# house conventions\n")
    (tmp_path / CONFIG_FILENAME).write_text(
        f'[conventions]\ndefault = "{conventions}"\n'
    )
    assert load_default_conventions() == conventions
    assert capsys.readouterr().err == ""  # nothing to warn about


def test_config_supports_tilde_expansion(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    conventions_dir = tmp_path / "conventions"
    conventions_dir.mkdir()
    (conventions_dir / "house.md").write_text("# house conventions\n")
    (tmp_path / CONFIG_FILENAME).write_text(
        '[conventions]\ndefault = "~/conventions/house.md"\n'
    )
    assert load_default_conventions() == conventions_dir / "house.md"


def test_malformed_toml_falls_through_with_a_stderr_note(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("this is not [ valid toml")
    assert load_default_conventions() is None
    err = capsys.readouterr().err
    assert str(tmp_path / CONFIG_FILENAME) in err
    assert "not valid TOML" in err


def test_missing_conventions_section_falls_through_with_a_stderr_note(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text('[somethingelse]\nkey = "value"\n')
    assert load_default_conventions() is None
    assert "[conventions]" in capsys.readouterr().err


def test_default_key_wrong_type_falls_through_with_a_stderr_note(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("[conventions]\ndefault = 5\n")
    assert load_default_conventions() is None
    assert "default" in capsys.readouterr().err


def test_default_path_that_does_not_exist_falls_through_with_a_stderr_note(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    missing = tmp_path / "nope.md"
    (tmp_path / CONFIG_FILENAME).write_text(f'[conventions]\ndefault = "{missing}"\n')
    assert load_default_conventions() is None
    err = capsys.readouterr().err
    assert str(missing) in err
    assert "does not exist" in err


# ---- [watch_conditions] default -- same TOML shape, same
# failure posture, one section over. Mirrors every test above exactly.


def test_no_config_file_returns_none_silently_for_watch_conditions(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert load_default_watch_conditions() is None
    assert capsys.readouterr().err == ""


def test_valid_config_returns_the_default_watch_conditions_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    watch_conditions = tmp_path / "house.watch.json"
    watch_conditions.write_text('{"version": 2, "watch_conditions": []}\n')
    (tmp_path / CONFIG_FILENAME).write_text(
        f'[watch_conditions]\ndefault = "{watch_conditions}"\n'
    )
    assert load_default_watch_conditions() == watch_conditions
    assert capsys.readouterr().err == ""  # nothing to warn about


def test_watch_conditions_config_supports_tilde_expansion(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    (watch_dir / "house.watch.json").write_text('{"version": 2, "watch_conditions": []}\n')
    (tmp_path / CONFIG_FILENAME).write_text(
        '[watch_conditions]\ndefault = "~/watch/house.watch.json"\n'
    )
    assert load_default_watch_conditions() == watch_dir / "house.watch.json"


def test_malformed_toml_falls_through_with_a_stderr_note_for_watch_conditions(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("this is not [ valid toml")
    assert load_default_watch_conditions() is None
    err = capsys.readouterr().err
    assert str(tmp_path / CONFIG_FILENAME) in err
    assert "not valid TOML" in err


def test_missing_watch_conditions_section_falls_through_with_a_stderr_note(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text('[somethingelse]\nkey = "value"\n')
    assert load_default_watch_conditions() is None
    assert "[watch_conditions]" in capsys.readouterr().err


def test_watch_conditions_default_key_wrong_type_falls_through_with_a_stderr_note(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("[watch_conditions]\ndefault = 5\n")
    assert load_default_watch_conditions() is None
    assert "default" in capsys.readouterr().err


def test_watch_conditions_default_path_that_does_not_exist_falls_through_with_a_stderr_note(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    missing = tmp_path / "nope.watch.json"
    (tmp_path / CONFIG_FILENAME).write_text(f'[watch_conditions]\ndefault = "{missing}"\n')
    assert load_default_watch_conditions() is None
    err = capsys.readouterr().err
    assert str(missing) in err
    assert "does not exist" in err


def test_conventions_and_watch_conditions_defaults_are_independent(tmp_path, monkeypatch, capsys):
    # Both sections can live in the same config file at once, each
    # resolved independently -- one being absent/broken must not affect
    # the other.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    conventions = tmp_path / "house.md"
    conventions.write_text("# house conventions\n")
    watch_conditions = tmp_path / "house.watch.json"
    watch_conditions.write_text('{"version": 2, "watch_conditions": []}\n')
    (tmp_path / CONFIG_FILENAME).write_text(
        f'[conventions]\ndefault = "{conventions}"\n\n'
        f'[watch_conditions]\ndefault = "{watch_conditions}"\n'
    )
    assert load_default_conventions() == conventions
    assert load_default_watch_conditions() == watch_conditions
    assert capsys.readouterr().err == ""


# --- [console] -------------------------------------------
#
# The fourth section, and the first that names something other than a
# path. Two things make it different from the three above, and both are
# worth a test: every key is optional and independent (a port with no
# address is a reasonable thing to set), and a wrong-typed key drops that
# key rather than the whole section.


def test_no_config_file_means_every_console_default_is_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert load_console_defaults() == {"address": None, "port": None, "timeout": None}
    assert capsys.readouterr().err == ""


def test_console_section_supplies_address_port_and_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text(
        '[console]\ndefault = "192.0.2.16"\nport = 9000\ntimeout = 2.5\n'
    )
    assert load_console_defaults() == {"address": "192.0.2.16", "port": 9000, "timeout": 2.5}
    assert capsys.readouterr().err == ""


def test_a_console_section_with_only_a_port_is_valid(tmp_path, monkeypatch, capsys):
    """The address per show from $ATOO_CONSOLE, the port once in the
    config file because this house desk has always been on 9000."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("[console]\nport = 9000\n")
    assert load_console_defaults() == {"address": None, "port": 9000, "timeout": None}
    assert capsys.readouterr().err == ""


def test_an_integer_timeout_is_accepted_as_a_float(tmp_path, monkeypatch):
    """`timeout = 2` is TOML's integer type, and the flag it stands in
    for is `type=float`."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("[console]\ntimeout = 2\n")
    assert load_console_defaults()["timeout"] == 2.0


def test_a_wrong_typed_console_key_drops_that_key_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text(
        '[console]\ndefault = "192.0.2.16"\nport = "two thousand"\n'
    )
    assert load_console_defaults() == {"address": "192.0.2.16", "port": None, "timeout": None}
    err = capsys.readouterr().err
    assert "[console] port should be a number" in err


def test_a_boolean_port_is_refused_rather_than_read_as_one(tmp_path, monkeypatch, capsys):
    """`isinstance(True, int)` is True in Python, so `port = true` would
    otherwise sail through as port 1."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("[console]\nport = true\n")
    assert load_console_defaults()["port"] is None
    assert "[console] port should be a number" in capsys.readouterr().err


def test_an_empty_console_address_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text('[console]\ndefault = "   "\n')
    assert load_console_defaults()["address"] is None
    assert "[console] default should be a console address" in capsys.readouterr().err


def test_no_console_section_at_all_is_silent(tmp_path, monkeypatch, capsys):
    """Unlike the three path sections, a missing [console] is not worth a
    line: a config file that only sets a house conventions file is the
    normal case, not a mistake."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text('[conventions]\ndefault = "/nowhere.md"\n')
    assert load_console_defaults() == {"address": None, "port": None, "timeout": None}
    assert "[console]" not in capsys.readouterr().err


def test_malformed_toml_leaves_console_defaults_empty_with_a_stderr_note(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("[console\ndefault =\n")
    assert load_console_defaults() == {"address": None, "port": None, "timeout": None}
    assert "not valid TOML" in capsys.readouterr().err


def test_console_and_conventions_defaults_are_independent(tmp_path, monkeypatch, capsys):
    """One file, four independent sections -- the same property the
    conventions/watch_conditions pair already has."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    conventions = tmp_path / "house.md"
    conventions.write_text("# house\n")
    (tmp_path / CONFIG_FILENAME).write_text(
        f'[conventions]\ndefault = "{conventions}"\n\n[console]\ndefault = "192.0.2.16"\n'
    )
    assert load_default_conventions() == conventions
    assert load_console_defaults()["address"] == "192.0.2.16"
    assert capsys.readouterr().err == ""


# ---- set_default_conventions: the one thing Atoo writes here --------
#
# Step 01's New file (2026-09-25). `tomllib` cannot write, so the edit is
# one line found and changed -- and every test below is about what it must
# NOT change: every other section, key, comment, blank line and line ending
# in a file someone wrote by hand.

import pytest  # noqa: E402

from atoo.config import (  # noqa: E402
    ConfigWriteError, conventions_default_setting, set_default_conventions,
)

# A config the way a person writes one: comments, blank lines, a watch
# default, a console section, keys in their own order.
HAND_WRITTEN = """\
# my atoo settings -- do not lose this comment
[watch_conditions]
default = "~/conventions/house.watch.json"   # the settled one

[console]
default = "192.0.2.16"
port = 2223
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _new_file(home, name="atoo-rules-house.md"):
    path = home / name
    path.write_text("# blank\n")
    return path


def test_no_config_file_is_created_holding_only_the_default(home):
    target = _new_file(home)
    result = set_default_conventions(target)
    assert result["status"] == "created"
    # `~/...` under the home directory -- the form the docs use.
    assert (home / CONFIG_FILENAME).read_text() == (
        '[conventions]\ndefault = "~/atoo-rules-house.md"\n')
    assert load_default_conventions() == target


def test_a_config_with_other_sections_keeps_every_byte_and_gains_a_section(home, capsys):
    config = home / CONFIG_FILENAME
    config.write_text(HAND_WRITTEN)
    target = _new_file(home)
    watch = home / "conventions" / "house.watch.json"
    watch.parent.mkdir()
    watch.write_text("[]")

    result = set_default_conventions(target)

    assert result["status"] == "added"
    after = config.read_text()
    # The original, untouched, as a prefix -- then the section, after a
    # blank line.
    assert after.startswith(HAND_WRITTEN)
    assert after[len(HAND_WRITTEN):] == '\n[conventions]\ndefault = "~/atoo-rules-house.md"\n'
    # And every section still reads as it did.
    assert load_default_conventions() == target
    assert load_default_watch_conditions() == watch
    assert load_console_defaults() == {"address": "192.0.2.16", "port": 2223, "timeout": None}
    assert capsys.readouterr().err == ""


def test_an_unterminated_last_line_is_terminated_not_joined(home):
    config = home / CONFIG_FILENAME
    config.write_text('[console]\ndefault = "192.0.2.16"')
    set_default_conventions(_new_file(home))
    assert config.read_text() == (
        '[console]\ndefault = "192.0.2.16"\n\n[conventions]\n'
        'default = "~/atoo-rules-house.md"\n')


def test_a_conventions_section_with_no_default_gets_the_key_under_its_header(home):
    config = home / CONFIG_FILENAME
    before = ("# top\n[conventions]\n# the house file goes here\n\n"
              "[console]\nport = 2223\n")
    config.write_text(before)
    set_default_conventions(_new_file(home))
    assert config.read_text() == (
        '# top\n[conventions]\ndefault = "~/atoo-rules-house.md"\n'
        "# the house file goes here\n\n[console]\nport = 2223\n")


def test_a_different_default_is_kept_and_named_unless_replace_is_said(home):
    config = home / CONFIG_FILENAME
    old = _new_file(home, "house.md")
    before = HAND_WRITTEN + '\n[conventions]\ndefault = "~/house.md"\n'
    config.write_text(before)
    target = _new_file(home)

    result = set_default_conventions(target)
    assert result["status"] == "kept"
    assert result["previous"] == "~/house.md"
    assert "~/house.md" in result["message"]
    assert config.read_text() == before  # not one byte
    assert load_default_conventions() == old


def test_replace_rewrites_that_one_line_and_nothing_else(home):
    config = home / CONFIG_FILENAME
    _new_file(home, "house.md")
    before = "[conventions]\n  default = \"~/house.md\"\n\n" + HAND_WRITTEN
    config.write_text(before)

    result = set_default_conventions(_new_file(home), replace=True)

    assert result["status"] == "replaced"
    assert result["previous"] == "~/house.md"
    after = config.read_text()
    assert len(before.splitlines()) == len(after.splitlines())
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    # Its indentation kept, too.
    assert changed == [('  default = "~/house.md"', '  default = "~/atoo-rules-house.md"')]


def test_crlf_line_endings_survive_an_edit(home):
    config = home / CONFIG_FILENAME
    before = '[conventions]\r\ndefault = "/elsewhere/house.md"\r\n[console]\r\nport = 2223\r\n'
    config.write_bytes(before.encode())
    set_default_conventions(_new_file(home), replace=True)
    assert config.read_bytes() == (
        b'[conventions]\r\ndefault = "~/atoo-rules-house.md"\r\n'
        b'[console]\r\nport = 2223\r\n')


def test_a_section_appended_to_a_crlf_file_is_crlf_too(home):
    config = home / CONFIG_FILENAME
    config.write_bytes(b'[console]\r\nport = 2223\r\n')
    set_default_conventions(_new_file(home))
    assert config.read_bytes() == (
        b'[console]\r\nport = 2223\r\n\r\n[conventions]\r\n'
        b'default = "~/atoo-rules-house.md"\r\n')


def test_naming_the_file_it_already_names_changes_nothing(home):
    config = home / CONFIG_FILENAME
    target = _new_file(home)
    before = f'[conventions]\ndefault = "{target}"   # absolute, on purpose\n'
    config.write_text(before)
    result = set_default_conventions(target)
    assert result["status"] == "unchanged"
    assert config.read_text() == before


def test_a_path_outside_home_is_written_absolute(home, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("shared") / "rules.md"
    elsewhere.write_text("x")
    set_default_conventions(elsewhere)
    assert conventions_default_setting() == str(elsewhere)


def test_a_path_with_quotes_and_backslashes_round_trips(home):
    target = home / 'odd "name" \\ here.md'
    target.write_text("x")
    set_default_conventions(target)
    assert load_default_conventions() == target


@pytest.mark.parametrize("before", [
    "[conventions\ndefault = \n",                                   # not TOML
    'conventions.default = "/somewhere/else.md"\n',                 # dotted key
    'conventions = { default = "/somewhere/else.md" }\n',           # inline table
    '[conventions]\ndefault = """\n/somewhere/else.md"""\n',        # multi-line string
    'conventions = "not a table"\n',
])
def test_a_layout_a_one_line_edit_cannot_handle_is_refused_untouched(home, before):
    """Refused, and the file left exactly as it was -- the re-parse check
    is what catches the layouts the line scan did not foresee."""
    config = home / CONFIG_FILENAME
    config.write_text(before)
    with pytest.raises(ConfigWriteError) as exc:
        set_default_conventions(_new_file(home), replace=True)
    assert config.read_text() == before
    assert "by hand" in str(exc.value)


def test_conventions_default_setting_is_silent_and_raw(home, capsys):
    """What the page shows before offering to change anything: the string
    as written, even when the file it names is gone, and no stderr noise
    on every request."""
    assert conventions_default_setting() is None
    (home / CONFIG_FILENAME).write_text('[conventions]\ndefault = "~/gone.md"\n')
    assert conventions_default_setting() == "~/gone.md"
    (home / CONFIG_FILENAME).write_text("[not toml\n")
    assert conventions_default_setting() is None
    assert capsys.readouterr().err == ""


def test_a_section_left_out_of_the_config_is_silent(tmp_path, monkeypatch, capsys):
    # 2026-09-25: a config with only [conventions] announced "expected a
    # [presets] section" on every command of a desk session. Leaving a
    # section out is not a mistake; a section that is there and wrong is.
    house = tmp_path / "house.md"
    house.write_text("# house\n")
    (tmp_path / ".atoo.config").write_text(f'[conventions]\ndefault = "{house}"\n')
    monkeypatch.setenv("HOME", str(tmp_path))
    from atoo import config
    assert config.load_default_presets() is None
    assert config.load_default_watch_conditions() is None
    assert config.load_default_conventions() == house
    assert capsys.readouterr().err == ""


def test_a_section_that_is_there_and_wrong_still_says_so(tmp_path, monkeypatch, capsys):
    from atoo import config
    (tmp_path / ".atoo.config").write_text('[presets]\npath = "/somewhere"\n')
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.load_default_presets() is None
    assert "expected a [presets] section" in capsys.readouterr().err


def test_a_misspelled_section_is_still_reported(tmp_path, monkeypatch, capsys):
    from atoo import config
    (tmp_path / ".atoo.config").write_text('[convention]\ndefault = "/x.md"\n')
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.load_default_conventions() is None
    err = capsys.readouterr().err
    assert "[convention]" in err and "[conventions]" in err
