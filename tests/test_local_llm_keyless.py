"""نموذج كتابة محلي (على نفس السيرفر): الاتصال والنداء بدون مفتاح لو العنوان محلي، ومفتاح مطلوب لغيره."""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from tests.phase8_support import isolated  # noqa: E402,F401

import connections  # noqa: E402
import llm  # noqa: E402


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = str(self._body)

    def json(self):
        return self._body


@pytest.fixture
def http(monkeypatch):
    sent = []

    def get(url, headers=None, params=None, timeout=None):
        sent.append({"url": url, "headers": dict(headers or {})})
        return Resp(200, {"data": [{"id": "qwen3"}, {"id": "llama"}]})
    monkeypatch.setattr(connections.requests, "get", get)
    return sent


@pytest.mark.parametrize("provider,url", [("custom", "http://127.0.0.1:8000/v1"), ("custom", "http://llm:8000/v1"),
                                          ("custom", "http://localhost:11434/v1"), ("ollama", "")])
def test_local_connections_need_no_key_and_send_no_authorization(isolated, http, provider, url):
    conn = connections.create(provider, "", "", url)
    assert conn["api_key"] == "" and [m["id"] for m in conn["models"]] == ["llama", "qwen3"]
    assert "Authorization" not in http[-1]["headers"]
    assert connections.get(conn["id"])["api_key"] == ""


@pytest.mark.parametrize("provider,url", [("custom", "https://api.example.com/v1"), ("custom", "http://example.com:80/v1"),
                                          ("custom", "http://10.0.0.5:8000/v1"), ("openai", ""), ("anthropic", "")])
def test_everything_else_still_needs_a_key(isolated, http, provider, url):
    with pytest.raises(connections.ConnectionError_, match="لازم مفتاح"):
        connections.create(provider, "  ", "", url)
    assert http == []                                                       # ما بعتنا ولا طلب


def test_a_key_is_still_sent_when_given(isolated, http):
    connections.create("custom", "sk-FAKE-local-0123456789", "", "http://127.0.0.1:8000/v1")
    assert http[-1]["headers"]["Authorization"] == "Bearer sk-FAKE-local-0123456789"


def test_is_local_url_uses_the_same_allowlist_as_the_boxes():
    for ok in ("http://127.0.0.1:8000/v1", "http://localhost:1234", "http://llm:8000/v1", "http://[::1]:8000/v1"):
        assert connections.is_local_url(ok), ok
    for bad in ("https://127.0.0.1:8000/v1", "http://example.com:80/v1", "http://192.168.1.5:8000/v1", "http://user@127.0.0.1:80", "", "nonsense"):
        assert not connections.is_local_url(bad), bad


def cfg(base, key=""):
    return {"provider": "custom", "model": "qwen3", "base_url": base, "api_key": key}


@pytest.fixture
def chat(monkeypatch):
    sent = []

    def post(url, headers=None, json=None, timeout=None):
        sent.append({"url": url, "headers": dict(headers or {}), "json": json})
        return Resp(200, {"choices": [{"message": {"content": "أهلاً"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setattr(llm, "_record", lambda *a, **k: None)
    return sent


@pytest.mark.parametrize("base", ["http://localhost:11434/v1", "http://127.0.0.1:8000/v1", "http://llm:8000/v1", "http://localhost/v1"])
def test_chat_calls_to_local_servers_need_no_key(chat, base):
    assert llm._call_openai(cfg(base), "sys", [{"type": "text", "text": "hi"}], 100) == "أهلاً"
    assert "Authorization" not in chat[-1]["headers"] and chat[-1]["url"] == f"{base}/chat/completions"


def test_chat_calls_elsewhere_still_demand_a_key(chat):
    with pytest.raises(llm.LLMError, match="ما في مفتاح"):
        llm._call_openai(cfg("https://api.example.com/v1"), "sys", [{"type": "text", "text": "hi"}], 100)
    assert chat == []
    llm._call_openai(cfg("https://api.example.com/v1", "sk-FAKE-1234567890"), "sys", [{"type": "text", "text": "hi"}], 100)
    assert chat[-1]["headers"]["Authorization"] == "Bearer sk-FAKE-1234567890"


# ───────── Ollama: التفكير مطفي (نماذج qwen3.5 بترجّع رد فاضي لو فكّرت) ─────────
@pytest.mark.parametrize("provider,url,expect", [
    ("ollama", "http://localhost:11434/v1", True),
    ("custom", "http://127.0.0.1:11434/v1", True),                          # اتصال مخصّص بيأشّر على Ollama
    ("custom", "http://127.0.0.1:8000/v1", False),
    ("openai", "https://api.openai.com/v1", False),
])
def test_ollama_calls_turn_thinking_off(monkeypatch, provider, url, expect):
    sent = {}

    def post(u, headers=None, json=None, timeout=None):
        sent.update(json)
        return Resp(200, {"choices": [{"message": {"content": "تمام"}}], "usage": {}})
    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setattr(llm, "_record", lambda *a, **k: None)
    cfg = {"task": "translate", "provider": provider, "kind": "openai", "model": "qwen3.5:4b",
           "base_url": url, "api_key": "sk-FAKE-0123456789" if provider == "openai" else "", "vision": True}
    assert llm._call_openai(cfg, "سيستم", [{"type": "text", "text": "hi"}], 50) == "تمام"
    assert (sent.get("reasoning_effort") == "none") is expect


def test_ollama_suggests_the_models_on_the_owners_pc():
    assert llm.PROVIDER_PRESETS["ollama"]["models"][0] == "qwen3.5:4b"
