"""
مكتبة النماذج — «زي كونفي» بلا تعقيده: لكل مهمة نموذج بتربطه إنت، وبتخلّيه الافتراضي، والنظام بيستعمله بمكانه.

المهام التسع: الصور · التحريك · الصوت · التفريغ · مزامنة الشفاه · التكبير · تفريغ الخلفية · الموسيقى · المؤثرات.
طرق الربط الأربع: أوزان على السيرفر (weights) · برنامج نموذج Gradio (app) · سيرفر بواجهة OpenAI (std) · أمر تشغيل (command).
«الطريقة الحالية» (ElevenLabs، UnoRouter، Whisper المحلي…) بتضل موجودة كاحتياط للمهام اللي بيسمح تغيير نموذجها بنص الشغلة
(الصور، التفريغ، التكبير، تفريغ الخلفية). الصوت ومزامنة الشفاه والموسيقى والمؤثرات بلا احتياط: تغيّر الصوت بنص الفيديو بيخرّبه.

الملف: library/model_library.json (أو VP_MODEL_LIBRARY). كتابة ذرّية، وتحقق صارم: أي مفتاح غريب بيترفض.
التوكنات ما بتنكتب هون أبداً: الملف فيه بس «اسم التوكن» (token_secret)، والقيمة بمخزن الأسرار (secrets_store).

الرخصة بوابة، مش معلومة: «no» ما بيتفعّل أبداً، و«conditional/unknown» بدهم تأكيد المالك بنفسه قبل التفعيل.

التحريك: واجهة فوق motion_models.json (بلا ترحيل). بالمكتبة بس «الافتراضي المثبّت» (tasks.motion.default = mm_NNN).
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import config
import net_allow

VERSION = 1
ENV_PATH = "VP_MODEL_LIBRARY"
LIB_PREFIX = "lib:"

TASKS = ("image", "motion", "voice", "stt", "lipsync", "upscale", "bgremove", "music", "sfx")
LIBRARY_TASKS = tuple(t for t in TASKS if t != "motion")             # المخزّن بهالملف؛ التحريك بسجله الخاص
TASK_LABELS = {"image": "الصور", "motion": "التحريك", "voice": "الصوت", "stt": "التفريغ (كلام لنص)", "lipsync": "مزامنة الشفاه",
               "upscale": "التكبير", "bgremove": "تفريغ الخلفية", "music": "الموسيقى", "sfx": "المؤثرات"}
LINKS = ("weights", "app", "std", "command")
LINK_LABELS = {"weights": "أوزان على السيرفر", "app": "برنامج نموذج (Gradio)", "std": "سيرفر بواجهة OpenAI", "command": "أمر تشغيل"}
OPEN_LINKS = ("weights", "app", "std", "command")                      # الطرق اللي بتشتغل بهالنسخة
NO_FALLBACK = ("voice", "lipsync", "music", "sfx", "motion")           # ما في رجوع تلقائي للطريقة الحالية (أو ما في طريقة حالية أصلاً)
LINK_TASKS = {                                                         # أي طريقة بتخدم أي مهمة
    "std": ("image", "voice", "stt"),
    "weights": ("image", "upscale", "music", "sfx"),                   # الموسيقى والمؤثرات = t2a (Stable Audio)؛ التحريك بسجله الخاص
    "app": LIBRARY_TASKS,
    "command": LIBRARY_TASKS,
}
DEFAULT_TIMEOUT = {"image": 300, "voice": 300, "stt": 600, "lipsync": 1800, "upscale": 600, "bgremove": 300, "music": 600, "sfx": 300}
COMMERCIAL = ("yes", "conditional", "unknown", "no")
COMMERCIAL_LABELS = {"yes": "تجارية ✓", "conditional": "⚠ راجع الشروط", "unknown": "⚠ غير معروفة", "no": "✗ ممنوعة تجارياً"}

# قدرات النموذج حسب المهمة (القيم: "bool" أو (نوع، أدنى، أعلى)). غير هاد = خطأ.
CAPS = {
    "image": {"refs": "bool", "edit": "bool"},
    "voice": {"arabic": "bool", "word_timing": "bool", "clone": "bool"},
    "stt": {"arabic": "bool", "word_timing": "bool"},
    "lipsync": {},
    "upscale": {"scale_max": ("int", 2, 8)},
    "bgremove": {"alpha": "bool"},
    "music": {"max_sec": ("float", 1, 600)},
    "sfx": {"max_sec": ("float", 0.5, 120)},
}
# المعاملات الافتراضية للنداء حسب المهمة
PARAMS = {
    "image": {"width": ("int", 256, 4096), "height": ("int", 256, 4096), "steps": ("int", 1, 200), "guidance": ("float", 0, 30),
              "negative": ("str", 1900), "seed": ("int", 0, 2 ** 31 - 1)},
    "voice": {"voice": ("str", 80), "speed": ("float", 0.5, 2.0), "language": ("str", 12), "instructions": ("str", 300)},
    "stt": {"language": ("str", 12)},
    "lipsync": {},
    "upscale": {"scale": ("int", 2, 8)},
    "bgremove": {},
    "music": {"seconds": ("float", 1, 300), "style": ("str", 200)},
    "sfx": {"seconds": ("float", 0.5, 60)},
}
MODEL_KEYS = {"name", "task", "link", "enabled", "template", "licence", "caps", "params", "uses_gpu", "timeout_sec", "note",
              "weights", "app", "std", "command"}
LICENCE_KEYS = {"id", "commercial", "confirmed_by_owner", "confirmed_at", "confirmed_by", "note"}
STD_KEYS = {"url", "model", "token_secret", "response_format", "size"}
APP_KEYS = {"url", "api_name", "inputs", "output", "schema_hash"}
APP_SOURCES = ("prompt", "negative", "text", "image", "refs", "audio", "video", "seconds", "width", "height", "language", "voice", "scale", "seed", "steps")   # = link_app.SOURCES
APP_API_RX = re.compile(r"/?[A-Za-z0-9_\-]{1,80}")
APP_PARAM_RX = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}")
WEIGHTS_KEYS = {"model", "steps", "guidance"}
CMD_KEYS = {"argv", "cwd", "output_glob", "env"}
PLACEHOLDERS = ("prompt", "prompt_file", "negative", "image", "refs", "audio", "video", "text", "text_file", "out", "out_dir",
                "seconds", "width", "height", "language", "voice", "scale", "seed", "steps")
CMD_NEEDS = {                                                          # كل مهمة لازم أمرها يستقبل مدخلاتها
    "image": (("prompt", "prompt_file"),), "voice": (("text", "text_file"),), "stt": (("audio",),), "upscale": (("image",),),
    "bgremove": (("image",),), "lipsync": (("video", "image"), ("audio",)), "music": (("prompt", "prompt_file"),), "sfx": (("prompt", "prompt_file"),),
}
SECRET_NAME_RX = re.compile(r"[A-Za-z0-9_.-]{1,64}")
MODEL_SECRET_RX = re.compile(r"modellib\.[A-Za-z0-9_]{1,40}\.token")            # توكن نموذج/صندوق المكتبة بس: ما بنقبل اسم أي سرّ تاني (توكن الـ OMS، مفتاح النسخ…) عشان ما يطلع لسيرفر النموذج
ENV_NAME_RX = re.compile(r"[A-Z_][A-Z0-9_]{0,40}")
ENV_BLOCK_RX = re.compile(r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH", re.I)
ID_RX = re.compile(r"ml_\d{3,}")
PLACEHOLDER_RX = re.compile(r"\{(\w+)\}")
TEMPLATES_PATH = Path(config.BASE) / "presets" / "model_templates.json"

_LOCK = threading.RLock()
_cache: dict = {"key": None, "doc": None}
_tpl_cache: dict = {"key": None, "items": None}


class ModelLibraryError(ValueError):
    """رسالة عربية جاهزة للعرض."""


@dataclass(frozen=True)
class Pick:
    """نتيجة اختيار نموذج لمهمة. source: lib (اختيار صريح lib:ml_x) | default (افتراضي المهمة) | explicit (مزوّد صريح بالنداء) | builtin (الطريقة الحالية)."""
    source: str
    model: dict | None = None
    fallback_builtin: bool = False                                     # لو النموذج وقع تقنياً: ممكن الطريقة الحالية تكمّل؟
    reason: str = ""                                                   # ليش تخطّينا افتراضي المكتبة (معطّل/رخصة/ملف تالف) — بيتعرض للمالك


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── الملف ───────────────────────────────────────────────────────────────
def path() -> Path:
    env = os.environ.get(ENV_PATH, "").strip()
    return Path(env) if env else Path(config.LIBRARY_DIR) / "model_library.json"


def _blank() -> dict:
    return {"version": VERSION, "next_id": 1, "box": {"url": None, "token_secret": None},
            "tasks": {t: {"default": None, "fallback_builtin": t not in NO_FALLBACK} for t in TASKS}, "models": []}


def load() -> dict:
    """المكتبة كاملة (نسخة مستقلة). ملف مش موجود = مكتبة فاضية. ملف تالف = ModelLibraryError (ما بنكتب فوقه)."""
    p = path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return _blank()
    racy = time.time_ns() - st.st_mtime_ns < 2_000_000_000          # اتعدّل من أقل من ثانيتين: تعديل تاني بنفس لحظة الطابع والحجم ما بيبيّن — ما منثق بالكاش (مثل git)
    with _LOCK:
        if _cache["key"] != key or racy:
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ModelLibraryError(f"ملف مكتبة النماذج تالف ({p}) — صلّحه أو احذفه ليبدأ من جديد") from None
            _cache["doc"], _cache["key"] = _normalize(raw), key
        return copy.deepcopy(_cache["doc"])


def _write(doc: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise ModelLibraryError("تعذّرت كتابة مكتبة النماذج (المجلد مقفول أو ممتلي؟)") from None
    _cache["key"] = None


def _normalize(raw) -> dict:
    """يتحقق من ملف المكتبة كامل ويرجّع الشكل المعياري. أي خلل = ModelLibraryError بنص يقول وين."""
    if not isinstance(raw, dict):
        raise ModelLibraryError("ملف مكتبة النماذج مش بالشكل المتوقع")
    if int(raw.get("version") or 0) > VERSION:
        raise ModelLibraryError("ملف مكتبة النماذج أحدث من نسخة الاستوديو — حدّث الاستوديو")
    bad = set(raw) - {"version", "next_id", "box", "tasks", "models"}
    if bad:
        raise ModelLibraryError(f"مكتبة النماذج: حقول غير معروفة {sorted(bad)}")
    doc = _blank()
    doc["box"] = _clean_box(raw.get("box") or {})
    for t, cfg in (raw.get("tasks") or {}).items():
        if t not in TASKS or not isinstance(cfg, dict) or set(cfg) - {"default", "fallback_builtin"}:
            raise ModelLibraryError(f"مكتبة النماذج: إعداد مهمة غير صالح ({t})")
        d = cfg.get("default")
        if d is not None and not isinstance(d, str):
            raise ModelLibraryError(f"مكتبة النماذج: افتراضي مهمة {t} لازم معرّف")
        fb = bool(cfg.get("fallback_builtin", t not in NO_FALLBACK)) and t not in NO_FALLBACK
        doc["tasks"][t] = {"default": d, "fallback_builtin": fb}
    seen, models = set(), []
    for m in raw.get("models") or []:
        mid = m.get("id") if isinstance(m, dict) else None
        if not isinstance(mid, str) or not ID_RX.fullmatch(mid) or mid in seen:
            raise ModelLibraryError("مكتبة النماذج: معرّف نموذج غير صالح أو مكرّر")
        seen.add(mid)
        body = {k: v for k, v in m.items() if k not in ("id", "created_at", "updated_at")}
        try:
            clean = _clean_model(body, None, partial_ok=True)
        except ModelLibraryError as e:
            raise ModelLibraryError(f"مكتبة النماذج: النموذج {mid} فيه خلل — {e}") from None
        clean.update(id=mid, created_at=str(m.get("created_at") or _now()), updated_at=str(m.get("updated_at") or m.get("created_at") or _now()))
        models.append(clean)
    doc["models"] = models
    nums = [int(i[3:]) for i in seen]
    doc["next_id"] = max(int(raw.get("next_id") or 1), (max(nums) + 1) if nums else 1)
    return doc


# ── التحقق من الحقول ────────────────────────────────────────────────────
def _num(v, kind: str, lo, hi, label: str):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ModelLibraryError(f"{label}: لازم رقم")
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise ModelLibraryError(f"{label}: لازم رقم") from None
    if n != n or not lo <= n <= hi:
        raise ModelLibraryError(f"{label}: خارج المعقول ({lo:g}–{hi:g})")
    if kind == "int":
        if n != int(n):
            raise ModelLibraryError(f"{label}: لازم رقم صحيح")
        return int(n)
    return n


def _typed(spec, v, label: str):
    if spec == "bool":
        if not isinstance(v, bool):
            raise ModelLibraryError(f"{label}: لازم صح/غلط")
        return v
    if spec[0] == "str":
        if not isinstance(v, str):
            raise ModelLibraryError(f"{label}: لازم نص")
        v = v.strip()
        if len(v) > spec[1] or "\x00" in v:
            raise ModelLibraryError(f"{label}: أطول من {spec[1]} حرف")
        return v
    return _num(v, spec[0], spec[1], spec[2], label)


def _clean_map(raw, specs: dict, what: str) -> dict:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise ModelLibraryError(f"{what}: لازم كائن")
    bad = set(raw) - set(specs)
    if bad:
        raise ModelLibraryError(f"{what}: حقول غير معروفة {sorted(bad)}")
    out = {}
    for k, v in raw.items():
        if v in (None, ""):
            continue
        out[k] = _typed(specs[k], v, f"{what}.{k}")
    return out


def _text(v, label: str, limit: int, *, required=False) -> str:
    if v is None or v == "":
        if required:
            raise ModelLibraryError(f"{label} مطلوب")
        return ""
    if not isinstance(v, str) or "\x00" in v:
        raise ModelLibraryError(f"{label}: لازم نص")
    v = v.strip()
    if len(v) > limit:
        raise ModelLibraryError(f"{label}: أطول من {limit} حرف")
    return v


def _clean_licence(raw, existing: dict | None, by: str | None, trusted: bool = False) -> dict:
    old = existing or {}
    if raw is None:
        raw = {k: old[k] for k in LICENCE_KEYS if k in old} if old else {}
    if not isinstance(raw, dict):
        raise ModelLibraryError("الرخصة: لازم كائن")
    bad = set(raw) - LICENCE_KEYS
    if bad:
        raise ModelLibraryError(f"الرخصة: حقول غير معروفة {sorted(bad)}")
    com = raw.get("commercial", old.get("commercial", "unknown"))
    if com not in COMMERCIAL:
        raise ModelLibraryError("الرخصة: «تجاري» لازم yes أو conditional أو unknown أو no")
    lic_id = _text(raw.get("id", old.get("id")), "الرخصة: الاسم", 60) or "غير معروف"
    changed = bool(old) and (lic_id != (old.get("id") or "غير معروف") or com != old.get("commercial", "unknown"))      # رخصة غير اللي راجعها المالك: التأكيد القديم ما بينطبق عليها
    conf = raw.get("confirmed_by_owner", False if changed else old.get("confirmed_by_owner", False))
    if not isinstance(conf, bool):
        raise ModelLibraryError("الرخصة: التأكيد لازم صح/غلط")
    out = {"id": lic_id, "commercial": com, "confirmed_by_owner": conf, "note": _text(raw.get("note", old.get("note")), "الرخصة: ملاحظة", 300)}
    if conf:                                                           # الختم بيحطه الخادم مش العميل (إلا لما نقرا من ملفنا نفسه: trusted)
        was = bool(old.get("confirmed_by_owner")) and not changed
        src = raw if trusted and raw.get("confirmed_at") and raw.get("confirmed_by") else old if was else {}
        out["confirmed_at"] = str(src.get("confirmed_at") or _now())[:40]
        out["confirmed_by"] = str(src.get("confirmed_by") or by or "المالك")[:80]
    return out


def licence_gate(model: dict) -> tuple[bool, str]:
    """بوابة الرخصة: (مسموح؟، السبب)."""
    lic = model.get("licence") or {}
    com = lic.get("commercial", "unknown")
    name = lic.get("id") or "غير معروفة"
    if com == "no":
        return False, f"رخصته ({name}) بتمنع الاستخدام التجاري — ما بنفعّله"
    if com in ("conditional", "unknown") and not lic.get("confirmed_by_owner"):
        return False, f"رخصته ({name}) محتاجة مراجعتك — أكّد إنك راجعتها قبل التفعيل"
    return True, ""


def usable(model: dict) -> tuple[bool, str]:
    if not model.get("enabled"):
        return False, "معطّل"
    return licence_gate(model)


def _clean_std(raw) -> dict:
    if not isinstance(raw, dict):
        raise ModelLibraryError("إعدادات الواجهة القياسية (std) مطلوبة: الرابط واسم الموديل")
    bad = set(raw) - STD_KEYS
    if bad:
        raise ModelLibraryError(f"إعدادات الواجهة القياسية: حقول غير معروفة {sorted(bad)}")
    try:
        url = net_allow.validate(raw.get("url"), subject="رابط الواجهة القياسية", example="http://127.0.0.1:8000/v1", allow_path=True)
    except net_allow.NetAllowError as e:
        raise ModelLibraryError(str(e)) from None
    out = {"url": url, "model": _text(raw.get("model"), "اسم الموديل", 120, required=True)}
    ts = raw.get("token_secret")
    if ts in (None, ""):
        out["token_secret"] = None
    elif isinstance(ts, str) and MODEL_SECRET_RX.fullmatch(ts.strip()):
        out["token_secret"] = ts.strip()
    else:
        raise ModelLibraryError("اسم مفتاح التوكن لازم بالشكل modellib.<رقم النموذج>.token (النظام بيحطه لحاله من خانة التوكن)")
    fmt = _text(raw.get("response_format"), "صيغة الرد", 12)
    if fmt and fmt not in ("mp3", "wav", "opus", "flac", "aac", "b64_json", "url"):
        raise ModelLibraryError("صيغة الرد غير معروفة (mp3 أو wav أو opus أو flac أو aac، وللصور b64_json أو url)")
    out["response_format"] = fmt or None
    size = _text(raw.get("size"), "مقاس الصورة", 12)
    if size and not re.fullmatch(r"\d{3,4}x\d{3,4}", size):
        raise ModelLibraryError("مقاس الصورة بالشكل 1024x1024")
    out["size"] = size or None
    return out


def _clean_app(raw, task: str) -> dict:
    """ربط برنامج Gradio: الرابط (قائمة السماح) + اسم النقطة + ربط معاملاتها بمدخلات الطلب أو بقيم ثابتة + بصمة الشكل."""
    if not isinstance(raw, dict):
        raise ModelLibraryError("إعدادات برنامج النموذج (app) مطلوبة: الرابط والنقطة وربط المعاملات")
    bad = set(raw) - APP_KEYS
    if bad:
        raise ModelLibraryError(f"إعدادات البرنامج: حقول غير معروفة {sorted(bad)}")
    try:
        url = net_allow.validate(raw.get("url"), subject="رابط البرنامج", example="http://127.0.0.1:7860")
    except net_allow.NetAllowError as e:
        raise ModelLibraryError(str(e)) from None
    api = _text(raw.get("api_name"), "اسم النقطة", 81, required=True)
    if not APP_API_RX.fullmatch(api):
        raise ModelLibraryError("اسم النقطة: حروف إنجليزية وأرقام و _ - (مثال /generate)")
    items = raw.get("inputs")
    if items in (None, ""):
        items = []
    if not isinstance(items, list) or len(items) > 60:
        raise ModelLibraryError("ربط المعاملات: قائمة لحد 60 معامل")
    inputs, seen = [], set()
    for it in items:
        if not isinstance(it, dict) or set(it) - {"param", "from", "const"} or ("from" in it) == ("const" in it):
            raise ModelLibraryError("ربط معامل: لازم param مع from (من الطلب) أو const (قيمة ثابتة)")
        param = it.get("param")
        if not isinstance(param, str) or not APP_PARAM_RX.fullmatch(param) or param in seen:
            raise ModelLibraryError(f"اسم المعامل «{param}» غير صالح أو مكرّر")
        seen.add(param)
        if "from" in it:
            if it["from"] not in APP_SOURCES:
                raise ModelLibraryError(f"مصدر «{it['from']}» غير معروف — المتاح: " + " ".join(APP_SOURCES))
            inputs.append({"param": param, "from": it["from"]})
        else:
            v = it["const"]
            if isinstance(v, str):
                if len(v) > 500 or "\x00" in v:
                    raise ModelLibraryError(f"القيمة الثابتة لـ «{param}»: أطول من 500 حرف")
            elif isinstance(v, float):
                if v != v or v in (float("inf"), float("-inf")):
                    raise ModelLibraryError(f"القيمة الثابتة لـ «{param}»: رقم غير صالح")
            elif v is not None and not isinstance(v, (bool, int)):
                raise ModelLibraryError(f"القيمة الثابتة لـ «{param}»: نص أو رقم أو صح/غلط بس")
            inputs.append({"param": param, "const": v})
    have = {i["from"] for i in inputs if "from" in i}
    for group in CMD_NEEDS.get(task, ()):
        if not (set(group) & have):
            raise ModelLibraryError("لازم تربط معامل بـ " + " أو ".join(g for g in group if g in APP_SOURCES) + f" لمهمة «{TASK_LABELS[task]}»")
    out = raw.get("output") or {}
    if not isinstance(out, dict) or set(out) - {"index"}:
        raise ModelLibraryError("المخرج: index بس (رقم المخرج، أو فاضي = تلقائي حسب نوع المهمة)")
    idx = out.get("index")
    idx = None if idx in (None, "") else _num(idx, "int", 0, 40, "رقم المخرج")
    h = raw.get("schema_hash")
    if h in (None, ""):
        h = None
    elif not (isinstance(h, str) and re.fullmatch(r"[0-9a-f]{8,64}", h)):
        raise ModelLibraryError("بصمة شكل البرنامج غير صالحة (بتيجي من «اقرا البرنامج»)")
    return {"url": url, "api_name": api if api.startswith("/") else "/" + api, "inputs": inputs, "output": {"index": idx}, "schema_hash": h}


def _clean_weights(raw) -> dict:
    if not isinstance(raw, dict):
        raise ModelLibraryError("إعدادات الأوزان (weights) مطلوبة: اسم مجلد النموذج")
    bad = set(raw) - WEIGHTS_KEYS
    if bad:
        raise ModelLibraryError(f"إعدادات الأوزان: حقول غير معروفة {sorted(bad)}")
    name = _text(raw.get("model"), "اسم مجلد النموذج", 120, required=True)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", name) or ".." in name:
        raise ModelLibraryError("اسم مجلد النموذج: حروف إنجليزية وأرقام و _ - . بس")
    out = {"model": name}
    for k, kind, lo, hi in (("steps", "int", 1, 200), ("guidance", "float", 0, 30)):
        out[k] = None if raw.get(k) in (None, "") else _num(raw[k], kind, lo, hi, k)
    return out


def _clean_command(raw, task: str) -> dict:
    if not isinstance(raw, dict):
        raise ModelLibraryError("إعدادات الأمر (command) مطلوبة: الأمر وأماكن الملفات")
    bad = set(raw) - CMD_KEYS
    if bad:
        raise ModelLibraryError(f"إعدادات الأمر: حقول غير معروفة {sorted(bad)}")
    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or len(argv) > 60 or not all(isinstance(a, str) and len(a) <= 600 and "\x00" not in a for a in argv):
        raise ModelLibraryError("الأمر: قائمة وسائط نصية (مو سطر واحد)، لحد 60 وسيط")
    if not argv[0].strip() or "{" in argv[0]:
        raise ModelLibraryError("الأمر: الوسيط الأول لازم يكون اسم البرنامج نفسه (بلا أماكن ملفات)")
    used = {m for a in argv for m in PLACEHOLDER_RX.findall(a)}
    unknown = used - set(PLACEHOLDERS)
    if unknown:
        raise ModelLibraryError(f"الأمر: أماكن ملفات غير معروفة {sorted('{' + u + '}' for u in unknown)} — المتاح: " + " ".join("{" + p + "}" for p in PLACEHOLDERS))
    if not ({"out", "out_dir"} & used):
        raise ModelLibraryError("الأمر لازم يعرف وين يكتب الناتج: حط {out} (ملف) أو {out_dir} (مجلد)")
    for group in CMD_NEEDS.get(task, ()):
        if not (set(group) & used):
            raise ModelLibraryError("الأمر لازم يستقبل " + " أو ".join("{" + g + "}" for g in group) + f" لمهمة «{TASK_LABELS[task]}»")
    cwd = _text(raw.get("cwd"), "مجلد التشغيل", 400)
    glob = _text(raw.get("output_glob"), "نمط ملف الناتج", 80)
    if glob and (".." in glob or "/" in glob or "\\" in glob):
        raise ModelLibraryError("نمط ملف الناتج: اسم ملف بس (مثل *.wav)، بلا مسارات")
    env = raw.get("env") or {}
    if not isinstance(env, dict) or len(env) > 10:
        raise ModelLibraryError("متغيّرات البيئة: لحد 10")
    for k, v in env.items():
        if not isinstance(k, str) or not ENV_NAME_RX.fullmatch(k) or ENV_BLOCK_RX.search(k):
            raise ModelLibraryError(f"متغيّر البيئة «{k}»: اسم غير مسموح (ممنوع أي اسم فيه KEY أو TOKEN أو SECRET أو PASSWORD)")
        if not isinstance(v, str) or len(v) > 300 or "\x00" in v:
            raise ModelLibraryError(f"متغيّر البيئة «{k}»: قيمة غير صالحة")
    return {"argv": [a for a in argv], "cwd": cwd or None, "output_glob": glob or None, "env": dict(env)}


LINK_CLEANERS = {"std": lambda raw, task: _clean_std(raw), "weights": lambda raw, task: _clean_weights(raw), "command": _clean_command, "app": _clean_app}


def _clean_model(raw: dict, existing: dict | None, *, by: str | None = None, partial_ok: bool = False) -> dict:
    """نموذج معياري من حقول المالك (جديد أو معدّل). partial_ok: قراءة من الملف (بلا فحص «الطريقة مفتوحة»)."""
    if not isinstance(raw, dict):
        raise ModelLibraryError("النموذج: لازم كائن")
    bad = set(raw) - MODEL_KEYS
    if bad:
        raise ModelLibraryError(f"حقول غير معروفة: {sorted(bad)}")
    old = existing or {}
    task = raw.get("task", old.get("task"))
    if task not in LIBRARY_TASKS:
        raise ModelLibraryError("المهمة: " + " أو ".join(LIBRARY_TASKS) + (" (التحريك بسجله الخاص)" if task == "motion" else ""))
    if old and task != old["task"]:
        raise ModelLibraryError("ما بتتبدّل مهمة النموذج بعد ما ينعمل — اعمل نموذج جديد")
    link = raw.get("link", old.get("link"))
    if link not in LINKS:
        raise ModelLibraryError("طريقة الربط: " + " أو ".join(LINKS))
    if old and link != old["link"]:
        raise ModelLibraryError("ما بتتبدّل طريقة الربط بعد ما ينعمل النموذج — اعمل نموذج جديد")
    if task not in LINK_TASKS[link]:
        ok_links = [l for l in LINKS if task in LINK_TASKS[l]]
        raise ModelLibraryError(f"«{LINK_LABELS[link]}» ما بتخدم مهمة «{TASK_LABELS[task]}» — المتاح لها: " + "، ".join(LINK_LABELS[l] for l in ok_links))
    if not partial_ok and link not in OPEN_LINKS:
        raise ModelLibraryError(f"ربط «{LINK_LABELS[link]}» لسا ما انفتح بهالنسخة")
    name = _text(raw.get("name", old.get("name")), "اسم النموذج", 80, required=True)
    enabled = raw.get("enabled", old.get("enabled", False))
    if not isinstance(enabled, bool):
        raise ModelLibraryError("التفعيل: لازم صح/غلط")
    tpl = raw.get("template", old.get("template"))
    if tpl not in (None, "") and not (isinstance(tpl, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", tpl)):
        raise ModelLibraryError("معرّف القالب غير صالح")
    out = {"name": name, "task": task, "link": link, "enabled": enabled, "template": tpl or None,
           "licence": _clean_licence(raw["licence"] if "licence" in raw else None, old.get("licence"), by, trusted=partial_ok),
           "caps": _clean_map(raw["caps"] if "caps" in raw else old.get("caps"), CAPS[task], "القدرات"),
           "params": _clean_map(raw["params"] if "params" in raw else old.get("params"), PARAMS[task], "المعاملات"),
           "note": _text(raw.get("note", old.get("note")), "الملاحظة", 300)}
    gpu = raw.get("uses_gpu", old.get("uses_gpu", link in ("app", "command")))
    if not isinstance(gpu, bool):
        raise ModelLibraryError("استعمال الكرت: لازم صح/غلط")
    out["uses_gpu"] = False if link == "weights" else gpu                # الصندوق بيمسك قفل الكرت بنفسه (قفلين = انتظار للأبد)
    out["timeout_sec"] = _num(raw.get("timeout_sec", old.get("timeout_sec", DEFAULT_TIMEOUT[task])), "int", 10, 7200, "المهلة (ثانية)")
    out[link] = LINK_CLEANERS[link](raw[link] if link in raw else old.get(link), task)
    for other in LINKS:
        if other != link:
            out.pop(other, None)
    if out["enabled"] and not partial_ok:
        ok, why = licence_gate(out)
        if not ok:
            raise ModelLibraryError(why)
    return out


# ── القراءة ─────────────────────────────────────────────────────────────
def list_models(task: str | None = None) -> list[dict]:
    if task is not None and task not in LIBRARY_TASKS:
        raise ModelLibraryError("التحريك بسجله الخاص (سجل موديلات التحريك)" if task == "motion" else "مهمة غير معروفة")
    return [m for m in load()["models"] if task is None or m["task"] == task]


def get(model_id: str) -> dict | None:
    return next((m for m in load()["models"] if m["id"] == model_id), None)


def task_config(task: str) -> dict:
    if task not in TASKS:
        raise ModelLibraryError("مهمة غير معروفة")
    return load()["tasks"][task]


# ── الكتابة ─────────────────────────────────────────────────────────────
def create(raw: dict, *, by: str | None = None) -> dict:
    with _LOCK:
        doc = load()
        m = _clean_model(raw, None, by=by)
        m.update(id=f"ml_{doc['next_id']:03d}", created_at=_now(), updated_at=_now())
        doc["next_id"] += 1
        doc["models"].append(m)
        _write(doc)
        return copy.deepcopy(m)


def update(model_id: str, patch: dict, *, by: str | None = None) -> dict:
    with _LOCK:
        doc = load()
        cur = next((m for m in doc["models"] if m["id"] == model_id), None)
        if not cur:
            raise ModelLibraryError("النموذج مش موجود")
        new = _clean_model(patch, cur, by=by)
        new.update(id=model_id, created_at=cur["created_at"], updated_at=_now())
        doc["models"][doc["models"].index(cur)] = new
        _write(doc)
        return copy.deepcopy(new)


def delete(model_id: str) -> bool:
    with _LOCK:
        doc = load()
        n = len(doc["models"])
        doc["models"] = [m for m in doc["models"] if m["id"] != model_id]
        if len(doc["models"]) == n:
            return False
        for cfg in doc["tasks"].values():
            if cfg["default"] == model_id:
                cfg["default"] = None
        _write(doc)
    try:                                                               # توكن النموذج ما بيضل بالخزنة بعد حذفه
        import secrets_store
        secrets_store.delete_secret(token_secret_name(model_id))
    except Exception:                                                  # noqa: BLE001 — مخزن غير متاح: ما بنوقف الحذف
        pass
    return True


def token_secret_name(model_id: str) -> str:
    return f"modellib.{model_id}.token"


def set_default(task: str, model_id: str | None, *, fallback_builtin: bool | None = None) -> dict:
    """يثبّت نموذج الافتراضي للمهمة (None = بدون، الطريقة الحالية). التحريك: معرّف من motion_models.json (mm_NNN)."""
    if task not in TASKS:
        raise ModelLibraryError("مهمة غير معروفة")
    with _LOCK:
        doc = load()
        cfg = doc["tasks"][task]
        if model_id:
            if task == "motion":
                import motion
                m = next((x for x in motion.load_models() if x["id"] == model_id), None)
                if not m or m.get("enabled") is False:
                    raise ModelLibraryError("موديل التحريك مش موجود أو معطّل")
            else:
                m = next((x for x in doc["models"] if x["id"] == model_id), None)
                if not m or m["task"] != task:
                    raise ModelLibraryError("النموذج مش موجود لهالمهمة")
                ok, why = usable(m)
                if not ok:
                    raise ModelLibraryError(f"ما بنقدر نجعله الافتراضي: {why}")
        cfg["default"] = model_id or None
        if fallback_builtin is not None:
            if not isinstance(fallback_builtin, bool):
                raise ModelLibraryError("الرجوع للطريقة الحالية: لازم صح/غلط")
            if fallback_builtin and task in NO_FALLBACK:
                raise ModelLibraryError(f"«{TASK_LABELS[task]}» ما بيرجع للطريقة الحالية تلقائياً (تغيير النموذج بنص الشغلة بيخرّب الناتج)")
            cfg["fallback_builtin"] = fallback_builtin
        _write(doc)
        return dict(cfg)


def _clean_box(raw) -> dict:
    if not isinstance(raw, dict) or set(raw) - {"url", "token_secret"}:
        raise ModelLibraryError("إعدادات صندوق الأوزان: الرابط واسم التوكن بس")
    url = raw.get("url")
    if url in (None, ""):
        url = None
    else:
        try:
            url = net_allow.validate(url, subject="عنوان صندوق الأوزان", example="http://127.0.0.1:8100")
        except net_allow.NetAllowError as e:
            raise ModelLibraryError(str(e)) from None
    ts = raw.get("token_secret")
    if ts not in (None, "") and not (isinstance(ts, str) and MODEL_SECRET_RX.fullmatch(ts.strip())):
        raise ModelLibraryError("اسم مفتاح التوكن لازم بالشكل modellib.<رقم النموذج>.token (النظام بيحطه لحاله من خانة التوكن)")
    return {"url": url, "token_secret": (ts or "").strip() or None}


def set_box(url, token_secret=None) -> dict:
    with _LOCK:
        doc = load()
        doc["box"] = _clean_box({"url": url, "token_secret": token_secret})
        _write(doc)
        return dict(doc["box"])


# ── الاختيار ────────────────────────────────────────────────────────────
def pick(task: str, override=None) -> Pick:
    """أي نموذج بيشغّل هالمهمة؟  الترتيب: lib:ml_x صريح ← مزوّد صريح بالنداء ← افتراضي المكتبة ← الطريقة الحالية.
    اختيار صريح لنموذج مكتبة مش موجود/معطّل/رخصته ما بتسمح = ModelLibraryError (بدل ما نشتغل بنموذج غير اللي طلبه المالك بصمت)."""
    if task not in TASKS:
        raise ModelLibraryError("مهمة غير معروفة")
    ov = override.strip() if isinstance(override, str) else ""
    if ov.startswith(LIB_PREFIX):
        m = get(ov[len(LIB_PREFIX):])
        if not m or m["task"] != task:
            raise ModelLibraryError("النموذج المطلوب مش موجود بمكتبة النماذج لهالمهمة")
        ok, why = usable(m)
        if not ok:
            raise ModelLibraryError(f"«{m['name']}»: {why}")
        return Pick("lib", m, False)
    if ov:
        return Pick("explicit")
    try:
        doc = load()
    except ModelLibraryError as e:
        return Pick("builtin", reason=str(e))                          # ملف تالف ما بيوقف الإنتاج: الطريقة الحالية + سبب للمالك
    cfg = doc["tasks"][task]
    if not cfg["default"]:
        return Pick("builtin")
    m = next((x for x in doc["models"] if x["id"] == cfg["default"]), None)
    if not m:
        return Pick("builtin", reason="افتراضي المكتبة انحذف")
    ok, why = usable(m)
    if not ok:
        return Pick("builtin", reason=f"افتراضي {TASK_LABELS[task]} «{m['name']}» اتخطّى: {why}")
    return Pick("default", m, bool(cfg["fallback_builtin"]) and task not in NO_FALLBACK)


# ── القوالب ─────────────────────────────────────────────────────────────
def templates() -> list[dict]:
    """قوالب النماذج الجاهزة (presets/model_templates.json). الرخصة والشارات هون «مساعدة» — القرار للمالك."""
    p = TEMPLATES_PATH
    try:
        st = p.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return []
    if _tpl_cache["key"] != key:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ModelLibraryError("ملف قوالب النماذج تالف") from None
        _tpl_cache["items"], _tpl_cache["key"] = _check_templates(raw), key
    return copy.deepcopy(_tpl_cache["items"])


def _check_templates(raw) -> list[dict]:
    items = raw.get("templates") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ModelLibraryError("ملف قوالب النماذج: ما في قائمة templates")
    out, seen = [], set()
    for t in items:
        tid = t.get("id") if isinstance(t, dict) else None
        if not isinstance(tid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", tid) or tid in seen:
            raise ModelLibraryError("ملف قوالب النماذج: معرّف قالب غير صالح أو مكرّر")
        seen.add(tid)
        if t.get("task") not in TASKS or t.get("link") not in LINKS or t["task"] not in (LINK_TASKS[t["link"]] + ("motion",) if t["link"] == "weights" else LINK_TASKS[t["link"]]):
            raise ModelLibraryError(f"قالب {tid}: مهمة أو طريقة ربط غير صالحة")
        lic = t.get("licence") or {}
        if lic.get("commercial") not in COMMERCIAL:
            raise ModelLibraryError(f"قالب {tid}: رخصة غير صالحة")
        out.append(t)
    return out


def template(template_id: str) -> dict | None:
    return next((t for t in templates() if t["id"] == template_id), None)


def public(m: dict) -> dict:
    """نموذج جاهز للواجهة: كل شي، بدون أي قيمة سرّية (ما في أصلاً) + حالة التوكن والاستعمال."""
    out = copy.deepcopy(m)
    ok, why = usable(m)
    out["usable"], out["unusable_reason"] = ok, why
    out["licence_label"] = COMMERCIAL_LABELS[m["licence"]["commercial"]]
    blk = m.get(m["link"]) or {}
    name = blk.get("token_secret") if isinstance(blk, dict) else None
    out["token_set"] = (_secret_set(name) if name else False) if m["link"] == "std" else None      # None = الطريقة ما بتستعمل توكن
    return out


def _secret_set(name: str) -> bool:
    try:
        import secrets_store
        return bool(secrets_store.get_secret(name))
    except Exception:                                                  # noqa: BLE001 — مخزن غير متاح = ما منعرف
        return False
