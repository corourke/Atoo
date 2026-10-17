"""The architecture as wired into the CLI.

Three things get tested here that the experiment could not:

  - verification runs on EVERY plan, not just generated ones. The first
    thing the verifier ever did was reject the *compiler's* own plan, so
    binding it to the generate path would have thrown away most of its
    value.
  - `atoo apply` refuses a plan that fails verification. `build` says
    it will; this is where that promise is kept.
  - verify_plan without an input list says what it did not check, rather
    than returning a clean result that implies an assurance nobody made.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo.cli import main
from atoo.input_list import load_input_list
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).parent / "fixtures"
GENERATED = Path(__file__).parent / "fixtures" / "touringband.generated.plan.json"


@pytest.fixture
def touring(tmp_path):
    for name in ("touringband.csv", "touringband.md"):
        (tmp_path / name).write_text((FIXTURES / name).read_text())
    return tmp_path


#: A socket a WING Compact does not have: the touringband Matrix patched
#: here is a physical setting that cannot work, so verify refuses it.
NO_SUCH_SOCKET = {"group": "LCL", "sockets": [99]}
REFUSAL = "output.socket-out-of-range"


def stub_refused_build(stub_build) -> dict:
    """The touringband stub plan, made unapplyable.

    Its Matrix states no patch, which is a working desk (the maintainer,
    2026-10-09: a Matrix used as the phones source has no socket) and
    only a WARNING, `output.no-patch`. A test of the refusal gate needs a
    plan the desk cannot take, so this one patches that Matrix into a
    local output the Compact does not have. `stub_build` returns the
    plan its stub will build, so editing it here changes the build."""
    plan = stub_build("touringband")
    matrix = plan["outputs"]["Matrix"]
    matrix["socket"] = dict(NO_SUCH_SOCKET)
    matrix["sockets"] = [dict(NO_SUCH_SOCKET)]
    return plan


def test_build_exits_two_when_the_plan_cannot_be_applied(stub_build, touring, capsys):
    """A plan the desk cannot take (its Matrix patched to a socket the
    Compact does not have) is a stop at build, so `build && apply` cannot
    walk into it."""
    stub_refused_build(stub_build)
    code = main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--out", str(touring / "p.json")])
    assert code == 2
    err = capsys.readouterr().err
    assert REFUSAL in err
    assert "apply` will refuse it" in err
    # ...and the plan is still written, so it can be read and fixed
    assert (touring / "p.json").exists()


def test_build_writes_no_report_file_beside_the_plan(stub_build, touring):
    """An earlier change originally wrote a `.report.md` file beside the plan;
    an earlier change retired it once the same findings (critic and verify) were
    folded directly into plan.json's own `meta` -- one file, not two. `build` must never write a `.report.md`
    companion."""
    stub_refused_build(stub_build)
    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--out", str(touring / "p.json")])
    assert not (touring / "p.report.md").exists()
    meta = json.loads((touring / "p.json").read_text())["meta"]
    assert meta["verify_at_generation"]["summary"] == "BLOCKED -- do not apply"
    codes = {f["code"] for f in meta["verify_findings"]["errors"]}
    assert REFUSAL in codes  # the same info, now in plan.json alone


def test_out_dash_writes_no_files(stub_build, touring, monkeypatch):
    """--out - means stdout only, by design -- nothing on disk gets
    written at all, plan or otherwise: no build log either,
    and -- since there is no bundle and no real file to sit beside --
    nowhere in particular for one to fall back to, which a wrong fallback
    could put in the process's OWN current directory rather than
    anywhere near this build (`build_log.directory_for` returns `None`
    for exactly this case)."""
    stub_build("touringband")
    before = set(touring.iterdir())
    monkeypatch.chdir(touring)
    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--out", "-"])
    assert set(touring.iterdir()) == before


def test_skip_verify_restores_the_old_exit_code(stub_build, touring):
    stub_build("touringband")
    code = main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--skip-verify", "--out", str(touring / "p.json")])
    assert code == 0


def test_apply_refuses_a_plan_that_fails_verification(stub_build, touring, capsys):
    """Refusal happens before the console is contacted -- no --console is
    reachable in this test, and the command must still fail at the gate
    rather than at the network."""
    stub_refused_build(stub_build)
    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])

    code = main(["apply", "--plan", str(touring / "p.json"),
                 "--console", "203.0.113.1"])
    assert code == 2
    err = capsys.readouterr().err
    assert "Refusing to apply" in err
    assert "--skip-verify" in err


def test_apply_accepts_raw_log_flag_without_reaching_network(stub_build, touring, capsys, tmp_path):
    """`--raw-log` is parsed and doesn't disturb the refusal
    gate above -- the actual raw-log-writes-traffic behavior is
    console.py's own, already covered by test_console.py's
    test_raw_log_records_traffic against a fake local server."""
    stub_refused_build(stub_build)
    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])

    code = main(["apply", "--plan", str(touring / "p.json"),
                 "--console", "203.0.113.1", "--raw-log", str(tmp_path / "raw.log")])
    assert code == 2
    assert "Refusing to apply" in capsys.readouterr().err


def test_apply_reports_a_socket_error_at_connect_clearly_instead_of_garbage(stub_build, touring, capsys, monkeypatch):
    """A genuine socket-level failure (host unreachable,
    connection refused, ...) on the initial identity() check must be
    caught explicitly, not treated as a successful connection because a
    SOCKET_ERROR OscReply happens to be truthy. Before the fix this
    printed the nonsensical `Console: OSError: [Errno 65] No route to
    host` and went on to flood hundreds of UNREADABLE lines from
    apply_plan(); after the fix it stops right here with one clear line
    and never reaches apply_plan() at all."""
    stub_build("touringband")
    import atoo.console as console_module
    from atoo.console import OscReply

    class FakeSocketErrorConsole:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def identity(self):
            return OscReply(address="/?", typetag="SOCKET_ERROR", args=["OSError: [Errno 65] No route to host"])

        def close(self):
            pass

    monkeypatch.setattr(console_module, "WingConsole", FakeSocketErrorConsole)

    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])

    code = main(["apply", "--plan", str(touring / "p.json"), "--skip-verify",
                 "--console", "192.0.2.16"])
    assert code == 1
    err = capsys.readouterr().err
    assert "couldn't reach 192.0.2.16:2223" in err
    assert "No route to host" in err
    # The old, misleading line must not appear either.
    assert "Console: OSError" not in err


def test_apply_wires_clean_output_sockets_flag_through_to_apply_plan(stub_build, touring, capsys, monkeypatch):
    """`--clean-output-sockets LCL=6` on the CLI must
    reach `apply_plan` as the parsed `{"LCL": 6}` dict it expects --
    confirmed end to end with a fake console rather than just unit-testing
    the parser, since a wiring mistake (wrong kwarg name, wrong parse
    call) wouldn't show up in either half tested alone."""
    stub_build("touringband")
    import atoo.console as console_module
    from atoo.console import OscReply

    captured_kwargs = {}

    class FakeConsole:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def identity(self):
            return OscReply(address="/?", typetag="s", args=["WING,192.0.2.16,Fake,wing-compact,SN,3.1-0"])

        def get(self, address):
            return None  # every baseline read "unreadable" -- fine, this test only checks wiring

        def close(self):
            pass

    monkeypatch.setattr(console_module, "WingConsole", FakeConsole)

    import atoo.apply as apply_module
    real_apply_plan = apply_module.apply_plan

    def spy_apply_plan(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return real_apply_plan(*args, **kwargs)

    monkeypatch.setattr(apply_module, "apply_plan", spy_apply_plan)

    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])

    main(["apply", "--plan", str(touring / "p.json"), "--skip-verify",
          "--console", "192.0.2.16", "--clean-output-sockets", "LCL=6,A=8"])

    assert captured_kwargs.get("clean_output_sockets") == {"LCL": 6, "A": 8}


