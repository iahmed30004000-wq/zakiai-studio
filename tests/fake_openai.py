"""سيرفر وهمي بواجهة OpenAI (صور/صوت/تفريغ/models) للاختبارات — على 127.0.0.1 بمنفذ عشوائي، وبيسجّل كل طلب.

modes (self.modes[endpoint] = اسم الوضع) بتخلّي السيرفر يغلط بطرق محددة: error500، oom، redirect، slow، json_error، foreign_url…
"""

from __future__ import annotations

import base64
import io
import json
import threading
import time
import wave
from email.parser import BytesParser
from email.policy import default as email_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def png_bytes(w: int = 512, h: int = 512, alpha: bool = False) -> bytes:
    from PIL import Image
    im = Image.new("RGBA" if alpha else "RGB", (w, h), (200, 40, 40, 128) if alpha else (200, 40, 40))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def wav_bytes(sec: float = 0.6, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(sec * rate)
        w.writeframes(b"".join(int(8000 * ((i // 40) % 2 * 2 - 1)).to_bytes(2, "little", signed=True) for i in range(n)))
    return buf.getvalue()


class FakeOpenAI:
    def __init__(self, token: str | None = None):
        self.token = token
        self.requests: list[dict] = []
        self.modes: dict[str, str] = {}
        self.transcript: dict = {"text": "مرحبا بكم", "language": "ar", "duration": 1.2,
                                 "words": [{"word": "مرحبا", "start": 0.0, "end": 0.5}, {"word": "بكم", "start": 0.6, "end": 1.1}],
                                 "segments": [{"text": "مرحبا بكم", "start": 0.0, "end": 1.1}]}
        owner = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):                      # صامت
                pass

            def _read(self) -> bytes:
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, obj):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def _record(self, body: bytes):
                ct = self.headers.get("Content-Type", "")
                rec = {"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"), "ctype": ct, "raw_len": len(body)}
                if "json" in ct:
                    try:
                        rec["json"] = json.loads(body.decode("utf-8"))
                    except ValueError:
                        rec["json"] = None
                elif "multipart" in ct:
                    msg = BytesParser(policy=email_default).parsebytes(b"Content-Type: " + ct.encode() + b"\r\n\r\n" + body)
                    fields: dict = {}
                    for part in msg.iter_parts():
                        name = part.get_param("name", header="content-disposition")
                        payload = part.get_payload(decode=True) or b""
                        if part.get_filename():
                            fields.setdefault(name, []).append({"filename": part.get_filename(), "size": len(payload)})
                        else:
                            fields.setdefault(name, []).append(payload.decode("utf-8"))
                    rec["fields"] = fields
                owner.requests.append(rec)
                return rec

            def _gate(self, endpoint: str) -> bool:
                """أوضاع الفشل العامة + التوكن. True = انتهى الرد."""
                mode = owner.modes.get(endpoint, "")
                if owner.token and self.headers.get("Authorization") != f"Bearer {owner.token}":
                    self._json(401, {"error": {"message": "bad token"}})
                    return True
                if mode == "error500":
                    self._json(500, {"error": {"message": "boom internal"}})
                    return True
                if mode == "oom":
                    self._json(500, {"error": {"message": "CUDA out of memory. Tried to allocate 2 GiB"}})
                    return True
                if mode == "bad400":
                    self._json(400, {"error": {"message": "size not supported"}})
                    return True
                if mode == "notfound":
                    self._json(404, {"detail": "Not Found"})
                    return True
                if mode == "busy":
                    self._json(429, {"error": {"message": "slow down"}})
                    return True
                if mode == "redirect":
                    self._send(302, b"", "text/plain", {"Location": "http://evil.example/x"})
                    return True
                if mode == "slow":
                    time.sleep(3)
                return False

            def do_GET(self):
                body = self._read()
                self._record(body)
                if self.path == "/v1/models":
                    if self._gate("models"):
                        return
                    self._json(200, {"object": "list", "data": [{"id": "flux"}, {"id": "whisper-large"}, {"id": 5}, {"id": ""}]})
                elif self.path.startswith("/files/"):
                    self._send(200, png_bytes(), "image/png")
                else:
                    self._json(404, {"detail": "nope"})

            def do_POST(self):
                body = self._read()
                rec = self._record(body)
                ep = {"/v1/images/generations": "images", "/v1/images/edits": "edits", "/v1/audio/speech": "speech",
                      "/v1/audio/transcriptions": "stt"}.get(self.path)
                if ep is None:
                    self._json(404, {"detail": "nope"})
                    return
                if self._gate(ep):
                    return
                mode = owner.modes.get(ep, "")
                if ep in ("images", "edits"):
                    if mode == "url":
                        self._json(200, {"data": [{"url": f"http://127.0.0.1:{owner.port}/files/x.png"}]})
                    elif mode == "foreign_url":
                        self._json(200, {"data": [{"url": "http://evil.example/x.png"}]})
                    elif mode == "userinfo_url":
                        self._json(200, {"data": [{"url": f"http://evil@127.0.0.1:{owner.port}/files/x.png"}]})
                    elif mode == "html":
                        self._json(200, {"data": [{"b64_json": base64.b64encode(b"<html><body>error</body></html>").decode()}]})
                    elif mode == "empty":
                        self._json(200, {"data": []})
                    elif mode == "alpha":
                        self._json(200, {"data": [{"b64_json": base64.b64encode(png_bytes(alpha=True)).decode()}]})
                    elif mode == "tiny":
                        self._json(200, {"data": [{"b64_json": base64.b64encode(png_bytes(16, 16)).decode()}]})
                    elif mode == "notjson":
                        self._send(200, b"<html>hi</html>", "text/html")
                    else:
                        self._json(200, {"created": 1, "data": [{"b64_json": base64.b64encode(png_bytes()).decode()}]})
                elif ep == "speech":
                    if mode == "json_error":
                        self._json(200, {"error": {"message": "voice not found"}})
                    elif mode == "silence_empty":
                        self._send(200, b"", "audio/mpeg")
                    elif mode == "garbage":
                        self._send(200, b"this is not audio at all" * 50, "audio/mpeg")
                    else:
                        self._send(200, wav_bytes(), "audio/wav")
                elif ep == "stt":
                    t = dict(owner.transcript)
                    if mode == "words_in_segments":
                        t["segments"] = [{"text": "مرحبا بكم", "start": 0.0, "end": 1.1, "words": t.pop("words")}]
                    elif mode == "no_words":
                        t.pop("words", None)
                    elif mode == "empty":
                        t = {"text": "", "segments": []}
                    self._json(200, t)

        self._H = H
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> "FakeOpenAI":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def last(self, path_suffix: str) -> dict:
        return next(r for r in reversed(self.requests) if r["path"].endswith(path_suffix))
