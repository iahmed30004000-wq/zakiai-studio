"""
خطة الحصاد للفئات الناقصة + طابور المرشّحين (مراجعة بشرية قبل أي استخراج).

  · خطة الفئة: استعلامات بحث عربية/إنجليزية جاهزة (قاموس بالكود لكل فئة) + روابط بحث
    جاهزة لمكتبة إعلانات ميتا وتيك توك + أوامر الحصاد الآلي إذا APIFY_TOKEN موجود.
    بدون التوكن: الخطة بتنتج الاستعلامات وخطوات يدوية، وبتقدر تضيف روابط بإيدك — بدون انهيار.
  · الطابور library/candidates/queue.json — كل مرشّح: pending ← approved | rejected ← extracted.
    الموافقة (approve) هي اللي بتبدأ job الاستخراج (stage1_extract.py <url>)؛ ما في استخراج تلقائي.

هالوحدة ما بتسحب شي بحالها: الحصاد الفعلي بيمرّ من stage0_harvest.py (Apify) أو بروابط
بتضيفها يدوياً.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import config
import taxonomy

STATUSES = ("pending", "approved", "rejected", "extracted")

# استعلامات جاهزة لكل فئة: عربي (للسوق) + إنجليزي (لمكتبات الإعلانات الدولية) + هاشتاقات.
CATEGORY_QUERIES: dict[str, dict[str, list[str]]] = {
    "fragrance": {
        "ar": ["عطر رجالي فاخر", "عطر نسائي ثابت", "عطور بديلة الماركات", "عطر عود ومسك"],
        "en": ["perfume", "long lasting fragrance", "perfume dupe", "oud perfume"],
        "hashtags": ["عطور", "perfume"],
    },
    "skincare": {
        "ar": ["سيروم للبشرة", "كريم ترطيب البشرة", "علاج حب الشباب", "تفتيح البشرة"],
        "en": ["skincare serum", "face cream", "acne treatment", "skin brightening"],
        "hashtags": ["العناية_بالبشرة", "skincare"],
    },
    "hair_removal": {
        "ar": ["كريم إزالة الشعر", "إزالة الشعر بدون ألم", "جهاز إزالة الشعر", "إزالة شعر الوجه"],
        "en": ["hair removal cream", "painless hair removal", "hair remover device"],
        "hashtags": ["ازالة_الشعر", "hairremoval"],
    },
    "hair_care": {
        "ar": ["زيت تطويل الشعر", "علاج تساقط الشعر", "سيروم للشعر", "ماسك الشعر"],
        "en": ["hair growth oil", "hair loss treatment", "hair serum"],
        "hashtags": ["العناية_بالشعر", "haircare"],
    },
    "makeup": {
        "ar": ["مكياج طبيعي", "أحمر شفاه يدوم", "كريم أساس", "أدوات مكياج"],
        "en": ["makeup", "long wear lipstick", "foundation makeup"],
        "hashtags": ["مكياج", "makeup"],
    },
    "eye_care": {
        "ar": ["قطرة عين للجفاف", "علاج جفاف العين", "إجهاد العين من الشاشات", "الهالات السوداء تحت العين"],
        "en": ["eye drops dry eyes", "eye strain relief", "eye care"],
        "hashtags": ["العناية_بالعين", "eyecare"],
    },
    "ear_care": {
        "ar": ["تنظيف الأذن", "قطرة أذن", "إزالة شمع الأذن", "جهاز تنظيف الأذن"],
        "en": ["ear wax removal", "ear drops", "ear cleaner"],
        "hashtags": ["earcare", "تنظيف_الاذن"],
    },
    "oral_care": {
        "ar": ["تبييض الأسنان", "معجون أسنان طبيعي", "علاج رائحة الفم", "جهاز تنظيف الأسنان"],
        "en": ["teeth whitening", "oral care", "bad breath solution"],
        "hashtags": ["تبييض_الاسنان", "teethwhitening"],
    },
    "supplements": {
        "ar": ["مكمل غذائي", "فيتامينات للطاقة", "مكمل لزيادة الوزن", "مكمل للتركيز"],
        "en": ["dietary supplement", "energy vitamins", "weight gain supplement"],
        "hashtags": ["مكملات", "supplements"],
    },
    "joint_pain": {
        "ar": ["علاج آلام المفاصل", "كريم لآلام الظهر", "مسكن طبيعي للركبة", "آلام الرقبة"],
        "en": ["joint pain relief", "back pain cream", "knee pain"],
        "hashtags": ["الم_المفاصل", "jointpain"],
    },
    "wellness_device": {
        "ar": ["جهاز مساج", "جهاز تدليك الرقبة", "جهاز علاج طبيعي منزلي", "حزام تنحيف"],
        "en": ["massager device", "neck massager", "home therapy device"],
        "hashtags": ["جهاز_مساج", "massager"],
    },
    "home_kitchen": {
        "ar": ["أدوات مطبخ", "خلاط كهربائي", "منظم مطبخ", "قطاعة خضار"],
        "en": ["kitchen gadget", "vegetable chopper", "kitchen organizer"],
        "hashtags": ["ادوات_مطبخ", "kitchengadgets"],
    },
    "cleaning": {
        "ar": ["منظف متعدد الاستخدامات", "إزالة البقع", "منظف الحمام", "فرشاة تنظيف"],
        "en": ["cleaning product", "stain remover", "bathroom cleaner"],
        "hashtags": ["تنظيف", "cleaninghacks"],
    },
    "gadgets": {
        "ar": ["اكسسوارات جوال", "شاحن لاسلكي", "سماعات بلوتوث", "أدوات إلكترونية ذكية"],
        "en": ["phone gadget", "wireless charger", "smart gadget"],
        "hashtags": ["اجهزة", "gadgets"],
    },
    "apparel": {
        "ar": ["ملابس رجالية", "عبايات", "ملابس رياضية", "أحذية"],
        "en": ["men's clothing", "abaya", "sportswear"],
        "hashtags": ["ازياء", "fashion"],
    },
    "accessories": {
        "ar": ["ساعات", "إكسسوارات نسائية", "محافظ", "نظارات"],
        "en": ["watches", "women accessories", "jewelry"],
        "hashtags": ["اكسسوارات", "accessories"],
    },
    "other": {
        "ar": ["منتج مبتكر", "عرض خاص الدفع عند الاستلام"],
        "en": ["cash on delivery product", "trending product"],
        "hashtags": ["الدفع_عند_الاستلام", "trendingproducts"],
    },
}

_PLATFORM_HOSTS = (
    ("tiktok", ("tiktok.com",)),
    ("meta", ("facebook.com", "fb.watch", "fb.com", "fb.me")),
    ("instagram", ("instagram.com",)),
    ("youtube", ("youtube.com", "youtu.be")),
)


class QueueError(Exception):
    """خطأ متوقع بالطابور — الرسالة عربية."""


def apify_configured() -> bool:
    return bool(os.environ.get("APIFY_TOKEN"))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─────────────────────────── الطابور ───────────────────────────


def queue_path() -> Path:
    return Path(config.CANDIDATES_DIR) / "queue.json"


def load_queue() -> dict:
    p = queue_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
        except json.JSONDecodeError:
            pass
    return {"items": []}


def save_queue(data: dict) -> None:
    p = queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def normalize_url(url: str) -> str:
    u = str(url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise QueueError("الرابط لازم يبدأ بـ http:// أو https://")
    return parsed._replace(fragment="").geturl()


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for name, hosts in _PLATFORM_HOSTS:
        if any(host == h or host.endswith("." + h) for h in hosts):
            return name
    return "other"


def _id_for(url: str) -> str:
    key = urlparse(url)._replace(scheme="https", netloc=urlparse(url).netloc.lower()).geturl().rstrip("/")
    return "c_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def add_candidate(url: str, category: str, source: str = "manual", note: str = "",
                  query: str = "", *, _data: dict | None = None) -> dict:
    """يضيف مرشّحاً بحالة pending. بيرمي QueueError للرابط الخاطئ/المكرر/الفئة غير المعروفة."""
    slug = taxonomy.normalize_category(category).value
    if not slug:
        raise QueueError("الفئة لازم تكون من القائمة المغلقة (slug صحيح)")
    url = normalize_url(url)
    data = _data if _data is not None else load_queue()
    cid = _id_for(url)
    if any(i["id"] == cid for i in data["items"]):
        raise QueueError("الرابط موجود مسبقاً بالطابور")
    item = {
        "id": cid, "category": slug, "source": source, "url": url,
        "platform": detect_platform(url), "status": "pending", "note": note or "",
        "query": query or "", "created_at": _now(), "updated_at": _now(),
    }
    data["items"].append(item)
    if _data is None:
        save_queue(data)
    return item


def add_candidates(category: str, source: str, candidates: list[dict], query: str = "") -> dict:
    """للحصاد الآلي: يضيف قائمة (بتخطّى المكرر) ← {added, skipped}."""
    data = load_queue()
    added = skipped = 0
    for c in candidates:
        if not c.get("url"):
            skipped += 1
            continue
        note = f"مشاهدات {c.get('views', 0):,} · لايكات {c.get('likes', 0):,}" if c.get("views") else ""
        try:
            add_candidate(c["url"], category, source, note, query, _data=data)
            added += 1
        except QueueError:
            skipped += 1
    save_queue(data)
    return {"added": added, "skipped": skipped}


def _refresh_from_jobs(data: dict) -> bool:
    """approved + job خلص بنجاح ← extracted. بيرجع true لو تغيّر شي."""
    changed = False
    try:
        from web import jobs
    except Exception:
        return False
    for it in data["items"]:
        if it["status"] != "approved" or not it.get("job_id"):
            continue
        try:
            job = jobs.get_job(it["job_id"])
        except Exception:
            continue
        if not job:
            continue
        it["job_status"] = job.get("status")
        if job.get("status") == "done":
            it["status"], it["updated_at"] = "extracted", _now()
            changed = True
        elif job.get("status") in ("failed", "cancelled"):
            it["note"] = f"فشل الاستخراج: {job.get('error') or job.get('status')}"
            changed = True
    return changed


def list_items(status: str | None = None, category: str | None = None) -> list[dict]:
    if status and status not in STATUSES:
        raise QueueError(f"حالة غير معروفة: {status}")
    data = load_queue()
    if _refresh_from_jobs(data):
        save_queue(data)
    return [i for i in data["items"]
            if (not status or i["status"] == status) and (not category or i["category"] == category)]


def _find(data: dict, item_id: str) -> dict:
    it = next((i for i in data["items"] if i["id"] == item_id), None)
    if not it:
        raise QueueError("المرشّح غير موجود")
    return it


def approve(item_id: str) -> dict:
    """موافقة بشرية: بتبدأ job الاستخراج. المُستخرَج/المرفوض ما بيتوافق عليه من جديد."""
    from web import jobs
    data = load_queue()
    it = _find(data, item_id)
    retry = it["status"] == "approved" and it.get("job_status") in ("failed", "cancelled")
    if it["status"] != "pending" and not retry:
        raise QueueError(f"ما بتنفع الموافقة: الحالة الحالية «{it['status']}»")
    job_id = jobs.create_job("extract", f"استخراج (مرشّح): {it['url'][:60]}",
                             ["stage1_extract.py", it["url"]])
    it.update(status="approved", job_id=job_id, job_status="queued", updated_at=_now())
    save_queue(data)
    return it


def reject(item_id: str) -> dict:
    data = load_queue()
    it = _find(data, item_id)
    if it["status"] in ("extracted",):
        raise QueueError("انستخرج مسبقاً — ما بينرفض")
    if it["status"] == "approved" and it.get("job_status") in ("queued", "running", "paused"):
        raise QueueError("الاستخراج شغّال — أوقف المهمة من صفحة المهام أولاً")
    it.update(status="rejected", updated_at=_now())
    save_queue(data)
    return it


# ─────────────────────────── الخطة ───────────────────────────


def _known_countries(slug: str) -> list[str]:
    """بلدان المنتجات الفعلية بهالفئة."""
    import brief as brief_mod
    out: list[str] = []
    for f in sorted(Path(config.PRODUCTS_DIR).glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            b = brief_mod.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if b.get("category") == slug and b.get("country") and b["country"] not in out:
            out.append(b["country"])
    return out


def _meta_url(query: str, country: str) -> str:
    return ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
            f"&country={country}&media_type=video&q={quote(query)}&search_type=keyword_unordered")


def _tiktok_url(query: str) -> str:
    return f"https://www.tiktok.com/search?q={quote(query)}"


def plan_for_category(slug: str, missing: int | None = None, have: int | None = None) -> dict:
    """خطة حصاد لفئة. بتشتغل بدون شبكة وبدون توكن."""
    if slug not in taxonomy.CATEGORIES:
        raise QueueError("فئة غير معروفة")
    q = CATEGORY_QUERIES.get(slug) or CATEGORY_QUERIES["other"]
    countries = _known_countries(slug)
    auto = apify_configured()
    label = taxonomy.CATEGORY_LABELS.get(slug, slug)
    all_queries = q["ar"] + q["en"]

    meta_links = [{"query": qq, "country": cc, "url": _meta_url(qq, cc)}
                  for qq in all_queries for cc in (countries or ["ALL"])]
    tiktok_links = [{"query": qq, "url": _tiktok_url(qq)} for qq in all_queries]

    sources = [
        {"source": "adlibrary", "platform": "meta", "label": "مكتبة إعلانات ميتا",
         "links": meta_links, "commands": []},
        {"source": "tiktok", "platform": "tiktok", "label": "تيك توك",
         "links": tiktok_links, "hashtags": q["hashtags"], "commands": []},
        {"source": "links", "platform": "any", "label": "روابط يدوية",
         "instructions": "الصق رابط أي إعلان فيديو ناجح بالفئة عبر «إضافة رابط» — بينضاف كمرشّح بانتظار موافقتك."},
    ]
    if auto:
        for qq in q["ar"][:2] + q["en"][:1]:
            for cc in (countries[:1] or []):
                sources[0]["commands"].append(
                    ["stage0_harvest.py", "adlibrary", "--query", qq, "--country", cc,
                     "--category", slug])
            if not countries:
                sources[0]["commands"].append(
                    ["stage0_harvest.py", "adlibrary", "--query", qq, "--category", slug])
            sources[1]["commands"].append(
                ["stage0_harvest.py", "tiktok", "--query", qq, "--category", slug])

    if auto:
        manual = ["الحصاد الآلي متاح (APIFY_TOKEN موجود): شغّل الخطة وراجع المرشّحين بالطابور قبل الموافقة."]
    else:
        manual = [
            "ما في APIFY_TOKEN — الحصاد الآلي معطّل، والخطة يدوية:",
            "1) افتح روابط البحث أدناه (مكتبة ميتا / تيك توك) وابحث بالاستعلامات المقترحة.",
            "2) اختر إعلانات الفيديو الشغّالة من فترة طويلة أو ذات التفاعل العالي.",
            "3) الصق روابطها بـ «إضافة رابط» — كل رابط بيصير مرشّح pending.",
            "4) راجع المرشّحين ووافق على اللي بدك تستخرجه — الموافقة بتبدأ الاستخراج.",
        ]

    return {
        "category": slug, "label": label, "missing": missing, "have": have,
        "quota": getattr(config, "LIBRARY_QUOTA", 10),
        "apify_configured": auto,
        "queries": {"ar": q["ar"], "en": q["en"], "hashtags": q["hashtags"]},
        "countries": countries,
        "sources": sources,
        "manual_steps": manual,
        "created_at": _now(),
    }


def plans_for_gaps() -> list[dict]:
    import library_stats
    cov = library_stats.coverage()
    have = {r["category"]: r["count"] for r in cov["per_category"]}
    return [plan_for_category(g["category"], g["missing"], have.get(g["category"]))
            for g in cov["gaps"]]


def run_plan(slug: str) -> list[str]:
    """يبدأ jobs الحصاد الآلي (Apify) لفئة. بيرمي QueueError بدون توكن."""
    if not apify_configured():
        raise QueueError("ما في APIFY_TOKEN — الحصاد الآلي غير متاح، استخدم الخطة اليدوية")
    from web import jobs
    plan = plan_for_category(slug)
    ids = []
    for src in plan["sources"]:
        for cmd in src.get("commands", []):
            ids.append(jobs.create_job("harvest", f"حصاد {plan['label']}: {cmd[cmd.index('--query') + 1]}", cmd))
    return ids
