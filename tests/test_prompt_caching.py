"""Anthropic prompt caching on the Claude path.

No paid call is made. The host here is a FAKE Anthropic one: it records the
request body of every call and answers with the `usage` a real cache would
report -- it keeps the prefixes written at each `cache_control` breakpoint
and says what a later request would read, write and leave uncached (the
minimum length, the order tools, system, messages, and the lifetime aside --
see `FakeAnthropic`). What these tests prove is Atoo's side: where the
breakpoints go, that two calls' prefixes are byte-identical, that a repair
reads what the first call wrote, and what the usage line and the build log
say and charge. They cannot say what the real cache does; the live eval
(`evals/live/live_eval.py`) is where that is read off.
"""

from __future__ import annotations

import io
import json

import pytest

from atoo import generate, patch
from atoo.ai_provider import (CACHE_TERMS, ClaudeProvider, FakeProvider, Prompt,
                              claude_cost)
from test_patch import horns_change_set


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeAnthropic:
    """Replaces urlopen with a host that records each request and keeps a
    cache of the prefixes it has been asked to write.

    A request's prefix is its system blocks then its user content blocks,
    in order; a block with `cache_control` ends a cacheable prefix. The
    reported usage follows the documented rules: the longest earlier
    prefix is READ, the rest up to the last breakpoint is WRITTEN, the
    remainder is `input_tokens`; a prefix under the model's minimum is
    neither. Tokens are characters / 4 -- only the shape matters here.
    """

    def __init__(self, monkeypatch, replies=None, minimum: int = 512):
        self.requests: list[dict] = []
        self.usage: list[dict] = []
        self.cache: set[str] = set()
        self.replies = list(replies or ["ok"])
        self.minimum = minimum
        monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", self._urlopen)

    @staticmethod
    def _tokens(chars: int) -> int:
        return chars // 4

    def _urlopen(self, req, timeout=None):
        body = json.loads(req.data)
        self.requests.append(body)
        blocks = list(body["system"]) if isinstance(body["system"], list) else \
            [{"type": "text", "text": body["system"]}]
        content = body["messages"][0]["content"]
        blocks += content if isinstance(content, list) else [{"type": "text", "text": content}]
        total = sum(len(b["text"]) for b in blocks)
        prefix, ends = "", []
        for b in blocks:
            prefix += b["text"]
            if "cache_control" in b:
                ends.append(prefix)
        read = max((len(e) for e in ends if e in self.cache), default=0)
        last = ends[-1] if ends else ""
        write = len(last) - read if last and len(last) > read else 0
        if self._tokens(len(last)) < self.minimum:
            read = write = 0
        self.cache.update(ends if self._tokens(len(last)) >= self.minimum else ())
        usage = {"input_tokens": self._tokens(total - read - write),
                 "cache_creation_input_tokens": self._tokens(write),
                 "cache_read_input_tokens": self._tokens(read)}
        self.usage.append(usage)
        text = self.replies[min(len(self.requests), len(self.replies)) - 1]
        events = [
            {"type": "message_start", "message": {"id": "m", "usage": dict(usage)}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
             "usage": {"output_tokens": 50}},
            {"type": "message_stop"},
        ]
        return _Response("".join(f"data: {json.dumps(e)}\n\n" for e in events).encode())


@pytest.fixture
def host(monkeypatch):
    return FakeAnthropic(monkeypatch)


def claude(**kw) -> ClaudeProvider:
    kw.setdefault("model", "claude-sonnet-5-5")
    return ClaudeProvider(api_key="k", show_progress=False, **kw)


CONVENTIONS = "# Conventions\nKick is red. Vocals are blue.\n" * 40
INPUT_CSV = "ch,name\n" + "".join(f"{i},Ch {i}\n" for i in range(1, 25))
PLAN = {"channels": [{"name": "Kick", "fader": {"fader_db": None, "muted": None}}],
        "busses": {"Mon 1": {"index": 1}}, "meta": {"build_log": {"generator": {}}}}
BASE = {"channels": [{"name": "Kick", "channel": 1}], "busses": {"Mon 1": {"index": 1}}}


def breakpoints(body: dict) -> list[str]:
    """Where the request marks the end of a cached prefix, as the text of
    the block it sits on (the system prompt, then the user blocks)."""
    system = body["system"]
    content = body["messages"][0]["content"]
    blocks = list(system) + (content if isinstance(content, list) else [])
    return [b["text"] for b in blocks if "cache_control" in b]


