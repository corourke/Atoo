"""A plan records the conventions file it was built from,
relative to the show bundle, and the UI's Build step 01 loads that file
when the bundle is opened.

The maintainer, 2026-09-23: *"A generated plan file should include a relative
(to the show bundle directory) file name reference to the conventions
file that was incorporated in the build such that it can be loaded by
the UI when a show bundle is loaded."*

Every bundle here is built in `tmp_path` -- nothing reads a bundle under
`examples/` (CLAUDE.md, "a bundle under examples/ is a living example").
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient
from atoo import conventions_ref
from atoo.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
HOUSE_TEXT = "# House\n\n## Channels\nDrums first.\n\n## Busses\nMonitors are mono.\n"
OTHER_TEXT = "# Other house\n\n## Channels\nVocals first.\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _show(tmp_path: Path, *, instructions: bool = True) -> Path:
    """A bundle one level below the house file -- the ordinary layout."""
    d = tmp_path / "shows" / "my-show"
    d.mkdir(parents=True)
    (d / "input.csv").write_text((FIXTURES / "smallband.csv").read_text())
    if instructions:
        (d / "instructions.md").write_text("# This show\n\n## Busses\nFour mixes.\n")
    return d


def _house(tmp_path: Path, name: str = "house-A.md", text: str = HOUSE_TEXT) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def _build(show: Path, *extra: str) -> int:
    return main(["build", "--console-model", "wing-compact", "--skip-verify",
                 "--show", str(show), *extra])


def _stack(show: Path) -> list[dict]:
    return json.loads((show / "plan.json").read_text())["meta"]["conventions_stack"]


# ---- what `atoo build` records ----------------------------------------


def test_a_bundle_build_records_the_house_file_relative_to_the_bundle(stub_build, tmp_path):
    stub_build("smallband")
    show, house = _show(tmp_path), _house(tmp_path)
    assert _build(show, "--conventions", str(house)) == 0

    layer = _stack(show)[0]
    assert layer["role"] == "conventions"
    assert layer["bundle_relative_path"] == os.path.join("..", "..", "house-A.md")
    assert layer["absolute_path"] == str(house)
    assert layer["sha256"] == _sha(house)
    # The whole point: it resolves from the bundle, whatever the cwd was.
    assert (show / layer["bundle_relative_path"]).resolve() == house.resolve()


def test_the_instructions_layer_carries_the_same_three_keys(stub_build, tmp_path):
    stub_build("smallband")
    show, house = _show(tmp_path), _house(tmp_path)
    assert _build(show, "--conventions", str(house)) == 0
    layer = _stack(show)[1]
    assert layer["role"] == "instructions"
    assert layer["bundle_relative_path"] == "instructions.md"
    assert layer["sha256"] == _sha(show / "instructions.md")


def test_a_cwd_relative_conventions_path_is_kept_as_typed_and_recorded_absolute(
        stub_build, tmp_path, monkeypatch):
    """`path` is what was typed -- relative to a working directory nobody
    recorded, which is why it could never be read back."""
    stub_build("smallband")
    show, house = _show(tmp_path), _house(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert _build(show, "--conventions", "house-A.md") == 0
    layer = _stack(show)[0]
    assert layer["path"] == "house-A.md"
    assert layer["absolute_path"] == str(house)
    assert layer["bundle_relative_path"] == os.path.join("..", "..", "house-A.md")


def test_the_config_default_is_recorded_too_when_no_flag_names_one(stub_build, tmp_path, monkeypatch):
    """The absent case: no `--conventions` at all, the house file comes
    from ~/.atoo.config -- and the plan still records where."""
    stub_build("smallband")
    show, house = _show(tmp_path), _house(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    (home / ".atoo.config").write_text(f'[conventions]\ndefault = "{house}"\n')
    assert _build(show) == 0
    layer = _stack(show)[0]
    assert layer["absolute_path"] == str(house)
    assert layer["bundle_relative_path"] == os.path.join("..", "..", "house-A.md")
    assert layer["sha256"] == _sha(house)


def test_a_build_with_no_bundle_says_nothing_is_relative(stub_build, tmp_path):
    stub_build("smallband")
    house = _house(tmp_path)
    out = tmp_path / "p.json"
    assert main(["build", "--console-model", "wing-compact", "--skip-verify",
                 "--input", str(FIXTURES / "smallband.csv"),
                 "--conventions", str(house), "--out", str(out)]) == 0
    layer = json.loads(out.read_text())["meta"]["conventions_stack"][0]
    assert layer["bundle_relative_path"] is None
    assert layer["absolute_path"] == str(house)
    assert layer["sha256"] == _sha(house)


# ---- reading it back --------------------------------------------------------


def test_a_plan_from_before_236_has_no_record():
    old = {"meta": {"conventions_stack": [
        {"path": "house.md", "role": "conventions", "source": "--conventions"}]}}
    assert conventions_ref.recorded_conventions(old) is None
    assert conventions_ref.recorded_conventions({}) is None
    assert conventions_ref.recorded_conventions({"meta": {}}) is None
    assert conventions_ref.recorded_conventions(None) is None


def test_resolution_prefers_the_bundle_relative_path(tmp_path):
    show, house = _show(tmp_path), _house(tmp_path)
    decoy = _house(tmp_path, "decoy.md")
    layer = {"role": "conventions", "bundle_relative_path": "../../house-A.md",
             "absolute_path": str(decoy)}
    assert conventions_ref.resolve_recorded(layer, show) == (house, "relative")
    house.unlink()
    assert conventions_ref.resolve_recorded(layer, show) == (decoy, "absolute")
    decoy.unlink()
    assert conventions_ref.resolve_recorded(layer, show) == (None, None)


# ---- the UI's Build step 01 -------------------------------------------------

fastapi_testclient = require_fastapi_testclient()
from atoo.webui import create_app  # noqa: E402


def _record(show: Path, house: Path, *, sha: str | None = "auto", relative: str | None = "auto",
            absolute: str | None = "auto") -> None:
    """A plan.json in `show` whose stack records `house`, built by hand so
    each key can be omitted or falsified on its own."""
    plan = json.loads((FIXTURES / "setup_viewer.plan.json").read_text())
    layer = {"path": str(house), "role": "conventions", "source": "--conventions"}
    if relative is not None:
        layer["bundle_relative_path"] = (os.path.relpath(house, show)
                                         if relative == "auto" else relative)
    if absolute is not None:
        layer["absolute_path"] = str(house) if absolute == "auto" else absolute
    if sha is not None:
        layer["sha256"] = _sha(house) if sha == "auto" else sha
    plan.setdefault("meta", {})["conventions_stack"] = [layer]
    (show / "plan.json").write_text(json.dumps(plan))


def _sources(show: Path, config_house: "Path | None") -> dict:
    app = create_app(initial_bundle=str(show),
                     initial_conventions=str(config_house) if config_house else None)
    with fastapi_testclient.TestClient(app) as c:
        return c.get("/api/build/sources").json()


def _finding(data: dict, code: str) -> dict | None:
    hits = [f for f in data["findings"] if f["code"] == code]
    return hits[0] if hits else None


_PLAN_CODES = {
    "build.recorded-conventions-missing", "build.recorded-conventions-moved",
    "build.recorded-conventions-edited", "build.conventions-from-plan",
    "build.conventions-not-plan",
}


def test_a_bundle_opens_on_the_conventions_file_its_plan_was_built_from(tmp_path):
    show = _show(tmp_path)
    built_from, config_names = _house(tmp_path, "house-A.md"), _house(tmp_path, "house-B.md", OTHER_TEXT)
    _record(show, built_from)
    data = _sources(show, config_names)

    assert data["conventions"]["path"] == str(built_from)
    assert data["conventions"]["text"] == HOUSE_TEXT
    assert data["conventions"]["display_origin"] == "recorded in my-show/plan.json"
    assert data["stack"][0]["path"] == str(built_from)
    assert data["stack"][0]["display_source"] == "recorded in my-show/plan.json"
    # ...and the disagreement with the config announces itself.
    info = _finding(data, "build.conventions-from-plan")
    assert info["severity"] == "info"
    assert "house-B.md" in info["message"] and "house-A.md" in info["message"]
    assert _finding(data, "build.recorded-conventions-edited") is None


def test_no_disagreement_finding_when_the_plan_and_config_name_one_file(tmp_path):
    show, house = _show(tmp_path), _house(tmp_path)
    _record(show, house)
    data = _sources(show, house)
    assert data["conventions"]["path"] == str(house)
    assert not _PLAN_CODES & {f["code"] for f in data["findings"]}


def test_a_recorded_file_that_is_gone_falls_back_to_the_config_and_warns(tmp_path):
    show = _show(tmp_path)
    built_from, config_names = _house(tmp_path, "house-A.md"), _house(tmp_path, "house-B.md", OTHER_TEXT)
    _record(show, built_from)
    built_from.unlink()
    data = _sources(show, config_names)

    assert data["conventions"]["path"] == str(config_names)
    assert "[conventions]" in data["conventions"]["display_origin"]
    warning = _finding(data, "build.recorded-conventions-missing")
    assert warning["severity"] == "warning"
    assert "house-A.md" in warning["message"]
    assert str(config_names) in warning["message"]
    assert "cannot be rebuilt" in warning["message"]
    assert _finding(data, "build.conventions-from-plan") is None


def test_a_gone_recorded_file_with_no_config_either_is_still_a_warning_beside_the_to_do(tmp_path):
    """The recorded file is gone (a WARNING: this plan cannot be rebuilt as
    built), and there is no other file at all -- which is a to-do on the
    tile, its ERROR held for Build (`missing`)."""
    show, built_from = _show(tmp_path), _house(tmp_path)
    _record(show, built_from)
    built_from.unlink()
    data = _sources(show, None)
    assert _finding(data, "build.no-conventions") is None
    assert data["conventions"]["missing"]["code"] == "build.no-conventions"
    assert data["conventions"]["missing"]["severity"] == "error"
    assert _finding(data, "build.recorded-conventions-missing")["severity"] == "warning"


def test_a_recorded_file_edited_since_the_build_is_named(tmp_path):
    show, house = _show(tmp_path), _house(tmp_path)
    _record(show, house)
    house.write_text(HOUSE_TEXT + "\n## Output\nNew rule.\n")
    data = _sources(show, house)
    info = _finding(data, "build.recorded-conventions-edited")
    assert info["severity"] == "info"
    assert "edited since" in info["message"]
    # The tile shows the file as it is now -- what the next build uses.
    assert "New rule." in data["conventions"]["text"]


def test_a_plan_with_no_hash_is_not_called_edited(tmp_path):
    show, house = _show(tmp_path), _house(tmp_path)
    _record(show, house, sha=None)
    house.write_text("changed\n")
    data = _sources(show, house)
    assert data["conventions"]["path"] == str(house)
    assert _finding(data, "build.recorded-conventions-edited") is None


def test_a_moved_bundle_finds_the_file_by_its_absolute_path_and_says_so(tmp_path):
    show, house = _show(tmp_path), _house(tmp_path)
    _record(show, house, relative="../nowhere/house-A.md")
    data = _sources(show, None)
    assert data["conventions"]["path"] == str(house)
    assert _finding(data, "build.recorded-conventions-moved")["severity"] == "info"


def test_a_bundle_moved_with_its_house_file_resolves_relatively(tmp_path):
    """The bundle and house file move together (another laptop, another
    depth): the absolute path is stale, the relative one still holds."""
    show, house = _show(tmp_path), _house(tmp_path)
    _record(show, house, absolute="/somewhere/that/was/another/laptop/house-A.md")
    data = _sources(show, None)
    assert data["conventions"]["path"] == str(house)
    assert _finding(data, "build.recorded-conventions-moved") is None
    assert _finding(data, "build.recorded-conventions-missing") is None


def test_a_plan_from_before_236_opens_exactly_as_it_did(tmp_path):
    """No migration: an old stack entry's bare `path` is not trusted, and
    the tile shows the config default with no #236 finding at all."""
    show = _show(tmp_path)
    old_file, config_names = _house(tmp_path, "house-A.md"), _house(tmp_path, "house-B.md", OTHER_TEXT)
    _record(show, old_file, sha=None, relative=None, absolute=None)
    data = _sources(show, config_names)
    assert data["conventions"]["path"] == str(config_names)
    assert not _PLAN_CODES & {f["code"] for f in data["findings"]}
    assert set(data["stack"][0]) >= {"path", "role", "source"}


