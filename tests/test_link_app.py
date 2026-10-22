"""ربط «برنامج نموذج» (link_app.py): عميل Gradio خاص فينا. سيرفر Gradio وهمي (tests/fake_gradio.py) بنفس بروتوكول 4.44.1 و6.30.0 الحقيقيين
(اللي انفحصوا بتشغيل برنامج حقيقي): فحص، توليد صور وصوت وتفريغ ومزامنة، رفع الملفات، الأخطاء، الإلغاء، تغيّر البرنامج، وسلامة الروابط."""

from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import link_app as la  # noqa: E402
import model_run as mr  # noqa: E402
from endless_server import EndlessServer  # noqa: E402
from fake_gradio import FakeGradio, png_bytes, wav_bytes  # noqa: E402


@pytest.fixture(params=["4", "6"], ids=["gradio4", "gradio6"])
def gr(request):
    la.clear_cache()
    s = FakeGradio(request.param).start()
    yield s
    s.stop()
    la.clear_cache()


def model(gr, task, api, inputs, *, params=None, output=None, schema_hash=None):
    return {"id": "ml_001", "name": "برنامج", "task": task, "link": "app", "enabled": True, "licence": {"id": "MIT", "commercial": "yes"}, "timeout_sec": 60,
            "params": params or {}, "app": {"url": gr.url, "api_name": api, "inputs": inputs, "output": output or {"index": None}, "schema_hash": schema_hash}}


def ctx_for(m, tmp_path, *, remaining=30.0, **req):
    r = mr.RunRequest(task=m["task"], record=False, **req)
    return mr.Ctx(m, r, {**m["params"], **(r.params or {})}, tmp_path, time.monotonic() + remaining)


def run(m, tmp_path, **kw):
    return la.run(ctx_for(m, tmp_path, **kw))


def save_png(path: Path, size=(40, 60)) -> Path:
    Image.new("RGB", size, (200, 30, 30)).save(path, "PNG")
    return path


def save_wav(path: Path) -> Path:
    path.write_bytes(wav_bytes(1.0))
    return path


# ── فحص البرنامج ──────────────────────────────────────────────────────────
def test_inspect_lists_endpoints_versions_hashes_and_suggestions_per_task(gr):
    ins = la.inspect(gr.url, "image")
    assert ins["ok"] and ins["version"] == ("4.44.1" if gr.gversion == "4" else "6.30.0") and ins["prefix"] == ("" if gr.gversion == "4" else "/gradio_api")
    names = [e["api_name"] for e in ins["endpoints"]]
    assert set(names) == set(gr.endpoints) and ins["suggested"] == "/generate" and names[0] == "/generate"          # الأنسب أول
    gen = ins["endpoints"][0]
    assert gen["fits"] is True and gen["hash"] and [(s["param"], s["from"]) for s in gen["suggest"]] == [
        ("prompt", "prompt"), ("negative", "negative"), ("width", "width"), ("height", "height"), ("seed", "seed")]
    assert [p["name"] for p in gen["params"]] == ["prompt", "width", "height", "seed", "negative"]
    assert gen["params"][0]["required"] is True and gen["params"][1]["required"] is False and gen["params"][1]["default"] == 128
    assert gen["returns"] == [{"label": "Result", "component": "Image", "kind": "image"}]
    pick = {t: la.inspect(gr.url, t)["suggested"] for t in ("music", "upscale", "stt", "voice", "lipsync", "bgremove", "sfx")}
    assert pick["music"] == "/music" and pick["upscale"] == "/upscale" and pick["stt"] in ("/transcribe", "/transcribe_json") and pick["voice"] == "/speak"
    assert pick["lipsync"] == "/lipsync" and pick["bgremove"] == "/upscale" and pick["sfx"] in ("/music", "/speak")
    sp = next(e for e in la.inspect(gr.url, "voice")["endpoints"] if e["api_name"] == "/speak")
    assert [(s["param"], s["from"]) for s in sp["suggest"]] == [("text", "text"), ("voice", "voice")]                 # speed ما بيتخمّن
    assert "suggest" not in la.inspect(gr.url)["endpoints"][0] and la.inspect(gr.url)["suggested"] is None