def cached_prefix(body: dict) -> str:
    """Everything up to and including the LAST breakpoint."""
    content = body["messages"][0]["content"]
    blocks = list(body["system"]) + (content if isinstance(content, list) else [])
    last = max(i for i, b in enumerate(blocks) if "cache_control" in b)
    return "".join(b["text"] for b in blocks[:last + 1])


# -- placement and order ----------------------------------------------------


def test_a_patch_puts_a_breakpoint_after_each_stable_part_and_none_on_the_change(host):
    user = patch.change_user(BASE, "Add two choir mics", conventions=CONVENTIONS,
                             conventions_name="house.md")
    claude().complete(system=patch.change_system("wing-compact"), user=user, label="change")
    body = host.requests[0]

    blocks = body["messages"][0]["content"]
    # domain knowledge | conventions | the desk | the change (not cached)
    assert [("cache_control" in b) for b in blocks] == [True, True, True, False]
    assert blocks[0]["text"].startswith("# Domain knowledge")
    assert "# The engineer's conventions" in blocks[1]["text"] or CONVENTIONS.strip() in blocks[1]["text"]
    assert blocks[2]["text"].startswith("# The plan currently on the desk")
    assert blocks[3]["text"].startswith("# The change") and "Add two choir mics" in blocks[3]["text"]
    # The system prompt (static, and first) is covered by the first user
    # breakpoint; it needs none of its own, and three is under the limit of four.
    assert "cache_control" not in body["system"][0]
    assert body["system"][0]["text"] == patch.change_system("wing-compact")
    assert len(breakpoints(body)) == 3
    # the 5-minute lifetime is the default: no ttl is sent
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks if "cache_control" in b)


def test_without_a_domain_group_the_system_prompt_carries_the_first_breakpoint(host):
    """Fix-up and the watchlist send no domain knowledge: the system
    prompt is the static prefix and is marked itself."""
    claude().complete(system=generate.fixup_system("wing-compact"),
                      user=generate.fixup_user(CONVENTIONS, INPUT_CSV, '{"channels":[]}', ["bad"],
                                               checker="verify", conventions_name="c.md",
                                               input_name="in.csv"),
                      label="fixup")
    body = host.requests[0]
    assert "cache_control" in body["system"][0]
    blocks = body["messages"][0]["content"]
    assert [("cache_control" in b) for b in blocks] == [True, True, False]   # conventions, input list, the reply
    assert blocks[2]["text"].startswith("# Your reply")
    assert len(breakpoints(body)) == 3


def test_a_resolved_build_marks_the_system_prompt_and_the_conventions(host):
    user = generate.generator_user(CONVENTIONS, INPUT_CSV, conventions_name="c.md",
                                   input_name="in.csv", resolved="RESOLVED RULES", resolved_name="r.md")
    claude().complete(system=generate.generator_system("wing-compact"), user=user, label="generator")
    body = host.requests[0]
    assert "cache_control" in body["system"][0]
    assert [("cache_control" in b) for b in body["messages"][0]["content"]] == [True, True, False]


def test_a_plain_string_prompt_still_caches_the_system_prompt(host):
    claude().complete(system="S" * 5000, user="just a string", label="resolve")
    body = host.requests[0]
    assert body["messages"][0]["content"] == "just a string"
    assert "cache_control" in body["system"][0]


def test_the_critic_and_the_watchlist_each_get_their_own_breakpoints(host):
    provider = claude()
    generate.critique_plan(CONVENTIONS, INPUT_CSV, PLAN, provider=provider,
                           conventions_name="c.md", input_name="in.csv")
    generate.draft_watch_conditions(PLAN, CONVENTIONS, provider=provider, conventions_name="c.md")
    critic, watchlist = host.requests
    assert critic["system"][0]["text"] == generate.critic_system()
    assert watchlist["system"][0]["text"] == generate.watchlist_system()
    # critic: domain | conventions | input list | the plan under review
    assert [("cache_control" in b) for b in critic["messages"][0]["content"]] == [True, True, True, False]
    assert critic["messages"][0]["content"][3]["text"].startswith("# The plan to review")
    # watchlist: (system) | conventions | the built plan | the instruction
    assert "cache_control" in watchlist["system"][0]
    assert [("cache_control" in b) for b in watchlist["messages"][0]["content"]] == [True, True, False]
    for body in (critic, watchlist):
        assert len(breakpoints(body)) <= 4


