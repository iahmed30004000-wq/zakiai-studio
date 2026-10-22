"""فحص ثبات وجه الشخصية (facecheck): منطق المقارنة بمحرّك مزيّف + دخان بالمحرّك الحقيقي لو الموديلات موجودة."""

import os
import shutil
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
import test_studio_characters_shots as tc  # noqa: E402

import config  # noqa: E402
import facecheck as fc  # noqa: E402

RED, GREEN, WHITE = (255, 0, 0), (0, 255, 0), (255, 255, 255)
RED2 = (255, 14, 0)                                   # نفس «الهوية» بتغيّر بسيط


def img(path, color, size=(96, 96)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "PNG")
    return path


class Fake:
    """الصورة لون مسطّح = هوية الوجه (الأبيض = بلا وجه). عرض الوجه = عرض الصورة. بنحسب كم مرة انعمل embed."""

    def __init__(self):
        self.ref_cache = {}
        self.embeds = 0

    def faces(self, im):
        if tuple(int(v) for v in im[0, 0]) == (255, 255, 255):
            return []
        return [{"box": (0, 0, im.shape[1], im.shape[0]), "score": 0.9, "tag": "main"}]

    def embed(self, im, face):
        self.embeds += 1
        v = np.array(im[0, 0], dtype=float)           # BGR
        return v / np.linalg.norm(v)

    def cosine(self, a, b):
        return float(np.dot(a, b))


@pytest.fixture
def work(tmp_path):
    return tmp_path


# ───────────────────────── مقارنة الصور ─────────────────────────
def test_same_identity_passes_and_reports_the_raw_number(work):
    r = fc.check_image([img(work / "ref.png", RED)], img(work / "a.png", RED2), engine=Fake())
    assert r["status"] == "pass" and r["similarity"] > 0.99 and r["threshold"] == 0.363
    assert r["ref"] == "ref" and r["faces"] == 1 and r["face_px"] == 96
    assert "مطابق" in r["note"] and "0.36" in r["note"]


def test_a_different_identity_fails_with_an_arabic_reason(work):
    r = fc.check_image([img(work / "ref.png", RED)], img(work / "a.png", GREEN), engine=Fake())
    assert r["status"] == "fail" and r["similarity"] == 0.0
    assert "الوجه تغيّر" in r["note"] and "0.36" in r["note"]


def test_the_best_reference_wins_so_a_three_quarter_shot_matches_its_own_view(work):
    refs = [img(work / "front.png", GREEN), img(work / "three_quarter.png", RED)]
    r = fc.check_image(refs, img(work / "a.png", RED2), engine=Fake())
    assert r["status"] == "pass" and r["ref"] == "three_quarter"


def test_the_threshold_is_a_config_knob_and_bad_values_fall_back(work, monkeypatch):
    refs, shot = [img(work / "r.png", (255, 120, 0))], img(work / "a.png", (255, 0, 0))
    e = Fake()
    sim = fc.check_image(refs, shot, engine=e)["similarity"]
    assert 0.5 < sim < 0.99
    monkeypatch.setattr(config, "FACE_MATCH_THRESHOLD", 0.95)
    assert fc.check_image(refs, shot, engine=e)["status"] == "fail"
    for bad in ("x", None, 5, -1, 0.0):
        monkeypatch.setattr(config, "FACE_MATCH_THRESHOLD", bad)
        assert fc.threshold() == fc.DEFAULT_THRESHOLD


def test_no_face_in_the_shot_is_not_a_failure(work):
    r = fc.check_image([img(work / "r.png", RED)], img(work / "a.png", WHITE), engine=Fake())
    assert r["status"] == "no_face" and r["similarity"] is None and "ما انكشف وجه" in r["note"]


def test_a_face_smaller_than_the_minimum_is_not_judged(work, monkeypatch):
    ref = img(work / "r.png", RED, (96, 96))
    assert fc.check_image([ref], img(work / "small.png", RED, (30, 30)), engine=Fake())["status"] == "no_face"
    assert fc.check_image([ref], img(work / "ok.png", RED, (41, 41)), engine=Fake())["status"] == "pass"
    monkeypatch.setattr(config, "FACE_MIN_PX", 20)
    assert fc.check_image([ref], img(work / "small.png", RED, (30, 30)), engine=Fake())["status"] == "pass"


