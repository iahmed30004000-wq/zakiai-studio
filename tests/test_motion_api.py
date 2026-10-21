"""تحريك عبر API مباشر (fal.ai): الاختبارات كلها على خادم مزيّف محلي — بلا إنترنت ولا مفتاح حقيقي ولا رصيد."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import motion_api  # noqa: E402

KEY = "test-key-123"


class Fake:
    """خادم fal مزيّف: يسجّل الطلبات ويتحكّم بسلوك الحالة/الأخطاء."""

    def __init__(self, video: bytes):
        self.video = video
        self.requests = []          # (method, path, auth, body)
        self.polls_before_done = 1
        self.status_error = None
        self.submit_status = 200
        self.bad_status_url = False
        self.video_url_override = None
        self.never_done = False
        self.polls = 0
        self.base = ""

    def reset_polls(self):
        self.polls = 0


def make_server(fake: Fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj=None, raw=None, ctype="application/json"):
            body = raw if raw is not None else json.dumps(obj or {}).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _rec(self, body=None):
            fake.requests.append((self.command, self.path, self.headers.get("Authorization"), body))

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self._rec(body)
            if self.headers.get("Authorization") != f"Key {KEY}":
                return self._send(401, {"detail": "unauthorized"})
            if fake.submit_status != 200:
                return self._send(fake.submit_status, {"detail": "x"})
            app = "/".join(self.path.strip("/").split("/")[:2])
            self._send(200, {
                "request_id": "req-1",
                "status_url": "http://evil.example/status" if fake.bad_status_url else f"{fake.base}/{app}/requests/req-1/status",
                "response_url": f"{fake.base}/{app}/requests/req-1",
                "cancel_url": f"{fake.base}/{app}/requests/req-1/cancel"})

        def do_GET(self):
            self._rec()
            if self.path.startswith("/files/"):
                return self._send(200, raw=fake.video, ctype="video/mp4")
            if self.headers.get("Authorization") != f"Key {KEY}":
                return self._send(401, {"detail": "unauthorized"})
            if self.path.endswith("/status"):
                fake.polls += 1
                if fake.never_done or fake.polls <= fake.polls_before_done:
                    return self._send(200, {"status": "IN_PROGRESS"})
                st = {"status": "COMPLETED"}
                if fake.status_error:
                    st["error"] = fake.status_error
                return self._send(200, st)
            url = fake.video_url_override if fake.video_url_override is not None else f"{fake.base}/files/v.mp4"
            self._send(200, {"video": {"url": url}} if url else {"video": {}})

        def do_PUT(self):
            self._rec()
            self._send(200, {"status": "OK"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def fal(tmp_path, monkeypatch):
    mp4 = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=64x112:d=6:r=10", "-pix_fmt", "yuv420p", str(mp4)],
                   capture_output=True, check=True)
    fake = Fake(mp4.read_bytes())
    srv = make_server(fake)
    port = srv.server_address[1]
    fake.base = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(motion_api, "QUEUE_BASE", fake.base)
    motion_api.allow_test_host("127.0.0.1")
    monkeypatch.setattr(motion_api, "get_key", lambda: KEY)
    img = tmp_path / "shot.png"
    Image.new("RGB", (270, 480), (30, 90, 160)).save(img)
    fake.img, fake.tmp = img, tmp_path
    yield fake
    srv.shutdown()
    motion_api._EXTRA_HOSTS.discard("127.0.0.1")


def spec(**kw):
    s = {"provider": "fal", "endpoint": "fal-ai/kling-video/v2.6/pro/image-to-video",
         "input": {"prompt": "{prompt}", "start_image_url": "{image}", "duration": "{duration_str}", "generate_audio": False},
         "durations": [5, 10], "cost_per_sec": 0.07}
    s.update(kw)
    return s


FAST = dict(sleep=lambda s: None)


# ───────── التحقق من الإعداد ─────────
@pytest.mark.parametrize("bad,msg", [
    ({"endpoint": "../etc/passwd"}, "endpoint"),
    ({"endpoint": "https://evil.com/x"}, "endpoint"),
    ({"endpoint": "onlyone"}, "endpoint"),
    ({"input": {"prompt": "{prompt}"}}, "{image}"),
    ({"input": {}}, "كائن"),
    ({"durations": []}, "المدد"),
    ({"durations": [0]}, "المدد"),
    ({"cost_per_sec": "abc"}, "رقم"),
    ({"cost_per_sec": 99}, "المعقول"),
    ({"provider": "other"}, "fal فقط"),
])
def test_invalid_specs_are_rejected_with_arabic_reasons(bad, msg):
    with pytest.raises(motion_api.ApiMotionError, match=msg):
        motion_api.validate_spec(spec(**bad))


def test_all_presets_validate_and_use_silent_audio_so_cost_is_not_doubled():
    for key, p in motion_api.PRESETS.items():
        v = motion_api.validate_spec(p)
        assert v["endpoint"] == p["endpoint"] and v["durations"]
    k = motion_api.PRESETS["kling26"]["input"]
    assert k["generate_audio"] is False and k["start_image_url"] == "{image}"      # Kling بيسمّي حقل الصورة start_image_url


def test_pick_duration_and_cost_estimate():
    s = motion_api.validate_spec(spec())
    assert motion_api.pick_duration(s, 3.4) == 5 and motion_api.pick_duration(s, 5.0) == 5 and motion_api.pick_duration(s, 5.1) == 10
    with pytest.raises(motion_api.ApiMotionError, match="أطول"):
        motion_api.pick_duration(s, 11)
    assert motion_api.estimate_cost(s, 3.4) == pytest.approx(0.35) and motion_api.estimate_cost(s, 11) is None
    assert motion_api.estimate_cost(motion_api.validate_spec(spec(cost_per_sec=None)), 3) is None


def test_payload_substitution_is_single_pass_and_types_are_right():
    g = motion_api.validate_spec(motion_api.PRESETS["grok"])
    pl = motion_api.build_payload(g, "data:image/jpeg;base64,AAA", "حرّك {image} بلطف", 6)
    assert pl["duration"] == 6 and isinstance(pl["duration"], int) and pl["aspect_ratio"] == "9:16"
    assert pl["prompt"] == "حرّك {image} بلطف" and pl["image_url"] == "data:image/jpeg;base64,AAA"   # نص البرومبت ما بيتبدّل
    h = motion_api.build_payload(motion_api.validate_spec(motion_api.PRESETS["hailuo02"]), "d", "p", 6)
    assert h["duration"] == "6" and h["resolution"] == "768P"


# ───────── التشغيل الكامل ─────────
def test_full_run_downloads_the_video_and_reports_cost_without_leaking_the_key(fal):
    out = fal.tmp / "clips" / "raw.mp4"
    logs = []
    r = motion_api.run_job(spec(), fal.img, "كاميرا بتقرّب ببطء", 3.4, out, log=logs.append, **FAST)
    assert out.exists() and out.stat().st_size > 1000
    assert r["billed_sec"] == 5 and r["cost_usd"] == pytest.approx(0.35) and r["request_id"] == "req-1"
    sub = next(x for x in fal.requests if x[0] == "POST")
    assert sub[2] == f"Key {KEY}" and sub[1].startswith("/fal-ai/kling-video")
    body = sub[3]
    assert body["duration"] == "5" and body["generate_audio"] is False and body["prompt"] == "كاميرا بتقرّب ببطء"
    assert body["start_image_url"].startswith("data:image/jpeg;base64,") and len(body["start_image_url"]) < 60_000
    assert KEY not in " ".join(logs)
    dl = [x for x in fal.requests if x[1].startswith("/files/")]
    assert dl and dl[0][2] is None                                              # تنزيل الفيديو بلا المفتاح


def test_missing_key_gives_a_clear_message(fal, monkeypatch):
    monkeypatch.setattr(motion_api, "get_key", lambda: None)
    with pytest.raises(motion_api.ApiMotionError, match="ما في مفتاح"):
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", **FAST)
    assert not fal.requests


@pytest.mark.parametrize("code,msg", [(401, "مرفوض"), (403, "مرفوض"), (402, "رصيد"), (422, "رفض"), (429, "طلبات كتير"), (500, "خطأ 500")])
def test_http_errors_become_plain_arabic_without_the_key(fal, code, msg):
    fal.submit_status = code
    with pytest.raises(motion_api.ApiMotionError, match=msg) as e:
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", **FAST)
    assert KEY not in str(e.value)


def test_wrong_key_is_rejected_by_the_server(fal, monkeypatch):
    monkeypatch.setattr(motion_api, "get_key", lambda: "wrong")
    with pytest.raises(motion_api.ApiMotionError, match="مفتاح fal مرفوض"):
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", **FAST)


def test_generation_error_reported_by_the_provider(fal):
    fal.status_error = "content policy violation"
    with pytest.raises(motion_api.ApiMotionError, match="فشل بالتوليد"):
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", **FAST)


def test_status_url_pointing_elsewhere_is_never_followed_and_key_never_sent(fal):
    fal.bad_status_url = True
    with pytest.raises(motion_api.ApiMotionError, match="غير متوقّع"):
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", **FAST)
    assert [x for x in fal.requests if x[0] == "GET"] == []                       # ما في طلب GET واحد


def test_video_from_an_untrusted_host_is_not_downloaded(fal):
    fal.video_url_override = "https://evil.example/v.mp4"
    with pytest.raises(motion_api.ApiMotionError, match="مصدر غير متوقّع"):
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", **FAST)
    assert not (fal.tmp / "o.mp4").exists()
    fal.video_url_override = "http://v3.fal.media/x.mp4"                           # http مش https
    with pytest.raises(motion_api.ApiMotionError, match="مصدر غير متوقّع"):
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", **FAST)


def test_no_video_in_the_result_means_content_refusal_message(fal):
    fal.video_url_override = ""
    with pytest.raises(motion_api.ApiMotionError, match="ما رجّع فيديو"):
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", **FAST)


def test_timeout_cancels_the_remote_job(fal):
    fal.never_done = True
    with pytest.raises(motion_api.ApiMotionError, match="تأخّر"):
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", timeout_sec=0, **FAST)
    assert any(x[0] == "PUT" and x[1].endswith("/cancel") for x in fal.requests)


def test_owner_cancel_stops_and_cancels_remotely(fal):
    fal.never_done = True
    with pytest.raises(motion_api.ApiMotionError, match="ألغى"):
        motion_api.run_job(spec(), fal.img, "p", 3, fal.tmp / "o.mp4", cancel=lambda: True, **FAST)
    assert any(x[0] == "PUT" for x in fal.requests)


def test_shot_longer_than_the_models_max_fails_before_any_request(fal):
    with pytest.raises(motion_api.ApiMotionError, match="أطول"):
        motion_api.run_job(spec(durations=[5]), fal.img, "p", 7, fal.tmp / "o.mp4", **FAST)
    assert not fal.requests


def test_bad_image_file_is_a_clean_error(fal):
    bad = fal.tmp / "bad.png"
    bad.write_bytes(b"nope")
    with pytest.raises(motion_api.ApiMotionError, match="تعذّرت قراءة"):
        motion_api.run_job(spec(), bad, "p", 3, fal.tmp / "o.mp4", **FAST)
