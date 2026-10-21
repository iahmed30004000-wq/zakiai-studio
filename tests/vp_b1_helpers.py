"""
أدوات مشتركة لاختبارات المرحلتين 5 و6 (الوكيل B1): بيئة معزولة + CRM وهمي على منفذ عشوائي.
ما في شبكة حقيقية ولا مفاتيح ولا كتابة على library/ الحقيقية.
"""

from __future__ import annotations

import json
import sys
import threading
import types
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import adname  # noqa: E402
import config  # noqa: E402

TODAY = date(2026, 9, 29)
TOKEN = "test-token-not-real"


class Env:
    def __init__(self, root: Path):
        self.root = root
        self.lib = root / "library"
        self.scripts = self.lib / "scripts"
        self.patterns = self.lib / "patterns"
        self.products = root / "products"
        self.settings = root / "settings.json"
        self.secrets: dict[str, str] = {}
        for d in (self.scripts, self.patterns, self.products):
            d.mkdir(parents=True, exist_ok=True)

    # ── بيانات ──
    def product(self, stem="kama", *, code=None, name=None, country="SY", landing="DawaCare",
                category="eye_care", **extra) -> str:
        import brief
        b = brief.empty_brief()
        b.update({"product_name": name or stem, "product_code": code or stem, "country": country,
                  "landing_page": landing, "category": category, "dialect": "shami", **extra})
        (self.products / f"{stem}.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        return f"{stem}.json"

    def pattern(self, pid, *, name=None, category="eye_care", reusability=5) -> str:
        p = {"pattern_name": name or pid, "framework": "pas", "product_category": category,
             "reusability_score": reusability, "scene_blueprint": []}
        (self.patterns / f"{pid}.pattern.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
        return pid

    def script(self, code, number, pattern_id, *, version=1, product_file=None, name=None,
               with_id=True) -> tuple[str, str]:
        """(اسم ملف السيناريو، script_id)"""
        sid = f"VP-{code}-{number}-v{version}"
        stem = f"{code}__{pattern_id}__{number}v{version}"
        meta = {"product": name or code, "product_file": product_file or f"{code}.json",
                "product_code": code, "number": number, "version": version,
                "pattern_id": pattern_id, "status": "approved"}
        if with_id:
            meta["script_id"] = sid
        s = {"title": f"سيناريو {number}", "hook_line": f"هوك {number}", "framework": "pas",
             "scenes": [{"scene_number": 1, "duration_sec": 7, "voiceover": "..."}], "_meta": meta}
        (self.scripts / f"{stem}.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        return f"{stem}.json", sid


def ad(code: str, sid: str, country="SY", page="DawaCare") -> str:
    return adname.build(country, code, page, sid)


def day(offset: int, today: date = TODAY) -> str:
    return (today + timedelta(days=offset)).isoformat()


def perf_row(ad_name: str, date_str: str, *, delivered: int, cpd: float, orders=None,
             engagement=None, **extra) -> dict:
    orders = orders if orders is not None else int(delivered * 1.5) + 1
    r = {"ad_name": ad_name, "date": date_str, "spend": round(cpd * delivered, 4),
         "orders": orders, "delivered": delivered, "collected": max(delivered - 1, 0)}
    if engagement is not None:
        r["engagement"] = engagement
    r.update(extra)
    return r


def load_rows(rows: list[dict]) -> int:
    import crm
    return crm.upsert_rows(crm.parse_rows({"rows": rows}))


def install_env(tmp_path: Path, monkeypatch) -> Env:
    env = Env(tmp_path)
    for attr, val in (("LIBRARY_DIR", env.lib), ("SCRIPTS_DIR", env.scripts), ("PATTERNS_DIR", env.patterns),
                      ("PRODUCTS_DIR", env.products), ("SETTINGS_PATH", env.settings)):
        monkeypatch.setattr(config, attr, val)
    import evidence
    monkeypatch.setattr(evidence, "today", lambda: TODAY)
    monkeypatch.setattr(config, "PERF_MATURITY_DAYS", 0, raising=False)
    monkeypatch.setattr(config, "MIN_DELIVERED", 20, raising=False)
    monkeypatch.setattr(config, "FATIGUE_DAYS", 7, raising=False)

    import clusters, performance, review_queue
    monkeypatch.setattr(performance, "PERF_PATH", env.lib / "performance.json")
    monkeypatch.setattr(clusters, "CLUSTERS_PATH", env.lib / "clusters.json")
    monkeypatch.setattr(review_queue, "QUEUE_PATH", env.lib / "review_queue.json")

    # لا وصول لمخزن الأسرار ولا للإعدادات الحقيقية
    monkeypatch.setitem(sys.modules, "settings_io", None)
    fake = types.ModuleType("secrets_store")
    fake.get_secret = lambda name: env.secrets.get(name)
    fake.set_secret = lambda name, value: env.secrets.__setitem__(name, value)
    fake.delete_secret = lambda name: env.secrets.pop(name, None)
    monkeypatch.setitem(sys.modules, "secrets_store", fake)
    monkeypatch.delenv("VP_CRM_TOKEN", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    return env


class FakeCRM:
    """سيرفر CRM وهمي على 127.0.0.1 بمنفذ عشوائي — بيسجّل الطلبات وبيتحكّم بالوضع."""

    def __init__(self, token: str = TOKEN):
        self.token = token
        self.rows: list[dict] = []
        self.facts: dict = {}
        self.failures: dict = {}
        self.mode = "ok"                       # ok | 503 | badjson | redirect
        self.requests: list[tuple[str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a, **k):
                pass

            def _send(self, code, body, ctype="application/json"):
                raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                outer.requests.append((u.path, q))
                if self.headers.get("Authorization") != f"Bearer {outer.token}":
                    return self._send(401, {"error": "unauthorized"})
                if outer.mode == "503":
                    return self._send(503, {"error": "down"})
                if outer.mode == "badjson":
                    return self._send(200, b"<html>not json</html>", "text/html")
                if outer.mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://evil.example/")
                    self.end_headers()
                    return
                if u.path == "/api/vidpattern/ad-performance":
                    rows = [r for r in outer.rows if q.get("since", "") <= r["date"] <= q.get("until", "9999")]
                    return self._send(200, {"rows": rows})
                if u.path == "/api/vidpattern/product-market":
                    f = outer.facts.get(q.get("product"))
                    return self._send(200, f) if f is not None else self._send(404, {"error": "no"})
                if u.path == "/api/vidpattern/failure-reasons":
                    return self._send(200, outer.failures.get(q.get("product"), {"reasons": []}))
                self._send(404, {"error": "nope"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def configure(self, env: Env) -> None:
        env.settings.write_text(json.dumps({"CRM": {"base_url": self.url}}), encoding="utf-8")
        env.secrets["crm_token"] = self.token


def seed_market(env: Env, code: str, specs: list[tuple], *, country="SY", page="DawaCare",
                day_offset: int = -10, product_file: str | None = None) -> dict[str, str]:
    """
    specs: [(number, pattern_id, cost_per_delivered, delivered)] → يكتب السيناريوهات وصفوف الأداء.
    بيرجّع {script_file: script_id}.
    """
    out, rows = {}, []
    for number, pid, cpd, delivered in specs:
        f, sid = env.script(code, number, pid, product_file=product_file)
        out[f] = sid
        rows.append(perf_row(ad(code, sid, country, page), day(day_offset), delivered=delivered, cpd=cpd))
    load_rows(rows)
    return out


def series(name, points, *, end_offset=0, base=3.0, step=0.25, delivered=10, engagement=(0.030, 0.020),
           skip=(), zero_delivered=()):
    """points نقاط يومية متتالية بتنتهي عند end_offset. تكلفة الطلب المُسلَّم بترتفع كل يوم."""
    rows = []
    for i in range(points):
        if i in skip:
            continue
        off = end_offset - (points - 1 - i)
        eng = None
        if engagement is not None:
            lo, hi = engagement
            eng = lo + (hi - lo) * i / max(points - 1, 1)
        d = 0 if i in zero_delivered else delivered
        rows.append(perf_row(name, day(off), delivered=d, cpd=base + step * i, engagement=eng,
                             orders=delivered + 2))
        if d == 0:
            rows[-1]["spend"] = 30.0
    return rows