def test_no_usable_reference_says_so_and_names_the_skipped_files(work):
    r = fc.check_image([img(work / "blank.png", WHITE), work / "missing.png"], img(work / "a.png", RED), engine=Fake())
    assert r["status"] == "no_ref" and r["similarity"] is None and "blank" in r["note"] and "missing" in r["note"]
    assert fc.check_image([], img(work / "a.png", RED), engine=Fake())["status"] == "no_ref"
    assert fc.check_image(None, img(work / "a.png", RED), engine=Fake())["status"] == "no_ref"


def test_a_corrupt_reference_is_skipped_but_the_good_one_still_works(work):
    bad = work / "bad.png"
    bad.write_bytes(b"not an image at all")
    r = fc.check_image([bad, img(work / "good.png", RED)], img(work / "a.png", RED2), engine=Fake())
    assert r["status"] == "pass" and r["ref"] == "good"


def test_the_character_may_share_the_shot_with_other_faces(work):
    class Crowd(Fake):
        def faces(self, im):
            base = super().faces(im)
            return base + [{"box": (5, 5, 80, 80), "score": .8, "tag": "extra"}] if base else base

        def embed(self, im, face):
            self.embeds += 1
            v = np.array([0, 255, 0] if face.get("tag") == "extra" else im[0, 0], dtype=float)
            return v / np.linalg.norm(v)

    r = fc.check_image([img(work / "r.png", RED)], img(work / "a.png", RED2), engine=Crowd())
    assert r["status"] == "pass" and r["faces"] == 2


def test_the_largest_face_of_a_reference_is_the_one_used(work):
    class TwoFaces(Fake):
        tags = []

        def faces(self, im):
            return [{"box": (0, 0, 50, 50), "score": .9, "tag": "small"}, {"box": (0, 0, 90, 90), "score": .9, "tag": "big"}]

        def embed(self, im, face):
            self.tags.append(face["tag"])
            return np.array([1.0])

    e = TwoFaces()
    embs, skipped = fc._ref_embeddings(e, [img(work / "r.png", RED)])
    assert e.tags == ["big"] and len(embs) == 1 and skipped == []


def test_reference_embeddings_are_cached_until_the_file_changes(work):
    e = Fake()
    ref, shot = img(work / "r.png", RED), img(work / "a.png", RED2)
    fc.check_image([ref], shot, engine=e)
    n1 = e.embeds                                         # مرجع + وجه اللقطة
    fc.check_image([ref], shot, engine=e)
    assert e.embeds == n1 + 1                             # وجه اللقطة بس
    img(work / "r.png", GREEN, (100, 100))                # المرجع تغيّر → بيتحسب من جديد
    assert fc.check_image([ref], shot, engine=e)["status"] == "fail"


def test_an_arabic_folder_name_is_fine(work):
    d = work / "ورقة الشخصية"
    r = fc.check_image([img(d / "أمام.png", RED)], img(d / "لقطة.png", RED2), engine=Fake())
    assert r["status"] == "pass" and r["ref"] == "أمام"


def test_unreadable_or_missing_shots_raise_an_arabic_error(work):
    ref = img(work / "r.png", RED)
    with pytest.raises(fc.FaceCheckError, match="غير موجود"):
        fc.check_image([ref], work / "nope.png", engine=Fake())
    junk = work / "junk.png"
    junk.write_bytes(b"\x00\x01\x02")
    with pytest.raises(fc.FaceCheckError, match="تعذّر قراءة"):
        fc.check_image([ref], junk, engine=Fake())


def test_status_values_are_a_closed_set(work):
    seen = {fc.check_image([img(work / "r.png", RED)], img(work / f"{n}.png", c), engine=Fake())["status"]
            for n, c in (("p", RED2), ("f", GREEN), ("n", WHITE))}
    seen.add(fc.check_image([], img(work / "p.png", RED), engine=Fake())["status"])
    assert seen == set(fc.STATUSES)


# ───────────────────────── مقارنة الفيديو ─────────────────────────
def frames_grab(*colors):
    """grab يرجّع لقطة بلون كل ما انطلب (بالترتيب)، والوقت المطلوب بينحفظ."""
    asked = []

    def grab(video, t):
        asked.append(t)
        c = colors[len(asked) - 1]
        return None if c is None else np.full((96, 96, 3), c[::-1], dtype=np.uint8)

    grab.asked = asked
    return grab