def test_hashes_follow_the_shape_not_the_values(gr):
    a = la.inspect(gr.url)["endpoints"]
    gr.endpoints["/generate"]["parameters"][1]["parameter_default"] = 999                # قيمة جاهزة اتغيّرت: نفس الشكل
    b = la.inspect(gr.url)["endpoints"]
    h = lambda eps, n: next(e["hash"] for e in eps if e["api_name"] == n)             # noqa: E731
    assert h(a, "/generate") == h(b, "/generate")
    gr.endpoints["/generate"]["parameters"].pop()                                       # معامل راح: شكل جديد
    assert h(la.inspect(gr.url)["endpoints"], "/generate") != h(a, "/generate")


def test_inspect_failures_say_what_is_wrong(gr):
    assert la.inspect("http://example.com:7860")["reason"] == "config"
    assert la.inspect("")["reason"] == "config"
    gr.stop()
    dead = la.inspect(gr.url, timeout=2)
    assert dead["ok"] is False and dead["reason"] == "connection" and "واقف" in dead["message"] and dead["endpoints"] == []


def test_old_protected_redirecting_and_non_gradio_servers_are_refused():
    old = FakeGradio("3").start()
    prot = FakeGradio("6", auth=True).start()
    redir = FakeGradio("6").start()
    redir.modes["config"] = "redirect"

    class Plain(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html>hello</html>" if self.path == "/config" else b"nope"
            self.send_response(200 if self.path == "/config" else 404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    plain = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Plain)
    threading.Thread(target=plain.serve_forever, daemon=True).start()
    try:
        a = la.inspect(old.url)
        assert a["ok"] is False and a["reason"] == "unsupported" and "Gradio 3" in a["message"] and "4 وأحدث" in a["message"]
        b = la.inspect(prot.url)
        assert b["reason"] == "auth" and "كلمة سر" in b["message"]
        c = la.inspect(redir.url)
        assert c["reason"] == "connection" and "التحويلات ممنوعة" in c["message"]
        d = la.inspect(f"http://127.0.0.1:{plain.server_address[1]}")
        assert d["reason"] == "bad_output" and "Gradio" in d["message"]
    finally:
        for s in (old, prot, redir):
            s.stop()
        plain.shutdown()
        plain.server_close()


# ── التشغيل ──────────────────────────────────────────────────────────────
def test_image_maps_request_fields_constants_and_defaults_and_never_sends_a_session(gr, tmp_path):
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}, {"param": "width", "from": "width"}, {"param": "height", "from": "height"},
                                          {"param": "seed", "const": 7.0}], params={"width": 96, "height": 160})
    out = run(m, tmp_path, prompt="عبوة عطر")
    assert out["file"].exists() and out["file"].suffix == ".webp" and out["data"] == {}
    with Image.open(out["file"]) as im:
        assert im.size == (96, 160) and im.format == "WEBP"
    call = gr.calls[-1]
    assert call["data"] == ["عبوة عطر", 96, 160, 7.0, ""] and call["session_hash"] is None          # negative = قيمته الجاهزة، والـ seed ثابت
    assert gr.calls[-1]["api"] == "generate"


def test_negative_comes_from_the_request_or_the_model_and_numbers_are_clean_ints(gr, tmp_path):
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}, {"param": "negative", "from": "negative"}, {"param": "width", "from": "width"}],
              params={"negative": "من الموديل", "width": 128.0})
    run(m, tmp_path, prompt="x")
    assert gr.calls[-1]["data"][0] == "x" and gr.calls[-1]["data"][4] == "من الموديل" and gr.calls[-1]["data"][1] == 128 and isinstance(gr.calls[-1]["data"][1], int)
    run(m, tmp_path, prompt="x", negative="من الطلب")
    assert gr.calls[-1]["data"][4] == "من الطلب"


