"""CLI-level tests -- catches exactly the class of bug found 2026-09-10
by actually running the tool (no output file, no way to target specific
files without a directory scan, and later a subcommand layer that hid
the real options a level below `atoo --help`): unit tests on
compile_plan() alone don't exercise argparse wiring or file I/O at all.

`atoo sandbox` was retired 2026-09-10 (the maintainer: "the syntax needs to
go away -- it's weird") in favor of an easy-button mode: omit
--input/--conventions and it auto-detects an unambiguous pair in the
current directory, or explains why it can't.

The real complaint underneath that, restated the same day ("I just want
it all shown in help!"), was never about subcommands -- it was that
argparse hides a subcommand's options one level down. So `build` is a
subcommand again (apply/extract need their own argument sets), and the
fix is that `atoo --help` splices every subcommand's own options
into one screen. The tests below cover both halves."""

import copy
import json
import re
import socket
import sys
from pathlib import Path

import pytest

from atoo import install_info
from atoo.cli import main
from atoo.diagnostics import Diagnostic, Severity

from conftest import REAL_PLANS

FIXTURES = Path(__file__).parent / "fixtures"


def test_bare_invocation_shows_full_help_including_subcommand_options(capsys):
    # Regression: `atoo` alone used to print argparse's "the
    # following arguments are required: command" stub, and `atoo -h`
    # listed only the command names -- "the input, conventions, out and
    # pretty are totally missing", reported 2026-09-10.
    exit_code = main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    for flag in ("--input", "--conventions", "--out", "--pretty"):
        assert flag in out, f"{flag} missing from top-level help"


def test_explicit_help_flag_shows_the_same_full_help(capsys):
    assert main(["--help"]) == 0
    assert "--pretty" in capsys.readouterr().out


def _copy_smallband(tmp_path):
    (tmp_path / "smallband.csv").write_text((FIXTURES / "smallband.csv").read_text())
    (tmp_path / "smallband.md").write_text((FIXTURES / "smallband.md").read_text())


def test_auto_detects_the_only_pair_in_cwd(stub_build, tmp_path, monkeypatch, capsys):
    stub_build("smallband")
    _copy_smallband(tmp_path)
    monkeypatch.chdir(tmp_path)
    exit_code = main(["build", "--console-model", "wing-compact", "--out", "plan.json", "--skip-verify"])
    assert exit_code == 0
    assert "using the only pair found here" in capsys.readouterr().out
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert len(plan["channels"]) == 9