def test_a_bundle_with_no_plan_or_an_unreadable_one_uses_the_config(tmp_path):
    show, house = _show(tmp_path), _house(tmp_path)
    assert _sources(show, house)["conventions"]["path"] == str(house)
    (show / "plan.json").write_text("{ not json")
    data = _sources(show, house)
    assert data["conventions"]["path"] == str(house)
    assert not _PLAN_CODES & {f["code"] for f in data["findings"]}


def test_a_typed_path_still_wins_over_the_plan_and_says_so(tmp_path):
    show = _show(tmp_path)
    built_from, typed = _house(tmp_path, "house-A.md"), _house(tmp_path, "typed.md", OTHER_TEXT)
    _record(show, built_from)
    app = create_app(initial_bundle=str(show), initial_conventions=None)
    with fastapi_testclient.TestClient(app) as c:
        data = c.post("/api/build/sources/load",
                      json={"slot": "conventions", "path": str(typed)}).json()
    assert data["conventions"]["path"] == str(typed)
    assert data["conventions"]["display_origin"] == "loaded here"
    info = _finding(data, "build.conventions-not-plan")
    assert info["severity"] == "info"
    assert "house-A.md" in info["message"]


def test_the_stack_carries_the_plans_keys(tmp_path):
    """`_build_payload` promises `meta.conventions_stack`'s shape key for
    key -- so the three #236 keys ride on the page's stack too."""
    show, house = _show(tmp_path), _house(tmp_path)
    data = _sources(show, house)
    for layer in data["stack"]:
        assert {"absolute_path", "bundle_relative_path", "sha256"} <= set(layer)
    assert data["stack"][0]["bundle_relative_path"] == os.path.join("..", "..", "house-A.md")
    assert data["stack"][1]["bundle_relative_path"] == "instructions.md"


