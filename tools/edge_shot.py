"""لقطات شاشة كاملة عبر Edge بلا واجهة + بروتوكول CDP (لأن لوحة المتصفح المخفية بتقصّ اللقطات 800×600).

الاستعمال: python tools/edge_shot.py jobs.json
jobs.json: قائمة كائنات:
  { "url": "http://127.0.0.1:8000/?mock=1#/library/patterns", "theme": "neon", "w": 1280, "h": 800,
    "out": "C:/.../neon_libs.png", "full": false, "wait": 1.5, "js": "اختياري: كود يشتغل قبل اللقطة", "clip_sel": "اختياري: عنصر بنلتقطه لحاله", "nosave": true (بلا لقطة، قياسات js بس), "name": "اسم للطباعة" }
بيعطّل الحركات ويضبط vp-theme وvp-tour-done قبل التحميل، وبيطبع أي أخطاء صفحة (console.error) لكل مهمة.
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = int(os.environ.get("EDGE_SHOT_PORT", "9333"))


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.pending = {}
        self.events = []

    async def pump(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if "id" in m and m["id"] in self.pending:
                self.pending.pop(m["id"]).set_result(m)
            else:
                self.events.append(m)

    async def call(self, method, params=None, timeout=60):
        self.n += 1
        i = self.n
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        m = await asyncio.wait_for(fut, timeout)
        if "error" in m:
            raise RuntimeError(f"{method}: {m['error']}")
        return m.get("result", {})

    async def eval(self, js, await_promise=True):
        r = await self.call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": await_promise})
        if "exceptionDetails" in r:
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return r.get("result", {}).get("value")


async def run(jobs):
    prof = tempfile.mkdtemp(prefix="edge_shot_")
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                pages = [t for t in tabs if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws_url:
            raise SystemExit("Edge ما رد")
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            c = CDP(ws)
            asyncio.get_event_loop().create_task(c.pump())
            await c.call("Page.enable")
            await c.call("Runtime.enable")
            for j in jobs:
                w, h = int(j.get("w", 1280)), int(j.get("h", 800))
                await c.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": float(j.get("dpr", 1)), "mobile": bool(j.get("mobile", False))})
                theme = j.get("theme", "night")
                # نحط التخزين على نفس الأصل أول، وبعدين نحمّل الصفحة الحقيقية
                origin = j["url"].split("#")[0].split("?")[0]
                await c.call("Page.navigate", {"url": origin.rsplit("/", 1)[0] + "/img/art/logo.png"})
                await asyncio.sleep(0.4)
                await c.eval(f"localStorage.setItem('vp-theme', {json.dumps(theme)}); localStorage.setItem('vp-tour-done','1'); true")
                c.events.clear()
                await c.call("Page.navigate", {"url": j["url"]})
                await asyncio.sleep(float(j.get("wait", 1.6)))
                await c.eval("(() => { const s = document.createElement('style'); s.textContent = '*,*::before,*::after{transition:none!important;animation:none!important}'; document.head.appendChild(s); return true; })()")
                if j.get("js"):
                    r = await c.eval(j["js"])
                    if r is not None:
                        print("   js →", json.dumps(r, ensure_ascii=False)[:600])
                    await asyncio.sleep(float(j.get("after_js", 0.5)))
                clip = None
                if j.get("clip_sel"):
                    box = await c.eval(f"(() => {{ const e = document.querySelector({json.dumps(j['clip_sel'])}); if (!e) return null; e.scrollIntoView({{block:'center'}}); const b = e.getBoundingClientRect(); return {{x: b.left + scrollX, y: b.top + scrollY, w: b.width, h: b.height}}; }})()")
                    if box:
                        clip = {"x": box["x"], "y": box["y"], "width": box["w"], "height": box["h"], "scale": 1}
                if j.get("nosave"):
                    errs = [e for e in c.events if e.get("method") == "Runtime.exceptionThrown" or (e.get("method") == "Runtime.consoleAPICalled" and e["params"].get("type") == "error")]
                    print("OK", j.get("name", j["url"]), f"{w}x{h}", theme, f"(أخطاء: {len(errs)})")
                    for e in errs[:4]:
                        print("   ✗", json.dumps(e["params"], ensure_ascii=False)[:300])
                    continue
                params = {"format": "png", "captureBeyondViewport": bool(j.get("full", False))}
                if clip:
                    params["clip"] = clip
                    params["captureBeyondViewport"] = True
                r = await c.call("Page.captureScreenshot", params)
                out = j["out"]
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "wb") as f:
                    f.write(base64.b64decode(r["data"]))
                errs = [e for e in c.events if e.get("method") == "Runtime.exceptionThrown" or (e.get("method") == "Runtime.consoleAPICalled" and e["params"].get("type") == "error")]
                print("OK", out, f"{w}x{h}", theme, f"(أخطاء: {len(errs)})")
                for e in errs[:4]:
                    print("   ✗", json.dumps(e["params"], ensure_ascii=False)[:300])
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except Exception:
            proc.kill()
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(run(json.load(open(sys.argv[1], encoding="utf-8"))))
