"""The api (OpenAI-compatible) provider path, an earlier change.

Every host here is a FAKE one: a local HTTP server that answers like the
host named in each test's docstring (accepts `response_format`, refuses it
with a 400, ignores it, says `null` for a field that may be left out, ...).
Nothing calls a paid model; what these prove is Atoo's side of the exchange --
what it sends, what it does when a host refuses a field, and what it makes of
the reply. They cannot say what a real host's decoder does with the schema.
"""

from __future__ import annotations

import copy
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from atoo import cli, patch, plan_schema, strict_schema
from atoo.ai_provider import AIProviderError, ApiKeyProvider, ClaudeProvider, FakeProvider, provider_from_env
from atoo.schema_check import unsupported_keywords, validate
from test_amend import horn
from test_patch import _bundle, _patch, _reply, desk, horns_change_set  # noqa: F401


# -- a fake OpenAI-compatible host ---------------------------------------------


class FakeHost:
    """Answers each POST from `script`: a list of `(status, body)` taken in
    order (the last repeats). A body that is a dict is sent as a chat
    completion whose message content is its `content`."""

    def __init__(self, script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        host = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                host.requests.append(body)
                host.headers.append({k.lower(): v for k, v in self.headers.items()})
                status, reply = host.script[min(len(host.requests), len(host.script)) - 1]
                if isinstance(reply, str):
                    data = reply.encode()
                else:
                    data = json.dumps({
                        "choices": [{"message": {"content": reply["content"]}}],
                        "usage": reply.get("usage", {"prompt_tokens": 100, "completion_tokens": 20})}).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def provider(self, **kw) -> ApiKeyProvider:
        kw.setdefault("stream", False)
        return ApiKeyProvider(api_key="k", model="some-model", base_url=self.url,
                              show_progress=kw.pop("show_progress", True),
                              price_in=1.0, price_out=2.0, **kw)


@pytest.fixture
def host():
    made: list[FakeHost] = []

    def make(*script):
        made.append(FakeHost(script))
        return made[-1]

    yield make
    for h in made:
        h.close()


def ok(change_set) -> tuple[int, dict]:
    return 200, {"content": change_set if isinstance(change_set, str) else json.dumps(change_set)}


def ok_with_usage(usage: dict, change_set=None) -> tuple[int, dict]:
    status, body = ok(patch.empty_change_set("x") if change_set is None else change_set)
    return status, {**body, "usage": usage}


def bad(message: str) -> tuple[int, str]:
    return 400, json.dumps({"error": {"message": message}})


def _compile(provider, infos=None):
    return patch.compile_change(
        "trumpet on A 21", {"channels": [], "dcas": {"Horns": {"index": 1}}, "busses": {},
                            "mute_groups": {}, "outputs": {}},
        provider=provider, console_model="wing-compact", infos=infos if infos is not None else [])


def _valid_change() -> dict:
    change = patch.empty_change_set("Add a trumpet")
    change["add"]["channels"] = [horn(1, "Trumpet", 21)]
    change["add"]["channels"][0].update(dca=[], mute_group=[], bus_sends=[])
    return change


# -- the derived schema ----------------------------------------------------------


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            yield node
        for child in node.values():
            yield from _objects(child)
    elif isinstance(node, list):
        for child in node:
            yield from _objects(child)


@pytest.mark.parametrize("schema", [patch.CHANGE_SET_SCHEMA, plan_schema.REPLY_SCHEMA],
                         ids=["change set", "plan reply"])
def test_the_wire_schema_is_in_strict_mode_form(schema):
    wire = strict_schema.strict_wire(schema)
    assert wire is not None
    for obj in _objects(wire):
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])
    text = json.dumps(wire)
    for refused in ("minimum", "maxLength", "minItems", "oneOf"):
        assert refused not in text
    assert not unsupported_keywords(wire)


def _no_nulls(node):
    """A field a reply may leave out and one it says `null` for mean the same
    ("unstated"); a strict-mode reply has to say null for every one."""
    if isinstance(node, dict):
        return {k: _no_nulls(v) for k, v in node.items() if v is not None}
    if isinstance(node, list):
        return [_no_nulls(v) for v in node]
    return node


