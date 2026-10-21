"""المونتاج المتقدّم — المرحلة صفر: بناء job محايد + تجهيز الوسائط + التحقق (ffmpeg/ffprobe حقيقيين، ملفات lavfi صغيرة)."""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.advanced_montage import constants as C  # noqa: E402
from services.advanced_montage.adapter.build_job import build_job, safe_name, summarize  # noqa: E402
from services.advanced_montage.adapter.captions import build_captions, frame_of  # noqa: E402
from services.advanced_montage.adapter.stage_media import stage_media  # noqa: E402
from services.advanced_montage.adapter.text import latin_digits, scan_job_for_leaks  # noqa: E402
from services.advanced_montage.adapter.verify import verify_output  # noqa: E402
from services.advanced_montage import render as render_mod  # noqa: E402
from services.advanced_montage.errors import JobError, RendererUnavailable, StageError  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                reason="ffmpeg/ffprobe غير متوفر")

SCENE_MS = [2100, 2300, 2300, 2300, 2300, 2300, 2100]          # المجموع 15700 (قيم غير مدوّرة عمداً)
TOTAL = sum(SCENE_MS)
LONG_WORD = "والاستشعارالمتناهيالصغرمتعددالأبعاد"                # 35 حرف: أطول من حد السطر
WORDS = ["عينك", "بآخر", "النهار", "تعبانة،", "جرّبي", "قطرة", "الكمأة", "الطبيعية", "للعين", "٢", "مرات",
         "يومياً", "وبسهولة", "ومن", "غير", "تعب"]
