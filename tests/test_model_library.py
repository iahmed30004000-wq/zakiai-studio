"""مكتبة النماذج (model_library): تحقق صارم، بوابة الرخصة، الافتراضي والاختيار، القوالب، وكتابة ذرّية. بلا شبكة."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import model_library as ml  # noqa: E402
import secrets_store  # noqa: E402


@pytest.fixture
def mem():
    m, prev = secrets_store.use_memory_backend()
    yield m
    secrets_store.restore_backend(prev)


def std_image(**over):
    raw = {"name": "صور محلية", "task": "image", "link": "std", "enabled": True,
           "licence": {"id": "Apache-2.0", "commercial": "yes"},
           "caps": {"refs": False}, "params": {"width": 1024, "height": 1024},
           "std": {"url": "http://127.0.0.1:8000/v1", "model": "flux"}}
    raw.update(over)
    return raw


def cmd_voice(**over):
    raw = {"name": "صوت بأمر", "task": "voice", "link": "command", "enabled": True,
           "licence": {"id": "MIT", "commercial": "yes"},
           "command": {"argv": ["python", "speak.py", "--text", "{text}", "--out", "{out}"]}}
    raw.update(over)
    return raw


# ── الملف والأساس ─────────────────────────────────────────────────────────

def test_a_missing_file_is_a_blank_library_and_nothing_is_created(tmp_path, monkeypatch):
    monkeypatch.setenv(ml.ENV_PATH, str(tmp_path / "x" / "model_library.json"))
    d = ml.load()
    assert d["models"] == [] and d["next_id"] == 1 and set(d["tasks"]) == set(ml.TASKS)
    assert d["tasks"]["image"] == {"default": None, "fallback_builtin": True}
    for t in ml.NO_FALLBACK:                                               # الصوت والشفاه والموسيقى والمؤثرات بلا رجوع تلقائي
        assert d["tasks"][t]["fallback_builtin"] is False, t
    assert not (tmp_path / "x").exists()
    assert ml.pick("image") == ml.Pick("builtin")


def test_default_path_is_inside_library_and_env_overrides_it(tmp_path, monkeypatch):
    monkeypatch.delenv(ml.ENV_PATH, raising=False)
    import config
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "lib")
    assert ml.path() == tmp_path / "lib" / "model_library.json"
    monkeypatch.setenv(ml.ENV_PATH, str(tmp_path / "elsewhere.json"))
    assert ml.path() == tmp_path / "elsewhere.json"


def test_create_get_list_and_the_file_is_the_normal_shape():
    m = ml.create(std_image(), by="سارة")
    assert m["id"] == "ml_001" and m["task"] == "image" and m["link"] == "std" and m["std"]["url"] == "http://127.0.0.1:8000/v1"
    assert m["uses_gpu"] is False and m["timeout_sec"] == ml.DEFAULT_TIMEOUT["image"]
    assert "command" not in m and "weights" not in m and m["licence"]["commercial"] == "yes"
    assert ml.get("ml_001")["name"] == "صور محلية" and ml.get("nope") is None
    assert [x["id"] for x in ml.list_models("image")] == ["ml_001"] and ml.list_models("voice") == []
    raw = json.loads(ml.path().read_text(encoding="utf-8"))
    assert raw["version"] == 1 and raw["next_id"] == 2 and raw["models"][0]["id"] == "ml_001"
    assert [f.name for f in ml.path().parent.iterdir()] == ["model_library.json"]         # بلا ملفات مؤقتة


def test_load_returns_independent_copies_and_notices_outside_edits():
    ml.create(std_image())
    a = ml.load()
    a["models"][0]["name"] = "تخريب"
    assert ml.load()["models"][0]["name"] == "صور محلية"
    raw = json.loads(ml.path().read_text(encoding="utf-8"))
    raw["models"][0]["name"] = "عدّلها المالك بالملف"
    ml.path().write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    assert ml.load()["models"][0]["name"] == "عدّلها المالك بالملف"


def test_ids_are_never_reused_after_a_delete():
    ml.create(std_image(name="أ"))
    ml.create(std_image(name="ب"))
    assert ml.delete("ml_002") is True and ml.delete("ml_002") is False
    assert ml.create(std_image(name="ج"))["id"] == "ml_003"


@pytest.mark.parametrize("content", ["not json", "[1]", '{"version": 99}', '{"models": [{"id": "bad"}]}', '{"extra": 1}',
                                      '{"tasks": {"nope": {}}}'])
def test_a_corrupt_or_foreign_file_is_refused_and_never_overwritten(content):
    ml.path().parent.mkdir(parents=True, exist_ok=True)
    ml.path().write_text(content, encoding="utf-8")
    with pytest.raises(ml.ModelLibraryError):
        ml.load()
    with pytest.raises(ml.ModelLibraryError):
        ml.create(std_image())
    assert ml.path().read_text(encoding="utf-8") == content
    p = ml.pick("image")                                                   # الإنتاج ما بيوقف: الطريقة الحالية + سبب
    assert p.source == "builtin" and p.reason


def test_a_failed_write_keeps_the_old_file(monkeypatch):
    ml.create(std_image())
    before = ml.path().read_bytes()

    def boom(src, dst):
        raise OSError("disk full")
    with monkeypatch.context() as mp:                                      # مش monkeypatch.undo(): بيشيل كمان عزل المكتبة بـ conftest
        mp.setattr(ml.os, "replace", boom)
        with pytest.raises(ml.ModelLibraryError, match="تعذّرت كتابة"):
            ml.create(std_image(name="تاني"))
    assert ml.path().read_bytes() == before
    assert [f.name for f in ml.path().parent.iterdir()] == ["model_library.json"]


# ── التحقق الصارم ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("patch,msg", [
    ({"surprise": 1}, "حقول غير معروفة"),
    ({"id": "ml_009"}, "حقول غير معروفة"),
    ({"created_at": "x"}, "حقول غير معروفة"),
    ({"name": ""}, "اسم النموذج مطلوب"),
    ({"name": "x" * 81}, "أطول من 80"),
    ({"task": "motion"}, "التحريك بسجله الخاص"),
    ({"task": "nope"}, "المهمة"),
    ({"link": "ftp"}, "طريقة الربط"),
    ({"enabled": "yes"}, "التفعيل"),
    ({"timeout_sec": 5}, "المهلة"),
    ({"timeout_sec": 99999}, "المهلة"),
    ({"uses_gpu": "x"}, "استعمال الكرت"),
    ({"template": "Bad Name!"}, "القالب"),
    ({"caps": {"nope": True}}, "القدرات"),
    ({"caps": {"refs": "yes"}}, "صح/غلط"),
    ({"params": {"width": 10}}, "خارج المعقول"),
    ({"params": {"steps": 1.5}}, "رقم صحيح"),
    ({"params": {"negative": "x" * 2000}}, "أطول من"),
    ({"params": {"bogus": 1}}, "حقول غير معروفة"),
    ({"licence": {"commercial": "maybe"}}, "الرخصة"),
    ({"licence": {"nope": 1}}, "الرخصة: حقول غير معروفة"),
    ({"std": {"url": "http://example.com:80/v1", "model": "m"}}, "المضيف مش مسموح"),
    ({"std": {"url": "https://127.0.0.1:8000/v1", "model": "m"}}, "http://"),
    ({"std": {"url": "http://127.0.0.1:8000/v1"}}, "اسم الموديل مطلوب"),
    ({"std": {"url": "http://127.0.0.1:8000/v1", "model": "m", "extra": 1}}, "حقول غير معروفة"),
    ({"std": {"url": "http://127.0.0.1:8000/v1", "model": "m", "token_secret": "a b"}}, "اسم مفتاح التوكن"),
    ({"std": {"url": "http://127.0.0.1:8000/v1", "model": "m", "size": "big"}}, "مقاس الصورة"),
    ({"std": {"url": "http://127.0.0.1:8000/v1", "model": "m", "response_format": "gif"}}, "صيغة الرد"),
    ({"std": None}, "الواجهة القياسية"),
])
def test_strict_validation_messages(patch, msg):
    with pytest.raises(ml.ModelLibraryError, match=msg):
        ml.create(std_image(**patch))
    assert ml.load()["models"] == []


def test_link_must_serve_the_task_and_closed_links_say_so():
    with pytest.raises(ml.ModelLibraryError, match="ما بتخدم مهمة «مزامنة الشفاه»"):
        ml.create({**std_image(), "task": "lipsync"})
    for task, label in (("voice", "الصوت"), ("stt", "التفريغ"), ("lipsync", "مزامنة الشفاه"), ("bgremove", "تفريغ الخلفية")):     # الأوزان بتخدم الصور والتكبير والموسيقى والمؤثرات بس
        with pytest.raises(ml.ModelLibraryError, match=f"ما بتخدم مهمة «{label}"):
            ml.create({"name": "x", "task": task, "link": "weights", "weights": {"model": "stable-audio"}})
    with pytest.raises(ml.ModelLibraryError, match="إعدادات البرنامج: حقول غير معروفة|اسم النقطة"):         # برنامج النموذج (app) انفتح بم7: بيتحقق من كتلته
        ml.create({"name": "x", "task": "music", "link": "app", "app": {"url": "http://127.0.0.1:7860"}})


def test_weights_link_is_open_for_images_upscale_and_audio_and_checks_the_folder_name():
    m = ml.create({"name": "Qwen", "task": "image", "link": "weights", "weights": {"model": "Qwen-Image", "steps": 30}, "licence": {"id": "Apache-2.0", "commercial": "yes"}})
    assert m["weights"] == {"model": "Qwen-Image", "steps": 30, "guidance": None} and m["uses_gpu"] is False and m["enabled"] is False
    assert ml.create({"name": "up", "task": "upscale", "link": "weights", "weights": {"model": "upscale-RealESRGAN_x4plus"}})["task"] == "upscale"
    for task in ("music", "sfx"):                                                                 # t2a: Stable Audio بيخدم الموسيقى والمؤثرات
        a = ml.create({"name": f"sa {task}", "task": task, "link": "weights", "weights": {"model": "stable-audio-open-1.0"}, "caps": {"max_sec": 47}, "params": {"seconds": 20},
                       "licence": {"id": "stable-audio-community", "commercial": "conditional"}})
        assert a["task"] == task and a["uses_gpu"] is False and a["caps"] == {"max_sec": 47.0} and a["params"] == {"seconds": 20.0}
    for bad, msg in (({"model": "Qwen Image"}, "اسم مجلد النموذج"), ({"model": "../x"}, "اسم مجلد النموذج"), ({"model": ""}, "مطلوب"),
                     ({"model": "a", "steps": 999}, "خارج المعقول"), ({"model": "a", "extra": 1}, "حقول غير معروفة"), (None, "الأوزان")):
        with pytest.raises(ml.ModelLibraryError, match=msg):
            ml.create({"name": "x", "task": "image", "link": "weights", "weights": bad})
    assert len(ml.load()["models"]) == 4


def test_each_model_keeps_only_its_own_link_block_and_task_link_are_immutable():
    ml.create(std_image())
    ml.create(cmd_voice())
    assert "command" not in ml.get("ml_001") and "std" not in ml.get("ml_002")
    with pytest.raises(ml.ModelLibraryError, match="مهمة النموذج"):
        ml.update("ml_001", {"task": "voice"})
    with pytest.raises(ml.ModelLibraryError, match="طريقة الربط"):
        ml.update("ml_001", {"link": "command", "command": cmd_voice()["command"]})
    with pytest.raises(ml.ModelLibraryError, match="مش موجود"):
        ml.update("ml_404", {"name": "x"})


def test_update_patches_fields_and_keeps_the_rest():
    first = ml.create(std_image(), by="أ")
    u = ml.update("ml_001", {"name": "اسم جديد", "params": {"steps": 20}})
    assert u["name"] == "اسم جديد" and u["params"] == {"steps": 20} and u["std"] == first["std"] and u["created_at"] == first["created_at"]
    u = ml.update("ml_001", {"std": {"url": "http://localhost:9000/v1/", "model": "m2"}})
    assert u["std"]["url"] == "http://localhost:9000/v1" and u["std"]["model"] == "m2" and u["name"] == "اسم جديد"
    assert ml.update("ml_001", {"params": {"steps": ""}})["params"] == {}                 # فاضي = بيشيل القيمة


def test_numbers_may_arrive_as_strings_from_forms_but_not_booleans():
    m = ml.create(std_image(params={"width": "512", "height": "768", "guidance": "3.5"}))
    assert m["params"] == {"width": 512, "height": 768, "guidance": 3.5}
    with pytest.raises(ml.ModelLibraryError, match="رقم"):
        ml.create(std_image(params={"width": True}))


# ── أمر التشغيل ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd,msg", [
    ({"argv": []}, "قائمة وسائط"),
    ({"argv": "python x.py"}, "قائمة وسائط"),
    ({"argv": ["python", 5]}, "قائمة وسائط"),
    ({"argv": ["{text}", "--out", "{out}"]}, "اسم البرنامج نفسه"),
    ({"argv": ["python", "s.py", "--text", "{text}"]}, "{out}"),
    ({"argv": ["python", "s.py", "--out", "{out}"]}, "{text}"),
    ({"argv": ["python", "s.py", "{text}", "{out}", "{secret}"]}, "غير معروفة"),
    ({"argv": ["python", "s.py", "{text}", "{out}"], "env": {"API_KEY": "x"}}, "اسم غير مسموح"),
    ({"argv": ["python", "s.py", "{text}", "{out}"], "env": {"lower": "x"}}, "اسم غير مسموح"),
    ({"argv": ["python", "s.py", "{text}", "{out}"], "env": {f"V{i}": "x" for i in range(11)}}, "لحد 10"),
    ({"argv": ["python", "s.py", "{text}", "{out}"], "output_glob": "../*.wav"}, "بلا مسارات"),
    ({"argv": ["python", "s.py", "{text}", "{out}"], "bogus": 1}, "حقول غير معروفة"),
])
def test_command_validation(cmd, msg):
    with pytest.raises(ml.ModelLibraryError, match=msg):
        ml.create(cmd_voice(command=cmd))


def test_command_accepts_out_dir_text_file_env_and_cwd():
    m = ml.create(cmd_voice(command={"argv": ["bash", "run.sh", "{text_file}", "{out_dir}"], "cwd": "/srv/tts", "output_glob": "*.wav", "env": {"CUDA_VISIBLE_DEVICES": "0"}}))
    assert m["command"]["cwd"] == "/srv/tts" and m["command"]["env"] == {"CUDA_VISIBLE_DEVICES": "0"} and m["uses_gpu"] is True
    lip = ml.create({"name": "شفاه", "task": "lipsync", "link": "command", "licence": {"commercial": "yes"},
                     "command": {"argv": ["python", "l.py", "{video}", "{audio}", "{out}"]}})
    assert lip["task"] == "lipsync"
    with pytest.raises(ml.ModelLibraryError, match="{audio}"):
        ml.create({"name": "شفاه", "task": "lipsync", "link": "command", "command": {"argv": ["python", "l.py", "{video}", "{out}"]}})


# ── الرخصة ────────────────────────────────────────────────────────────────

def test_a_no_licence_can_be_saved_but_never_enabled():
    m = ml.create(std_image(enabled=False, licence={"id": "NC", "commercial": "no"}))
    assert ml.usable(m) == (False, "معطّل")
    with pytest.raises(ml.ModelLibraryError, match="بتمنع الاستخدام التجاري"):
        ml.update(m["id"], {"enabled": True})
    with pytest.raises(ml.ModelLibraryError, match="بتمنع الاستخدام التجاري"):
        ml.create(std_image(licence={"id": "NC", "commercial": "no"}))
    with pytest.raises(ml.ModelLibraryError, match="بتمنع"):
        ml.update(m["id"], {"enabled": True, "licence": {"confirmed_by_owner": True}})   # التأكيد ما بيفتح «ممنوع»


@pytest.mark.parametrize("com", ["conditional", "unknown"])
def test_uncertain_licences_need_the_owners_confirmation_stamped_by_the_server(com):
    with pytest.raises(ml.ModelLibraryError, match="محتاجة مراجعتك"):
        ml.create(std_image(licence={"id": "X", "commercial": com}))
    m = ml.create(std_image(licence={"id": "X", "commercial": com, "confirmed_by_owner": True, "confirmed_by": "مزوّر", "confirmed_at": "2000-01-01"}), by="أحمد")
    lic = m["licence"]
    assert lic["confirmed_by_owner"] is True and lic["confirmed_by"] == "أحمد" and lic["confirmed_at"] != "2000-01-01"
    stamp = lic["confirmed_at"]
    m2 = ml.update(m["id"], {"name": "تعديل ثاني"}, by="غيره")
    assert m2["licence"]["confirmed_by"] == "أحمد" and m2["licence"]["confirmed_at"] == stamp   # الختم بيضل
    off = ml.update(m["id"], {"enabled": False, "licence": {"confirmed_by_owner": False}})
    assert "confirmed_at" not in off["licence"] and "confirmed_by" not in off["licence"]
    with pytest.raises(ml.ModelLibraryError, match="محتاجة مراجعتك"):
        ml.update(m["id"], {"enabled": True})


def test_the_owners_confirmation_does_not_survive_a_different_licence():
    m = ml.create(std_image(licence={"id": "Custom", "commercial": "conditional", "confirmed_by_owner": True}), by="سارة")
    assert m["licence"]["confirmed_by_owner"] is True and m["licence"]["confirmed_by"] == "سارة" and ml.usable(m)[0] is True
    kept = ml.update(m["id"], {"name": "اسم جديد"}, by="خالد")                                  # تعديل غير الرخصة: التأكيد والختم بيضلوا
    assert kept["licence"]["confirmed_by_owner"] is True and kept["licence"]["confirmed_by"] == "سارة"
    same = ml.update(m["id"], {"licence": {"id": "Custom", "commercial": "conditional", "confirmed_by_owner": True}}, by="خالد")
    assert same["licence"]["confirmed_by"] == "سارة"                                            # نفس الرخصة: الختم القديم
    with pytest.raises(ml.ModelLibraryError, match="محتاجة مراجعتك"):                          # المفعّل ما بيتحوّل لرخصة غير مراجَعة (كان بيعدّي بتأكيد الرخصة القديمة)
        ml.update(m["id"], {"licence": {"id": "CC-BY-NC", "commercial": "unknown"}}, by="خالد")
    assert ml.get(m["id"])["licence"]["id"] == "Custom"                                         # والرفض ما غيّر شي
    swapped = ml.update(m["id"], {"enabled": False, "licence": {"id": "CC-BY-NC", "commercial": "unknown"}}, by="خالد")    # معطّل: بيتحفظ بلا تأكيد
    assert swapped["licence"]["confirmed_by_owner"] is False and "confirmed_by" not in swapped["licence"] and "confirmed_at" not in swapped["licence"]
    assert ml.licence_gate(swapped)[0] is False and "محتاجة مراجعتك" in ml.licence_gate(swapped)[1]
    again = ml.update(m["id"], {"licence": {"id": "Other", "commercial": "conditional", "confirmed_by_owner": True}}, by="خالد")   # تأكيد جديد صريح ← ختم جديد
    assert again["licence"]["confirmed_by_owner"] is True and again["licence"]["confirmed_by"] == "خالد"
    cls = ml.update(m["id"], {"licence": {"commercial": "unknown"}}, by="رنا")                 # نفس الاسم بتصنيف تجاري تاني: برضو بلا تأكيد
    assert cls["licence"]["confirmed_by_owner"] is False


def test_token_secret_names_are_limited_to_the_model_library_namespace():
    for bad in ("crm_token", "backup_key", "settings.IMAGE.api_key", "modellib.token", "modellib..token", "modellib.a b.token", "engine_ltx", "modellib." + "x" * 50 + ".token"):
        with pytest.raises(ml.ModelLibraryError, match="modellib"):
            ml.create(std_image(std={"url": "http://127.0.0.1:8000/v1", "model": "m", "token_secret": bad}))
        with pytest.raises(ml.ModelLibraryError, match="modellib"):
            ml.set_box("http://127.0.0.1:8100", bad)
    ok = ml.create(std_image(std={"url": "http://127.0.0.1:8000/v1", "model": "m", "token_secret": "modellib.ml_007.token"}))
    assert ok["std"]["token_secret"] == "modellib.ml_007.token"
    assert ml.set_box("http://127.0.0.1:8100", "modellib.box.token")["token_secret"] == "modellib.box.token"
    assert ml.set_box("http://127.0.0.1:8100", None)["token_secret"] is None


def test_licence_gate_and_usable_helpers():
    assert ml.licence_gate({"licence": {"commercial": "yes"}}) == (True, "")
    assert ml.licence_gate({"licence": {"commercial": "no", "id": "NC"}})[0] is False
    assert ml.licence_gate({"licence": {"commercial": "unknown"}})[0] is False
    assert ml.licence_gate({"licence": {"commercial": "unknown", "confirmed_by_owner": True}}) == (True, "")
    assert ml.usable({"enabled": False, "licence": {"commercial": "yes"}}) == (False, "معطّل")


# ── الافتراضي والاختيار ───────────────────────────────────────────────────

def test_set_default_needs_an_enabled_usable_model_of_the_same_task():
    a = ml.create(std_image())
    v = ml.create(cmd_voice())
    off = ml.create(std_image(name="معطّل", enabled=False))
    with pytest.raises(ml.ModelLibraryError, match="لهالمهمة"):
        ml.set_default("image", v["id"])
    with pytest.raises(ml.ModelLibraryError, match="معطّل"):
        ml.set_default("image", off["id"])
    with pytest.raises(ml.ModelLibraryError, match="لهالمهمة"):
        ml.set_default("image", "ml_404")
    assert ml.set_default("image", a["id"]) == {"default": a["id"], "fallback_builtin": True}
    assert ml.set_default("image", None)["default"] is None
    with pytest.raises(ml.ModelLibraryError, match="مهمة غير معروفة"):
        ml.set_default("nope", None)


def test_fallback_to_the_builtin_method_is_only_for_tasks_where_switching_is_safe():
    v = ml.create(cmd_voice())
    ml.set_default("voice", v["id"])
    with pytest.raises(ml.ModelLibraryError, match="ما بيرجع للطريقة الحالية"):
        ml.set_default("voice", v["id"], fallback_builtin=True)
    a = ml.create(std_image())
    assert ml.set_default("image", a["id"], fallback_builtin=False)["fallback_builtin"] is False
    with pytest.raises(ml.ModelLibraryError, match="صح/غلط"):
        ml.set_default("image", a["id"], fallback_builtin="yes")
    raw = json.loads(ml.path().read_text(encoding="utf-8"))
    raw["tasks"]["voice"]["fallback_builtin"] = True                       # حتى لو الملف انعدّل يدوياً: بيضل ممنوع
    ml.path().write_text(json.dumps(raw), encoding="utf-8")
    assert ml.load()["tasks"]["voice"]["fallback_builtin"] is False
    assert ml.pick("voice").fallback_builtin is False


def test_deleting_the_default_clears_it_and_removes_its_token(mem):
    m = ml.create(std_image())
    ml.set_default("image", m["id"])
    secrets_store.set_secret(ml.token_secret_name(m["id"]), "tok-FAKE-1234567890")
    assert ml.delete(m["id"]) is True
    assert ml.load()["tasks"]["image"]["default"] is None
    assert secrets_store.get_secret(ml.token_secret_name(m["id"])) is None


def test_pick_precedence_lib_then_explicit_then_default_then_builtin():
    a = ml.create(std_image(name="أ"))
    b = ml.create(std_image(name="ب"))
    ml.set_default("image", a["id"])
    d = ml.pick("image")
    assert (d.source, d.model["id"], d.fallback_builtin, d.reason) == ("default", a["id"], True, "")
    lib = ml.pick("image", f"lib:{b['id']}")
    assert (lib.source, lib.model["id"], lib.fallback_builtin) == ("lib", b["id"], False)       # اختيار صريح: ما في تبديل بصمت
    ex = ml.pick("image", "openai")
    assert ex == ml.Pick("explicit") and ex.model is None                                         # مزوّد صريح بالنداء بيغلب افتراضي المكتبة
    assert ml.pick("voice").source == "builtin"
    assert ml.pick("image", "  ").source == "default"


def test_pick_with_a_bad_explicit_library_choice_fails_loudly():
    a = ml.create(std_image())
    v = ml.create(cmd_voice())
    off = ml.create(std_image(name="معطّل", enabled=False))
    for bad in ("lib:ml_404", f"lib:{v['id']}"):
        with pytest.raises(ml.ModelLibraryError, match="مش موجود"):
            ml.pick("image", bad)
    with pytest.raises(ml.ModelLibraryError, match="معطّل"):
        ml.pick("image", f"lib:{off['id']}")
    assert ml.pick("image", f"lib:{a['id']}").source == "lib"


def test_a_default_that_became_unusable_falls_back_to_the_builtin_with_a_reason():
    m = ml.create(std_image())
    ml.set_default("image", m["id"])
    ml.update(m["id"], {"enabled": False})
    p = ml.pick("image")
    assert p.source == "builtin" and "اتخطّى" in p.reason and "معطّل" in p.reason
    raw = json.loads(ml.path().read_text(encoding="utf-8"))
    raw["models"][0]["enabled"] = True
    raw["models"][0]["licence"] = {"id": "NC", "commercial": "no", "confirmed_by_owner": False, "note": ""}
    ml.path().write_text(json.dumps(raw), encoding="utf-8")                # رخصة اتغيّرت بعد التفعيل: بوابة وقت الاستعمال
    p = ml.pick("image")
    assert p.source == "builtin" and "بتمنع الاستخدام التجاري" in p.reason
    raw["tasks"]["image"]["default"] = "ml_999"
    ml.path().write_text(json.dumps(raw), encoding="utf-8")
    assert ml.pick("image").reason == "افتراضي المكتبة انحذف"


def test_motion_default_pins_a_model_from_the_motion_registry(monkeypatch):
    import motion
    monkeypatch.setattr(motion, "load_models", lambda: [{"id": "mm_001", "enabled": True}, {"id": "mm_002", "enabled": False}])
    assert ml.set_default("motion", "mm_001")["default"] == "mm_001"
    for bad in ("mm_002", "mm_404"):
        with pytest.raises(ml.ModelLibraryError, match="مش موجود أو معطّل"):
            ml.set_default("motion", bad)
    assert ml.task_config("motion")["default"] == "mm_001"
    with pytest.raises(ml.ModelLibraryError, match="التحريك"):
        ml.list_models("motion")


# ── صندوق الأوزان ─────────────────────────────────────────────────────────

def test_box_url_goes_through_net_allow():
    assert ml.set_box("http://engine:8100/", "modellib.box.token") == {"url": "http://engine:8100", "token_secret": "modellib.box.token"}
    assert ml.load()["box"]["url"] == "http://engine:8100"
    for bad in ("http://example.com:8100", "http://engine:8100/v1", "https://engine:8100", "http://engine"):
        with pytest.raises(ml.ModelLibraryError):
            ml.set_box(bad)
    with pytest.raises(ml.ModelLibraryError, match="اسم مفتاح التوكن"):
        ml.set_box("http://engine:8100", "bad name!")
    assert ml.set_box("", None) == {"url": None, "token_secret": None}


# ── العرض للواجهة ────────────────────────────────────────────────────────

def test_public_shape_has_no_secret_and_reports_token_and_usability(mem):
    m = ml.create(std_image(std={"url": "http://127.0.0.1:8000/v1", "model": "m", "token_secret": "modellib.ml_001.token"}))
    pub = ml.public(m)
    assert pub["usable"] is True and pub["unusable_reason"] == "" and pub["token_set"] is False and pub["licence_label"] == "تجارية ✓"
    secrets_store.set_secret("modellib.ml_001.token", "tok-FAKE-abcdefghijkl")
    pub = ml.public(m)
    assert pub["token_set"] is True and "tok-FAKE" not in json.dumps(pub, ensure_ascii=False)
    plain = ml.public(ml.create(cmd_voice(enabled=False)))
    assert plain["token_set"] is None and plain["usable"] is False and plain["unusable_reason"] == "معطّل"


# ── القوالب ───────────────────────────────────────────────────────────────

def test_templates_file_is_valid_and_has_the_planned_models():
    ts = {t["id"]: t for t in ml.templates()}
    assert len(ts) >= 20
    assert ts["latentsync"]["licence"]["commercial"] == "no" and ts["ltx-video"]["licence"]["commercial"] == "conditional"
    for good in ("qwen-image", "qwen-image-edit", "flux-schnell", "real-esrgan", "wan22-ti2v-5b", "chatterbox-voice", "speaches-stt", "ace-step", "wan22-s2v"):
        assert ts[good]["licence"]["commercial"] == "yes", good
    assert ts["chatterbox-voice"]["badges"]["arabic"] is True and ts["speaches-stt"]["badges"]["arabic"] is True
    assert ml.template("qwen-image")["task"] == "image" and ml.template("nope") is None
    for t in ts.values():                                                  # شارات وشرح لكل قالب
        assert t["name"] and t["summary"] and t["howto"] and t["licence"]["note"], t["id"]


def test_every_open_template_makes_a_valid_model_once_the_user_fills_the_blanks():
    made = 0
    for t in ml.templates():
        if t["task"] not in ml.LIBRARY_TASKS or t["link"] not in ml.OPEN_LINKS:
            continue
        d = json.loads(json.dumps(t["defaults"]))
        raw = {"name": t["name"], "task": t["task"], "link": t["link"], "template": t["id"], "licence": {**t["licence"]}, **d, "enabled": False}
        if t["link"] == "std":
            raw["std"] = {**raw["std"], "url": t.get("example_url") or "http://127.0.0.1:8000/v1", "model": raw["std"].get("model") or "some-model"}
        if t["link"] == "app":                                                       # الرابط والنقطة وربط المعاملات بيعبّيهم المعالج من «اقرا البرنامج»
            raw["app"] = {"url": t.get("example_url") or "http://127.0.0.1:7860", "api_name": "/run",
                          "inputs": [{"param": "video", "from": "video"}, {"param": "audio", "from": "audio"}] if t["task"] == "lipsync" else [{"param": "prompt", "from": "prompt"}]}
        m = ml.create(raw)
        assert m["template"] == t["id"] and m["licence"]["commercial"] == t["licence"]["commercial"]
        if t["link"] == "weights":
            assert m["uses_gpu"] is False and m["weights"]["model"]              # الصندوق بيمسك قفل الكرت بنفسه
        made += 1
    assert made >= 12


def test_closed_link_templates_are_still_valid_records_for_when_their_phase_opens():
    assert set(ml.OPEN_LINKS) == set(ml.LINKS)                      # كل الطرق الأربع انفتحت: ما بقي قوالب لطريقة مسكّرة
    for t in ml.templates():
        if t["task"] not in ml.LIBRARY_TASKS or t["link"] in ml.OPEN_LINKS:
            continue
        raw = {"name": t["name"], "task": t["task"], "link": t["link"], "licence": {**t["licence"]}, **json.loads(json.dumps(t["defaults"]))}
        clean = ml._clean_model(raw, None, partial_ok=True)
        assert clean["task"] == t["task"] and clean["link"] == t["link"], t["id"]
