"""
plugins/openai_proxy_v0/router.py
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.openai_proxy_v0 import config
import logging

logger = logging.getLogger(__name__)

# 建议设为空，在下面的路由里手动写 /v0，或者设为 /v0，路由里不写 /v0。
# 为了和你提供的第一个旧版 router 逻辑保持一致，我们这里设为 ""
PLUGIN_PREFIX = ""
PLUGIN_NAME = "openai_proxy_v0"

router = APIRouter()

async def _proxy_request(
    incoming_path: str, # 用于审计日志的路径 (例如 /v0/chat/completions)
    upstream_path: str, # 实际转发给上游的路径 (例如 /v1/chat/completions)
    body: dict,
    user: User,
    db: AsyncSession,
):
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="'model' field is required")

    upstream_url = f"{config.UPSTREAM_BASE}{upstream_path}"
    is_stream = body.get("stream", False)

    headers = {
        "Authorization": f"Bearer {config.UPSTREAM_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info(f"[v0] Proxying {incoming_path} -> {upstream_url} (model={model})")

    if is_stream:
        async def generate():
            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    async with client.stream(
                        "POST", upstream_url, json=body, headers=headers
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            yield f"{line.strip()}\n\n"
                except Exception as e:
                    logger.error(f"[v0][STREAM ERROR] {e}")
                    raise
        return StreamingResponse(generate(), media_type="text/event-stream")

    else:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(upstream_url, json=body, headers=headers)

        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"error": resp.text}

        usage_raw = resp_json.get("usage") if isinstance(resp_json, dict) else {}

        # 2. 核心修复：如果 usage_raw 是 None，则强制变为 {}
        usage = usage_raw or {}

        await log_request(db, user, PLUGIN_NAME, incoming_path, resp.status_code, {
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "stream": False,
        })

        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp_json)

        return resp_json


# ---------- Endpoints ----------

@router.post("/v0/chat/completions")
async def chat_completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    # 转发时将 /v0 还原为 /v1
    return await _proxy_request("/v0/chat/completions", "/v1/chat/completions", body, user, db)


@router.post("/v0/completions")
async def completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v0/completions", "/v1/completions", body, user, db)


@router.post("/v0/embeddings")
async def embeddings(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v0/embeddings", "/v1/embeddings", body, user, db)


@router.get("/v0/models")
async def list_models(user: User = Depends(get_current_user)):
    """获取上游真实模型列表"""
    upstream_models_url = f"{config.UPSTREAM_BASE}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                upstream_models_url,
                headers={"Authorization": f"Bearer {config.UPSTREAM_API_KEY}"},
            )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"[v0] Failed to fetch upstream models: {e}")

    return {"object": "list", "data": []}