def _more_valid_changes() -> list[dict]:
    full = _valid_change()
    full["add"]["busses"] = {"Brass Mix": copy.deepcopy(plan_schema.EXAMPLE_BUS)}
    full["add"]["outputs"] = {"Matrix 1": copy.deepcopy(plan_schema.EXAMPLE_OUTPUT)}
    full["add"]["dcas"] = {"Brass": {}}
    full["add"]["mute_groups"] = {"Brass": {"anything": ["goes", 1]}}
    full["drop"]["channels"] = ["Old"]
    full["modify"] = [{"object": "channel", "name": "Kick", "change": "HPF 100",
                       "fields": {"processing.hpf_hz": 100, "dca": ["A", "B"],
                                  "patch": {"group": "A", "sockets": [30], "stated": True},
                                  "source.phantom": True}}]
    full["notes"] = ["a note"]
    return [patch.empty_change_set("Nothing"), _valid_change(), full]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_the_wire_schema_accepts_what_the_original_accepts(index):
    """Every valid reply, put on the wire, passes the derived schema; and
    read back it is the very same reply. That is what 'the same replies'
    means for a schema whose open maps are sent as arrays."""
    change = _more_valid_changes()[index]
    assert validate(change, patch.CHANGE_SET_SCHEMA) == []
    wire = strict_schema.strict_wire(patch.CHANGE_SET_SCHEMA)
    sent = strict_schema.to_wire(change, patch.CHANGE_SET_SCHEMA)
    assert validate(sent, wire) == []
    assert _no_nulls(strict_schema.from_wire(sent, patch.CHANGE_SET_SCHEMA)) == _no_nulls(change)


def test_the_wire_schema_refuses_what_the_original_refuses():
    wire = strict_schema.strict_wire(patch.CHANGE_SET_SCHEMA)
    sent = strict_schema.to_wire(_more_valid_changes()[2], patch.CHANGE_SET_SCHEMA)
    broken = copy.deepcopy(sent)
    del broken["drop"]["channels"]
    assert validate(broken, wire)
    broken = copy.deepcopy(sent)
    broken["modify"][0]["object"] = "speaker"
    assert validate(broken, wire)
    broken = copy.deepcopy(sent)
    broken["add"]["busses"] = {"a": {}}     # a map must arrive as an array
    assert validate(broken, wire)


def test_a_null_on_a_field_a_reply_may_leave_out_is_dropped_and_listed():
    sent = strict_schema.to_wire(_valid_change(), patch.CHANGE_SET_SCHEMA)
    assert sent["add"]["channels"][0]["source"]["pair_phantom"] is None   # the wire says null
    dropped: list[str] = []
    plain = strict_schema.from_wire(sent, patch.CHANGE_SET_SCHEMA, dropped)
    assert "pair_phantom" not in plain["add"]["channels"][0]["source"]
    assert "add.channels[0].source.pair_phantom" in dropped
    # a field the format lets be null stays null
    assert plain["add"]["channels"][0]["processing"]["preset"] is None


# -- (a) a host that takes response_format ---------------------------------------