def test_auto_detect_ambiguous_prints_guidance_not_a_guess(tmp_path, monkeypatch, capsys):
    _copy_smallband(tmp_path)
    (tmp_path / "fullband.csv").write_text((FIXTURES / "fullband.csv").read_text())
    monkeypatch.chdir(tmp_path)
    exit_code = main(["build", "--console-model", "wing-compact"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "ambiguous" in err
    assert "--input" in err and "--conventions" in err
    assert not list(tmp_path.glob("*.plan.json"))


def test_auto_detect_no_csv_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["build", "--console-model", "wing-compact"])
    assert exit_code == 1
    assert "no .csv input list found" in capsys.readouterr().err


# --- ~/.atoo.config fallback ---------------------------
#
# `atoo/config.py` has its own unit tests (tests/test_config.py) for
# every way a config file can be missing/broken. These cover only how
# `build()` wires that module into the auto-detect fallback: it's tried
# when (and only when) the current directory has exactly one .csv and
# ZERO conventions sources, an explicit flag or a locally auto-detected
# pair always wins over it, and its own failures fall through to the
# older "no conventions source found" error rather than crashing.

def _home_config(tmp_path, monkeypatch, default_conventions):
    """A fake $HOME, separate from the cwd this test also sets up, with
    .atoo.config pointing at `default_conventions` (a Path)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    (home / ".atoo.config").write_text(
        f'[conventions]\ndefault = "{default_conventions}"\n'
    )


def test_config_default_used_when_csv_present_and_no_conventions_found(stub_build, tmp_path, monkeypatch, capsys):
    stub_build("smallband")
    work = tmp_path / "work"
    work.mkdir()
    (work / "smallband.csv").write_text((FIXTURES / "smallband.csv").read_text())
    monkeypatch.chdir(work)

    house = tmp_path / "house.md"
    house.write_text((FIXTURES / "smallband.md").read_text())
    _home_config(tmp_path, monkeypatch, house)

    exit_code = main(["build", "--console-model", "wing-compact", "--out", "plan.json", "--skip-verify"])
    assert exit_code == 0

    err = capsys.readouterr().err
    assert str(tmp_path / "home" / ".atoo.config") in err
    assert str(house) in err
    assert "smallband.csv" in err

    plan = json.loads((work / "plan.json").read_text())
    assert len(plan["channels"]) == 9


def test_config_default_not_used_when_local_conventions_found(stub_build, tmp_path, monkeypatch, capsys):
    # Auto-detect already finds an unambiguous pair here -- the config
    # default must never even be consulted, let alone override it. Proven
    # by pointing the config at a file that doesn't exist: if it were
    # read, load_default_conventions() would print an "ignoring it" note.
    stub_build("smallband")
    work = tmp_path / "work"
    work.mkdir()
    _copy_smallband(work)
    monkeypatch.chdir(work)
    _home_config(tmp_path, monkeypatch, tmp_path / "does-not-exist.md")

    exit_code = main(["build", "--console-model", "wing-compact", "--out", "plan.json", "--skip-verify"])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "atoo.config" not in err
    assert "ignoring it" not in err


def test_config_default_not_used_when_conventions_given_explicitly(stub_build, tmp_path, monkeypatch, capsys):
    # Same proof, for the explicit-flag case rather than local auto-detect.
    stub_build("smallband")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # no config file at all here
    out_path = tmp_path / "plan.json"
    exit_code = main([
        "build", "--console-model", "wing-compact", "--skip-verify",
        "--input", str(FIXTURES / "smallband.csv"),
        "--conventions", str(FIXTURES / "smallband.md"),
        "--out", str(out_path),
    ])
    assert exit_code == 0
    assert out_path.exists()


def test_missing_config_file_falls_through_to_existing_error(tmp_path, monkeypatch, capsys):
    work = tmp_path / "work"
    work.mkdir()
    (work / "smallband.csv").write_text((FIXTURES / "smallband.csv").read_text())
    monkeypatch.chdir(work)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home-with-no-config")

    exit_code = main(["build", "--console-model", "wing-compact"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "no --conventions given" in err
    assert not list(work.glob("*.plan.json"))


def test_malformed_config_falls_through_to_existing_error_not_a_crash(tmp_path, monkeypatch, capsys):
    work = tmp_path / "work"
    work.mkdir()
    (work / "smallband.csv").write_text((FIXTURES / "smallband.csv").read_text())
    monkeypatch.chdir(work)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    (home / ".atoo.config").write_text("not [ valid toml at all")

    exit_code = main(["build", "--console-model", "wing-compact"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "not valid TOML" in err  # config.py's own note
    # ...and it still falls all the way through to the older message,
    # not a traceback.
    assert "no --conventions given" in err


def test_config_default_pointing_at_a_missing_file_falls_through(tmp_path, monkeypatch, capsys):
    work = tmp_path / "work"
    work.mkdir()
    (work / "smallband.csv").write_text((FIXTURES / "smallband.csv").read_text())
    monkeypatch.chdir(work)
    _home_config(tmp_path, monkeypatch, tmp_path / "ghost.md")

    exit_code = main(["build", "--console-model", "wing-compact"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "does not exist" in err
    assert "no --conventions given" in err


def test_explicit_input_and_conventions(stub_build, tmp_path):
    stub_build("smallband")
    out_path = tmp_path / "plan.json"
    exit_code = main([
        "build", "--console-model", "wing-compact", "--skip-verify",
        "--input", str(FIXTURES / "smallband.csv"),
        "--conventions", str(FIXTURES / "smallband.md"),
        "--out", str(out_path),
    ])
    assert exit_code == 0
    assert out_path.exists()


def test_input_without_conventions_is_a_clear_error(capsys):
    # --conventions/--ai-conventions are no longer an argparse-required
    # group (both are legitimately absent together, for auto-detect) --
    # so this is build()'s own validation, a clean exit(1), not argparse's
    # SystemExit(2).
    exit_code = main(["build", "--console-model", "wing-compact", "--input", str(FIXTURES / "smallband.csv")])
    assert exit_code == 1


def test_pretty_and_out_together(stub_build, tmp_path):
    stub_build("smallband")
    out_path = tmp_path / "plan.json"
    exit_code = main([
        "build", "--console-model", "wing-compact", "--skip-verify",
        "--input", str(FIXTURES / "smallband.csv"),
        "--conventions", str(FIXTURES / "smallband.md"),
        "--out", str(out_path),
        "--pretty",
    ])
    assert exit_code == 0
    assert out_path.exists()
    plan = json.loads(out_path.read_text())
    assert plan["channels"][0]["patch"]["group"] == "LCL"


def test_pretty_prints_a_current_plan(stub_build, tmp_path, capsys):
    """`build --pretty` crashed (KeyError: 'conventions_file') after
    writing the plan, on every plan built since the texts moved to `meta`.
    The test above never saw it: its frozen plan still carries the dead
    top-level keys. A current plan has neither."""
    plan = stub_build("smallband")
    plan.pop("conventions_file", None)
    plan.pop("input_list", None)
    exit_code = main([
        "build", "--console-model", "wing-compact", "--skip-verify",
        "--input", str(FIXTURES / "smallband.csv"),
        "--conventions", str(FIXTURES / "smallband.md"),
        "--out", str(tmp_path / "plan.json"),
        "--pretty",
    ])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert f"  conventions: {FIXTURES / 'smallband.md'}" in out
    assert f"  input list:  {FIXTURES / 'smallband.csv'}" in out


def test_conventions_and_ai_conventions_together_is_a_clear_error():
    # argparse's own mutually-exclusive group catches this before build()
    # runs -- SystemExit, not a return value, same shape argparse always
    # uses for a bad combination of arguments.
    with pytest.raises(SystemExit) as exc_info:
        main([
            "build", "--console-model", "wing-compact", "--skip-verify",
            "--input", str(FIXTURES / "smallband.csv"),
            "--conventions", str(FIXTURES / "smallband.md"),
            "--ai-conventions", str(FIXTURES / "smallband.md"),
        ])
    assert exc_info.value.code == 2


def test_no_out_given_writes_a_default_named_file(stub_build, tmp_path, monkeypatch):
    # Regression: "the atoo command does not create an output file
    # at all, just console output" -- reported 2026-09-10, right after
    # --out's default reverted to stdout-only when `sandbox` (which
    # always wrote a file) was folded into `build`. --out now defaults to
    # a derived filename, not stdout.
    stub_build("smallband")
    monkeypatch.chdir(tmp_path)
    exit_code = main([
        "build", "--console-model", "wing-compact", "--skip-verify",
        "--input", str(FIXTURES / "smallband.csv"),
        "--conventions", str(FIXTURES / "smallband.md"),
    ])
    assert exit_code == 0
    out_path = tmp_path / "smallband+smallband.plan.json"
    assert out_path.exists()
    plan = json.loads(out_path.read_text())
    assert len(plan["channels"]) == 9


def test_out_dash_prints_to_stdout_instead_of_writing_a_file(stub_build, tmp_path, monkeypatch, capsys):
    stub_build("smallband")
    monkeypatch.chdir(tmp_path)
    exit_code = main([
        "build", "--console-model", "wing-compact", "--skip-verify",
        "--input", str(FIXTURES / "smallband.csv"),
        "--conventions", str(FIXTURES / "smallband.md"),
        "--out", "-",
    ])
    assert exit_code == 0
    assert not list(tmp_path.glob("*.plan.json"))
    plan = json.loads(capsys.readouterr().out)
    assert len(plan["channels"]) == 9


def test_audit_with_plan_runs_conventions_diff(tmp_path, capsys):
    # FR-4.1's conventions-diff mode (first slice): --plan adds
    # findings on top of whichever live-state source (--state here) was
    # already selected, independent of it.
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "/ch/1/name": "Kick",
        "/ch/1/mute": 0,
    }))
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps({
        "channels": [{
            "channel": 1, "bank": "ch", "name": "Kick", "color": None,
            "source": {"input": "Kick", "type": "Mic", "model": "", "stereo": False, "phantom": False},
            "patch": {"group": "LCL", "sockets": [1], "stated": True},
            "processing": {"hpf_hz": None, "preset": None},
            "fader": {"fader_db": None, "muted": True},
            "dca": [], "mute_group": [], "bus_sends": [], "main_routes": [],
            "provenance": {"fader": "Drums convention: kick starts muted at top of show"},
        }],
        "dcas": {}, "mute_groups": {}, "busses": {}, "outputs": {},
    }))

    exit_code = main([
        "audit", "--state", str(state_file), "--plan", str(plan_file),
    ])
    assert exit_code == 0  # WARNING-only findings don't fail the run
    out = capsys.readouterr().out
    assert "CV001" in out
    assert "Drums convention" in out


# --- audit --plan scopes the structural rules too (FR-4.5) ----
#
# `atoo/audit.py` decides what a plan puts out of scope and
# `tests/test_audit_scope.py` covers that in detail. These three cover
# only the wiring: that `audit_cmd` hands the plan to `run_audit` at all,
# that the withheld count reaches the printed report, and that no plan
# still means no scoping.


def _scope_case(tmp_path):
    """A desk with one planned channel and one strip nobody planned, both
    routed and unmuted with the fader on the floor. The unplanned strip
    trips a convention rule (E003, an effect inserted and switched off)
    and a hazard (L002, routed and silent) -- so one finding about it must
    go and the other must stay."""
    state_file = tmp_path / "state.json"
    # Routed via a bus send rather than a Main, so the fixture trips only
    # the two rules it is about -- an unpatched Main would add an
    # unrelated R005 ERROR and change the exit code.
    state_file.write_text(json.dumps({
        "/ch/1/name": "Kick", "/ch/1/mute": 0, "/ch/1/fdr": -144.0, "/ch/1/send/1/on": 1,
        "/ch/1/tags": "#D1", "/dca/1/name": "Drums",
        "/ch/30/name": "Somebody Elses", "/ch/30/mute": 0, "/ch/30/fdr": -144.0,
        "/ch/30/send/1/on": 1,
        "/ch/30/preins/ins": "FX1", "/ch/30/preins/on": 0, "/fx/1/mdl": "HALL",
    }))
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps({
        "channels": [{
            "channel": 1, "bank": "ch", "name": "Kick", "color": None,
            "source": {"input": "Kick", "type": "Mic", "model": "", "stereo": False, "phantom": False},
            "patch": {}, "processing": {}, "fader": {"fader_db": -144, "muted": None},
            "dca": ["Drums"], "mute_group": [], "bus_sends": [], "main_routes": [],
            "provenance": {},
        }],
        "dcas": {"Drums": {"index": 1}}, "mute_groups": {}, "busses": {}, "outputs": {},
    }))
    return state_file, plan_file


def test_audit_with_plan_withholds_out_of_scope_findings_and_says_so(tmp_path, capsys):
    state_file, plan_file = _scope_case(tmp_path)

    assert main(["audit", "--state", str(state_file), "--plan", str(plan_file)]) == 0
    out = capsys.readouterr().out

    # The convention finding about the unplanned strip is gone as a
    # finding -- its rendered block is not there...
    assert "[INFO] E003" not in out
    assert "but the insert is switched off" not in out
    # ...but never silently: it is still named, counted and explained.
    assert "[INFO] S001" in out
    assert "1 E003 (1 about an object the plan never mentions)" in out


def test_audit_with_plan_keeps_a_hazard_about_an_unplanned_strip(tmp_path, capsys):
    """A routed, unmuted, silent strip that is NOT part of
    your show is the classic why-can't-I-hear-it, and is the single most
    useful thing L002 ever says. Withholding it is the failure
    direction that hides something real."""
    state_file, plan_file = _scope_case(tmp_path)

    assert main(["audit", "--state", str(state_file), "--plan", str(plan_file)]) == 0
    out = capsys.readouterr().out

    assert "L002" in out
    assert "CH 30" in out
    # ...while the planned channel whose fader the plan itself put on the
    # floor does not appear under that rule.
    assert 'CH 1 "Kick" is unmuted' not in out


def test_audit_without_a_plan_withholds_nothing(tmp_path, capsys):
    state_file, _ = _scope_case(tmp_path)

    assert main(["audit", "--state", str(state_file)]) == 0
    out = capsys.readouterr().out

    assert "E003" in out
    assert "L002" in out
    assert "S001" not in out


# --- watch --watch-conditions ---------------------------------
#
# atoo/watch_conditions.py has its own unit tests
# (tests/test_watch_conditions.py) for loading and evaluation. These cover
# only how `watch_cmd` wires it in: a good file's findings show up in the
# existing watch/audit output alongside built-in structural findings, and a
# bad path is a clean exit(1) before any console connection is attempted.

# The audit/watch demo state, as a TEST fixture rather than the copy in
# `examples/`. "examples is really for
# experimentation and user testing" -- so a user editing
# `examples/audit_demo_state.json` to try something must not turn the
# suite red. The two files are byte-identical today and serve different
# purposes: the example is there to be changed, this one is not.
DEMO = Path(__file__).parent / "fixtures"


def test_watch_with_watch_conditions_reports_a_finding_in_baseline(tmp_path, capsys):
    # examples/audit_demo_state.json's "Kick" channel is unmuted -- assert
    # the opposite (must always be muted) so this condition is guaranteed
    # to fire, appearing in the baseline alongside built-in rule findings (R005, C001, ...).
    conditions_file = tmp_path / "conditions.json"
    conditions_file.write_text(json.dumps({
        "version": 2, "watch_conditions": [{
            "id": "kick-must-be-muted",
            "description": "Kick must be muted (test fixture)",
            "channel": "Kick",
            "field": "muted",
            "operator": "!=",
            "value": True,
            "severity": "warning",
        }]
    }))

    exit_code = main([
        "watch",
        "--state-sequence", str(DEMO / "audit_demo_state.json"),
        "--watch-conditions", str(conditions_file),
        "--count", "1",
    ])
    assert exit_code == 0  # WARNING-only findings don't fail the run
    out = capsys.readouterr().out
    assert "WATCH:kick-must-be-muted" in out
    assert "baseline" in out
    # A built-in structural finding is still present alongside it -- the
    # extra rules ADD to DEFAULT_RULES, they don't replace it.
    assert re.search(r"\b(?:R|C|CH|CV|L|E|N|T|W|S)\d{3}\b", out)


def test_watch_with_bad_watch_conditions_path_exits_1_cleanly(tmp_path, capsys):
    missing = tmp_path / "does-not-exist.json"
    exit_code = main([
        "watch",
        "--state-sequence", str(DEMO / "audit_demo_state.json"),
        "--watch-conditions", str(missing),
    ])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert str(missing) in captured.err
    assert "Traceback" not in captured.err
    # No console-connection attempt was made -- no "Watching ..." banner
    # or console-identity line on stdout.
    assert "Watching" not in captured.out


def test_watch_with_invalid_watch_conditions_exits_1_cleanly(tmp_path, capsys):
    conditions_file = tmp_path / "bad.json"
    conditions_file.write_text(json.dumps({
        "version": 2, "watch_conditions": [{
            "id": "bad", "description": "bad", "channel": "Kick",
            # `dca` stood in for "unknown field" here until an earlier change made
            # it a real one; `gain` is still genuinely unknown.
            "field": "gain", "operator": "!=", "value": True, "severity": "warning",
        }]
    }))
    exit_code = main([
        "watch",
        "--state-sequence", str(DEMO / "audit_demo_state.json"),
        "--watch-conditions", str(conditions_file),
    ])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "unknown field" in err


# --- ~/.atoo.config [watch_conditions] default fallback --
#
# Same "explicit flag always wins, config default only fills in when the
# flag is omitted" precedence as the [conventions] default above (see
# `_home_config`/its own tests) -- `tests/test_config.py` covers every way
# `load_default_watch_conditions()` itself can be missing/broken; these
# cover only how `watch_cmd`/`ui_cmd` wire it in.

def _home_watch_conditions_config(tmp_path, monkeypatch, default_watch_conditions):
    """A fake $HOME with .atoo.config pointing its [watch_conditions]
    default at `default_watch_conditions` (a Path)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    (home / ".atoo.config").write_text(
        f'[watch_conditions]\ndefault = "{default_watch_conditions}"\n'
    )


def test_watch_uses_config_default_watch_conditions_when_flag_omitted(tmp_path, monkeypatch, capsys):
    house_conditions = tmp_path / "house.watch.json"
    house_conditions.write_text(json.dumps({
        "version": 2, "watch_conditions": [{
            "id": "kick-must-be-muted",
            "description": "Kick must be muted (test fixture)",
            "channel": "Kick",
            "field": "muted",
            "operator": "!=",
            "value": True,
            "severity": "warning",
        }]
    }))
    _home_watch_conditions_config(tmp_path, monkeypatch, house_conditions)

    exit_code = main([
        "watch",
        "--state-sequence", str(DEMO / "audit_demo_state.json"),
        "--count", "1",
    ])
    assert exit_code == 0
    out, err = capsys.readouterr()
    assert "WATCH:kick-must-be-muted" in out
    assert str(house_conditions) in err  # the "using the default from ..." note


def test_watch_explicit_flag_wins_over_config_default(tmp_path, monkeypatch, capsys):
    # Point the config default at a file that doesn't exist -- if it were
    # consulted at all, load_default_watch_conditions() would print an
    # "ignoring it"/"does not exist" note. The explicit --watch-conditions
    # below must win outright, with the config default never even read.
    _home_watch_conditions_config(tmp_path, monkeypatch, tmp_path / "does-not-exist.json")

    conditions_file = tmp_path / "explicit.watch.json"
    conditions_file.write_text(json.dumps({
        "version": 2, "watch_conditions": [{
            "id": "kick-must-be-muted",
            "description": "Kick must be muted (test fixture)",
            "channel": "Kick",
            "field": "muted",
            "operator": "!=",
            "value": True,
            "severity": "warning",
        }]
    }))

    exit_code = main([
        "watch",
        "--state-sequence", str(DEMO / "audit_demo_state.json"),
        "--watch-conditions", str(conditions_file),
        "--count", "1",
    ])
    assert exit_code == 0
    out, err = capsys.readouterr()
    assert "WATCH:kick-must-be-muted" in out
    assert "ignoring it" not in err
    assert "does not exist" not in err


def test_watch_with_no_flag_and_no_config_default_behaves_as_before(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # no config file at all here
    exit_code = main([
        "watch",
        "--state-sequence", str(DEMO / "audit_demo_state.json"),
        "--count", "1",
    ])
    assert exit_code == 0
    out, err = capsys.readouterr()
    assert "WATCH:" not in out
    # Nothing to report -- no config file, and no note about it -- but the
    # install line every desk command prints first.
    assert err.splitlines() == [install_info.describe().summary()]


# --- `atoo ui` --watch-conditions ------------------------
#
# ui_cmd hands off to a uvicorn server that would otherwise block forever
# -- monkeypatched out here the same way every test below needs it, so
# these only ever check the argument-parsing/validation/create_app-wiring
# behavior that runs before that point.
#
# The stub is `stub_ui_server` in conftest.py, shared with
# test_console_address.py, which had its own copy until an earlier change broke
# one of them. It stubs `uvicorn.Server.run` rather than `uvicorn.run`,
# because an earlier change moved `ui_cmd` off the latter: the listening socket is now
# bound by `ui_cmd` itself, BEFORE the URL banner, and handed to the
# server. So the bind here is real, which is why every one of these passes
# `--port 0` and lets the kernel pick -- a test that hard-coded the
# default port would collide with anything already on it.

def test_ui_watch_conditions_flag_accepted_without_reaching_network(stub_ui_server, capsys):
    calls = stub_ui_server
    exit_code = main(["ui", "--port", "0", "--watch-conditions", str(FIXTURES / "sample.watch.json")])
    assert exit_code == 0
    assert len(calls) == 1  # the server was reached exactly once, and never actually served
    out = capsys.readouterr().out
    assert "Watch conditions:" in out
    assert str(FIXTURES / "sample.watch.json") in out


def test_ui_watch_conditions_flag_with_bad_path_fails_fast(stub_ui_server, tmp_path, capsys):
    calls = stub_ui_server
    missing = tmp_path / "does-not-exist.json"
    exit_code = main(["ui", "--port", "0", "--watch-conditions", str(missing)])
    assert exit_code == 1
    assert calls == []  # never reached the server -- failed before binding a socket
    err = capsys.readouterr().err
    assert str(missing) in err


def test_ui_uses_config_default_watch_conditions_when_flag_omitted(tmp_path, monkeypatch, stub_ui_server, capsys):
    calls = stub_ui_server
    house_conditions = tmp_path / "house.watch.json"
    house_conditions.write_text(json.dumps({"version": 2, "watch_conditions": []}))
    _home_watch_conditions_config(tmp_path, monkeypatch, house_conditions)

    exit_code = main(["ui", "--port", "0"])
    assert exit_code == 0
    assert len(calls) == 1
    out, err = capsys.readouterr()
    assert str(house_conditions) in out  # "Watch conditions: ..." startup line
    assert str(house_conditions) in err  # "using the default from ..." note


def test_ui_with_no_flag_and_no_config_default_behaves_as_before(tmp_path, monkeypatch, stub_ui_server, capsys):
    calls = stub_ui_server
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # no config file at all here
    exit_code = main(["ui", "--port", "0"])
    assert exit_code == 0
    assert len(calls) == 1
    out, err = capsys.readouterr()
    assert "Watch conditions:" not in out
    assert err == ""
    assert "Traceback" not in err


# --- `atoo ui` cannot start ------------------------------
#
# The commonest way `ui` fails to start is a port already in use, and it
# used to be the one way `ui` handled badly: three URLs promised on stdout,
# then uvicorn's own `ERROR:` line on stderr, then exit 3 -- a code
# `docs/user/cli-reference.md`'s canonical table does not list, leaking out
# of `uvicorn.config.Config.bind_socket`'s `sys.exit(STARTUP_FAILURE)`.
#
# These take a real listener rather than stubbing one, because the whole
# defect is about what a real bind failure does. `stub_ui_server` is
# deliberately NOT used: nothing should get as far as a server.


def _hold_a_port():
    """A bound, listening socket, and the port it holds. Closed by the
    caller."""
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    return holder, holder.getsockname()[1]


def test_ui_on_a_busy_port_exits_1_not_uvicorns_3(capsys):
    pytest.importorskip("uvicorn")
    holder, port = _hold_a_port()
    try:
        assert main(["ui", "--port", str(port)]) == 1
    finally:
        holder.close()


def test_ui_on_a_busy_port_promises_no_url_it_cannot_keep(capsys):
    """The half that is the actual defect. A wrong exit code is
    recoverable; an address printed for a server that never started is a
    lie, and the user opens it."""
    pytest.importorskip("uvicorn")
    holder, port = _hold_a_port()
    try:
        main(["ui", "--port", str(port)])
    finally:
        holder.close()
    out, err = capsys.readouterr()
    assert out == ""
    assert "http://" not in out
    # Atoo's voice, naming what it could not do -- not uvicorn's
    # "ERROR:    [Errno 98] error while attempting to bind on address".
    assert f"127.0.0.1:{port}" in err
    assert "ERROR:" not in err
    assert f"--port {port + 1}" in err  # the way out, for the error that has one


def test_ui_on_an_unassignable_host_does_not_blame_the_port(capsys):
    """A bad --host fails at the same bind, and the "try the next port up"
    advice would send someone round the same wall. It is EADDRINUSE's
    advice, not every OSError's."""
    pytest.importorskip("uvicorn")
    assert main(["ui", "--host", "203.0.113.254"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "203.0.113.254" in err
    assert "--port" not in err


def test_ui_announces_the_port_it_got_not_the_one_it_asked_for(stub_ui_server, capsys):
    """`--port 0` means "you pick". Printing the request back gives
    http://127.0.0.1:0, which nothing can open."""
    assert main(["ui", "--port", "0", "--no-browser"]) == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:0 " not in out
    url = [line for line in out.splitlines() if line.startswith("Atoo: http")]
    assert len(url) == 1
    announced = int(url[0].split("http://127.0.0.1:")[1].split()[0])
    assert announced > 0


# --------------------------------------------------------------------------
# diagnostics reach a human distinguishably, not as one
# undifferentiated bullet list. This is the issue's actual acceptance
# criterion -- the engine change was only ever a means to it, and before
# this nothing in the suite asserted on the rendered output at all.
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Show bundles: one directory, fixed filenames, no manifest.
# Precedence everywhere: explicit flag > --show > auto-detect > config.
# --------------------------------------------------------------------------

# The house conventions file, which lives OUTSIDE any bundle (an earlier change point 5,
# reaffirmed by the maintainer 2026-09-20: "conventions.md is not a part of the
# show... It should be referenced by a config file or a command line
# option"). Every bundle build below passes it explicitly.
HOUSE = FIXTURES / "smallband.md"


def _bundle(tmp_path, *, conventions=True, stale_expectations=False, watch=False):
    """A show bundle laid out the way a user would lay one out by hand.

    `conventions=True` puts an `instructions.md` in it -- per-show text
    that *layers over* the house file, never replaces it.

    `stale_expectations=True` drops an `expectations.toml` in it. That was
    a bundle slot until an earlier change retired the feature; a real bundle on a real
    laptop still has one sitting in it, and nothing may notice.
    """
    d = tmp_path / "my-show"
    d.mkdir(parents=True)
    (d / "input.csv").write_text((FIXTURES / "smallband.csv").read_text())
    if conventions:
        (d / "instructions.md").write_text(
            "# Instructions for this show\n\nFour monitor mixes, MON1-4.\n")
    if stale_expectations:
        (d / "expectations.toml").write_text("[plan]\nchannels = 9999\n")
    if watch:
        (d / "watch.json").write_text(json.dumps({
            "version": 2, "watch_conditions": [{
                "id": "from-the-bundle",
                "description": "Kick must be muted (bundle fixture)",
                "channel": "Kick", "field": "muted",
                "operator": "!=", "value": True, "severity": "warning",
            }]
        }))
    return d


def test_build_show_resolves_the_bundle_and_writes_the_plan_into_it(stub_build, tmp_path, capsys):
    stub_build("smallband")
    d = _bundle(tmp_path)
    assert main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d), "--conventions", str(HOUSE)]) == 0
    # An earlier change point 4: generated artifacts land in the bundle, not wherever
    # --out happened to point.
    plan = json.loads((d / "plan.json").read_text())
    assert plan["channels"], "the plan should have been written into the bundle"


def test_build_show_ignores_a_leftover_expectations_file(stub_build, tmp_path, capsys):
    """An earlier change retired expectations. A bundle directory someone laid out last
    month still holds an `expectations.toml`, and that must be neither read
    nor complained about -- an old bundle keeps building."""
    stub_build("smallband")
    d = _bundle(tmp_path, stale_expectations=True)
    code = main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d), "--conventions", str(HOUSE)])
    captured = capsys.readouterr()
    assert code == 0
    # The leftover file asserts an impossible channel count, so any mention
    # of it -- or of 9999 -- would mean something still read it.
    assert "9999" not in captured.err + captured.out
    assert "expectations" not in (captured.err + captured.out).lower()
    assert json.loads((d / "plan.json").read_text())["channels"]


