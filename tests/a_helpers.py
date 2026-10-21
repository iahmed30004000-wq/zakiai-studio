"""
عدّة اختبارات الوكيل A (المراحل 2–4): بيئة مؤقتة معزولة + موديل مزيّف.
لا شبكة ولا LLM حقيقي، ولا كتابة على library/ الحقيقية.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import clusters  # noqa: E402
import llm  # noqa: E402

_WORDS = ["قطرة", "لطيفة", "للعين", "يومياً", "بسهولة", "وراحة", "مع", "الشاشة", "والتعب",
          "تحس", "بفرق", "بسيط", "خلال", "الدوام", "كامل"]
_DURATIONS = [6.0, 7.0, 7.0, 7.0, 7.0, 7.0, 6.0]        # = 47 ثانية


def words(n: int, salt: int = 0) -> str:
    return " ".join(_WORDS[(i + salt) % len(_WORDS)] for i in range(n))


def make_script(hook: str = "هوك تجريبي أول", cta: str = "اطلب الآن وادفع عند الاستلام بلا مخاطرة",
                salt: int = 0, title: str = "سيناريو تجريبي", visual_prefix: str = "لقطة") -> dict:
    """سيناريو سليم: 7 مشاهد، 47ث، إيقاع 2.29–2.5 كلمة/ث، بلا أي ادعاء ممنوع."""
    scenes = []
    for i, dur in enumerate(_DURATIONS, 1):
        n = 15 if dur == 6.0 else 16
        scenes.append({
            "scene_number": i, "duration_sec": dur, "purpose": f"beat {i}",
            "shot_type": "close-up", "visual": f"{visual_prefix} {i} {salt} قريبة على العبوة",
            "voiceover": words(n, i + salt), "on_screen_text": "نص قصير", "emotion": "calm",
            "word_count": n,
        })
    return {
        "title": title, "framework": "pas", "pattern_slot_mapping": [],
        "hook_line": hook, "core_angle": "angle", "pain_points_used": [f"pain {salt}"],
        "total_duration_sec": sum(_DURATIONS), "scenes": scenes, "cta_line": cta,
        "production_notes": [], "self_check": {},
    }


def make_brief(**over) -> dict:
    b = {
        "product_name": "TESTP", "product_code": "testp", "category": "eye_care",
        "country": "SY", "dialect": "shami", "landing_page": "lp1",
        "price": "", "price_positioning": "متوسط",
        "offer": "", "no_offer": True, "guarantee": "", "no_guarantee": True,
        "scarcity_deadline": "", "stock_units": "",
        "core_promise": "ترطيب لطيف للعين", "what_it_does": "قطرة ترطب سطح العين",
        "features": ["عبوة 30 مل", "قطارة معقمة"], "target_audience": "مستخدمو الشاشات",
        "pain_points": ["جفاف العين", "إجهاد الشاشة"], "objections": ["هل هي آمنة؟"],
        "proof_assets": ["صورة العبوة", "مكونات معلنة"], "differentiator": "تركيبة لطيفة",
        "production_constraints": "تصوير داخلي فقط", "forbidden_claims": [],
        "market_claims_evidence": [], "brand_tone": "موثوق", "product_visual": "عبوة زرقاء",
        "previously_used_patterns": [], "_provenance": {}, "_legacy": {},
    }
    b.update(over)
    return b


def make_pattern(category: str = "eye_care", framework: str = "pas", dialect: str = "shami",
                 name: str = "نمط", role: str | None = None) -> dict:
    p = {
        "pattern_name": name, "framework": framework, "product_category": category,
        "dialect_or_language": dialect, "target_audience": "عام", "hook": {"type": "question"},
        "scene_blueprint": [{"function": f"f{i}"} for i in range(7)],
        "reusability_score": 70, "_source": {"type": "mined"},
    }
    if role:
        p["cluster_role"] = role
    return p


class FakeLLM:
    """موديل مزيّف: طابور ردود لكل مهمة (writer/reviewer/match)، وسجل بالنداءات."""

    def __init__(self):
        self.calls: list[dict] = []
        self.queues: dict[str, list] = {}
        self.last: dict[str, object] = {}

    def queue(self, task: str, *responses) -> None:
        self.queues.setdefault(task, []).extend(responses)

    def count(self, task: str) -> int:
        return sum(1 for c in self.calls if c["task"] == task)

    def user(self, task: str, index: int = -1) -> str:
        return [c for c in self.calls if c["task"] == task][index]["user"]

    def __call__(self, task, system, blocks, max_tokens=None):
        self.calls.append({"task": task, "system": system, "user": blocks[0]["text"]})
        q = self.queues.get(task) or []
        if q:
            r = q.pop(0)
            self.last[task] = r
        elif task in self.last:
            r = self.last[task]                 # آخر رد بيتكرر
        else:
            raise AssertionError(f"ما في رد مزيّف جاهز لمهمة {task}")
        if callable(r):
            r = r(self.calls[-1])
        return copy.deepcopy(r)


def review_ok(verdict: str = "approve", findings=None) -> dict:
    return {"verdict": verdict, "summary": "ملخص", "scores": {}, "findings": findings or [],
            "corrected_script": None}


class Env:
    def __init__(self, root: Path, fake: FakeLLM, jobs_created: list):
        self.root = root
        self.lib = root / "library"
        self.scripts = self.lib / "scripts"
        self.patterns = self.lib / "patterns"
        self.products = root / "products"
        self.fake = fake
        self.jobs = jobs_created

    def product(self, name: str = "testp.json", **over) -> Path:
        p = self.products / name
        p.write_text(json.dumps(make_brief(**over), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def pattern(self, pid: str, **kw) -> str:
        (self.patterns / f"{pid}.pattern.json").write_text(
            json.dumps(make_pattern(**kw), ensure_ascii=False, indent=2), encoding="utf-8")
        return pid

    def script_file(self, name: str, script: dict, meta: dict | None = None) -> Path:
        s = copy.deepcopy(script)
        s["_meta"] = meta if meta is not None else {
            "product": "TESTP", "product_file": "testp.json", "product_code": "testp",
            "number": 1, "version": 1, "script_id": "VP-testp-1-v1", "pattern_id": "p1",
            "status": "draft"}
        path = self.scripts / name
        path.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    lib = tmp_path / "library"
    dirs = {"SCRIPTS_DIR": lib / "scripts", "PATTERNS_DIR": lib / "patterns",
            "CANDIDATES_DIR": lib / "candidates", "LIBRARY_DIR": lib,
            "PRODUCTS_DIR": tmp_path / "products"}
    for k, v in dirs.items():
        v.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(config, "REGISTRY_PATH", lib / "used_registry.json")
    monkeypatch.setattr(clusters, "CLUSTERS_PATH", lib / "clusters.json")
    monkeypatch.delenv("APIFY_TOKEN", raising=False)

    fake = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(llm, "task_config", lambda task: {
        "task": task, "provider": "fake", "kind": "fake", "model": "fake-1", "vision": True})

    import stage3_generate
    monkeypatch.setattr(stage3_generate, "_scoreboard", lambda: {})

    created: list = []
    from web import jobs

    def fake_create_job(kind, label, cmd):
        created.append({"kind": kind, "label": label, "cmd": cmd})
        return f"job{len(created)}"

    monkeypatch.setattr(jobs, "create_job", fake_create_job)
    monkeypatch.setattr(jobs, "get_job", lambda jid: None)
    return Env(tmp_path, fake, created)


def api_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_pipeline
    app = FastAPI()
    app.include_router(routes_pipeline.router)
    return TestClient(app)


def future_date(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()