def test_the_schema_goes_as_strict_response_format_and_the_reply_comes_back_plain(host, capsys):
    change = _valid_change()
    change["add"]["busses"] = {"Brass Mix": {"destination": {"type": "main"}}}
    h = host(ok(strict_schema.to_wire(change, patch.CHANGE_SET_SCHEMA)))
    got = _compile(h.provider())
    [sent] = h.requests
    fmt = sent["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == strict_schema.strict_wire(patch.CHANGE_SET_SCHEMA)
    assert strict_schema.WIRE_NOTE.strip().splitlines()[0] in sent["messages"][0]["content"]
    assert got["add"]["busses"]["Brass Mix"]["destination"]["type"] == "main"
    assert got["add"]["channels"][0]["name"] == "Trumpet"


def test_a_call_with_no_schema_sends_no_response_format(host):
    h = host(ok("hello"))
    assert h.provider().complete(system="s", user="u") == "hello"
    assert "response_format" not in h.requests[0]
    assert h.requests[0]["messages"][0]["content"] == "s"


def test_structured_off_sends_none(host):
    h = host(ok(patch.empty_change_set("x")))
    _compile(h.provider(structured=False))
    assert "response_format" not in h.requests[0]


# -- (b) a host that refuses it ---------------------------------------------------


@pytest.mark.parametrize("message", [
    "Unknown field: response_format",
    "the json_schema is not supported by this model",
    "Invalid schema: too complex to compile",
])
def test_a_400_about_the_schema_is_asked_again_without_it_and_said(host, capsys, message):
    h = host(bad(message), ok(patch.empty_change_set("x")))
    got = _compile(h.provider())
    assert got["name"] == "x"
    first, second = h.requests
    assert "response_format" in first and "response_format" not in second
    assert strict_schema.WIRE_NOTE not in second["messages"][0]["content"]
    err = capsys.readouterr().err
    assert "INFO the host at" in err and "refused `response_format`" in err


def test_another_400_is_not_retried(host):
    h = host(bad("model not found"))
    with pytest.raises(AIProviderError, match="HTTP 400"):
        _compile(h.provider())
    assert len(h.requests) == 1


def test_a_500_is_not_retried(host):
    h = host((500, "boom"))
    with pytest.raises(AIProviderError, match="HTTP 500"):
        _compile(h.provider())
    assert len(h.requests) == 1


def test_a_reasoning_model_that_refuses_temperature_is_asked_again(host, capsys):
    h = host(bad("temperature is not supported for this model"), ok(patch.empty_change_set("x")))
    _compile(h.provider())
    assert "temperature" in h.requests[0] and "temperature" not in h.requests[1]
    assert "refused `temperature`" in capsys.readouterr().err


def test_reasoning_effort_and_the_ceiling_are_sent_when_set_and_dropped_when_refused(host, capsys):
    h = host(bad("unknown parameter: reasoning_effort"),
             bad("unknown parameter: max_completion_tokens"), ok(patch.empty_change_set("x")))
    _compile(h.provider(reasoning_effort="low", max_tokens=9000))
    first, second, third = h.requests
    assert first["reasoning_effort"] == "low" and first["max_completion_tokens"] == 9000
    assert "reasoning_effort" not in second and "max_completion_tokens" in second
    assert "max_completion_tokens" not in third
    err = capsys.readouterr().err
    assert "refused `reasoning_effort`" in err and "refused `max_completion_tokens`" in err


def test_nothing_reasoning_is_sent_unless_asked(host):
    h = host(ok(patch.empty_change_set("x")))
    _compile(h.provider())
    assert not {"reasoning_effort", "max_completion_tokens"} & set(h.requests[0])


def test_the_environment_reaches_the_provider():
    p = provider_from_env({"ATOO_AI_PROVIDER": "api", "ATOO_AI_API_KEY": "k",
                           "ATOO_AI_STRUCTURED": "0", "ATOO_AI_REASONING_EFFORT": " low ",
                           "ATOO_AI_MAX_TOKENS": "4000"})
    assert (p.structured, p.reasoning_effort, p.max_tokens) == (False, "low", 4000)
    q = provider_from_env({"ATOO_AI_PROVIDER": "api", "ATOO_AI_API_KEY": "k"})
    assert (q.structured, q.reasoning_effort, q.max_tokens) == (True, None, None)
    with pytest.raises(AIProviderError, match="ATOO_AI_MAX_TOKENS"):
        provider_from_env({"ATOO_AI_PROVIDER": "api", "ATOO_AI_API_KEY": "k",
                           "ATOO_AI_MAX_TOKENS": "lots"})


# -- (c) null for an optional field ------------------------------------------------


def test_a_null_phantom_is_read_as_off_and_said(host):
    """The Stage 1 failure: `source.phantom: expected boolean, got NoneType`,
    a refused paid reply. A host that ignores the schema can still say it."""
    change = _valid_change()
    change["add"]["channels"][0]["source"]["phantom"] = None
    change["add"]["channels"][0]["source"]["pair_phantom"] = None
    change["add"]["channels"][0]["patch"]["stated"] = None
    infos: list[str] = []
    got = _compile(host(ok(change)).provider(), infos)
    source = got["add"]["channels"][0]["source"]
    assert source["phantom"] is False and "pair_phantom" not in source
    assert got["add"]["channels"][0]["patch"]["stated"] is False
    text = "\n".join(infos)
    assert "add.channels[].source.pair_phantom" in text and "read as not stated" in text
    assert "add.channels[].source.phantom was null on 1 entry; read as false -- 48V is not switched on" in text
    assert "add.channels[].patch.stated was null" in text


def test_a_null_where_a_setting_is_needed_is_still_the_replys_fault():
    change = _valid_change()
    change["add"]["channels"][0]["source"]["stereo"] = None
    with pytest.raises(patch.ChangeError, match="source.stereo: expected boolean, got NoneType"):
        patch.validate_change_set(change)


# -- (d) invalid, then valid on the repair --------------------------------------------


def _invalid_change() -> dict:
    change = _valid_change()
    del change["add"]["channels"][0]["source"]["stereo"]
    return change


def test_an_invalid_reply_is_sent_back_once_with_the_validators_message(host):
    h = host(ok(_invalid_change()), ok(_valid_change()))
    provider = h.provider()
    infos: list[str] = []
    got = _compile(provider, infos)
    assert got["add"]["channels"][0]["name"] == "Trumpet"
    first, second = h.requests
    assert len(h.requests) == 2
    repair = second["messages"][1]["content"]
    assert repair.startswith(first["messages"][1]["content"])
    assert "Your previous reply was not accepted" in repair
    assert "missing required field 'stereo'" in repair
    # both calls are counted: a usage line each, a build-log entry each
    assert set(provider.build_log) == {"change", "change-repair"}
    assert any("sent back once" in i and "change-repair" in i for i in infos)


def test_the_repair_is_bounded_to_one(host):
    h = host(ok(_invalid_change()))
    with pytest.raises(patch.ChangeError, match="the first reply failed too"):
        _compile(h.provider())
    assert len(h.requests) == 2


def test_both_calls_print_a_priced_usage_line(host, capsys):
    h = host(ok(_invalid_change()), ok(_valid_change()))
    _compile(h.provider())
    err = capsys.readouterr().err
    lines = re.findall(r"some-model \((change[a-z-]*)\): 100 in, 20 out.* -- \$", err)
    assert lines == ["change", "change-repair"]


def test_a_provider_that_does_not_repair_fails_after_one_call():
    fake = FakeProvider(response=json.dumps(_invalid_change()))
    with pytest.raises(patch.ChangeError):
        _compile(fake)
    assert len(fake.calls) == 1
    assert not getattr(ClaudeProvider, "repairs_replies", False)


# -- (e) a host that ignores the schema ----------------------------------------------------


def test_a_reply_in_the_plain_form_still_works_when_the_host_ignored_the_schema(host):
    change = _more_valid_changes()[2]
    got = _compile(host(ok(change)).provider())
    assert set(got["add"]["busses"]) == {"Brass Mix"} and set(got["add"]["outputs"]) == {"Matrix 1"}
    assert got["add"]["mute_groups"] == change["add"]["mute_groups"]
    assert got["modify"][0]["fields"] == change["modify"][0]["fields"]


def test_text_that_is_not_json_goes_to_the_callers_own_error(host):
    with pytest.raises(patch.ChangeError, match="usable change set"):
        _compile(host(ok("I could not do that.")).provider())


# -- the desk refuses what the model proposed (a Compact desk fake) ------------------------------


class _Sequence(FakeProvider):
    repairs_replies = True

    def __init__(self, *replies):
        super().__init__(response="")
        self.replies = list(replies)

    def complete(self, **kw):
        self.calls.append((kw["system"], kw["user"]))
        self.labels.append(kw.get("label", ""))
        return self.replies[min(len(self.calls), len(self.replies)) - 1]


def test_a_refusal_by_the_desk_is_sent_back_once(tmp_path, desk, monkeypatch, capsys):
    bad_set = horns_change_set()
    bad_set["add"]["channels"][0]["bus_sends"] = [{"bus": "MON9", "mode": "pre", "level_db": 0.0}]
    seq = _Sequence(_reply(bad_set), _reply(horns_change_set()))
    monkeypatch.setattr(cli, "provider_from_env", lambda: seq)
    show = _bundle(tmp_path)
    assert _patch(show, confirm=False) == 0
    out = capsys.readouterr().out
    assert len(seq.calls) == 2 and seq.labels == ["change", "change-repair"]
    assert "bus 'MON9'" in seq.calls[1][1] and "neither on the desk nor added" in seq.calls[1][1]
    assert "sent back once" in out
    assert out.count("REFUSED") == 1          # only the INFO quoting the first reply's refusal


def test_a_refusal_the_second_reply_repeats_still_refuses_after_exactly_two_calls(
        tmp_path, desk, monkeypatch, capsys):
    bad_set = horns_change_set()
    bad_set["add"]["channels"][0]["bus_sends"] = [{"bus": "MON9", "mode": "pre", "level_db": 0.0}]
    seq = _Sequence(_reply(bad_set))
    monkeypatch.setattr(cli, "provider_from_env", lambda: seq)
    assert _patch(_bundle(tmp_path), confirm=True) == 2
    assert len(seq.calls) == 2
    assert "Refusing to patch" in capsys.readouterr().err


def test_a_provider_that_does_not_repair_is_asked_once_on_a_refusal(tmp_path, desk, monkeypatch):
    bad_set = horns_change_set()
    bad_set["add"]["channels"][0]["bus_sends"] = [{"bus": "MON9", "mode": "pre", "level_db": 0.0}]
    fake = FakeProvider(response=_reply(bad_set))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    assert _patch(_bundle(tmp_path), confirm=True) == 2
    assert len(fake.calls) == 1


# -- follow-ups to an earlier change: cost, caching, timeout, a refused field remembered ----------------


def test_a_key_value_entry_that_is_not_json_is_kept_as_a_string():
    sent = [{"key": "a", "json": "{\"x\": 1}"}, {"key": "b", "json": "not json"}]
    schema = {"type": "object", "additionalProperties": True}
    assert strict_schema.from_wire(sent, schema) == {"a": {"x": 1}, "b": "not json"}


def _usage_err(h, capsys, **provider_kw):
    _compile(h.provider(**provider_kw))
    return capsys.readouterr().err


def test_the_hosts_own_cost_is_used_and_said(host, capsys):
    h = host(ok_with_usage({"prompt_tokens": 100, "completion_tokens": 20,
                            "cost_in_usd_ticks": 123_000_000}))
    err = _usage_err(h, capsys)
    assert "-- $0.01 (host-reported cost)" in err      # 123e6 ticks of 1e-10 USD


def test_the_hosts_cost_reaches_the_build_log(host):
    h = host(ok_with_usage({"prompt_tokens": 100, "completion_tokens": 20,
                            "cost_in_usd_ticks": 5_000_000_000}))
    provider = h.provider()
    provider.complete(system="s", user="u", label="generator")
    assert provider.build_log["generator"]["usage"]["cost"] == pytest.approx(0.5)


def test_reasoning_tokens_xai_leaves_out_of_completion_tokens_are_counted_as_output(host, capsys):
    # total = prompt + completion + reasoning: the host kept reasoning out.
    h = host(ok_with_usage({"prompt_tokens": 1_000_000, "completion_tokens": 100_000,
                            "total_tokens": 1_600_000,
                            "completion_tokens_details": {"reasoning_tokens": 500_000}}))
    err = _usage_err(h, capsys)
    assert "-- $2.20 (reasoning tokens counted as output)" in err      # 1 + 0.6M * 2


def test_reasoning_tokens_already_inside_completion_tokens_are_not_counted_twice(host, capsys):
    h = host(ok_with_usage({"prompt_tokens": 1_000_000, "completion_tokens": 600_000,
                            "total_tokens": 1_600_000,
                            "completion_tokens_details": {"reasoning_tokens": 500_000}}))
    err = _usage_err(h, capsys)
    assert "-- $2.20" in err and "counted as output" not in err


def test_cached_input_is_priced_when_a_cached_price_is_set(host, capsys):
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0, "total_tokens": 1_000_000,
             "prompt_tokens_details": {"cached_tokens": 800_000}}
    h = host(ok_with_usage(usage))
    err = _usage_err(h, capsys, price_cached=0.25)
    assert "-- $0.40 (cached input at the cached price)" in err      # 0.2 * 1 + 0.8 * 0.25
    h2 = host(ok_with_usage(usage))
    assert "-- $1.00" in _usage_err(h2, capsys) and "cached" not in capsys.readouterr().err