def test_apply_clean_output_sockets_defaults_to_off(stub_build, touring, monkeypatch):
    """No --clean-output-sockets flag at all -- apply_plan must receive
    an empty dict (falsy, behaves exactly like the parameter's own None
    default), never a truthy default someone forgot to gate."""
    stub_build("touringband")
    import atoo.console as console_module
    from atoo.console import OscReply

    captured_kwargs = {}

    class FakeConsole:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def identity(self):
            return OscReply(address="/?", typetag="s", args=["WING,192.0.2.16,Fake,wing-compact,SN,3.1-0"])

        def get(self, address):
            return None

        def close(self):
            pass

    monkeypatch.setattr(console_module, "WingConsole", FakeConsole)

    import atoo.apply as apply_module
    real_apply_plan = apply_module.apply_plan

    def spy_apply_plan(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return real_apply_plan(*args, **kwargs)

    monkeypatch.setattr(apply_module, "apply_plan", spy_apply_plan)

    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])

    main(["apply", "--plan", str(touring / "p.json"), "--skip-verify", "--console", "192.0.2.16"])

    assert not captured_kwargs.get("clean_output_sockets")


def test_verify_without_an_input_list_says_what_it_skipped():
    """Silence here would imply the omission check passed when it never
    ran -- and that is the most important check there is."""
    plan = json.loads(GENERATED.read_text())
    result = verify_plan(plan)
    codes = {f.code for f in result.findings}
    assert "reconcile.not-checked" in codes
    message = next(f.message for f in result.findings if f.code == "reconcile.not-checked")
    assert "every input became a channel" in message
    assert "phantom power" in message


def test_verify_with_an_input_list_runs_the_skipped_checks():
    plan = json.loads(GENERATED.read_text())
    rows = load_input_list(str(FIXTURES / "touringband.csv"))
    result = verify_plan(plan, rows)
    assert "reconcile.not-checked" not in {f.code for f in result.findings}
    # the generated plan accounts for all 19 rows
    assert not [f for f in result.findings if f.code == "reconcile.dropped-input"]


def test_generate_strategy_reports_a_provider_failure_clearly(touring, capsys, monkeypatch):
    from atoo.ai_provider import AIProviderError

    def unreachable():
        raise AIProviderError("no provider configured")

    monkeypatch.setattr("atoo.cli.provider_from_env", unreachable)
    code = main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--out", str(touring / "p.json")])
    assert code == 1
    assert "generation failed" in capsys.readouterr().err