def test_required_params_that_are_not_mapped_or_have_no_value_are_config_errors(gr, tmp_path):
    m = model(gr, "image", "/generate", [{"param": "width", "from": "width"}])              # prompt مطلوب وما انربط
    with pytest.raises(mr.RunError, match="مطلوب وغير مربوط") as e:
        run(m, tmp_path, prompt="x")
    assert e.value.reason == "config" and not e.value.technical and not gr.calls
    m2 = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}, {"param": "steps_x", "from": "steps"}])
    with pytest.raises(mr.RunError, match="ما عاد موجود بالبرنامج") as e:
        run(m2, tmp_path, prompt="x")
    assert not e.value.technical
    m3 = model(gr, "music", "/music", [{"param": "prompt", "from": "prompt"}, {"param": "seconds", "from": "seconds"}])
    out = run(m3, tmp_path, prompt="calm")                                                  # seconds بلا قيمة: قيمته الجاهزة (3)
    assert gr.calls[-1]["data"] == ["calm", 3] and out["file"].suffix == ".wav"
    run(m3, tmp_path, prompt="calm", seconds=12.0)
    assert gr.calls[-1]["data"] == ["calm", 12]


def test_upscale_uploads_our_file_and_sends_filedata_not_a_path_string(gr, tmp_path):
    src = save_png(tmp_path / "s.png", (40, 60))
    m = model(gr, "upscale", "/upscale", [{"param": "img", "from": "image"}, {"param": "scale", "from": "scale"}], params={"scale": 4})
    out = run(m, tmp_path, image=src)
    assert list(gr.uploads.values()) == [src.read_bytes()]
    path = next(iter(gr.uploads))
    assert gr.calls[-1]["data"] == [{"path": path, "meta": {"_type": "gradio.FileData"}}, 4]
    with Image.open(out["file"]) as im:
        assert im.size == (160, 240)
    with pytest.raises(mr.RunError, match="بدّه image وما انبعت") as e:
        run(m, tmp_path)
    assert e.value.reason == "config" and not e.value.technical


def test_voice_text_voice_name_and_speed_default(gr, tmp_path):
    m = model(gr, "voice", "/speak", [{"param": "text", "from": "text"}, {"param": "voice", "from": "voice"}], params={"voice": "ahmad"})
    out = run(m, tmp_path, text="أهلاً بكم")
    assert gr.calls[-1]["data"] == ["أهلاً بكم", "ahmad", 1] and out["file"].suffix == ".wav"


def test_transcription_text_and_whisper_style_json(gr, tmp_path):
    aud = save_wav(tmp_path / "a.wav")
    m = model(gr, "stt", "/transcribe", [{"param": "audio", "from": "audio"}])
    out = run(m, tmp_path, audio=aud)
    assert out["file"] is None and out["data"]["text"] == "مرحبا بكم" and out["data"]["words"] == []
    j = model(gr, "stt", "/transcribe_json", [{"param": "audio", "from": "audio"}, {"param": "language", "from": "language"}])
    out = run(j, tmp_path, audio=aud, language="ar")
    assert out["data"]["text"] == "مرحبا بكم" and [w["text"] for w in out["data"]["words"]] == ["مرحبا", "بكم"] and gr.calls[-1]["data"][1] == "ar"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")
def test_lipsync_uploads_video_and_audio_and_returns_a_video(gr, tmp_path):
    mp4 = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=96x160:d=1:r=12", "-pix_fmt", "yuv420p", str(mp4)], check=True)
    gr.mp4 = mp4.read_bytes()
    aud = save_wav(tmp_path / "a.wav")
    m = model(gr, "lipsync", "/lipsync", [{"param": "video", "from": "video"}, {"param": "audio", "from": "audio"}])
    out = run(m, tmp_path, video=mp4, audio=aud)
    assert out["file"].suffix == ".mp4" and out["file"].read_bytes()[4:8] == b"ftyp" and len(gr.uploads) == 2
    d = gr.calls[-1]["data"]
    assert all(x["meta"] == {"_type": "gradio.FileData"} for x in d)


