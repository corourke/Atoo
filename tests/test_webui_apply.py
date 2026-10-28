"""The Apply screen (version H phase 4) -- server and assets.

**This is the one screen in Atoo that writes to a console**, so the
tests here are weighted towards the guards rather than the rendering: that
a `confirm` without the arming checkbox writes nothing, that arming alone
writes nothing either, that the pre-flight refusal really does stop a run,
and that a preview leaves no journal behind pretending to be reversible.
Every one of them was mutation-checked -- the guard was removed, the test
was watched to fail, the guard was put back.

**No test here touches a real console.** `atoo apply` is run for
real, in the server's own worker thread, against `test_apply.FakeConsole`
substituted for `atoo.console.WingConsole` -- the same fake the apply
engine's own tests use. Nothing opens a socket.

The second half asserts over the **served assets**, because the Python
suite cannot see the browser: a field `webui.py` renames is
a silently blank element on the page, not an exception.
"""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

import atoo.console as console_module  # noqa: E402
from atoo import console_facts  # noqa: E402
from atoo import bundle as bundle_module  # noqa: E402
from atoo.apply import _build_write_targets, full_apply_targets  # noqa: E402
from atoo.console import OscReply  # noqa: E402
from atoo.webui import _apply_abort_reason, create_app  # noqa: E402
from test_apply import FakeConsole  # noqa: E402
from webui_page import armed  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

# A plan frozen in `tests/fixtures/`, never one out of `examples/`: a
# bundle under `examples/` is a show file the maintainer edits, and a test that
# asserted on its contents would break the next time he touched it.
# This one verifies with **no errors** on its own, and with
# **one error** against `touringband.csv` -- which is exactly the pair the
# pre-flight gate tests need.
CLEAN_PLAN = json.loads((FIXTURES / "applied-show.plan.json").read_text())
INPUT_LIST = FIXTURES / "touringband.csv"

CONSOLE = {"address": "198.51.100.9", "port": 2223, "timeout": 1.0,
           "address_source": "ATOO_CONSOLE"}

IDENTITY = OscReply(address="/?", typetag="s",
                    args=["WING,198.51.100.9,DESK,wing-compact,SER,3.1"])


def _other(value, value_type):
    """A value of the same type this desk could plausibly be sitting at
    that is NOT the planned one -- far enough away that
    `_values_equal`'s stepped-parameter tolerance cannot call it equal."""
    if value_type == "f":
        return float(value) + 50.0
    if value_type == "i":
        return int(value) + 7
    return "was-" + str(value)


def _seeded_state(plan, every_third_already_right=True):
    """A desk that answers every address this plan will write.

    Two thirds of them sit at something else (so a real apply writes
    them), one third already hold the planned value (so a real apply
    skips them, and the journal view has a `skipped_no_change` group to
    collapse). Built from `_build_write_targets`, the same function the
    apply engine builds its own list from, so the desk cannot drift out
    of step with the plan.
    """
    targets, _warnings = _build_write_targets(plan, True)
    # A full apply also unpatches every strip the plan does not build, and
    # sets talkback's assign (`apply.full_apply_targets`, 2026-10-02).
    # Appended, so the plan's own targets keep the indices they had.
    targets = targets + full_apply_targets(plan)
    state = {}
    for index, target in enumerate(targets):
        intended = target.compute_value(None)
        # A real desk answers an "f" leaf with a float, and
        # `OscReply.value("f")` refuses anything else -- a plan that
        # states `-144` is an int until the console has it.
        if target.value_type == "f":
            intended = float(intended)
        already = every_third_already_right and index % 3 == 0
        state[target.address] = (
            intended if already else _other(intended, target.value_type),
            target.value_type,
        )
    return state


class _Desk(FakeConsole):
    """`FakeConsole` with the three things `cli.apply_cmd` needs on top of
    the write/readback surface: a constructor shaped like `WingConsole`'s,
    an `identity()` and the context-manager protocol."""

    #: Set by the fixture before the CLI constructs one, because the CLI
    #: constructs it itself and the test never gets to pass anything in.
    next_state: dict = {}
    reject: set = set()
    made: list = []

    def __init__(self, address, port=2223, timeout=1.0, raw_log=None):
        super().__init__(copy.deepcopy(type(self).next_state))
        self.address = address
        self.port = port
        self.reject_writes_to = set(type(self).reject)
        type(self).made.append(self)

    def identity(self):
        return IDENTITY

    def _reply_to(self, address):
        """Answer the way a real WING does, not the way the state dict
        holds it. A patch connector's GET reply is one LOWER
        than the value its SET takes, and `apply._extract_reply_value`
        puts that back with `console_facts.correct_readback_index`. A fake
        that echoed what it was written would read one high on exactly
        those addresses, and every one of them would come back a false
        mismatch -- which is the bug an earlier change is about, inverted.

        So `state` stays in the values a plan states, and this is the
        wire."""
        reply = super()._reply_to(address)
        offset = console_facts.readback_index_offset(address)
        if not offset or reply is None or reply.typetag != "i":
            return reply
        value = reply.args[0]
        if isinstance(value, bool) or not isinstance(value, int):
            return reply
        return OscReply(address=address, typetag="i", args=[value - offset])

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def desk(monkeypatch):
    """`atoo.console.WingConsole` replaced for the whole test. The
    CLI imports it inside `apply_cmd`, so patching the module attribute is
    enough and no socket is ever opened."""
    _Desk.next_state = {}
    _Desk.reject = set()
    _Desk.made = []
    monkeypatch.setattr(console_module, "WingConsole", _Desk)
    return _Desk


def _bundle(tmp_path, plan=None, with_input_list=False, name="touringband"):
    directory = tmp_path / name
    directory.mkdir()
    if plan is not None:
        (directory / "plan.json").write_text(json.dumps(plan, indent=2))
    if with_input_list:
        (directory / "input.csv").write_text(INPUT_LIST.read_text())
    return directory


def _app(directory, plan=CLEAN_PLAN, console=CONSOLE):
    return create_app(
        initial_bundle=str(directory),
        initial_plan=copy.deepcopy(plan) if plan is not None else None,
        initial_plan_path=str(Path(directory) / "plan.json") if plan is not None else None,
        initial_console=dict(console) if console else None,
    )