def test_generate_strategy_end_to_end_against_a_canned_model(touring, capsys, monkeypatch):
    """The whole generate path, with the model stubbed: plan out, notes
    surfaced as warnings, verification applied to the result."""
    from atoo.ai_provider import FakeProvider

    canned = GENERATED.read_text()
    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: FakeProvider(response=canned))

    out = touring / "p.json"
    code = main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--out", str(out)])

    assert json.loads(out.read_text())["channels"][0]["name"] == "Kick"
    captured = capsys.readouterr()
    assert "Generated plan written to" in captured.out
    # the generator's own notes become build warnings
    assert "Matrix has no physical output socket" in captured.err
    # and verify says the same Matrix gap at WARNING: the Matrix is set
    # up and routed to no socket, which is a working desk, so the build
    # is not refused for it
    assert "[warning]" in captured.err and "output.no-patch" in captured.err
    assert code == 0


def test_critic_findings_are_printed_but_never_gate(touring, capsys, monkeypatch):
    """A critic is a model. Only deterministic code gates the console."""
    plan = json.loads(GENERATED.read_text())
    plan["outputs"]["Matrix"]["socket"] = {"group": "USB", "sockets": [40]}
    critique = json.dumps({"findings": [
        {"severity": "error", "kind": "intent", "where": "Kick",
         "message": "the conventions asked for a 60Hz high-pass, not 80"}]})

    class _TwoTurnProvider:
        """Generator first, critic second -- FakeProvider keys by exact
        input text, and both prompts are built here, so a scripted
        sequence is the honest stub for a two-call flow."""
        def __init__(self, replies):
            self._replies = iter(replies)

        def complete(self, *, system, user, response_schema=None, label=""):
            return next(self._replies)

    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: _TwoTurnProvider([json.dumps(plan), critique]))

    code = main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--critic", "--out", str(touring / "p.json")])

    err = capsys.readouterr().err
    assert "Critic pass -- 1 finding(s)" in err
    assert "not a gate" in err
    assert "60Hz high-pass" in err
    # the critic called it an error; the build still succeeds, because the
    # deterministic verifier is the only thing that stops anything
    assert code == 0


def test_meta_build_log_is_populated_from_a_streaming_summarized_generator(touring, monkeypatch):
    """docs/developer/build-lessons-2026-09-27.md, part C, as revised
    2026-09-28: a build whose provider streams summarized thinking (as
    `ClaudeProvider` does when it asks for `display: "summarized"`)
    writes its OWN log file, `builds/<timestamp>.json`, holding the
    notes, times and usage -- not just for the generator, but folded in
    for every role that ran -- and the plan on disk carries only a
    pointer to it (`meta.build_log_file`), never the log inline."""
    from atoo.ai_provider import FakeProvider

    canned = GENERATED.read_text()
    provider = FakeProvider(response=canned, stream_chunks=3, chunk_delay=0,
                            thinking_text="Considering sockets.\nPatching LCL first.\n",
                            summarized_thinking=True, model="claude-sonnet-5")
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)

    out = touring / "p.json"
    code = main(["build", "--console-model", "wing-compact",
                 "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--out", str(out)])
    assert code == 0  # the fixture's unpatched Matrix is a WARNING, not a refusal
    plan = json.loads(out.read_text())
    assert "build_log" not in plan["meta"]
    pointer = plan["meta"]["build_log_file"]
    assert pointer.startswith("builds/") and pointer.endswith(".json")
    log_file = touring / pointer
    assert log_file.is_file()
    logged = json.loads(log_file.read_text())
    assert logged["outcome"] == {"status": "done", "reason": None}
    entry = logged["build_log"]["generator"]
    texts = [n["text"] for n in entry["notes"]]
    assert "Considering sockets." in texts and "Patching LCL first." in texts
    assert all(isinstance(n["t"], (int, float)) for n in entry["notes"])
    assert entry["usage"]["model"] == "claude-sonnet-5"
    assert logged["console_model"] == "wing-compact"


def test_the_bundle_wins_over_out_for_where_the_build_log_lands(stub_build, touring, tmp_path):
    """`atoo/build_log.py`'s `directory_for`: a bundle (`--show`)
    wins over `--out` pointing somewhere else -- the maintainer's "into the
    bundle when there is one." A build with both must not scatter its
    log next to `--out`'s target; it belongs with the rest of the show."""
    stub_build("touringband")
    bundle_dir = tmp_path / "show"
    bundle_dir.mkdir()
    (bundle_dir / "input.csv").write_text((touring / "touringband.csv").read_text())
    elsewhere = tmp_path / "elsewhere" / "p.json"
    elsewhere.parent.mkdir()

    code = main(["build", "--console-model", "wing-compact",
                 "--show", str(bundle_dir), "--conventions", str(touring / "touringband.md"),
                 "--out", str(elsewhere)])
    assert code in (0, 2)
    plan = json.loads(elsewhere.read_text())
    pointer = plan["meta"]["build_log_file"]
    assert pointer.startswith("builds/")
    assert (bundle_dir / pointer).is_file()
    assert not (elsewhere.parent / "builds").exists()


def test_build_log_never_reaches_the_critic_or_watchlist_prompt():
    """`meta.build_log` is for a human reviewing a batch of builds later
    (docs/developer/build-lessons-2026-09-27.md) -- never fed back into a
    prompt. Both prompt-assembly functions strip it
    (`generate._plan_for_prompt`)."""
    from atoo import generate

    plan = json.loads(GENERATED.read_text())
    tell_tale = "SHOULD-NEVER-REACH-A-PROMPT"
    plan["meta"] = {"build_log": {
        "generator": {"notes": [{"t": 1.0, "text": tell_tale}], "usage": {}}}}

    critic_prompt = generate.critic_user(
        "conventions text", "csv text", plan, conventions_name="c.md", input_name="i.csv")
    watchlist_prompt = generate.watchlist_user(
        plan, "conventions text", conventions_name="c.md")

    assert tell_tale not in critic_prompt
    assert tell_tale not in watchlist_prompt
    # The rest of the plan still reaches both -- this isn't a blanket
    # redaction of `meta`.
    assert "Kick" in critic_prompt and "Kick" in watchlist_prompt