def test_explicit_output_index_and_task_kind_selection(gr, tmp_path):
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}], output={"index": 0})
    assert run(m, tmp_path, prompt="x")["file"].exists()
    bad = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}], output={"index": 3})
    with pytest.raises(mr.RunError, match="رقم المخرج") as e:
        run(bad, tmp_path, prompt="x")
    assert not e.value.technical
    assert la.pick_output(["نص", {"path": "/x/a.wav", "meta": {}, "orig_name": "a.wav"}, {"path": "/x/b.webp", "meta": {}, "orig_name": "b.webp"}], "image", None)["path"] == "/x/b.webp"
    assert la.pick_output(["", {"x": 1}, "نص"], "stt", None) == {"x": 1}


# ── الأخطاء ───────────────────────────────────────────────────────────────
def test_program_errors_carry_the_message_when_there_is_one(gr, tmp_path):
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}])
    gr.modes["generate"] = "error"
    with pytest.raises(mr.RunError) as e:
        run(m, tmp_path, prompt="x")
    if gr.gversion == "6":
        assert e.value.reason == "oom" and "CUDA out of memory" in str(e.value) and e.value.technical
    else:
        assert e.value.reason == "model_failed" and "بلا تفاصيل" in str(e.value)               # Gradio 4 ما بيرجّع نص الخطأ
    gr.modes["generate"] = "error_null"
    with pytest.raises(mr.RunError, match="بلا تفاصيل") as e:
        run(m, tmp_path, prompt="x")
    assert e.value.reason == "model_failed" and e.value.technical


@pytest.mark.parametrize("mode,reason,needle", [("complete_null", "cancelled", "انلغت"), ("not_list", "bad_output", "بلا ناتج"), ("empty", "bad_output", "ما لقيت"),
                                                ("traversal", "bad_output", "غير آمن"), ("external_url", "bad_output", "رابط خارجي")])
def test_odd_results_become_clear_errors(gr, tmp_path, mode, reason, needle):
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}])
    gr.modes["generate"] = mode
    with pytest.raises(mr.RunError, match=needle) as e:
        run(m, tmp_path, prompt="x")
    assert e.value.reason == reason and (e.value.technical is (mode != "complete_null"))


def test_downloads_come_from_the_file_path_not_the_url_the_program_hands_us(gr, tmp_path):
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}])
    assert run(m, tmp_path, prompt="x")["file"].exists()
    urls = [r["path"] for r in gr.requests if "/file=" in r["path"]]
    assert len(urls) == 1 and "/ca/file=" not in urls[0]                          # Gradio 4 بيرجّع رابط مبتور: ما منستعمله
    gr.modes["generate"] = "no_path"
    if gr.gversion == "6":
        assert run(m, tmp_path, prompt="x")["file"].exists()                       # رابط البرنامج نفسه (نفس المضيف) بيمشي لو ما في path
    else:
        with pytest.raises(mr.RunError, match="ما لقيت ملف الناتج"):               # ومبتور بـ 4: خطأ واضح مش ملف غلط
            run(m, tmp_path, prompt="x")


def test_download_size_cap_and_empty_files(gr, tmp_path, monkeypatch):
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}])
    gr.modes["generate"] = "huge"
    monkeypatch.setitem(la.MAX_DOWNLOAD, "image", 5000)
    with pytest.raises(mr.RunError, match="أكبر من الحد") as e:
        run(m, tmp_path, prompt="x")
    assert e.value.reason == "bad_output"
    gr.modes["generate"] = ""
    gr.requests.clear()
    monkeypatch.setitem(la.MAX_DOWNLOAD, "image", 64 * 1024 * 1024)
    assert run(m, tmp_path, prompt="x")["file"].exists()