def test_round_trip_build_then_open_under_a_different_config(stub_build, tmp_path):
    """The issue end to end: build against house-A, the config names
    house-B by the time the bundle is opened, and step 01 shows house-A."""
    stub_build("smallband")
    show = _show(tmp_path)
    built_from, config_names = _house(tmp_path, "house-A.md"), _house(tmp_path, "house-B.md", OTHER_TEXT)
    assert _build(show, "--conventions", str(built_from)) == 0
    data = _sources(show, config_names)
    assert data["conventions"]["path"] == str(built_from)
    assert _finding(data, "build.recorded-conventions-edited") is None


def test_the_served_page_draws_the_origin(tmp_path):
    """CLAUDE.md's web/static rule: the Python suite cannot see the page,
    so assert the served assets read the new key."""
    app = create_app()
    with fastapi_testclient.TestClient(app) as c:
        js = c.get("/static/shell.js").text
        html = c.get("/static/shell.html").text
    # The read itself, not just a mention in a comment.
    assert "source.display_origin" in js
    assert 'el("conv-house-origin")' in js
    assert 'id="conv-house-origin"' in html


def test_run_from_the_page_rebuilds_against_the_plans_file(stub_build, tmp_path, monkeypatch):
    """Step 04's Run passes step 01's file as `--conventions`, so a
    bundle opened on its recorded file rebuilds against it -- and the new
    plan records it again."""
    import time

    stub_build("smallband")
    monkeypatch.setattr("atoo.generate.draft_watch_conditions", lambda *a, **k: [])
    show = _show(tmp_path)
    built_from, config_names = _house(tmp_path, "house-A.md"), _house(tmp_path, "house-B.md", OTHER_TEXT)
    _record(show, built_from)
    app = create_app(initial_bundle=str(show), initial_conventions=str(config_names))
    with fastapi_testclient.TestClient(app) as c:
        assert c.post("/api/build/run", json={"console_model": "wing-compact"}).status_code == 200
        deadline = time.time() + 10
        while c.get("/api/build/status").json()["state"] == "running":
            assert time.time() < deadline, "the build never finished"
            time.sleep(0.05)
        command = c.get("/api/build/status").json()["command"]
    assert command[command.index("--conventions") + 1] == str(built_from)
    assert _stack(show)[0]["absolute_path"] == str(built_from)


