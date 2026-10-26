"""مسارات /api/drive/* على خادم Google وهمي — ولا ردّ بيرجّع سر، والـ mock موجود لكل مسار."""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from fake_drive import CID, CSECRET, RT, drive  # noqa: E402,F401
from test_drive_sync import STEM, approve_all, make_mission, run  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import drive_sync  # noqa: E402
import gdrive  # noqa: E402
from web import routes_drive  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def client():
    app = FastAPI()
    app.include_router(routes_drive.router)
    return TestClient(app)


def no_secret(r):
    t = r.text
    assert CSECRET not in t and RT not in t and "device_code" not in t and "at-" not in t
    return r.json()


def test_connect_flow_over_http(drive, env, monkeypatch):
    monkeypatch.setattr(drive_sync, "start", lambda: False)
    c = client()
    st = no_secret(c.get("/api/drive/status"))
    assert not st["configured"] and not st["connected"]
    assert c.post("/api/drive/connect").status_code == 409
    assert c.put("/api/drive/app", json={"client_id": "bad", "client_secret": CSECRET}).status_code == 400
    st = no_secret(c.put("/api/drive/app", json={"client_id": CID, "client_secret": CSECRET}))
    assert st["configured"]
    d = no_secret(c.post("/api/drive/connect"))
    assert d["user_code"] == "ABCD-EFGH"
    assert no_secret(c.post("/api/drive/connect/check"))["state"] == "pending"
    gdrive._device["next_at"] = 0
    drive.device = "ok"
    r = no_secret(c.post("/api/drive/connect/check"))
    assert r["state"] == "connected" and r["status"]["connected"] and r["status"]["email"] == "owner@example.com"
    st = no_secret(c.put("/api/drive/app", json={"auto": False}))
    assert st["auto"] is False and st["connected"]
    st = no_secret(c.post("/api/drive/disconnect"))
    assert not st["connected"] and drive.revoked


def test_ad_sync_routes(drive, env, monkeypatch):
    from fake_drive import connect
    c = client()
    make_mission(env)
    assert c.post(f"/api/drive/sync/{STEM}.json").status_code == 409            # بلا ربط
    assert c.get("/api/drive/ad/nope.json").status_code == 404
    connect(drive)
    gdrive.write_cfg(lambda x: x.update(auto=False))
    approve_all()
    st = no_secret(c.post(f"/api/drive/sync/{STEM}.json"))
    assert st["requested"]
    monkeypatch.setattr(drive_sync, "daily_globals", lambda: False)
    run()
    st = no_secret(c.get(f"/api/drive/ad/{STEM}.json"))
    assert st["pending"] == 0 and st["last_ok"] and st["folder_url"]
    r = no_secret(c.post("/api/drive/sync-all"))
    assert r["requested"] == 3
    no_secret(c.post("/api/drive/retry"))


def test_every_drive_route_has_mock():
    """قاعدة AGENTS: كل مسار إلو mock بـ app.js (?mock=1). (جمل سجل النشاط بيفحصها tests/test_activity.py لكل المسارات.)"""
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "mockDriveHook" in app_js and json.loads((STATIC / "mock" / "drive.json").read_text(encoding="utf-8"))["connected"]
    for route in routes_drive.router.routes:
        tail = route.path.replace("/api/drive", "").split("{")[0].rstrip("/")
        assert tail and f"/api/drive{tail}" in app_js.replace("\/", "/"), route.path


def test_ui_files_wired():
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    login = (STATIC / "login.html").read_text(encoding="utf-8")
    assert '/drive.js?v=' in idx and 'id="drivePanel"' in idx
    v_idx = set(re.findall(r"\?v=(\d+)", idx))
    assert v_idx == set(re.findall(r"\?v=(\d+)", login)) and len(v_idx) == 1
    js = (STATIC / "drive.js").read_text(encoding="utf-8")
    assert js.lstrip().startswith("/*") and "(() => {" in js and js.rstrip().endswith("})();")
    assert re.findall(r"window\.(\w+)\s*=", js) == ["driveUI"]
