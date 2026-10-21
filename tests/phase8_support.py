"""أدوات مشتركة لاختبارات المرحلة 8 — بدون شبكة، بدون Credential Manager الحقيقي."""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
import secrets_store
import settings_io

FAKE_KEY_A = "sk-ant-FAKEKEY-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
FAKE_KEY_B = "sk-proj-FAKEKEY-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
FAKE_KEY_IMG = "sk-img-FAKEKEY-cccccccccccccccccccccccccccccccccc"
FAKE_KEY_TASK = "sk-task-FAKEKEY-dddddddddddddddddddddddddddddddd"
FAKE_KEY_TTS = "el-FAKEKEY-tts-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
FAKE_KEY_STT = "stt-FAKEKEY-ffffffffffffffffffffffffffffffffff"
FAKE_ANTHROPIC = "sk-ant-FAKEKEY-gggggggggggggggggggggggggggggggggg"
FAKE_CRM_TOKEN = "crm-token-FAKE-hhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh"
ALL_FAKE = [FAKE_KEY_A, FAKE_KEY_B, FAKE_KEY_IMG, FAKE_KEY_TASK, FAKE_KEY_TTS,
            FAKE_KEY_STT, FAKE_ANTHROPIC, FAKE_CRM_TOKEN]


def sample_settings() -> dict:
    return {
        "MAX_OUTPUT_TOKENS": 12000,
        "ANTHROPIC_API_KEY": FAKE_ANTHROPIC,
        "CUSTOM_MODELS": {"openai": ["my-model"]},
        "CONNECTIONS": {
            "c_one": {"provider": "openai", "label": "A", "api_key": FAKE_KEY_A,
                      "base_url": "https://api.openai.com/v1",
                      "models": [{"id": "gpt-5", "label": "gpt-5"}]},
            "c_two": {"provider": "moonshot", "label": "B", "api_key": FAKE_KEY_B,
                      "base_url": "https://api.moonshot.ai/v1", "models": []},
        },
        "TASKS": {"writer": {"connection": "c_one", "model": "gpt-5"},
                  "match": {"provider": "deepseek", "model": "deepseek-chat", "api_key": FAKE_KEY_TASK}},
        "IMAGE": {"provider": "openai", "api_key": FAKE_KEY_IMG},
        "TTS": {"provider": "elevenlabs", "api_key": FAKE_KEY_TTS},
        "STT": {"provider": "openai", "api_key": FAKE_KEY_STT},
    }


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """مسارات مؤقتة + مخزن أسرار بالذاكرة. ما بنلمس settings.json ولا library الحقيقية."""
    mem, prev = secrets_store.use_memory_backend()
    lib = tmp_path / "library"
    prods = tmp_path / "products"
    prompts = tmp_path / "prompts"
    for d in (lib, prods, prompts, lib / "patterns", lib / "scripts"):
        d.mkdir(parents=True, exist_ok=True)
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(config, "BASE", tmp_path)
    monkeypatch.setattr(config, "LIBRARY_DIR", lib)
    monkeypatch.setattr(config, "PATTERNS_DIR", lib / "patterns")
    monkeypatch.setattr(config, "SCRIPTS_DIR", lib / "scripts")
    monkeypatch.setattr(config, "PRODUCTS_DIR", prods)
    monkeypatch.setattr(config, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(config, "SETTINGS_PATH", settings)
    import usage
    monkeypatch.setattr(usage, "DB_PATH", lib / "usage.db")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings_io._cache["sig"] = None
    settings_io._known_values.clear()
    settings_io._warned.clear()
    try:
        yield SimpleNamespace(tmp=tmp_path, lib=lib, products=prods, prompts=prompts,
                              settings=settings, mem=mem)
    finally:
        secrets_store.restore_backend(prev)
        settings_io._cache["sig"] = None
        settings_io._known_values.clear()


def make_library(ns, videos: bool = True) -> None:
    """مكتبة تجريبية صغيرة بنفس أشكال الحقيقية."""
    lib = ns.lib
    (lib / "patterns" / "p1.pattern.json").write_text(json.dumps(
        {"pattern_name": "نمط أول", "framework": "pas", "product_category": "fragrance"},
        ensure_ascii=False), encoding="utf-8")
    (lib / "scripts" / "s1.json").write_text(json.dumps(
        {"title": "سيناريو", "scenes": [{"scene_number": 1}]}, ensure_ascii=False), encoding="utf-8")
    (lib / "reviews").mkdir(exist_ok=True)
    (lib / "reviews" / "s1.review.json").write_text('{"ok": true}', encoding="utf-8")
    raw = lib / "raw" / "108"
    (raw / "frames").mkdir(parents=True, exist_ok=True)
    (raw / "extract.json").write_text('{"video_id": "108"}', encoding="utf-8")
    (raw / "transcript.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nمرحبا\n", encoding="utf-8")
    (raw / "frames" / "f1.jpg").write_bytes(b"\xff\xd8\xff" + bytes(range(256)) * 20)
    if videos:
        (raw / "108.mp4").write_bytes(b"VIDEO" * 5000)
    (lib / "uploads").mkdir(exist_ok=True)
    (lib / "uploads" / "up.mp4").write_bytes(b"UPLOAD" * 100)
    (lib / "_backups" / "old").mkdir(parents=True, exist_ok=True)
    (lib / "_backups" / "old" / "x.txt").write_text("old", encoding="utf-8")
    conn = sqlite3.connect(lib / "usage.db")
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    (ns.products / "kama.json").write_text('{"product_name": "kama"}', encoding="utf-8")
    (ns.prompts / "script_writer.txt").write_text("prompt", encoding="utf-8")


# ── CRM وهمي ────────────────────────────────────────────────────────────


class CRMOffline(Exception):
    pass


class CRMError(Exception):
    pass


class FakeCRM:
    """
    بيقلّد عميل B1 الحقيقي: بيرجّع JSON مباشرة، وبيرمي CRMOffline (انقطاع/5xx)
    وCRMError برسالة «HTTP nnn» على 4xx. السيرفر: طابور + مطالبة + نتيجة + رفع مكتبة.
    """

    def __init__(self, items: list[dict] | None = None):
        self.items = {str(i["id"]): {**i, "status": "pending"} for i in (items or [])}
        self.claims: list[str] = []
        self.results: dict[str, list[dict]] = {}
        self.library_puts: list[dict] = []
        self.offline = False
        self.result_status = 200
        self.claim_status = 200
        self.put_status = 200

    def _raise_for(self, code: int) -> None:
        if code >= 500:
            raise CRMOffline(f"الـ OMS غير متاح مؤقتاً (HTTP {code})")
        if code >= 400:
            raise CRMError(f"الـ OMS رفض الطلب (HTTP {code})")

    def get(self, path, params=None, **kw):
        if self.offline:
            raise CRMOffline("offline")
        assert path == "/api/vidpattern/queue" and (params or {}).get("status") == "pending"
        pend = [{k: v for k, v in i.items() if k != "status"}
                for i in self.items.values() if i["status"] in ("pending", "claimed")]
        return {"items": pend}

    def post(self, path, json=None, **kw):
        if self.offline:
            raise CRMOffline("offline")
        parts = path.strip("/").split("/")
        item_id, action = parts[-2], parts[-1]
        if action == "claim":
            self.claims.append(item_id)
            self._raise_for(self.claim_status)
            self.items[item_id]["status"] = "claimed"
            return {}
        if action == "result":
            self._raise_for(self.result_status)
            self.results.setdefault(item_id, []).append(json)
            self.items[item_id]["status"] = "done"
            return {}
        raise AssertionError(path)

    def put(self, path, json=None, **kw):
        if self.offline:
            raise CRMOffline("offline")
        assert path == "/api/vidpattern/library"
        self._raise_for(self.put_status)
        self.library_puts.append(json)
        return {}


def install_fake_crm(monkeypatch, client: FakeCRM, configured: bool = True):
    mod = types.ModuleType("crm")
    mod.get_client = lambda: client
    mod.is_configured = lambda: configured
    mod.CRMOffline = CRMOffline
    mod.CRMError = CRMError
    monkeypatch.setitem(sys.modules, "crm", mod)
    return mod


def hide_module(monkeypatch, name: str) -> None:
    """يخلّي import للوحدة يفشل كأنها مش موجودة."""
    monkeypatch.setitem(sys.modules, name, None)
