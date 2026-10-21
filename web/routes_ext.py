"""إضافة المتصفح متعددة المواقع: صوت · صور · تحريك · آهات · موسيقى (راجع ext_contract.md)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

import config

router = APIRouter(prefix="/api")


def _script(filename: str) -> Path:
    p = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return p


def _auth(tok: str | None) -> None:
    import ext_bridge
    if not ext_bridge.verify(tok):
        raise HTTPException(401, "توكن الإضافة غير صالح — انسخه من إعدادات الاستوديو")


def _need_token(x_vp_ext_token: str | None = Header(None)) -> None:
    """dependency: بيشتغل قبل فحص الجسم، فالطلب بلا توكن = 401 دايماً."""
    _auth(x_vp_ext_token)


def _e(fn, *a, **k):
    import ext_bridge
    import ext_config
    try:
        return fn(*a, **k)
    except (ext_bridge.ExtError, ext_config.ExtConfigError) as e:
        raise HTTPException(409, str(e))


def _local(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "بس من نفس الجهاز")


# ── للإضافة (بتوكن) ─────────────────────────────────────────────────────
@router.get("/studio/{filename}/ext/queue", dependencies=[Depends(_need_token)])
def ext_queue(filename: str, x_vp_ext_token: str | None = Header(None)) -> dict:
    import ext_bridge
    _auth(x_vp_ext_token)
    p = _script(filename)
    return {"queue": _e(ext_bridge.build_queue, p), "control": ext_bridge.control(p.stem)}


@router.get("/studio/{filename}/ext/control", dependencies=[Depends(_need_token)])
def ext_get_control(filename: str, x_vp_ext_token: str | None = Header(None)) -> dict:
    import ext_bridge
    _auth(x_vp_ext_token)
    return ext_bridge.control(_script(filename).stem)


@router.get("/studio/{filename}/ext/ref/{shot_id}/{index}", dependencies=[Depends(_need_token)])
def ext_ref(filename: str, shot_id: str, index: int, x_vp_ext_token: str | None = Header(None)):
    import ext_bridge
    _auth(x_vp_ext_token)
    return FileResponse(_e(ext_bridge.ref_path, _script(filename), shot_id, index))


@router.get("/studio/{filename}/ext/tasks", dependencies=[Depends(_need_token)])
def ext_tasks_list(filename: str, kind: str | None = Query(None)) -> dict:
    """مهام نوع واحد (بيحترم control.only). بدون kind ← النوع الحالي بالتحكم."""
    import ext_bridge
    import ext_tasks
    p = _script(filename)
    ctl = ext_bridge.control(p.stem)
    k = kind or ctl.get("kind") or "image"
    return {"kind": k, "tasks": _e(ext_tasks.tasks, p, k), "control": ctl}


@router.get("/studio/{filename}/ext/asset/{task_id}/{index}", dependencies=[Depends(_need_token)])
def ext_asset(filename: str, task_id: str, index: int, kind: str | None = Query(None)):
    """ملف مرجع: صور المراجع للـ image، والصورة النهائية للـ video (index 0). النوع الافتراضي = نوع التحكم الحالي."""
    import ext_bridge
    import ext_tasks
    p = _script(filename)
    k = kind or ext_bridge.control(p.stem).get("kind") or "image"
    return FileResponse(_e(ext_tasks.asset_path, p, k, task_id, index))


@router.post("/studio/{filename}/ext/result", dependencies=[Depends(_need_token)])
async def ext_result(filename: str, file: UploadFile = File(...), task_id: str | None = Form(None),
                     shot_id: str | None = Form(None), site: str = Form(...), kind: str = Form("image"),
                     x_vp_ext_token: str | None = Header(None)) -> dict:
    """نتيجة من الإضافة. task_id هو الأساس، و shot_id توافق قديم (صور) لو task_id غايب."""
    import ext_tasks
    p = _script(filename)
    tid = (task_id or shot_id or "").strip()
    data = await file.read()
    return await run_in_threadpool(_e, ext_tasks.receive, p, kind, tid, data, site, file.filename or "")


@router.post("/studio/{filename}/ext/log", dependencies=[Depends(_need_token)])
def ext_log(filename: str, payload: dict, x_vp_ext_token: str | None = Header(None)) -> dict:
    import ext_bridge
    _auth(x_vp_ext_token)
    ext_bridge.append_log(_script(filename).stem, payload)
    return {"ok": True}


@router.post("/studio/{filename}/ext/stop", dependencies=[Depends(_need_token)])
def ext_stop(filename: str, payload: dict, x_vp_ext_token: str | None = Header(None)) -> dict:
    """الإضافة وقفت عند تحقق/كابتشا/تحذير/دخول/صفحة غريبة. ما في استئناف تلقائي."""
    import ext_bridge
    _auth(x_vp_ext_token)
    return ext_bridge.record_stop(_script(filename).stem, str(payload.get("code") or "unknown"),
                                  str(payload.get("reason") or ""), payload.get("position"))


# ── لواجهة الاستوديو ────────────────────────────────────────────────────
@router.get("/studio/{filename}/ext/status")
def ext_status(filename: str) -> dict:
    import ext_bridge
    return _e(ext_bridge.status, _script(filename))


@router.post("/studio/{filename}/ext/control")
def ext_set_control(filename: str, payload: dict) -> dict:
    import ext_bridge
    return _e(ext_bridge.set_control, _script(filename).stem, payload.get("command"), payload.get("mode"), payload.get("site"),
              payload.get("kind"), payload.get("step_mode"),
              payload["only"] if "only" in payload else ext_bridge.UNSET)


@router.post("/studio/{filename}/ext/requests")
def ext_add_request(filename: str, payload: dict, request: Request) -> dict:
    """طلب آهة أو موسيقى من المالك (بينضاف للطابور وبيرجع للمكتبة غير معتمد)."""
    import ext_tasks
    _local(request)
    p = _script(filename)
    return _e(ext_tasks.add_request, p.stem, payload.get("kind"), payload.get("prompt"), payload.get("name") or "",
              payload.get("mood") or "any", payload.get("seconds"))


@router.delete("/studio/{filename}/ext/requests/{rid}")
def ext_del_request(filename: str, rid: str, request: Request) -> dict:
    import ext_tasks
    _local(request)
    _e(ext_tasks.delete_request, _script(filename).stem, rid)
    return {"ok": True}


@router.post("/studio/{filename}/ext/retry")
def ext_retry(filename: str, payload: dict, request: Request) -> dict:
    """إعادة لقطة/مشهد/طلب: مهمة جديدة (want=1) وبرومبت بديل اختياري."""
    import ext_tasks
    _local(request)
    return {"task": _e(ext_tasks.retry, _script(filename), payload.get("task_id"), payload.get("kind"), payload.get("prompt"))}


# ── إعداد المحوّلات والإصدار والفحص الذاتي ───────────────────────────────
@router.get("/ext/config", dependencies=[Depends(_need_token)])
def ext_get_config() -> dict:
    import ext_config
    return ext_config.load()


@router.put("/ext/config")
def ext_put_config(payload: dict, request: Request) -> dict:
    import ext_config
    _local(request)
    return _e(ext_config.save_patch, payload)


@router.get("/ext/version", dependencies=[Depends(_need_token)])
def ext_version() -> dict:
    import ext_bridge
    return {"latest": _e(ext_bridge.extension_version), "download_url": "/api/ext/download"}


@router.get("/ext/download")
def ext_download(request: Request) -> Response:
    import ext_bridge
    _local(request)
    name, data = _e(ext_bridge.build_zip)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/ext/selftest", dependencies=[Depends(_need_token)])
def ext_post_selftest(payload: dict) -> dict:
    import ext_config
    return _e(ext_config.record_selftest, payload.get("site"), payload.get("kind"), payload.get("ok"),
              payload.get("adapter_version"), payload.get("missing") if payload.get("missing") is not None else [])


@router.post("/ext/diag", dependencies=[Depends(_need_token)])
def ext_post_diag(payload: dict) -> dict:
    """تقرير بنية الصفحة من الإضافة عند وقوف unknown_page/timeout/download_failed (بدون محتوى)."""
    import ext_config
    return _e(ext_config.record_diag, payload.get("site"), payload.get("kind"), payload.get("code"), payload.get("reason"),
              payload.get("step"), payload.get("diag"))


@router.get("/ext/diag")
def ext_get_diag(request: Request, limit: int = Query(10)) -> dict:
    import ext_config
    _local(request)
    return {"items": ext_config.diag_results(limit)}


@router.get("/ext/selftest")
def ext_get_selftest(request: Request) -> dict:
    import ext_config
    _local(request)
    return {"results": ext_config.selftest_results()}


@router.get("/ext/token")
def ext_token(request: Request) -> dict:
    """توكن الاقتران — للصقه بخيارات الإضافة. بس من نفس الجهاز."""
    import ext_bridge
    _local(request)
    return {"token": ext_bridge.token()}


@router.post("/ext/token/rotate")
def ext_rotate(request: Request) -> dict:
    import ext_bridge
    _local(request)
    return {"token": ext_bridge.rotate_token()}