def test_empty_groups_are_not_sent(host):
    claude().complete(system="S" * 5000, user=Prompt(("", "  ", "stable part\n"), "tail"))
    blocks = host.requests[0]["messages"][0]["content"]
    assert [b["text"] for b in blocks] == ["stable part\n", "tail"]
    assert all(b["text"].strip() for b in blocks)


def test_a_prompt_has_at_most_three_cached_groups():
    with pytest.raises(ValueError):
        Prompt(("a", "b", "c", "d"), "tail")


def test_a_prompt_is_the_same_string_every_other_provider_gets():
    user = patch.change_user(BASE, "Add two choir mics", conventions=CONVENTIONS,
                             conventions_name="house.md")
    assert isinstance(user, str) and str(user) == "".join(user.groups) + user.tail
    fake = FakeProvider(response="{}")
    fake.complete(system="s", user=user)          # a provider that knows nothing of groups
    assert fake.calls[0][1] == str(user)


# -- byte stability ----------------------------------------------------------


def test_two_patches_on_one_show_differ_only_after_the_last_breakpoint():
    a = patch.change_user(BASE, "Add two choir mics", conventions=CONVENTIONS, conventions_name="house.md")
    b = patch.change_user(BASE, "Rename Kick to Kick In", conventions=CONVENTIONS, conventions_name="house.md")
    assert a.groups == b.groups and a.tail != b.tail
    assert patch.change_system("wing-compact") == patch.change_system("wing-compact")


def test_a_repair_re_sends_the_prompt_and_only_adds_to_its_tail():
    first = patch.change_user(BASE, "Add two choir mics", conventions=CONVENTIONS, conventions_name="house.md")
    repair = patch._repair_user(first, '{"name": "x"}', "bus 5 is not free")
    assert repair.groups == first.groups
    assert repair.startswith(str(first)) and "bus 5 is not free" in repair.tail


def test_the_critic_prompt_differs_only_in_the_plan_it_reviews():
    other = dict(PLAN, channels=[{"name": "Snare", "fader": {"fader_db": -3, "muted": False}}])
    a = generate.critic_user(CONVENTIONS, INPUT_CSV, PLAN, conventions_name="c.md", input_name="in.csv")
    b = generate.critic_user(CONVENTIONS, INPUT_CSV, other, conventions_name="c.md", input_name="in.csv")
    assert a.groups == b.groups and a.tail != b.tail
    assert generate.critic_system() == generate.critic_system()


def test_two_builds_and_their_fixups_share_what_is_stable():
    kw = dict(conventions_name="c.md", input_name="in.csv")
    g1 = generate.generator_user(CONVENTIONS, INPUT_CSV, **kw)
    g2 = generate.generator_user(CONVENTIONS, INPUT_CSV, **kw)
    assert g1 == g2 and g1.groups == g2.groups
    f1 = generate.fixup_user(CONVENTIONS, INPUT_CSV, '{"channels":[1]}', ["a"], checker="verify", **kw)
    f2 = generate.fixup_user(CONVENTIONS, INPUT_CSV, '{"channels":[2]}', ["b", "c"], checker="verify", **kw)
    assert f1.groups == f2.groups and f1.tail != f2.tail
    # the fix-up's conventions and input list are the generator's own text
    assert f1.groups[1:] == g1.groups[1:]


def test_nothing_before_a_breakpoint_moves_with_the_clock_or_a_counter():
    """The groups are built from the show's own text only: building the
    same prompt twice, a moment apart and with the process's dict ordering
    shuffled by the caller, gives the same bytes."""
    base_a = {"channels": [{"name": "Kick", "channel": 1}], "busses": {"A": {"i": 1}, "B": {"i": 2}}}
    base_b = {"busses": {"A": {"i": 1}, "B": {"i": 2}}, "channels": [{"name": "Kick", "channel": 1}]}
    one = patch.change_user(base_a, "x", conventions=CONVENTIONS, conventions_name="h.md")
    two = patch.change_user(base_b, "x", conventions=CONVENTIONS, conventions_name="h.md")
    assert one.groups == two.groups      # the prompt names the sections in a fixed order