def test_an_explicit_flag_always_wins_over_the_bundle(stub_build, tmp_path, capsys):
    """The precedence --watch-conditions already has over ~/.atoo.config, applied to every bundle slot."""
    stub_build("smallband")
    d = _bundle(tmp_path)
    elsewhere = tmp_path / "elsewhere.plan.json"
    assert main([
        "build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d),
        "--conventions", str(HOUSE), "--out", str(elsewhere),
    ]) == 0
    assert elsewhere.is_file()
    assert not (d / "plan.json").exists(), "--out should have won over the bundle slot"


def test_build_show_without_an_input_list_says_which_filename_it_wanted(tmp_path, capsys):
    d = tmp_path / "not-a-bundle"
    d.mkdir()
    (d / "touringband.csv").write_text("name,category\n")  # right idea, wrong name
    assert main(["build", "--console-model", "wing-compact", "--show", str(d), "--conventions", str(HOUSE)]) == 1
    err = capsys.readouterr().err
    assert "input.csv" in err
    assert str(d) in err


def test_build_names_an_invalid_input_list_by_its_file_name(tmp_path, capsys):
    """The line names the file, and only by its name -- it is
    also the line the Build page's dock quotes when a build fails, where a
    full path would put the home folder into a shared screenshot."""
    d = tmp_path / "fest"
    d.mkdir()
    (d / "input.csv").write_text("name,category,type,phantom\nClick Track,,,FALSE\n")
    assert main(["build", "--console-model", "wing-compact", "--show", str(d),
                 "--conventions", str(HOUSE)]) == 1
    err = capsys.readouterr().err
    assert ("input list error in input.csv: row 2: 'category' and 'type' are required "
            "and cannot be blank") in err
    assert str(tmp_path) not in err