# --------------------------------------------------------------------------
# plan.json's own `meta` block
# --------------------------------------------------------------------------

def test_meta_records_generated_at_and_no_strategy(stub_build, touring):
    """`generated_at` is a real, parseable UTC timestamp -- not a
    placeholder. `strategy` is retired (review 2026-09-28, C5): it had one
    value, so a new plan does not write it."""
    stub_build("touringband")
    out = touring / "p.json"
    main(["build", "--console-model", "wing-compact", "--skip-verify",
          "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--out", str(out)])
    meta = json.loads(out.read_text())["meta"]
    assert "strategy" not in meta
    # Round-trips through datetime.fromisoformat -- the whole point of
    # using stdlib ISO 8601 rather than inventing a format.
    from datetime import datetime, timezone
    parsed = datetime.fromisoformat(meta["generated_at"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)


def test_meta_verify_at_generation_is_blocked_when_verification_fails(stub_build, touring):
    """A Matrix patched to a socket the desk does not have (see
    test_build_exits_two_when_the_plan_cannot_be_applied above) is a real
    verify_plan() error -- `meta` should say so, with counts, not just a
    bare boolean."""
    stub_refused_build(stub_build)
    out = touring / "p.json"
    code = main(["build", "--console-model", "wing-compact",
                 "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--out", str(out)])
    assert code == 2
    vag = json.loads(out.read_text())["meta"]["verify_at_generation"]
    assert vag["skipped"] is False
    assert vag["ok"] is False
    assert vag["error_count"] >= 1
    assert vag["summary"] == "BLOCKED -- do not apply"


def test_meta_verify_at_generation_is_ok_when_clean(touring, monkeypatch):
    """The generate path's canned plan, with its unpatched Matrix (a
    WARNING -- same fixup `test_critic_findings_are_printed_but_
    never_gate` above uses) patched to a socket, verifies clean -- `meta` should
    say `ok: true`, not just omit the error."""
    from atoo.ai_provider import FakeProvider

    plan = json.loads(GENERATED.read_text())
    plan["outputs"]["Matrix"]["socket"] = {"group": "USB", "sockets": [40]}
    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: FakeProvider(response=json.dumps(plan)))

    out = touring / "p.json"
    code = main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--out", str(out)])
    assert code == 0
    vag = json.loads(out.read_text())["meta"]["verify_at_generation"]
    assert vag["skipped"] is False
    assert vag["ok"] is True
    assert vag["error_count"] == 0
    assert vag["summary"] == "OK"


def test_meta_verify_at_generation_reports_skipped_distinctly(stub_build, touring):
    """`--skip-verify` means verification never ran -- `meta` must say
    that plainly, not quietly report `ok: true` as if it had checked and
    found nothing wrong (the explicit requirement: skipped and
    clean are not the same state)."""
    stub_build("touringband")
    out = touring / "p.json"
    code = main(["build", "--console-model", "wing-compact", "--skip-verify",
                 "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--out", str(out)])
    assert code == 0
    vag = json.loads(out.read_text())["meta"]["verify_at_generation"]
    assert vag["skipped"] is True
    assert vag["ok"] is None


def test_apply_ignores_a_hand_edited_meta_claiming_ok(stub_build, touring, capsys):
    """The hard guardrail: `meta.verify_at_generation` is
    informational only. Even a plan file hand-edited to CLAIM it was
    clean at generation time must still be refused by `apply` if it
    actually fails a fresh verify_plan() run -- `apply_cmd`'s gate never
    reads `meta` at all."""
    stub_refused_build(stub_build)
    out = touring / "p.json"
    main(["build", "--console-model", "wing-compact",
          "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--out", str(out)])

    plan = json.loads(out.read_text())
    assert plan["meta"]["verify_at_generation"]["ok"] is False  # sanity check
    # Tamper with it: a stale or malicious "looks fine" left in the file.
    plan["meta"]["verify_at_generation"] = {
        "skipped": False, "ok": True, "error_count": 0,
        "warning_count": 0, "summary": "OK",
    }
    out.write_text(json.dumps(plan))

    code = main(["apply", "--plan", str(out), "--console", "203.0.113.1"])
    assert code == 2
    err = capsys.readouterr().err
    assert "Refusing to apply" in err
    assert REFUSAL in err


# --------------------------------------------------------------------------
# critic and verify findings mirrored into plan.json
# --------------------------------------------------------------------------