def test_a_conversation_id_is_sent_and_is_stable_for_the_run(host):
    h = host(ok(patch.empty_change_set("x")))
    provider = h.provider()
    _compile(provider)
    _compile(provider)
    ids = {hd["x-grok-conv-id"] for hd in h.headers}
    assert len(ids) == 1 and "k" not in next(iter(ids))
    other = host(ok(patch.empty_change_set("x")))
    _compile(other.provider())
    assert other.headers[0]["x-grok-conv-id"] not in ids


def test_the_api_provider_waits_longer_than_a_local_one_and_the_timeout_is_a_setting():
    base = {"ATOO_AI_PROVIDER": "api", "ATOO_AI_API_KEY": "k"}
    assert provider_from_env(base).timeout == 600.0
    assert provider_from_env({**base, "ATOO_AI_TIMEOUT": "900"}).timeout == 900.0
    assert provider_from_env({**base, "ATOO_AI_PRICE_CACHED": "0.3"}).price_cached == 0.3
    with pytest.raises(AIProviderError, match="ATOO_AI_TIMEOUT"):
        provider_from_env({**base, "ATOO_AI_TIMEOUT": "soon"})


def test_a_refused_field_is_remembered_so_later_calls_do_not_send_it(host, capsys):
    # grok-build-0.1 answers a reasoning_effort with a 400.
    h = host(bad("Model grok-build-0.1 does not support parameter reasoningEffort."),
             ok(patch.empty_change_set("x")))
    provider = h.provider(reasoning_effort="low")
    _compile(provider)
    _compile(provider)
    _compile(provider)
    assert len(h.requests) == 4        # one refused request, then one per call
    assert "reasoning_effort" in h.requests[0]
    assert all("reasoning_effort" not in r for r in h.requests[1:])
    err = capsys.readouterr().err
    assert err.count("refused `reasoning_effort`") == 1
    assert "not sent again this run" in err
