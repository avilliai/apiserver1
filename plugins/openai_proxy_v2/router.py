"""
plugins/openai_proxy_v2/router.py

Proxies OpenAI-compatible requests for V2 to http://localhost:8007/v1
"""
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.openai_proxy_v2 import config  # 引入本插件自己的 config

logger = logging.getLogger(__name__)

PLUGIN_PREFIX = ""
router = APIRouter()

PLUGIN_NAME = "openai_proxy_v2"


async def _proxy_request(
        incoming_path: str,  # 记录在日志里的路径，如 "/v2/chat/completions"
        upstream_path: str,  # 发给上游的相对路径，如 "/chat/completions"
        body: dict,
        user: User,
        db: AsyncSession,
):
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="'model' field is required")

    # 组合最终的转发 URL -> http://localhost:8007/v1 + /chat/completions
    upstream_url = f"{config.UPSTREAM_URL}{upstream_path}"
    is_stream = body.get("stream", False)

    headers = {
        "Authorization": f"Bearer {config.UPSTREAM_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info(f"Proxying V2 request for model '{model}' to {upstream_url} (stream={is_stream})")

    async with httpx.AsyncClient(timeout=120.0) as client:
        if is_stream:
            async def generate():
                async with httpx.AsyncClient(timeout=120.0) as client:
                    try:
                        async with client.stream(
                                "POST", upstream_url, json=body, headers=headers
                        ) as resp:
                            logger.info(f"🔥 [UPSTREAM HEADERS V2] {resp.headers}")

                            async for line in resp.aiter_lines():
                                if not line:
                                    continue
                                data = line.strip()
                                yield f"{data}\n\n"

                    except Exception as e:
                        logger.error("❌ [STREAM ERROR V2]", exc_info=True)
                        raise

            return StreamingResponse(generate(), media_type="text/event-stream")

        else:
            resp = await client.post(upstream_url, json=body, headers=headers)
            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {"error": resp.text}

            usage = resp_json.get("usage", {}) if isinstance(resp_json, dict) else {}
            # 日志记录请求
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

@router.post("/v2/chat/completions")
async def chat_completions(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v2/chat/completions", "/chat/completions", body, user, db)


@router.post("/v2/completions")
async def completions(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v2/completions", "/completions", body, user, db)


@router.post("/v2/embeddings")
async def embeddings(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v2/embeddings", "/embeddings", body, user, db)


@router.get("/v2/models")
async def list_models(user: User = Depends(get_current_user)):
    """
    直接代理转发给 http://localhost:8007/v1/models 获取模型列表
    不扣除配额
    """
    upstream_url = f"{config.UPSTREAM_URL}/models"
    headers = {
        "Authorization": f"Bearer {config.UPSTREAM_API_KEY}",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(upstream_url, headers=headers)
        except Exception as e:
            logger.error("❌[V2 MODELS ERROR]", exc_info=True)
            raise HTTPException(status_code=502, detail="Bad Gateway: Unable to reach upstream models endpoint")

        try:
            resp_json = resp.json()
        except Exception:
            raise HTTPException(status_code=502, detail="Bad Gateway: Upstream returned invalid JSON")

        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp_json)

        return resp_json