def test_show_pointed_at_a_file_is_a_clear_error(tmp_path, capsys):
    f = tmp_path / "plan.json"
    f.write_text("{}")
    assert main(["build", "--console-model", "wing-compact", "--show", str(f), "--conventions", str(HOUSE)]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_show_pointed_at_a_missing_directory_is_a_clear_error(tmp_path, capsys):
    assert main(["build", "--console-model", "wing-compact", "--show", str(tmp_path / "nope"),
                 "--conventions", str(HOUSE)]) == 1
    assert "no such directory" in capsys.readouterr().err


def test_audit_show_takes_the_plan_from_the_bundle(stub_build, tmp_path, capsys):
    stub_build("smallband")
    d = _bundle(tmp_path)
    main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d), "--conventions", str(HOUSE)])
    capsys.readouterr()

    # Same state file both ways: with the bundle's plan resolved, the
    # conventions-diff rules (FR-4.1) add findings the structural rules
    # alone don't produce.
    main(["audit", "--state", str(DEMO / "audit_demo_state.json")])
    without_plan = capsys.readouterr().out
    main(["audit", "--state", str(DEMO / "audit_demo_state.json"), "--show", str(d)])
    with_plan = capsys.readouterr().out
    assert len(with_plan) > len(without_plan)
    assert "CV" in with_plan and "CV" not in without_plan