def test_meta_critic_findings_populated_when_critic_finds_something(touring, capsys, monkeypatch):
    """Same two-turn generate+critic setup as
    test_critic_findings_are_printed_but_never_gate above, but reading the
    finding back out of `meta` rather than off stderr."""
    plan = json.loads(GENERATED.read_text())
    plan["outputs"]["Matrix"]["socket"] = {"group": "USB", "sockets": [40]}
    critique = json.dumps({"findings": [
        {"severity": "error", "kind": "intent", "where": "Kick",
         "message": "the conventions asked for a 60Hz high-pass, not 80"}]})

    class _TwoTurnProvider:
        def __init__(self, replies):
            self._replies = iter(replies)

        def complete(self, *, system, user, response_schema=None, label=""):
            return next(self._replies)

    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: _TwoTurnProvider([json.dumps(plan), critique]))

    out = touring / "p.json"
    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--critic", "--out", str(out)])

    meta = json.loads(out.read_text())["meta"]
    # The canonical diagnostic wire shape: the critic's
    # `kind` is now a stable `code` as well, and `source` records that a
    # model -- not deterministic code -- said this.
    # The critic answered "error"; its worst is WARNING (2026-10-02):
    # whether the desk can work is verify's call, not a model's.
    assert meta["critic_findings"] == [
        {"severity": "warning", "code": "critic.intent", "where": "Kick",
         "category": "intent", "source": "critic",
         "message": "the conventions asked for a 60Hz high-pass, not 80"},
    ]


def test_meta_critic_findings_empty_list_when_critic_ran_clean(touring, monkeypatch):
    """The critic ran and found nothing -- `[]`, not `None`. This is the
    distinction `report.py`'s own docstring says it cannot make ('ran and found nothing' vs 'never ran' must not collapse into one
    stderr-only shrug)."""
    plan = json.loads(GENERATED.read_text())
    plan["outputs"]["Matrix"]["socket"] = {"group": "USB", "sockets": [40]}
    clean_critique = json.dumps({"findings": []})

    class _TwoTurnProvider:
        def __init__(self, replies):
            self._replies = iter(replies)

        def complete(self, *, system, user, response_schema=None, label=""):
            return next(self._replies)

    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: _TwoTurnProvider([json.dumps(plan), clean_critique]))

    out = touring / "p.json"
    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--critic", "--out", str(out)])

    meta = json.loads(out.read_text())["meta"]
    assert meta["critic_findings"] == []


def test_meta_critic_findings_null_when_critic_not_requested(stub_build, touring):
    """`--critic` was never passed (and this is the `compile` strategy, so
    the critic pass could not even apply) -- `None`, not `[]`, so a reader
    of plan.json alone can tell 'didn't run' from 'ran clean'."""
    stub_build("touringband")
    out = touring / "p.json"
    main(["build", "--console-model", "wing-compact",
          "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--out", str(out)])
    meta = json.loads(out.read_text())["meta"]
    assert meta["critic_findings"] is None


def test_meta_verify_findings_mirrors_verdicts_errors_and_warnings(stub_build, touring, monkeypatch):
    """`meta.verify_findings` is `verdict.errors`/`verdict.warnings`,
    plain-dict-ified -- exercised with both severities present so the
    shape (not just the error half) is proven."""
    stub_build("touringband")
    from atoo.verify_plan import VerifyResult

    def fake_verify_plan(plan, rows=None, **kwargs):
        result = VerifyResult()
        result.add("error", "output.socket-out-of-range", "outputs[Matrix]",
                    "LCL output 99 does not exist")
        result.add("warning", "group.empty", "plan.dcas[FX]",
                    "FX is declared but no channel joins it")
        result.add("info", "inferred.bus-width", "busses[MON1]",
                   "width set to mono")
        return result

    monkeypatch.setattr("atoo.cli.verify_plan", fake_verify_plan)
    out = touring / "p.json"
    code = main(["build", "--console-model", "wing-compact",
                 "--input", str(touring / "touringband.csv"),
                 "--conventions", str(touring / "touringband.md"),
                 "--out", str(out)])
    assert code == 2
    vf = json.loads(out.read_text())["meta"]["verify_findings"]
    assert vf == {
        "errors": [{"severity": "error", "code": "output.socket-out-of-range",
                    "where": "outputs[Matrix]", "source": "verify",
                    "message": "LCL output 99 does not exist"}],
        "warnings": [{"severity": "warning", "code": "group.empty",
                      "where": "plan.dcas[FX]", "source": "verify",
                      "message": "FX is declared but no channel joins it"}],
        # 2026-09-25: notes are mirrored too -- the Setup UI's dock reads them.
        "info": [{"severity": "info", "code": "inferred.bus-width",
                  "where": "busses[MON1]", "source": "verify",
                  "message": "width set to mono"}],
    }


def test_meta_verify_findings_null_when_skip_verify(stub_build, touring):
    stub_build("touringband")
    out = touring / "p.json"
    main(["build", "--console-model", "wing-compact", "--skip-verify",
          "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--out", str(out)])
    meta = json.loads(out.read_text())["meta"]
    assert meta["verify_findings"] is None


def test_meta_no_longer_carries_expectations_findings(stub_build, touring):
    """An earlier change retired expectations, so a freshly built plan must not write
    the key at all -- neither a value nor a null placeholder for a pass
    that no longer exists."""
    stub_build("touringband")
    out = touring / "p.json"
    main(["build", "--console-model", "wing-compact",
          "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--out", str(out)])
    meta = json.loads(out.read_text())["meta"]
    assert "expectations_findings" not in meta
    assert "verify_findings" in meta


