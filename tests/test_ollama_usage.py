"""The Ollama provider prints the token counts Ollama reports (B).

It already fed them to the progress listener and the build log; it never
printed the one-line spend report the other providers do, so an eval that reads
those lines saw 0 in / 0 out. A fake Ollama host answers over real HTTP.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from atoo.ai_provider import OllamaProvider
from atoo.progress import model_progress_listener

USAGE = re.compile(r"^\s+(\S+) \([^)]*\): ([\d,]+) in, ([\d,]+) out(.*)$", re.M)


@pytest.fixture
def host():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            if self.path != "/api/chat":
                self.send_response(404)
                self.end_headers()
                return
            events = [
                {"message": {"content": '{"name":'}, "done": False},
                {"message": {"content": '"x"}'}, "done": False},
                {"message": {"content": ""}, "done": True, "done_reason": "stop",
                 "prompt_eval_count": 5663, "eval_count": 74, "total_duration": 9_000_000_000},
            ]
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for event in events:
                self.wfile.write((json.dumps(event) + "\n").encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", seen
    server.shutdown()


def test_the_usage_line_carries_ollamas_own_counts(host, capsys):
    url, seen = host
    text = OllamaProvider(model="qwen2.5:7b-instruct", base_url=url, num_ctx=8192).complete(
        system="s", user="u", label="intent")
    assert text == '{"name":"x"}' and seen[-1][0] == "/api/chat"
    err = capsys.readouterr().err
    (who, sent, got, rest), = USAGE.findall(err)
    assert (who, sent, got) == ("qwen2.5:7b-instruct", "5,663", "74")
    assert "-- $0.00" in rest, "a local model is counted at no charge, not left unpriced"


def test_the_same_counts_reach_the_listener_and_a_quiet_provider_prints_nothing(host, capsys):
    url, _ = host
    seen = []
    with model_progress_listener(seen.append):
        OllamaProvider(model="m", base_url=url, num_ctx=8192, show_progress=False).complete(
            system="s", user="u", label="critic")
    assert capsys.readouterr().err == ""
    assert seen[-1]["input_tokens"] == 5663 and seen[-1]["total_output_tokens"] == 74


def test_a_thinking_model_is_not_capped_and_think_is_sent_only_when_set(monkeypatch):
    import io
    import json as _json
    from atoo import intent
    from atoo.ai_provider import OllamaProvider, provider_from_env

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_open(capabilities):
        def opener(req, timeout=None):
            return Resp(_json.dumps({"capabilities": capabilities}).encode())
        return opener

    thinker = OllamaProvider(model="t")
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_open(["completion", "thinking"]))
    assert thinker.thinks() and intent._capped(thinker).num_predict == -1
    assert OllamaProvider(model="t", think=False).thinks() is False
    assert intent._capped(OllamaProvider(model="t", think=False)).num_predict == intent.REPLY_TOKENS
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_open(["completion"]))
    assert not thinker.thinks() and intent._capped(thinker).num_predict == intent.REPLY_TOKENS
    assert provider_from_env({"ATOO_AI_PROVIDER": "ollama", "ATOO_AI_THINK": "off"}).think is False
    assert provider_from_env({"ATOO_AI_PROVIDER": "ollama"}).think is None


def test_the_context_size_is_one_of_a_few_fixed_sizes_and_an_intent_is_not_given_a_plans_room(monkeypatch):
    """Ollama reloads the model when num_ctx changes, losing its cached prompt prefix; a size that
    moved with every prompt made every request a reload."""
    from atoo import intent
    from atoo.ai_provider import CHARS_PER_TOKEN, OllamaProvider

    monkeypatch.setattr(OllamaProvider, "thinks", lambda self: False)
    plain = intent._capped(OllamaProvider(model="m"))
    assert plain.reply_tokens == intent.REPLY_TOKENS
    sizes = {plain._auto_num_ctx("s" * int(n * CHARS_PER_TOKEN), "") for n in range(9000, 11500, 250)}
    assert sizes == {16384}                       # every Patch-sized prompt gets the same window
    for n in (1000, 9000, 20000, 40000):
        size = plain._auto_num_ctx("s" * int(n * CHARS_PER_TOKEN), "")
        assert size & (size - 1) == 0 and size >= n + intent.REPLY_TOKENS
    monkeypatch.setattr(OllamaProvider, "thinks", lambda self: True)
    assert intent._capped(OllamaProvider(model="m")).reply_tokens == 4 * intent.REPLY_TOKENS
    # a whole plan (no reply size given) still gets room for a plan, rounded the same way
    whole = OllamaProvider(model="m")
    size = whole._auto_num_ctx("s" * int(5000 * CHARS_PER_TOKEN), "")
    assert size >= 5000 * 2.5 and size & (size - 1) == 0


def test_each_request_prints_the_context_window_it_ran_with_and_the_eval_records_it(capsys):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "evals" / "live" / "live_intent_eval.py"
    if not path.exists():
        pytest.skip("evals/live is private; not in the public tree")
    spec = importlib.util.spec_from_file_location("_lie", path)
    lie = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lie)
    text = ("  m (intent): 9,000 in, 100 out -- $0.00\n  num_ctx 16,384 for m (intent)\n"
            "  m (intent-repair): 13,000 in, 100 out -- $0.00\n  num_ctx 32,768 for m (intent-repair)\n")
    assert lie.num_ctx_seen(text) == [16384, 32768]
    assert lie.num_ctx_seen("") == []
