"""
إعداد محوّلات الإضافة متعددة المواقع (راجع ext_contract.md الفقرة 4).

الخادم هو المصدر: DEFAULTS هون (لستة مواقع)، وملف تعديلات library/ext/adapters.json بيندمج فوقه دمج عميق.
الإضافة بتسحب الإعداد المدموج وبتخزّنه، فلما موقع يغيّر شكله منصلّح الإعداد هون بلا إعادة تثبيت.

  · المحدّدات تخمينية جزئياً (verified: false): صندوق الكتابة وزر الإرسال انقرت بقراءة فقط من صفحات Flow وFlow Music وGemini وChatGPT
    وAI Studio الحقيقية يوم 2026-10-21، وباقيها (النتائج، التحريك، ElevenLabs) ما انجرّب على موقع حقيقي. بتتحوّل لـ true بعد أول نجاح حقيقي.
  · أي موقع أو نوع شغل غير معروف بيترفض، وكل عنوان لازم يكون https على مضيف معلن بالموقع نفسه.
  · ممنوع أي محدّد يلمس حقول كلمات السر (قاعدة ثابتة بالعقد).
  · نتائج الفحص الذاتي اليومي بتتخزّن بملف library/ext/selftest.json.
"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import config

SITES = ("gemini", "chatgpt", "aistudio", "flow", "flowmusic", "elevenlabs")
KINDS = ("voice", "image", "video", "ahat", "music")
STEP_DO = ("click", "type", "attach", "wait")
RESULT_TYPES = ("image", "audio", "video")
# نوع النتيجة المقبول لكل نوع شغل
RESULT_FOR_KIND = {"voice": "audio", "ahat": "audio", "music": "audio", "image": "image", "video": "video"}

DEFAULTS_VERSION = 3

SITE_KEYS = {"label", "adapter_version", "verified", "hosts", "newUrl", "kinds", "selftest"}
KIND_KEYS = {"url", "steps", "busy", "result", "timeoutSec"}
STEP_KEYS = {"do", "sel", "text", "ms", "optional", "needs", "if", "via", "waitMs"}
RESULT_KEYS = {"type", "sel", "download", "reveal"}
STEP_NEEDS = ("refs",)                        # خطوة بتتنفّذ بس لو في صور مرجعية
STEP_IF = ("pressed", "unpressed")           # نقر حسب حالة الزر (aria-pressed/checked/selected)
ATTACH_VIA = ("input", "drop", "paste")
# محدّد بيستهدف فعل مدمّر أو مالي مرفوض (الإضافة بتولّد بس) — نفس قاعدة adapters.js
_DANGER_RX = re.compile(r"\b(?:delete|remove|trash|purchase|buy|checkout|upgrade|subscribe|logout|log[ -]?out|sign[ -]?out|billing)\b|حذف|شراء|ترقية|اشتراك|تسجيل الخروج", re.I)
_HOST_RX = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


class ExtConfigError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── القيم الافتراضية ────────────────────────────────────────────────────
def _type(sel, text="{prompt}"):
    return {"do": "type", "sel": sel, "text": text}


def _click(sel, optional=False, **extra):
    return {"do": "click", "sel": sel, "optional": optional, **extra}


def _attach(optional=True, sel=None, via=None):
    st = {"do": "attach", "sel": sel or ['input[type="file"]'], "optional": optional}
    if via:
        st["via"] = via
    return st


def _kind(url, steps, busy, rtype, rsel, timeout, download=None, reveal=None):
    res = {"type": rtype, "sel": rsel, "download": download or []}
    if reveal:
        res["reveal"] = reveal
    return {"url": url, "steps": steps, "busy": busy, "result": res, "timeoutSec": timeout}


_BUSY_GENERIC = ["[role=progressbar]", "mat-progress-bar"]

# ── Flow (flow.google.com) ──
# الشريط السفلي فيه وضع «Agent» (وكيل بيسأل تأكيد قبل التوليد) ووضع مباشر. بنشتغل بالمباشر: نطفّي شريحة Agent، نفتح قائمة الإعدادات
# (Image/Video + النسبة + العدد)، ونثبّت النوع والنسبة وعدد النتائج x1 (حماية الرصيد). كلها خطوات اختيارية بانتظار قصير.
_FLOW_URL = "https://flow.google.com/"
_FLOW_COMPOSER = ['div.ProseMirror[role="textbox"]', 'div[role="textbox"][aria-label*="create" i]']
_FLOW_SETTINGS = ['button[aria-label="Settings trigger"]']
_FLOW_BUSY = ['[role="progressbar"]', "mat-progress-bar", "mat-spinner"]
_FLOW_NEW_PROJECT = [_click(["button::contains(New project)", '[role="button"]::contains(New project)'], True, waitMs=1500)]
_GEMINI_COMPOSER = ['rich-textarea div.ql-editor[contenteditable="true"]', 'div.ql-editor[contenteditable="true"]',
                    'div[contenteditable="true"][role="textbox"]']
_CHATGPT_COMPOSER = ["#prompt-textarea", 'div.ProseMirror[contenteditable="true"]', 'div[contenteditable="true"][role="textbox"]',
                     'div[contenteditable="true"][id*="prompt"]', "textarea"]
_AISTUDIO_COMPOSER = ['textarea[aria-label="Enter a prompt"]', "textarea", 'div[contenteditable="true"]']
_FLOWMUSIC_URL = "https://www.flowmusic.app/"
_FLOWMUSIC_COMPOSER = ['textarea[aria-label="Chat message"]', 'textarea[placeholder*="create" i]', "textarea"]


def _flow_prep(tab, extra=None):
    return [
        _click(["button.agent-mode-chip"], True, **{"if": "pressed", "waitMs": 12000}),     # بعد «New project» الصفحة بتاخد وقت تحمّل
        _click(_FLOW_SETTINGS, True, waitMs=5000),
        _click([f'button[role="radio"]::contains({tab})'], True, **{"if": "unpressed", "waitMs": 2000}),
        *(extra or []),
        _click(['button[role="radio"]::contains({aspect})'], True, **{"if": "unpressed", "waitMs": 2000}),
        _click(['button[role="radio"]::contains(x1)'], True, **{"if": "unpressed", "waitMs": 2000}),
        _click(_FLOW_SETTINGS, True, waitMs=2000),
    ]


def _flow_send_tail():
    return [
        _click(['button[aria-label="Add ingredients to the prompt box"]'], True, needs="refs", waitMs=3000),
        _attach(True),
        _type(_FLOW_COMPOSER),
        _click(['button[aria-label="Start generation"]']),
    ]


DEFAULTS: dict = {
    "version": DEFAULTS_VERSION,
    "sites": {
        "gemini": {
            "label": "Gemini", "adapter_version": 2, "verified": False,
            "hosts": ["gemini.google.com"], "newUrl": "https://gemini.google.com/app",
            "kinds": {"image": _kind(
                "https://gemini.google.com/app",
                [_attach(True, _GEMINI_COMPOSER, "paste"),
                 _type(_GEMINI_COMPOSER),
                 _click(['button[aria-label*="Send" i]', 'button[aria-label*="إرسال"]', "button.send-button"])],
                ['button[aria-label*="Stop" i]', 'button[aria-label*="إيقاف"]', "mat-progress-bar", '[role="progressbar"]'],
                "image", ["model-response img", "generated-image img", "single-image img", "message-content img", "response-container img"], 300)},
            "selftest": {"composer": _GEMINI_COMPOSER},
        },
        "chatgpt": {
            "label": "ChatGPT", "adapter_version": 3, "verified": False,
            "hosts": ["chatgpt.com"], "newUrl": "https://chatgpt.com/",
            "kinds": {"image": _kind(
                "https://chatgpt.com/",
                [_attach(),
                 _type(_CHATGPT_COMPOSER),
                 _click(['button[data-testid="send-button"]', 'button[aria-label*="Send" i]', 'button[aria-label*="إرسال"]'])],
                ['button[data-testid="stop-button"]', 'button[aria-label*="Stop" i]', 'button[aria-label*="إيقاف"]'],
                "image", ['article img[alt*="Generated" i]', 'article img[src*="files"]', "article img"], 300)},
            "selftest": {"composer": _CHATGPT_COMPOSER},
        },
        "aistudio": {
            "label": "AI Studio", "adapter_version": 2, "verified": False,
            "hosts": ["aistudio.google.com"], "newUrl": "https://aistudio.google.com/prompts/new_chat",
            "kinds": {"image": _kind(
                "https://aistudio.google.com/prompts/new_chat",
                [_attach(),
                 _type(_AISTUDIO_COMPOSER),
                 _click(["ms-run-button button", "run-button button", 'button[aria-label*="Run" i]', "button::contains(Run)"])],
                ['button[aria-label*="Stop" i]', '[role="progressbar"]', "mat-progress-bar"],
                "image", ["ms-chat-turn img", 'img[src^="blob:"]', 'img[src^="data:image"]'], 300)},
            "selftest": {"composer": _AISTUDIO_COMPOSER},
        },
        "flow": {
            "label": "Flow", "adapter_version": 2, "verified": False,
            "hosts": ["flow.google.com"], "newUrl": _FLOW_URL,
            "kinds": {
                "video": _kind(
                    _FLOW_URL,
                    [*_FLOW_NEW_PROJECT,
                     *_flow_prep("Video", [_click(['button[role="radio"]::contains(Frames)'], True, needs="refs", **{"if": "unpressed", "waitMs": 2000})]),
                     *_flow_send_tail()],
                    _FLOW_BUSY, "video", ["video[src]", "video source", "video"], 900, download=["a[download]"]),
                "image": _kind(
                    _FLOW_URL,
                    [*_FLOW_NEW_PROJECT, *_flow_prep("Image"), *_flow_send_tail()],
                    _FLOW_BUSY, "image", ['img[alt*="Tile displaying" i]', 'img[src*="/asb/"]'], 300),
            },
            "selftest": {"composer": [*_FLOW_COMPOSER, "button::contains(New project)"]},     # مشروع مفتوح ← الصندوق؛ الرئيسية ← زر «New project»
        },
        "flowmusic": {
            "label": "Flow Music", "adapter_version": 2, "verified": False,
            "hosts": ["flowmusic.app", "www.flowmusic.app"], "newUrl": _FLOWMUSIC_URL,
            "kinds": {"music": _kind(
                _FLOWMUSIC_URL,
                [_type(_FLOWMUSIC_COMPOSER),
                 _click(['button[aria-label="Send message"]'])],
                ['[role="progressbar"]', '[aria-busy="true"]'],
                "audio", ["audio[src]", "audio source", "audio"], 300, download=["a[download][href]"], reveal=['button[aria-label*="Play" i]'])},
            "selftest": {"composer": _FLOWMUSIC_COMPOSER},
        },
        "elevenlabs": {
            "label": "ElevenLabs", "adapter_version": 2, "verified": False,
            "hosts": ["elevenlabs.io"], "newUrl": "https://elevenlabs.io/app/speech-synthesis/text-to-speech",
            "kinds": {
                "voice": _kind(
                    "https://elevenlabs.io/app/speech-synthesis/text-to-speech",
                    [_type(["textarea"]),
                     _click(['button[aria-label*="Generate" i]', 'button[data-testid*="generate" i]', "button::contains(Generate speech)", 'button[type="submit"]'])],
                    ['[role="progressbar"]'], "audio", ["audio[src]", "audio source"], 180),
                "ahat": _kind(
                    "https://elevenlabs.io/app/sound-effects/generate",
                    [{"do": "type", "sel": ['input[aria-label*="Duration" i]'], "text": "{seconds}", "optional": True, "waitMs": 2000},
                     _type(["textarea"]),
                     _click(['button[aria-label*="Generate" i]', 'button[data-testid*="generate" i]', "button::contains(Generate sound effect)", 'button[type="submit"]'])],
                    ['[role="progressbar"]'], "audio", ["audio[src]", "audio source"], 180),
            },
            "selftest": {"composer": ["textarea"]},
        },
    },
}


# ── مسارات التخزين ──────────────────────────────────────────────────────
def _dir() -> Path:
    return Path(config.LIBRARY_DIR) / "ext"


def adapters_path() -> Path:
    return _dir() / "adapters.json"


def selftest_path() -> Path:
    return _dir() / "selftest.json"


def _write_json(p: Path, data: dict) -> None:
    """كتابة ذرّية: ملف مؤقت ثم استبدال، فما بيضل ملف نص مكتوب."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _read_overlay() -> dict:
    p = adapters_path()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return {"version": int(d.get("version") or DEFAULTS_VERSION),
                        "sites": d.get("sites") if isinstance(d.get("sites"), dict) else {}}
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return {"version": DEFAULTS_VERSION, "sites": {}}


