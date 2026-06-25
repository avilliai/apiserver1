import httpx
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.gptimage2 import config

PLUGIN_PREFIX = "/v1"
PLUGIN_NAME = "gptimage2"

BACKEND_BASE = config.BACKEND_BASE
BACKEND_KEY  = config.BACKEND_KEY

# 1K 分辨率走这个更快的本地服务
BACKEND_BASE_1K = "http://localhost:8019"

router = APIRouter()

_headers = {
    "Authorization": f"Bearer {BACKEND_KEY}",
}


def _pick_base(resolution: str | None) -> str:
    """根据 resolution 选择后端地址。"""
    if resolution and resolution.upper() == "1K":
        return BACKEND_BASE_1K
    return BACKEND_BASE


# ── 共用转发助手 ────────────────────────────────────────────────

async def _forward_json(path: str, body: dict) -> dict:
    """转发 JSON 请求到后端，返回解析后的 JSON。"""
    base = _pick_base(body.get("resolution"))
    async with httpx.AsyncClient(timeout=None) as client:
        resp = await client.post(
            f"{base}{path}",
            json=body,
            headers=_headers,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def _forward_multipart(path: str, request: Request) -> dict:
    """
    原样透传 multipart/form-data 到后端。
    把客户端上传的文件流全部读入内存后重新拼装 multipart。
    """
    form = await request.form()

    files = []   # [(field_name, (filename, bytes, content_type)), ...]
    data  = {}   # 普通文本字段

    for key, value in form.multi_items():
        if hasattr(value, "read"):          # UploadFile
            raw = await value.read()
            files.append((key, (value.filename or key, raw, value.content_type or "image/png")))
        else:
            data[key] = value

    base = _pick_base(data.get("resolution"))

    async with httpx.AsyncClient(timeout=None) as client:
        resp = await client.post(
            f"{base}{path}",
            files=files if files else None,
            data=data,
            headers=_headers,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# ── /v1/images/generations ──────────────────────────────────────

@router.post("/images/generations")
async def images_generations(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    result = await _forward_json("/images/generations", body)
    await log_request(db, user, PLUGIN_NAME, "/images/generations", 200)
    return JSONResponse(content=result)


# ── /v1/images/edits ────────────────────────────────────────────

@router.post("/images/edits")
async def images_edits(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        result = await _forward_multipart("/images/edits", request)
    elif "application/json" in content_type:
        body = await request.json()
        result = await _forward_json("/images/edits", body)
    else:
        raise HTTPException(status_code=415, detail="需要 multipart/form-data 或 application/json")

    await log_request(db, user, PLUGIN_NAME, "/images/edits", 200)
    return JSONResponse(content=result)