# -- the cache, end to end through the provider ------------------------------


def test_the_second_patch_reads_the_domain_knowledge_and_conventions_from_cache(host):
    provider = claude()
    system = patch.change_system("wing-compact")
    for text in ("Add two choir mics", "Rename Kick"):
        provider.complete(system=system, user=patch.change_user(
            BASE, text, conventions=CONVENTIONS, conventions_name="h.md"), label="change")
    first, second = host.usage
    assert first["cache_read_input_tokens"] == 0 and first["cache_creation_input_tokens"] > 0
    assert second["cache_creation_input_tokens"] == 0
    assert second["cache_read_input_tokens"] == first["cache_creation_input_tokens"]
    assert second["input_tokens"] < first["input_tokens"] + first["cache_creation_input_tokens"]


def test_a_patch_after_an_apply_reads_the_conventions_but_writes_the_new_desk(host):
    provider = claude()
    system = patch.change_system("wing-compact")
    provider.complete(system=system, user=patch.change_user(
        BASE, "one", conventions=CONVENTIONS, conventions_name="h.md"), label="change")
    changed = dict(BASE, busses={"Mon 1": {"index": 1}, "Mon 2": {"index": 2}} | {"pad": {"x": "y" * 4000}})
    provider.complete(system=system, user=patch.change_user(
        changed, "two", conventions=CONVENTIONS, conventions_name="h.md"), label="change")
    first, second = host.usage
    assert second["cache_read_input_tokens"] > 0          # system + domain + conventions
    assert second["cache_read_input_tokens"] < first["cache_creation_input_tokens"]
    assert second["cache_creation_input_tokens"] > 0      # the desk, written again


def test_the_repair_reads_the_first_calls_prefix(monkeypatch):
    host = FakeAnthropic(monkeypatch, replies=[json.dumps(horns_change_set())])
    provider = claude()
    system = patch.change_system("wing-compact")
    user = patch.change_user(BASE, "Add horns", conventions=CONVENTIONS, conventions_name="h.md")
    provider.complete(system=system, user=user, label="change")
    patch.repair_change_set("Add horns", BASE, horns_change_set(), "bus 5 is not free",
                            provider=provider, console_model="wing-compact",
                            conventions=CONVENTIONS, conventions_name="h.md")
    first, repair = host.requests
    assert cached_prefix(first) == cached_prefix(repair)
    assert "bus 5 is not free" in repair["messages"][0]["content"][-1]["text"]
    written, after = host.usage
    assert after["cache_read_input_tokens"] == written["cache_creation_input_tokens"] > 0
    assert after["cache_creation_input_tokens"] == 0


def test_fixup_rounds_read_the_conventions_and_input_list(host):
    provider = claude()
    system = generate.fixup_system("wing-compact")
    for reply, errors in (('{"channels":[1]}', ["a"]), ('{"channels":[2]}', ["b"])):
        provider.complete(system=system, user=generate.fixup_user(
            CONVENTIONS, INPUT_CSV, reply, errors, checker="verify",
            conventions_name="c.md", input_name="in.csv"), label="fixup")
    assert host.usage[1]["cache_read_input_tokens"] == host.usage[0]["cache_creation_input_tokens"] > 0


def test_a_prefix_below_the_minimum_is_not_cached_and_the_line_says_so(monkeypatch, capsys):
    FakeAnthropic(monkeypatch)
    ClaudeProvider(api_key="k", model="claude-sonnet-5-5", show_progress=True).complete(
        system="short system", user=Prompt(("short group\n",), "tail"), label="change")
    err = capsys.readouterr().err
    assert "below the 512-token minimum, not cached" in err
    assert "cache write" not in err


# -- what the line says and what the call costs ------------------------------

WORKED = {"input_tokens": 500, "cache_creation_input_tokens": 10_000,
          "cache_read_input_tokens": 30_000, "output_tokens": 800}