# ── الدمج ───────────────────────────────────────────────────────────────
def _merge(base: dict, patch: dict) -> dict:
    """دمج عميق على base: القواميس بتندمج، والقوائم والقيم بتستبدل، و None بتحذف المفتاح."""
    for k, v in patch.items():
        if v is None:
            base.pop(k, None)
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def _merge_overlay(old: dict, patch: dict) -> dict:
    """نفس الدمج بس بيحافظ على علامة الحذف (None) عشان تضل مطبّقة فوق DEFAULTS."""
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(old.get(k), dict):
            _merge_overlay(old[k], v)
        else:
            old[k] = copy.deepcopy(v)
    return old


def _merged_sites(overlay_sites: dict) -> dict:
    sites = copy.deepcopy(DEFAULTS["sites"])
    known = {k: v for k, v in overlay_sites.items() if k in SITES and isinstance(v, dict)}
    return _merge(sites, known)


def load() -> dict:
    ov = _read_overlay()
    return {"version": ov["version"], "sites": _merged_sites(ov["sites"])}


# ── التحقق ──────────────────────────────────────────────────────────────
def _fail(msg: str):
    raise ExtConfigError(msg)


def _check_sel(where: str, sel, *, allow_empty: bool = False) -> None:
    if not isinstance(sel, list) or (not sel and not allow_empty) or len(sel) > 12:
        _fail(f"{where}: المحدّدات لازم تكون قائمة من 1 إلى 12")
    for s in sel:
        if not isinstance(s, str) or not s.strip() or len(s) > 300:
            _fail(f"{where}: محدّد غير صالح")
        if "password" in s.lower():
            _fail(f"{where}: ممنوع محدّد يلمس حقول كلمات السر")
        if _DANGER_RX.search(s):
            _fail(f"{where}: ممنوع محدّد يستهدف حذف أو شراء أو ترقية أو خروج (الإضافة بتولّد بس)")