def test_watch_show_takes_watch_conditions_from_the_bundle(tmp_path, capsys):
    d = _bundle(tmp_path, watch=True)
    assert main([
        "watch", "--state-sequence", str(DEMO / "audit_demo_state.json"),
        "--show", str(d), "--count", "1",
    ]) == 0
    out = capsys.readouterr().out
    assert "WATCH:from-the-bundle" in out
    assert re.search(r"\b(?:R|C|CH|CV|L|E|N|T|W|S)\d{3}\b", out)  # still alongside the built-in structural rules


def test_ui_show_loads_both_the_plan_and_the_watch_conditions(stub_build, tmp_path, monkeypatch, stub_ui_server, capsys):
    stub_build("smallband")
    d = _bundle(tmp_path, watch=True)
    main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d), "--conventions", str(HOUSE)])
    capsys.readouterr()

    calls = stub_ui_server
    assert main(["ui", "--port", "0", "--show", str(d)]) == 0
    assert len(calls) == 1
    out = capsys.readouterr().out
    assert str(d / "plan.json") in out
    assert str(d / "watch.json") in out


def test_apply_without_plan_or_show_explains_both_ways_to_supply_one(capsys):
    """--plan stopped being argparse-required so --show could supply it;
    the error it used to give must not have gone with it."""
    assert main(["apply", "--console", "192.0.2.1"]) == 1
    err = capsys.readouterr().err
    assert "--plan" in err and "--show" in err


def test_flat_invocations_are_completely_unchanged_by_the_bundle_work(stub_build, tmp_path, capsys):
    """An earlier change is explicit: a bundle is an additional way to invoke, never a
    replacement. The existing flat-file form must behave identically."""
    stub_build("smallband")
    out = tmp_path / "flat.plan.json"
    assert main([
        "build", "--console-model", "wing-compact", "--skip-verify",
        "--input", str(FIXTURES / "smallband.csv"),
        "--conventions", str(FIXTURES / "smallband.md"),
        "--out", str(out),
    ]) == 0
    assert json.loads(out.read_text())["channels"]