def vid(work, **kw):
    return dict(engine=Fake(), duration=10.0, **kw)


def test_video_passes_when_every_sampled_frame_matches(work):
    g = frames_grab(RED, RED2, RED)
    r = fc.check_video([img(work / "r.png", RED)], work / "v.mp4", grab=g, **vid(work))
    assert r["status"] == "pass" and len(r["frames"]) == 3 and all(f["status"] == "pass" for f in r["frames"])
    assert g.asked == [1.667, 5.0, 8.333]                 # ثلاث لقطات موزّعة بالتساوي


def test_video_fails_when_the_face_drifts_even_only_at_the_end(work):
    r = fc.check_video([img(work / "r.png", RED)], work / "v.mp4", grab=frames_grab(RED, RED2, GREEN), **vid(work))
    assert r["status"] == "fail" and r["similarity"] == 0.0
    assert [f["status"] for f in r["frames"]] == ["pass", "pass", "fail"] and "83٪" in r["note"]


def test_video_frames_without_a_face_are_ignored_but_reported(work):
    r = fc.check_video([img(work / "r.png", RED)], work / "v.mp4", grab=frames_grab(WHITE, RED, RED2), **vid(work))
    assert r["status"] == "pass" and r["frames"][0]["status"] == "no_face" and "2 من 3" in r["note"]


def test_video_with_no_face_anywhere_is_no_face(work):
    r = fc.check_video([img(work / "r.png", RED)], work / "v.mp4", grab=frames_grab(WHITE, WHITE, WHITE), **vid(work))
    assert r["status"] == "no_face" and r["similarity"] is None


def test_video_with_no_usable_reference_is_no_ref(work):
    r = fc.check_video([], work / "v.mp4", grab=frames_grab(RED, RED, RED), **vid(work))
    assert r["status"] == "no_ref" and r["frames"] == []


def test_video_frame_count_follows_the_knob_and_the_argument(work, monkeypatch):
    g = frames_grab(RED, RED, RED, RED, RED)
    r = fc.check_video([img(work / "r.png", RED)], work / "v.mp4", grab=g, frames=5, **vid(work))
    assert len(r["frames"]) == 5
    monkeypatch.setattr(config, "FACE_VIDEO_FRAMES", 2)
    assert fc.video_frames() == 2
    monkeypatch.setattr(config, "FACE_VIDEO_FRAMES", 99)
    assert fc.video_frames() == fc.DEFAULT_FRAMES


def test_a_video_that_cannot_be_read_raises(work):
    with pytest.raises(fc.FaceCheckError, match="أي لقطة"):
        fc.check_video([img(work / "r.png", RED)], work / "v.mp4", grab=frames_grab(None, None, None), **vid(work))
    with pytest.raises(fc.FaceCheckError, match="مدة"):
        fc.check_video([img(work / "r.png", RED)], work / "v.mp4", grab=frames_grab(RED), engine=Fake(), duration=0)


def test_one_unreadable_frame_does_not_sink_the_rest(work):
    r = fc.check_video([img(work / "r.png", RED)], work / "v.mp4", grab=frames_grab(None, RED, RED2), **vid(work))
    assert r["status"] == "pass" and r["frames"][0]["status"] == "unreadable"


def test_without_ffmpeg_or_the_file_it_says_so(work, monkeypatch):
    ref = img(work / "r.png", RED)
    with pytest.raises(fc.FaceCheckError, match="غير موجود"):
        fc.check_video([ref], work / "none.mp4", engine=Fake())
    here = work / "here.mp4"
    here.write_bytes(b"x")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(fc.FaceCheckError, match="ffmpeg"):
        fc.check_video([ref], here, engine=Fake())


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg مش موجود")
def test_real_ffmpeg_reads_frames_and_duration_from_an_arabic_path(work):
    import subprocess
    d = work / "فيديوهات"
    d.mkdir()
    v = d / "تجربة.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=96x96:d=2:r=10", "-pix_fmt", "yuv420p",
                    str(v)], check=True, timeout=60)
    assert 1.5 < fc._duration(v) < 2.5
    f = fc._grab_frame(v, 1.0)
    assert f is not None and f.shape == (96, 96, 3) and f[48, 48, 2] > 200 and f[48, 48, 0] < 60     # أحمر (BGR)
    assert fc._grab_frame(d / "nope.mp4", 1.0) is None
    r = fc.check_video([img(work / "r.png", RED)], v, engine=Fake())
    assert r["status"] == "pass" and len(r["frames"]) == 3