def test_a_plan_built_before_expectations_was_retired_still_loads(stub_build, touring):
    """The backwards-compatibility rule: `meta` is an open object, so a
    plan.json written last week -- carrying `expectations_findings` -- must
    still verify and apply rather than being refused for an unknown key."""
    stub_build("touringband")
    out = touring / "p.json"
    main(["build", "--console-model", "wing-compact", "--skip-verify",
          "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--out", str(out)])
    plan = json.loads(out.read_text())
    plan["meta"]["expectations_findings"] = {
        "errors": [{"severity": "error", "code": "expect.channel-count",
                    "where": "old.toml", "message": "plan should have 999 channels"}],
        "warnings": [],
    }
    out.write_text(json.dumps(plan))
    # `verify` is the cheapest reader of a whole plan; a schema that had
    # grown strict about `meta` would fail here.
    assert main(["verify", "--plan", str(out),
                 "--input", str(touring / "touringband.csv")]) in (0, 2)


def test_apply_ignores_stale_meta_findings_claiming_clean(stub_build, touring, capsys):
    """The same hard guardrail as
    test_apply_ignores_a_hand_edited_meta_claiming_ok above, extended to
    the new an earlier change fields: a plan hand-edited so `meta.verify_findings`
    claims a spotless run must still be refused by `apply` on a fresh
    `verify_plan()` call, because `apply_cmd`'s gate never reads `meta` at
    all. The retired `expectations_findings` is set too, because an old
    plan on disk still carries it and it must stay just as powerless."""
    stub_refused_build(stub_build)
    out = touring / "p.json"
    main(["build", "--console-model", "wing-compact",
          "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--out", str(out)])

    plan = json.loads(out.read_text())
    assert plan["meta"]["verify_findings"]["errors"]  # sanity check: really failing
    # Tamper with it: make the embedded findings lie about a clean build.
    plan["meta"]["verify_findings"] = {"errors": [], "warnings": []}
    plan["meta"]["expectations_findings"] = {"errors": [], "warnings": []}
    plan["meta"]["critic_findings"] = []
    out.write_text(json.dumps(plan))

    code = main(["apply", "--plan", str(out), "--console", "203.0.113.1"])
    assert code == 2
    err = capsys.readouterr().err
    assert "Refusing to apply" in err
    assert REFUSAL in err


def _fake_console_reporting(model: str):
    """A console that answers `/?` as the given WING model and reads
    nothing -- enough to exercise the identity handshake."""
    from atoo.console import OscReply

    class FakeConsole:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def identity(self):
            return OscReply(address="/?", typetag="s",
                            args=[f"WING,192.0.2.16,Fake,{model},SN,3.1-0"])

        def get(self, address):
            return None

        def close(self):
            pass

    return FakeConsole


def test_apply_refuses_a_plan_whose_sockets_the_desk_does_not_have(
        stub_build, touring, capsys, monkeypatch):
    """A plan for a Compact can patch local inputs 9..24, which a
    full-size WING does not have -- so applying it to that desk would write
    real patches to jacks that aren't there. Verification runs before the
    console is contacted, so this can only be caught at the handshake, and
    it must be caught there.

    Since 2026-09-24 a different model alone is not a refusal (a
    judgement call is not an impossible patch -- `test_apply_cross_model`
    covers the rest). A socket the desk lacks still is, so the built plan
    is given one: its first channel moved to LCL 20."""
    stub_build("touringband")
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole", _fake_console_reporting("wing-full"))

    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])
    capsys.readouterr()
    plan = json.loads((touring / "p.json").read_text())
    plan["channels"][0]["patch"] = {"group": "LCL", "sockets": [20]}
    plan["channels"][0].setdefault("source", {})["stereo"] = False
    (touring / "p.json").write_text(json.dumps(plan))

    # --skip-verify deliberately does NOT suppress this: it is a statement
    # about the plan's findings, not about which desk is on the other end.
    code = main(["apply", "--plan", str(touring / "p.json"), "--console", "192.0.2.16",
                 "--skip-verify"])

    assert code == 2
    err = capsys.readouterr().err
    assert "WING Compact" in err and "full-size console" in err
    assert "LCL 20" in err
    assert "--console-model wing-full" in err


def test_apply_proceeds_when_the_console_is_the_model_the_plan_was_built_for(
        stub_build, touring, capsys, monkeypatch):
    """The other half -- the guard must not fire on the happy path."""
    stub_build("touringband")
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole", _fake_console_reporting("wing-compact"))

    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])
    capsys.readouterr()

    code = main(["apply", "--plan", str(touring / "p.json"), "--console", "192.0.2.16",
                 "--skip-verify"])

    err = capsys.readouterr().err
    assert "This plan is for a" not in err
    assert "WING model" not in err
    assert code != 2


# --- exit codes: the scripting contract -----------------------
#
# `examples/README.md` §3 and `docs/user/quickstart.md` both state it:
# `0` clean, `1` bad usage or an unreadable file, `2` the command ran and
# found problems. The three assertions below are that contract for
# `apply`, written down where a future change to any of the three return
# statements will trip over them.

def _mismatching_apply_result():
    """An `ApplyResult` that landed one address and failed another --
    the only outcome `apply_cmd` treats as "ran and found problems"."""
    from atoo.apply import ApplyResult, WriteRecord

    def record(address, intended, readback, status):
        return WriteRecord(
            address=address, description=address, value_type="s", method="node", ack="OK",
            prior_value="", intended_value=intended, readback_value=readback,
            status=status, timestamp="2026-09-22T00:00:00Z",
        )

    return ApplyResult(dry_run=False, writes=[
        record("/ch/1/name", "Kick", "Kick", "match"),
        record("/ch/10/tags", "#D6,#M1", "", "mismatch"),
    ])