def _host_ok(url: str, hosts: list[str]) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme == "https" and bool(u.hostname) and u.hostname.lower() in hosts


def validate_site(name: str, site: dict) -> None:
    if name not in SITES:
        _fail(f"موقع غير معروف: {name}")
    if not isinstance(site, dict):
        _fail(f"{name}: الإعداد لازم يكون كائن")
    extra = set(site) - SITE_KEYS
    if extra:
        _fail(f"{name}: حقول غير معروفة: {sorted(extra)}")
    if not isinstance(site.get("label"), str) or not site["label"].strip() or len(site["label"]) > 40:
        _fail(f"{name}: الاسم (label) مطلوب وأقصر من 40 حرف")
    av = site.get("adapter_version")
    if not isinstance(av, int) or isinstance(av, bool) or av < 0:
        _fail(f"{name}: adapter_version لازم رقم صحيح")
    if not isinstance(site.get("verified"), bool):
        _fail(f"{name}: verified لازم true أو false")
    hosts = site.get("hosts")
    if (not isinstance(hosts, list) or not hosts or len(hosts) > 5
            or not all(isinstance(h, str) and _HOST_RX.match(h) for h in hosts)):
        _fail(f"{name}: hosts لازم تكون أسماء مضيف صالحة بحروف صغيرة")
    if not _host_ok(site.get("newUrl") or "", hosts):
        _fail(f"{name}: newUrl لازم https على مضيف معلن بالموقع")
    kinds = site.get("kinds")
    if not isinstance(kinds, dict):
        _fail(f"{name}: kinds لازم تكون كائن")
    for kind, spec in kinds.items():
        if kind not in KINDS:
            _fail(f"{name}: نوع شغل غير معروف: {kind}")
        _validate_kind(name, kind, spec, hosts)
    st = site.get("selftest", {})
    if not isinstance(st, dict) or len(st) > 10:
        _fail(f"{name}: selftest لازم يكون كائن")
    for k, sel in st.items():
        if not isinstance(k, str) or not k or len(k) > 40:
            _fail(f"{name}: اسم فحص غير صالح")
        _check_sel(f"{name}.selftest.{k}", sel)