# ── الإلغاء والمهلة ───────────────────────────────────────────────────────
def test_cancel_stops_waiting_and_asks_the_program_to_cancel_the_event(gr, tmp_path):
    m = model(gr, "stt", "/slow", [{"param": "seconds", "const": 5}])
    flag = threading.Event()
    threading.Timer(0.6, flag.set).start()
    t0 = time.monotonic()
    with pytest.raises(mr.RunError, match="انلغت") as e:
        run(m, tmp_path, cancel=flag)
    assert e.value.reason == "cancelled" and not e.value.technical and time.monotonic() - t0 < 4
    ev = gr.calls[-1]["event_id"]
    assert gr.cancelled == [{"session_hash": ev, "fn_index": gr.dep_id("slow"), "event_id": ev}]         # session_hash = رقم الحدث (انفحص بالحقيقي)


def test_timeout_raises_and_cancels_too(gr, tmp_path):
    m = model(gr, "stt", "/slow", [{"param": "seconds", "const": 5}])
    t0 = time.monotonic()
    with pytest.raises(mr.RunError, match="تجاوز المهلة") as e:
        run(m, tmp_path, remaining=0.8)
    assert e.value.reason == "timeout" and e.value.technical and time.monotonic() - t0 < 4
    assert len(gr.cancelled) == 1


def test_a_normal_slow_call_finishes_with_its_text(gr, tmp_path):
    m = model(gr, "stt", "/slow", [{"param": "seconds", "const": 0.3}])
    out = run(m, tmp_path)
    assert out["data"]["text"] == "finished" and not gr.cancelled


def test_a_chatty_program_that_streams_steps_still_honors_timeout_and_cancel(gr, tmp_path):
    gr.modes["slow"] = "chatty"                                                   # أحداث كل 50ms: ما بيجي وقت «ما في أحداث» اللي كانت الوحيدة اللي بتفحص المهلة
    m = model(gr, "stt", "/slow", [{"param": "seconds", "const": 30}])
    t0 = time.monotonic()
    with pytest.raises(mr.RunError, match="تجاوز المهلة") as e:
        run(m, tmp_path, remaining=1.0)
    assert e.value.reason == "timeout" and time.monotonic() - t0 < 6 and len(gr.cancelled) == 1
    flag = threading.Event()
    threading.Timer(0.5, flag.set).start()
    t0 = time.monotonic()
    with pytest.raises(mr.RunError, match="انلغت") as e2:
        run(m, tmp_path, cancel=flag)
    assert e2.value.reason == "cancelled" and time.monotonic() - t0 < 6 and len(gr.cancelled) == 2


def test_a_hard_stop_while_waiting_still_asks_the_program_to_cancel_the_event(gr, tmp_path):
    """SIGTERM بيوصل كـ SystemExit (مش RunError): الحدث ما لازم يضل شغّال عند البرنامج بعد ما يوقف الاستوديو."""
    m = model(gr, "stt", "/slow", [{"param": "seconds", "const": 30}])

    class Boom:
        def is_set(self):
            if gr.slow_started.is_set():
                raise SystemExit(143)
            return False
    t0 = time.monotonic()
    with pytest.raises(SystemExit):
        run(m, tmp_path, cancel=Boom())
    ev = gr.calls[-1]["event_id"]
    assert gr.cancelled == [{"session_hash": ev, "fn_index": gr.dep_id("slow"), "event_id": ev}] and time.monotonic() - t0 < 6


def test_an_event_line_that_never_ends_is_cut_by_the_memory_cap(gr, tmp_path, monkeypatch):
    monkeypatch.setattr(la, "MAX_EVENT_BYTES", 10_000)
    gr.modes["generate"] = "endless_line"
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}])
    t0 = time.monotonic()
    with pytest.raises(mr.RunError, match="أكبر من الحد") as e:
        run(m, tmp_path, prompt="x")
    assert e.value.reason == "bad_output" and time.monotonic() - t0 < 6