def test_apply_exits_2_when_a_value_did_not_land(stub_build, touring, capsys, monkeypatch):
    """A readback mismatch is the headline finding of this
    whole tool, and it used to exit 1 -- the same code as "I could not
    read the plan file" and "the desk never answered". A script could not
    tell "two parameters did not land on a desk that is otherwise fine"
    from "I could not reach the desk", and those call for different
    responses at a venue."""
    stub_build("touringband")
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole", _fake_console_reporting("wing-compact"))

    import atoo.apply as apply_module
    monkeypatch.setattr(apply_module, "apply_plan",
                        lambda *a, **kw: _mismatching_apply_result())

    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])
    capsys.readouterr()

    code = main(["apply", "--plan", str(touring / "p.json"), "--console", "192.0.2.16",
                 "--skip-verify", "--confirm", "--journal", str(touring / "j.json")])

    assert code == 2
    err = capsys.readouterr().err
    # Still named by address on stderr (FR-3.2) -- the exit code changed,
    # what it tells you did not.
    assert "1 parameter(s) did NOT land" in err
    assert "/ch/10/tags" in err


def test_apply_exits_1_when_the_console_never_answered(stub_build, touring, capsys, monkeypatch):
    """The other side of the distinction, and the reason the mismatch
    code had to move rather than this one: a desk that does not answer is
    a transport problem, not a finding about the plan. It stays 1."""
    stub_build("touringband")
    import atoo.console as console_module
    from atoo.console import OscReply

    class SilentConsole:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def identity(self):
            return None

        def close(self):
            pass

    monkeypatch.setattr(console_module, "WingConsole", SilentConsole)

    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])
    capsys.readouterr()

    code = main(["apply", "--plan", str(touring / "p.json"), "--console", "192.0.2.16",
                 "--skip-verify"])

    assert code == 1
    assert "no reply from 192.0.2.16:2223" in capsys.readouterr().err


def test_apply_exits_0_when_every_value_landed(stub_build, touring, capsys, monkeypatch):
    """`0` is the only code that means every value landed -- the claim
    `docs/user/applying.md`'s exit-code table makes."""
    stub_build("touringband")
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole", _fake_console_reporting("wing-compact"))

    from atoo.apply import ApplyResult, WriteRecord
    landed = ApplyResult(dry_run=False, writes=[WriteRecord(
        address="/ch/1/name", description="/ch/1/name", value_type="s", method="node", ack="OK",
        prior_value="", intended_value="Kick", readback_value="Kick",
        status="match", timestamp="2026-09-22T00:00:00Z",
    )])
    import atoo.apply as apply_module
    monkeypatch.setattr(apply_module, "apply_plan", lambda *a, **kw: landed)

    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])
    capsys.readouterr()

    code = main(["apply", "--plan", str(touring / "p.json"), "--console", "192.0.2.16",
                 "--skip-verify", "--confirm", "--journal", str(touring / "j.json")])

    assert code == 0


# --- expansion bays: apply refuses a patch into an empty slot -
#
# Measured on the maintainer's WING Compact, 2026-09-21
# (`archive/examples/console-runs/2026-09-21/A8_patch_test.txt`): with
# `/$syscfg/opt_mod` reading `NONE`, setting `/ch/40/in/conn/grp` to `MOD`
# was ACCEPTED and read back `MOD`. No error, no clamp. So every check
# Atoo already has passes, the journal says `match`, and the channel
# is silent -- which makes refusing it this tool's job or nobody's.

def _fake_console_with_bays(card="WLIVE", module="NONE", model="wing-compact"):
    """A console that answers `/?`, `/cards/$type` and `/$syscfg/opt_mod`.
    `None` for either bay means that address does not answer at all."""
    from atoo.console import OscReply

    answers = {}
    if card is not None:
        answers["/cards/$type"] = card
    if module is not None:
        answers["/$syscfg/opt_mod"] = module

    class FakeConsole:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def identity(self):
            return OscReply(address="/?", typetag="s",
                            args=[f"WING,192.0.2.16,Fake,{model},SN,3.1-0"])

        def get(self, address):
            if address in answers:
                return OscReply(address=address, typetag="s", args=[answers[address]])
            return None

        def close(self):
            pass

    return FakeConsole


def _build_a_plan_patched_from(touring, group, stub_build):
    """Build the touringband plan, then move its first channel onto
    `group`. Cheaper and more honest than a second fixture plan: every
    other field is one a real build produced."""
    stub_build("touringband")
    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])
    path = touring / "p.json"
    plan = json.loads(path.read_text())
    plan["channels"][0]["patch"] = {"group": group, "sockets": [1], "stated": True}
    plan["channels"][0]["source"]["stereo"] = False
    path.write_text(json.dumps(plan))
    return path


def test_apply_refuses_a_plan_patched_from_an_empty_module_bay(
        stub_build, touring, capsys, monkeypatch):
    """An earlier change, the headline case. The desk says `NONE`, the plan wants
    `MOD 1`, and nothing downstream would ever report it."""
    plan_path = _build_a_plan_patched_from(touring, "MOD", stub_build)
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole",
                        _fake_console_with_bays(card="WLIVE", module="NONE"))
    capsys.readouterr()

    # --skip-verify deliberately does NOT suppress this, for the reason:
    # that flag is a judgement about the plan's findings, and this is a
    # fact about the hardware on the other end of the cable.
    code = main(["apply", "--plan", str(plan_path), "--console", "192.0.2.16",
                 "--skip-verify", "--confirm"])

    assert code == 2
    err = capsys.readouterr().err
    assert "NOTHING in the MOD bay" in err
    assert "AoIP module" in err          # says what MOD is, not just its token
    assert "channel 'Kick' from MOD 1" in err   # and which channel, by name