_DEFAULT_BRIEF = {
    "product_name": "TESTP", "product_code": "testp", "price": "١٩٫٩", "currency": "د.أ",
    "offer": "اشتري ٢ والتوصيل مجاني", "no_offer": False,
    "guarantee": "ضمان استرجاع ٧ أيام", "no_guarantee": False,
    "ops_product_id": "ops-12345", "ops_store_id": "store-777", "landing_page": "lp-secret-page",
}


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def probe_s(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


# ───────────────────────── مكتبة تجريبية ─────────────────────────
def _make_timeline(stem="s1", with_fallback=True) -> dict:
    words, scenes, t, w_i = [], [], 0, 0
    for n, dur in enumerate(SCENE_MS, 1):
        s0, s1 = t, t + dur
        per = dur // 8
        first = len(words)
        for k in range(8):
            text = LONG_WORD if (n == 3 and k == 2) else WORDS[(n * 3 + k) % len(WORDS)]
            ws = s0 + k * per
            words.append({"i": len(words), "text": text, "start_ms": ws, "end_ms": min(ws + per - 20, s1), "scene": n})
        cut = s0 + int(dur * 0.43)
        shots = []
        for k, (a, b) in enumerate(((s0, cut), (cut, s1)), 1):
            sid = f"s{n}c{k}"
            shot = {"id": sid, "start_ms": a, "end_ms": b, "type": "medium",
                    "image": {"chosen": "img/c1.png", "composite": None},
                    "motion": {"model_id": "mm_001", "duration_ms": b - a, "clip": f"clips/{'a' if k == 1 else 'b'}.mp4",
                               "lipsync": False}}
            if with_fallback and sid == "s2c2":
                shot["motion"] = None                      # بدون تحريك معتمد ← صورة ثابتة
            shots.append(shot)
        scenes.append({"n": n, "start_ms": s0, "end_ms": s1, "word_range": [first, len(words) - 1],
                       "emotion": "calm", "shots": shots})
        t = s1
    return {"schema": 1, "script_id": "VP-testp-1-v1",
            "voice": {"audio": "voice/s1/full.wav", "duration_ms": t},
            "words": words, "scenes": scenes, "ambience": None, "captions": None}


@pytest.fixture(scope="module")
def base_assets(tmp_path_factory):
    """ملفات الوسائط الحقيقية الصغيرة، تنعمل مرة وحدة للموديول."""
    d = tmp_path_factory.mktemp("assets")
    (d / "voice").mkdir()
    (d / "clips").mkdir()
    (d / "img").mkdir()
    (d / "ahat").mkdir()
    ff("-f", "lavfi", "-i", f"sine=frequency=440:duration={TOTAL / 1000:.3f}:sample_rate=8000", d / "voice" / "full.wav")
    for n, col in (("a", "blue"), ("b", "red")):
        ff("-f", "lavfi", "-i", f"color=c={col}:s=64x114:d=1:r=10", "-pix_fmt", "yuv420p", d / "clips" / f"{n}.mp4")
    ff("-f", "lavfi", "-i", "color=c=green:s=64x114:d=1", "-frames:v", "1", d / "img" / "c1.png")
    ff("-f", "lavfi", "-i", "sine=frequency=220:duration=3", d / "ahat" / "audio.wav")
    return d


class Lib:
    def __init__(self, root: Path, assets: Path):
        self.root = root
        self.lib = root / "library"
        self.products = root / "products"
        self.stem = "s1"
        tdir = self.lib / "timelines" / "s1"
        (tdir).mkdir(parents=True)
        (self.lib / "voice" / "s1").mkdir(parents=True)
        (self.lib / "scripts").mkdir(parents=True)
        self.products.mkdir()
        shutil.copy2(assets / "voice" / "full.wav", self.lib / "voice" / "s1" / "full.wav")
        shutil.copytree(assets / "clips", tdir / "clips")
        shutil.copytree(assets / "img", tdir / "img")
        self.ahat_audio = assets / "ahat" / "audio.wav"
        self.tl = _make_timeline()
        self.write_tl()
        self.brief(**{})
        self.script = self.lib / "scripts" / "s1.json"
        self.script.write_text(json.dumps({"_meta": {"script_id": "VP-testp-1-v1", "product_file": "testp.json",
                                                       "product": "TESTP"}}, ensure_ascii=False), encoding="utf-8")

    def write_tl(self):
        (self.lib / "timelines" / "s1" / "timeline.json").write_text(
            json.dumps(self.tl, ensure_ascii=False), encoding="utf-8")

    def brief(self, replace=None, **over):
        b = dict(_DEFAULT_BRIEF) if replace is None else replace
        b.update(over)
        (self.products / "testp.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")

    def add_ahat(self, approved=True, tid="ah_001"):
        d = self.lib / "ahat" / tid
        d.mkdir(parents=True)
        shutil.copy2(self.ahat_audio, d / "audio.wav")
        (d / "track.json").write_text(json.dumps({"id": tid, "audio": "audio.wav", "approved": approved}), encoding="utf-8")
        self.tl["ambience"] = {"track_id": tid, "approved": True, "duck_db": -14}
        self.write_tl()

    def job(self):
        return build_job(self.script, self.lib, self.products)


@pytest.fixture
def L(tmp_path, base_assets):
    return Lib(tmp_path, base_assets)


# ───────────────────────── القطع والمدة ─────────────────────────
def test_cuts_sum_equals_audio_duration_exactly(L):
    job = L.job()
    cuts = job["cuts"]
    assert len(cuts) == 14
    assert sum(c["duration_ms"] for c in cuts) == job["duration_ms"] == TOTAL        # فارق صفر
    assert abs(probe_s(L.lib / "voice" / "s1" / "full.wav") * 1000 - TOTAL) <= 2     # ومدة ملف الصوت الحقيقي نفسها
    assert not [w for w in job["report"]["warnings"] if "مدة ملف الصوت" in w]
    cursor = 0
    for c in cuts:                                                                      # متصلة بلا فجوات
        assert c["start_ms"] == cursor and c["duration_ms"] == c["end_ms"] - c["start_ms"] > 0
        cursor = c["end_ms"]
    f = 0
    for c in cuts:                                                                      # الإطارات متصلة وبلا فجوة ولا تداخل
        assert c["start_frame"] == f and c["end_frame"] > c["start_frame"]
        f = c["end_frame"]
    assert f == job["total_frames"] == frame_of(TOTAL)
    assert (job["width"], job["height"], job["fps"], job["version"]) == (1080, 1920, 30, 1)


def test_output_named_by_script_id_ascii_only(L):
    job = L.job()
    assert job["output"]["path"] == "library/exports/VP-testp-1-v1.mp4"
    assert job["output"]["w"] == 1080 and job["output"]["h"] == 1920 and job["output"]["fps"] == 30
    assert re.fullmatch(r"[A-Za-z0-9_.-]+", safe_name("VP/../عربي x")) and "/" not in safe_name("VP/../عربي x")
    assert safe_name("") == "video" and safe_name("...") == "video" and not safe_name("..a").startswith(".")
    L.tl["script_id"] = "VP/../سيناريو 1"
    L.write_tl()
    out = L.job()["output"]["path"]
    assert re.fullmatch(r"library/exports/[A-Za-z0-9_.-]+\.mp4", out)
    assert "/" not in out[len("library/exports/"):]


def test_broken_timeline_is_rejected(L):
    L.tl["scenes"][2]["shots"][0]["end_ms"] += 5                       # فجوة/تداخل
    L.write_tl()
    with pytest.raises(JobError):
        L.job()
    L.tl = _make_timeline()
    L.tl["voice"]["duration_ms"] += 1                                  # المجموع ≠ مدة الصوت
    L.write_tl()
    with pytest.raises(JobError) as e:
        L.job()
    assert "مجموع" in str(e.value)
    (L.lib / "timelines" / "s1" / "timeline.json").unlink()
    with pytest.raises(JobError):
        L.job()


def test_image_fallback_when_no_approved_motion_with_warning(L):
    job = L.job()
    cut = next(c for c in job["cuts"] if c["id"] == "s2c2")
    assert cut["source"]["kind"] == "image" and cut["source"]["library_path"].endswith("img/c1.png")
    assert any("s2c2" in w and "الصورة الثابتة" in w for w in job["report"]["warnings"])
    assert all(c["source"]["kind"] == "video" for c in job["cuts"] if c["id"] != "s2c2")
    # مدة حركة غلط ← بديل بالصورة مع تحذير
    L.tl = _make_timeline(with_fallback=False)
    L.tl["scenes"][0]["shots"][0]["motion"]["duration_ms"] += 40
    L.write_tl()
    job = L.job()
    assert job["cuts"][0]["source"]["kind"] == "image" and any("s1c1" in w for w in job["report"]["warnings"])
    # لا حركة ولا صورة = خطأ
    L.tl["scenes"][0]["shots"][0]["motion"] = None
    L.tl["scenes"][0]["shots"][0]["image"] = {}
    L.write_tl()
    with pytest.raises(JobError):
        L.job()


# ───────────────────────── البطاقات ─────────────────────────
def _types(job):
    return [o["type"] for o in job["overlays"]]


def test_all_cards_present_with_full_brief_and_logical_timing(L):
    job = L.job()
    assert _types(job) == ["product", "offer", "cta"]
    p, o, c = job["overlays"]
    assert c["end_ms"] == TOTAL and c["end_ms"] - c["start_ms"] == C.CTA_MS               # آخر 3 ثواني
    assert o["end_ms"] == c["start_ms"] and p["end_ms"] <= o["start_ms"]                  # عرض ← «اطلب هلأ»، والسعر قبلهم
    for x in job["overlays"]:
        assert 0 <= x["start_ms"] < x["end_ms"] <= TOTAL and x["end_frame"] > x["start_frame"]
    assert job["overlays"][2]["content"]["text"] == "اطلب هلأ"
    assert p["content"] == {"name": "TESTP", "price": "19.9", "currency": "د.أ"}
    assert o["content"]["offer"] == "اشتري 2 والتوصيل مجاني" and o["content"]["guarantee"] == "ضمان استرجاع 7 أيام"
    assert job["report"]["dropped_overlays"] == []


@pytest.mark.parametrize("over,gone,kept", [
    ({"price": ""}, ["product"], ["offer", "cta"]),
    ({"offer": "", "guarantee": ""}, ["offer"], ["product", "cta"]),
    ({"offer": "", "no_offer": True}, [], ["product", "offer", "cta"]),             # الضمان لسا موجود ← بطاقة بالضمان بس
    ({"offer": "عرض", "no_offer": True, "guarantee": ""}, ["offer"], ["product", "cta"]),   # «لا يوجد عرض» مؤكّد
    ({"price": "", "offer": "", "guarantee": ""}, ["product", "offer"], ["cta"]),
    ({"price": "   "}, ["product"], ["offer", "cta"]),
])
def test_cards_auto_dropped_when_fields_empty(L, over, gone, kept):
    L.brief(**over)
    job = L.job()
    assert _types(job) == kept
    assert sorted(d["type"] for d in job["report"]["dropped_overlays"]) == sorted(gone)
    assert all(d["reason"] for d in job["report"]["dropped_overlays"])
    assert "cta" in _types(job)


def test_offer_card_with_only_guarantee_has_no_empty_offer_field(L):
    L.brief(offer="")
    o = next(x for x in L.job()["overlays"] if x["type"] == "offer")
    assert "offer" not in o["content"] and o["content"]["guarantee"]


def test_missing_brief_drops_price_and_offer_cards_with_warning(L):
    (L.products / "testp.json").unlink()
    job = L.job()
    assert _types(job) == ["cta"] and any("بريف" in w for w in job["report"]["warnings"])


def test_real_kama_product_has_no_offer_card_and_no_price_card(L):
    kama = ROOT / "products" / "kama.json"
    if not kama.exists():
        pytest.skip("products/kama.json مش موجود")
    shutil.copy2(kama, L.products / "kama.json")
    L.script.write_text(json.dumps({"_meta": {"script_id": "VP-kama-1-v1", "product_file": "kama.json"}}), encoding="utf-8")
    real = json.loads(kama.read_text(encoding="utf-8"))
    # اليوم: السعر والعرض والضمان فاضيين بالملف الحقيقي ← لا بطاقة سعر ولا عرض (وإذا انعبّوا لاحقاً بتظهر لحالها)
    has_offer = bool(real["offer"].strip() and not real.get("no_offer")) or bool(
        real["guarantee"].strip() and not real.get("no_guarantee"))
    has_price = bool(real["price"].strip())
    job = L.job()
    types = _types(job)
    assert ("offer" in types) == has_offer and ("product" in types) == has_price and "cta" in types
    if not (has_offer or has_price):
        assert types == ["cta"] and {d["type"] for d in job["report"]["dropped_overlays"]} == {"product", "offer"}


def test_overlays_are_static_and_inside_the_safe_zone_above_captions(L):
    job = L.job()
    sz = job["style"]["safe_zone"]
    assert sz["bottom"] == 0.22 and sz["bottom_px"] == round(1920 * 0.22)
    r = job["style"]["safe_zone"]["rect"]
    caption_top = 1920 - sz["bottom_px"] - job["style"]["caption"]["band_h"]
    for o in job["overlays"]:
        b = o["layout"]["box"]
        assert o["layout"]["static"] is True and o["layout"]["dir"] == "rtl"           # نص ثابت
        assert b["x"] >= r["x"] and b["x"] + b["w"] <= r["x"] + r["w"]
        assert b["y"] >= r["y"] and b["y"] + b["h"] <= r["y"] + r["h"] <= 1920 - sz["bottom_px"]
        assert b["y"] + b["h"] <= caption_top                                           # ما بتغطي الترجمة
    wins = sorted((o["start_ms"], o["end_ms"]) for o in job["overlays"])
    assert all(a[1] <= b[0] for a, b in zip(wins, wins[1:]))                            # البطاقات ما بتتداخل


def test_cards_on_a_short_video_stay_ordered_and_inside(L):
    # فيديو قصير: ما بيصير تداخل ولا خروج عن المدة
    from services.advanced_montage.adapter.overlays import build_overlays
    product = {"name": "X", "price": "5", "offer": "عرض", "guarantee": ""}
    scenes = [{"n": i + 1, "start_ms": i * 1500, "end_ms": (i + 1) * 1500} for i in range(7)]
    ovs, dropped = build_overlays(product, scenes, 10500)
    wins = sorted((o["start_ms"], o["end_ms"]) for o in ovs)
    assert all(0 <= a < b <= 10500 for a, b in wins) and all(a[1] <= b[0] for a, b in zip(wins, wins[1:]))
    assert [o["type"] for o in sorted(ovs, key=lambda o: o["start_ms"])] == ["product", "offer", "cta"] and not dropped


def test_card_windows_for_a_real_47_second_video():
    from services.advanced_montage.adapter.overlays import build_overlays
    starts = [0, 6000, 13000, 20000, 27000, 34000, 41000]
    scenes = [{"n": i + 1, "start_ms": a, "end_ms": (starts + [47000])[i + 1]} for i, a in enumerate(starts)]
    ovs, _ = build_overlays({"name": "X", "price": "5", "offer": "عرض", "guarantee": ""}, scenes, 47000)
    got = {o["type"]: (o["start_ms"], o["end_ms"]) for o in ovs}
    assert got == {"product": (34000, 37500), "offer": (41000, 44000), "cta": (44000, 47000)}


# ───────────────────────── الترجمة ─────────────────────────
def test_caption_lines_never_split_an_arabic_word(L):
    job = L.job()
    tl_words = [latin_digits(w["text"]) for w in L.tl["words"]]
    lines = job["captions"]
    assert [w for ln in lines for w in ln["text"].split(" ")] == tl_words                # كل كلمة كاملة وبنفس الترتيب
    assert [w["text"] for ln in lines for w in ln["words"]] == tl_words
    for ln in lines:
        assert ln["text"] == " ".join(w["text"] for w in ln["words"])
        assert len(ln["text"]) <= C.CAPTION_MAX_CHARS or len(ln["words"]) == 1          # الحد، إلا كلمة طويلة لحالها
        assert len(ln["words"]) <= C.CAPTION_MAX_WORDS
        assert ln["start_ms"] == ln["words"][0]["start_ms"] and ln["end_ms"] >= ln["words"][-1]["end_ms"]
    long_line = next(ln for ln in lines if LONG_WORD in ln["text"])
    assert long_line["text"] == LONG_WORD                                                   # الكلمة الطويلة ما انقسمت
    prev = 0
    for ln in lines:                                                                        # بلا تداخل وضمن المدة
        assert ln["start_ms"] >= prev and ln["end_ms"] <= TOTAL and ln["end_ms"] > ln["start_ms"]
        prev = ln["end_ms"]


def test_caption_grouping_respects_custom_char_limit_and_punctuation():
    words = [{"text": t, "start_ms": i * 300, "end_ms": i * 300 + 280} for i, t in
             enumerate(["قطرة", "طبيعية،", "للعين", "تريّح", "عينيك", "بسرعة"])]
    lines = build_captions(words, 2000, max_chars=10, max_words=9)
    assert [ln["text"] for ln in lines] == ["قطرة", "طبيعية،", "للعين", "تريّح", "عينيك", "بسرعة"]
    assert " ".join(ln["text"] for ln in lines).split() == [w["text"] for w in words]
    wide = build_captions(words, 2000, max_chars=40, max_words=9)
    assert wide[0]["text"] == "قطرة طبيعية،"                                              # قطع عند علامة الترقيم
    assert build_captions([], 1000) == []


# ───────────────────────── الأرقام والبيانات ─────────────────────────
_ARABIC_DIGITS = re.compile("[\u0660-\u0669\u06f0-\u06f9\u066b\u066c]")


def test_all_numbers_are_latin_everywhere_in_the_job(L):
    job = L.job()
    blob = json.dumps(job, ensure_ascii=False)
    assert not _ARABIC_DIGITS.search(blob)
    assert job["product"]["price"] == "19.9" and "2" in [w["text"] for ln in job["captions"] for w in ln["words"]]
    assert latin_digits("١٩٫٩ د.أ ٣٬٥٠٠ ۱۲") == "19.9 د.أ 3,500 12"
    assert re.fullmatch(r"[0-9]+", str(job["total_frames"]))


def test_job_has_no_keys_tokens_or_pii(L):
    L.brief(offer="اتصل 0933123456 أو راسلنا test@example.com", guarantee="ضمان 7 أيام",
            landing_page="https://secret.example/lp", ops_product_id="ops-9999")
    job = L.job()
    blob = json.dumps(job, ensure_ascii=False)
    for needle in ("ops-12345", "store-777", "lp-secret-page", "ops-9999", "0933123456", "example.com",
                   "secret.example", str(L.root), str(L.root).replace("\\", "/"), "C:\\", "Users"):
        assert needle not in blob, needle
    assert scan_job_for_leaks(job) == []
    assert not re.search(r"token|secret|api[_-]?key|passw|authorization|bearer", blob, re.I)
    assert "offer" not in next(o for o in job["overlays"] if o["type"] == "offer")["content"]       # حقل العرض المشبوه انحذف
    assert any("رقم هاتف" in w or "إيميل" in w for w in job["report"]["warnings"])
    assert set(job["product"]) == {"name", "price", "currency", "offer", "guarantee", "scarcity_deadline", "stock_units"}
    # كل المسارات نسبية
    for c in job["cuts"]:
        assert not os.path.isabs(c["source"]["library_path"]) and ":" not in c["source"]["library_path"]
    # الفحص الدفاعي بيمسك التسريب لو صار
    bad = copy.deepcopy(job)
    bad["audio"]["api_key"] = "x"
    bad["product"]["name"] = "me@mail.com"
    bad["cuts"][0]["source"]["library_path"] = "C:\\Users\\x\\a.mp4"
    assert len(scan_job_for_leaks(bad)) == 3


# ───────────────────────── الآهات ─────────────────────────
def test_ahat_included_only_if_approved_and_ducked(L):
    base = L.job()
    assert base["audio"]["ahat"] == [] and base["audio"]["duck"]["enabled"] is False and base["audio"]["music"] is None
    L.add_ahat(approved=False)
    with pytest.raises(JobError) as e:
        L.job()
    assert "معتمدة" in str(e.value)
    shutil.rmtree(L.lib / "ahat")
    L.add_ahat(approved=True)
    a = L.job()["audio"]
    assert [t["id"] for t in a["ahat"]] == ["ah_001"] and a["duck"]["enabled"] and a["duck"]["gain_db"] == -14.0
    assert a["ahat"][0]["end_ms"] == TOTAL and a["ahat"][0]["loop"] and a["loudnorm"] == {"I": -16, "TP": -1.5, "LRA": 11}
    L.tl["ambience"]["track_id"] = "../evil"
    L.write_tl()
    with pytest.raises(JobError):
        L.job()


# ───────────────────────── منع الخروج من المكتبة ─────────────────────────
@pytest.mark.parametrize("bad", ["../../outside.mp4", "/etc/passwd.mp4", "C:/Windows/x.mp4", "clips\\..\\..\\x.mp4",
                                 "clips/../../../outside.mp4"])
def test_path_traversal_in_timeline_clip_is_rejected(L, bad):
    (L.root / "outside.mp4").write_bytes(b"x" * 100)
    L.tl["scenes"][0]["shots"][0]["motion"]["clip"] = bad
    L.write_tl()
    with pytest.raises(JobError) as e:
        L.job()
    assert "مرفوض" in str(e.value)


def test_path_traversal_in_voice_image_and_ahat_is_rejected(L):
    (L.root / "outside.wav").write_bytes(b"x" * 100)
    L.tl["voice"]["audio"] = "../outside.wav"
    L.write_tl()
    with pytest.raises(JobError):
        L.job()
    L.tl = _make_timeline()
    L.tl["scenes"][1]["shots"][1]["motion"] = None
    L.tl["scenes"][1]["shots"][1]["image"] = {"chosen": "../../../outside.png"}
    L.write_tl()
    with pytest.raises(JobError):
        L.job()
    L.tl = _make_timeline()
    L.add_ahat()
    (L.lib / "ahat" / "ah_001" / "track.json").write_text(
        json.dumps({"audio": "../../../outside.wav", "approved": True}), encoding="utf-8")
    with pytest.raises(JobError):
        L.job()


def test_symlink_escaping_the_library_is_rejected(L, tmp_path):
    outside = tmp_path / "outside.mp4"
    shutil.copy2(L.lib / "timelines" / "s1" / "clips" / "a.mp4", outside)
    link = L.lib / "timelines" / "s1" / "clips" / "evil.mp4"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("ويندوز ما سمح بإنشاء رابط رمزي بدون صلاحية")
    L.tl["scenes"][0]["shots"][0]["motion"]["clip"] = "clips/evil.mp4"
    L.write_tl()
    with pytest.raises(JobError):
        L.job()


@pytest.mark.parametrize("bad", ["../outside.mp4", "/abs/x.mp4", "C:/x.mp4", "a\\b.mp4", "timelines/../../x.mp4", "", None])
def test_stage_media_rejects_tampered_job_paths(L, tmp_path, bad):
    job = L.job()
    job["cuts"][3]["source"]["library_path"] = bad
    wd = tmp_path / "wd_bad"
    with pytest.raises(StageError):
        stage_media(job, L.lib, wd)
    assert not (wd / "media").exists() or not any((wd / "media").iterdir())             # ما انكتب شي قبل التحقق


def test_stage_media_rejects_bad_extension_and_output_outside_exports(L, tmp_path):
    job = L.job()
    (L.lib / "voice" / "s1" / "x.exe").write_bytes(b"x" * 10)
    job["audio"]["voice"]["library_path"] = "voice/s1/x.exe"
    with pytest.raises(StageError):
        stage_media(job, L.lib, tmp_path / "w1")
    job = L.job()
    job["output"]["library_rel"] = "../evil.mp4"
    with pytest.raises(StageError):
        stage_media(job, L.lib, tmp_path / "w2")
    job["output"]["library_rel"] = "voice/s1/full.wav"                                  # داخل المكتبة بس مش تحت exports
    with pytest.raises(StageError):
        stage_media(job, L.lib, tmp_path / "w3")
    with pytest.raises(StageError):
        stage_media(L.job(), L.lib, tmp_path / "w4", mode="weird")


# ───────────────────────── تجهيز الوسائط ─────────────────────────
def test_stage_media_uses_safe_ascii_names_and_relative_paths(L, tmp_path):
    arabic = L.lib / "timelines" / "s1" / "img" / "صورة اللقطة.png"                       # اسم عربي بالمكتبة
    shutil.copy2(L.lib / "timelines" / "s1" / "img" / "c1.png", arabic)
    L.tl["scenes"][1]["shots"][1]["image"] = {"chosen": "img/صورة اللقطة.png"}      # s2c2 (بلا تحريك)
    for k in (0, 1):                                                                    # s4c1 وs4c2 بنفس الصورة
        L.tl["scenes"][3]["shots"][k]["motion"] = None
    L.add_ahat()
    job = L.job()
    wd = tmp_path / "work"
    staged = stage_media(job, L.lib, wd)
    files = sorted(p.name for p in (wd / "media").iterdir())
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+", n) for n in files)
    assert "voice.wav" in files and "ahat_01.wav" in files and "cut_001.mp4" in files
    srcs = [c["source"]["src"] for c in staged["cuts"]] + [staged["audio"]["voice"]["src"], staged["audio"]["ahat"][0]["src"]]
    for s in srcs:
        assert re.fullmatch(r"media/[A-Za-z0-9_.-]+", s) and (wd / s).is_file()
    by_id = {c["id"]: c["source"] for c in staged["cuts"]}
    assert by_id["s2c2"]["kind"] == "image" and by_id["s2c2"]["src"].endswith(".png")
    assert by_id["s4c1"]["src"] == by_id["s4c2"]["src"]                               # نفس الصورة بلقطتين = ملف واحد
    assert by_id["s1c1"]["src"] != by_id["s1c2"]["src"]
    assert job["cuts"][0]["source"]["src"] is None                                      # الأصل ما تغيّر
    assert not scan_job_for_leaks(staged)
    # إعادة التجهيز على نفس المجلد بتشتغل
    assert stage_media(job, L.lib, wd, mode="copy")["audio"]["voice"]["src"] == "media/voice.wav"
    f = tmp_path / "a_file"
    f.write_text("x")
    with pytest.raises(StageError):
        stage_media(job, L.lib, f)


# ───────────────────────── التحقق من الناتج ─────────────────────────
@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    d = tmp_path_factory.mktemp("vids")
    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p"]

    def make(name, size="1080x1920", rate=30, dur=3, audio=True, src="testsrc2"):
        args = ["-f", "lavfi", "-i", f"{src}=size={size}:rate={rate}:duration={dur}"]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-c:a", "aac", "-shortest"]
        ff(*args, *enc, d / name)
        return d / name

    return {"good": make("good.mp4"), "small": make("small.mp4", size="540x960"),
            "long": make("long.mp4", dur=5), "silent": make("silent.mp4", audio=False),
            "fps25": make("fps25.mp4", rate=25), "tiny": make("tiny.mp4", size="1080x1920", src="color")}


JOBX = {"version": 1, "duration_ms": 3000, "output": {"w": 1080, "h": 1920, "fps": 30}}


def test_verify_accepts_a_correct_video(videos):
    assert verify_output(videos["good"], JOBX) == []


def test_verify_catches_wrong_size_duration_audio_fps_and_tiny_file(videos):
    e = verify_output(videos["small"], JOBX)
    assert len(e) >= 1 and any("540x960" in m and "1080x1920" in m for m in e)
    e = verify_output(videos["long"], JOBX)
    assert any("مدة الفيديو" in m for m in e) and not any("حجم الفيديو" in m for m in e)
    assert any("بلا مسار صوت" in m for m in verify_output(videos["silent"], JOBX))
    assert any("الإطارات" in m for m in verify_output(videos["fps25"], JOBX))
    tiny = verify_output(videos["tiny"], JOBX)
    assert any("صغير" in m for m in tiny)
    assert verify_output(videos["good"], JOBX, min_bytes=10 ** 9)                      # الحد الأدنى قابل للضبط
    assert verify_output(videos["good"], dict(JOBX, duration_ms=3030)) == []           # ضمن ±40ms
    assert any("مدة الفيديو" in m for m in verify_output(videos["good"], dict(JOBX, duration_ms=3085)))
    assert verify_output(videos["good"].with_name("nope.mp4"), JOBX) == ["ملف الفيديو مش موجود"]
    junk = videos["good"].with_name("junk.mp4")
    junk.write_bytes(b"not a video" * 100)
    assert "فيديو صالح" in verify_output(junk, JOBX)[0]


# ───────────────────────── الرندر والـ CLI ─────────────────────────
def test_only_remotion_is_registered_and_unknown_engines_give_clear_arabic_error(L, tmp_path):
    job = L.job()
    assert render_mod.available_renderers() == ["remotion"]
    with pytest.raises(RendererUnavailable) as e:
        render_mod.render(job, tmp_path / "w", renderer="ffmpeg")
    assert "المحرّك المتقدّم غير مثبّت بعد" in str(e.value)
    with pytest.raises(RendererUnavailable) as e2:
        render_mod.render(job, tmp_path / "w", renderer="nonexistent")
    assert "مش معروف" in str(e2.value) and "remotion" in str(e2.value)


def test_renderer_registry_passes_options_and_checks_job_version(L, tmp_path):
    job = L.job()
    called = {}
    original = render_mod.RENDERERS["remotion"]

    def fake(j, wd, **opts):
        called["ok"] = (j["script_id"], wd, opts)
        return wd / "out.mp4"

    render_mod.register_renderer("remotion", fake)
    try:
        assert render_mod.render(job, tmp_path / "w", library_dir="LIB") == tmp_path / "w" / "out.mp4"
        assert called["ok"][0] == "VP-testp-1-v1" and called["ok"][2] == {"library_dir": "LIB"}
        with pytest.raises(RendererUnavailable):
            render_mod.render(dict(job, version=99), tmp_path / "w")
    finally:
        render_mod.register_renderer("remotion", original)
    assert render_mod.available_renderers() == ["remotion"]


def test_constants_match_current_montage_py():
    import montage
    assert (C.WIDTH, C.HEIGHT) == montage.FINAL_SIZE and C.FPS == montage.FPS
    assert C.SAFE_BOTTOM == montage.SAFE_BOTTOM and C.SAFE_SIDE == montage.SAFE_SIDE
    cmd = montage.build_command([Path("a.mp4")], Path("v.mp3"), Path("ah.wav"), Path("o.mp4"), (108, 192), 10.0, True)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert f"loudnorm=I={C.LOUDNORM['I']}:TP={C.LOUDNORM['TP']}:LRA={C.LOUDNORM['LRA']}" in graph
    assert f"threshold={C.DUCK_THRESHOLD}:ratio={C.DUCK_RATIO}:attack={C.DUCK_ATTACK_MS}:release={C.DUCK_RELEASE_MS}" in graph
    assert f"volume={round(10 ** (C.DUCK_DB / 20), 3)}" in graph
    assert C.AHAT_FADE_OUT_S == 1.5 and "afade=t=out" in graph


def _cli(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "services.advanced_montage", *map(str, args)], cwd=str(ROOT),
                       capture_output=True, env=env)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def test_cli_prepare_writes_job_and_prints_arabic_summary(L, videos):
    L.brief(price="", offer="", guarantee="")
    code, out, err = _cli("prepare", L.script, "--library", L.lib, "--products", L.products)
    assert code == 0, err
    jf = L.lib / "exports" / "s1_adv" / "job.json"
    assert jf.exists()
    job = json.loads(jf.read_text(encoding="utf-8"))
    assert job["version"] == 1 and len(job["cuts"]) == 14 and _types(job) == ["cta"]
    assert "اللقطات: 14" in out and "بطاقة محذوفة (بطاقة المنتج والسعر)" in out and "بطاقة محذوفة (بطاقة العرض)" in out
    assert "صورة ثابتة" in out and "الكلمات" in out and "كتبنا" in out and out.startswith(summarize(job).splitlines()[0])
    # verify من الـ CLI
    good = dict(job, duration_ms=3000)
    jp = L.root / "job3.json"
    jp.write_text(json.dumps(good), encoding="utf-8")
    assert _cli("verify", videos["good"], jp)[0] == 0
    code, out, _ = _cli("verify", videos["small"], jp)
    assert code == 1 and "540x960" in out
    code, _, err = _cli("prepare", L.root / "nope.json", "--library", L.lib, "--products", L.products)
    assert code != 0 and "[!]" in err
    # --stage
    code, out, err = _cli("prepare", L.script, "--library", L.lib, "--products", L.products, "--stage",
                          "--out", L.root / "outdir")
    assert code == 0, err
    assert (L.root / "outdir" / "work" / "media" / "voice.wav").exists()
    staged = json.loads((L.root / "outdir" / "job.json").read_text(encoding="utf-8"))
    assert staged["audio"]["voice"]["src"] == "media/voice.wav"


