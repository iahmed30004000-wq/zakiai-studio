#!/usr/bin/env python3
"""
STAGE 0 — HARVESTER
يحصد الفيديوهات الناجحة أوتوماتيكياً من تيك توك / ريلز / مكتبة إعلانات فيسبوك
عبر Apify، يفلترها بعتبات الأداء، ويطلع links.txt جاهز للمرحلة 1.

الاستخدام:
    python stage0_harvest.py tiktok --query "كريم ازالة الشعر" --limit 60
    python stage0_harvest.py tiktok --hashtag hairremoval --limit 100
    python stage0_harvest.py adlibrary --query "كريم" --country SY
    python stage0_harvest.py reels --query "hair removal cream"
    python stage0_harvest.py --merge          # يدمج كل الحصادات في links.txt
    python stage0_harvest.py tiktok --query "عطر" --category fragrance
        # --category: المرشّحين بينضافوا لطابور المراجعة (library/candidates/queue.json)
        # كـ pending — الاستخراج بيبدأ بعد موافقتك البشرية بس.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# كونسول ويندوز افتراضياً cp1252 وبيفشل مع العربي
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from config import (
    CANDIDATES_DIR,
    LIBRARY_DIR,
    APIFY_ACTORS,
    APIFY_TIMEOUT_SEC,
    MIN_VIEWS,
    MIN_LIKES,
    MIN_ENGAGEMENT_RATE,
    MAX_AGE_DAYS,
    HARVEST_TOP_N,
)


def token() -> str:
    t = os.environ.get("APIFY_TOKEN")
    if not t:
        sys.exit("[!] حدّد المفتاح:  export APIFY_TOKEN=apify_api_...")
    return t


def call_apify(actor_id: str, payload: dict) -> list:
    try:
        import requests
    except ImportError:
        sys.exit("[!] ثبّت requests:  pip install requests")

    url = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
    print(f"[…] تشغيل الأكتر: {actor_id} (ممكن ياخد دقائق)")
    r = requests.post(
        url,
        params={"token": token(), "timeout": APIFY_TIMEOUT_SEC},
        json=payload,
        timeout=APIFY_TIMEOUT_SEC + 60,
    )
    if r.status_code >= 400:
        sys.exit(f"[!] Apify رجّع خطأ {r.status_code}: {r.text[:400]}")
    data = r.json()
    print(f"[i] رجع {len(data)} عنصر خام")
    return data


# ----------------------------------------------------------------------------
# التطبيع — يوحّد اختلاف حقول الأكترز
# ----------------------------------------------------------------------------


def first(item: dict, *keys):
    for k in keys:
        v = item
        for part in k.split("."):
            v = v.get(part) if isinstance(v, dict) else None
            if v is None:
                break
        if v not in (None, "", 0):
            return v
    return None


def to_int(v) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def age_days(raw) -> float:
    if not raw:
        return 0.0
    try:
        if isinstance(raw, (int, float)) or str(raw).isdigit():
            dt = datetime.fromtimestamp(int(raw), tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 86400, 1)
    except (ValueError, OSError, OverflowError):
        return 0.0


def normalize(item: dict, source: str) -> dict:
    views = to_int(first(item, "playCount", "videoPlayCount", "views", "play_count", "viewCount"))
    likes = to_int(first(item, "diggCount", "likesCount", "likes", "like_count"))
    link = first(
        item, "webVideoUrl", "url", "videoUrl", "postUrl", "snapshot.videos.0.video_hd_url", "link"
    )
    return {
        "source": source,
        "url": link,
        "author": first(item, "authorMeta.name", "authorName", "pageName", "ownerUsername", "author"),
        "caption": (first(item, "text", "caption", "description", "snapshot.body.text", "adText") or "")[:400],
        "views": views,
        "likes": likes,
        "comments": to_int(first(item, "commentCount", "commentsCount", "comments")),
        "shares": to_int(first(item, "shareCount", "sharesCount", "shares")),
        "engagement_rate": round(likes / views, 4) if views else 0.0,
        "age_days": age_days(first(item, "createTimeISO", "createTime", "timestamp", "startDate", "publishedAt")),
        "raw_id": first(item, "id", "adArchiveID", "postId", "shortCode"),
    }


# ----------------------------------------------------------------------------
# الفلترة والترتيب
# ----------------------------------------------------------------------------


def score(c: dict) -> float:
    """ترتيب مركّب: مشاهدات + تفاعل + حداثة."""
    import math

    reach = math.log10(max(c["views"], 1))
    engage = c["engagement_rate"] * 100
    fresh = max(0, 1 - (c["age_days"] / max(MAX_AGE_DAYS, 1))) if c["age_days"] else 0.5
    return round(reach * 2 + engage * 1.5 + fresh * 3, 3)


def filter_rank(cands: list) -> tuple:
    kept, dropped = [], []
    for c in cands:
        if not c["url"]:
            dropped.append((c, "بدون رابط"))
        elif c["views"] and c["views"] < MIN_VIEWS:
            dropped.append((c, f"مشاهدات {c['views']} < {MIN_VIEWS}"))
        elif c["likes"] and c["likes"] < MIN_LIKES:
            dropped.append((c, f"لايكات {c['likes']} < {MIN_LIKES}"))
        elif c["engagement_rate"] and c["engagement_rate"] < MIN_ENGAGEMENT_RATE:
            dropped.append((c, f"تفاعل {c['engagement_rate']} < {MIN_ENGAGEMENT_RATE}"))
        elif MAX_AGE_DAYS and c["age_days"] > MAX_AGE_DAYS:
            dropped.append((c, f"عمره {c['age_days']} يوم"))
        else:
            c["score"] = score(c)
            kept.append(c)

    # إزالة التكرار بالرابط
    seen, unique = set(), []
    for c in sorted(kept, key=lambda x: x["score"], reverse=True):
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)
    return unique[:HARVEST_TOP_N], dropped


# ----------------------------------------------------------------------------
# مدخلات الأكترز
# ----------------------------------------------------------------------------


def build_input(source: str, args) -> dict:
    if source == "tiktok":
        payload = {"resultsPerPage": args.limit, "shouldDownloadVideos": False}
        if args.hashtag:
            payload["hashtags"] = [args.hashtag]
        elif args.profile:
            payload["profiles"] = [args.profile]
        else:
            payload["searchQueries"] = [args.query]
        return payload

    if source == "adlibrary":
        return {
            "count": args.limit,
            "searchTerms": [args.query],
            "country": args.country,
            "activeStatus": "active",
            "adType": "all",
        }

    if source == "reels":
        return {
            "search": args.query,
            "resultsLimit": args.limit,
            "searchType": "hashtag" if args.hashtag else "user",
        }

    sys.exit(f"[!] مصدر غير مدعوم: {source}")


# ----------------------------------------------------------------------------
# التشغيل
# ----------------------------------------------------------------------------


def harvest(source: str, args) -> Path:
    actor = APIFY_ACTORS.get(source)
    if not actor:
        sys.exit(f"[!] ما في أكتر معرّف لـ {source} في config.py")

    raw = call_apify(actor, build_input(source, args))
    cands = [normalize(i, source) for i in raw if isinstance(i, dict)]
    kept, dropped = filter_rank(cands)

    print(f"\n[i] عدّى الفلتر: {len(kept)}  |  انرفض: {len(dropped)}")
    for c, why in dropped[:5]:
        print(f"    ✗ {(c['url'] or '—')[:60]} — {why}")

    Path(CANDIDATES_DIR).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out = Path(CANDIDATES_DIR) / f"{source}_{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "source": source,
                "query": args.hashtag or args.profile or args.query,
                "harvested_at": stamp,
                "filters": {
                    "min_views": MIN_VIEWS,
                    "min_likes": MIN_LIKES,
                    "min_engagement_rate": MIN_ENGAGEMENT_RATE,
                    "max_age_days": MAX_AGE_DAYS,
                },
                "kept": len(kept),
                "candidates": kept,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n[✓] {out}")
    category = getattr(args, "category", None)
    if category:
        import harvest_plan
        res = harvest_plan.add_candidates(category, source, kept,
                                          args.hashtag or args.profile or args.query or "")
        print(f"[i] طابور المراجعة: أُضيف {res['added']} مرشّح (تخطّى {res['skipped']} مكرر/بلا رابط) "
              "— بانتظار موافقتك.")
    print("\n  أعلى 5 مرشّحين:")
    for c in kept[:5]:
        print(f"    {c['score']:>6}  👁 {c['views']:>9,}  ❤ {c['likes']:>7,}  {(c['author'] or '')[:18]:<18} {c['url'][:50]}")
    return out


def merge_links() -> Path:
    files = [f for f in sorted(Path(CANDIDATES_DIR).glob("*.json")) if f.name != "queue.json"]
    if not files:
        sys.exit(f"[!] ما في حصادات في {CANDIDATES_DIR}")

    seen, rows = set(), []
    for f in files:
        for c in json.loads(f.read_text(encoding="utf-8")).get("candidates", []):
            if c["url"] and c["url"] not in seen:
                seen.add(c["url"])
                rows.append(c)

    rows.sort(key=lambda x: x.get("score", 0), reverse=True)
    out = Path(LIBRARY_DIR) / "links.txt"
    out.write_text("\n".join(c["url"] for c in rows), encoding="utf-8")
    print(f"[✓] {len(rows)} رابط فريد  →  {out}")
    print(f"    التالي:  python stage1_extract.py --batch {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 0 — حصاد الفيديوهات الناجحة")
    ap.add_argument("source", nargs="?", choices=["tiktok", "adlibrary", "reels"])
    ap.add_argument("--query", help="كلمة البحث")
    ap.add_argument("--hashtag", help="هاشتاق (تيك توك/ريلز)")
    ap.add_argument("--profile", help="حساب منافس (تيك توك)")
    ap.add_argument("--country", default="SY", help="كود الدولة لمكتبة الإعلانات")
    ap.add_argument("--limit", type=int, default=60, help="عدد النتائج المطلوب سحبها")
    ap.add_argument("--category", help="slug الفئة — بينضاف المرشّحين لطابور المراجعة")
    ap.add_argument("--merge", action="store_true", help="ادمج كل الحصادات في links.txt")
    args = ap.parse_args()

    if args.category:
        import taxonomy
        slug = taxonomy.normalize_category(args.category).value
        if not slug:
            ap.error(f"--category لازم يكون slug صحيح من: {', '.join(taxonomy.CATEGORIES)}")
        args.category = slug

    if args.merge:
        merge_links()
    elif args.source:
        if not (args.query or args.hashtag or args.profile):
            ap.error("لازم --query أو --hashtag أو --profile")
        harvest(args.source, args)
    else:
        ap.error("حدّد المصدر أو استخدم --merge")


if __name__ == "__main__":
    main()