# ── Gallery ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode", ["", "plain_files"], ids=["image-caption-items", "plain-file-list"])
def test_gallery_outputs_are_unwrapped_to_the_first_file(gr, tmp_path, mode):
    ins = la.inspect(gr.url, "image")
    gal = next(e for e in ins["endpoints"] if e["api_name"] == "/gallery")
    assert gal["fits"] is True and gal["returns"][0]["kind"] == "images"            # بيتقترح للصور...
    gr.modes["gallery"] = mode
    m = model(gr, "image", "/gallery", [{"param": "prompt", "from": "prompt"}])
    out = run(m, tmp_path, prompt="x")["file"]                                       # ...وبيشتغل فعلاً (كان بيفشل بـ «ما لقيت ناتج»)
    with Image.open(out) as im:
        assert im.size == (64, 96)
    pinned = model(gr, "image", "/gallery", [{"param": "prompt", "from": "prompt"}], output={"index": 0})
    with Image.open(run(pinned, tmp_path, prompt="x")["file"]) as im:
        assert im.size == (64, 96)
    assert la._unwrap("نص") == "نص" and la._unwrap([]) == [] and la._unwrap([{"x": 1}]) == [{"x": 1}]


# ── سقوف الحجم أثناء التنزيل ──────────────────────────────────────────────
def test_oversized_config_and_error_bodies_are_cut_while_downloading_not_after(monkeypatch):
    monkeypatch.setattr(la, "MAX_CONFIG_BYTES", 100 * 1024)
    big = EndlessServer()
    try:
        r = la.inspect(big.url)
        assert r["ok"] is False and r["reason"] == "bad_output" and "أكبر من الحد" in r["message"]
        assert big.sent < 16 * 1024 * 1024, big.sent                                 # قطعنا الاتصال بدل ما نحمّل 128MB كلها
    finally:
        big.stop()
    err = EndlessServer(status=500)
    try:
        r = la.inspect(err.url)
        assert r["ok"] is False and "رد 500" in r["message"] and err.sent < 16 * 1024 * 1024, err.sent
    finally:
        err.stop()


def test_a_body_that_takes_too_long_is_cut(monkeypatch):
    monkeypatch.setattr(la, "BODY_MAX_SEC", -1.0)                                    # أي قطعة بتوصل بعد «انتهاء الوقت» = قطع
    gr = FakeGradio("6").start()
    try:
        r = la.inspect(gr.url)
        assert r["ok"] is False and r["reason"] == "timeout" and "طوّل كتير" in r["message"]
    finally:
        gr.stop()


# ── تغيّر البرنامج ────────────────────────────────────────────────────────
def test_an_updated_program_is_detected_instead_of_sending_wrong_inputs(gr, tmp_path):
    h = la.inspect(gr.url)["endpoints"][0]["hash"]
    la.clear_cache()
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}], schema_hash=h)
    assert run(m, tmp_path, prompt="x")["file"].exists()
    gr.endpoints["/generate"]["parameters"].append({"label": "Steps", "parameter_name": "steps", "parameter_has_default": False, "parameter_default": None,
                                                   "type": {"type": "number"}, "python_type": {"type": "float"}, "component": "Number"})
    la.clear_cache()
    n = len(gr.calls)
    with pytest.raises(mr.RunError, match="اتغيّر بعد ما ربطته") as e:
        run(m, tmp_path, prompt="x")
    assert e.value.reason == "config" and not e.value.technical and len(gr.calls) == n         # ما وصل نداء للبرنامج
    del gr.endpoints["/generate"]
    la.clear_cache()
    with pytest.raises(mr.RunError, match="ما عادت موجودة") as e:
        run(m, tmp_path, prompt="x")
    assert not e.value.technical


# ── سلامة الروابط والمدخلات ───────────────────────────────────────────────
def test_bad_addresses_names_and_tasks_are_refused_before_any_call(gr, tmp_path):
    m = model(gr, "image", "/generate", [{"param": "prompt", "from": "prompt"}])
    for bad_url in ("http://example.com:7860", "https://127.0.0.1:7860", "http://127.0.0.1", "http://user@127.0.0.1:7860"):
        with pytest.raises(mr.RunError) as e:
            run({**m, "app": {**m["app"], "url": bad_url}}, tmp_path, prompt="x")
        assert e.value.reason == "config" and not e.value.technical
    for bad_api in ("/../etc", "/a b", "", "/x?y=1", "/" + "a" * 90):
        with pytest.raises(mr.RunError, match="اسم نقطة") as e:
            run({**m, "app": {**m["app"], "api_name": bad_api}}, tmp_path, prompt="x")
        assert not e.value.technical
    with pytest.raises(mr.RunError, match="مهمة غير مدعومة"):
        run({**m, "task": "motion"}, tmp_path, prompt="x")
    assert not gr.requests