# ═════════════════════════ محرّك Remotion: عقد props (بلا Node) ═════════════════════════
import threading  # noqa: E402
import time  # noqa: E402

from services.advanced_montage.adapter.audio_mix import build_audio_mix, build_mix_command  # noqa: E402
from services.advanced_montage.adapter.text import redact_paths  # noqa: E402
from services.advanced_montage.errors import RenderError  # noqa: E402
from services.advanced_montage.renderers import remotion_engine as eng  # noqa: E402

TS_SRC = ROOT / "services" / "advanced_montage" / "remotion" / "src"


def _ts_text() -> dict:
    return {p.relative_to(TS_SRC).as_posix(): p.read_text(encoding="utf-8") for p in TS_SRC.rglob("*.ts*")}


def test_remotion_project_files_are_pinned_and_local():
    rd = eng.REMOTION_DIR
    pkg = json.loads((rd / "package.json").read_text(encoding="utf-8"))
    deps = {**pkg["dependencies"], **pkg.get("devDependencies", {})}
    assert set(deps) == {"remotion", "@remotion/cli", "@remotion/renderer", "@remotion/bundler", "react", "react-dom",
                         "@types/react", "typescript"}
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in deps.values()), "كل الإصدارات لازم تكون مثبّتة بالضبط"
    assert deps["remotion"].startswith("4.") and len({deps[k] for k in deps if k.startswith(("remotion", "@remotion"))}) == 1
    assert (rd / "package-lock.json").is_file()
    assert "ignore-scripts=true" in (rd / ".npmrc").read_text(encoding="utf-8")
    fonts = sorted(p.name for p in (rd / "fonts").glob("*.woff2"))
    assert len(fonts) == 8 and all(n.startswith("ibm-plex-sans-arabic-") for n in fonts)