def _validate_kind(name: str, kind: str, spec, hosts: list[str]) -> None:
    w = f"{name}.{kind}"
    if not isinstance(spec, dict):
        _fail(f"{w}: لازم كائن")
    extra = set(spec) - KIND_KEYS
    if extra:
        _fail(f"{w}: حقول غير معروفة: {sorted(extra)}")
    if not _host_ok(spec.get("url") or "", hosts):
        _fail(f"{w}: url لازم https على مضيف معلن بالموقع")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps or len(steps) > 30:
        _fail(f"{w}: steps لازم تكون قائمة من 1 إلى 30 خطوة")
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict) or set(s) - STEP_KEYS:
            _fail(f"{w}: خطوة {i} فيها حقول غير معروفة")
        if s.get("do") not in STEP_DO:
            _fail(f"{w}: خطوة {i}: do لازم واحد من {'/'.join(STEP_DO)}")
        if "optional" in s and not isinstance(s["optional"], bool):
            _fail(f"{w}: خطوة {i}: optional لازم true أو false")
        if s["do"] == "wait":
            ms = s.get("ms")
            if not isinstance(ms, (int, float)) or isinstance(ms, bool) or not 0 <= ms <= 120000:
                _fail(f"{w}: خطوة {i}: ms لازم بين 0 و120000")
        else:
            _check_sel(f"{w}: خطوة {i}", s.get("sel"))
        if "needs" in s and s["needs"] not in STEP_NEEDS:
            _fail(f"{w}: خطوة {i}: needs لازم {'/'.join(STEP_NEEDS)}")
        if "if" in s and (s["do"] != "click" or s["if"] not in STEP_IF):
            _fail(f"{w}: خطوة {i}: if بس للنقر وبقيمة {'/'.join(STEP_IF)}")
        if "via" in s and (s["do"] != "attach" or s["via"] not in ATTACH_VIA):
            _fail(f"{w}: خطوة {i}: via بس للإرفاق وبقيمة {'/'.join(ATTACH_VIA)}")
        if "waitMs" in s and (not isinstance(s["waitMs"], (int, float)) or isinstance(s["waitMs"], bool) or not 200 <= s["waitMs"] <= 30000):
            _fail(f"{w}: خطوة {i}: waitMs لازم بين 200 و30000")
        if s["do"] == "type" and (not isinstance(s.get("text"), str) or not s["text"] or len(s["text"]) > 2000):
            _fail(f"{w}: خطوة {i}: النص مطلوب")
    if "busy" in spec:
        _check_sel(f"{w}.busy", spec["busy"], allow_empty=True)
    res = spec.get("result")
    if not isinstance(res, dict) or set(res) - RESULT_KEYS:
        _fail(f"{w}: result لازم كائن بحقول معروفة")
    if res.get("type") not in RESULT_TYPES:
        _fail(f"{w}: result.type لازم واحد من {'/'.join(RESULT_TYPES)}")
    if res["type"] != RESULT_FOR_KIND[kind]:
        _fail(f"{w}: نتيجة هالنوع لازم تكون {RESULT_FOR_KIND[kind]}")
    _check_sel(f"{w}.result", res.get("sel"))
    if "download" in res:
        _check_sel(f"{w}.result.download", res["download"], allow_empty=True)
    if "reveal" in res:
        _check_sel(f"{w}.result.reveal", res["reveal"], allow_empty=True)
    t = spec.get("timeoutSec")
    if not isinstance(t, (int, float)) or isinstance(t, bool) or not 5 <= t <= 3600:
        _fail(f"{w}: timeoutSec لازم بين 5 و3600")


