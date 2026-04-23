from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request

import httpx

PLUGIN_PREFIX = ""
PLUGIN_NAME = "gptimage2"

router = APIRouter()

UPSTREAM_BASE = "http://127.0.0.1:8009"


@router.post("/v1/images/generations")
async def proxy_draw(
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    try:
        async with httpx.AsyncClient(timeout=240) as client:
            resp = await client.post(
                f"{UPSTREAM_BASE}/v1/images/generations",
                json=payload
            )

        # 透传状态码 + 内容
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail=resp.text
            )

        data = resp.json()

        # 记录日志
        await log_request(db, user, PLUGIN_NAME, "/v1/images/generations", 200)

        return data

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"上游请求失败: {str(e)}")


# =========================
# 2️⃣ 代理配额接口
# =========================
@router.get("/api/quota")
async def proxy_quota(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{UPSTREAM_BASE}/api/quota")

        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail=resp.text
            )

        data = resp.json()

        await log_request(db, user, PLUGIN_NAME, "/api/quota", 200)

        return data

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# 3️⃣ 代理 admin token 接口（可选）
# =========================
@router.post("/admin/tokens/add")
async def proxy_add_tokens(
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{UPSTREAM_BASE}/admin/tokens/add",
                json=payload
            )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail=resp.text
            )

        data = resp.json()

        await log_request(db, user, PLUGIN_NAME, "/admin/tokens/add", 200)

        return data

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=str(e))