def test_the_program_without_a_bundle_cache_is_refetched_but_cached_within_a_minute(gr, tmp_path):
    m = model(gr, "music", "/music", [{"param": "prompt", "from": "prompt"}])
    run(m, tmp_path, prompt="a")
    first = len([r for r in gr.requests if r["path"].endswith("/config")])
    run(m, tmp_path, prompt="b")
    assert len([r for r in gr.requests if r["path"].endswith("/config")]) == first == 1
    la.clear_cache()
    run(m, tmp_path, prompt="c")
    assert len([r for r in gr.requests if r["path"].endswith("/config")]) == 2


# ── مقترحات الربط (أسماء حقيقية من برامج معروفة) ───────────────────────────
def P(name, label, comp, default=None, has=None):
    return {"parameter_name": name, "label": label, "component": comp, "parameter_has_default": (default is not None) if has is None else has, "parameter_default": default}


def test_suggestions_for_realistic_parameter_sets():
    ace = [P("prompt", "Tags / Prompt", "Textbox", has=False), P("lyrics", "Lyrics", "Textbox", ""), P("audio_duration", "Audio Duration", "Slider", 30), P("infer_step", "Infer Steps", "Slider", 60),
           P("guidance_scale", "Guidance Scale", "Slider", 15), P("seed", "Seed", "Number", 0)]
    sug = {s["param"]: s["from"] for s in la.suggest("music", ace)}
    assert sug == {"prompt": "prompt", "audio_duration": "seconds", "infer_step": "steps", "seed": "seed"}      # guidance ما بيتخمّن، lyrics ما إلها مصدر
    tts = [P("text", "Text to synthesize", "Textbox", has=False), P("speaker", "Speaker", "Dropdown", "a"), P("language", "Language", "Textbox", "en"), P("speed", "Speed", "Slider", 1)]
    sug = {s["param"]: s["from"] for s in la.suggest("voice", tts)}
    assert sug == {"text": "text", "language": "language"}                                                      # Dropdown ما بيتخمّن (خيارات محددة)
    up = [P("image", "Input", "Image", has=False), P("model_name", "Model", "Dropdown", "x"), P("outscale", "Upscale factor", "Slider", 2), P("denoise", "Denoise strength", "Slider", 0.5)]
    sug = {s["param"]: s["from"] for s in la.suggest("upscale", up)}
    assert sug == {"image": "image", "outscale": "scale"}
    s2v = [P("ref_image", "Reference image", "Image", has=False), P("audio", "Driving audio", "Audio", has=False), P("prompt", "Prompt", "Textbox", "")]
    assert {s["param"]: s["from"] for s in la.suggest("lipsync", s2v)} == {"ref_image": "image", "audio": "audio"}
    assert la.suggest("image", []) == [] and la.suggest("stt", [P("file", "File", "File", has=False)]) == []
    gal = [P("prompt", "Prompt", "Textbox", has=False), P("refs", "Reference images", "Gallery", has=False)]
    assert {s["param"]: s["from"] for s in la.suggest("image", gal)} == {"prompt": "prompt", "refs": "refs"}


def test_component_kinds_and_api_names():
    assert [la.kind_of(c) for c in ("Textbox", "Image", "Audio", "Video", "File", "Gallery", "Slider", "Number", "Checkbox", "Radio", "Dropdown", "Whatever", None)] == [
        "text", "image", "audio", "video", "file", "images", "number", "number", "bool", "choice", "choice", "text", "text"]
    assert la.api_name_of("generate") == "/generate" and la.api_name_of("/gen_1-x") == "/gen_1-x"