# --------------------------------------------------------------------------
# the acceptance criterion, restated for the newer world.
#
# The original pair of tests here drove the *conventions parser's* own
# diagnostics (a '## Watch' heading the templated grammar couldn't read, a
# rule detail the compiler couldn't carry) through `build`. Both of those
# producers were deleted with the compile path, so the tests could
# not survive their subject. What an earlier change actually asked for -- that what
# reaches a human is severity-labelled and blocked, not one
# undifferentiated bullet list -- is still true of every stream that
# remains, and that is what these assert.
#
# The renderer itself is covered directly in test_diagnostics.py.
# --------------------------------------------------------------------------

def test_a_generated_plans_notes_render_through_the_one_renderer(tmp_path, monkeypatch, capsys):
    plan = copy.deepcopy(REAL_PLANS["smallband"])
    plan["notes"] = [
        {"text": "no socket stated for 'Kick' -- auto-assigned LCL 1", "source": "generator"},
        {"text": "the conventions ask for a DCA named 'Band'; no input row matches",
         "source": "generator"},
    ]
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: object())
    monkeypatch.setattr("atoo.generate.generate_plan", lambda *a, **k: copy.deepcopy(plan))

    main(["build", "--console-model", "wing-compact", "--skip-verify",
          "--input", str(FIXTURES / "smallband.csv"),
          "--conventions", str(FIXTURES / "smallband.md"),
          "--out", str(tmp_path / "p.json")])
    err = capsys.readouterr().err
    flat = " ".join(err.split())

    # severity-labelled blocks, not "  - {x}" bullets
    assert "WARNING" in err
    assert "  - " not in err
    # counted by severity rather than as one bare total
    assert "2 warning(s)" in err
    # the model's own provenance tag survives into the rendered line
    assert "generator" in flat
    assert "auto-assigned LCL 1" in flat


def test_the_critic_keeps_its_own_heading_so_it_never_reads_as_a_finding(tmp_path, monkeypatch, capsys):
    """The whole point: a model's opinion must never render as though it
    were a deterministic finding, even though both go through one
    renderer."""
    plan = copy.deepcopy(REAL_PLANS["smallband"])
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: object())
    monkeypatch.setattr("atoo.generate.generate_plan", lambda *a, **k: copy.deepcopy(plan))
    monkeypatch.setattr(
        "atoo.generate.critique_plan",
        lambda *a, **k: [Diagnostic(
            severity=Severity.ERROR, code="critic.intent", where="Kick",
            message="the conventions asked for a 60Hz high-pass, not 80",
            category="intent", source="critic")],
    )

    main(["build", "--console-model", "wing-compact", "--skip-verify", "--critic",
          "--input", str(FIXTURES / "smallband.csv"),
          "--conventions", str(FIXTURES / "smallband.md"),
          "--out", str(tmp_path / "p.json")])
    err = capsys.readouterr().err
    flat = " ".join(err.split())

    assert "Critic pass" in flat
    assert "a model's opinion, not a gate" in flat
    assert "ERROR" in err
    assert "60Hz high-pass" in flat


# --------------------------------------------------------------------------
# the house conventions file and a show's instructions are LAYERS.
#
# "the show independent conventions file should always
# be brought in, as well as a show's instructions if it is present. Content
# in the instructions file overrides the conventions file."
#
# Before this, a bundle's instructions.md either replaced the house file
# (when --conventions was absent) or was silently discarded (when it was
# present). Neither is layering, and the second was silent.
# --------------------------------------------------------------------------

def _capture_prompt(monkeypatch):
    """What generate_plan was actually handed."""
    seen = {}

    def fake(conventions, input_csv, *, provider, conventions_name, input_name,
             instructions=None, instructions_name=None, constrain=True, **kw):
        seen.update(conventions=conventions, conventions_name=conventions_name,
                    instructions=instructions, instructions_name=instructions_name)
        return copy.deepcopy(REAL_PLANS["smallband"])

    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: object())
    monkeypatch.setattr("atoo.generate.generate_plan", fake)
    return seen


def test_both_layers_reach_the_model_with_the_house_file_first(tmp_path, monkeypatch, capsys):
    d = _bundle(tmp_path)
    seen = _capture_prompt(monkeypatch)
    assert main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d),
                 "--conventions", str(HOUSE)]) == 0

    # the house file is the conventions text -- not displaced by the bundle
    assert seen["conventions_name"] == "smallband.md"
    assert "Patch order" in seen["conventions"]
    # ...and the per-show instructions arrive as their own layer
    assert seen["instructions_name"] == "instructions.md"
    assert "Four monitor mixes" in seen["instructions"]


def test_the_prompt_states_which_layer_wins(tmp_path, monkeypatch, capsys):
    """An earlier change point 2: precedence is resolved by the model, told in the prompt,
    never by merging the two texts in `compiler.py`-style code."""
    from atoo.generate import generator_user
    rendered = generator_user(
        "HOUSE", "name\nKick\n", conventions_name="house.md", input_name="i.csv",
        instructions="PER SHOW", instructions_name="instructions.md",
    )
    assert rendered.index("HOUSE") < rendered.index("PER SHOW")
    assert "this section wins" in rendered
    # and the house layer still applies where the show is silent
    assert "still apply in full" in rendered


def test_a_bundle_without_instructions_sends_only_the_house_layer(tmp_path, monkeypatch):
    d = _bundle(tmp_path, conventions=False)
    seen = _capture_prompt(monkeypatch)
    assert main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d),
                 "--conventions", str(HOUSE)]) == 0
    assert seen["instructions"] is None
    assert seen["instructions_name"] is None


def test_the_layering_announces_itself(tmp_path, monkeypatch, capsys):
    """"yes, make it announce itself." A build that
    quietly composed a file the command line never named is a build whose
    output cannot be explained afterwards."""
    d = _bundle(tmp_path)
    _capture_prompt(monkeypatch)
    main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d), "--conventions", str(HOUSE)])
    err = capsys.readouterr().err
    assert "Conventions, in order" in err
    assert "smallband.md" in err
    assert "instructions.md" in err
    assert "overrides the one above" in err


def test_the_plan_records_the_whole_stack_not_just_one_file(tmp_path, monkeypatch, capsys):
    """`conventions_file` names one file and cannot say "and also"."""
    d = _bundle(tmp_path)
    _capture_prompt(monkeypatch)
    main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d), "--conventions", str(HOUSE)])
    stack = json.loads((d / "plan.json").read_text())["meta"]["conventions_stack"]
    assert [layer["role"] for layer in stack] == ["conventions", "instructions"]
    assert stack[0]["path"].endswith("smallband.md")
    assert stack[1]["path"].endswith("instructions.md")


def test_instructions_are_never_a_substitute_for_the_house_file(tmp_path, capsys):
    """A bundle with instructions.md but no conventions anywhere is an
    error naming both ways to supply one -- not a silent promotion of
    per-show text to house style."""
    d = _bundle(tmp_path)
    monkeypatch_home = tmp_path / "home"
    monkeypatch_home.mkdir()
    assert main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d)]) == 1
    err = capsys.readouterr().err
    assert "a conventions file is required" in err or "one is required" in err
    assert "--conventions" in err
    assert "not a substitute" in err


