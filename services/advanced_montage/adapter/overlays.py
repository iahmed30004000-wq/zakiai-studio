"""البطاقات (طبقات فوق الفيديو): منتج/سعر · عرض · «اطلب هلأ». كل بطاقة بتنحذف لحالها لو بياناتها فاضية."""

from __future__ import annotations

from .. import constants as C
from .captions import frame_of

_SAFE_X = C.SAFE_SIDE_PX
_SAFE_W = C.WIDTH - 2 * C.SAFE_SIDE_PX
_CARD_H = C.CARD_BOTTOM_PX - C.CARD_TOP_PX


def safe_rect() -> dict:
    """المنطقة الآمنة: كل النص الثابت لازم يكون جواتها (الـ 22٪ السفلية فاضية)."""
    return {"x": _SAFE_X, "y": 0, "w": _SAFE_W, "h": C.HEIGHT - C.SAFE_BOTTOM_PX}


def _layout(full_screen: bool = False) -> dict:
    return {
        "zone": "above_captions", "static": True, "dir": "rtl", "backdrop": full_screen,
        "box": {"x": _SAFE_X, "y": C.CARD_TOP_PX, "w": _SAFE_W, "h": _CARD_H},
    }


def plan_windows(total_ms: int, scenes: list[dict], want_product: bool, want_offer: bool) -> dict[str, tuple[int, int]]:
    """
    توقيت منطقي: «اطلب هلأ» آخر 3 ثواني، العرض قبلها (من بداية المشهد الأخير)، والسعر بالمشهد اللي قبل الأخير.
    النوافذ ما بتتداخل. لو الفيديو قصير بنزحزح للخلف.
    """
    cta_ms = min(C.CTA_MS, total_ms // 3)
    wins = {"cta": (total_ms - cta_ms, total_ms)}
    cursor_end = wins["cta"][0]
    if want_offer:
        s = scenes[-1]["start_ms"] if scenes else cursor_end - C.OFFER_MIN_MS
        st = max(0, min(s, cursor_end - C.OFFER_MIN_MS))
        wins["offer"] = (st, cursor_end)
        cursor_end = st
    if want_product:
        sc = scenes[-2] if len(scenes) >= 2 else (scenes[0] if scenes else None)
        base = sc["start_ms"] if sc else 0
        e = min(sc["end_ms"] if sc else cursor_end, base + C.PRODUCT_MS, cursor_end)
        st = base
        if e - st < C.MIN_VISIBLE_MS:                      # ما في وقت بمكانه الطبيعي: نزحزحها للخلف
            e = cursor_end
            st = max(0, e - C.PRODUCT_MS)
        wins["product"] = (st, e)
    return wins


def build_overlays(product: dict, scenes: list[dict], total_ms: int) -> tuple[list[dict], list[dict]]:
    """(overlays, dropped[{type, reason}]) — البطاقة بتنحذف بسبب مكتوب، ما بنرسم بطاقة فاضية."""
    dropped: list[dict] = []
    want_product = bool(product.get("price") and product.get("name"))
    if not want_product:
        why = "السعر فاضي بالبريف — ما بنخترع قيمة" if not product.get("price") else "اسم المنتج فاضي"
        dropped.append({"type": "product", "reason": why})
    want_offer = bool(product.get("offer") or product.get("guarantee"))
    if not want_offer:
        dropped.append({"type": "offer", "reason": "العرض والضمان فاضيين (أو مؤكّد «لا يوجد») — بلا بطاقة عرض"})

    wins = plan_windows(total_ms, scenes, want_product, want_offer)
    content = {
        "product": {"name": product.get("name", ""), "price": product.get("price", ""), "currency": product.get("currency", "")},
        "offer": {k: product[k] for k in ("offer", "guarantee", "scarcity_deadline", "stock_units") if product.get(k)},
        "cta": {"text": C.CTA_TEXT},
    }
    overlays: list[dict] = []
    for typ in ("product", "offer", "cta"):
        if typ not in wins:
            continue
        a, b = wins[typ]
        if b - a < C.MIN_VISIBLE_MS:
            dropped.append({"type": typ, "reason": "ما في وقت كافي بالفيديو لعرضها"})
            continue
        overlays.append({
            "id": f"ov_{typ}", "type": typ, "start_ms": a, "end_ms": b,
            "start_frame": frame_of(a), "end_frame": frame_of(b),
            "content": content[typ], "layout": _layout(full_screen=(typ == "cta")),
        })
    return overlays, dropped
