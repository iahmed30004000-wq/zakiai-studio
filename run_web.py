#!/usr/bin/env python3
"""
تشغيل واجهة الويب.

    python run_web.py              # محلي فقط: http://127.0.0.1:8000
    python run_web.py --lan        # متاح لأجهزة نفس الشبكة (موبايلك مثلاً)
    python run_web.py --port 9000
"""

import argparse
import os
import socket
import sys

import uvicorn

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="واجهة Zakiai Systems")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true", help="افتحه لأجهزة الشبكة المحلية")
    ap.add_argument("--reload", action="store_true", help="إعادة تحميل تلقائية (للتطوير)")
    args = ap.parse_args()

    os.environ["VP_PORT"] = str(args.port)           # رابط إرجاع فيسبوك (ads_meta.redirect_uri) لازم يطابق المنفذ الفعلي
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    shown = lan_ip() if args.lan else "127.0.0.1"

    print(f"\n  Zakiai Systems → http://{shown}:{args.port}\n")
    if args.lan:
        print("  مفتوح لأجهزة نفس الشبكة. لا تشغّله على شبكة عامة بدون حماية.\n")
        extra = {shown, socket.gethostname().lower()}                      # الحارس (web/guard.py) بيرفض أي Host مش معروف
        extra |= {x.strip() for x in os.environ.get("VP_ALLOWED_HOSTS", "").split(",") if x.strip()}
        os.environ["VP_ALLOWED_HOSTS"] = ",".join(sorted(extra))

    uvicorn.run("web.app:app", host=host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