def test_remotion_composition_matches_job_contract():
    t = _ts_text()
    root = t["Root.tsx"]
    assert 'id="AdVertical"' in root and "WIDTH = 1080" in root and "HEIGHT = 1920" in root and "FPS = 30" in root
    assert "calculateMetadata" in root and "total_frames" in root
    keys = ("cuts", "captions", "overlays", "audio", "product", "style")
    assert all(k in t["lib/types.ts"] for k in keys)
    job_keys = set(L_job_keys())
    assert {"cuts", "captions", "overlays", "audio", "product", "style", "total_frames", "duration_ms", "output"} <= job_keys


def L_job_keys():
    # مفاتيح الـ job اللي بيبنيها build_job (من مصدر الدالة، بدون مكتبة) — حماية من انحراف العقد
    src = (ROOT / "services" / "advanced_montage" / "adapter" / "build_job.py").read_text(encoding="utf-8")
    return re.findall(r'"([a-z_]+)":', src[src.index("job = {"):src.index("leaks =")])


def test_arabic_safety_rules_in_remotion_sources():
    t = _ts_text()
    for name, src in t.items():
        # ممنوع تقطيع النص حرف حرف (بيكسر وصل الحروف) وممنوع أي letterSpacing غير صفر
        assert not re.search(r"split\(\s*(''|\"\")\s*\)", src), f"{name}: split حرف حرف"
        assert not re.search(r"\[\s*\.\.\.\s*(?:text|name|word|line)\b", src), f"{name}: نشر نص لحروف"
        for m in re.finditer(r"letterSpacing\s*:\s*([^,}\n]+)", src):
            assert m.group(1).strip() in ("0", "'0'", "0px", "'normal'"), f"{name}: letterSpacing غير صفر"
    caps = t["components/ArabicCaptions.tsx"]
    assert "ARABIC_TEXT_STYLE" in caps and "unicodeBidi: 'isolate'" in caps
    brand = t["lib/brand.ts"]
    assert "direction: 'rtl'" in brand and "letterSpacing: 0" in brand and "IBM Plex Sans Arabic" in brand
    assert "#f5c542" in brand and "#120a2a" in brand
    assert "caption.bottom_px" in caps                                                   # الترجمة فوق المنطقة الآمنة
    # الخطوط محلية: ما في أي رابط خارجي بكود الواجهة
    assert not [n for n, s in t.items() if re.search(r"https?://", s)]