def _second_show(tmp_path: Path) -> Path:
    d = tmp_path / "shows" / "other-show"
    d.mkdir(parents=True)
    (d / "input.csv").write_text((FIXTURES / "smallband.csv").read_text())
    return d


def test_opening_another_bundle_drops_a_typed_conventions_path(tmp_path):
    """The maintainer, 2026-09-24: a conventions file typed into step 01 for one
    show does not carry over to the next. It used to (the house file is
    outside the bundle), but since #236 a bundle's plan records the file it
    was built from, and a path typed for the LAST show would beat that
    record for this one. Opening a bundle now drops it, exactly as it
    already dropped typed input-list and instructions paths.

    Mutation-checked: stop clearing `build_overrides["conventions"]` in
    `/api/bundle/open` and the path assertion below fails."""
    first, second = _show(tmp_path), _second_show(tmp_path)
    house_b = _house(tmp_path, "house-B.md", OTHER_TEXT)
    typed = _house(tmp_path, "typed.md")
    _record(second, house_b)

    app = create_app(initial_bundle=str(first), initial_conventions=None)
    with fastapi_testclient.TestClient(app) as c:
        assert c.post("/api/build/sources/load",
                      json={"slot": "conventions", "path": str(typed)}).status_code == 200
        assert c.post("/api/bundle/open", json={"directory": str(second)}).status_code == 200
        data = c.get("/api/build/sources").json()

    assert data["conventions"]["path"] == str(house_b), "the typed path came along"
    assert _finding(data, "build.conventions-not-plan") is None


def test_after_the_drop_a_bundle_with_no_record_falls_back_to_the_config(tmp_path):
    """The absent case: the second show's plan records no house file, so
    the tile shows the config's -- not the path typed for the first show."""
    first, second = _show(tmp_path), _second_show(tmp_path)
    config_house, typed = _house(tmp_path, "house-config.md"), _house(tmp_path, "typed.md")

    app = create_app(initial_bundle=str(first), initial_conventions=str(config_house))
    with fastapi_testclient.TestClient(app) as c:
        c.post("/api/build/sources/load", json={"slot": "conventions", "path": str(typed)})
        c.post("/api/bundle/open", json={"directory": str(second)})
        data = c.get("/api/build/sources").json()

    assert data["conventions"]["path"] == str(config_house)
