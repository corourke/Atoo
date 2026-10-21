"""Socket group counts (`GROUP=COUNT,...`), as the browser's field and the command line state them."""

from __future__ import annotations

import pytest

from atoo import cli, console_facts


@pytest.mark.parametrize("spec, expected", [
    (None, {}), ("", {}), (" , ", {}),
    ("LCL=8", {"LCL": 8}), (" LCL = 8 , A=48 ", {"LCL": 8, "A": 48}),
])
def test_socket_counts_are_group_equals_count(spec, expected):
    assert console_facts.parse_socket_counts(spec) == expected


@pytest.mark.parametrize("spec", ["BUS 5-6", "LCL", "LCL=", "=8", "LCL=lots", "LCL=-1", "LCL=8.5",
                                  "A=\u00b2"])
def test_a_socket_count_that_is_not_group_equals_count_says_what_to_write(spec):
    with pytest.raises(ValueError, match="GROUP=COUNT") as caught:
        console_facts.parse_socket_counts(spec)
    assert repr(spec.strip()) in str(caught.value) or spec.split(",")[0].strip() in str(caught.value)


def test_the_command_line_stops_with_the_reason_and_exit_2_before_touching_the_desk(
        tmp_path, capsys):
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as stop:
        cli.main(["apply", "--plan", str(plan), "--console", "192.0.2.1",
                  "--clean-output-sockets", "BUS 5-6"])
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "'BUS 5-6' is not a socket group and its count" in err and "Traceback" not in err