def _staged(L, tmp_path, ahat=False):
    if ahat:
        L.add_ahat()
    job = L.job()
    wd = tmp_path / "wd"
    return stage_media(job, L.lib, wd), wd


def test_prepare_workdir_builds_props_media_fonts_and_mix(L, tmp_path):
    job = L.job()
    wd = tmp_path / "work"
    staged, props = eng.prepare_workdir(job, wd, L.lib)
    p = json.loads(props.read_text(encoding="utf-8"))
    assert p["audio"]["mixed"] == {"src": "media/mix.wav", "duration_ms": TOTAL, "rate": 48000}
    assert (wd / "media" / "mix.wav").is_file() and len(list((wd / "fonts").glob("*.woff2"))) == 8
    for c in p["cuts"]:
        assert re.fullmatch(r"media/[A-Za-z0-9_.-]+", c["source"]["src"]) and (wd / c["source"]["src"]).is_file()
    assert p["cuts"][0]["start_frame"] == 0 and p["cuts"][-1]["end_frame"] == p["total_frames"]
    blob = json.dumps(p, ensure_ascii=False)
    assert scan_job_for_leaks(p) == [] and str(L.root) not in blob and not _ARABIC_DIGITS.search(blob)
    assert job["cuts"][0]["source"]["src"] is None                                         # الأصل ما تغيّر
    # إعادة التجهيز على مجلد جاهز بتشتغل بدون مكتبة
    staged2, _ = eng.prepare_workdir(staged, wd)
    assert staged2["audio"]["mixed"]["src"] == "media/mix.wav"
    with pytest.raises(RenderError):
        eng.prepare_workdir(job, tmp_path / "w2")                                           # مش مجهّز وبلا مكتبة