def validate_all(sites: dict) -> None:
    for name, site in sites.items():
        validate_site(name, site)


# ── الحفظ ───────────────────────────────────────────────────────────────
def save_patch(patch: dict) -> dict:
    """يدمج تعديل جزئي {sites:{<site>:{...}}} فوق الإعداد، بعد التحقق، وبيرفع version."""
    if not isinstance(patch, dict):
        _fail("جسم الطلب لازم يكون كائن")
    extra = set(patch) - {"sites", "version"}
    if extra:
        _fail(f"حقول غير معروفة: {sorted(extra)}")
    psites = patch.get("sites")
    if not isinstance(psites, dict) or not psites:
        _fail("sites مطلوبة: {sites:{<الموقع>:{...}}}")
    for name, sp in psites.items():
        if name not in SITES:
            _fail(f"موقع غير معروف: {name}")
        if not isinstance(sp, dict):
            _fail(f"{name}: التعديل لازم يكون كائن")
    ov = _read_overlay()
    new_sites = _merge_overlay(copy.deepcopy(ov["sites"]), psites)
    merged = _merged_sites(new_sites)
    validate_all(merged)                       # بنتحقق من الناتج النهائي كامل مش من التعديل بس
    _write_json(adapters_path(), {"version": ov["version"] + 1, "sites": new_sites})
    return load()


