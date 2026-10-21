"""مكتبة الادعاءات الممنوعة القابلة للتعديل: عرض، إضافة، تعديل، حذف، استرجاع الافتراضي، وتجربة نص."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/claims")


def _call(fn, *a, **k):
    import claims
    try:
        return fn(*a, **k)
    except claims.ClaimsError as e:
        raise HTTPException(400, str(e))


@router.get("/rules")
def get_rules() -> dict:
    import claims
    import taxonomy
    st = claims.rules_state()
    return {**st, "category_labels": dict(taxonomy.CATEGORY_LABELS)}


@router.post("/rules/{group}")
def add_rule(group: str, payload: dict) -> dict:
    import claims
    return _call(claims.add_rule, group, payload.get("label"), payload.get("patterns"), payload.get("phrase"))


@router.put("/rules/{group}/{rule_id}")
def edit_rule(group: str, rule_id: str, payload: dict) -> dict:
    import claims
    return _call(claims.edit_rule, group, rule_id, payload.get("label"), payload.get("patterns"),
                 payload.get("phrase"), payload.get("enabled"))


@router.delete("/rules/{group}/{rule_id}")
def delete_rule(group: str, rule_id: str) -> dict:
    import claims
    return _call(claims.delete_rule, group, rule_id)


@router.post("/reset/{group}")
def reset_group(group: str) -> dict:
    import claims
    return _call(claims.reset_group, group)


@router.post("/try")
def try_text(payload: dict) -> dict:
    import claims
    text = str(payload.get("text") or "")
    cat = payload.get("category") or None
    return {"found": [{"issue": f["issue"], "evidence": f["evidence"]} for f in claims.try_text(text, cat)]}