# ───────────────────────── audio_mix ─────────────────────────
def test_mix_command_uses_the_same_chain_as_montage_py(L, tmp_path):
    staged, wd = _staged(L, tmp_path, ahat=True)
    cmd = build_mix_command(staged, wd, wd / "media" / "mix.wav")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "sidechaincompress=threshold=0.02:ratio=12:attack=20:release=400" in graph
    assert "volume=0.2" in graph and "afade=t=in:d=1" in graph and "afade=t=out:st=" in graph
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in graph and "amix=inputs=2:duration=first:normalize=0" in graph
    assert "aloop=loop=-1" in graph and cmd[0] == "ffmpeg" and "shell" not in " ".join(cmd)
    staged["audio"]["ahat"] = []
    plain = build_mix_command(staged, wd, wd / "media" / "mix.wav")
    g2 = plain[plain.index("-filter_complex") + 1]
    assert "sidechaincompress" not in g2 and "loudnorm=I=-16" in g2


@pytest.mark.parametrize("with_ahat", [False, True])
def test_audio_mix_makes_48k_wav_with_exact_duration(L, tmp_path, with_ahat):
    staged, wd = _staged(L, tmp_path, ahat=with_ahat)
    out = build_audio_mix(staged, wd)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,codec_name:format=duration",
                        "-of", "json", str(out)], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    assert d["streams"][0]["sample_rate"] == "48000" and d["streams"][0]["codec_name"] == "pcm_s16le"
    assert abs(float(d["format"]["duration"]) * 1000 - TOTAL) <= C.DURATION_TOLERANCE_MS
    assert out.name == "mix.wav" and out.parent == wd / "media"