def sites_summary() -> dict:
    """ملخص للواجهة: لكل موقع الأنواع اللي بيدعمها وهل هو مجرّب ورقم محوّله."""
    cfg = load()
    return {n: {"kinds": list(s.get("kinds", {})), "verified": bool(s.get("verified")),
                "adapter_version": s.get("adapter_version", 0), "label": s.get("label", n),
                "hosts": list(s.get("hosts", [])), "newUrl": s.get("newUrl", "")}
            for n, s in cfg["sites"].items()}


def site_label(site: str) -> str:
    s = load()["sites"].get(site) or {}
    return s.get("label") or site


def site_kinds(site: str) -> list[str]:
    return list((load()["sites"].get(site) or {}).get("kinds", {}))


# ── الفحص الذاتي ────────────────────────────────────────────────────────
def record_selftest(site: str, kind, ok, adapter_version, missing) -> dict:
    if site not in SITES:
        _fail(f"موقع غير معروف: {site}")
    if kind is not None and kind not in KINDS:
        _fail(f"نوع شغل غير معروف: {kind}")
    if not isinstance(ok, bool):
        _fail("ok لازم true أو false")
    if not isinstance(adapter_version, int) or isinstance(adapter_version, bool) or adapter_version < 0:
        _fail("adapter_version لازم رقم صحيح")
    if (not isinstance(missing, list) or len(missing) > 50
            or not all(isinstance(m, str) and len(m) <= 200 for m in missing)):
        _fail("missing لازم قائمة نصوص قصيرة")
    rec = {"site": site, "kind": kind, "ok": ok, "adapter_version": adapter_version,
           "missing": list(missing), "checked_at": _now()}
    p = selftest_path()
    data = {"results": {}}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"results": {}}
    data.setdefault("results", {})[f"{site}:{kind or '*'}"] = rec
    _write_json(p, data)
    return rec


def selftest_results() -> list[dict]:
    p = selftest_path()
    if not p.exists():
        return []
    try:
        res = json.loads(p.read_text(encoding="utf-8")).get("results", {})
    except json.JSONDecodeError:
        return []
    return sorted(res.values(), key=lambda r: (r.get("site", ""), r.get("kind") or ""))


# ── تقارير بنية الصفحة عند الوقوف (بدون محتوى) ─────────────────────────────
DIAG_MAX = 30
DIAG_MAX_BYTES = 24000


def diag_path() -> Path:
    return _dir() / "diag.json"


def record_diag(site, kind, code, reason, step, diag) -> dict:
    """الإضافة بتبعت بنية الصفحة (تسميات أزرار وصناديق كتابة ووسائط) لما توقف بـ unknown_page/timeout/download_failed،
    عشان تنصلّح المحدّدات بدون تصوير. بنحتفظ بآخر 30 وبنقصّ أي تقرير كبير."""
    if site not in SITES:
        _fail(f"موقع غير معروف: {site}")
    if kind is not None and kind not in KINDS:
        _fail(f"نوع شغل غير معروف: {kind}")
    if not isinstance(diag, dict):
        _fail("diag لازم كائن")
    clean = {k: diag[k] for k in ("host", "path", "composers", "buttons", "fileInputs", "media", "dialogs", "captchaVisible") if k in diag}
    raw = json.dumps(clean, ensure_ascii=False)
    while len(raw.encode("utf-8")) > DIAG_MAX_BYTES and clean.get("buttons"):
        clean["buttons"] = clean["buttons"][: max(0, len(clean["buttons"]) // 2)]
        raw = json.dumps(clean, ensure_ascii=False)
    if len(raw.encode("utf-8")) > DIAG_MAX_BYTES:
        _fail("التقرير كبير")
    rec = {"site": site, "kind": kind, "code": str(code or "")[:40], "reason": str(reason or "")[:300], "step": str(step or "")[:60],
           "at": _now(), "diag": clean}
    p = diag_path()
    items = []
    if p.exists():
        try:
            items = json.loads(p.read_text(encoding="utf-8")).get("items", [])
        except (json.JSONDecodeError, AttributeError):
            items = []
    items.insert(0, rec)
    _write_json(p, {"items": items[:DIAG_MAX]})
    return {"ok": True}


def diag_results(limit: int = 10) -> list[dict]:
    p = diag_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("items", [])[: max(1, min(int(limit), DIAG_MAX))]
    except (json.JSONDecodeError, AttributeError, ValueError):
        return []
