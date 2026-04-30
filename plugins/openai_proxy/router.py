"""
plugins/openai_proxy/router.py

Proxies OpenAI-compatible requests to different upstreams based on model name.
Supports both streaming and non-streaming responses.

配额逻辑：
- 普通模型（v1）：从 "openai_proxy" bucket 扣除，转发到 UPSTREAM_ROUTES
- V2 模型（config.V2_MODELS 精确匹配）：从 "openai_proxy_v2" bucket 扣除，
  转发到 V2_UPSTREAM_BASE，请求路径保持 /v1/...（上游接受标准 OpenAI 格式）

quota.py 未做任何修改，通过直接 await 调用 require_quota() 返回的内部
_check 函数实现运行时动态切换 plugin_name。
"""
import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.openai_proxy import config
from plugins.openai_proxy_v2 import config as v2_config
import logging

logger = logging.getLogger(__name__)

PLUGIN_PREFIX = ""
PLUGIN_NAME = "openai_proxy"
V2_PLUGIN_NAME = "openai_proxy_v2"
_V2_MODELS: set[str] = set(v2_config.SUPPORTED_MODELS)

router = APIRouter()


def _resolve(model: str) -> tuple[str, str, str]:
    """
    返回 (upstream_base_url, api_key, plugin_name)。
    V2 模型走独立上游和独立配额 bucket；其余走原有路由表。
    """
    if model.lower() in _V2_MODELS:
        return v2_config.UPSTREAM_BASE, v2_config.UPSTREAM_API_KEY, V2_PLUGIN_NAME

    model_lower = model.lower()
    for prefix, url in config.UPSTREAM_ROUTES.items():
        if model_lower.startswith(prefix):
            return url, config.UPSTREAM_API_KEY, PLUGIN_NAME

    # 默认 fallback
    return list(config.UPSTREAM_ROUTES.values())[-1], config.UPSTREAM_API_KEY, PLUGIN_NAME


async def _proxy_request(
    path: str,
    body: dict,
    user: User,
    db: AsyncSession,
):
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="'model' field is required")

    upstream_base, api_key, effective_plugin = _resolve(model)
    upstream_url = f"{upstream_base}{path}"
    is_stream = body.get("stream", False)

    # ── 动态配额检查 ──────────────────────────────────────────────────────────
    # require_quota(name) 返回一个普通 async 函数，直接 await 即可；
    # 它内部会用 with_for_update() 行锁保证原子性，和走 FastAPI Depends 完全等价。
    await require_quota(effective_plugin)(user=user, db=db)
    # ─────────────────────────────────────────────────────────────────────────

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        f"Proxying '{model}' -> {upstream_url} "
        f"(plugin={effective_plugin}, stream={is_stream})"
    )

    if is_stream:
        async def generate():
            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    async with client.stream(
                        "POST", upstream_url, json=body, headers=headers
                    ) as resp:
                        logger.info(f"[UPSTREAM HEADERS] {resp.headers}")
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            yield f"{line.strip()}\n\n"
                except Exception as e:
                    logger.error(f"[STREAM ERROR] {e}")
                    raise

        return StreamingResponse(generate(), media_type="text/event-stream")

    else:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(upstream_url, json=body, headers=headers)

        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"error": resp.text}

        usage = resp_json.get("usage", {}) if isinstance(resp_json, dict) else {}
        await log_request(db, user, effective_plugin, path, resp.status_code, {
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "stream": False,
        })

        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp_json)

        return resp_json


# ---------- Endpoints ----------
# 注意：quota 检查已移入 _proxy_request，这里不再挂 _quota=Depends(require_quota(...))，
# 否则会对同一请求扣两次 v1 配额。

@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    return await _proxy_request("/v1/chat/completions", body, user, db)


@router.post("/v1/completions")
async def completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    return await _proxy_request("/v1/completions", body, user, db)


@router.post("/v1/embeddings")
async def embeddings(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    return await _proxy_request("/v1/embeddings", body, user, db)


@router.get("/v1/models")
async def list_models(user: User = Depends(get_current_user)):
    """Fetches model lists from all upstreams in parallel and merges them."""

    async def fetch_models(base_url: str, api_key: str) -> list:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{base_url}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if resp.status_code == 200:
                return resp.json().get("data", [])
        except Exception as e:
            logger.warning(f"Failed to fetch models from {base_url}: {e}")
        return []

    # 对每个不同的 upstream base_url 只请求一次
    unique_upstreams = {url: config.UPSTREAM_API_KEY for url in config.UPSTREAM_ROUTES.values()}
    unique_upstreams[v2_config.UPSTREAM_BASE] = v2_config.UPSTREAM_API_KEY

    results = await asyncio.gather(
        *[fetch_models(url, key) for url, key in unique_upstreams.items()]
    )

    # 合并去重，以 id 为唯一键
    merged: dict[str, dict] = {}
    for models in results:
        for m in models:
            if "id" in m:
                merged[m["id"]] = m

    return {"object": "list", "data": list(merged.values())}