def test_audio_mix_pads_short_voice_to_job_duration_and_ducks_ahat(L, tmp_path):
    staged, wd = _staged(L, tmp_path, ahat=True)
    staged["duration_ms"] = TOTAL + 600                                      # الصوت أقصر من الـ job بـ 600ms
    staged["audio"]["ahat"][0]["end_ms"] = TOTAL + 600
    out = build_audio_mix(staged, wd)
    assert abs(probe_s(out) * 1000 - (TOTAL + 600)) <= C.DURATION_TOLERANCE_MS


def test_audio_mix_errors_are_arabic_and_hide_paths(L, tmp_path):
    staged, wd = _staged(L, tmp_path)
    (wd / "media" / "voice.wav").write_bytes(b"not audio at all" * 100)       # ملف تالف
    with pytest.raises(RenderError) as e:
        build_audio_mix(staged, wd)
    assert "فشل دمج الصوت" in str(e.value) and str(tmp_path) not in str(e.value)
    staged["audio"]["voice"]["src"] = "../evil.wav"
    with pytest.raises(RenderError):
        build_mix_command(staged, wd, wd / "x.wav")
    staged["audio"]["voice"]["src"] = None
    with pytest.raises(RenderError):
        build_mix_command(staged, wd, wd / "x.wav")


