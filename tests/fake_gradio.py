"""برنامج Gradio وهمي للاختبارات — بنفس بروتوكول REST اللي انفحص على Gradio 4.44.1 و6.30.0 الحقيقيين (شكل /config و/info والرفع و/call وSSE و/file و/cancel).

الفروقات اللي بيقلّدها حسب version:
    "4": بلا api_prefix، رابط FileData مبتور (/ca/file=…)، خطأ SSE بلا تفاصيل (data: null)، وبعد الإلغاء بينقطع الاتصال (أو خطأ session).
    "6": api_prefix=/gradio_api، رابط FileData كامل ومشفّر، خطأ SSE بـ {error, visible}، وبعد الإلغاء `complete` بـ null.
    "3": /config فيه version 3.x (مرفوض عندنا).
modes[endpoint] = اسم وضع بيخلّي النقطة تغلط بطرق محددة: error | error_null | complete_null | external_url | no_path | empty | not_list | huge | traversal.
أوضاع إضافية: slow=chatty (بث أحداث generating كل 50ms) · generate=endless_line (سطر data بلا نهاية) · gallery=plain_files (قائمة ملفات بدل عناصر {image, caption}).
"""

from __future__ import annotations

import io
import json
import threading
import time
import urllib.parse
import wave
from email.parser import BytesParser
from email.policy import default as email_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def png_bytes(w: int = 64, h: int = 96) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), (30, 120, 200)).save(b, "PNG")
    return b.getvalue()


def webp_bytes(w: int = 64, h: int = 96) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), (30, 120, 200)).save(b, "WEBP")
    return b.getvalue()