@pytest.fixture
def apply_client(tmp_path, desk):
    """A shell over a bundle whose plan verifies clean, with a console
    resolved and a fake desk seeded to answer every address."""
    directory = _bundle(tmp_path, CLEAN_PLAN)
    desk.next_state = _seeded_state(CLEAN_PLAN)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        c.bundle_directory = directory
        yield c


def _wait(c, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = c.get("/api/apply/status").json()
        if status["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("the apply never finished")


def _writes(desk):
    return sum(len(d.set_param_calls) + len(d.set_node_calls) for d in desk.made)


# ======================================================================
# The pre-flight verify block
# ======================================================================


def test_apply_status_is_idle_before_any_apply(apply_client):
    """Always a state, never a 404 -- the page draws "no apply yet" from
    it, the same contract `GET /api/build/status` has."""
    status = apply_client.get("/api/apply/status").json()
    assert status["state"] == "idle"
    assert status["log"] == [] and status["findings"] == [] and status["result"] is None


def test_preflight_runs_verify_and_reports_both_counts(apply_client):
    body = apply_client.get("/api/apply/preflight").json()
    # One warning since A24 (2026-09-28) gave the desk a Pink: the fixture's
    # 'Pink' strip no longer draws `strip.colour-not-writable`.
    assert body["errors"] == 0 and body["warnings"] == 1 and body["ok"] is True
    # And the INFO that a full apply unpatches the strips the plan does
    # not build (`apply.full_apply_notes`), said before anyone arms it.
    assert {f["source"] for f in body["findings"]} == {"verify", "apply"}
    [full] = [f for f in body["findings"] if f["code"] == "apply.unbuilt-strips"]
    assert full["severity"] == "info" and "unpatched from their sources" in full["message"]
    assert body["plan_path"].endswith("plan.json")
    # And the reset to initialized that comes before the plan.
    [init] = [f for f in body["findings"] if f["code"] == "apply.init"]
    assert init["severity"] == "info"
    assert "resets the desk to the WING Compact's initialized state" in init["message"]
    assert "--no-init" in init["message"]


def test_preflight_is_fresh_and_not_the_plans_own_record(tmp_path, desk):
    """`apply` re-verifies immediately before writing and refuses on any
    error; the block on screen has to be THAT check, not the one the build
    recorded about itself. A plan carrying a clean `meta.verify_findings`
    and a real error in its body must read as blocked."""
    plan = copy.deepcopy(CLEAN_PLAN)
    plan["meta"]["verify_findings"] = {"errors": [], "warnings": []}
    plan["channels"][0]["bus_sends"] = [{"bus": "NoSuchBus", "mode": "post", "level_db": 0.0}]
    directory = _bundle(tmp_path, plan)
    with fastapi_testclient.TestClient(_app(directory, plan)) as c:
        body = c.get("/api/apply/preflight").json()
    assert body["errors"] >= 1 and body["ok"] is False
    assert any(f["code"] == "reference.dangling" for f in body["findings"]), body["findings"]


def test_preflight_does_not_block_on_an_unpatched_matrix(tmp_path, desk):
    """A Matrix used as the phones source has no
    physical socket, and `output.no-patch` was an ERROR that blocked
    Apply. It is a WARNING: apply sets the Matrix up and routes it to no
    socket, so the pre-flight reads applicable."""
    plan = copy.deepcopy(CLEAN_PLAN)
    plan["outputs"]["Phones"] = {"kind": "matrix", "index": 2,
                                 "fed_by": {"type": "main", "index": 1},
                                 "fader": {"fader_db": -10.0, "muted": False}}
    directory = _bundle(tmp_path, plan)
    with fastapi_testclient.TestClient(_app(directory, plan)) as c:
        body = c.get("/api/apply/preflight").json()
    assert body["errors"] == 0 and body["ok"] is True
    [warning] = [f for f in body["findings"] if f["code"] == "output.no-patch"]
    assert warning["severity"] == "warning" and warning["where"] == "outputs[Phones]"


def test_preflight_verifies_the_bytes_on_disk_not_the_plan_in_memory(tmp_path, desk):
    """`atoo apply --show DIR` opens `DIR/plan.json` and verifies
    what it finds there. This server may be holding a copy read at
    startup. Edit the file and the two diverge -- and a block reading
    clean over a command that is about to refuse is worse than no block.

    Mutation-checked: make the endpoint verify `app.state.plan` and this
    fails with `errors == 0` over a plan that cannot be applied.

    Caught by running `examples/README.md`'s Apply walkthrough: it told a
    reader to edit the plan and press Re-check, and nothing changed."""
    directory = _bundle(tmp_path, CLEAN_PLAN)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        assert c.get("/api/apply/preflight").json()["errors"] == 0

        broken = copy.deepcopy(CLEAN_PLAN)
        broken["channels"][0]["bus_sends"] = [
            {"bus": "NoSuchBus", "mode": "post", "level_db": 0.0}]
        (directory / "plan.json").write_text(json.dumps(broken))

        body = c.get("/api/apply/preflight").json()

    assert body["errors"] == 1, body["findings"]
    assert [f["code"] for f in body["findings"] if f["severity"] == "error"] \
        == ["reference.dangling"]
    assert body["plan_path"] == str(directory / "plan.json")


def test_preflight_refuses_a_plan_file_that_will_not_parse(tmp_path, desk):
    directory = _bundle(tmp_path, CLEAN_PLAN)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        (directory / "plan.json").write_text("{ not json")
        r = c.get("/api/apply/preflight")
    assert r.status_code == 400
    assert "would refuse it too" in r.json()["error"]


def test_preflight_says_when_it_could_not_check_the_input_list(apply_client):
    """Three checks do not run without the list -- every input became a
    channel, no channel was invented, phantom is safe for the mics in use
    -- and a screen that did not say so would imply an assurance nobody
    made."""
    body = apply_client.get("/api/apply/preflight").json()
    assert body["checked_input_list"] is False and body["input_path"] is None


def test_preflight_reads_the_bundles_input_list_when_there_is_one(tmp_path, desk):
    directory = _bundle(tmp_path, CLEAN_PLAN, with_input_list=True)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        body = c.get("/api/apply/preflight").json()
    assert body["checked_input_list"] is True
    assert body["input_path"].endswith("input.csv")
    assert body["errors"] == 1 and body["ok"] is False
    assert any(f["code"] == "reconcile.invented-source" for f in body["findings"])


def test_preflight_with_no_plan_is_a_404_with_a_body(tmp_path, desk):
    directory = _bundle(tmp_path, plan=None)
    with fastapi_testclient.TestClient(_app(directory, plan=None)) as c:
        r = c.get("/api/apply/preflight")
    assert r.status_code == 404
    assert "no plan loaded" in r.json()["error"]


# ======================================================================
# The arming guard -- FR-X.2, and the reason this screen exists
# ======================================================================


def test_a_confirm_without_the_arming_checkbox_is_refused_and_writes_nothing(
        apply_client, desk):
    """**The guard.** The button says write, the checkbox does not, and
    the request is refused outright rather than quietly downgraded to a
    preview: a write asked for without the arming control is a bug
    somewhere, and a silent preview would hide it.

    Two halves, and both were mutation-checked. Dropping the
    `req.confirm and not req.arm` branch alone leaves the run a preview,
    because `confirmed` is an `and` of the same two flags; drop that as
    well and 471 addresses reach the desk, which is what the write count
    below catches. The status-code assertions come after it on purpose --
    the assertion that must fail first is the one about the console."""
    r = apply_client.post("/api/apply/run", json={"confirm": True, "arm": False})

    # The desk first, deliberately: with the guard removed this request
    # starts a real apply, and the assertion that catches it has to be the
    # one about what reached the console, not the one about a status code.
    _wait(apply_client)
    assert _writes(desk) == 0, "a request with no arming must not reach the desk at all"
    assert not (apply_client.bundle_directory / "apply-journal.json").exists()

    assert r.status_code == 400
    assert "not armed" in r.json()["error"]
    assert "--confirm" in r.json()["error"]
    assert apply_client.get("/api/apply/status").json()["state"] == "idle"


def test_a_request_that_omits_the_arm_key_entirely_is_refused(apply_client, desk):
    """`arm` is the one default in `ApplyRequest` that decides whether an
    under-specified request writes to a desk, and until this test nothing
    exercised it: every other test in this file spells both keys out, so
    flipping the default to `True` left all 44 of them passing while a
    bare `{"confirm": true}` reached the console.

    A client that does not know about the checkbox does not get to skip
    it. The absent key must read as not-armed, not as armed-by-default."""
    r = apply_client.post("/api/apply/run", json={"confirm": True})

    _wait(apply_client)
    assert _writes(desk) == 0, "an absent `arm` key must not be read as armed"
    assert not (apply_client.bundle_directory / "apply-journal.json").exists()

    assert r.status_code == 400
    assert "not armed" in r.json()["error"]


def test_arming_alone_still_only_previews(apply_client, desk):
    """The checkbox is not the button. Ticking it and pressing Preview
    reads the desk and writes nothing."""
    r = apply_client.post("/api/apply/run", json={"confirm": False, "arm": True})
    assert r.status_code == 200
    status = _wait(apply_client)

    assert "--confirm" not in status["command"]
    assert status["result"]["dry_run"] is True
    assert _writes(desk) == 0
    assert not (apply_client.bundle_directory / "apply-journal.json").exists()


def test_armed_and_confirmed_writes_journals_and_says_how_to_reverse_it(
        apply_client, desk):
    r = apply_client.post("/api/apply/run", json=armed(apply_client, "/api/apply/run"))
    assert r.status_code == 200
    status = _wait(apply_client)
    assert status["state"] == "done", status["log"]
    assert status["exit_code"] == 0, status["log"]
    assert _writes(desk) > 0

    from atoo import journal_stack

    [entry] = journal_stack.entries(apply_client.bundle_directory)
    journal = entry.path
    assert journal.parent == apply_client.bundle_directory / "journals"
    assert not (apply_client.bundle_directory / "apply-journal.json").exists()
    result = status["result"]
    assert result["dry_run"] is False
    assert result["journal_path"] == str(journal)
    assert result["summary"].startswith("APPLIED: ")
    assert result["counts"]["written"] > 0

    # An engineer who has just written to a desk wants to know the run is
    # reversible and what reverses it. `atoo undo` does,
    # and the journal file is its argument.
    reversible = [f for f in status["findings"] if f["code"] == "apply.journalled"]
    assert len(reversible) == 1, status["findings"]
    assert f"atoo undo {journal}" in reversible[0]["message"]


def test_an_undo_preview_sends_every_address_and_not_the_last_200_lines_of_a_log(
        apply_client, desk):
    """A full apply writes hundreds of addresses; the run's log keeps its last
    200 lines. The undo preview's rows come from the command's own result
    file, whole -- one per address the apply wrote -- so the page lists them
    all."""
    from atoo import journal_stack

    assert apply_client.post("/api/apply/run",
                             json=armed(apply_client, "/api/apply/run")).status_code == 200
    assert _wait(apply_client)["exit_code"] == 0
    [entry] = journal_stack.entries(apply_client.bundle_directory)
    sent = [w for w in json.loads(entry.path.read_text())["writes"] if w["status"] == "match"]
    assert len(sent) > 200, "the scenario has to be bigger than the log"
    before = _writes(desk)

    assert apply_client.post("/api/undo/run", json={}).status_code == 200
    status = _wait(apply_client)
    assert status["kind"] == "undo" and status["preview"] is True
    undo = status["result"]["undo"]
    assert len(undo["rows"]) == len(sent) and len(status["log"]) <= 200
    assert undo["counts"]["total"] == len(sent)
    assert undo["journal_id"] == entry.id and undo["kind"] == "apply"
    assert _writes(desk) == before


def test_the_apply_is_the_cli_command_not_a_copy_of_it(apply_client):
    """What the browser writes and what a terminal writes cannot drift
    apart: this is `atoo apply`'s own argv, with the one console the
    shell resolved."""
    apply_client.post("/api/apply/run", json=armed(apply_client, "/api/apply/run"))
    status = _wait(apply_client)
    directory = apply_client.bundle_directory
    assert status["command"] == [
        "atoo", "apply", "--show", str(directory),
        "--console", "198.51.100.9", "--port", "2223", "--timeout", "1.0", "--confirm",
    ]


def test_the_journal_goes_where_the_command_would_have_put_it(apply_client):
    """A confirmed apply from the page names no --journal: the command
    puts it where a terminal's would go -- a new entry in the bundle's
    journals/ (an earlier change point 4) -- and the page reads back that
    entry, the one this run added."""
    from atoo import journal_stack

    apply_client.post("/api/apply/run", json=armed(apply_client, "/api/apply/run"))
    status = _wait(apply_client)
    show = bundle_module.load(str(apply_client.bundle_directory))
    assert "--journal" not in status["command"]
    [entry] = journal_stack.entries(show.directory)
    assert status["result"]["journal_path"] == str(entry.path)
    assert entry.path.parent == show.journals


def test_a_preview_leaves_no_journal_anywhere(apply_client, tmp_path, tmp_path_factory,
                                             monkeypatch):
    """`atoo undo` refuses a dry-run journal outright, so a preview
    that left one behind would leave a file that looks reversible and is
    not. The scratch copy the server reads is deleted, and the payload
    names no path.

    The scratch copy is made in a temporary directory of this test's own,
    so another test's preview, running beside it in another worker,
    cannot add or remove one between the two looks."""
    import tempfile

    scratch_root = tmp_path_factory.mktemp("preview-scratch")
    monkeypatch.setattr(tempfile, "tempdir", str(scratch_root))
    before_bundle = {p.name for p in tmp_path.rglob("*")}
    before_scratch = set(scratch_root.glob("atoo-preview-*"))

    apply_client.post("/api/apply/run", json={"confirm": False, "arm": False})
    status = _wait(apply_client)

    assert status["result"]["dry_run"] is True
    assert status["result"]["journal_path"] is None
    assert not (apply_client.bundle_directory / "apply-journal.json").exists()
    assert {p.name for p in tmp_path.rglob("*")} == before_bundle
    assert set(scratch_root.glob("atoo-preview-*")) == before_scratch


def test_an_apply_run_from_the_browser_lands_on_the_bundles_journal_stack(apply_client):
    """The Apply screen names the journal explicitly (it has
    to read back the records it draws), and that must not be a way to
    write to a desk without the write appearing on the bundle's stack --
    otherwise every apply made from the browser would be invisible to
    `atoo undo --show DIR`.

    Mutation-checked: drop the `_record_on_stack` call from
    `cli.apply_cmd` and this fails, while every other test in this file
    stays green.
    """
    from atoo import journal_stack

    apply_client.post("/api/apply/run", json=armed(apply_client, "/api/apply/run"))
    status = _wait(apply_client)
    assert status["exit_code"] == 0, status["log"]

    directory = apply_client.bundle_directory
    entries = journal_stack.entries(directory)
    assert [e.kind for e in entries] == ["apply"]
    assert journal_stack.top(directory).id == entries[0].id
    # The very file the page read back, and no top-level copy.
    assert status["result"]["journal_path"] == str(entries[0].path)
    assert not (directory / "apply-journal.json").exists()


def test_the_journal_the_page_reads_back_is_this_runs_after_recording(apply_client):
    """`api_apply_run` finds this run's journal as the stack entry it
    added, and an earlier change rewrites that entry after the command's write (to
    stamp it with its `stack_entry` block). The page reads it once the
    command has returned, so what it draws is the recorded run."""
    apply_client.post("/api/apply/run", json=armed(apply_client, "/api/apply/run"))
    status = _wait(apply_client)
    assert status["result"] is not None
    assert status["result"]["counts"]["written"] > 0
    assert status["result"]["dry_run"] is False


def test_a_preview_from_the_browser_puts_nothing_on_the_stack(apply_client):
    """A preview writes nothing to the desk, so there is nothing to
    reverse and nothing to record. `atoo undo` refuses a dry-run
    journal outright; a stack row for one would be a line on this very
    screen that looks reversible and is not."""
    from atoo import journal_stack

    apply_client.post("/api/apply/run", json={"confirm": False, "arm": False})
    _wait(apply_client)
    assert journal_stack.entries(apply_client.bundle_directory) == []


# ======================================================================
# The pre-flight gate, doing its job
# ======================================================================


def test_the_pre_flight_gate_stops_an_armed_apply(tmp_path, desk):
    """`apply` runs `verify_plan` before a single packet goes out and
    refuses on any ERROR. Armed, confirmed, and still nothing written.

    Mutation-checked: this is the command's own gate, and removing
    `if not args.skip_verify` from `cli.apply_cmd` makes this test fail on
    the write count."""
    directory = _bundle(tmp_path, CLEAN_PLAN, with_input_list=True)
    desk.next_state = _seeded_state(CLEAN_PLAN)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        c.post("/api/apply/run", json=armed(c, "/api/apply/run"))
        status = _wait(c)

    assert status["state"] == "done" and status["exit_code"] == 2
    assert any("Refusing to apply" in line for line in status["log"]), status["log"]
    assert status["result"] is None
    assert _writes(desk) == 0
    assert not (directory / "apply-journal.json").exists()


def test_a_refused_run_never_draws_the_bundles_PREVIOUS_journal(tmp_path, desk):
    """A bundle carries the journal of its last apply, and a run the gate
    refuses writes no journal at all. Reading the path unconditionally
    drew last week's 707 addresses as the result of a run that sent
    nothing -- a false proof, which is the one outcome this tool exists to
    prevent. Found by running `examples/README.md`'s own Apply
    walkthrough on a copy of `examples/touringband`, which ships one.

    The previous journal is the stack's newest entry, and
    the page reads only an entry THIS run added (`_RunJournal`).
    Mutation-checked: read the stack's newest apply entry instead and this
    test fails with a `result` full of a journal nobody wrote today."""
    from atoo import journal_stack

    directory = _bundle(tmp_path, CLEAN_PLAN, with_input_list=True)
    stale = json.loads((FIXTURES / "touringband-2026-09-18.apply-journal.json").read_text())
    source = tmp_path / "last-week.apply-journal.json"
    source.write_text(json.dumps(stale))
    [previous] = [journal_stack.record(directory, "apply", source)]
    stale = json.loads(previous.path.read_text())
    desk.next_state = _seeded_state(CLEAN_PLAN)

    with fastapi_testclient.TestClient(_app(directory)) as c:
        c.post("/api/apply/run", json=armed(c, "/api/apply/run"))
        status = _wait(c)

    assert status["exit_code"] == 2, status["log"]      # the gate refused it
    assert status["result"] is None, "a refused run must draw no journal at all"
    assert _writes(desk) == 0
    # And the journal that was there is untouched -- nothing overwrote it.
    assert json.loads(previous.path.read_text()) == stale
    assert [e.id for e in journal_stack.entries(directory)] == [previous.id]


def test_skip_verify_writes_the_plan_the_gate_refused(tmp_path, desk):
    directory = _bundle(tmp_path, CLEAN_PLAN, with_input_list=True)
    desk.next_state = _seeded_state(CLEAN_PLAN)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        c.post("/api/apply/run",
               json=armed(c, "/api/apply/run", skip_verify=True))
        status = _wait(c)

    assert "--skip-verify" in status["command"]
    assert status["state"] == "done" and status["exit_code"] == 0
    assert _writes(desk) > 0


# ======================================================================
# The journal view's payload
# ======================================================================


def test_mismatches_are_expanded_and_the_boring_rows_are_counted(apply_client, desk):
    """Version H's journal: the rows somebody has to read are expanded;
    the six hundred that landed are a count with a sample behind a
    disclosure."""
    targets, _ = _build_write_targets(CLEAN_PLAN, True)
    # Three the desk is NOT already sitting at -- an address `_seeded_state`
    # left already correct is skipped without a write, so refusing it would
    # prove nothing.
    refused = {t.address for i, t in enumerate(targets) if i % 3}
    refused = set(sorted(refused)[:3])
    desk.reject = refused

    apply_client.post("/api/apply/run", json=armed(apply_client, "/api/apply/run"))
    status = _wait(apply_client)
    result = status["result"]

    assert result["counts"]["mismatch"] == len(refused)
    assert {r["address"] for r in result["flagged"]} == refused
    assert all(r["status"] == "mismatch" for r in result["flagged"])

    groups = {g["key"]: g for g in result["groups"]}
    assert set(groups) == {"match", "skipped_no_change"}
    assert groups["match"]["count"] > 100, "the boring rows must be counted, not listed"
    assert groups["skipped_no_change"]["count"] > 0
    assert groups["match"]["records"], "a group still carries a sample to expand"

    # And one dock finding for the class, never one per address.
    mismatch_findings = [f for f in status["findings"] if f["code"] == "apply.mismatch"]
    assert len(mismatch_findings) == 1
    assert mismatch_findings[0]["severity"] == "error"


def test_a_preview_puts_every_row_in_a_tile_and_lists_none(apply_client):
    """A preview's rows are in its drawing's tiles, each in
    exactly one, and the result lists none of its own (the page has no
    "All N changes" list any more)."""
    apply_client.post("/api/apply/run", json={"confirm": False, "arm": False})
    result = _wait(apply_client)["result"]
    assert result["groups"] == []
    tiles = result["drawing"]["tiles"]
    rows = [r for t in tiles.values() for r in t["rows"]]
    assert len(rows) == result["counts"]["total"]
    assert len({r["address"] for r in rows}) == len(rows)
    assert result["summary"].startswith("DRY RUN: ")
    assert f"{result['counts']['would_change']} would change" in result["summary"]


def test_would_change_is_the_engines_answer_not_a_recomputed_one(apply_client):
    """`would_change` is `_values_equal`, type-aware and
    tolerant for floats. Each tile row carries the engine's answer, so the
    browser never has to ask the question with a `!==` of its own, and the
    tiles' changes add up to the preview's count."""
    apply_client.post("/api/apply/run", json={"confirm": False, "arm": False})
    result = _wait(apply_client)["result"]
    tiles = result["drawing"]["tiles"]
    assert sum(t["changes"] for t in tiles.values()) == result["counts"]["would_change"]
    assert sum(1 for t in tiles.values() for r in t["rows"] if r["changes"]) \
        == result["counts"]["would_change"]


def test_the_summary_is_apply_results_own_words(apply_client):
    """`ApplyResult.summary()`, reused verbatim rather than paraphrased --
    the string the command prints in a terminal is the string the page
    prints, so the two can never word the same run differently."""
    apply_client.post("/api/apply/run", json=armed(apply_client, "/api/apply/run"))
    status = _wait(apply_client)
    summary = status["result"]["summary"]
    # It is in the command's own stdout too, which is where it came from.
    assert any(summary.splitlines()[0] == line.strip() for line in status["log"]), status["log"]


def test_replies_discarded_is_surfaced_in_its_own_right(apply_client, desk):
    """A desk that duplicates datagrams is the condition that made the
    2026-09-21 journal worthless. A run that says nothing about it cannot
    be told apart from one where it did not happen -- so it is a field of
    its own, not only a sentence inside the summary."""
    apply_client.post("/api/apply/run", json=armed(apply_client, "/api/apply/run"))
    result = _wait(apply_client)["result"]
    assert "replies_discarded" in result and "replies_used" in result
    assert result["replies_discarded"] == sum(d.replies_discarded for d in desk.made)


def test_unreadable_addresses_are_flagged_and_warned_about(tmp_path, desk):
    """A baseline read that fails means a write with no known prior value,
    which is a write that cannot be reversed (FR-X.3) -- so it is skipped,
    expanded in the journal, and warned about in the dock."""
    directory = _bundle(tmp_path, CLEAN_PLAN)
    desk.next_state = {}  # a desk that answers NODE NOT FOUND to everything
    with fastapi_testclient.TestClient(_app(directory)) as c:
        c.post("/api/apply/run", json=armed(c, "/api/apply/run"))
        status = _wait(c)

    result = status["result"]
    assert result["counts"]["unreadable"] == result["counts"]["total"] > 0
    assert all(r["status"] == "unreadable_skipped" for r in result["flagged"])
    assert [f["code"] for f in status["findings"] if f["severity"] == "warning"] \
        == ["apply.unreadable"]
    assert _writes(desk) == 0


def test_the_abort_reason_parser_reads_apply_results_own_wording():
    """`_apply_abort_reason` reads one literal out of
    `ApplyResult.summary()`, because `_write_journal` does not record
    `aborted`. This pins that coupling: the wording is taken from the real
    method, not restated here."""
    from atoo.apply import ApplyResult

    summary = ApplyResult(dry_run=False, aborted=True,
                          abort_reason="host unreachable").summary()
    assert _apply_abort_reason(summary.splitlines()) == "host unreachable"
    assert _apply_abort_reason(["APPLIED: 3 address(es) evaluated, 3 written, 0 mismatch(es)."]) \
        is None


# ======================================================================
# Refusals that never reach the command
# ======================================================================


def test_an_apply_needs_a_show_bundle(desk):
    with fastapi_testclient.TestClient(create_app(initial_console=dict(CONSOLE))) as c:
        r = c.post("/api/apply/run", json={})
    assert r.status_code == 400 and "no show bundle open" in r.json()["error"]


def test_an_apply_needs_a_plan_in_that_bundle(tmp_path, desk):
    directory = _bundle(tmp_path, plan=None)
    with fastapi_testclient.TestClient(_app(directory, plan=None)) as c:
        r = c.post("/api/apply/run", json={})
    assert r.status_code == 400 and "does not exist yet" in r.json()["error"]


def test_an_apply_needs_a_console_and_says_the_two_ways_to_set_one(tmp_path, desk):
    """There is no console field on this screen -- one console, resolved
    once, shown with its provenance in the bundle bar. With none
    resolved the fix is outside the browser, so the refusal names it."""
    directory = _bundle(tmp_path, CLEAN_PLAN)
    with fastapi_testclient.TestClient(_app(directory, console=None)) as c:
        r = c.post("/api/apply/run", json={})
    assert r.status_code == 400
    assert "ATOO_CONSOLE" in r.json()["error"]
    assert "[console]" in r.json()["error"]


def test_a_full_apply_initializes_unless_the_request_says_not_to(apply_client):
    apply_client.post("/api/apply/run", json={})
    assert "--no-init" not in _wait(apply_client)["command"]
    apply_client.post("/api/apply/run", json={"initialize": False})
    assert "--no-init" in _wait(apply_client)["command"]


def test_the_preflight_says_whether_initialize_can_do_anything_and_whether_it_is_off(apply_client):
    on = apply_client.get("/api/apply/preflight").json()
    assert on["initialize"]["available"] is True and on["initialize"]["why"] == ""
    codes = {f.get("code") for f in on["findings"]}
    off = apply_client.get("/api/apply/preflight?initialize=0").json()
    off_codes = {f.get("code") for f in off["findings"]}
    assert "apply.init" in codes and "apply.init" not in off_codes
    assert "apply.init-off" in off_codes


def test_a_request_with_the_old_clean_output_sockets_field_does_not_send_the_flag(apply_client):
    apply_client.post("/api/apply/run", json={"clean_output_sockets": "LCL=8"})
    assert "--clean-output-sockets" not in _wait(apply_client)["command"]


def test_a_second_apply_while_one_runs_is_refused(apply_client, monkeypatch):
    import threading

    import atoo.apply as apply_module

    release = threading.Event()
    real = apply_module.apply_plan

    def slow(*a, **k):
        release.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(apply_module, "apply_plan", slow)
    assert apply_client.post("/api/apply/run", json={}).status_code == 200
    # Give the worker thread a moment to get as far as `apply_plan`.
    for _ in range(200):
        if apply_client.get("/api/apply/status").json()["state"] == "running":
            break
        time.sleep(0.01)
    second = apply_client.post("/api/apply/run", json={})
    assert second.status_code == 409
    assert second.json() == {"error": "an apply is already running"}
    release.set()
    _wait(apply_client)


def test_a_failed_preview_is_a_finding_not_a_crash(tmp_path, desk, monkeypatch):
    """A desk that never answers its identity: exit 1, state `failed`, and
    one finding carrying the command's own last word. The press was
    Preview (no confirm), so it is `preview.failed`, "Preview failed",
    and says nothing was written -- never "the apply did not run"."""
    class Silent(_Desk):
        def identity(self):
            return None

    monkeypatch.setattr(console_module, "WingConsole", Silent)
    directory = _bundle(tmp_path, CLEAN_PLAN)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        c.post("/api/apply/run", json={})
        status = _wait(c)

    assert status["state"] == "failed" and status["exit_code"] == 1
    assert status["result"] is None
    assert status["preview"] is True
    assert not [f for f in status["findings"] if f["code"] == "apply.failed"]
    failed = [f for f in status["findings"] if f["code"] == "preview.failed"]
    assert len(failed) == 1 and "no reply from 198.51.100.9" in failed[0]["message"]
    assert failed[0]["message"].startswith("Preview failed (exit 1)")
    # The command's own "which Atoo ran" line follows, so a failure reported to
    # someone else says which copy it came from.
    assert re.search(r"Nothing was written\.( Ran as atoo [^\n]*)?$", failed[0]["message"])


def test_a_failed_write_and_a_failed_preview_are_worded_apart():
    """The runner words a failure by what was pressed: an armed apply that
    could not run is `apply.failed`; a preview of any kind is
    `preview.failed`, naming that kind."""
    from atoo.webui import ApplyRun

    def failed(kind, preview):
        run = ApplyRun()
        run.kind, run.preview, run.exit_code = kind, preview, 1
        run.log = ["no reply from 198.51.100.9:2223"]
        return run._failure_finding()

    assert failed("apply", False)["code"] == "apply.failed"
    assert failed("apply", True)["code"] == "preview.failed"
    assert failed("patch", True)["message"].startswith("Patch preview failed")
    assert failed("undo", True)["message"].startswith("Undo preview failed")
    assert failed("undo", False)["code"] == "undo.failed"


def test_the_shell_embeds_the_apply_run_at_first_paint(apply_client):
    """A reload part way through an apply must land on the run, not on a
    blank screen that invites someone to press the button again."""
    page = apply_client.get("/").text
    start = page.index('id="initial-shell"')
    blob = page[page.index(">", start) + 1:page.index("</script>", start)]
    assert json.loads(blob)["apply"]["state"] == "idle"


# ======================================================================
# The served assets -- the Python suite cannot see the browser
# ======================================================================


@pytest.fixture
def assets():
    app = create_app()
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_apply_js_wires_the_initialize_switch_and_the_typed_socket_box_is_gone(assets):
    js = assets.get("/static/apply.js").text
    html = assets.get("/static/shell.html").text
    assert 'el("apply-init")' in js and "initialize: initOn()" in js
    assert 'role="switch"' in html and 'id="apply-init"' in html
    assert "cleanValue" not in js and "clean_output_sockets" not in js
    assert "apply-clean" not in html and "apply-clean" not in js


def test_apply_js_is_served_and_the_shell_loads_it(assets):
    assert assets.get("/static/apply.js").status_code == 200
    assert '<script src="/static/apply.js">' in assets.get("/static/shell.html").text


def test_shell_html_carries_every_apply_element_apply_js_fills(assets):
    """`el(id)` returning null is a silent no-op in this codebase's style,
    so an id renamed on one side and not the other is a dead control, not
    an exception."""
    html = assets.get("/static/shell.html").text
    js = assets.get("/static/apply.js").text
    import re

    for element_id in sorted(set(re.findall(r'el\("([a-z0-9-]+)"\)', js))):
        if element_id == "initial-shell":
            continue  # webui.py splices this one in per request
        assert f'id="{element_id}"' in html, f"shell.html has no #{element_id}"


def test_apply_js_reads_every_apply_key_webui_sends(assets):
    """The wire shape `_apply_payload` and `ApplyRun.status()` send. A key
    renamed in Python and not here renders a blank element rather than
    throwing."""
    js = assets.get("/static/apply.js").text
    for key in ("result.summary", "result.dry_run", "result.journal_path",
                "result.aborted", "result.replies_discarded",
                "result.replies_used", "result.counts", "result.flagged",
                "result.groups", "record.address", "record.description",
                "record.status", "record.prior_value", "record.intended_value",
                "record.readback_value", "record.readback_source",
                "group.count", "group.label", "group.records",
                "preflight.errors", "preflight.warnings", "preflight.findings",
                "preflight.checked_input_list",
                "run.state", "run.log", "run.command", "run.exit_code",
                "run.elapsed_s", "run.started_at", "run.findings", "run.result"):
        assert key in js, f"apply.js never reads {key}"
    # The counts are read as `c` (`const c = result.counts`).
    assert "const c = result.counts;" in js and "const c = run.result.counts;" in js
    for count in ("total", "would_change", "written", "mismatch", "unreadable", "cleaned"):
        assert f"c.{count}" in js, f"apply.js never reads counts.{count}"
    # And the drawing of the desk (desk_view.full_build_desk), and where it was read.
    for key in ("run.result.drawing", "drawing.sections", "drawing.counts", "run.on",
                "strip.colour", "strip.name", "strip.changes", "section.count"):
        assert key in js, f"apply.js never reads {key}"


def test_apply_lists_no_findings_of_its_own(assets):
    """The dock is the one place findings are read. Apply's
    pre-flight block and its result panel each keep one line counting
    theirs, and list none: the pre-flight's findings were drawn twice
    (here and in the dock), and the journal's warnings were drawn here
    and nowhere else."""
    js = assets.get("/static/apply.js").text
    html = assets.get("/static/shell.html").text
    for gone in ("apply-preflight-list", "preflightFinding", "apply-warnings-list",
                 "result.warnings"):
        assert gone not in js, f"apply.js still lists findings ({gone})"
        assert f'id="{gone}"' not in html
    assert 'id="apply-preflight-summary"' in html and 'id="apply-result-findings"' in html
    # Errors and warnings are on the pre-flight badge; the line
    # beside it counts the notes and links to the dock -- by the dock's
    # folds since an earlier change (see the test below).
    assert "preflightNotesLine(preflightSummary, preflight.findings);" in js


def test_box_1_counts_the_preflights_notes_by_the_docks_folds(assets):
    """Box 1 said "7 notes in Findings" while the dock said 6
    notes on choices -- the dock counts the whole show's notes (the
    build's, and after a preview the run's), and folds some of the
    pre-flight's under Build details. The line counts the pre-flight's own
    notes, one per finding as the dock counts rows, says which fold each
    is among, and its link flashes exactly those in the dock."""
    js = assets.get("/static/apply.js").text
    shell = assets.get("/static/shell.js").text
    start = js.index("function preflightNotesLine(")
    body = js[start:js.index("function renderPreflight(", start)]
    assert '" among Choices"' in body and '" among Build details"' in body
    assert "SP.isBuildDetail" in body
    # One per finding: the dock's unit, not `members` (severityCounts').
    assert "members" not in body
    assert '_producer === "apply-preflight"' in body and "SP.showFindings(mine)" in body
    # The shell decides what Build details holds, from finding_groups.
    assert "isBuildDetail: (f) =>" in shell and "BUILD_DETAILS.has(f.code)" in shell
    assert '"show in Findings →"' in body


def test_a_previews_sample_does_not_point_at_a_journal(assets):
    """A collapsed group's sample line said "all of them are in
    the journal file" after a preview, which writes none. Since an earlier change
    a preview shows no groups at all (its rows are in its tiles), and the
    journal is named only when the result has one."""
    js = assets.get("/static/apply.js").text
    start = js.index("function sampleNote(")
    body = js[start:js.index("function groupElement(", start)]
    assert body.index("if (result && result.journal_path)") < body.index(
        "all of them are in the journal file")
    assert js.count("in the journal file") == 1
    assert "groupElement(g, result)" in js
    assert "const shown = !!result && mine && !result.dry_run;" in js


def test_the_journals_warnings_reach_the_dock():
    """What Apply's result panel listed under "Warnings and notes" is in
    the dock, grouped (FR-X.15c) and with its severity:
    a line the journal marks `INFO ` is a note, any other a warning."""
    from atoo.webui import _apply_findings

    payload = {"dry_run": True, "journal_path": None, "flagged": [],
               "counts": {"mismatch": 0, "unreadable": 0, "written": 0},
               "warnings": ["ch 1-4 (4 channels): patch socket was not stated",
                            "INFO the desk is a Compact"]}
    found = [(f["severity"], f["code"], f["message"]) for f in _apply_findings(payload, "x")]
    assert found == [
        ("warning", "apply.journal-warning", "ch 1-4 (4 channels): patch socket was not stated"),
        ("info", "apply.journal-note", "the desk is a Compact")]


def test_there_is_exactly_one_arming_control_on_the_one_screen_that_writes(assets):
    """The maintainer's rule: exactly one screen in Atoo writes to a
    console, and it carries one arming control. A second checkbox here --
    or an arming control on any other page -- is the thing the rule
    forbids (`OPTIONS-H.md`)."""
    import re

    html = assets.get("/static/shell.html").text
    served = assets.get("/").text
    # Every id on the shell with `arm` in it, and there is exactly one --
    # in the file on disk and in the page as served. Until an earlier change
    # there was a second, separate Watch page to check for none; Watch is
    # now a mode of this page, so "exactly one here" is the whole claim.
    assert re.findall(r'id="[^"]*arm[^"]*"', html) == ['id="apply-arm-checkbox"']
    assert re.findall(r'id="[^"]*arm[^"]*"', served) == ['id="apply-arm-checkbox"']
    assert html.count('type="checkbox" id="apply-arm-checkbox"') == 1
    # The label is "Arm", in step 3's Arm section; the red button that spends it
    # is in the section after it, directly under its own header (Write, or
    # Undo after an undo preview), never beside the tick.
    row = html[html.index('class="apply-run-row apply-arm-row"'):]
    row = row[:row.index("</div>")]
    assert 'id="apply-arm-checkbox"> <span>Arm</span>' in row and 'id="apply-run-btn"' not in row
    box = html[html.index('id="apply-step-3-box"'):html.index('id="journal-stack-panel"')]
    assert box.index("<h3>Arm</h3>") < box.index('id="apply-arm-checkbox"') < box.index("<h3>Write</h3>")
    assert box.index("<h3>Write</h3>") < box.index('id="apply-run-btn"') < box.index("<h3>Undo</h3>")
    assert box.index("<h3>Undo</h3>") < box.index('id="undo-run-btn"')
    assert "<code>--confirm</code>" in html


def test_apply_js_never_words_the_summary_itself(assets):
    """`ApplyResult.summary()` is reused verbatim. A second copy of its
    wording here is how the page and the terminal come to describe the
    same run differently."""
    js = assets.get("/static/apply.js").text
    for phrase in ("address(es) evaluated", "would change, nothing written",
                   "mismatch(es)", "stale reply"):
        assert phrase not in js, f"apply.js paraphrases summary(): {phrase!r}"


def test_apply_js_never_recomputes_would_change(assets):
    """`_values_equal` is type-aware and carries a tolerance
    for floats. A `!==` here would overstate a preview by exactly the
    addresses that issue is about."""
    js = assets.get("/static/apply.js").text
    for comparison in ("prior_value !=", "prior_value ===", "prior_value =="):
        assert comparison not in js, f"apply.js compares values itself: {comparison!r}"
    # The tiles' rows carry the server's answer.
    assert "d.rows.filter((r) => r.changes)" in js, "apply.js must read the server's answer"


def test_the_journal_view_says_the_run_is_reversible_and_names_the_file(assets):
    # One line -- the journal's file name, and that Undo below
    # puts every address back -- rather than a paragraph and a CLI line.
    js = assets.get("/static/apply.js").text
    assert "Undo, in History, puts every address back." in js
    assert "result.journal_path" in js


def test_the_pre_flight_gate_is_visible_on_the_page_not_implied(assets):
    html = assets.get("/static/shell.html").text
    assert 'id="apply-preflight-panel"' in html
    assert "Pre-flight verify" in html
    # What it is, in a popup opened from the line's "?".
    assert 'data-popup="popup-preflight"' in html and 'id="popup-preflight"' in html
    assert "a setting that can't work on this desk" in html


def test_the_amend_switch_is_drawn_on_this_screen(assets):
    """Phase 5 reuses this switch rather than adding its own:
    Amend is a mode of Apply, not a page. Phase 4 drew it disabled; the
    enabled flow is tested in `test_webui_amend.py`."""
    html = assets.get("/static/shell.html").text
    switch = html[html.index('id="apply-mode-switch"'):]
    assert 'id="apply-mode-full"' in switch and 'id="apply-mode-amend"' in switch
    assert html.index('id="apply-mode-switch"') > html.index('id="mode-apply"')


def test_styles_css_carries_the_apply_vocabulary(assets):
    css = assets.get("/static/styles.css").text
    for cls in (".apply-shell", ".apply-step", ".desk-strip", ".sp-popup", ".apply-arm-checkbox",
                ".apply-record", ".apply-record.is-mismatch",
                ".apply-record.is-unreadable", ".apply-journal-group",
                ".apply-journal-groups", ".apply-chips", ".step-no", ".lock-reason", ".apply-warn-caption",
                ".btn-danger", ".seg", ".seg-opt", ".switch"):
        assert cls in css, f"styles.css has no rule for {cls}"


def test_the_apply_panels_start_hidden(assets):
    """`hidden` on the run and result panels, so a fresh page shows the
    controls and nothing else -- these are drawn by JS, and an unhidden
    empty panel is a page that looks broken before anyone presses
    anything."""
    html = assets.get("/static/shell.html").text
    for element_id in ("apply-run-panel", "apply-result-panel"):
        marker = html.index(f'id="{element_id}"')
        assert "hidden" in html[marker:html.index(">", marker)], element_id


def test_watch_mode_adds_no_write_path_and_no_second_arming_control(assets):
    """This checked that Apply left the separate Watch
    page at `/` alone. Watch now shares a page with Apply, so the property
    worth keeping is the one that page separation used to give for free:
    Watch is read-only (FR-6.7), there is exactly ONE arming control in
    Atoo, and it is Apply's. Watch's script may not reach an apply
    endpoint or touch the arming checkbox, and the moved markup may not
    bring a second checkbox that looks like one."""
    page = assets.get("/").text
    watch_js = assets.get("/static/watch.js").text
    for marker in ("apply-arm-checkbox", "/api/apply", "confirm", "arm"):
        assert marker not in watch_js.replace("arming control", ""), marker
    assert page.count('id="apply-arm-checkbox"') == 1
    assert page.count("<span>Arm</span>") == 1
    watch_panel = page[page.index('id="mode-watch"'):page.index("The findings dock")]
    assert 'type="checkbox"' not in watch_panel, (
        "the Watch panel's static markup carries a checkbox -- the only checkbox "
        "that means anything near a console is Apply's arming control"
    )
    # Watch's rows carry a Hide check box, drawn by watch.js, which hides a
    # row on this page and reaches nothing (like the findings pane's own). The
    # other checkbox is the watch-conditions editor's value box (a condition's
    # `muted == true`), which is a field of the file, not a control.
    assert watch_js.count('.type = "checkbox"') == 1
    assert watch_js.count('wcMakeInput("checkbox"') == 1
    assert 'wcMakeInput("checkbox", cond.value, "wc-value-checkbox")' in watch_js
    maker = watch_js[watch_js.index("function makeHideCheck("):]
    maker = maker[:maker.index("\n  }\n")]
    assert 'box.type = "checkbox"' in maker
    assert 'box.className = "watch-row-hide"' in maker
    assert "fetch(" not in maker
