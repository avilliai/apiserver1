"""
plugins/openai_proxy_v3/router.py

Proxies requests to the Pegasus upstream (localhost:8011).

外部模型名带 "Pegasus/" 前缀（例如 "Pegasus/gemini-pro"）。
转发给 8011 之前，前缀会被自动剥离，上游收到的是裸名（例如 "gemini-pro"）。

暴露端点：
  POST /v3/chat/completions
  POST /v3/completions
  POST /v3/embeddings
  GET  /v3/models

v1 端点同样可路由到本插件（由 openai_proxy/router.py 中的 _resolve() 负责），
配额独立计入 "openai_proxy_v3" bucket。
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.openai_proxy_v3 import config
import logging

logger = logging.getLogger(__name__)

PLUGIN_NAME = "openai_proxy_v3"

router = APIRouter()


def _strip_prefix(model: str) -> str:
    """
    将带前缀的模型名还原为上游裸名。
    "Pegasus/gemini-pro" -> "gemini-pro"
    已经是裸名时原样返回（防御性处理）。
    """
    if model.startswith(config.MODEL_PREFIX):
        return model[len(config.MODEL_PREFIX):]
    return model


async def _proxy_request(
    incoming_path: str,   # 审计日志路径，例如 /v3/chat/completions
    upstream_path: str,   # 实际转发路径，例如 /v1/chat/completions
    body: dict,
    user: User,
    db: AsyncSession,
):
    model_with_prefix = body.get("model", "")
    if not model_with_prefix:
        raise HTTPException(status_code=400, detail="'model' field is required")

    # 剥离前缀，构造转发给 8011 的 body
    bare_model = _strip_prefix(model_with_prefix)
    upstream_body = {**body, "model": bare_model}

    upstream_url = f"{config.UPSTREAM_BASE}{upstream_path}"
    is_stream = body.get("stream", False)

    headers = {
        "Authorization": f"Bearer {config.UPSTREAM_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info(
        f"[v3] {incoming_path} -> {upstream_url} "
        f"(model={model_with_prefix} -> {bare_model}, stream={is_stream})"
    )

    if is_stream:
        async def generate():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream(
                        "POST", upstream_url, json=upstream_body, headers=headers
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            yield f"{line.strip()}\n\n"
                except Exception as e:
                    logger.error(f"[v3][STREAM ERROR] {e}")
                    raise

        return StreamingResponse(generate(), media_type="text/event-stream")

    else:
        async with httpx.AsyncClient(timeout=None) as client:
            resp = await client.post(upstream_url, json=upstream_body, headers=headers)

        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"error": resp.text}

        usage = resp_json.get("usage", {}) if isinstance(resp_json, dict) else {}
        await log_request(db, user, PLUGIN_NAME, incoming_path, resp.status_code, {
            "model": model_with_prefix,   # 日志记录带前缀的名字，便于追溯
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "stream": False,
        })

        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp_json)

        return resp_json


# ── 公共代理入口（供 openai_proxy/router.py 的 _resolve 复用）──────────────────
# openai_proxy/router.py 在识别到 Pegasus/ 前缀后会直接 await 这个函数，
# 无需重复扣 v3 配额（配额已在 _proxy_request 外层由调用方处理）。
async def proxy_v3_request(
    path: str,
    body: dict,
    user: User,
    db: AsyncSession,
):
    """
    供 openai_proxy/router.py 调用的统一入口。
    path 是上游路径（例如 /v1/chat/completions）。
    配额检查由调用方（openai_proxy/router._proxy_request）负责。
    """
    return await _proxy_request(path, path, body, user, db)


# ---------- v3 专属端点 ----------
# 配额在 Depends 里检查，_proxy_request 内部不再重复检查。

@router.post("/v3/chat/completions")
async def chat_completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v3/chat/completions", "/v1/chat/completions", body, user, db)


@router.post("/v3/completions")
async def completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v3/completions", "/v1/completions", body, user, db)


@router.post("/v3/embeddings")
async def embeddings(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v3/embeddings", "/v1/embeddings", body, user, db)


@router.get("/v3/models")
async def list_models(user: User = Depends(get_current_user)):
    """返回本插件支持的模型列表（带 Pegasus/ 前缀）。"""
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": 1700000000,
                "owned_by": "Pegasus",
            }
            for model_id in config.SUPPORTED_MODELS
        ],
    }