def test_the_house_default_applies_to_an_explicit_input_too(tmp_path, monkeypatch, capsys):
    """"The show independent conventions file should always be brought in."
    Until an earlier change the config default was consulted only by the auto-detect
    branch, so this route failed with a settled house file in the config."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".atoo.config").write_text(
        f'[conventions]\ndefault = "{HOUSE}"\n')
    monkeypatch.setattr(Path, "home", lambda: home)
    seen = _capture_prompt(monkeypatch)

    assert main(["build", "--console-model", "wing-compact", "--skip-verify",
                 "--input", str(FIXTURES / "smallband.csv"),
                 "--out", str(tmp_path / "p.json")]) == 0
    assert seen["conventions_name"] == "smallband.md"
    assert str(home / ".atoo.config") in capsys.readouterr().err


# --------------------------------------------------------------------------
# `--show` on verify and compare -- the gap an earlier change left (found while renaming
# examples/touringband: the testing guide claimed every file flag collapsed
# into --show, and for these two it did not).
#
# These are the commands that run most often -- `verify` is the whole
# "I changed my mind about what is correct, does the plan still hold"
# loop -- so leaving them out made the bundle a half-measure exactly where
# it would be felt most.
# --------------------------------------------------------------------------


def test_verify_show_ignores_a_leftover_expectations_file(stub_build, tmp_path, capsys):
    """Both of verify's file arguments are bundle slots, so a bundle verify
    needs no other flag at all -- and the `expectations.toml` an earlier change retired
    is no longer one of them, so a leftover copy changes nothing."""
    stub_build("smallband")
    plain = _bundle(tmp_path / "plain")
    stale = _bundle(tmp_path / "stale", stale_expectations=True)
    outputs = []
    for d in (plain, stale):
        main(["build", "--console-model", "wing-compact", "--skip-verify",
              "--show", str(d), "--conventions", str(HOUSE)])
        capsys.readouterr()
        code = main(["verify", "--show", str(d)])
        captured = capsys.readouterr()
        outputs.append((code, captured.out.replace(str(d), "DIR"),
                        captured.err.replace(str(d), "DIR")))
    assert outputs[0] == outputs[1], "the leftover file changed verify's answer"
    assert "expectations" not in (outputs[1][1] + outputs[1][2]).lower()
    assert "9999" not in outputs[1][1] + outputs[1][2]


def test_verify_show_reads_the_input_list_from_the_bundle(stub_build, tmp_path, capsys):
    """Without an input list, verify skips the checks that need one and
    says so. With --show supplying input.csv it must not skip them."""
    d = _bundle(tmp_path)
    stub_build("smallband")
    main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d), "--conventions", str(HOUSE)])
    capsys.readouterr()

    main(["verify", "--show", str(d)])
    with_bundle = capsys.readouterr().out
    main(["verify", "--plan", str(d / "plan.json")])
    without = capsys.readouterr().out

    # Without an input list verify says so, by code, and skips those checks
    assert "reconcile.not-checked" in without
    # With the bundle supplying input.csv, it ran them instead
    assert "reconcile.not-checked" not in with_bundle


def test_compare_show_takes_the_plan_from_the_bundle(stub_build, tmp_path, capsys):
    """`--snapshot` stays explicit: a .snap is a capture from a moment in
    time, not one of the show's standing artifacts, so it has no slot."""
    d = _bundle(tmp_path)
    stub_build("smallband")
    main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d), "--conventions", str(HOUSE)])
    capsys.readouterr()

    code = main(["compare", "--show", str(d), "--snapshot", str(FIXTURES / "sample.snap")])
    assert code in (0, 2)                       # ran; either verdict is fine
    assert "couldn't read plan" not in capsys.readouterr().err


@pytest.mark.parametrize("command", ["verify", "compare"])
def test_an_explicit_plan_still_beats_the_bundle(command, stub_build, tmp_path, capsys):
    """The precedence every other --show command already has."""
    d = _bundle(tmp_path)
    stub_build("smallband")
    main(["build", "--console-model", "wing-compact", "--skip-verify", "--show", str(d), "--conventions", str(HOUSE)])
    capsys.readouterr()

    argv = [command, "--show", str(d), "--plan", str(tmp_path / "elsewhere.json")]
    if command == "compare":
        argv += ["--snapshot", str(FIXTURES / "sample.snap")]
    assert main(argv) == 1
    assert "elsewhere.json" in capsys.readouterr().err


@pytest.mark.parametrize("command, extra", [
    ("verify", []),
    ("compare", ["--snapshot", str(FIXTURES / "sample.snap")]),
])
def test_neither_plan_nor_show_is_a_readable_error(command, extra, capsys):
    """--plan stopped being argparse-required so --show could supply it;
    the message it used to give has to still come from somewhere."""
    assert main([command] + extra) == 1
    assert "--plan is required" in capsys.readouterr().err


@pytest.mark.parametrize("command, extra", [
    ("verify", []),
    ("compare", ["--snapshot", str(FIXTURES / "sample.snap")]),
])
def test_a_bundle_with_no_plan_names_the_filename_it_wanted(command, extra, tmp_path, capsys):
    """`plan.json` is absent until the first build, and the bundle's own
    error explains that rather than reporting a missing flag."""
    d = _bundle(tmp_path)
    assert main([command, "--show", str(d)] + extra) == 1
    err = capsys.readouterr().err
    assert "plan.json" in err and "show bundle" in err


# --------------------------------------------------------------------------
# `atoo presets`
#
# A preset's name is the `info_text` INSIDE the .chn file, not its
# filename, so a directory listing cannot tell you what your own library
# is called. Before this command the only way to learn the real names was
# to name one that does not exist and read them off the `preset.unknown`
# warning -- which works, and needs a plan that already names a preset.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
# A frozen copy of the maintainer's own set, `starter/presets/` (2026-10-12): these tests count and name what is in it.
SHIPPED_PRESETS = FIXTURES / "channel_presets"
PRESET_FIXTURES = FIXTURES / "presets"


def test_presets_prints_the_name_inside_the_file_beside_the_filename(capsys):
    """The exact confusion an earlier change is about: nothing on disk says that
    `Kick.chn` answers to `Kick In`, the name saved inside it."""
    assert main(["presets", "--presets", str(SHIPPED_PRESETS)]) == 0
    out = capsys.readouterr().out
    assert "Kick In" in out
    assert "Kick.chn" in out
    # Both on ONE line -- the pairing is the whole point, and two lists
    # that happen to contain both strings would pass a looser assertion.
    line = [ln for ln in out.splitlines() if "Kick.chn" in ln]
    assert len(line) == 1 and line[0].startswith("Kick In")


def test_presets_counts_the_leaves_each_one_carries(capsys):
    main(["presets", "--presets", str(SHIPPED_PRESETS)])
    out = capsys.readouterr().out
    # Columns are separated by two spaces; a filename can contain one
    # ("Fl Tom.chn"), so `.split()` is not enough.
    rows = [re.match(r"^(.+?)\s{2,}(\d+)\s{2,}(.+\.chn)$", ln)
            for ln in out.splitlines() if ln.endswith(".chn")]
    assert all(rows), [ln for ln, m in zip(out.splitlines(), rows) if not m]
    counts = [int(m.group(2)) for m in rows]
    # 19 channel presets; the `.bus` files are listed in their own
    # table after them, not as channel presets.
    assert len(counts) == 19
    # Asserted as a band rather than a snapshot: the point is that a preset
    # carries most of a strip's processing, not that it carries exactly 83.
    assert all(75 <= n <= 83 for n in counts), counts