def wav_bytes(sec: float = 1.0, rate: int = 16000) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(sec * rate)
        w.writeframes(b"".join(int(8000 * ((i // 40) % 2 * 2 - 1)).to_bytes(2, "little", signed=True) for i in range(n)))
    return b.getvalue()


def param(name, label, component, *, default=None, has_default=None, ptype="string"):
    has = (default is not None) if has_default is None else has_default
    return {"label": label, "parameter_name": name, "parameter_has_default": has, "parameter_default": default,
            "type": {"type": ptype}, "python_type": {"type": "str", "description": ""}, "component": component, "example_input": "x"}


def ret(label, component):
    return {"label": label, "type": {"type": "object"}, "python_type": {"type": "filepath", "description": ""}, "component": component}


class FakeGradio:
    def __init__(self, version: str = "6", *, auth: bool = False):
        self.gversion = version
        self.auth = auth
        self.prefix = "/gradio_api" if version == "6" else ""
        self.requests: list[dict] = []
        self.modes: dict[str, str] = {}
        self.uploads: dict[str, bytes] = {}
        self.files: dict[str, tuple[bytes, str]] = {}
        self.events: dict[str, dict] = {}
        self.cancelled: list[dict] = []
        self.calls: list[dict] = []
        self.slow_started = threading.Event()
        self.transcript_json = {"text": "مرحبا بكم", "language": "ar", "words": [{"word": "مرحبا", "start": 0.0, "end": 0.5}, {"word": "بكم", "start": 0.6, "end": 1.1}]}
        self.endpoints = self._endpoints()
        self.mp4: bytes = b""
        owner = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _read(self) -> bytes:
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _send(self, code, body: bytes, ctype="application/json", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code, obj):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def _rec(self, body: bytes):
                owner.requests.append({"method": self.command, "path": self.path, "ctype": self.headers.get("Content-Type", ""), "len": len(body)})

            def do_GET(self):
                body = self._read()
                self._rec(body)
                path = self.path.split("?")[0]
                p = owner.prefix
                if owner.modes.get("config") == "redirect":
                    return self._send(302, b"", "text/plain", {"Location": "http://example.com/steal"})
                if path == "/config":
                    if owner.auth:
                        return self._json(401, {"detail": "Not authenticated"})
                    return self._json(200, owner._config())
                if path == p + "/info":
                    if owner.auth:
                        return self._json(401, {"detail": "Not authenticated"})
                    return self._json(200, {"named_endpoints": owner.endpoints, "unnamed_endpoints": {}})
                if path.startswith(p + "/call/"):
                    return self._sse(path)
                if path.startswith(p + "/file="):
                    key = urllib.parse.unquote(path[len(p) + len("/file="):])
                    got = owner.files.get(key)
                    if not got:
                        return self._json(404, {"detail": "File not found"})
                    return self._send(200, got[0], "application/octet-stream")
                self._json(404, {"detail": "Not Found"})

            def do_POST(self):
                body = self._read()
                self._rec(body)
                path = self.path.split("?")[0]
                p = owner.prefix
                if path == p + "/upload":
                    ct = self.headers.get("Content-Type", "")
                    msg = BytesParser(policy=email_default).parsebytes(b"Content-Type: " + ct.encode() + b"\r\n\r\n" + body)
                    out = []
                    for part in msg.iter_parts():
                        name = part.get_filename() or "file"
                        data = part.get_payload(decode=True) or b""
                        server_path = f"/tmp/gradio/{len(owner.uploads):04d}/{name}"
                        owner.uploads[server_path] = data
                        out.append(server_path)
                    return self._json(200, out)
                if path.startswith(p + "/call/"):
                    api = path[len(p) + len("/call/"):].strip("/")
                    try:
                        j = json.loads(body.decode("utf-8"))
                    except ValueError:
                        return self._json(422, {"detail": "bad json"})
                    ev = owner._start(api, j)
                    return self._json(200, {"event_id": ev})
                if path == p + "/cancel":
                    j = json.loads(body.decode("utf-8"))
                    owner.cancelled.append(j)
                    e = owner.events.get(j.get("event_id"))
                    if e:
                        e["cancelled"] = True
                    return self._json(200, {"success": True})
                self._json(404, {"detail": "Not Found"})

            def _sse(self, path):
                p = owner.prefix
                rest = path[len(p) + len("/call/"):].split("/")
                if len(rest) != 2:
                    return self._json(404, {"detail": "Not Found"})
                e = owner.events.get(rest[1])
                if not e:
                    return self._json(404, {"detail": "Not Found"})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

                def emit(event, data):
                    self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                try:
                    if owner.gversion == "4" and e["session"]:           # Gradio 4: session_hash بعتناه بـ /call = الحدث بيضيع (انفحص بالحقيقي)
                        return emit("error", json.dumps("404: Session not found."))
                    if rest[0] == "slow":
                        owner.slow_started.set()
                        end = time.time() + float(e["data"][0] if e["data"] else 5)
                        chatty = owner.modes.get("slow") == "chatty"
                        while time.time() < end and not e.get("cancelled"):
                            if chatty:
                                emit("generating", json.dumps([None]))            # بث خطوات أسرع من نص ثانية (ما بيجي وقت «ما في أحداث»)
                            time.sleep(0.05)
                        if e.get("cancelled"):
                            if owner.gversion == "6":
                                emit("complete", "null")
                            return                                  # 4: الاتصال بينقطع بلا حدث ختامي
                        return emit("complete", json.dumps(["finished"]))
                    mode = owner.modes.get(rest[0], "")
                    if mode == "endless_line":
                        self.wfile.write(b"data: ")
                        for _ in range(400):                                          # سطر بلا \n: العميل لازم يقطعه بسقف ذاكرة
                            self.wfile.write(b"x" * 65536)
                            self.wfile.flush()
                        return
                    res = owner._result(rest[0], e["data"], mode)
                    if res[0] == "error":
                        return emit("error", res[1])
                    emit("complete", res[1])
                except (BrokenPipeError, ConnectionResetError):
                    pass

        class Quiet(ThreadingHTTPServer):
            def handle_error(self, request, client_address):          # انقطاع الاتصال بعد الإلغاء متوقّع: بلا ضجيج بمخرجات الاختبار
                pass

        self.server = Quiet(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    # ── الشكل ──
    def _endpoints(self) -> dict:
        v = {
            "/generate": {"parameters": [param("prompt", "Prompt", "Textbox", has_default=False), param("width", "Width", "Slider", default=128, ptype="number"),
                                         param("height", "Height", "Slider", default=192, ptype="number"), param("seed", "Seed", "Number", default=0, ptype="number"),
                                         param("negative", "Negative prompt", "Textbox", default="")],
                          "returns": [ret("Result", "Image")]},
            "/music": {"parameters": [param("prompt", "Prompt", "Textbox", has_default=False), param("seconds", "Duration (s)", "Slider", default=3, ptype="number")],
                       "returns": [ret("Audio", "Audio")]},
            "/upscale": {"parameters": [param("img", "Input image", "Image", has_default=False), param("scale", "Scale", "Radio", default=2)],
                         "returns": [ret("Output", "Image")]},
            "/transcribe": {"parameters": [param("audio", "Audio file", "Audio", has_default=False)], "returns": [ret("Text", "Textbox")]},
            "/transcribe_json": {"parameters": [param("audio", "Audio file", "Audio", has_default=False), param("language", "Language", "Textbox", default="")],
                                 "returns": [ret("Result", "JSON")]},
            "/speak": {"parameters": [param("text", "Text to speak", "Textbox", has_default=False), param("voice", "Voice", "Textbox", default="alloy"),
                                      param("speed", "Speed", "Slider", default=1, ptype="number")], "returns": [ret("Audio", "Audio")]},
            "/lipsync": {"parameters": [param("video", "Video", "Video", has_default=False), param("audio", "Audio", "Audio", has_default=False)],
                         "returns": [ret("Video", "Video")]},
            "/slow": {"parameters": [param("seconds", "Seconds", "Number", default=5, ptype="number")], "returns": [ret("Out", "Textbox")]},
            "/broken": {"parameters": [param("prompt", "Prompt", "Textbox", has_default=False)], "returns": [ret("Result", "Image")]},
            "/gallery": {"parameters": [param("prompt", "Prompt", "Textbox", has_default=False)], "returns": [ret("Gallery", "Gallery")]},
        }
        return v

    def _config(self) -> dict:
        ver = {"4": "4.44.1", "6": "6.30.0", "3": "3.50.2"}[self.gversion]
        cfg = {"version": ver, "protocol": "sse_v3", "mode": "tabbed_interface", "auth_required": None, "max_file_size": None, "root": f"http://127.0.0.1:{self.port}",
               "dependencies": [{"id": i, "api_name": name.lstrip("/"), "queue": True} for i, name in enumerate(self.endpoints)] + [{"id": 99, "api_name": None, "queue": False}]}
        if self.gversion == "6":
            cfg["api_prefix"] = "/gradio_api"
        return cfg

    def dep_id(self, name: str) -> int:
        return list(self.endpoints).index("/" + name.lstrip("/"))

    # ── التنفيذ ──
    def _start(self, api: str, body: dict) -> str:
        ev = f"ev{len(self.events):04d}"
        self.events[ev] = {"api": api, "data": body.get("data") or [], "session": body.get("session_hash")}
        self.calls.append({"api": api, "data": body.get("data"), "session_hash": body.get("session_hash"), "event_id": ev})
        return ev

    def _file(self, name: str, data: bytes) -> dict:
        path = f"/tmp/gradio/{len(self.files):04d}/{name}"
        self.files[path] = (data, name)
        base = f"http://127.0.0.1:{self.port}"
        if self.gversion == "6":
            url = f"{base}{self.prefix}/file={urllib.parse.quote(path, safe='/')}"
        else:
            url = f"{base}/ca/file={path}"                          # الرابط المبتور اللي شفناه بـ 4.44.1
        return {"path": path, "url": url, "size": None, "orig_name": name, "mime_type": None, "is_stream": False, "meta": {"_type": "gradio.FileData"}}

    def _result(self, api: str, data: list, mode: str):
        if mode == "error":
            return "error", json.dumps({"error": "An event handler (gen_image) failed: CUDA out of memory. Tried to allocate 2.00 GiB", "visible": True} if self.gversion == "6" else None)
        if mode == "error_null":
            return "error", "null"
        if mode == "complete_null":
            return "complete", "null"
        if mode == "not_list":
            return "complete", json.dumps({"x": 1})
        if mode == "empty":
            return "complete", json.dumps([])
        if api in ("generate", "upscale", "broken"):
            if api == "upscale":
                src = data[0] if data else None
                size = (80, 120)
                if isinstance(src, dict) and src.get("path") in self.uploads:
                    from PIL import Image
                    im = Image.open(io.BytesIO(self.uploads[src["path"]]))
                    sc = int(data[1]) if len(data) > 1 else 2
                    size = (im.width * sc, im.height * sc)
                fd = self._file("image.webp", webp_bytes(*size))
            else:
                w, h = (int(data[1]), int(data[2])) if len(data) >= 3 else (64, 96)
                fd = self._file("image.webp", webp_bytes(w, h))
            if mode == "external_url":
                fd = {**fd, "path": None, "url": "http://evil.example/x.webp"}
            elif mode == "no_path":
                fd = {**fd, "path": None}
            elif mode == "traversal":
                fd = {**fd, "path": "/tmp/gradio/../../etc/passwd"}
            elif mode == "huge":
                self.files[fd["path"]] = (webp_bytes(64, 96) * 400, "image.webp")
            return "complete", json.dumps([fd])
        if api == "gallery":
            fds = [self._file("a.webp", webp_bytes(64, 96)), self._file("b.webp", webp_bytes(32, 48))]
            if mode == "plain_files":
                return "complete", json.dumps([fds])
            return "complete", json.dumps([[{"image": fd, "caption": None} for fd in fds]])             # شكل Gallery الحقيقي بـ Gradio 4/5/6
        if api in ("music", "speak"):
            return "complete", json.dumps([self._file("audio.wav", wav_bytes(1.0))])
        if api == "transcribe":
            return "complete", json.dumps(["مرحبا بكم"])
        if api == "transcribe_json":
            return "complete", json.dumps([json.dumps(self.transcript_json, ensure_ascii=False)])
        if api == "lipsync":
            return "complete", json.dumps([self._file("video.mp4", self.mp4)])
        return "error", json.dumps(None)

    def start(self) -> "FakeGradio":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"
