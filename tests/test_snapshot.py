"""Tests for atoo/snapshot.py (`load_snapshot`, `compare_snapshot`) and
the `atoo compare` CLI wiring in atoo/cli.py -- an earlier change.

`tests/fixtures/sample.snap` is a small, hand-written `.snap`-shaped fixture
(`{"ae_data": {...}}`), grounded in `docs/reference/wing-console-model.md`
and `atoo/console_facts.py`'s confirmed addresses: `ch.{n}.name` (and
`ch.{n}.config.name`, the firmware-ambiguous form `_scalar()` also tries),
`ch.{n}.in.conn.grp`/`.in`, `ch.{n}.flt.lcf`/`.lc`, `ch.{n}.fdr`,
`ch.{n}.mute`, `ch.{n}.tags` (the `#D<n>`/`#M<n>` DCA/mute-group tokens),
and `ch.{n}.send.{n}.on`/`.lvl`/`.mode`. Its channel 1 ("Kick") is a
deliberately "clean" strip that a fully-stated plan channel can match on
every field; channel 2 ("Snare") stores its name under `config` instead of
at the top level, exercising the other firmware shape `_scalar()` tries.

Plan-channel dicts follow the same shape as `plan_schema.py`'s
EXAMPLE_CHANNEL, trimmed to what each test needs -- the same
`_plan_channel()` convention `tests/test_audit.py` established for the `diff_against_plan()` tests.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo.cli import main
from atoo.snapshot import SnapshotError, compare_snapshot, load_snapshot

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_SNAP = FIXTURES / "sample.snap"


def _snapshot() -> dict:
    """A fresh copy of the sample fixture's `ae_data`, so a test that
    mutates a strip in place never leaks into another test."""
    return copy.deepcopy(json.loads(SAMPLE_SNAP.read_text())["ae_data"])


def _plan_channel(**overrides) -> dict:
    entry = {
        "channel": 1, "bank": "ch", "name": "Kick",
        "patch": {"group": None, "sockets": [], "stated": False},
        "processing": {"hpf_hz": None, "preset": None},
        "fader": {"fader_db": None, "muted": None},
        "dca": [], "mute_group": [], "bus_sends": [],
    }
    entry.update(overrides)
    return entry


def _plan(channels, dcas=None, mute_groups=None, busses=None) -> dict:
    return {
        "channels": channels,
        "dcas": dcas or {},
        "mute_groups": mute_groups or {},
        "busses": busses or {},
    }


def _codes(result) -> set[str]:
    return {f.code for f in result.findings}


# --------------------------------------------------------------------------
# load_snapshot()
# --------------------------------------------------------------------------


def test_load_snapshot_reads_ae_data():
    ae_data = load_snapshot(SAMPLE_SNAP)
    assert ae_data["ch"]["1"]["name"] == "Kick"
    assert ae_data["bus"]["1"]["name"] == "Drums"


def test_load_snapshot_missing_file_raises():
    with pytest.raises(SnapshotError):
        load_snapshot(FIXTURES / "does-not-exist.snap")


def test_load_snapshot_invalid_json_raises(tmp_path):
    bad = tmp_path / "bad.snap"
    bad.write_text("{not valid json")
    with pytest.raises(SnapshotError):
        load_snapshot(bad)


def test_load_snapshot_without_ae_data_key_names_it(tmp_path):
    no_ae = tmp_path / "no_ae.snap"
    no_ae.write_text(json.dumps({"something_else": {}}))
    with pytest.raises(SnapshotError) as exc_info:
        load_snapshot(no_ae)
    assert "ae_data" in str(exc_info.value)


# --------------------------------------------------------------------------
# compare_snapshot() -- clean run and strip-level checks
# --------------------------------------------------------------------------


def test_clean_run_every_stated_field_matches():
    """Every field the plan states matches fixture channel 1 ("Kick")
    exactly -- name, patch, HPF, fader, mute, DCA/mute-group membership,
    and one bus send."""
    ch = _plan_channel(
        patch={"group": "A", "sockets": [1], "stated": True},
        processing={"hpf_hz": 80, "preset": None},
        fader={"fader_db": -3.0, "muted": False},
        dca=["Drums"], mute_group=["Drums"],
        bus_sends=[{"bus": "Drums", "mode": "post", "level_db": 0.0}],
    )
    plan = _plan([ch], dcas={"Drums": {"index": 1}},
                 mute_groups={"Drums": {"index": 1}},
                 busses={"Drums": {"index": 1}})
    result = compare_snapshot(plan, _snapshot())
    assert result.findings == []


def test_missing_strip():
    ch = _plan_channel(channel=9, name="Nothing Here")
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.strip-missing"}
    assert result.findings[0].severity == "error"


def test_name_mismatch():
    ch = _plan_channel(name="Not Kick")
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.name"}
    assert result.findings[0].severity == "error"


def test_name_field_not_found_is_a_warning_not_a_crash():
    ae_data = _snapshot()
    del ae_data["ch"]["1"]["name"]
    ch = _plan_channel()
    plan = _plan([ch])
    result = compare_snapshot(plan, ae_data)
    assert _codes(result) == {"snapshot.field-not-found"}
    assert result.findings[0].severity == "warning"


# --------------------------------------------------------------------------
# Patch
# --------------------------------------------------------------------------


def test_patch_mismatch():
    ch = _plan_channel(patch={"group": "A", "sockets": [7], "stated": True})
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.patch"}
    assert result.findings[0].severity == "error"


def test_patch_not_stated_is_not_compared():
    # default _plan_channel() already has sockets=[] (not stated)
    ch = _plan_channel()
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert result.findings == []


# --------------------------------------------------------------------------
# HPF
# --------------------------------------------------------------------------


def test_hpf_off_on_the_desk():
    ae_data = _snapshot()
    ae_data["ch"]["1"]["flt"]["lc"] = 0
    ch = _plan_channel(processing={"hpf_hz": 80, "preset": None})
    plan = _plan([ch])
    result = compare_snapshot(plan, ae_data)
    assert _codes(result) == {"snapshot.hpf-off"}
    assert result.findings[0].severity == "error"


def test_hpf_frequency_mismatch_beyond_tolerance():
    # fixture's ch1 flt.lcf is 80.0Hz -- plan asks for 60Hz, well beyond
    # DB_TOLERANCE (0.25, reused here as a Hz tolerance -- see snapshot.py's
    # _close()).
    ch = _plan_channel(processing={"hpf_hz": 60, "preset": None})
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.hpf"}
    assert result.findings[0].severity == "error"


def test_hpf_not_stated_is_not_compared():
    ch = _plan_channel(processing={"hpf_hz": None, "preset": None})
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert result.findings == []


# --------------------------------------------------------------------------
# Fader / mute
# --------------------------------------------------------------------------


def test_fader_mismatch_beyond_tolerance():
    # fixture's ch1 fdr is -3.0dB; 0.3dB away is outside DB_TOLERANCE=0.25.
    ch = _plan_channel(fader={"fader_db": -3.3, "muted": None})
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.fader"}
    assert result.findings[0].severity == "error"


def test_fader_within_tolerance_is_clean():
    ch = _plan_channel(fader={"fader_db": -3.1, "muted": None})
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert result.findings == []


def test_mute_mismatch():
    # fixture's ch1 mute is 0 (unmuted) -- plan says muted.
    ch = _plan_channel(fader={"fader_db": None, "muted": True})
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.mute"}
    assert result.findings[0].severity == "error"


# --------------------------------------------------------------------------
# DCA / mute-group membership
# --------------------------------------------------------------------------


def test_dca_membership_mismatch():
    # fixture's ch1 tags is "#D1 #M1" -- a plan DCA that resolves to a
    # different console index than 1 is not present in the tags.
    ch = _plan_channel(dca=["Vocals"])
    plan = _plan([ch], dcas={"Vocals": {"index": 2}})
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.d-membership"}
    assert result.findings[0].severity == "error"


def test_mute_group_membership_mismatch():
    ch = _plan_channel(mute_group=["Vocals"])
    plan = _plan([ch], mute_groups={"Vocals": {"index": 2}})
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.m-membership"}
    assert result.findings[0].severity == "error"


def test_dca_membership_match_is_clean():
    ch = _plan_channel(dca=["Drums"])
    plan = _plan([ch], dcas={"Drums": {"index": 1}})
    result = compare_snapshot(plan, _snapshot())
    assert result.findings == []


def test_dca_name_with_no_console_index_in_the_plan_is_a_warning():
    """This is distinct from a name that fails to resolve against a *live*
    console (test_audit.py's `test_diff_dca_name_not_resolved_is_silent`,
    silent by design there): here the *plan itself* never allocated a
    console index for the name at all, so membership cannot be compared --
    silence would claim a check that never ran."""
    ch = _plan_channel(dca=["Nonexistent"])
    plan = _plan([ch])  # dcas={} -- "Nonexistent" has no index
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.no-console-index"}
    assert result.findings[0].severity == "warning"


def test_mute_group_name_with_no_console_index_in_the_plan_is_a_warning():
    ch = _plan_channel(mute_group=["Nonexistent"])
    plan = _plan([ch])
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.no-console-index"}
    assert result.findings[0].severity == "warning"


# --------------------------------------------------------------------------
# Bus sends
# --------------------------------------------------------------------------


def test_send_off():
    ae_data = _snapshot()
    ae_data["ch"]["1"]["send"]["1"]["on"] = 0
    ch = _plan_channel(bus_sends=[{"bus": "Drums", "mode": "post", "level_db": 0.0}])
    plan = _plan([ch], busses={"Drums": {"index": 1}})
    result = compare_snapshot(plan, ae_data)
    assert _codes(result) == {"snapshot.send-off"}
    assert result.findings[0].severity == "error"


def test_send_level_mismatch_beyond_tolerance():
    # fixture's ch1 send/1 lvl is 0.0dB; plan asks for -3.0dB.
    ch = _plan_channel(bus_sends=[{"bus": "Drums", "mode": "post", "level_db": -3.0}])
    plan = _plan([ch], busses={"Drums": {"index": 1}})
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.send-level"}
    assert result.findings[0].severity == "error"


def test_send_mode_mismatch():
    # fixture's ch1 send/1 mode is "POST" -- plan states "pre".
    ch = _plan_channel(bus_sends=[{"bus": "Drums", "mode": "pre", "level_db": 0.0}])
    plan = _plan([ch], busses={"Drums": {"index": 1}})
    result = compare_snapshot(plan, _snapshot())
    assert _codes(result) == {"snapshot.send-mode"}
    assert result.findings[0].severity == "error"


def test_send_mode_comparison_is_case_insensitive():
    # fixture's ch1 send/2 mode is "PRE"; plan states lowercase "pre" --
    # must NOT be reported as a mismatch.
    ch = _plan_channel(bus_sends=[{"bus": "Monitor 1", "mode": "pre", "level_db": -3.0}])
    plan = _plan([ch], busses={"Monitor 1": {"index": 2}})
    result = compare_snapshot(plan, _snapshot())
    assert result.findings == []


# --------------------------------------------------------------------------
# CLI: `atoo compare --plan ... --snapshot ...`
# --------------------------------------------------------------------------


def _clean_plan_dict() -> dict:
    ch = _plan_channel(
        patch={"group": "A", "sockets": [1], "stated": True},
        processing={"hpf_hz": 80, "preset": None},
        fader={"fader_db": -3.0, "muted": False},
        dca=["Drums"], mute_group=["Drums"],
        bus_sends=[{"bus": "Drums", "mode": "post", "level_db": 0.0}],
    )
    return _plan([ch], dcas={"Drums": {"index": 1}},
                 mute_groups={"Drums": {"index": 1}},
                 busses={"Drums": {"index": 1}})


def test_cli_compare_clean_exits_zero(tmp_path, capsys):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_clean_plan_dict()))
    code = main(["compare", "--plan", str(plan_path), "--snapshot", str(SAMPLE_SNAP)])
    assert code == 0
    out = capsys.readouterr().out
    assert "matches the plan on every field" in out


def test_cli_compare_with_differences_exits_nonzero(tmp_path, capsys):
    plan = _clean_plan_dict()
    plan["channels"][0]["name"] = "Not Kick"  # forces snapshot.name, an error
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    code = main(["compare", "--plan", str(plan_path), "--snapshot", str(SAMPLE_SNAP)])
    assert code == 2
    out = capsys.readouterr().out
    assert "difference(s)" in out


def test_cli_compare_bad_plan_path_is_a_clean_error(tmp_path, capsys):
    code = main(["compare", "--plan", str(tmp_path / "nope.json"),
                 "--snapshot", str(SAMPLE_SNAP)])
    assert code == 1
    err = capsys.readouterr().err
    assert "couldn't read plan" in err


def test_cli_compare_bad_snapshot_path_is_a_clean_error(tmp_path, capsys):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_clean_plan_dict()))
    code = main(["compare", "--plan", str(plan_path),
                 "--snapshot", str(tmp_path / "nope.snap")])
    assert code == 1
    err = capsys.readouterr().err
    assert "couldn't read" in err
