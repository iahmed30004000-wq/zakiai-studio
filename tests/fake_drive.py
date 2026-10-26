"""خادم وهمي بيقلّد Google (الربط بالرمز + Drive v3) للاختبارات — على 127.0.0.1 بمنفذ عشوائي، وبيسجّل كل طلب.

self.device: pending | ok | denied — شو بيرد على سؤال «المالك خلّص؟».
self.modes[اسم] بيخلّي نداء يغلط: upload=500|429|quota|disabled · resumable=evil_location|drop · token=invalid_grant.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

RT = "rt-fake-refresh-0123456789"
FOLDER = "application/vnd.google-apps.folder"


class FakeDrive:
    def __init__(self):
        self.requests: list[dict] = []
        self.modes: dict[str, str] = {}
        self.device = "pending"
        self.files: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.tokens: set[str] = set()
        self.revoked = False
        self.n = 0
        self.lock = threading.Lock()
        owner = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _read(self) -> bytes:
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _send(self, code, obj=None, extra=None, raw=None):
                body = raw if raw is not None else (json.dumps(obj, ensure_ascii=False).encode() if obj is not None else b"")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _err(self, code, reason):
                self._send(code, {"error": {"code": code, "errors": [{"reason": reason}], "message": reason}})

            def _auth(self) -> bool:
                h = self.headers.get("Authorization") or ""
                if not h.startswith("Bearer ") or h[7:] not in owner.tokens:
                    self._send(401, {"error": {"code": 401, "message": "bad token"}})
                    return False
                return True

            def _dispatch(self):
                body = self._read()
                u = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                owner.requests.append({"method": self.command, "path": u.path, "query": q,
                                       "auth": self.headers.get("Authorization"), "len": len(body),
                                       "range": self.headers.get("Content-Range")})
                with owner.lock:
                    try:
                        return owner._route(self, self.command, u.path, q, body)
                    except KeyError:
                        return self._err(404, "notFound")

            do_GET = do_POST = do_PATCH = do_PUT = _dispatch

        self.H = H
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    # ── أدوات ─────────────────────────────────────────────────────────────
    def _id(self, prefix="f") -> str:
        self.n += 1
        return f"{prefix}{self.n:04d}"

    def by_name(self, name: str) -> list[dict]:
        return [f for f in self.files.values() if f["name"] == name]

    def path_of(self, fid: str) -> str:
        parts = []
        f = self.files.get(fid)
        while f:
            parts.append(f["name"])
            par = (f.get("parents") or [None])[0]
            f = self.files.get(par) if par else None
        return "/".join(reversed(parts))

    def trashed(self, fid: str) -> bool:
        """متل Google: الملف بالسلة إذا هو أو أي مجلد فوقه بالسلة."""
        f = self.files.get(fid)
        while f:
            if f["trashed"]:
                return True
            par = (f.get("parents") or [None])[0]
            f = self.files.get(par) if par else None
        return False

    def uploads(self) -> list[dict]:
        return [r for r in self.requests if r["path"].startswith("/upload/")]

    def _store(self, meta: dict, content: bytes, fid: str | None) -> dict:
        if fid:
            f = self.files[fid]
            f["content"] = content
            f["revisions"] += 1
            if meta.get("name"):
                f["name"] = meta["name"]
            f.setdefault("appProperties", {}).update(meta.get("appProperties") or {})
            return f
        for par in meta.get("parents") or []:
            if par not in self.files or self.trashed(par):
                raise KeyError(par)                     # المجلد الأب انمسح ← 404
        fid = self._id()
        f = {"id": fid, "name": meta.get("name"), "mimeType": meta.get("mimeType") or "application/octet-stream",
             "parents": meta.get("parents") or [], "appProperties": meta.get("appProperties") or {},
             "content": content, "trashed": False, "revisions": 1}
        self.files[fid] = f
        return f

    # ── التوجيه ───────────────────────────────────────────────────────────
    def _route(self, h, method, path, q, body):
        form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()} if method == "POST" and not path.startswith(("/drive", "/upload")) else {}
        if path == "/device/code":
            return h._send(200, {"device_code": "dc-" + uuid.uuid4().hex, "user_code": "ABCD-EFGH",
                                 "verification_url": "https://www.google.com/device", "expires_in": 1800, "interval": 5})
        if path == "/token":
            if form.get("grant_type", "").endswith("device_code"):
                if self.device == "pending":
                    return h._send(428, {"error": "authorization_pending"})
                if self.device == "denied":
                    return h._send(403, {"error": "access_denied"})
                tok = "at-" + uuid.uuid4().hex[:8]
                self.tokens.add(tok)
                return h._send(200, {"access_token": tok, "refresh_token": RT, "expires_in": 3599, "scope": "drive.file"})
            if self.revoked or self.modes.get("token") == "invalid_grant" or form.get("refresh_token") != RT:
                return h._send(400, {"error": "invalid_grant"})
            tok = "at-" + uuid.uuid4().hex[:8]
            self.tokens.add(tok)
            return h._send(200, {"access_token": tok, "expires_in": 3599})
        if path == "/revoke":
            self.revoked = True
            return h._send(200, {})
        if not h._auth():
            return None
        if path == "/drive/v3/about":
            return h._send(200, {"user": {"emailAddress": "owner@example.com", "displayName": "Owner"},
                                 "storageQuota": {"limit": "16106127360", "usage": "1024"}})
        if path == "/drive/v3/files" and method == "GET":
            m = re.search(r"key='([^']+)' and value='((?:[^'\\]|\\.)*)'", q.get("q", ""))
            k, v = (m.group(1), re.sub(r"\\(.)", r"\1", m.group(2))) if m else ("", "")
            hits = [{"id": f["id"]} for f in self.files.values() if not self.trashed(f["id"]) and f["appProperties"].get(k) == v]
            return h._send(200, {"files": hits})
        if path == "/drive/v3/files" and method == "POST":
            f = self._store(json.loads(body), b"", None)
            return h._send(200, {"id": f["id"]})
        m = re.fullmatch(r"/drive/v3/files/([\w-]+)", path)
        if m:
            f = self.files.get(m.group(1))
            if not f:
                return h._err(404, "notFound")
            if method == "PATCH":
                f["name"] = json.loads(body).get("name") or f["name"]
            return h._send(200, {"id": f["id"], "trashed": self.trashed(f["id"])})
        m = re.fullmatch(r"/upload/drive/v3/files(?:/([\w-]+))?", path)
        if m:
            fid = m.group(1)
            if fid and fid not in self.files:
                return h._err(404, "notFound")
            mode = self.modes.get("upload", "")
            if mode == "500":
                return h._err(500, "backendError")
            if mode == "429":
                return h._err(429, "rateLimitExceeded")
            if mode == "quota":
                return h._err(403, "storageQuotaExceeded")
            if mode == "disabled":
                return h._err(403, "accessNotConfigured")
            if q.get("upload_id"):
                return self._chunk(h, q["upload_id"], body)
            if q.get("uploadType") == "multipart":
                meta, content = _split_multipart(h.headers.get("Content-Type", ""), body)
                f = self._store(meta, content, fid)
                return h._send(200, {"id": f["id"]})
            if q.get("uploadType") == "resumable":
                sid = uuid.uuid4().hex[:10]
                self.sessions[sid] = {"meta": json.loads(body or b"{}"), "fid": fid, "data": bytearray(),
                                      "size": int(h.headers.get("X-Upload-Content-Length") or 0)}
                loc = (f"http://evil.example/upload?upload_id={sid}" if self.modes.get("resumable") == "evil_location"
                       else f"{self.base}/upload/drive/v3/files?uploadType=resumable&upload_id={sid}")
                return h._send(200, {}, extra={"Location": loc})
        return h._err(404, "notFound")

    def _chunk(self, h, sid, body):
        s = self.sessions.get(sid)
        if not s:
            return h._err(404, "notFound")
        rng = h.headers.get("Content-Range") or ""
        m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", rng)
        if m:
            a = int(m.group(1))
            if a != len(s["data"]):
                return h._send(308, None, extra={"Range": f"bytes=0-{len(s['data']) - 1}"} if s["data"] else {})
            if self.modes.get("resumable") == "drop" and s["data"]:
                self.modes["resumable"] = ""
                h.close_connection = True
                h.connection.shutdown(2)                 # النت انقطع بالنص
                return None
            s["data"] += body
        if len(s["data"]) >= s["size"]:
            f = self._store(s["meta"], bytes(s["data"]), s["fid"])
            return h._send(200, {"id": f["id"]})
        return h._send(308, None, extra={"Range": f"bytes=0-{len(s['data']) - 1}"} if s["data"] else {})


def _split_multipart(ctype: str, body: bytes) -> tuple[dict, bytes]:
    b = ctype.split("boundary=", 1)[1].encode()
    parts = body.split(b"--" + b)
    meta_part, media_part = parts[1], parts[2]
    meta = json.loads(meta_part.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n").decode("utf-8"))
    content = media_part.split(b"\r\n\r\n", 1)[1]
    if content.endswith(b"\r\n"):
        content = content[:-2]
    return meta, content


# ── تجهيز مشترك لاختبارات درايف ─────────────────────────────────────────
CID = "123-abc.apps.googleusercontent.com"
CSECRET = "GOCSPX-fake-secret-123"

try:
    import pytest
except ImportError:                                       # pragma: no cover
    pytest = None

if pytest:
    @pytest.fixture
    def drive(env, monkeypatch, tmp_path):
        """خادم وهمي + مخزن أسرار بالذاكرة + settings.json مؤقت. درايف مش مطفي (conftest بيطفيه لباقي الاختبارات)."""
        import config
        import gdrive
        import secrets_store
        import settings_io
        mem, prev = secrets_store.use_memory_backend()
        monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
        settings_io._cache["sig"] = None
        monkeypatch.delenv("VIDPATTERN_NO_DRIVE", raising=False)
        fd = FakeDrive()
        monkeypatch.setattr(gdrive, "OAUTH_BASE", fd.base)
        monkeypatch.setattr(gdrive, "API_BASE", fd.base)
        gdrive.forget_token()
        gdrive._device.clear()
        fd.settings = config.SETTINGS_PATH
        yield fd
        fd.stop()
        gdrive.forget_token()
        gdrive._device.clear()
        secrets_store.restore_backend(prev)
        settings_io._cache["sig"] = None


def connect(fd) -> None:
    """ربط كامل على الخادم الوهمي: الرمزين ← رمز ← المالك وافق."""
    import gdrive
    gdrive.set_app(CID, CSECRET)
    gdrive.device_start()
    fd.device = "ok"
    assert gdrive.device_poll()["state"] == "connected"