def test_apply_proceeds_when_the_bay_this_plan_uses_is_occupied(
        stub_build, touring, capsys, monkeypatch):
    """The other half. A desk WITH the card is the normal case for a plan
    that patches from one, and refusing it would be the worse bug."""
    plan_path = _build_a_plan_patched_from(touring, "CRD", stub_build)
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole",
                        _fake_console_with_bays(card="WLIVE", module="NONE"))
    capsys.readouterr()

    code = main(["apply", "--plan", str(plan_path), "--console", "192.0.2.16", "--skip-verify"])

    err = capsys.readouterr().err
    assert "NOTHING in the" not in err
    assert code == 0


def test_an_empty_bay_the_plan_does_not_use_is_not_an_apply_failure(
        stub_build, touring, capsys, monkeypatch):
    """The maintainer's own Compact reports `opt_mod = NONE` and has a WLIVE card
    in it. Every plan that never mentions MOD must apply to that desk
    exactly as before -- the check is about what the PLAN needs, not about
    the desk having empty slots."""
    stub_build("touringband")
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole",
                        _fake_console_with_bays(card="WLIVE", module="NONE"))
    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])
    capsys.readouterr()

    code = main(["apply", "--plan", str(touring / "p.json"), "--console", "192.0.2.16",
                 "--skip-verify"])

    assert "NOTHING in the" not in capsys.readouterr().err
    assert code == 0


def test_a_bay_the_desk_did_not_answer_for_does_not_refuse_the_plan(
        stub_build, touring, capsys, monkeypatch):
    """Silence is not `NONE`. An older firmware, a dropped datagram or an
    emulator that does not implement these leaves must not turn into a
    refusal -- only the desk saying the slot is empty, in as many letters,
    may do that."""
    plan_path = _build_a_plan_patched_from(touring, "MOD", stub_build)
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole",
                        _fake_console_with_bays(card=None, module=None))
    capsys.readouterr()

    code = main(["apply", "--plan", str(plan_path), "--console", "192.0.2.16", "--skip-verify"])

    assert "NOTHING in the" not in capsys.readouterr().err
    assert code == 0


def test_a_card_name_we_do_not_recognise_does_not_refuse_the_plan(
        stub_build, touring, capsys, monkeypatch):
    """`/cards/$type`'s enum is what the 2026-09-08 walk found, and
    firmware ships new cards. A name this project has never heard of is a
    card that is *fitted*, so it must read as occupied, not as empty."""
    plan_path = _build_a_plan_patched_from(touring, "CRD", stub_build)
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole",
                        _fake_console_with_bays(card="WSOMETHINGNEW", module="NONE"))
    capsys.readouterr()

    code = main(["apply", "--plan", str(plan_path), "--console", "192.0.2.16", "--skip-verify"])

    assert "NOTHING in the" not in capsys.readouterr().err
    assert code == 0


def test_the_empty_bay_refusal_happens_before_anything_is_written(
        stub_build, touring, monkeypatch):
    """The whole value of a pre-flight is that it is pre-. `apply_plan`
    must never be reached -- a half-written show on a desk whose bay is
    empty is worse than a refused one."""
    plan_path = _build_a_plan_patched_from(touring, "MOD", stub_build)
    import atoo.console as console_module
    monkeypatch.setattr(console_module, "WingConsole",
                        _fake_console_with_bays(card="WLIVE", module="NONE"))

    reached = []
    import atoo.apply as apply_module
    monkeypatch.setattr(apply_module, "apply_plan",
                        lambda *a, **kw: reached.append(True))

    main(["apply", "--plan", str(plan_path), "--console", "192.0.2.16",
          "--skip-verify", "--confirm"])

    assert reached == [], "apply_plan was called after the bay check should have stopped the run"


def test_a_plan_that_uses_no_bay_never_asks_the_desk_about_one(
        stub_build, touring, capsys, monkeypatch):
    """These are ordinary GETs, and a firmware that does not implement the
    leaf costs a full timeout-and-retry apiece. Most plans touch no bay,
    and they must not pay for a question they never asked."""
    stub_build("touringband")
    import atoo.console as console_module
    from atoo.console import OscReply

    asked = []

    class CountingConsole:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def identity(self):
            return OscReply(address="/?", typetag="s",
                            args=["WING,192.0.2.16,Fake,wing-compact,SN,3.1-0"])

        def get(self, address):
            asked.append(address)
            return None

        def close(self):
            pass

    monkeypatch.setattr(console_module, "WingConsole", CountingConsole)
    main(["build", "--console-model", "wing-compact", "--input", str(touring / "touringband.csv"),
          "--conventions", str(touring / "touringband.md"),
          "--skip-verify", "--out", str(touring / "p.json")])
    capsys.readouterr()

    main(["apply", "--plan", str(touring / "p.json"), "--console", "192.0.2.16", "--skip-verify"])

    assert "/cards/$type" not in asked
    assert "/$syscfg/opt_mod" not in asked