# ───────────────────────── أوامر وأخطاء المحرّك (بلا Node) ─────────────────────────
def test_build_command_passes_each_value_as_separate_argument_and_never_downloads_a_browser(tmp_path):
    odd = tmp_path / "مجلد فيه فراغ & رمز"
    cmd = eng.build_command("node", "render", odd / "out.mp4", odd / "props.json", odd, Path("C:/Chrome Dir/chrome.exe"),
                            concurrency=4)
    assert isinstance(cmd, list) and cmd[0] == "node" and cmd[2:5] == ["render", "src/index.ts", "AdVertical"]
    assert f"--props={odd / 'props.json'}" in cmd and f"--public-dir={odd}" in cmd
    assert any(a.startswith("--browser-executable=") and "chrome.exe" in a for a in cmd)
    for flag in ("--codec=h264", "--crf=18", "--pixel-format=yuv420p", "--concurrency=4", "--chrome-mode=chrome-for-testing"):
        assert flag in cmd
    assert any(a.startswith("--timeout=") for a in cmd)
    still = eng.build_command("node", "still", odd / "o.png", odd / "p.json", odd, Path("c.exe"), concurrency=1, frame=7)
    assert "--frame=7" in still and "--codec=h264" not in still
    assert 1 <= eng.default_concurrency() <= max(1, (os.cpu_count() or 2) // 2)
    assert eng.default_timeout_s(1410) >= 900


def test_render_fails_in_arabic_when_node_is_missing(L, tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "find_node", lambda: None)
    with pytest.raises(RenderError) as e:
        render_mod.render(L.job(), tmp_path / "w", library_dir=L.lib)
    assert "Node.js" in str(e.value) and "مش مثبّت" in str(e.value)
    assert not (tmp_path / "w" / "media").exists()                             # ما لمسنا القرص قبل الفحص


def test_render_fails_in_arabic_when_browser_is_missing(L, tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "find_node", lambda: "node")
    monkeypatch.setattr(eng, "node_version", lambda n: (24, 0, 0))
    monkeypatch.setattr(eng, "project_ready", lambda: (True, eng.EXPECTED_REMOTION))
    monkeypatch.setattr(eng, "find_browser", lambda: None)
    with pytest.raises(RenderError) as e:
        render_mod.render(L.job(), tmp_path / "w", library_dir=L.lib)
    assert "المتصفح" in str(e.value) and "VP_CHROME" in str(e.value)
    monkeypatch.setattr(eng, "project_ready", lambda: (False, "حزم Remotion مش منزّلة — شغّل «npm ci»"))
    with pytest.raises(RenderError) as e2:
        render_mod.render(L.job(), tmp_path / "w", library_dir=L.lib)
    assert "npm ci" in str(e2.value)
    monkeypatch.setattr(eng, "node_version", lambda n: (16, 20, 0))
    monkeypatch.setattr(eng, "project_ready", lambda: (True, eng.EXPECTED_REMOTION))
    with pytest.raises(RenderError) as e3:
        render_mod.render(L.job(), tmp_path / "w", library_dir=L.lib)
    assert "قديم" in str(e3.value)


def test_vp_chrome_env_must_point_to_a_real_file(monkeypatch, tmp_path):
    monkeypatch.setenv("VP_CHROME", str(tmp_path / "nope.exe"))
    assert eng.find_browser() is None                                          # ما بنرجع لمسار تاني بالسر
    fake = tmp_path / "chrome.exe"
    fake.write_bytes(b"x")
    monkeypatch.setenv("VP_CHROME", str(fake))
    assert eng.find_browser() == fake


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_run_remotion_failure_timeout_and_cancel_are_clean_and_arabic(tmp_path):
    out = tmp_path / "o.mp4"
    out.write_bytes(b"partial")
    with pytest.raises(RenderError) as e:
        eng.run_remotion(_py("import sys; print('boom: C:/Users/x/secret/file.mp4 failed'); sys.exit(3)"),
                         cwd=tmp_path, timeout_s=30, cancel=None, log=lambda s: None, out_file=out)
    msg = str(e.value)
    assert "فشل الرندر (رمز 3)" in msg and "boom" in msg and "Users" not in msg and "secret" not in msg
    assert not out.exists()                                                    # الناتج الناقص انحذف
    t0 = time.monotonic()
    with pytest.raises(RenderError) as e2:
        eng.run_remotion(_py("import time; time.sleep(60)"), cwd=tmp_path, timeout_s=1, cancel=None,
                         log=lambda s: None, out_file=None)
    assert "المهلة" in str(e2.value) and time.monotonic() - t0 < 20
    ev = threading.Event()
    threading.Timer(0.8, ev.set).start()
    t0 = time.monotonic()
    with pytest.raises(RenderError) as e3:
        eng.run_remotion(_py("import time; time.sleep(60)"), cwd=tmp_path, timeout_s=60, cancel=ev,
                         log=lambda s: None, out_file=None)
    assert "انلغى" in str(e3.value) and time.monotonic() - t0 < 20
    with pytest.raises(RenderError) as e4:
        eng.run_remotion([str(tmp_path / "no_such_binary_xyz")], cwd=tmp_path, timeout_s=5, cancel=None,
                         log=lambda s: None, out_file=None)
    assert "Node.js" in str(e4.value) or "المحرّك" in str(e4.value)


def test_run_remotion_logs_progress_and_writes_clean_log(tmp_path):
    lines = []
    logp = tmp_path / "render.log"
    eng.run_remotion(_py("print('Rendered 5/10'); print('Rendered 10/10'); print('hello')"), cwd=tmp_path, timeout_s=30,
                     cancel=None, log=lines.append, out_file=None, log_path=logp)
    assert any("50%" in x for x in lines) and any("100%" in x for x in lines)
    assert logp.read_text(encoding="utf-8").strip() == "hello"


def test_redact_paths_keeps_only_file_names():
    s = redact_paths(r"خطأ بـ C:\Users\LOQ\Pictures\المشروع\library\x.mp4 وكمان /home/u/proj/a.wav تمام")
    assert "Users" not in s and "LOQ" not in s and "home" not in s and "x.mp4" in s and "a.wav" in s


def test_doctor_reports_each_check_in_arabic(monkeypatch, capsys):
    from services.advanced_montage import cli
    monkeypatch.setattr(eng, "find_node", lambda: None)
    monkeypatch.setattr(eng, "find_browser", lambda: None)
    with pytest.raises(SystemExit) as e:
        cli.main(["doctor"])
    out = capsys.readouterr().out
    assert e.value.code == 1
    assert "✗ Node.js مش مثبّت" in out and "✗ ما لقينا Google Chrome" in out and "✓" in out
    checks = eng.doctor_checks()
    assert [c.key for c in checks] == ["node", "npm", "remotion", "fonts", "browser", "ffmpeg", "ffprobe"]
    monkeypatch.setattr(eng, "find_node", lambda: "node")
    monkeypatch.setattr(eng, "node_version", lambda n: (24, 1, 0))
    monkeypatch.setattr(eng, "find_browser", lambda: Path("chrome.exe"))
    monkeypatch.setattr(eng, "project_ready", lambda: (True, eng.EXPECTED_REMOTION))
    ok = {c.key: c.ok for c in eng.doctor_checks()}
    assert ok["node"] and ok["browser"] and ok["remotion"] and ok["fonts"]


def test_cli_render_stops_early_with_arabic_message_when_engine_missing(L, monkeypatch):
    from services.advanced_montage import cli
    monkeypatch.setattr(eng, "find_node", lambda: None)
    with pytest.raises(SystemExit) as e:
        cli.main(["render", str(L.script), "--library", str(L.lib), "--products", str(L.products)])
    assert "[!]" in str(e.value) and "Node.js" in str(e.value)
    assert not (L.lib / "exports").exists()                                    # ما انكتب ولا شي


# ═════════════════════════ رندر Remotion حقيقي (بيتخطّى لو Node/المتصفح/node_modules غير موجودين) ═════════════════════════
def _engine_ready() -> bool:
    try:
        node, _ = eng.ensure_ready()
        return bool(node)
    except RenderError:
        return False


needs_engine = pytest.mark.skipif(not _engine_ready(), reason="Node/المتصفح/node_modules غير جاهزين")
# الرندر الحقيقي القصير (~30 ثانية) بيشتغل تلقائي؛ لو صار أبطأ من 40 ثانية على جهاز ما، فعّل العلامة:
needs_slow = pytest.mark.skipif(os.environ.get("VP_SLOW_TESTS") != "1" and os.environ.get("VP_SKIP_SLOW_RENDER") == "1",
                                reason="رندر حقيقي بطيء على هالجهاز")


def _short_job(L, tmp_path):
    """job قصير 3.6 ثانية (108 إطار) بعربي طويل وأرقام وبطاقات الثلاث، من ملفات lavfi."""
    from services.advanced_montage.adapter.overlays import build_overlays
    total = 3600
    scenes, words, t = [], [], 0
    texts = "عينك بآخر النهار تعبانة، جرّبي قطرةَ الكُمأة الطبيعية ٢ مرات يومياً بسعر ١٩٫٩ د.أ".split()
    for n in (1, 2, 3):
        s0, s1 = t, t + 1200
        shots = []
        for k, (a, b) in enumerate(((s0, s0 + 600), (s0 + 600, s1)), 1):
            sid = f"s{n}c{k}"
            mo = {"model_id": "m", "duration_ms": b - a, "clip": f"clips/{'a' if k == 1 else 'b'}.mp4", "lipsync": False}
            shots.append({"id": sid, "start_ms": a, "end_ms": b, "type": "medium",
                          "image": {"chosen": "img/c1.png"}, "motion": None if sid == "s2c2" else mo})
        scenes.append({"n": n, "start_ms": s0, "end_ms": s1, "shots": shots})
        t = s1
    for i, w in enumerate(texts):
        ws = 100 + i * 230
        words.append({"i": i, "text": w, "start_ms": ws, "end_ms": ws + 210, "scene": 1})
    L.tl.update(scenes=scenes, words=words, ambience=None)
    L.tl["voice"]["duration_ms"] = total
    L.write_tl()
    ff("-f", "lavfi", "-i", f"sine=frequency=330:duration={total / 1000}:sample_rate=24000",
       L.lib / "voice" / "s1" / "full.wav")
    L.brief(scarcity_deadline="الجمعة", stock_units="12")
    job = L.job()
    ovs, _ = build_overlays(job["product"], [{"n": i, "start_ms": i * 4000, "end_ms": i * 4000 + 4000} for i in range(3)], 12000)
    wins = {"product": (0, 1200), "offer": (1200, 2400), "cta": (2400, 3600)}
    for o in ovs:
        a, b = wins[o["type"]]
        o.update(start_ms=a, end_ms=b, start_frame=frame_of(a), end_frame=frame_of(b))
    job["overlays"] = ovs
    return job


@needs_engine
@needs_slow
def test_real_remotion_render_short_clip_matches_spec_and_looks_right(L, tmp_path):
    from PIL import Image
    job = _short_job(L, tmp_path)
    assert [o["type"] for o in job["overlays"]] == ["product", "offer", "cta"] and job["total_frames"] == 108
    wd = tmp_path / "work"
    out = render_mod.render(job, wd, library_dir=L.lib, log=lambda s: None, timeout_s=600)
    assert out.is_file() and verify_output(out, job) == []                   # 1080x1920 · 30 · المدة ±40ms · صوت · حجم
    assert (wd / "render.log").is_file() and (wd / "props.json").is_file()
    frames = {}
    for name, sec in (("product", 0.75), ("offer", 1.9), ("cta", 3.1)):
        png = tmp_path / f"{name}.png"
        ff("-ss", sec, "-i", out, "-frames:v", 1, png)
        frames[name] = Image.open(png).convert("RGB")
    assert all(im.size == (1080, 1920) for im in frames.values())

    import numpy as np

    def arr(im, box):
        return np.asarray(im.crop(box), dtype=int)

    def gold(a):
        return int(((a[..., 0] > 200) & (a[..., 1] > 150) & (a[..., 1] < 235) & (a[..., 2] < 130)).sum())

    assert gold(arr(frames["product"], (65, 200, 1015, 1150))) > 3000                                    # الاسم والإطار الذهبي
    assert gold(arr(frames["offer"], (65, 200, 1015, 1150))) > 1500
    assert gold(arr(frames["cta"], (65, 200, 1015, 1150))) > 20000                                       # زر «اطلب هلأ»
    for name in ("product", "offer"):                                                                      # المنطقة الآمنة السفلية فاضية
        strip = arr(frames[name], (0, 1500, 1080, 1920)).reshape(-1, 3)
        assert (strip.max(axis=0) - strip.min(axis=0)).max() < 30, f"{name}: في شي مرسوم بالـ 22٪ السفلية"
    cap = arr(frames["product"], (60, 1198, 1020, 1498))                                                   # شريط الترجمة فيه نص أبيض
    assert int((cap.min(axis=2) > 235).sum()) > 800