# ───────────────────────── التجهيز والموديلات ─────────────────────────
def test_non_ascii_model_paths_are_copied_once_to_an_ascii_folder(work, monkeypatch):
    import tempfile
    src = work / "نماذج" / "m.onnx"
    src.parent.mkdir()
    src.write_bytes(b"onnx-bytes")
    safe = work / "ascii_tmp"
    safe.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(safe))
    p = fc._loadable(src)
    assert p.isascii() and open(p, "rb").read() == b"onnx-bytes" and str(safe) in p
    m = os.stat(p).st_mtime_ns
    assert fc._loadable(src) == p and os.stat(p).st_mtime_ns == m          # ما بيتنسخ مرتين
    ascii_src = safe / "x.onnx"
    ascii_src.write_bytes(b"1")
    assert fc._loadable(ascii_src) == str(ascii_src)


def test_missing_or_tampered_models_give_an_arabic_error_not_a_crash(work, monkeypatch):
    monkeypatch.setattr(fc, "DETECTOR", work / "none.onnx")
    assert fc.available() is False
    with pytest.raises(fc.FaceCheckError, match="غير منزّلة"):
        fc.CvEngine()
    bad = work / "d.onnx"
    bad.write_bytes(b"truncated download")
    monkeypatch.setattr(fc, "DETECTOR", bad)
    monkeypatch.setitem(fc.SHA256, "d.onnx", "0" * 64)
    with pytest.raises(fc.FaceCheckError, match="تالف"):
        fc.CvEngine()


def test_character_refs_are_the_face_views_that_ship_with_generation(env):
    ch = tc.mk(env, name="ريم")
    names = [p.stem for p in fc.character_refs(ch["id"])]
    assert names == ["front", "three_quarter"]
    bare = tc.mk(env, name="لينا", ready=False)
    assert fc.character_refs(bare["id"]) == []


def test_the_cli_prints_json_and_reports_errors(work, monkeypatch, capsys):
    monkeypatch.setattr(fc, "check_image", lambda refs, t: {"status": "pass", "similarity": 0.9, "refs": list(refs)})
    monkeypatch.setattr(sys, "argv", ["facecheck.py", str(work / "a.png"), "--ref", str(work / "r.png")])
    fc.main()
    assert '"status": "pass"' in capsys.readouterr().out
    monkeypatch.setattr(fc, "check_image", lambda refs, t: (_ for _ in ()).throw(fc.FaceCheckError("بلا موديل")))
    with pytest.raises(SystemExit) as e:
        fc.main()
    assert "بلا موديل" in str(e.value)


# ───────────────────────── المحرّك الحقيقي (بيتخطّى لو الموديلات أو مصدر الصورة مش موجودين) ─────────────────────────
@pytest.mark.skipif(not fc.available(), reason="موديلات الوجه مش منزّلة")
def test_real_engine_matches_the_same_person_and_ignores_blank_images(work):
    skimage_data = pytest.importorskip("skimage.data")
    face = Image.fromarray(skimage_data.astronaut())                      # صورة بالملكية العامة (ناسا)
    d = work / "حقيقي"
    d.mkdir()
    face.save(d / "ref.png")
    face.transpose(Image.FLIP_LEFT_RIGHT).save(d / "flip.png")
    canvas = Image.new("RGB", (1080, 1920), (90, 90, 90))
    canvas.paste(face.resize((900, 900)), (90, 500))
    canvas.save(d / "portrait.png")
    Image.new("RGB", (800, 800), (200, 200, 200)).save(d / "blank.png")
    for name in ("flip.png", "portrait.png"):
        r = fc.check_image([d / "ref.png"], d / name)
        assert r["status"] == "pass" and r["similarity"] > 0.8, (name, r)
    assert fc.check_image([d / "ref.png"], d / "blank.png")["status"] == "no_face"
    assert fc.check_image([d / "blank.png"], d / "ref.png")["status"] == "no_ref"
