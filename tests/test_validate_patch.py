"""Step 02's Patch cell is checked before it goes into the row (the maintainer's
UI testing, 2026-09-28): `input_list.check_patch` and the read-only
`GET /api/build/validate-patch` that serves it to the page.

The check is the input list's own grammar (`parse_socket_spec`) and the
console model's own bound (`console_facts.input_socket_limit`) -- these
tests pin that it agrees with both, rather than keeping a list of its own.
"""

from __future__ import annotations

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import console_facts  # noqa: E402
from atoo.input_list import check_patch, format_socket, parse_socket_spec  # noqa: E402
from atoo.webui import create_app  # noqa: E402


# ---- the function -------------------------------------------------------


def test_a_valid_patch_is_ok_and_comes_back_in_the_parsers_own_spelling():
    verdict = check_patch("aes50-a 12", "wing-compact")
    assert verdict["ok"] is True
    assert verdict["error"] is None
    assert (verdict["group"], verdict["number"]) == ("A", 12)
    # What the parser reads back, byte for byte.
    assert verdict["patch"] == "AES50-A 12"
    assert parse_socket_spec(verdict["patch"]) == ("A", 12)


def test_out_of_range_is_refused_with_the_models_own_bound():
    limit = console_facts.input_socket_limit("LCL", "wing-full")
    verdict = check_patch(f"LCL {limit + 1}", "wing-full")
    assert verdict["ok"] is False
    assert verdict["limit"] == limit
    assert "out of range" in verdict["error"]
    assert f"LCL 1-{limit}" in verdict["error"]
    # The last socket that exists is fine; socket 0 never is.
    assert check_patch(f"LCL {limit}", "wing-full")["ok"] is True
    assert check_patch("LCL 0", "wing-full")["ok"] is False


def test_a_group_the_model_does_not_have_is_refused():
    # Rack and Compact have no local aux inputs; the full-size WING has 8.
    assert console_facts.input_socket_limit("AUX", "wing-rack") == 0
    verdict = check_patch("AUX 2", "wing-rack")
    assert verdict["ok"] is False
    assert "has no AUX inputs" in verdict["error"]
    assert check_patch("AUX 2", "wing-full")["ok"] is True


@pytest.mark.parametrize("text", ["XYZ 1", "Dante 3", "SD card 3"])
def test_an_unknown_group_is_refused_and_the_real_groups_are_named(text):
    assert parse_socket_spec(text) is None
    verdict = check_patch(text, "wing-compact")
    assert verdict["ok"] is False
    assert "is not a socket group" in verdict["error"]
    assert "AES50-A" in verdict["error"] and "LCL" in verdict["error"]


@pytest.mark.parametrize("text", ["AES50-A 15-16", "LCL 1/2", "lcl 3+4"])
def test_a_stereo_range_is_refused_because_a_stereo_source_is_two_rows(text):
    # The input list's grammar takes one socket per row: the pair is two
    # rows. The check says that, rather than "not <group> <number>".
    assert parse_socket_spec(text) is None
    verdict = check_patch(text, "wing-compact")
    assert verdict["ok"] is False
    assert "a stereo source is two rows" in verdict["error"]


def test_text_that_is_not_a_patch_at_all_says_the_shape():
    verdict = check_patch("hello", "wing-compact")
    assert verdict["ok"] is False
    assert "<group> <number>" in verdict["error"]


def test_blank_is_ok_because_the_build_chooses_one():
    verdict = check_patch("   ", "wing-compact")
    assert verdict["ok"] is True
    assert verdict["patch"] == ""


def test_no_model_checks_the_address_space_and_says_so():
    verdict = check_patch("LCL 20", None)
    assert verdict["ok"] is True
    assert verdict["limit"] == console_facts.INPUT_SOCKETS["LCL"]
    assert "no console model chosen" in verdict["note"]


def test_every_group_the_parser_knows_can_be_checked_on_every_model():
    """No second grammar: whatever group the parser accepts, the check
    reaches a verdict for, on every model -- never an exception."""
    for model in console_facts.CONSOLE_MODELS:
        for group in sorted(set(console_facts.INPUT_SOCKETS) - {"OSC"}):
            text = format_socket(group, 1)
            if parse_socket_spec(text) is None:
                continue
            verdict = check_patch(text, model)
            expected = console_facts.input_socket_limit(group, model) >= 1
            assert verdict["ok"] is expected, (model, text, verdict)


def test_an_unknown_model_raises():
    with pytest.raises(console_facts.UnknownConsoleModel):
        check_patch("LCL 1", "wing-huge")


# ---- the endpoint -------------------------------------------------------


@pytest.fixture
def client():
    app = create_app()
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_the_endpoint_answers_valid(client):
    r = client.get("/api/build/validate-patch", params={"value": "lcl 3", "model": "wing-compact"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["patch"] == "LCL 3"


def test_the_endpoint_refuses_out_of_range_with_a_reason(client):
    r = client.get("/api/build/validate-patch", params={"value": "LCL 99", "model": "wing-compact"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "out of range" in body["error"]


def test_the_endpoint_refuses_an_unknown_group(client):
    r = client.get("/api/build/validate-patch", params={"value": "XYZ 1", "model": "wing-compact"})
    assert r.json()["ok"] is False
    assert "is not a socket group" in r.json()["error"]


def test_the_endpoint_refuses_a_stereo_range(client):
    r = client.get("/api/build/validate-patch",
                   params={"value": "AES50-A 15-16", "model": "wing-compact"})
    assert r.json()["ok"] is False
    assert "two rows" in r.json()["error"]


def test_the_endpoint_without_a_model_checks_the_address_space(client):
    r = client.get("/api/build/validate-patch", params={"value": "AES50-B 48", "model": ""})
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["note"]


def test_the_endpoint_says_400_for_an_unknown_model(client):
    r = client.get("/api/build/validate-patch", params={"value": "LCL 1", "model": "wing-huge"})
    assert r.status_code == 400
    assert "unknown console model" in r.json()["error"]


def test_the_endpoint_is_read_only(client):
    # GET only: nothing can be posted to it.
    assert client.post("/api/build/validate-patch", json={"value": "LCL 1"}).status_code == 405