def test_the_worked_example_is_priced_the_way_anthropic_bills_it():
    """500 uncached + 10,000 cache write + 30,000 cache read + 800 out.
    Sonnet 5.5 ($2 in, $10 out; its cache read is 0.05x, $0.10):
      500 x $2 + 10,000 x $2.50 + 30,000 x $0.10 + 800 x $10 = $0.037.
    Sonnet 5 (read 0.1x, $0.20): $0.040. The old input-times-price figure
    for the same usage was $0.002 -- the uncached part only."""
    prices = ClaudeProvider.PRICES
    assert claude_cost("claude-sonnet-5-5", WORKED, prices) == pytest.approx(0.037)
    assert claude_cost("claude-sonnet-5", WORKED, prices) == pytest.approx(0.040)
    assert claude_cost("claude-opus-5", WORKED, prices) == pytest.approx(
        (500 * 5 + 10_000 * 6.25 + 30_000 * 0.5 + 800 * 25) / 1e6)
    assert claude_cost("claude-haiku-4-5", WORKED, prices) == pytest.approx(
        (500 * 1 + 10_000 * 1.25 + 30_000 * 0.1 + 800 * 5) / 1e6)


def test_a_one_hour_write_is_priced_at_twice_the_input_price():
    usage = dict(WORKED, cache_creation_input_tokens=10_000,
                 cache_creation={"ephemeral_5m_input_tokens": 4_000, "ephemeral_1h_input_tokens": 6_000})
    expected = (500 * 2 + 4_000 * 2.5 + 6_000 * 4 + 30_000 * 0.1 + 800 * 10) / 1e6
    assert claude_cost("claude-sonnet-5-5", usage, ClaudeProvider.PRICES) == pytest.approx(expected)


def test_an_unlisted_model_has_no_dollar_figure():
    assert claude_cost("claude-something-new", WORKED, ClaudeProvider.PRICES) is None


def test_every_priced_model_has_a_known_cache_read_price_and_minimum():
    assert set(ClaudeProvider.PRICES) <= set(CACHE_TERMS)


def _stream(usage: dict, text: str = "ok") -> bytes:
    events = [{"type": "message_start", "message": {"id": "m", "usage": usage}},
              {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
              {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
               "usage": {"output_tokens": usage.get("output_tokens", 800)}}]
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def test_the_usage_line_splits_the_input_and_charges_the_cache(monkeypatch, capsys):
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(_stream(WORKED | {"output_tokens": 800})))
    provider = ClaudeProvider(api_key="k", model="claude-sonnet-5-5", show_progress=True)
    provider.complete(system="s", user=Prompt(("g\n",), "t"), label="change")
    line = [ln for ln in capsys.readouterr().err.splitlines() if " in (" in ln][0]
    assert "40,500 in (500 uncached, 10,000 cache write, 30,000 cache read), 800 out" in line
    assert line.endswith("-- $0.04")                 # $0.037


def test_the_build_log_and_the_page_payload_carry_the_cache_counts_and_the_cost(monkeypatch):
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(_stream(WORKED)))
    provider = claude()
    provider.complete(system="s", user=Prompt(("g\n",), "t"), label="change")
    usage = provider.build_log["change"]["usage"]
    assert usage["input"] == 40_500                   # every input token, not only the uncached
    assert usage["cache_write"] == 10_000 and usage["cache_read"] == 30_000
    assert usage["output"] == 800
    assert usage["cost"] == pytest.approx(0.037)


def test_the_setup_page_shows_the_cache_counts_beside_the_cost():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "atoo/web/static/setup.js").read_text()
    assert "usage.cache_read" in js and "usage.cache_write" in js
    assert "usage.cost" in js


# -- compact JSON ------------------------------------------------------------


def test_the_desk_and_the_plan_are_sent_without_indentation():
    user = patch.change_user(BASE, "x", conventions=CONVENTIONS, conventions_name="h.md")
    desk_json = json.dumps(BASE, separators=(",", ":"))
    assert desk_json in user and '\n  "' not in user.groups[2]
    critic = generate.critic_user(CONVENTIONS, INPUT_CSV, PLAN, conventions_name="c.md", input_name="in.csv")
    assert '\n  "' not in critic.tail and ': ' not in critic.tail.split("```json")[1].split("```")[0]


def test_compact_json_is_the_same_content_in_fewer_characters():
    desk = {"channels": [{"name": f"Ch {i}", "channel": i, "fader": {"fader_db": 0.0, "muted": False},
                          "source": {"input": f"Ch {i}", "type": "xlr"}} for i in range(1, 25)]}
    old, new = json.dumps(desk, indent=2), generate.prompt_json(desk)
    assert json.loads(old) == json.loads(new)
    assert len(new) < 0.7 * len(old)
