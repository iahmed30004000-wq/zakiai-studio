"""
بنك الهوكات: عرض وفلترة، إضافة هوك يدوي، نجمة، أرشفة. (الفهرس بيتبني من السيناريوهات؛ اللي بينخزّن بس اليدوي والنجمة والأرشفة.)
المفتاح: «<script_id>.<hook_id>» للهوكات اللي من السيناريوهات (VP-kama-2-v1.h2)، و«m_<رقم>» لليدوي.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/hooks-bank")


def _call(fn, *a, **k):
    import hooks_bank
    try:
        return fn(*a, **k)
    except hooks_bank.BankError as e:
        raise HTTPException(e.status, str(e))


@router.get("")
def list_hooks(product: str | None = None, type: str | None = None, star: bool = False, q: str | None = None,
               role: str | None = None, archived: bool = False) -> dict:
    import hooks_bank
    return hooks_bank.list_entries(product=product or None, type=type or None, star=star, q=q or None,
                                   include_archived=archived, role=role or None)


@router.post("")
def add_manual(payload: dict) -> dict:
    """هوك يدوي (سمعته، شفته عند منافس، أو عجبك). النوع والمنتج والملاحظة اختيارية."""
    import hooks_bank
    return {"ok": True, "entry": _call(hooks_bank.add_manual, payload.get("text"), payload.get("type"), payload.get("product"),
                                       payload.get("note") or "", by=__import__("accounts").who("owner"))}


@router.put("/{key}")
def edit_manual(key: str, payload: dict) -> dict:
    import hooks_bank
    fields = {k: payload[k] for k in ("text", "type", "product", "note") if k in payload}
    return {"ok": True, "entry": _call(hooks_bank.update_manual, key, **fields)}


@router.delete("/{key}")
def delete_manual(key: str) -> dict:
    import hooks_bank
    _call(hooks_bank.delete_manual, key)
    return {"ok": True}


@router.post("/{key}/star")
def star(key: str, payload: dict) -> dict:
    import hooks_bank
    return {"ok": True, "entry": _call(hooks_bank.set_star, key, bool(payload.get("on", True)))}


@router.post("/{key}/archive")
def archive(key: str, payload: dict) -> dict:
    import hooks_bank
    return {"ok": True, "entry": _call(hooks_bank.set_archived, key, bool(payload.get("on", True)))}