def test_presets_lists_the_bus_presets_after_the_channel_presets(capsys):
    """The maintainer's set has three `.bus` files (two FX, and
    since 2026-10-13 the mix busses' "Mix Bus"); the listing names each
    bus preset, the effect it inserts and how it was saved."""
    assert main(["presets", "--presets", str(SHIPPED_PRESETS)]) == 0
    out = capsys.readouterr().out
    assert "3 bus preset(s)" in out
    assert re.search(r"^Mix Bus\s+no effect\s+Mix Bus\.bus$", out, re.M), out
    assert re.search(r"^Vox Verb\s+V-REV \(pre-insert, saved on FX5, saved bypassed\)\s+"
                     r"FX Vox Verb\.bus$", out, re.M), out
    assert re.search(r"^Snare Verb\s+GATED \(pre-insert, saved on FX8\)\s+FX Snare Verb\.bus$",
                     out, re.M), out
    assert "not read" not in out


def test_a_preset_with_a_problem_surfaces_without_any_plan_naming_it(tmp_path, capsys):
    """The part of an earlier change that is more than a convenience. A preset carrying
    an unrecognised field already reports itself -- but only when some
    plan happens to name it, which is to say never, until a show does."""
    source = json.loads((PRESET_FIXTURES / "Kick.chn").read_text())
    source["ch_data"]["totally_new_field"] = {"mystery": 42}
    (tmp_path / "odd.chn").write_text(json.dumps(source))

    assert main(["presets", "--presets", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "warning:" in out
    assert "totally_new_field.mystery" in out
    assert "odd.chn" in out


def test_two_files_claiming_one_name_is_reported_as_the_hygiene_problem_it_is(
        tmp_path, capsys):
    """`PresetLibrary.get` picks the newest rather than raising (the maintainer,
    2026-09-20), so a duplicate never stops a build -- and therefore never
    announces itself either. It does here."""
    source = (PRESET_FIXTURES / "Kick.chn").read_text()
    (tmp_path / "kick-a.chn").write_text(source)
    (tmp_path / "kick-b.chn").write_text(source)

    assert main(["presets", "--presets", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "2 files share the name" in out
    assert "kick-a.chn" in out and "kick-b.chn" in out
    assert "newest wins" in out


def test_a_library_with_no_presets_in_it_is_an_answer_not_an_error(tmp_path, capsys):
    """It ran, and there is nothing to report -- which is what `0` means
    in the canonical exit-code table. Asking for a listing and getting an
    empty one is a true answer to the question."""
    assert main(["presets", "--presets", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "No presets in" in out


def test_a_library_that_is_not_there_is_a_file_it_could_not_read(tmp_path, capsys):
    """Unlike build/verify/apply, where a missing library is a warning and
    the show still gets built. Here the library IS the subject."""
    assert main(["presets", "--presets", str(tmp_path / "nope")]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_presets_with_no_library_anywhere_says_both_ways_to_name_one(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # no config file at all
    assert main(["presets"]) == 1
    err = capsys.readouterr().err
    assert "--presets" in err and "[presets] default" in err


def test_presets_falls_back_to_the_config_default_like_every_other_command(
        tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    (home / ".atoo.config").write_text(f'[presets]\ndefault = "{SHIPPED_PRESETS}"\n')

    assert main(["presets"]) == 0
    out, err = capsys.readouterr()
    assert "Kick In" in out
    # Said out loud, on stderr, the way every other command announces a
    # value the command line never named.
    assert str(SHIPPED_PRESETS) in err


def test_a_partial_reply_is_saved_as_stem_partial_suffix():
    """`plan.partial.json`, not `plan.json.partial` --
    it sorts beside the file it was meant to become. (It is usually not
    valid JSON: a reply cut off partway.)"""
    from pathlib import Path

    from atoo import cli

    assert cli._partial_path(Path("show/plan.json")) == Path("show/plan.partial.json")
    assert cli._partial_path(Path("generation.json")) == Path("generation.partial.json")
    assert cli._partial_path(Path("show/change.json")) == Path("show/change.partial.json")


def test_a_rebuild_moves_the_old_plan_aside_before_it_starts(tmp_path, monkeypatch, capsys):
    """"If we rebuild, we need to clear the current
    plan ... because none of that is still current." A build that then
    fails leaves no out-of-date plan.json for Apply to offer."""
    from atoo.ai_provider import FakeProvider

    d = _bundle(tmp_path)
    (d / "plan.json").write_text('{"channels": [], "marker": "old"}')
    # A model is set up, and its call fails: the build had started.
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: FakeProvider(response=None))
    code = main(["build", "--console-model", "wing-compact", "--show", str(d),
                 "--conventions", str(HOUSE)])
    assert code == 1
    assert not (d / "plan.json").exists()
    assert json.loads((d / "plan.previous.json").read_text())["marker"] == "old"
    assert "plan.json moved aside to plan.previous.json" in capsys.readouterr().err


def test_with_no_model_set_up_a_build_moves_nothing_and_says_so(tmp_path, monkeypatch, capsys):
    """A build is a model call: with none set up it cannot start, and it says
    so before plan.json moves -- Apply still has the plan it had."""
    from atoo.ai_provider import AIProviderError

    d = _bundle(tmp_path)
    (d / "plan.json").write_text('{"channels": [], "marker": "old"}')

    def no_model():
        raise AIProviderError("a build needs a model: no API key")

    monkeypatch.setattr("atoo.cli.provider_from_env", no_model)
    code = main(["build", "--console-model", "wing-compact", "--show", str(d),
                 "--conventions", str(HOUSE)])
    assert code == 1
    assert json.loads((d / "plan.json").read_text())["marker"] == "old"
    assert not (d / "plan.previous.json").exists()
    err = capsys.readouterr().err
    assert ("build failed: a build needs a model: no API key. See 'Setting up an AI provider' in "
            "the user guide. Nothing was changed: plan.json is as it was.") in err
    assert "moved aside" not in err


def test_a_build_refused_before_it_starts_leaves_the_plan_alone(tmp_path, capsys):
    d = _bundle(tmp_path)
    (d / "plan.json").write_text('{"channels": []}')
    assert main(["build", "--show", str(d), "--conventions", str(HOUSE)]) == 1  # no model
    assert (d / "plan.json").exists() and not (d / "plan.previous.json").exists()


def test_a_successful_build_removes_an_old_partial_reply(stub_build, tmp_path, capsys):
    """"clear any plan.partial.json after a successful
    build"."""
    stub_build("smallband")
    out = tmp_path / "plan.json"
    (tmp_path / "plan.partial.json").write_text('{"half": ')
    assert main(["build", "--console-model", "wing-compact", "--skip-verify",
                 "--input", str(FIXTURES / "smallband.csv"),
                 "--conventions", str(FIXTURES / "smallband.md"),
                 "--out", str(out)]) == 0
    assert out.is_file() and not (tmp_path / "plan.partial.json").exists()
    assert "plan.partial.json removed" in capsys.readouterr().err


def test_warnings_under_a_summary_flush_stdout_first(monkeypatch):
    """The summary says "listed below"; piped, stdout is block-buffered and
    stderr is not, so the summary must be flushed before the lines."""
    import io
    import types
    from atoo import cli
    events = []

    class Out(io.StringIO):
        def flush(self):
            events.append("stdout flushed")

    class Err(io.StringIO):
        def write(self, text):
            if text.strip():
                events.append("stderr: " + text.strip())
            return super().write(text)

    monkeypatch.setattr(sys, "stdout", Out())
    monkeypatch.setattr(sys, "stderr", Err())
    cli._print_result_warnings(types.SimpleNamespace(warnings=["ch 14: socket assigned"]))
    assert events[0] == "stdout flushed"
    assert events[1] == "stderr: - ch 14: socket assigned"
