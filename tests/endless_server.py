"""سيرفر خام للاختبارات: بيرد بجسم ما بينتهي (قطع كبيرة) لحد ما العميل يقطع الاتصال (أو سقف أمان) — لإثبات إن سقوف الحجم بتنطبق أثناء التنزيل
مش بعده (عميل بيحمّل الرد كله بالذاكرة قبل ما يفحص حجمه = بيحمّل لحد سقف الأمان هون)."""

from __future__ import annotations

import http.server
import threading


class EndlessServer:
    def __init__(self, status: int = 200, ctype: str = "application/json", *, prefix: bytes = b"", chunk: int = 256 * 1024, hard_cap: int = 128 * 1024 * 1024,
                 only: str | None = None) -> None:
        self.sent = 0
        self.hits: list[tuple[str, str]] = []
        owner = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"                       # الجسم لحد ما يسكّر الاتصال: بلا Content-Length

            def log_message(self, *a):
                pass

            def _go(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                owner.hits.append((self.command, self.path))
                if only and self.path.split("?")[0] != only:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.end_headers()
                try:
                    if prefix:
                        self.wfile.write(prefix)
                        owner.sent += len(prefix)
                    block = b"x" * chunk
                    while owner.sent < hard_cap:
                        self.wfile.write(block)
                        self.wfile.flush()
                        owner.sent += len(block)
                except OSError:                                  # العميل قطع الاتصال: هيك المفروض
                    pass

            do_GET = do_POST = do_DELETE = _go

        class Quiet(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass

        self.srv = Quiet(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
